"""Placing venues by address: the geocoder, /api/geocode, and /api/relocate-venue.

Regression: a venue added from the form was pinned wherever the map happened to be centred, not at the address the
visitor typed (a pub in Davos showed up in the middle of Switzerland).
"""

import json
import os
import unittest
from unittest import mock

import app_server
import geocode
from tests.helpers import QuietHandler, serve, stop
from tests.test_api import ApiTestCase

REAL_COMBINED = app_server.get_all_combined_venues  # ApiTestCase replaces it with a stub while a test runs

DAVOS = {"lat": "46.80282", "lon": "9.83572", "display_name": "Promenade 119, 7270 Davos, Graubünden, Schweiz"}


def nominatim(answers, hits):
    """A fake Nominatim: ``answers`` maps a lower-cased query to the JSON list it answers with (else an empty list)."""
    from urllib.parse import parse_qs, urlparse

    class H(QuietHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            hits.append({"q": qs.get("q", [""])[0], "countrycodes": qs.get("countrycodes", [""])[0], "ua": self.headers.get("User-Agent")})
            status, body = answers.get(qs.get("q", [""])[0].lower(), (200, []))
            payload = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return H


class GeocodeTests(unittest.TestCase):
    def setUp(self):
        geocode.reset_cache()
        self.hits = []
        self.answers = {"promenade 119, 7270 davos": (200, [DAVOS])}
        self.server, url = serve(nominatim(self.answers, self.hits))
        self.addCleanup(stop, self.server)
        patch = mock.patch.dict(os.environ, {"GEOCODE_URL": url})
        patch.start()
        self.addCleanup(patch.stop)

    def test_finds_an_address_and_asks_politely_and_only_for_switzerland(self):
        r = geocode.geocode("Promenade 119, 7270 Davos")
        self.assertEqual((r["lat"], r["lng"]), (46.80282, 9.83572))
        self.assertIn("Davos", r["label"])
        self.assertEqual(self.hits[0]["countrycodes"], "ch")
        self.assertIn("GuinnessGuide", self.hits[0]["ua"], "Nominatim requires an identifying User-Agent")

    def test_repeated_addresses_are_served_from_the_cache(self):
        geocode.geocode("Promenade 119, 7270 Davos")
        geocode.geocode("  promenade 119,   7270 DAVOS ")
        self.assertEqual(len(self.hits), 1)

    def test_unknown_address_is_none_and_the_miss_is_cached_too(self):
        self.assertIsNone(geocode.geocode("Nowhere street 1, 9999 Nowhere"))
        self.assertIsNone(geocode.geocode("Nowhere street 1, 9999 Nowhere"))
        self.assertEqual(len(self.hits), 1)

    def test_a_result_outside_switzerland_is_not_accepted(self):
        self.answers["hyde park, london"] = (200, [{"lat": "51.5", "lon": "-0.16", "display_name": "Hyde Park"}])
        self.assertIsNone(geocode.geocode("Hyde Park, London"))

    def test_garbage_and_errors_say_unavailable_rather_than_not_found(self):
        for body in ((200, b"<html>busy</html>"), (503, b"")):
            geocode.reset_cache()
            self.answers["davos"] = body
            with self.subTest(body=body), self.assertRaises(geocode.GeocodeUnavailable):
                geocode.geocode("Davos")

    def test_malformed_results_are_not_found(self):
        for bad in ([{"lat": "x", "lon": "y"}], [{}], {"error": "x"}, [None]):
            geocode.reset_cache()
            self.answers["davos"] = (200, bad)
            with self.subTest(bad=bad):
                self.assertIsNone(geocode.geocode("Davos"))

    def test_too_short_queries_are_not_sent(self):
        self.assertIsNone(geocode.geocode("  "))
        self.assertIsNone(geocode.geocode("ab"))
        self.assertEqual(self.hits, [])


class GeocodeApiTests(ApiTestCase):
    def setUp(self):
        geocode.reset_cache()
        self.hits = []
        self.answers = {"promenade 119, 7270 davos": (200, [DAVOS])}
        self.geo, url = serve(nominatim(self.answers, self.hits))
        self.addCleanup(stop, self.geo)
        self.env = {"GEOCODE_URL": url}
        super().setUp()

    def test_geocode_endpoint(self):
        status, data, _ = self.call("GET", "/api/geocode?q=Promenade+119%2C+7270+Davos")
        self.assertEqual((status, data["found"], data["lat"], data["lng"]), (200, True, 46.80282, 9.83572))
        self.assertEqual(self.call("GET", "/api/geocode?q=Nowhere+street+1%2C+9999+Nowhere")[1], {"found": False})
        self.assertEqual(self.call("GET", "/api/geocode")[1], {"found": False})

    def test_geocode_endpoint_reports_a_busy_lookup_as_503(self):
        self.answers["davos"] = (503, b"")
        status, data, _ = self.call("GET", "/api/geocode?q=Davos")
        self.assertEqual(status, 503)
        self.assertIn("busy", data["error"])

    def add_venue(self, **kw):
        body = {"name": "The Green Wildman", "lat": 46.8182, "lng": 8.2275, "category": "pub", "city": "zurich",
                "servingFormat": "draught", "address": "Promenade 119, 7270 Davos", **kw}
        status, data, _ = self.post("/api/add-venue", body)
        self.assertEqual(status, 200, data)
        return data["venue"]

    def test_regression_relocate_moves_a_venue_to_its_address(self):
        """The venue was added with the map's centre as its position; its address says Davos."""
        venue = self.add_venue()  # lat/lng = the middle of Switzerland, as the old form sent
        status, data, _ = self.post("/api/relocate-venue", {"venueId": venue["id"]})
        self.assertEqual(status, 200, data)
        self.assertEqual((data["venue"]["lat"], data["venue"]["lng"]), (46.80282, 9.83572))
        self.assertGreater(data["movedKm"], 20)
        self.assertEqual(self.backend.load()["venueLocations"][venue["id"]], {"lat": 46.80282, "lng": 9.83572})

    def test_a_moved_venue_is_served_from_its_new_position(self):
        venue = self.add_venue()
        self.post("/api/relocate-venue", {"venueId": venue["id"]})
        store = self.backend.load()
        # (the API tests stub the venue list; this is the real one)
        served = {v["id"]: v for v in REAL_COMBINED(store)}[venue["id"]]
        self.assertEqual((served["lat"], served["lng"]), (46.80282, 9.83572))
        self.assertEqual(store["customVenues"][0]["lat"], 46.8182, "the stored record is untouched")

    def test_relocate_only_uses_the_stored_address_never_visitor_coordinates(self):
        venue = self.add_venue()
        self.post("/api/relocate-venue", {"venueId": venue["id"], "lat": 10, "lng": 10, "address": "Hyde Park, London"})
        self.assertEqual(self.backend.load()["venueLocations"][venue["id"]], {"lat": 46.80282, "lng": 9.83572})

    def test_relocate_refuses_what_it_cannot_do(self):
        no_address = self.add_venue(address="")
        for body, status, text in [
            ({"venueId": "zh-kennedys"}, 404, "added by visitors"),  # bundled venues are never moved
            ({"venueId": "custom-0"}, 404, "added by visitors"),
            ({"venueId": no_address["id"]}, 400, "no street address"),
            ({}, 400, "venueId"),
        ]:
            with self.subTest(body=body):
                s, d, _ = self.post("/api/relocate-venue", body)
                self.assertEqual(s, status, d)
                self.assertIn(text, d["error"])

    def test_relocate_says_so_when_the_address_is_not_found(self):
        venue = self.add_venue(address="Nowhere street 1, 9999 Nowhere")
        s, d, _ = self.post("/api/relocate-venue", {"venueId": venue["id"]})
        self.assertEqual(s, 400)
        self.assertIn("Could not find", d["error"])
        self.assertNotIn(venue["id"], self.backend.load()["venueLocations"])


if __name__ == "__main__":
    unittest.main()

"""The one-off Google Places discovery run: it spends within its cap, stops on a refusal, and writes only place IDs plus text from
venues' own websites (Google's terms allow storing place IDs, not names, ratings, reviews or website addresses)."""

import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

import app_server as app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("discover_google_places", os.path.join(ROOT, "scripts", "discover_google_places.py"))
disc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(disc)

KNOWN = [
    {"id": "ch-node-1", "name": "The Trinity Irish Pub", "lat": 46.00688, "lng": 8.96029, "menuCheck": {"checked": False}},
    {"id": "zh-kennedys", "name": "Kennedy's Irish Pub", "lat": 47.3768, "lng": 8.5326, "menuCheck": {"checked": True}},
]


def place(pid, name, lat, lng, site=None):
    return {"id": pid, "displayName": {"text": name}, "location": {"latitude": lat, "longitude": lng}, **({"websiteUri": site} if site else {})}


class FakeGoogle:
    """Answers every search with the same page (and a second page on request), recording each request."""

    def __init__(self, places, pages=1):
        self.places, self.pages, self.requests = places, pages, []

    def __call__(self, url, body, headers):
        self.requests.append((url, body, headers))
        n = sum(1 for r in self.requests if r[1].get("textQuery") == body.get("textQuery") and r[1]["locationBias"] == body["locationBias"])
        return {"places": self.places, **({"nextPageToken": f"t{n}"} if n < self.pages else {})}


def scan_says(found):
    return lambda venue: {"scanned": True, "reachable": True, "foundOnMenu": found, "typesFound": ["Guinness Draught (On Tap)"], "extractedPrice": "CHF 9.00", "snippets": ["Guinness vom Fass"]} if found else {"scanned": True, "reachable": True, "foundOnMenu": False}


class RunTests(unittest.TestCase):
    def test_a_google_place_next_to_a_known_venue_gives_its_place_id_and_nothing_else(self):
        g = FakeGoogle([place("ChIJtrinity00001", "Trinity Irish Pub", 46.00690, 8.96030)])
        doc = disc.run("KEY", KNOWN, max_requests=5, post=g, scan=scan_says(False))
        self.assertEqual(doc["placeIds"], {"ch-node-1": "ChIJtrinity00001"})
        self.assertEqual(doc["findings"], [])
        text = json.dumps(doc)
        for secret in ("Trinity Irish Pub", "46.0069", "KEY"):
            self.assertNotIn(secret, text)

    def test_the_request_cap_is_hard(self):
        g = FakeGoogle([place("ChIJxxxxxxxxxx01", "Somewhere", 47.0, 8.0)], pages=3)
        doc = disc.run("KEY", KNOWN, max_requests=7, post=g, scan=scan_says(False))
        self.assertEqual(len(g.requests), 7)
        self.assertEqual(doc["requestsUsed"], 7)
        self.assertEqual(doc["stopped"], "request cap reached")

    def test_the_first_refusal_stops_the_run(self):
        calls = []

        def refuse(url, body, headers):
            calls.append(1)
            raise disc.QuotaOrPermission("Google answered HTTP 429")

        doc = disc.run("KEY", KNOWN, max_requests=50, post=refuse, scan=scan_says(False))
        self.assertEqual(len(calls), 1)
        self.assertEqual(doc["stopped"], "Google answered HTTP 429")

    def test_a_venue_website_that_names_guinness_becomes_a_finding_without_google_details(self):
        g = FakeGoogle([place("ChIJnewplace00001", "Brand New Pub", 47.5, 9.0, "https://newpub.example")])
        doc = disc.run("KEY", KNOWN, max_requests=3, post=g, scan=scan_says(True))
        self.assertEqual(len(doc["findings"]), 1)
        f = doc["findings"][0]
        self.assertEqual((f["placeId"], f["venueId"], f["extractedPrice"], f["snippets"]), ("ChIJnewplace00001", None, "CHF 9.00", ["Guinness vom Fass"]))
        text = json.dumps(doc)
        for secret in ("Brand New Pub", "newpub.example", "47.5"):
            self.assertNotIn(secret, text)

    def test_a_directory_page_google_offers_is_not_read_and_an_already_checked_venue_is_not_read_again(self):
        read = []
        g = FakeGoogle([place("ChIJdirectory0001", "Listed Pub", 47.6, 9.1, "https://www.tripadvisor.ch/x"), place("ChIJkennedys00001", "Kennedys Irish Pub", 47.3768, 8.5326, "https://www.kennedys.ch")])
        doc = disc.run("KEY", KNOWN, max_requests=2, post=g, scan=lambda v: read.append(v) or scan_says(True)(v))
        self.assertEqual(read, [])
        self.assertEqual(doc["placeIds"], {"zh-kennedys": "ChIJkennedys00001"})

    def test_requests_ask_only_for_the_fields_needed_and_send_the_key_in_a_header(self):
        g = FakeGoogle([])
        disc.run("KEY", KNOWN, max_requests=1, post=g, scan=scan_says(False))
        url, body, headers = g.requests[0]
        self.assertTrue(url.startswith("https://places.googleapis.com/"))
        self.assertEqual(headers["X-Goog-Api-Key"], "KEY")
        self.assertNotIn("KEY", json.dumps(body))
        self.assertNotIn("reviews", headers["X-Goog-FieldMask"])
        self.assertEqual(body["regionCode"], "CH")

    def test_the_plan_is_bounded_and_the_dry_run_calls_nothing(self):
        self.assertLessEqual(len(disc.LOCATIONS) * len(disc.QUERIES) * disc.MAX_PAGES, 240 * 2)
        with mock.patch.object(disc, "http_post", side_effect=AssertionError("no network in a dry run")):
            self.assertEqual(disc.main(["--dry-run"]), 0)

    def test_without_a_key_it_says_what_to_do_and_calls_nothing(self):
        with mock.patch.dict(os.environ, {"GOOGLE_PLACES_API_KEY": ""}), mock.patch.object(disc, "http_post", side_effect=AssertionError("no network")):
            self.assertEqual(disc.main([]), 2)

    def test_earlier_place_ids_are_kept_when_a_run_adds_more(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"placeIds": {"old-venue": "ChIJold000000001"}}, f)
        try:
            doc = disc.merge_with_existing({"placeIds": {"new-venue": "ChIJnew000000001"}}, path=f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(doc["placeIds"], {"new-venue": "ChIJnew000000001", "old-venue": "ChIJold000000001"})


class AppTests(unittest.TestCase):
    def test_a_known_place_id_makes_the_maps_link_open_that_exact_place(self):
        with mock.patch.object(app, "load_google_place_ids", return_value={"zh-kennedys": "ChIJkennedys00001"}):
            v = next(x for x in app.get_all_combined_venues({}) if x["id"] == "zh-kennedys")
        self.assertEqual(v["googlePlaceId"], "ChIJkennedys00001")
        self.assertIn("query_place_id=ChIJkennedys00001", v["googleMapsUri"])

    def test_venues_without_a_place_id_keep_the_search_link(self):
        with mock.patch.object(app, "load_google_place_ids", return_value={}):
            v = next(x for x in app.get_all_combined_venues({}) if x["id"] == "zh-kennedys")
        self.assertNotIn("googlePlaceId", v)
        self.assertNotIn("query_place_id", v["googleMapsUri"])

    def test_a_malformed_place_id_file_is_ignored(self):
        for content in ('{"placeIds": ["x"]}', '{"placeIds": {"a": "short"}}', "not json"):
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                f.write(content)
            try:
                with mock.patch.object(app, "GOOGLE_PLACE_IDS_PATH", f.name):
                    self.assertEqual(app.load_google_place_ids(), {}, content)
            finally:
                os.unlink(f.name)

    def test_the_place_id_file_is_deployed_and_the_workflow_cannot_open_a_pr_or_push_to_main(self):
        with open(os.path.join(ROOT, "vercel.json"), encoding="utf-8") as f:
            self.assertIn("server/data/*.json", f.read(), "google_place_ids.json is bundled by the data glob")
        with open(os.path.join(ROOT, ".github", "workflows", "google-discovery.yml"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("workflow_dispatch", text)
        self.assertNotIn("schedule:", text, "a paid run must never be automatic")
        self.assertNotIn("gh pr create", text)
        self.assertNotIn("git push origin main", text)
        self.assertIn("secrets.GOOGLE_PLACES_API_KEY", text)
        self.assertLess(text.index("Check the result before publishing it"), text.index("git push origin"))


if __name__ == "__main__":
    unittest.main()

"""Tests for the app's core behaviour: Guinness status scoring, venue enrichment/merging, the Google
Places and OpenStreetMap mappings, bundled-data integrity and the HTTP routes. No network is used:
Google / Overpass are replaced by fakes that return realistic response shapes."""

import io
import json
import os
import re
import unittest
from unittest import mock

import app_server as app
import guard
import overpass
from tests.test_api import ApiTestCase

NO_STORE = {"menuScans": {}, "crowdReports": {}}


def venue(**over):
    base = {"id": "v1", "name": "Pub", "category": "restaurant", "menuCheck": {}, "crowdCheck": {}, "reviewCheck": {}}
    for key in ("menuCheck", "crowdCheck", "reviewCheck"):
        base[key] = {**base[key], **over.pop(key, {})}
    return {**base, **over}


class ComputeGuinnessStatusTests(unittest.TestCase):
    def status(self, **kw):
        return app.compute_guinness_status(venue(**kw))

    def test_menu_mention_means_confirmed_but_not_necessarily_on_tap(self):
        r = self.status(menuCheck={"checked": True, "foundOnMenu": True})
        self.assertEqual((r["status"], r["servingFormat"]), ("confirmed_draught", "unknown"))
        self.assertEqual((r["statusLabel"], r["reason"]), ("Confirmed", "Its website mentions Guinness"))  # "on tap" only when the page says so
        self.assertGreaterEqual(r["confidence"], 78)

    def test_menu_wording_decides_whether_it_is_on_tap(self):
        r = self.status(menuCheck={"foundOnMenu": True, "snippets": ["Guinness vom Fass 5dl CHF 9.80"]})
        self.assertEqual((r["servingFormat"], r["statusLabel"], r["reason"]), ("draught", "Confirmed", "Its website lists Guinness on tap"))

    def test_menu_with_only_bottles_or_cans_is_not_draught(self):
        r = self.status(menuCheck={"checked": True, "foundOnMenu": True, "typesFound": ["Guinness Cans", "Guinness Bottle"]})
        self.assertEqual((r["status"], r["servingFormat"]), ("cans_or_bottles", "cans_bottles"))

    def test_mixed_formats_count_as_draught(self):
        r = self.status(menuCheck={"foundOnMenu": True, "typesFound": ["Guinness Draught (On Tap)", "Guinness Cans"]})
        self.assertEqual(r["status"], "confirmed_draught")

    def test_crowd_reported_cans_format(self):
        r = self.status(menuCheck={"foundOnMenu": True}, crowdCheck={"servingFormat": "cans_bottles"})
        self.assertEqual(r["status"], "cans_or_bottles")

    def test_enough_community_confirmations_or_reviews_confirm(self):
        self.assertEqual(self.status(crowdCheck={"confirmedCount": 2})["status"], "confirmed_draught")
        self.assertEqual(self.status(reviewCheck={"mentionCount": 5})["status"], "confirmed_draught")

    def test_a_single_review_or_confirmation_is_only_likely(self):
        for kw in ({"reviewCheck": {"mentionCount": 1}}, {"crowdCheck": {"confirmedCount": 1}}):
            r = self.status(**kw)
            self.assertEqual(r["status"], "likely_serves", kw)
            self.assertGreaterEqual(r["confidence"], 55)

    def test_no_evidence_is_unverified_never_no(self):
        r = self.status()
        self.assertEqual((r["status"], r["servingFormat"]), ("unverified", "unknown"))
        self.assertGreaterEqual(r["confidence"], 15)

    def test_three_denials_without_any_support_means_no_guinness(self):
        r = self.status(crowdCheck={"deniedCount": 3})
        self.assertEqual((r["status"], r["servingFormat"]), ("no_guinness", "none"))

    def test_checked_menu_plus_community_saying_none_means_no_guinness(self):
        r = self.status(menuCheck={"checked": True, "foundOnMenu": False}, crowdCheck={"servingFormat": "none"})
        self.assertEqual(r["status"], "no_guinness")

    def test_an_unchecked_menu_is_never_reported_as_no(self):
        """'We did not look' must not become 'they do not serve it'."""
        r = self.status(menuCheck={"checked": False}, crowdCheck={"servingFormat": "none", "deniedCount": 2})
        self.assertNotEqual(r["status"], "no_guinness")

    def test_denials_cannot_override_real_evidence(self):
        self.assertNotEqual(self.status(menuCheck={"foundOnMenu": True}, crowdCheck={"deniedCount": 9})["status"], "no_guinness")
        self.assertNotEqual(self.status(crowdCheck={"deniedCount": 9, "confirmedCount": 1})["status"], "no_guinness")

    def test_pubs_score_higher_and_confidence_is_capped(self):
        base = self.status(reviewCheck={"mentionCount": 1})["confidence"]
        self.assertGreater(self.status(category="pub", reviewCheck={"mentionCount": 1})["confidence"], base - 1)
        huge = self.status(category="pub", menuCheck={"foundOnMenu": True}, reviewCheck={"mentionCount": 10**6}, crowdCheck={"confirmedCount": 500})
        self.assertLessEqual(huge["confidence"], 99)

    def test_null_counts_from_json_do_not_crash(self):
        r = self.status(reviewCheck={"mentionCount": None}, crowdCheck={"confirmedCount": None, "deniedCount": None})
        self.assertEqual(r["status"], "unverified")
        self.assertEqual(app.compute_guinness_status({})["status"], "unverified")


class SharedFixtureTests(unittest.TestCase):
    """Status and link-parsing scenarios kept as data (tests/fixtures/shared_cases.json) so they are easy to read and extend."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(os.path.dirname(__file__), "fixtures", "shared_cases.json"), encoding="utf-8") as f:
            cls.cases = json.load(f)

    def test_status_scenarios(self):
        self.assertGreater(len(self.cases["status"]), 20)
        for case in self.cases["status"]:
            with self.subTest(case["name"]):
                r = app.compute_guinness_status(case["venue"])
                self.assertEqual({"status": r["status"], "servingFormat": r["servingFormat"], "confidence": r["confidence"]}, case["expected"])

    def test_parse_scenarios(self):
        for case in self.cases["parse"]:
            with self.subTest(case["input"]):
                r = app.parse_google_maps_url_or_query(case["input"])
                self.assertEqual({"name": r["name"], "lat": r["lat"], "lng": r["lng"], "isUrl": r["isUrl"]}, case["expected"])


class EnrichVenueTests(unittest.TestCase):
    def test_does_not_mutate_the_input(self):
        v = venue(menuCheck={"foundOnMenu": False})
        app.enrich_venue(v, {"menuScans": {"v1": {"foundOnMenu": True}}, "crowdReports": {}})
        self.assertFalse(v["menuCheck"]["foundOnMenu"])
        self.assertNotIn("guinnessSummary", v)

    def test_saved_scan_overrides_the_menu_check_and_changes_the_status(self):
        v = venue(menuCheck={"checked": False, "foundOnMenu": False})
        out = app.enrich_venue(v, {"menuScans": {"v1": {"checked": True, "foundOnMenu": True, "typesFound": ["Guinness Draught (On Tap)"]}}, "crowdReports": {}})
        self.assertEqual(out["guinnessSummary"]["status"], "confirmed_draught")

    def test_community_reports_are_merged(self):
        reports = [
            {"servingFormat": "draught", "pintRating": 4.0, "price": "CHF 9.50", "hasZero": True},
            {"servingFormat": "draught", "pintRating": 5.0, "price": "CHF 8.00"},
            {"servingFormat": "none", "pintRating": None},
        ]
        v = venue(crowdCheck={"confirmedCount": 1, "deniedCount": 0, "avgPintRating": 4.0, "reportedPrice": "CHF 7.00"})
        cc = app.enrich_venue(v, {"menuScans": {}, "crowdReports": {"v1": reports}})["crowdCheck"]
        self.assertEqual((cc["confirmedCount"], cc["deniedCount"]), (3, 1))
        self.assertEqual(cc["servingFormat"], "draught")  # the newest report
        self.assertEqual(cc["reportedPrice"], "CHF 9.50")  # newest report that has a price
        self.assertTrue(cc["hasZero"])
        self.assertEqual(cc["avgPintRating"], 4.3)  # (1*4.0 base + 4.0 + 5.0) / 3
        self.assertEqual(len(cc["recentReports"]), 3)

    def test_recent_reports_are_limited_to_eight(self):
        reports = [{"servingFormat": "draught", "id": i} for i in range(20)]
        cc = app.enrich_venue(venue(), {"menuScans": {}, "crowdReports": {"v1": reports}})["crowdCheck"]
        self.assertEqual(len(cc["recentReports"]), 8)
        self.assertEqual(cc["recentReports"][0]["id"], 0)

    def test_reports_for_other_venues_are_ignored(self):
        out = app.enrich_venue(venue(), {"menuScans": {}, "crowdReports": {"other": [{"servingFormat": "none"}] * 5}})
        self.assertEqual(out["guinnessSummary"]["status"], "unverified")


class ParseGoogleMapsTests(unittest.TestCase):
    def test_plain_name(self):
        r = app.parse_google_maps_url_or_query("  Kennedy's Irish Pub  ")
        self.assertEqual((r["name"], r["isUrl"], r["lat"]), ("Kennedy's Irish Pub", False, None))

    def test_place_url_with_coordinates(self):
        r = app.parse_google_maps_url_or_query("https://www.google.com/maps/place/The+Old+Stand/@47.3769,8.5417,17z/data=x")
        self.assertEqual((r["name"], r["isUrl"], r["lat"], r["lng"]), ("The Old Stand", True, 47.3769, 8.5417))

    def test_short_links_and_q_coordinates(self):
        self.assertTrue(app.parse_google_maps_url_or_query("https://maps.app.goo.gl/abc123")["isUrl"])
        r = app.parse_google_maps_url_or_query("https://www.google.com/maps?q=46.2044,6.1432")
        self.assertEqual((r["lat"], r["lng"]), (46.2044, 6.1432))

    def test_empty(self):
        self.assertEqual(app.parse_google_maps_url_or_query(None)["name"], "")
        self.assertEqual(app.parse_google_maps_url_or_query("")["rawQuery"], "")


class CombinedVenuesTests(unittest.TestCase):
    def combine(self, store, demo, crawl):
        with mock.patch.object(app, "DEMO_VENUES", demo), mock.patch.object(app, "load_crawl_venues", lambda: crawl):
            return app.get_all_combined_venues(store)

    def test_dedupes_by_id_and_by_name_and_city_keeping_the_first(self):
        store = {"customVenues": [{"id": "c1", "name": "Pub", "city": "zurich", "address": "A"}], "googleMapsVenues": [{"id": "g1", "name": "pub ", "city": "Zurich"}]}
        out = self.combine(store, [{"id": "d1", "name": "Other", "city": "geneva"}, {"id": "c1", "name": "Dup id", "city": "bern"}], [{"id": "k1", "name": "Pub", "city": "basel"}])
        self.assertEqual([v["id"] for v in out], ["c1", "d1", "k1"])  # same name in another city is a different venue

    def test_skips_entries_without_an_id_and_adds_a_maps_link(self):
        out = self.combine({}, [{"name": "No id"}, None, {"id": "x", "name": "A B", "address": "Bahnhofstrasse 1"}], [])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["googleMapsUri"].startswith("https://www.google.com/maps/search/?api=1&query=A+B"))
        self.assertTrue(out[0]["googleMapsChecked"])

    def test_keeps_an_existing_maps_link(self):
        out = self.combine({}, [{"id": "x", "name": "A", "googleMapsUri": "https://maps.app.goo.gl/x"}], [])
        self.assertEqual(out[0]["googleMapsUri"], "https://maps.app.goo.gl/x")

    def test_upsert_replaces_by_id_and_saves(self):
        store = {"googleMapsVenues": [{"id": "g1", "name": "old"}]}
        with mock.patch.object(app, "save_store") as save:
            app.upsert_gmaps_venues_into_store(store, [{"id": "g1", "name": "new"}, {"id": "g2", "name": "two"}, None, {"name": "no id"}])
        self.assertEqual({v["id"]: v["name"] for v in store["googleMapsVenues"]}, {"g1": "new", "g2": "two"})
        save.assert_called_once()


class BundledDataIntegrityTests(unittest.TestCase):
    """The bundled dataset feeds map markers and links, so it must stay well-formed."""

    @classmethod
    def setUpClass(cls):
        cls.venues = app.get_all_combined_venues({})

    def test_there_is_data_with_unique_ids(self):
        self.assertGreater(len(self.venues), 100)
        ids = [v["id"] for v in self.venues]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_venue_is_well_formed_and_in_switzerland(self):
        for v in self.venues:
            with self.subTest(venue=v["id"]):
                self.assertTrue(v.get("name"))
                self.assertIn(v.get("category"), guard.CATEGORIES)
                self.assertIn(v.get("city"), app.CITY_PRESETS)
                b = guard.CH_BOUNDS
                self.assertTrue(b["south"] <= v["lat"] <= b["north"] and b["west"] <= v["lng"] <= b["east"], (v["lat"], v["lng"]))
                for key in ("menuCheck", "crowdCheck", "reviewCheck"):
                    self.assertIsInstance(v.get(key), dict)

    def test_every_website_is_a_plain_http_url(self):
        for v in self.venues:
            for key in ("website", "menuUrl"):
                if v.get(key):
                    with self.subTest(venue=v["id"], field=key):
                        self.assertEqual(guard.normalize_http_url(v[key]), v[key] if re.match(r"https?://", v[key], re.I) else "https://" + v[key])

    def test_every_venue_gets_a_valid_status(self):
        valid = {"confirmed_draught", "cans_or_bottles", "likely_serves", "no_guinness", "unverified"}
        for v in self.venues:
            s = app.enrich_venue(v, NO_STORE)["guinnessSummary"]
            self.assertIn(s["status"], valid)
            self.assertTrue(0 <= s["confidence"] <= 99)

    def test_city_presets_are_usable_map_views(self):
        for key, c in app.CITY_PRESETS.items():
            self.assertEqual(c["id"], key)
            self.assertTrue(45 < c["lat"] < 48 and 5 < c["lng"] < 11 and 5 <= c["zoom"] <= 18)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def fake_urlopen(routes, calls):
    """``routes``: substring of the URL -> JSON-able payload (or an Exception to raise)."""

    def opener(req, timeout=None):
        url = req.full_url
        body = req.data.decode() if isinstance(req.data, bytes) else req.data
        calls.append({"url": url, "body": body, "headers": {k.lower(): v for k, v in req.header_items()}})
        for needle, payload in routes.items():
            if needle in url:
                if isinstance(payload, Exception):
                    raise payload
                return FakeResponse(json.dumps(payload).encode())
        raise AssertionError(f"unexpected request to {url}")

    return opener


OLD_STAND = {
    "id": "A", "displayName": {"text": "The Old Stand"}, "types": ["pub", "bar"], "formattedAddress": "Zurich",
    "location": {"latitude": 47.37, "longitude": 8.54}, "rating": 4.6, "userRatingCount": 210, "websiteUri": "https://oldstand.example",
    "editorialSummary": {"text": "Irish pub pouring Guinness since 1990"},
    "reviews": [
        {"text": {"text": "Best Guinness in town"}, "authorAttribution": {"displayName": "Anna"}, "rating": 5, "relativePublishTimeDescription": "a week ago"},
        {"text": {"text": "Friendly staff, quick service"}},
    ],
}


class GooglePlacesMappingTests(unittest.TestCase):
    def run_live(self, places, text_places=None, **kw):
        calls = []
        routes = {"searchNearby": {"places": places}, "searchText": {"places": text_places or []}}
        with mock.patch("urllib.request.urlopen", fake_urlopen(routes, calls)), mock.patch.object(
            app, "scrape_menu_url", return_value={"checked": True, "foundOnMenu": True, "typesFound": ["Guinness 0.0"], "extractedPrice": "CHF 9.50", "snippets": ["x"]}
        ) as scrape:
            venues = app.fetch_google_places_live("KEY", 47.37, 8.54, **kw)
        self.calls, self.scrape = calls, scrape
        return {v["googlePlaceId"]: v for v in venues}

    def test_request_shape(self):
        self.run_live([OLD_STAND], radius=1234)
        nearby = next(c for c in self.calls if "searchNearby" in c["url"])
        self.assertEqual(nearby["headers"]["x-goog-api-key"], "KEY")
        self.assertIn("places.reviews", nearby["headers"]["x-goog-fieldmask"])
        body = json.loads(nearby["body"])
        self.assertEqual(body["locationRestriction"]["circle"]["radius"], 1234.0)
        self.assertIn("pub", body["includedTypes"])

    def test_maps_a_full_place_to_a_venue(self):
        v = self.run_live([OLD_STAND])["A"]
        self.assertEqual((v["id"], v["name"], v["category"], v["city"]), ("gplace-A", "The Old Stand", "pub", "all"))
        self.assertEqual((v["lat"], v["lng"], v["googleRating"], v["googleReviewCount"]), (47.37, 8.54, 4.6, 210))
        self.assertTrue(v["googleMapsUri"].startswith("https://www.google.com/maps/search/"))
        self.assertTrue(v["googleMapsChecked"])
        self.assertEqual(self.scrape.call_args.args[0], "https://oldstand.example")

    def test_counts_guinness_in_summaries_and_reviews(self):
        rc = self.run_live([OLD_STAND])["A"]["reviewCheck"]
        self.assertEqual(rc["mentionCount"], 2)  # the editorial summary counts once, plus one review
        self.assertEqual(rc["sentiment"], "positive")
        self.assertEqual([e["author"] for e in rc["excerpts"]], ["Google Maps Editorial Summary", "Anna"])

    def test_sentiment_levels_and_excerpt_cap(self):
        reviews = [{"text": {"text": f"Guinness number {i}"}} for i in range(8)]
        no_summary = {k: v for k, v in OLD_STAND.items() if k != "editorialSummary"}  # Google omits absent fields
        rc = self.run_live([{**no_summary, "reviews": reviews}])["A"]["reviewCheck"]
        self.assertEqual((rc["mentionCount"], rc["sentiment"], len(rc["excerpts"])), (8, "exceptional", 4))
        quiet = self.run_live([{"id": "Q", "displayName": {"text": "Quiet"}, "types": ["restaurant"], "location": {"latitude": 1, "longitude": 2}}])["Q"]["reviewCheck"]
        self.assertEqual((quiet["mentionCount"], quiet["sentiment"]), (0, "none"))

    def test_categories_from_google_types(self):
        mk = lambda i, name, types: {"id": i, "displayName": {"text": name}, "types": types, "location": {"latitude": 1, "longitude": 2}}
        out = self.run_live([mk("H", "Grand", ["lodging"]), mk("R", "Zum Ochsen", ["resort_hotel"]), mk("W", "Vinothek", ["wine_bar"]),
                             mk("N", "Late", ["night_club"]), mk("P", "Pasta", ["italian_restaurant"]), mk("T", "Tavern 5", [])])
        self.assertEqual({k: v["category"] for k, v in out.items()}, {"H": "hotel", "R": "hotel", "W": "bar", "N": "bar", "P": "restaurant", "T": "pub"})

    def test_websites_are_scanned_only_when_requested(self):
        self.run_live([OLD_STAND], scrape_menus=False)
        self.scrape.assert_not_called()

    def test_places_from_text_search_are_merged_without_duplicates(self):
        other = {"id": "B", "displayName": {"text": "Grand Hotel"}, "types": ["hotel"], "location": {"latitude": 1, "longitude": 2}}
        out = self.run_live([OLD_STAND], text_places=[OLD_STAND, other])
        self.assertEqual(sorted(out), ["A", "B"])

    def test_query_uses_text_search_with_location_bias_from_the_link(self):
        calls = []
        with mock.patch("urllib.request.urlopen", fake_urlopen({"searchText": {"places": [OLD_STAND]}}, calls)), mock.patch.object(app, "scrape_menu_url", return_value={}):
            app.fetch_google_places_live("KEY", 47.0, 8.0, query="https://www.google.com/maps/place/Pub/@46.5,7.5,15z", city="custom")
        body = json.loads(calls[0]["body"])
        self.assertEqual(body["locationBias"]["circle"]["center"], {"latitude": 46.5, "longitude": 7.5})
        self.assertEqual(len(calls), 1)

    def test_google_errors_for_a_query_are_raised(self):
        err = __import__("urllib.error").error.HTTPError("u", 403, "API key not valid", {}, None)
        with mock.patch("urllib.request.urlopen", fake_urlopen({"searchText": err}, [])), self.assertRaises(Exception):
            app.fetch_google_places_live("BAD", 47, 8, query="pub")


OSM_ELEMENTS = [
    {"id": 1, "lat": 47.37, "lon": 8.54, "tags": {"amenity": "pub", "name": "The Old Stand", "website": "www.oldstand.ch", "addr:street": "Bahnhofstr.", "addr:housenumber": "1", "addr:postcode": "8001", "addr:city": "Zürich", "phone": "+41 44 000"}},
    {"id": 2, "center": {"lat": 47.38, "lon": 8.55}, "tags": {"amenity": "bar", "name": "Cocktail Corner", "contact:website": "https://corner.example", "url:menu": "https://corner.example/drinks"}},
    {"id": 3, "lat": 47.39, "lon": 8.56, "tags": {"amenity": "restaurant", "name": "Pasta Place", "cuisine": "italian"}},
    {"id": 4, "lat": 47.40, "lon": 8.57, "tags": {"tourism": "hotel", "name": "Lake Palace"}},
    {"id": 5, "lat": 47.41, "lon": 8.58, "tags": {"amenity": "pub", "name": "the old stand"}},  # duplicate name (case-insensitive)
    {"id": 6, "lat": 47.42, "lon": 8.59, "tags": {"amenity": "pub"}},  # no name
    {"id": 7, "tags": {"amenity": "pub", "name": "Nowhere Pub"}},  # no coordinates
    {"id": 8, "lat": 47.43, "lon": 8.60, "tags": {"amenity": "restaurant", "name": "Brew House", "brewery": "Guinness;Feldschlösschen"}},
]


class OverpassMappingTests(unittest.TestCase):
    def run_osm(self, elements, fn=app.fetch_osm_overpass_live, *args, **kw):
        calls = []
        with mock.patch("urllib.request.urlopen", fake_urlopen({"overpass": {"elements": elements}}, calls)):
            venues = fn(*args, **kw)
        self.calls = calls
        return venues

    def test_query_is_built_from_numbers_only(self):
        self.run_osm([], app.fetch_osm_overpass_live, 47.37, 8.54, radius=900)
        self.assertIn("around:900,47.37,8.54", self.calls[0]["url"] + urllib_unquote(self.calls[0]["body"]))
        for bad in ({"lat": "47; out", "lng": 8}, {"lat": 47, "lng": "x"}):
            with self.assertRaises(ValueError):
                self.run_osm([], app.fetch_osm_overpass_live, bad["lat"], bad["lng"])

    def test_maps_tags_to_venues_and_skips_unusable_elements(self):
        out = {v["name"]: v for v in self.run_osm(OSM_ELEMENTS, app.fetch_osm_overpass_live, 47.37, 8.54)}
        self.assertEqual(sorted(out), ["Brew House", "Cocktail Corner", "Lake Palace", "Pasta Place", "The Old Stand"])
        self.assertEqual(out["The Old Stand"]["id"], "osm-1")
        self.assertEqual({n: v["category"] for n, v in out.items()}, {"The Old Stand": "pub", "Cocktail Corner": "bar", "Pasta Place": "restaurant", "Lake Palace": "hotel", "Brew House": "restaurant"})
        self.assertEqual((out["Cocktail Corner"]["lat"], out["Cocktail Corner"]["lng"]), (47.38, 8.55))  # way centre

    def test_address_phone_and_menu_url_tags(self):
        out = {v["name"]: v for v in self.run_osm(OSM_ELEMENTS, app.fetch_osm_overpass_live, 47.37, 8.54)}
        self.assertEqual(out["The Old Stand"]["address"], "Bahnhofstr. 1, 8001 Zürich")
        self.assertEqual(out["The Old Stand"]["phone"], "+41 44 000")
        self.assertEqual(out["Cocktail Corner"]["website"], "https://corner.example")
        self.assertEqual(out["Cocktail Corner"]["menuUrl"], "https://corner.example/drinks")
        self.assertEqual(out["Pasta Place"]["address"], "Switzerland")  # no address tags at all

    def test_a_guinness_brewery_tag_is_a_hint_not_a_menu_check(self):
        with mock.patch.object(app, "scrape_menu_url") as scrape:
            out = {v["name"]: v for v in self.run_osm(OSM_ELEMENTS, app.fetch_osm_overpass_live, 47.37, 8.54)}
        brew = out["Brew House"]
        self.assertEqual((brew["menuCheck"]["checked"], brew["menuCheck"]["foundOnMenu"]), (False, False))
        self.assertEqual(brew["tagCheck"]["kind"], "osm_tag")
        summary = app.enrich_venue(brew, NO_STORE)["guinnessSummary"]
        self.assertEqual((summary["status"], summary["statusLabel"]), ("likely_serves", "Possible"))
        self.assertIn("OpenStreetMap lists Guinness", summary["reason"])
        scrape.assert_not_called()

    def test_untouched_websites_are_not_scanned_by_default(self):
        out = {v["name"]: v for v in self.run_osm(OSM_ELEMENTS, app.fetch_osm_overpass_live, 47.37, 8.54)}
        mc = out["The Old Stand"]["menuCheck"]
        self.assertEqual((mc["checked"], mc["foundOnMenu"]), (False, False))
        self.assertIn("click 'Scan Menu'", mc["snippets"][0])
        self.assertIn("no website", out["Pasta Place"]["menuCheck"]["snippets"][0])

    def test_scanning_is_limited_to_the_first_six_venues(self):
        many = [{"id": i, "lat": 47.0 + i / 100, "lon": 8.0, "tags": {"amenity": "bar", "name": f"Bar {i}", "website": f"https://b{i}.example"}} for i in range(10)]
        with mock.patch.object(app, "scrape_menu_url", return_value={"checked": True, "foundOnMenu": False}) as scrape:
            self.run_osm(many, app.fetch_osm_overpass_live, 47, 8, scrape_menus=True)
        self.assertEqual(scrape.call_count, 6)

    def test_regression_hostile_website_tags_are_never_stored(self):
        """OpenStreetMap tags are editable by anyone; a javascript: 'website' must not enter our data."""
        evil = [{"id": 9, "lat": 47.0, "lon": 8.0, "tags": {"amenity": "pub", "name": "Evil", "website": "javascript:alert(document.cookie)", "url:menu": "data:text/html,x"}},
                {"id": 10, "lat": 47.1, "lon": 8.1, "tags": {"amenity": "pub", "name": "Spaces", "website": "http://exa mple.com"}}]
        for fn, args in ((app.fetch_osm_overpass_live, (47, 8)), (app.fetch_osm_switzerland_nationwide, ())):
            for v in self.run_osm(evil, fn, *args):
                with self.subTest(fn=fn.__name__, venue=v["name"]):
                    self.assertIsNone(v["website"])
                    self.assertIsNone(v["menuUrl"])

    def test_regression_schemeless_osm_websites_are_normalised(self):
        v = self.run_osm(OSM_ELEMENTS[:1], app.fetch_osm_overpass_live, 47.37, 8.54)[0]
        self.assertEqual(v["website"], "https://www.oldstand.ch")

    def test_nationwide_scan_skips_demo_venues_and_prefixes_ids(self):
        demo_name = app.DEMO_VENUES[0]["name"]
        els = [{"id": 11, "lat": 47.0, "lon": 8.0, "tags": {"amenity": "pub", "name": demo_name}}, {"id": 12, "lat": 47.0, "lon": 8.0, "tags": {"amenity": "pub", "name": "Brand New Irish Pub"}}]
        out = self.run_osm(els, app.fetch_osm_switzerland_nationwide)
        self.assertEqual([v["name"] for v in out], ["Brand New Irish Pub"])
        self.assertTrue(out[0]["id"].startswith("osm-"))

    def test_osm_failures_become_a_friendly_error_after_trying_every_server(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("overpass down")) as urlopen, self.assertRaises(overpass.OverpassUnavailable) as ctx:
            app.fetch_osm_overpass_live(47, 8)
        self.assertEqual(urlopen.call_count, len(overpass.DEFAULT_URLS) * 2)  # every server, two passes
        self.assertIn("try again in a minute", str(ctx.exception))


def urllib_unquote(s):
    import urllib.parse

    return urllib.parse.unquote_plus(s or "")


class HttpRoutesTests(ApiTestCase):
    def test_static_pages_are_served(self):
        for path, ctype in (("/", "text/html"), ("/index.html", "text/html"), ("/standalone.html", "text/html"), ("/src/styles.css", "text/css")):
            with self.subTest(path=path):
                status, body, resp = self.call("GET", path)
                self.assertEqual(status, 200)
                self.assertTrue(resp.getheader("Content-Type").startswith(ctype))
                self.assertGreater(len(body), 100)

    def test_regression_unknown_paths_never_serve_files_from_disk(self):
        """The fallback used to be SimpleHTTPRequestHandler, which served source files, .git, and .env."""
        for path in ("/app_server.py", "/guard.py", "/storage.py", "/README.md", "/.env", "/.env.example", "/.git/config", "/tests/helpers.py",
                     "/api/index.py", "/server/data/swiss_crawl_results.json", "/../app_server.py", "/%2e%2e/app_server.py", "/nope"):
            with self.subTest(path=path):
                status, body, _ = self.call("GET", path)
                self.assertEqual(status, 404)
                self.assertIsInstance(body, dict)  # a JSON error, not a file or an HTML listing
                self.assertNotIn("import ", json.dumps(body))

    def test_venues_in_osm_mode_returns_enriched_venues_and_stores_them(self):
        v = {"id": "osm-1", "city": "custom", "name": "OSM Pub", "category": "pub", "lat": 47.0, "lng": 8.0, "menuCheck": {}, "crowdCheck": {}, "reviewCheck": {}}
        with mock.patch.object(app, "fetch_osm_overpass_live", return_value=[v]) as osm, mock.patch.object(app, "upsert_gmaps_venues_into_store") as up:
            status, data, _ = self.call("GET", "/api/venues?mode=osm&lat=47.0&lng=8.0&scrapeMenus=true")
        self.assertEqual((status, data["source"]), (200, "openstreetmap_overpass_free"))
        self.assertEqual(data["venues"][0]["guinnessSummary"]["status"], "unverified")
        self.assertEqual(osm.call_args.args, (47.0, 8.0, 2200, True))
        up.assert_called_once()

    def test_venues_in_osm_mode_reports_upstream_errors_as_json(self):
        with mock.patch.object(app, "fetch_osm_overpass_live", side_effect=OSError("overpass down")):
            status, data, _ = self.call("GET", "/api/venues?mode=osm&lat=47.0&lng=8.0")
        self.assertEqual(status, 500)
        self.assertIn("overpass down", data["error"])

    def test_nationwide_mode_falls_back_to_bundled_data_when_overpass_fails(self):
        with mock.patch.object(app, "fetch_osm_switzerland_nationwide", side_effect=OSError("down")):
            status, data, _ = self.call("GET", "/api/venues?mode=osm_ch")
        self.assertEqual((status, data["source"]), (200, "switzerland_nationwide_scan"))
        self.assertEqual(data["venues"][0]["id"], "v-known")

    def test_city_filter(self):
        a = dict(os.environ)
        with mock.patch.object(app, "get_all_combined_venues", lambda s: [{"id": "z", "city": "zurich", "menuCheck": {}, "crowdCheck": {}, "reviewCheck": {}}, {"id": "g", "city": "geneva", "menuCheck": {}, "crowdCheck": {}, "reviewCheck": {}}]):
            self.assertEqual([v["id"] for v in self.call("GET", "/api/venues?city=geneva")[1]["venues"]], ["g"])
            self.assertEqual(len(self.call("GET", "/api/venues?city=all")[1]["venues"]), 2)
        self.assertEqual(a, dict(os.environ))


if __name__ == "__main__":
    unittest.main()

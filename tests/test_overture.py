"""Runtime lookup of venue websites in the Overture extract (overture.py) and its use by the OSM importers."""

import json
import os
import tempfile
import unittest
from unittest import mock

import app_server as app
import overture
from tests.test_core import fake_urlopen


def place(id, name, lat, lng, website="https://x.example", phone=None):
    return {"id": id, "name": name, "category": "pub", "lat": lat, "lng": lng, "website": website, "phone": phone, "address": "", "confidence": 0.9}


class NameScoreTests(unittest.TestCase):
    def test_tokens_drop_kind_of_place_words_and_accents(self):
        self.assertEqual(overture.normalize_tokens("Restaurant Rössli"), ["rossli"])
        self.assertEqual(overture.normalize_tokens("Hôtel de la Gare"), ["gare"])
        self.assertEqual(overture.normalize_tokens("Bar"), ["bar"])  # nothing else left: keep it
        self.assertEqual(overture.normalize_tokens("Pub 55"), ["55"])

    def test_same_venue_written_differently_matches(self):
        for a, b in [
            ("The Old Stand", "Old Stand Irish Pub"),
            ("Restaurant Rössli", "Roessli"),
            ("Hotel Schweizerhof", "Schweizerhof Bern"),
            ("Kennedy's Irish Pub", "Kennedys Irish Pub"),
            ("Café Central", "Central"),
        ]:
            with self.subTest(a=a, b=b):
                self.assertGreaterEqual(overture.name_score(a, b), overture.MIN_SCORE)

    def test_different_venues_do_not_match(self):
        for a, b in [("Bar Rouge", "Bar Bleu"), ("Pizzeria Roma", "Pizzeria Napoli"), ("Hotel Bellevue", "Hotel Belvedere"), ("", "Pub"), ("Pub", None),
                     ("Penny Farthing Pub Aarau", "The Penny")]:  # regression: one short word inside a longer name
            with self.subTest(a=a, b=b):
                self.assertLess(overture.name_score(a, b), overture.MIN_SCORE)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.index = overture.Index([
            place("1", "The Old Stand", 47.3700, 8.5400, "https://oldstand.example", "+41 44 111"),
            place("2", "Pasta Place", 47.3701, 8.5401, "https://pasta.example"),
            place("3", "The Old Stand", 47.3800, 8.5400, "https://far-away.example"),  # same name, 1 km away
        ])

    def test_finds_the_same_venue_nearby(self):
        hit = self.index.find("Old Stand Irish Pub", 47.37005, 8.54005)
        self.assertEqual((hit["id"], hit["website"], hit["phone"]), ("1", "https://oldstand.example", "+41 44 111"))
        self.assertLess(hit["distanceM"], 20)

    def test_same_name_far_away_is_a_different_venue(self):
        self.assertEqual(self.index.find("The Old Stand", 47.3700, 8.5400)["id"], "1")
        self.assertIsNone(self.index.find("The Old Stand", 47.3900, 8.5400))

    def test_similar_location_but_different_name(self):
        self.assertIsNone(self.index.find("Burger Bar", 47.3700, 8.5400))

    def test_distance_limit(self):
        self.assertIsNotNone(self.index.find("Pasta Place", 47.3701 + 0.0005, 8.5401))  # ~55 m
        self.assertIsNone(self.index.find("Pasta Place", 47.3701 + 0.0015, 8.5401))  # ~165 m

    def test_matches_across_grid_cell_borders(self):
        border = overture.CELL_DEGREES * 9400  # a cell edge
        idx = overture.Index([place("b", "Cafe Grenze", border - 0.00001, 8.5, "https://grenze.example")])
        self.assertEqual(idx.find("Grenze", border + 0.00001, 8.5)["id"], "b")

    def test_best_candidate_wins(self):
        idx = overture.Index([place("a", "Rose Garden", 47.0, 8.0, "https://a.example"), place("b", "Rose", 47.0, 8.0, "https://b.example")])
        self.assertEqual(idx.find("Rose Garden", 47.0, 8.0)["id"], "a")  # exact beats partial


class LoadIndexTests(unittest.TestCase):
    def tearDown(self):
        overture.reset_cache()

    def write(self, payload):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(payload, f)
        f.close()
        self.addCleanup(lambda: os.path.exists(f.name) and os.unlink(f.name))
        return f.name

    def test_missing_or_corrupt_file_gives_an_empty_index(self):
        self.assertEqual(overture.load_index("/nonexistent/overture.json").places, [])
        overture.reset_cache()
        bad = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        bad.write("{not json")
        bad.close()
        self.addCleanup(os.unlink, bad.name)
        self.assertEqual(overture.load_index(bad.name).places, [])

    def test_entries_without_a_website_or_location_are_ignored_and_the_file_is_cached(self):
        path = self.write({"places": [place("1", "A", 47.0, 8.0), place("2", "B", 47.0, 8.0, website=None), {"id": "3", "name": "C", "website": "https://c"}]})
        index = overture.load_index(path)
        self.assertEqual([p["id"] for p in index.places], ["1"])
        os.unlink(path)
        self.assertIs(overture.load_index(path), index)  # cached: not re-read

    def test_find_match_tolerates_missing_inputs(self):
        with mock.patch.object(overture, "DATA_PATH", "/nonexistent.json"):
            self.assertIsNone(overture.find_match("Pub", None, 8.0))
            self.assertIsNone(overture.find_match("", 47.0, 8.0))
            self.assertIsNone(overture.find_match("Pub", 47.0, 8.0))


class OsmIntegrationTests(unittest.TestCase):
    """OpenStreetMap venues without a website borrow one from Overture (and are then scannable)."""

    def setUp(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump({"places": [
            place("o1", "The Old Stand", 47.3700, 8.5400, "https://oldstand.example", "+41 44 111 22 33"),
            place("o2", "Kein Treffer", 47.5, 8.9, "https://other.example"),
        ]}, f)
        f.close()
        self.addCleanup(os.unlink, f.name)
        patcher = mock.patch.object(overture, "DATA_PATH", f.name)
        patcher.start()
        overture.reset_cache()
        self.addCleanup(patcher.stop)
        self.addCleanup(overture.reset_cache)

    def run_osm(self, elements, **kw):
        with mock.patch("urllib.request.urlopen", fake_urlopen({"overpass": {"elements": elements}}, [])):
            return app.fetch_osm_overpass_live(47.37, 8.54, **kw)

    def element(self, **tags):
        return {"id": 1, "lat": 47.37002, "lon": 8.54002, "tags": {"amenity": "pub", "name": "Old Stand Irish Pub", **tags}}

    def test_a_missing_website_is_filled_in(self):
        v = self.run_osm([self.element()])[0]
        self.assertEqual((v["website"], v["menuUrl"], v["phone"], v["websiteSource"]), ("https://oldstand.example", "https://oldstand.example", "+41 44 111 22 33", "overture"))

    def test_the_openstreetmap_website_always_wins(self):
        v = self.run_osm([self.element(website="https://osm-site.example", phone="+41 1")])[0]
        self.assertEqual((v["website"], v["phone"], v["websiteSource"]), ("https://osm-site.example", "+41 1", "openstreetmap"))

    def test_a_menu_url_tag_is_kept_and_only_the_website_is_borrowed(self):
        v = self.run_osm([self.element(**{"url:menu": "https://oldstand.example/drinks"})])[0]
        self.assertEqual((v["website"], v["menuUrl"]), ("https://oldstand.example", "https://oldstand.example/drinks"))

    def test_no_match_leaves_the_venue_as_it_was(self):
        v = self.run_osm([{"id": 2, "lat": 46.0, "lon": 7.0, "tags": {"amenity": "bar", "name": "Nowhere Bar"}}])[0]
        self.assertEqual((v["website"], v["websiteSource"]), (None, None))

    def test_a_borrowed_website_is_scanned_for_guinness(self):
        with mock.patch.object(app, "scrape_menu_url", return_value={"checked": True, "foundOnMenu": True, "typesFound": [], "snippets": []}) as scan:
            v = self.run_osm([self.element()], scrape_menus=True)[0]
        scan.assert_called_once_with("https://oldstand.example")
        self.assertTrue(v["menuCheck"]["foundOnMenu"])

    def test_the_nationwide_scan_borrows_websites_too(self):
        with mock.patch("urllib.request.urlopen", fake_urlopen({"overpass": {"elements": [self.element()]}}, [])):
            v = app.fetch_osm_switzerland_nationwide()[0]
        self.assertEqual((v["website"], v["websiteSource"]), ("https://oldstand.example", "overture"))

    def test_fill_helper_directly(self):
        self.assertEqual(app.fill_from_overture("Old Stand", 47.37, 8.54, "https://osm.example", None, None), ("https://osm.example", None, None, "openstreetmap"))
        self.assertEqual(app.fill_from_overture("Zzz", 47.37, 8.54, None, None, None), (None, None, None, None))


if __name__ == "__main__":
    unittest.main()

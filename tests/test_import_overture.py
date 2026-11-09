"""scripts/import_overture.py: classification, filtering, row-group pruning and the whole pipeline,
against synthetic Parquet files in Overture's real schema served by a fake S3 (no network)."""

import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

from tests import overture_fixtures as fx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("import_overture", os.path.join(ROOT, "scripts", "import_overture.py"))
imp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imp)

HAVE_PYARROW = fx.pq is not None
needs_pyarrow = unittest.skipUnless(HAVE_PYARROW, "pyarrow is not installed (pip install pyarrow)")


class ClassifyTests(unittest.TestCase):
    """Hierarchies copied from the real Overture data (release 2026-10-21.0)."""

    def tax(self, *hierarchy):
        return {"primary": hierarchy[-1], "hierarchy": list(hierarchy), "alternates": None}

    def test_categories(self):
        cases = {
            "pub": [self.tax(*fx.PUB), self.tax(*fx.IRISH_PUB), self.tax("food_and_drink", "casual_eatery", "gastropub")],
            "bar": [self.tax(*fx.BAR), self.tax("food_and_drink", "alcoholic_beverage_venue", "bar", "cocktail_bar"),
                    self.tax("food_and_drink", "alcoholic_beverage_venue", "bar", "sports_bar"), self.tax("food_and_drink", "alcoholic_beverage_venue", "lounge"),
                    self.tax("food_and_drink", "casual_eatery", "tapas_bar"), self.tax("food_and_drink", "alcoholic_beverage_venue", "beer_garden")],
            "restaurant": [self.tax(*fx.RESTAURANT), self.tax("food_and_drink", "restaurant")],
            "hotel": [self.tax(*fx.HOTEL), self.tax("lodging", "bed_and_breakfast"), self.tax("lodging", "hostel"), self.tax("lodging", "resort"), self.tax("lodging", "inn")],
        }
        for category, taxonomies in cases.items():
            for t in taxonomies:
                with self.subTest(category=category, primary=t["primary"]):
                    self.assertEqual(imp.classify(t), category)

    def test_things_that_are_not_places_to_drink_or_stay(self):
        for t in [
            self.tax(*fx.DENTIST), self.tax("lodging", "ski_resort"), self.tax("lodging", "campground"),
            self.tax("food_and_drink", "alcoholic_beverage_venue", "winery"), self.tax("food_and_drink", "alcoholic_beverage_venue", "brewery"),
            self.tax("food_and_drink", "alcoholic_beverage_venue", "bar", "hookah_bar"), self.tax("food_and_drink", "non_alcoholic_beverage_venue", "smoothie_juice_bar"),
            self.tax("food_and_drink", "restaurant", "salad_bar"), self.tax("food_and_drink", "alcoholic_beverage_venue", "airport_lounge"),
            self.tax("food_and_drink", "bakery"), None, {}, {"primary": "pub"},
        ]:
            with self.subTest(t=t):
                self.assertIsNone(imp.classify(t))


class WebsiteTests(unittest.TestCase):
    def test_first_usable_website_wins(self):
        self.assertEqual(imp.usable_website(["https://www.facebook.com/mypub", "https://mypub.ch/", "https://other.ch"]), "https://mypub.ch/")
        self.assertEqual(imp.usable_website(["mypub.ch/menu"]), "https://mypub.ch/menu")

    def test_social_booking_directory_and_shortener_pages_are_not_venue_websites(self):
        for url in ["https://www.facebook.com/x", "https://instagram.com/x", "https://www.tripadvisor.ch/Restaurant-x", "https://www.booking.com/hotel/x",
                    "https://yellow.local.ch/de/d/x", "https://tel.search.ch/x", "https://bit.ly/abc", "https://g.co/kgs/x", "https://maps.app.goo.gl/x",
                    "https://x.wixsite.com/pub", "https://www.thefork.ch/restaurant/x", "https://wolt.com/x", "https://bnb.ch/x"]:
            with self.subTest(url=url):
                self.assertIsNone(imp.usable_website([url]))

    def test_unsafe_or_garbage_values_are_dropped(self):
        for value in ["javascript:alert(1)", "http://localhost/x", "http://192.168.0.1/", "not a url", "", None, "ftp://x.ch"]:
            self.assertIsNone(imp.usable_website([value]), value)
        self.assertIsNone(imp.usable_website(None))
        self.assertIsNone(imp.usable_website([]))

    def test_chain_websites_are_kept(self):
        self.assertEqual(imp.usable_website(["https://www.mcdonalds.ch/de/restaurants/x"]), "https://www.mcdonalds.ch/de/restaurants/x")


class NormalizePlaceTests(unittest.TestCase):
    def good(self, **kw):
        args = dict(id="a", name="The Old Stand", hierarchy=fx.IRISH_PUB, lat=47.37, lng=8.54, websites=["https://oldstand.ch"], phones=["+41 44 1"])
        args.update(kw)
        return fx.place(**args)

    def test_a_good_venue_is_kept_in_compact_form(self):
        self.assertEqual(imp.normalize_place(self.good(), "CH"), {
            "id": "a", "name": "The Old Stand", "category": "pub", "lat": 47.37, "lng": 8.54, "website": "https://oldstand.ch",
            "phone": "+41 44 1", "address": "Bahnhofstrasse 1, 8001 Zürich", "confidence": 0.9})

    def test_filters(self):
        skip = {
            "foreign place in the bounding box": self.good(country="FR"),
            "no address": {**self.good(), "addresses": None},
            "closed for good": self.good(status="permanently_closed"),
            "temporarily closed": self.good(status="temporarily_closed"),
            "low confidence": self.good(confidence=0.3),
            "missing confidence": self.good(confidence=None),
            "not hospitality": self.good(hierarchy=fx.DENTIST),
            "no website": self.good(websites=None),
            "only a social page": self.good(websites=["https://facebook.com/x"]),
            "no name": {**self.good(), "names": {"primary": None}},
            "no location": {**self.good(), "bbox": {}},
        }
        for why, row in skip.items():
            with self.subTest(why):
                self.assertIsNone(imp.normalize_place(row, "CH"))

    def test_unknown_status_is_kept_and_options_are_respected(self):
        self.assertIsNotNone(imp.normalize_place(self.good(status=None), "CH"))
        self.assertIsNotNone(imp.normalize_place(self.good(confidence=0.3), "CH", min_confidence=0.2))
        no_site = imp.normalize_place(self.good(websites=None, phones=None), "CH", require_website=False)
        self.assertEqual((no_site["website"], no_site["phone"]), (None, None))

    def test_dedupe_keeps_the_most_confident_of_exact_repeats(self):
        a = imp.normalize_place(self.good(id="1", confidence=0.6), "CH")
        b = imp.normalize_place(self.good(id="2", confidence=0.95), "CH")
        c = imp.normalize_place(self.good(id="3", name="Other Pub"), "CH")
        self.assertEqual([p["id"] for p in imp.dedupe([a, b, c])], ["2", "3"])


@needs_pyarrow
class RowGroupSelectionTests(unittest.TestCase):
    def meta(self, statistics=True):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "t.parquet")
        fx.write_parquet(path, [
            [fx.place("z", "Zurich Pub", fx.PUB, 47.37, 8.54), fx.place("b", "Basel Pub", fx.PUB, 47.55, 7.59)],
            [fx.place("p", "Paris Pub", fx.PUB, 48.85, 2.35)],
            [fx.place("be", "Berlin Pub", fx.PUB, 52.52, 13.40)],
            [fx.place("g", "Geneva Pub", fx.PUB, 46.20, 6.14), fx.place("f", "Annecy Pub", fx.PUB, 45.90, 6.12)],
        ], statistics=statistics)
        return fx.pq.ParquetFile(path).metadata

    def test_only_row_groups_that_overlap_the_country_are_selected(self):
        self.assertEqual(imp.row_groups_overlapping(self.meta(), imp.COUNTRIES["CH"][1]), [0, 3])

    def test_a_row_group_without_statistics_is_kept_not_dropped(self):
        self.assertEqual(imp.row_groups_overlapping(self.meta(statistics=False), imp.COUNTRIES["CH"][1]), [0, 1, 2, 3])


class FakeNetworkMixin:
    def setUp(self):
        super().setUp()
        self.objects = {}
        self.bucket = fx.FakeBucket(self.objects)
        self.addCleanup(self.bucket.close)
        for patcher in (mock.patch.object(imp, "BUCKET", self.bucket.url), mock.patch.object(imp.time, "sleep", lambda s: None)):
            patcher.start()
            self.addCleanup(patcher.stop)


class ReleaseListingTests(FakeNetworkMixin, unittest.TestCase):
    def test_latest_release_is_the_newest_by_name(self):
        for r in ("2026-09-23.0", "2026-09-23.1", "2026-10-21.0"):
            self.objects[f"release/{r}/theme=places/type=place/part-0.parquet"] = b"x"
        self.assertEqual(imp.latest_release(), "2026-10-21.0")

    def test_data_files_are_listed_and_a_missing_release_is_an_error(self):
        self.objects[fx.KEY] = b"12345"
        self.assertEqual(imp.list_data_files(fx.RELEASE), [(fx.KEY, 5)])
        with self.assertRaisesRegex(RuntimeError, "no places files"):
            imp.list_data_files("1999-01-01.0")

    def test_no_releases_is_an_error(self):
        with self.assertRaises(RuntimeError):
            imp.latest_release()


class HttpFileTests(FakeNetworkMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.objects["k"] = bytes(range(256)) * 4

    def test_reads_seeks_and_tracks_bytes(self):
        f = imp.HttpFile("k", 1024)
        self.assertEqual(f.read(4), bytes([0, 1, 2, 3]))
        self.assertEqual(f.tell(), 4)
        f.seek(-2, 2)
        self.assertEqual(f.read(10), bytes([254, 255]))  # clamped at the end of the file
        self.assertEqual(f.read(5), b"")
        f.seek(300)
        buffer = bytearray(3)
        self.assertEqual(f.readinto(buffer), 3)
        self.assertEqual(bytes(buffer), bytes([44, 45, 46]))
        self.assertEqual(f.bytes_read, 4 + 2 + 3)

    def test_transient_failures_are_retried(self):
        self.bucket.failures = 2
        self.assertEqual(imp.HttpFile("k", 1024).read(2), bytes([0, 1]))

    def test_a_persistent_failure_is_reported_clearly(self):
        self.bucket.failures = 99
        with self.assertRaisesRegex(RuntimeError, "download failed after 4 attempts"):
            imp.HttpFile("k", 1024).read(2)


@needs_pyarrow
class PipelineTests(FakeNetworkMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        d = tempfile.mkdtemp()
        path = os.path.join(d, "part.parquet")
        fx.write_parquet(path, [
            [  # a row group around Zurich
                fx.place("pub1", "The Old Stand", fx.IRISH_PUB, 47.37, 8.54, websites=["https://oldstand.ch"], phones=["+41 44 1"]),
                fx.place("bar1", "Bar Rouge", fx.BAR, 47.38, 8.55, websites=["https://facebook.com/barrouge"]),  # only a social page
                fx.place("res1", "Rössli", fx.RESTAURANT, 47.39, 8.56, websites=["https://roessli.ch"]),
                fx.place("hot1", "Hotel Bellevue", fx.HOTEL, 47.40, 8.57, websites=["https://bellevue.ch"], confidence=0.4),  # low confidence
                fx.place("den1", "Dr. Zahn", fx.DENTIST, 47.41, 8.58, websites=["https://zahn.ch"]),
                fx.place("fr1", "Chez Pierre", fx.RESTAURANT, 46.0, 6.1, country="FR", websites=["https://pierre.fr"]),  # French, inside the bbox
                fx.place("cl1", "Closed Pub", fx.PUB, 47.42, 8.59, websites=["https://closed.ch"], status="permanently_closed"),
                fx.place("dup1", "The Old Stand", fx.PUB, 47.37, 8.54, websites=["https://oldstand.ch/dup"], confidence=0.6),  # repeat of pub1
            ],
            [fx.place("par1", "Paris Pub", fx.PUB, 48.85, 2.35, country="FR", websites=["https://paris.fr"])],  # a row group far away
        ])
        with open(path, "rb") as f:
            self.objects[fx.KEY] = f.read()

    def test_the_whole_pipeline(self):
        logs = []
        data = imp.build_dataset(fx.RELEASE, "CH", 0.5, True, 2, 0, logs.append)
        self.assertEqual({p["id"] for p in data["places"]}, {"pub1", "res1"})
        pub = next(p for p in data["places"] if p["id"] == "pub1")
        self.assertEqual((pub["category"], pub["website"], pub["phone"]), ("pub", "https://oldstand.ch", "+41 44 1"))
        self.assertEqual(data["release"], fx.RELEASE)
        self.assertEqual(data["stats"]["venues"], 2)
        self.assertEqual(data["stats"]["byCategory"], {"pub": 1, "restaurant": 1})
        self.assertIn("CDLA", data["license"])
        self.assertTrue(any("1 row groups overlap" in line for line in logs), logs)  # Paris was pruned

    def test_the_far_away_row_group_is_never_downloaded(self):
        imp.build_dataset(fx.RELEASE, "CH", 0.5, True, 1, 0, lambda m: None)
        file_requests = [p for p in self.bucket.requests if "list-type" not in p]
        self.assertTrue(file_requests)
        footer_and_one_group = len(file_requests)
        self.bucket.requests.clear()
        imp.build_dataset(fx.RELEASE, "CH", 0.5, True, 1, 1, lambda m: None)
        self.assertLessEqual(len([p for p in self.bucket.requests if "list-type" not in p]), footer_and_one_group)

    def test_options(self):
        with_site_optional = imp.build_dataset(fx.RELEASE, "CH", 0.5, False, 1, 0, lambda m: None)
        self.assertIn("bar1", {p["id"] for p in with_site_optional["places"]})  # kept: websites no longer required
        permissive = imp.build_dataset(fx.RELEASE, "CH", 0.3, True, 1, 0, lambda m: None)
        self.assertIn("hot1", {p["id"] for p in permissive["places"]})

    def test_main_writes_the_output_file(self):
        out = os.path.join(tempfile.mkdtemp(), "nested", "overture_ch.json")
        self.assertEqual(imp.main(["--release", fx.RELEASE, "--out", out, "--workers", "1"]), 0)
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["country"], "CH")
        self.assertEqual(len(data["places"]), 2)

    def test_the_latest_release_is_used_by_default(self):
        out = os.path.join(tempfile.mkdtemp(), "o.json")
        self.assertEqual(imp.main(["--out", out, "--workers", "1"]), 0)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["release"], fx.RELEASE)

    def test_unknown_countries_are_refused(self):
        with self.assertRaises(SystemExit):
            imp.build_dataset(fx.RELEASE, "FR", 0.5, True, 1, 0, lambda m: None)


if __name__ == "__main__":
    unittest.main()

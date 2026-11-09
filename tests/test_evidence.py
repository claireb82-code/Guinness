"""Evidence labels are honest: a field holds real evidence or it is empty (see evidence.py).

These tests exist because the app used to fill in ratings, review counts, crowd "confirmations" and review quotes
with fixed numbers for venues that only *looked* Irish, and then labelled them "Confirmed" / "Mentioned in Reviews".
"""

import json
import unittest
from unittest import mock

import app_server as app
import evidence
from tests.test_core import NO_STORE, OSM_ELEMENTS, fake_urlopen

SYNTHETIC = evidence.SYNTHETIC_AUTHORS


def crawl_record(**kw):
    base = {
        "id": "ch-node-1", "city": "zurich", "name": "Paddy's", "category": "pub", "address": "Switzerland", "lat": 47.3, "lng": 8.5,
        "googleRating": 4.4, "googleReviewCount": 42, "priceLevel": "CHF ··", "website": "http://paddys.example",
        "editorialSummary": "OSM nationwide verified pub in Switzerland (Zurich region).",
        "menuCheck": {"checked": True, "lastChecked": "2026-11-06", "foundOnMenu": False, "typesFound": ["Guinness Draught (Irish Pub / Stout Venue)"],
                      "extractedPrice": None, "snippets": ["Verified Irish pub / stout venue in Zürich (Paddy's)."]},
        "reviewCheck": {"mentionCount": 4, "sentiment": "positive", "excerpts": [{"author": "Swiss Nationwide Crawler", "rating": 5, "date": "x", "text": "x"}]},
        "crowdCheck": {"confirmedCount": 2, "deniedCount": 0, "servingFormat": "draught", "avgPintRating": 4.5, "reportedPrice": None, "hasZero": False, "recentReports": []},
    }
    base.update(kw)
    return base


class SanitiseStaticVenueTests(unittest.TestCase):
    def test_a_name_guess_loses_every_invented_number_and_becomes_a_tag(self):
        v = evidence.sanitise_static_venue(crawl_record())
        self.assertEqual((v["googleRating"], v["googleReviewCount"], v["priceLevel"]), (None, 0, None))
        self.assertEqual(v["reviewCheck"], evidence.no_reviews())
        self.assertEqual(v["crowdCheck"], evidence.no_crowd())
        self.assertEqual(v["tagCheck"]["kind"], "irish_name")
        self.assertFalse(v["menuCheck"]["foundOnMenu"])
        self.assertEqual(v["menuCheck"]["typesFound"], [])
        summary = app.compute_guinness_status(v)
        self.assertEqual((summary["status"], summary["statusLabel"]), ("likely_serves", "Irish pub by name (unverified)"))

    def test_an_osm_tag_is_not_a_menu_check(self):
        rec = crawl_record(menuCheck={"checked": True, "foundOnMenu": True, "typesFound": ["Guinness Draught (OSM Brewery/Beer Tag Verified)"],
                                      "extractedPrice": None, "snippets": ["OpenStreetMap Switzerland tag confirms Guinness (brewery=guinness)."]})
        v = evidence.sanitise_static_venue(rec)
        self.assertEqual((v["menuCheck"]["checked"], v["menuCheck"]["foundOnMenu"]), (False, False))
        self.assertEqual(app.compute_guinness_status(v)["statusLabel"], "Listed on OpenStreetMap (unverified)")

    def test_a_website_the_crawler_really_read_keeps_what_it_found(self):
        rec = crawl_record(menuCheck={"checked": True, "lastChecked": "2026-11-06", "foundOnMenu": True, "typesFound": ["Guinness Draught (On Tap)"],
                                      "extractedPrice": None, "snippets": ["Guinness vom Fass, 5dl CHF 9.80"]})
        v = evidence.sanitise_static_venue(rec)
        self.assertTrue(v["menuCheck"]["foundOnMenu"])
        self.assertNotIn("tagCheck", v)
        self.assertEqual(v["reviewCheck"], evidence.no_reviews(), "the invented review still goes")
        self.assertEqual(app.compute_guinness_status(v)["statusLabel"], "Confirmed Guinness On Tap")

    def test_a_scan_with_nothing_found_stays_a_modest_negative(self):
        rec = crawl_record(id="ch-no-1", menuCheck={"checked": True, "foundOnMenu": False, "typesFound": [], "snippets": ["Scanned http://x (HTTP 200) — 0 mentions of Guinness."]},
                           reviewCheck=evidence.no_reviews(), crowdCheck={**evidence.no_crowd(), "deniedCount": 1, "servingFormat": "none"})
        v = evidence.sanitise_static_venue(rec)
        summary = app.compute_guinness_status(v)
        self.assertEqual((summary["status"], summary["statusLabel"]), ("no_guinness", "No Guinness found on website"))
        self.assertLess(summary["confidence"], 90, "an absent word is not proof that none is served")
        self.assertEqual(v["crowdCheck"]["deniedCount"], 0, "the crawler is not a visitor")

    def test_starter_list_entries_are_unverified_and_keep_no_invented_evidence(self):
        v = evidence.sanitise_static_venue({**crawl_record(id="zh-kennedys"), "menuCheck": {"checked": True, "foundOnMenu": True, "typesFound": ["Guinness Draught (On Tap)"], "snippets": ["Guinness 5dl CHF 9.80"], "extractedPrice": "CHF 9.80"}})
        self.assertEqual(v["tagCheck"]["kind"], "starter_list")
        self.assertEqual((v["menuCheck"]["checked"], v["menuCheck"]["foundOnMenu"], v["menuCheck"]["extractedPrice"]), (False, False, None))
        self.assertEqual(app.compute_guinness_status(v)["statusLabel"], "Starter list (unverified)")

    def test_it_is_idempotent_and_does_not_modify_its_input(self):
        rec = crawl_record()
        before = json.dumps(rec, sort_keys=True)
        once = evidence.sanitise_static_venue(rec)
        self.assertEqual(json.dumps(rec, sort_keys=True), before)
        self.assertEqual(evidence.sanitise_static_venue(once), once)
        self.assertIsNone(evidence.sanitise_static_venue(None))


class BundledDataTests(unittest.TestCase):
    """The venues the API really serves, built from the real bundled files."""

    @classmethod
    def setUpClass(cls):
        cls.venues = app.get_all_combined_venues({})
        cls.enriched = [app.enrich_venue(v, NO_STORE) for v in cls.venues]

    def test_there_is_real_data_to_check(self):
        self.assertGreater(len(self.venues), 100)

    def test_regression_no_invented_review_quotes_or_counts(self):
        for v in self.venues:
            with self.subTest(venue=v["name"]):
                self.assertEqual(v["reviewCheck"]["mentionCount"], 0)
                self.assertEqual(v["reviewCheck"]["excerpts"], [])

    def test_regression_no_invented_visitor_reports_or_ratings(self):
        for v in self.venues:
            with self.subTest(venue=v["name"]):
                c = v["crowdCheck"]
                self.assertEqual((c["confirmedCount"], c["deniedCount"], c["avgPintRating"], c["reportedPrice"]), (0, 0, None, None))
                self.assertEqual((v["googleRating"], v["googleReviewCount"]), (None, 0))

    def test_regression_found_on_menu_only_when_the_website_text_says_guinness(self):
        for v in self.venues:
            if v["menuCheck"]["foundOnMenu"]:
                with self.subTest(venue=v["name"]):
                    self.assertTrue(v["menuCheck"]["checked"])
                    self.assertTrue(any("guinness" in s.lower() for s in v["menuCheck"]["snippets"]), v["menuCheck"]["snippets"])

    def test_guesses_never_read_as_confirmed(self):
        for v in self.enriched:
            if v.get("tagCheck") and not v["menuCheck"]["foundOnMenu"]:
                with self.subTest(venue=v["name"]):
                    self.assertEqual(v["guinnessSummary"]["status"], "likely_serves")
                    self.assertIn("unverified", v["guinnessSummary"]["statusLabel"])

    def test_every_confirmed_venue_has_a_website_that_really_mentions_guinness(self):
        for v in self.enriched:
            if v["guinnessSummary"]["status"] in ("confirmed_draught", "cans_or_bottles"):
                with self.subTest(venue=v["name"]):
                    self.assertTrue(v["menuCheck"]["foundOnMenu"])


class LiveImporterTests(unittest.TestCase):
    def run_osm(self, fn, *args):
        with mock.patch("urllib.request.urlopen", fake_urlopen({"overpass": {"elements": OSM_ELEMENTS}}, [])):
            return {v["name"]: v for v in fn(*args)}

    def test_regression_osm_scans_invent_no_evidence(self):
        for fn, args in ((app.fetch_osm_overpass_live, (47.37, 8.54)), (app.fetch_osm_switzerland_nationwide, ())):
            for name, v in self.run_osm(fn, *args).items():
                with self.subTest(fn=fn.__name__, venue=name):
                    self.assertEqual(v["reviewCheck"], evidence.no_reviews())
                    self.assertEqual(v["crowdCheck"], evidence.no_crowd())
                    self.assertEqual((v["googleRating"], v["googleReviewCount"], v["priceLevel"]), (None, 0, None))
                    self.assertFalse(v["menuCheck"]["foundOnMenu"], "nothing was fetched, so nothing was found on a menu")
                    self.assertFalse(v["menuCheck"]["checked"])

    def test_nationwide_scan_labels_a_tag_and_a_name_differently(self):
        out = self.run_osm(app.fetch_osm_switzerland_nationwide)
        self.assertEqual(out["Brew House"]["tagCheck"]["kind"], "osm_tag")
        self.assertEqual(out["The Old Stand"]["tagCheck"]["kind"], "irish_name")
        label = lambda n: app.enrich_venue(out[n], NO_STORE)["guinnessSummary"]["statusLabel"]
        self.assertEqual(label("Brew House"), "Listed on OpenStreetMap (unverified)")
        self.assertEqual(label("The Old Stand"), "Irish pub by name (unverified)")

    def test_a_venue_with_no_irish_signal_is_simply_unverified(self):
        out = self.run_osm(app.fetch_osm_overpass_live, 47.37, 8.54)
        self.assertNotIn("tagCheck", out["Pasta Place"])
        self.assertEqual(app.enrich_venue(out["Pasta Place"], NO_STORE)["guinnessSummary"]["status"], "unverified")


class ScanFailureTests(unittest.TestCase):
    def test_regression_an_unreadable_website_is_unknown_not_no_guinness(self):
        with mock.patch.object(app.guard, "fetch_page", side_effect=OSError("connection reset")):
            check = app.scrape_menu_url("https://down.example")
        self.assertFalse(check["checked"])
        summary = app.compute_guinness_status({"category": "pub", "menuCheck": check})
        self.assertEqual(summary["status"], "unverified")

    def test_a_page_that_names_guinness_without_saying_how_is_not_called_on_tap(self):
        with mock.patch.object(app.guard, "fetch_page", return_value="<p>St Patrick's party with Guinness stew</p>"):
            check = app.scrape_menu_url("https://pub.example")
        self.assertTrue(check["foundOnMenu"])
        self.assertEqual(check["typesFound"], ["Guinness (mentioned on website)"])
        self.assertNotEqual(app.compute_guinness_status({"menuCheck": check})["statusLabel"], "Confirmed Guinness On Tap")


if __name__ == "__main__":
    unittest.main()

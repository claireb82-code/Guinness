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
        "crowdCheck": {"confirmedCount": 2, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": None, "hasZero": False, "recentReports": []},
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
        self.assertEqual((summary["status"], summary["statusLabel"], summary["reason"]), ("likely_serves", "Possible", "Irish-sounding name (not checked)"))

    def test_an_osm_tag_is_not_a_menu_check(self):
        rec = crawl_record(menuCheck={"checked": True, "foundOnMenu": True, "typesFound": ["Guinness Draught (OSM Brewery/Beer Tag Verified)"],
                                      "extractedPrice": None, "snippets": ["OpenStreetMap Switzerland tag confirms Guinness (brewery=guinness)."]})
        v = evidence.sanitise_static_venue(rec)
        self.assertEqual((v["menuCheck"]["checked"], v["menuCheck"]["foundOnMenu"]), (False, False))
        self.assertIn("OpenStreetMap lists Guinness", app.compute_guinness_status(v)["reason"])

    def test_a_website_the_crawler_really_read_keeps_what_it_found(self):
        rec = crawl_record(menuCheck={"checked": True, "lastChecked": "2026-11-06", "foundOnMenu": True, "typesFound": ["Guinness Draught (On Tap)"],
                                      "extractedPrice": None, "snippets": ["Guinness vom Fass, 5dl CHF 9.80"]})
        v = evidence.sanitise_static_venue(rec)
        self.assertTrue(v["menuCheck"]["foundOnMenu"])
        self.assertNotIn("tagCheck", v)
        self.assertEqual(v["reviewCheck"], evidence.no_reviews(), "the invented review still goes")
        self.assertEqual(app.compute_guinness_status(v)["reason"], "Its website lists Guinness on tap")

    def test_a_scan_with_nothing_found_stays_a_modest_negative(self):
        rec = crawl_record(id="ch-no-1", menuCheck={"checked": True, "foundOnMenu": False, "typesFound": [], "snippets": ["Scanned http://x (HTTP 200) — 0 mentions of Guinness."]},
                           reviewCheck=evidence.no_reviews(), crowdCheck={**evidence.no_crowd(), "deniedCount": 1, "servingFormat": "none"})
        v = evidence.sanitise_static_venue(rec)
        summary = app.compute_guinness_status(v)
        self.assertEqual((summary["status"], summary["statusLabel"], summary["reason"]), ("no_guinness", "No Guinness found", "Its website doesn't mention Guinness"))
        self.assertLess(summary["confidence"], 90, "an absent word is not proof that none is served")
        self.assertEqual(v["crowdCheck"]["deniedCount"], 0, "the crawler is not a visitor")

    def test_starter_list_entries_are_unverified_and_keep_no_invented_evidence(self):
        v = evidence.sanitise_static_venue({**crawl_record(id="zh-kennedys"), "menuCheck": {"checked": True, "foundOnMenu": True, "typesFound": ["Guinness Draught (On Tap)"], "snippets": ["Guinness 5dl CHF 9.80"], "extractedPrice": "CHF 9.80"}})
        self.assertEqual(v["tagCheck"]["kind"], "starter_list")
        self.assertEqual((v["menuCheck"]["checked"], v["menuCheck"]["foundOnMenu"], v["menuCheck"]["extractedPrice"]), (False, False, None))
        self.assertEqual(app.compute_guinness_status(v)["reason"], "On our list of Irish pubs (not checked)")

    def test_crawled_prices_come_from_the_text_after_guinness(self):
        rec = crawl_record(menuCheck={"checked": True, "foundOnMenu": True, "typesFound": ["x"], "extractedPrice": "CHF 5",
                                      "snippets": ["CARLSBERG 30 cl CHF 5.5 GUINNESS DRAUGHT 50 cl CHF 9.7 BROOKLYN CHF 6"]})
        self.assertEqual(evidence.sanitise_static_venue(rec)["menuCheck"]["extractedPrice"], "CHF 9.70")

    def test_it_is_idempotent_and_does_not_modify_its_input(self):
        rec = crawl_record()
        before = json.dumps(rec, sort_keys=True)
        once = evidence.sanitise_static_venue(rec)
        self.assertEqual(json.dumps(rec, sort_keys=True), before)
        self.assertEqual(evidence.sanitise_static_venue(once), once)
        self.assertIsNone(evidence.sanitise_static_venue(None))


class StarterSiteCheckTests(unittest.TestCase):
    """Starter-list venues: no hand-typed deep links, and a website read by the crawler counts only for what it really said."""

    def starter(self, **kw):
        return evidence.sanitise_static_venue(crawl_record(id="al-example-lugano", name="The Example Irish Pub Lugano", website="https://examplepub-lugano.example",
                                                           menuUrl="https://examplepub-lugano.example/birre", **kw))

    def read(self, **kw):
        return {"reachable": True, "checkedAt": "2026-11-11T10:00:00+00:00", "checkedUrl": "https://examplepub-lugano.example/", "foundOnMenu": False,
                "typesFound": [], "extractedPrice": None, "snippets": [], **kw}

    def test_regression_a_hand_typed_menu_link_is_dropped_and_the_website_remains(self):
        v = self.starter()
        self.assertNotIn("menuUrl", v, "nothing in this app ever opened /birre")
        self.assertEqual(v["website"], "https://examplepub-lugano.example")

    def test_every_starter_venue_has_a_website_and_no_guessed_deep_link(self):
        self.assertGreaterEqual(len(app.DEMO_VENUES), 20)
        for raw in app.DEMO_VENUES:
            self.assertTrue(raw.get("website"), f"{raw['id']} would lose its only link")
            self.assertNotIn("menuUrl", evidence.sanitise_static_venue(raw), raw["id"])

    def test_a_crawled_venues_checked_page_is_kept(self):
        self.assertEqual(evidence.sanitise_static_venue(crawl_record(menuUrl="http://paddys.example/drinks"))["menuUrl"], "http://paddys.example/drinks")

    def test_an_unreadable_website_changes_nothing(self):
        v = self.starter()
        self.assertEqual(evidence.apply_site_check(v, {"reachable": False, "error": "timed out"}), v)
        self.assertEqual(evidence.apply_site_check(v, None), v)
        self.assertEqual(app.compute_guinness_status(evidence.apply_site_check(v, {"reachable": False}))["reason"], "On our list of Irish pubs (not checked)")

    def test_a_pub_website_that_names_guinness_becomes_a_real_menu_check(self):
        v = evidence.apply_site_check(self.starter(), self.read(foundOnMenu=True, checkedUrl="https://examplepub-lugano.example/birre",
                                                                snippets=["BIRRE ALLA SPINA: Guinness Draught — Pint CHF 9.20"]))
        self.assertEqual((v["menuCheck"]["checked"], v["menuCheck"]["foundOnMenu"], v["menuCheck"]["extractedPrice"]), (True, True, "CHF 9.20"))
        self.assertEqual(v["menuCheck"]["lastChecked"], "2026-11-11T10:00:00+00:00")
        self.assertNotIn("tagCheck", v, "evidence replaces the guess")
        self.assertNotIn("priceHint", v)
        self.assertEqual(v["menuUrl"], "https://examplepub-lugano.example/birre", "the page that was really read")
        self.assertEqual(app.compute_guinness_status(v)["status"], "confirmed_draught")

    def test_a_read_site_without_guinness_is_not_proof_of_none(self):
        v = evidence.apply_site_check(self.starter(), self.read())
        self.assertTrue(v["menuCheck"]["checked"])
        self.assertFalse(v["menuCheck"]["foundOnMenu"])
        self.assertEqual(v["tagCheck"]["kind"], "starter_list", "the pub is still on our list")
        self.assertNotEqual(app.compute_guinness_status(v)["status"], "no_guinness")
        self.assertIn("website was read", v["menuCheck"]["snippets"][0])

    def test_a_restaurant_that_only_mentions_guinness_stays_a_hint(self):
        v = evidence.apply_site_check(self.starter(category="restaurant"), self.read(foundOnMenu=True, snippets=["Braised beef in Guinness"]))
        self.assertEqual(v["tagCheck"]["kind"], evidence.TAG_WEB)
        self.assertFalse(v["menuCheck"]["foundOnMenu"])
        self.assertNotEqual(app.compute_guinness_status(v)["status"], "confirmed_draught")

    def test_it_does_not_modify_its_input(self):
        v = self.starter()
        before = json.dumps(v, sort_keys=True)
        evidence.apply_site_check(v, self.read(foundOnMenu=True, snippets=["Guinness on tap"]))
        self.assertEqual(json.dumps(v, sort_keys=True), before)


class PriceTests(unittest.TestCase):
    def test_the_price_is_the_one_printed_after_guinness_not_the_neighbouring_beer(self):
        # a real line from the crawl: the first price on it (7,80) belongs to a cider
        line = "pezial 5dl / 5,7% 7,80 CHF Cidre Möhl Straight Appel 3,3dl / 4,5% 6,50 CHF Guinness Draught Dose 5dl / 4,2% 8,50 CHF IPA Fleur de Lyss 7,50 CHF"
        self.assertEqual(evidence.price_near_guinness([line]), "CHF 8.50")

    def test_swiss_price_formats(self):
        for text, want in [("Guinness 5dl Fr. 9.-", "CHF 9.00"), ("Guinness vom Fass CHF 9.80", "CHF 9.80"), ("GUINNESS 9,50 CHF", "CHF 9.50"), ("Guinness SFr 10", "CHF 10.00")]:
            with self.subTest(text=text):
                self.assertEqual(evidence.price_near_guinness([text]), want)

    def test_no_price_after_guinness_means_no_price(self):
        for text in ["Kilkenny CHF 7 Guinness (ask the bar)", "Guinness stew with Irish whiskey", "Guinness 0.5% abv", "Guinness CHF 900"]:
            with self.subTest(text=text):
                self.assertIsNone(evidence.price_near_guinness([text]))
        self.assertIsNone(evidence.price_near_guinness(None))

    def test_a_real_scan_extracts_the_price(self):
        page = "<ul><li>Kilkenny 5dl CHF 8.00</li><li>Guinness Draught 5dl CHF 9.80</li></ul>"
        with mock.patch.object(app.guard, "fetch_page", return_value=page):
            check = app.scrape_menu_url("https://pub.example")
        self.assertEqual(check["extractedPrice"], "CHF 9.80")

    def test_regression_starter_list_prices_are_kept_but_marked_as_hints(self):
        """They vanished when the invented evidence was removed; the venue panel and cards show them as 'unchecked'."""
        by = {v["name"]: v for v in app.get_all_combined_venues({})}
        kennedys = by["Kennedy's Irish Pub"]
        self.assertEqual(kennedys["priceHint"]["price"], "CHF 9.80")
        self.assertIsNone(kennedys["menuCheck"]["extractedPrice"], "it was not read from the venue, so it is not a scan result")
        self.assertIsNone(kennedys["crowdCheck"]["reportedPrice"])
        self.assertGreater(sum(1 for v in by.values() if v.get("priceHint")), 30)


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
                self.assertEqual((c["confirmedCount"], c["deniedCount"], c["reportedPrice"]), (0, 0, None))
                self.assertNotIn("avgPintRating", c)
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
                    self.assertEqual(v["guinnessSummary"]["statusLabel"], "Possible")
                    self.assertRegex(v["guinnessSummary"]["reason"], r"not checked|not clearly on a menu")

    def test_regression_every_scanned_price_is_printed_after_guinness_in_the_snippets(self):
        for v in self.venues:
            price = v["menuCheck"].get("extractedPrice")
            if price:
                with self.subTest(venue=v["name"]):
                    self.assertTrue(v["menuCheck"]["foundOnMenu"])
                    self.assertEqual(price, evidence.price_near_guinness(v["menuCheck"]["snippets"]))

    def test_labels_are_the_plain_tiers_and_every_venue_says_why(self):
        """A visitor sees a short tier and one line of reason, never internal jargon."""
        tiers = {"Confirmed", "Confirmed (cans / bottles)", "Possible", "No Guinness found", "Not checked yet"}
        for v in self.enriched:
            summary = v["guinnessSummary"]
            with self.subTest(venue=v["name"]):
                self.assertIn(summary["statusLabel"], tiers)
                self.assertTrue(summary["reason"])
                self.assertNotRegex(summary["reason"] + summary["statusLabel"], r"(?i)starter|crawl|heuristic|tagCheck|confidence")

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
        reason = lambda n: app.enrich_venue(out[n], NO_STORE)["guinnessSummary"]["reason"]
        self.assertIn("OpenStreetMap lists Guinness", reason("Brew House"))
        self.assertEqual(reason("The Old Stand"), "Irish-sounding name (not checked)")

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
        self.assertNotIn("on tap", app.compute_guinness_status({"menuCheck": check})["reason"])


if __name__ == "__main__":
    unittest.main()

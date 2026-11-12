"""Venues the site owner has checked by hand on Google Maps: removed ones never come back, reviewed ones are never listed for review again."""

import json
import os
import tempfile
import unittest
from unittest import mock

import app_server as app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def write(doc):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(doc, f)
    f.close()
    return f.name


class ExclusionTests(unittest.TestCase):
    def test_an_excluded_id_is_never_served_whatever_list_it_comes_from(self):
        path = write({"excluded": [{"id": "ch-ov-x1"}, {"id": "zh-kennedys"}, {"id": "c1"}]})
        crawl = [{"id": "ch-ov-x1", "name": "Gone Pub", "city": "bern"}, {"id": "ch-ov-ok", "name": "Fine Pub", "city": "bern"}]
        store = {"customVenues": [{"id": "c1", "name": "Community Pub", "city": "bern", "address": "A"}]}
        try:
            with mock.patch.object(app, "EXCLUDED_VENUES_PATH", path), mock.patch.object(app, "load_crawl_venues", lambda: crawl):
                ids = [v["id"] for v in app.get_all_combined_venues(store)]
        finally:
            os.unlink(path)
        self.assertIn("ch-ov-ok", ids)
        for gone in ("ch-ov-x1", "zh-kennedys", "c1"):
            self.assertNotIn(gone, ids)

    def test_a_missing_or_malformed_file_excludes_nothing(self):
        for content in (None, '{"excluded": "x"}', '{"excluded": [1, {"name": "no id"}]}', "not json"):
            path = write({}) if content is None else None
            if content is not None:
                f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
                f.write(content)
                f.close()
                path = f.name
            try:
                with mock.patch.object(app, "EXCLUDED_VENUES_PATH", path):
                    self.assertEqual(app.load_excluded_ids(), set(), content)
            finally:
                os.unlink(path)
        with mock.patch.object(app, "EXCLUDED_VENUES_PATH", "/nonexistent.json"):
            self.assertEqual(app.load_excluded_ids(), set())

    def test_reviewed_ids_include_the_kept_the_investigated_and_the_removed(self):
        rev = write({"reviewed": [{"id": "a", "decision": "keep"}, {"id": "b", "decision": "investigate"}]})
        exc = write({"excluded": [{"id": "c"}]})
        try:
            with mock.patch.object(app, "REVIEWED_VENUES_PATH", rev), mock.patch.object(app, "EXCLUDED_VENUES_PATH", exc):
                self.assertEqual(app.load_reviewed_ids(), {"a", "b", "c"})
        finally:
            os.unlink(rev)
            os.unlink(exc)


class ExclusionInLiveScansTests(unittest.TestCase):
    """Regression: 'Sonas Irish Pub Davos' was removed by id, but 'Scan around me' asks OpenStreetMap again, which lists it under a new id."""

    ENTRIES = {"excluded": [{"id": "ch-ov-sonas", "name": "Sonas Irish Pub Davos", "lat": 46.7969, "lng": 9.8216}],
               "duplicates": [{"id": "ch-node-shamrock-osm", "name": "Shamrock Irish Pub", "lat": 47.0503, "lng": 8.3093, "duplicateOf": "lu-shamrock-luzern"}]}

    def run_with(self, venues):
        path = write(self.ENTRIES)
        try:
            with mock.patch.object(app, "EXCLUDED_VENUES_PATH", path):
                return [v["name"] for v in app.drop_excluded(venues)]
        finally:
            os.unlink(path)

    def v(self, name, lat, lng, vid="osm-1"):
        return {"id": vid, "name": name, "lat": lat, "lng": lng}

    def test_the_same_place_under_a_new_id_is_dropped(self):
        for name in ("Sonas Irish Pub Davos", "Sonas Irish Pub"):
            self.assertEqual(self.run_with([self.v(name, 46.79695, 9.82165)]), [], name)

    def test_the_same_name_somewhere_else_is_kept(self):
        self.assertEqual(self.run_with([self.v("Sonas Irish Pub", 47.37, 8.54)]), ["Sonas Irish Pub"])

    def test_a_different_pub_next_door_is_kept(self):
        self.assertEqual(self.run_with([self.v("The Dubliner", 46.79695, 9.82165)]), ["The Dubliner"])

    def test_a_venue_that_adds_a_distinguishing_word_is_a_different_place(self):
        self.assertEqual(self.run_with([self.v("Sonas Irish Pub Zermatt", 46.79695, 9.82165)]), ["Sonas Irish Pub Zermatt"])

    def test_a_duplicate_is_matched_only_by_a_near_identical_name_so_the_pub_it_duplicates_stays(self):
        kept = self.v("Shamrock Irish Pub Luzern", 47.0510, 8.3100, vid="lu-shamrock-luzern")
        self.assertEqual(self.run_with([self.v("Shamrock Irish Pub", 47.0503, 8.3093), kept]), ["Shamrock Irish Pub Luzern"])

    def test_scan_around_me_does_not_show_or_store_an_excluded_venue(self):
        osm = [self.v("Sonas Irish Pub", 46.79695, 9.82165, vid="osm-77"), self.v("Good Pub", 46.80, 9.83, vid="osm-78")]
        saved = []
        path = write(self.ENTRIES)
        try:
            with mock.patch.object(app, "EXCLUDED_VENUES_PATH", path), mock.patch.object(app, "fetch_osm_overpass_live", return_value=osm), \
                    mock.patch.object(app, "upsert_gmaps_venues_into_store", lambda store, vs: saved.extend(vs)):
                shown = app.drop_excluded(app.fetch_osm_overpass_live(46.8, 9.83))
                app.upsert_gmaps_venues_into_store({}, shown)
        finally:
            os.unlink(path)
        self.assertEqual([v["name"] for v in shown], ["Good Pub"])
        self.assertEqual([v["name"] for v in saved], ["Good Pub"])

    def test_a_scan_already_saved_before_the_exclusion_is_filtered_when_listed(self):
        store = {"googleMapsVenues": [self.v("Sonas Irish Pub", 46.79695, 9.82165, vid="osm-77")]}
        path = write(self.ENTRIES)
        try:
            with mock.patch.object(app, "EXCLUDED_VENUES_PATH", path):
                names = [v["name"] for v in app.get_all_combined_venues(store)]
        finally:
            os.unlink(path)
        self.assertNotIn("Sonas Irish Pub", names)

    def test_real_exclusion_file_carries_positions_for_every_entry(self):
        with open(os.path.join(ROOT, "server", "data", "excluded_venues.json"), encoding="utf-8") as f:
            doc = json.load(f)
        for e in doc["excluded"] + doc["duplicates"]:
            self.assertTrue(e["name"] and isinstance(e["lat"], float) and isinstance(e["lng"], float), e["id"])

    def test_the_real_exclusions_catch_sonas_and_keep_the_kept_venues_next_to_duplicates(self):
        sonas = next(e for e in json.load(open(os.path.join(ROOT, "server", "data", "excluded_venues.json"), encoding="utf-8"))["excluded"] if "Sonas" in e["name"])
        self.assertEqual(app.drop_excluded([self.v("Sonas Irish Pub", sonas["lat"], sonas["lng"])]), [])
        starter = next(v for v in app.DEMO_VENUES if v["id"] == "lu-shamrock-luzern")
        self.assertEqual(len(app.drop_excluded([starter])), 1)


class MenuReadingTests(unittest.TestCase):
    """Kennedy's drinks menu is a PDF whose text is drawn as shapes, so it was read by eye and recorded as evidence."""

    def kennedys(self):
        return next(v for v in app.get_all_combined_venues({}) if v["id"] == "zh-kennedys")

    def test_kennedys_is_confirmed_on_tap_from_its_own_menu(self):
        v = self.kennedys()
        s = app.compute_guinness_status(v)
        self.assertEqual((s["statusLabel"], s["servingFormat"]), ("Confirmed", "draught"))
        self.assertEqual(s["reason"], "Its website lists Guinness on tap")
        self.assertEqual(v["menuCheck"]["extractedPrice"], "CHF 10.00", "the 5 dl price printed first after Guinness")
        self.assertTrue(v["menuUrl"].endswith("26_Drinks_Menu.pdf"))
        self.assertNotIn("tagCheck", v)
        self.assertNotIn("priceHint", v, "the unchecked starter price is replaced by what the menu says")

    def test_the_reading_says_how_it_was_made_and_nothing_comes_from_google(self):
        with open(os.path.join(ROOT, "server", "data", "menu_readings.json"), encoding="utf-8") as f:
            doc = json.load(f)
        r = doc["readings"]["zh-kennedys"]
        self.assertIn("by eye", r["readBy"])
        self.assertIn("kennedys.ch", r["checkedUrl"])
        self.assertNotIn("googleapis", json.dumps(doc).lower())
        self.assertNotIn("placeId", json.dumps(doc))

    def test_a_reading_applies_to_any_venue_and_a_bad_file_applies_to_none(self):
        path = write({"readings": {"zh-kennedys": {"reachable": True, "foundOnMenu": False, "checkedAt": "2026-11-12", "snippets": []}}})
        try:
            with mock.patch.object(app, "MENU_READINGS_PATH", path):
                v = self.kennedys()
        finally:
            os.unlink(path)
        self.assertEqual((v["menuCheck"]["checked"], v["menuCheck"]["foundOnMenu"]), (True, False), "a reading that finds nothing says so")
        for content in ("not json", '{"readings": ["x"]}', '{"readings": {"a": 1}}'):
            f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
            f.write(content)
            f.close()
            try:
                with mock.patch.object(app, "MENU_READINGS_PATH", f.name):
                    self.assertEqual(app.load_menu_readings(), {}, content)
            finally:
                os.unlink(f.name)

    def test_the_readings_file_is_deployed(self):
        with open(os.path.join(ROOT, "vercel.json"), encoding="utf-8") as f:
            self.assertIn("server/data/*.json", f.read(), "menu_readings.json is bundled by the data glob")


class SavedScanTests(unittest.TestCase):
    """Regression: a saved 'Scan menu' result that found nothing (it reads one page) replaced Kennedy's hand-read menu evidence on the live
    site, so it showed 'Possible: reported by 1 visitor' with no price instead of Confirmed on tap."""

    NOTHING = {"checked": True, "lastChecked": "2026-11-12T09:00:00+00:00", "foundOnMenu": False, "typesFound": [], "extractedPrice": None,
               "snippets": ["Scanned https://www.kennedys.ch/ - no explicit 'Guinness' text found on public HTML page."]}

    def enriched(self, scan, report=False):
        store = {"menuScans": {"zh-kennedys": scan}} if scan else {}
        if report:
            store["crowdReports"] = {"zh-kennedys": [{"servingFormat": "draught", "price": "CHF 10.00"}]}
        venue = next(v for v in app.get_all_combined_venues(store) if v["id"] == "zh-kennedys")
        return app.enrich_venue(venue, store)

    def test_a_scan_that_found_nothing_does_not_erase_a_menu_that_was_read(self):
        v = self.enriched(self.NOTHING, report=True)
        self.assertEqual(v["guinnessSummary"]["statusLabel"], "Confirmed")
        self.assertEqual(v["guinnessSummary"]["servingFormat"], "draught")
        self.assertEqual(v["menuCheck"]["extractedPrice"], "CHF 10.00")
        self.assertTrue(v["menuUrl"].endswith("26_Drinks_Menu.pdf"))

    def test_a_scan_that_finds_guinness_still_updates_the_check(self):
        found = {"checked": True, "lastChecked": "2026-11-13T09:00:00+00:00", "foundOnMenu": True, "typesFound": ["Guinness Draught (On Tap)"],
                 "extractedPrice": "CHF 10.50", "snippets": ["Guinness on tap 5dl CHF 10.50"]}
        self.assertEqual(self.enriched(found)["menuCheck"]["extractedPrice"], "CHF 10.50")

    def test_a_scan_still_applies_to_a_venue_with_no_menu_evidence(self):
        store = {"menuScans": {"zh-lion-pub": self.NOTHING}}
        venue = next(v for v in app.get_all_combined_venues(store) if v["id"] == "zh-lion-pub")
        v = app.enrich_venue(venue, store)
        self.assertTrue(v["menuCheck"]["checked"])
        self.assertFalse(v["menuCheck"]["foundOnMenu"])

    def test_a_visitor_report_adds_to_the_menu_evidence_not_replaces_it(self):
        v = self.enriched(None, report=True)
        self.assertEqual(v["guinnessSummary"]["statusLabel"], "Confirmed")
        self.assertEqual(v["crowdCheck"]["confirmedCount"], 1)


class OwnerReviewDataTests(unittest.TestCase):
    """The 2026-11-12 review of 46 Overture venues and 19 starter venues, pinned."""

    def test_the_fifteen_removed_venues_are_gone_from_what_the_app_serves(self):
        with open(os.path.join(ROOT, "server", "data", "excluded_venues.json"), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(len(doc["excluded"]), 15)
        names = {e["id"]: e["name"] for e in doc["excluded"]}
        served = {v["id"] for v in app.get_all_combined_venues({})}
        self.assertFalse(served & set(names), sorted(names[i] for i in served & set(names)))

    def test_the_removed_ones_are_not_in_the_reviewed_list_twice_and_nothing_overlaps(self):
        with open(os.path.join(ROOT, "server", "data", "reviewed_venues.json"), encoding="utf-8") as f:
            rows = json.load(f)["reviewed"]
        ids = [r["id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)), "a venue is reviewed once")
        self.assertFalse(set(ids) & app._ids_in(app.EXCLUDED_VENUES_PATH, "excluded"))
        self.assertEqual({r["decision"] for r in rows}, {"keep", "investigate"})
        self.assertEqual(sum(1 for r in rows if r["decision"] == "investigate"), 8, "11 minus the 3 merged duplicates")
        self.assertFalse(set(ids) & app._ids_in(app.EXCLUDED_VENUES_PATH, "duplicates"))

    def test_reviewed_venues_stay_on_the_map_except_the_removed(self):
        with open(os.path.join(ROOT, "server", "data", "reviewed_venues.json"), encoding="utf-8") as f:
            rows = json.load(f)["reviewed"]
        served = {v["id"] for v in app.get_all_combined_venues({})}
        self.assertEqual([r["name"] for r in rows if r["id"] not in served], [], "keep and investigate stay listed")

    def test_the_three_duplicates_are_listed_once_under_the_venue_they_duplicate(self):
        with open(os.path.join(ROOT, "server", "data", "excluded_venues.json"), encoding="utf-8") as f:
            dups = json.load(f)["duplicates"]
        self.assertEqual(sorted(d["name"] for d in dups), ["Brian's Irish Bar", "MFG", "Shamrock Irish Pub"])
        served = {v["id"] for v in app.get_all_combined_venues({})}
        for d in dups:
            self.assertNotIn(d["id"], served, d["name"])
            self.assertIn(d["duplicateOf"], served, f"{d['name']} must point at a venue that is still shown")

    def test_a_duplicate_id_is_excluded_like_a_removed_one(self):
        path = write({"excluded": [{"id": "a"}], "duplicates": [{"id": "b", "duplicateOf": "a"}]})
        try:
            with mock.patch.object(app, "EXCLUDED_VENUES_PATH", path):
                self.assertEqual(app.load_excluded_ids(), {"a", "b"})
        finally:
            os.unlink(path)

    def test_the_exclusion_file_is_deployed(self):
        with open(os.path.join(ROOT, "vercel.json"), encoding="utf-8") as f:
            self.assertIn("server/data/*.json", f.read(), "excluded_venues.json is bundled by the data glob")


if __name__ == "__main__":
    unittest.main()

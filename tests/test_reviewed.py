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
        self.assertEqual(sum(1 for r in rows if r["decision"] == "investigate"), 11)

    def test_reviewed_venues_stay_on_the_map_except_the_removed(self):
        with open(os.path.join(ROOT, "server", "data", "reviewed_venues.json"), encoding="utf-8") as f:
            rows = json.load(f)["reviewed"]
        served = {v["id"] for v in app.get_all_combined_venues({})}
        self.assertEqual([r["name"] for r in rows if r["id"] not in served], [], "keep and investigate stay listed")

    def test_the_exclusion_file_is_deployed(self):
        with open(os.path.join(ROOT, "vercel.json"), encoding="utf-8") as f:
            self.assertIn("excluded_venues.json", f.read())


if __name__ == "__main__":
    unittest.main()

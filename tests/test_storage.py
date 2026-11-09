import json
import os
import tempfile
import unittest
from unittest import mock

import guard
import storage
from tests.helpers import FakeRedis


class FileBackendTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "sub", "store.json")
        self.backend = storage.FileBackend(self.path, os.path.join(self.dir.name, "missing.json"))

    def test_empty_when_nothing_exists(self):
        self.assertEqual(self.backend.load(), {"crowdReports": {}, "menuScans": {}, "customVenues": [], "googleMapsVenues": [], "venueLocations": {}})

    def test_a_moved_venue_round_trips_through_the_file(self):
        store = self.backend.load()
        self.backend.set_location(store, "custom-1", {"lat": 46.8, "lng": 9.83})
        self.assertEqual(self.backend.load()["venueLocations"], {"custom-1": {"lat": 46.8, "lng": 9.83}})

    def test_writes_round_trip_through_the_file(self):
        store = self.backend.load()
        self.backend.add_report(store, "v1", {"id": "r1", "note": "x"})
        self.backend.add_venue(store, {"id": "c1", "name": "Pub"})
        self.backend.set_scan(store, "v1", {"checked": True})
        fresh = storage.FileBackend(self.path, "").load()
        self.assertEqual(fresh["crowdReports"]["v1"][0]["id"], "r1")
        self.assertEqual(fresh["customVenues"][0]["id"], "c1")
        self.assertEqual(fresh["menuScans"]["v1"], {"checked": True})

    def test_newest_first_and_per_venue_cap(self):
        store = self.backend.load()
        for i in range(210):
            self.backend.add_report(store, "v1", {"id": f"r{i}"})
        reports = store["crowdReports"]["v1"]
        self.assertEqual(reports[0]["id"], "r209")
        self.assertEqual(len(reports), 200)

    def test_corrupt_file_falls_back_to_empty(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertEqual(self.backend.load()["customVenues"], [])

    def test_ephemeral_backend_refuses_submissions(self):
        self.assertTrue(self.backend.accepts_submissions)
        self.assertFalse(storage.FileBackend(self.path, "", ephemeral=True).accepts_submissions)

    def test_in_memory_counter_counts_and_expires(self):
        with mock.patch("storage.time.time", return_value=1000.0):
            self.assertEqual([self.backend.incr("k", 60) for _ in range(3)], [1, 2, 3])
            self.assertEqual(self.backend.incr("other", 60), 1)
        with mock.patch("storage.time.time", return_value=1061.0):
            self.assertEqual(self.backend.incr("k", 60), 1)  # window rolled over


class RedisBackendTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis().start()
        self.addCleanup(self.redis.stop)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def backend(self, **kw):
        # A separate instance == a separate serverless function with its own (empty) /tmp.
        path = os.path.join(tempfile.mkdtemp(dir=self.dir.name), "store.json")
        return storage.RedisBackend(kw.get("url", self.redis.url), kw.get("token", "test-token"), path, "", prefix="t:")

    def test_reports_written_by_one_instance_are_visible_to_another(self):
        """The whole point: data survives instances and is shared between visitors."""
        a, b = self.backend(), self.backend()
        store = a.load()
        a.add_report(store, "v1", {"id": "r1", "servingFormat": "draught", "note": "creamy"})
        a.add_report(store, "v1", {"id": "r2", "servingFormat": "none"})
        seen = b.load()
        self.assertEqual([r["id"] for r in seen["crowdReports"]["v1"]], ["r2", "r1"])  # newest first
        self.assertNotIn("venueId", seen["crowdReports"]["v1"][0])

    def test_custom_venues_and_scans_are_shared(self):
        a, b = self.backend(), self.backend()
        s = a.load()
        a.add_venue(s, {"id": "custom-1", "name": "Pub"})
        a.set_scan(s, "zh-x", {"checked": True, "foundOnMenu": True})
        seen = b.load()
        self.assertEqual(seen["customVenues"][0]["name"], "Pub")
        self.assertEqual(seen["menuScans"]["zh-x"]["foundOnMenu"], True)

    def test_a_moved_venue_is_shared_between_instances_and_junk_is_skipped(self):
        a, b = self.backend(), self.backend()
        a.set_location(a.load(), "custom-1", {"lat": 46.8, "lng": 9.83})
        self.redis.data.setdefault("t:locations", {})["custom-2"] = "not json"  # a malformed entry must not break loading
        seen = b.load()
        self.assertEqual(seen["venueLocations"], {"custom-1": {"lat": 46.8, "lng": 9.83}})

    def test_unicode_survives(self):
        a = self.backend()
        a.add_report(a.load(), "v", {"id": "r", "note": "Zürich – crème 🍺"})
        self.assertEqual(self.backend().load()["crowdReports"]["v"][0]["note"], "Zürich – crème 🍺")

    def test_lists_are_capped(self):
        a = self.backend()
        store = a.load()
        with mock.patch.object(storage, "MAX_REPORTS", 3):
            for i in range(6):
                a.add_report(store, "v", {"id": f"r{i}"})
            ids = [r["id"] for r in self.backend().load()["crowdReports"]["v"]]
        self.assertEqual(ids, ["r5", "r4", "r3"])

    def test_malformed_entries_are_skipped_not_fatal(self):
        self.redis.data["t:reports"] = ["{not json", json.dumps({"id": "ok", "venueId": "v"}), json.dumps({"id": "no-venue"}), "123"]
        self.redis.data["t:venues"] = ["garbage"]
        self.redis.data["t:scans"] = {"v": "garbage", "w": json.dumps({"checked": True})}
        seen = self.backend().load()
        self.assertEqual(list(seen["crowdReports"]), ["v"])
        self.assertEqual(seen["customVenues"], [])
        self.assertEqual(list(seen["menuScans"]), ["w"])

    def test_read_degrades_when_the_database_is_down(self):
        b = self.backend()
        self.redis.fail = True
        with mock.patch("sys.stderr"):
            seen = b.load()
        self.assertEqual(seen["crowdReports"], {})  # still returns a usable store

    def test_write_fails_loudly_when_the_database_is_down(self):
        b = self.backend()
        store = b.load()
        self.redis.fail = True
        with self.assertRaises(storage.StorageError):
            b.add_report(store, "v", {"id": "r"})
        self.assertEqual(store["crowdReports"], {})  # nothing pretends to have been saved

    def test_wrong_token_is_a_storage_error_on_write(self):
        b = self.backend(token="wrong")
        with mock.patch("sys.stderr"):
            store = b.load()
        with self.assertRaisesRegex(storage.StorageError, "rejected.*401"):
            b.add_venue(store, {"id": "c"})

    def test_unreachable_database(self):
        b = storage.RedisBackend("http://127.0.0.1:9", "t", "/nonexistent/x.json", "", timeout=1)
        with self.assertRaises(storage.StorageError):
            b.set_scan({}, "v", {})

    def test_token_is_sent_as_bearer_and_url_must_be_https(self):
        self.backend().add_venue({}, {"id": "x"})
        self.assertGreaterEqual(self.redis.requests, 1)
        with self.assertRaises(ValueError):
            storage.RedisBackend("http://redis.example.com", "t", "/x", "")  # token would travel in clear text
        storage.RedisBackend("https://redis.example.com", "t", "/x", "")
        storage.RedisBackend("http://127.0.0.1:1234", "t", "/x", "")  # localhost http is fine (tests/dev)

    def test_rate_limit_counters_are_shared_between_instances_and_always_expire(self):
        a, b = self.backend(), self.backend()
        self.assertEqual([a.incr("rl:write:1.2.3.4", 3600), b.incr("rl:write:1.2.3.4", 3600), a.incr("rl:write:1.2.3.4", 3600)], [1, 2, 3])
        self.assertEqual(self.redis.expiry["t:rl:write:1.2.3.4"], 3600)  # a counter can never be left without an expiry
        limiter = guard.RateLimiter(self.backend())
        results = [limiter.check("scan", "9.9.9.9", 2, 60)[0] for _ in range(4)]
        self.assertEqual(results, [True, True, False, False])


class BuildBackendTests(unittest.TestCase):
    def build(self, env, vercel=False):
        return storage.build_backend(env, "/tmp/x.json", "/tmp/y.json", vercel)

    def test_selection(self):
        self.assertEqual(self.build({}).name, "file")
        self.assertTrue(self.build({}).accepts_submissions)
        self.assertFalse(self.build({}, vercel=True).accepts_submissions)  # ephemeral /tmp: refuse rather than lose data
        for u, t in [("KV_REST_API_URL", "KV_REST_API_TOKEN"), ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN")]:
            b = self.build({u: "https://x.upstash.io", t: "tok"}, vercel=True)
            self.assertEqual(b.name, "redis")
            self.assertTrue(b.accepts_submissions)

    def test_url_without_token_is_ignored(self):
        self.assertEqual(self.build({"KV_REST_API_URL": "https://x.upstash.io"}).name, "file")

    def test_custom_prefix(self):
        b = self.build({"KV_REST_API_URL": "https://x.upstash.io", "KV_REST_API_TOKEN": "t", "GUINNESS_KEY_PREFIX": "prod:"})
        self.assertEqual(b.prefix, "prod:")


if __name__ == "__main__":
    unittest.main()

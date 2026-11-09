"""overpass.py: several servers, retries, caching and friendly errors, against real local HTTP servers
that behave like busy / broken Overpass mirrors (scripted per request)."""

import json
import os
import time
import unittest
import urllib.parse
from unittest import mock

import app_server as app
import overpass
from tests.helpers import QuietHandler, serve, stop
from tests.test_api import ApiTestCase

OK = {"version": 0.6, "elements": [{"type": "node", "id": 1, "lat": 47.37, "lon": 8.54, "tags": {"amenity": "pub", "name": "Mirror Pub"}}]}
QUERY = '[out:json];node["amenity"="pub"](around:100,47.37,8.54);out;'


class FakeServer:
    """A mirror that answers requests from a script: ('ok', payload) | ('status', code) | ('body', text) |
    ('json', value) | ('sleep', seconds). The last step repeats. Records every request."""

    def __init__(self, *steps):
        self.steps, self.requests = list(steps), []
        outer = self

        class Handler(QuietHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode()
                outer.requests.append({"form": urllib.parse.parse_qs(body), "headers": dict(self.headers)})
                kind, value = outer.steps[min(len(outer.requests) - 1, len(outer.steps) - 1)]
                if kind == "sleep":
                    time.sleep(value)
                    kind, value = "ok", OK
                try:
                    if kind == "status":
                        self.send_response(value)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    payload = value if kind == "body" else json.dumps(OK if kind == "ok" and value is None else value)
                    raw = payload.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass  # the client gave up (a timeout test)

        self.server, base = serve(Handler)
        self.url = base + "/api/interpreter"

    def close(self):
        stop(self.server)


class OverpassTestCase(unittest.TestCase):
    def setUp(self):
        overpass.clear_cache()
        self.servers = []
        self.addCleanup(overpass.clear_cache)

    def mirror(self, *steps):
        server = FakeServer(*steps)
        self.servers.append(server)
        self.addCleanup(server.close)
        return server

    def run_query(self, servers, **kw):
        kw.setdefault("attempt_seconds", 3)
        kw.setdefault("rounds", 1)
        with mock.patch.dict(os.environ, {"OVERPASS_CACHE_SECONDS": kw.pop("cache", "0"), "OVERPASS_RETRY_PAUSE_SECONDS": "0"}):
            return overpass.run(QUERY, urls=[s.url for s in servers], **kw)


class EndpointConfigTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(overpass.endpoints(""), overpass.DEFAULT_URLS)
        self.assertEqual(overpass.DEFAULT_URLS[0], "https://overpass-api.de/api/interpreter")
        self.assertGreaterEqual(len(overpass.DEFAULT_URLS), 2, "there must be at least one backup")

    def test_configured_urls_are_used_in_order_and_junk_is_ignored(self):
        raw = " https://a.example/i , ftp://b.example/i, not a url ,,http://c.example/i "
        self.assertEqual(overpass.endpoints(raw), ("https://a.example/i", "http://c.example/i"))
        self.assertEqual(overpass.endpoints("ftp://x, javascript:1, ???"), overpass.DEFAULT_URLS)

    def test_reads_the_environment(self):
        with mock.patch.dict(os.environ, {"OVERPASS_URLS": "https://only.example/i"}):
            self.assertEqual(overpass.endpoints(), ("https://only.example/i",))


class SingleServerTests(OverpassTestCase):
    def test_a_healthy_primary_is_used_alone_and_gets_a_form_encoded_query(self):
        primary, backup = self.mirror(("ok", None)), self.mirror(("ok", None))
        self.assertEqual(self.run_query([primary, backup]), OK)
        self.assertEqual((len(primary.requests), len(backup.requests)), (1, 0))
        request = primary.requests[0]
        self.assertEqual(request["form"]["data"], [QUERY])
        self.assertIn("StoutScout", request["headers"]["User-Agent"])


class FailoverTests(OverpassTestCase):
    def assert_falls_through(self, *broken_steps):
        primary, backup = self.mirror(*broken_steps), self.mirror(("ok", None))
        self.assertEqual(self.run_query([primary, backup]), OK)
        self.assertEqual((len(primary.requests), len(backup.requests)), (1, 1))

    def test_overload_statuses_move_on_to_the_next_server(self):
        for status in (429, 500, 502, 503, 504, 403, 404):
            with self.subTest(status=status):
                self.assert_falls_through(("status", status))

    def test_a_timeout_moves_on_quickly(self):
        primary, backup = self.mirror(("sleep", 1.5)), self.mirror(("ok", None))
        started = time.monotonic()
        self.assertEqual(self.run_query([primary, backup], attempt_seconds=0.3), OK)
        self.assertLess(time.monotonic() - started, 1.2)

    def test_http_200_with_a_server_side_timeout_or_memory_remark_counts_as_failure(self):
        for remark in ('runtime error: Query timed out in "query" at line 3 after 16 seconds.', "runtime error: Query ran out of memory", "Too many requests, rate limited"):
            with self.subTest(remark=remark):
                self.assert_falls_through(("json", {"elements": [], "remark": remark}))

    def test_a_harmless_remark_is_accepted(self):
        primary = self.mirror(("json", {**OK, "remark": "note: using the 2026 data set"}))
        self.assertEqual(self.run_query([primary])["elements"], OK["elements"])

    def test_html_error_pages_and_non_objects_move_on(self):
        self.assert_falls_through(("body", "<html><body>502 Bad Gateway</body></html>"))
        self.assert_falls_through(("body", ""))
        self.assert_falls_through(("json", [1, 2, 3]))

    def test_a_dead_server_moves_on(self):
        backup = self.mirror(("ok", None))
        gone = type("Dead", (), {"url": "http://127.0.0.1:9/api/interpreter"})()  # nothing listens here
        self.assertEqual(self.run_query([gone, backup]), OK)

    def test_a_malformed_query_is_an_error_and_other_servers_are_not_bothered(self):
        primary, backup = self.mirror(("status", 400)), self.mirror(("ok", None))
        with self.assertRaises(overpass.OverpassError) as ctx:
            self.run_query([primary, backup])
        self.assertNotIsInstance(ctx.exception, overpass.OverpassUnavailable)
        self.assertEqual(len(backup.requests), 0)

    def test_passes_over_the_list_are_repeated(self):
        flaky = self.mirror(("status", 503), ("ok", None))
        self.assertEqual(self.run_query([flaky], rounds=2), OK)
        self.assertEqual(len(flaky.requests), 2)


class GivingUpTests(OverpassTestCase):
    def test_all_servers_down_gives_a_friendly_error_after_every_attempt(self):
        a, b = self.mirror(("status", 502)), self.mirror(("status", 504))
        with self.assertRaises(overpass.OverpassUnavailable) as ctx:
            self.run_query([a, b], rounds=2)
        self.assertEqual((len(a.requests), len(b.requests)), (2, 2))
        self.assertIn("try again in a minute", str(ctx.exception))
        self.assertNotIn("502", str(ctx.exception))  # technical detail stays in .attempts / the logs
        self.assertEqual([reason for _, reason in ctx.exception.attempts], ["HTTP 502", "HTTP 504", "HTTP 502", "HTTP 504"])

    def test_the_overall_deadline_limits_how_long_it_keeps_trying(self):
        now = [0.0]
        calls = []

        def slow_failure(url, query, timeout):
            calls.append(timeout)
            now[0] += 4.0  # each attempt "takes" 4 seconds
            raise overpass._Retry("busy")

        with mock.patch.object(overpass, "_attempt", slow_failure), mock.patch.dict(os.environ, {"OVERPASS_CACHE_SECONDS": "0"}):
            with self.assertRaises(overpass.OverpassUnavailable):
                overpass.run(QUERY, urls=["http://a", "http://b", "http://c"], attempt_seconds=18, deadline_seconds=10, rounds=5, clock=lambda: now[0], sleep=lambda s: None)
        self.assertEqual(len(calls), 3)  # 4s + 4s + the last 2s, then the deadline
        self.assertEqual(calls, [10, 6, 2])  # each attempt gets at most what is left

    def test_it_pauses_between_passes_but_not_after_the_last(self):
        sleeps = []
        with mock.patch.object(overpass, "_attempt", side_effect=overpass._Retry("busy")), mock.patch.dict(os.environ, {"OVERPASS_CACHE_SECONDS": "0", "OVERPASS_RETRY_PAUSE_SECONDS": "2"}):
            with self.assertRaises(overpass.OverpassUnavailable):
                overpass.run(QUERY, urls=["http://a"], rounds=3, deadline_seconds=60, sleep=sleeps.append)
        self.assertEqual(sleeps, [2.0, 2.0])


class CacheTests(OverpassTestCase):
    def test_a_repeat_query_is_served_from_the_cache(self):
        server = self.mirror(("ok", None))
        self.assertEqual(self.run_query([server], cache="300"), OK)
        self.assertEqual(self.run_query([server], cache="300"), OK)
        self.assertEqual(len(server.requests), 1)

    def test_different_queries_are_cached_separately(self):
        server = self.mirror(("ok", None))
        with mock.patch.dict(os.environ, {"OVERPASS_CACHE_SECONDS": "300"}):
            overpass.run(QUERY, urls=[server.url])
            overpass.run(QUERY + " ", urls=[server.url])
        self.assertEqual(len(server.requests), 2)

    def test_caching_can_be_switched_off(self):
        server = self.mirror(("ok", None))
        self.run_query([server], cache="0")
        self.run_query([server], cache="0")
        self.assertEqual(len(server.requests), 2)

    def test_entries_expire(self):
        server = self.mirror(("ok", None))
        clock = [1000.0]
        with mock.patch.dict(os.environ, {"OVERPASS_CACHE_SECONDS": "60"}):
            overpass.run(QUERY, urls=[server.url], wall=lambda: clock[0])
            clock[0] += 59
            overpass.run(QUERY, urls=[server.url], wall=lambda: clock[0])
            self.assertEqual(len(server.requests), 1)
            clock[0] += 2
            overpass.run(QUERY, urls=[server.url], wall=lambda: clock[0])
        self.assertEqual(len(server.requests), 2)

    def test_an_older_copy_is_served_when_every_server_is_down(self):
        server = self.mirror(("ok", None), ("status", 503))
        clock = [0.0]
        env = {"OVERPASS_CACHE_SECONDS": "60", "OVERPASS_STALE_SECONDS": "3600", "OVERPASS_RETRY_PAUSE_SECONDS": "0"}
        with mock.patch.dict(os.environ, env):
            first = overpass.run(QUERY, urls=[server.url], rounds=1, wall=lambda: clock[0])
            clock[0] += 600  # past "fresh", within "stale"
            again = overpass.run(QUERY, urls=[server.url], rounds=1, wall=lambda: clock[0])
            self.assertEqual(again, first)
            clock[0] += 7200  # too old to serve
            with self.assertRaises(overpass.OverpassUnavailable):
                overpass.run(QUERY, urls=[server.url], rounds=1, wall=lambda: clock[0])

    def test_failures_are_never_cached_and_the_cache_is_bounded(self):
        down = self.mirror(("status", 503))
        with self.assertRaises(overpass.OverpassUnavailable):
            self.run_query([down], cache="300")
        up = self.mirror(("ok", None))
        self.assertEqual(self.run_query([up], cache="300"), OK)
        with mock.patch.dict(os.environ, {"OVERPASS_CACHE_SECONDS": "300"}), mock.patch.object(overpass, "MAX_CACHE_ENTRIES", 3):
            for i in range(10):
                overpass.run(f"{QUERY}{i}", urls=[up.url])
        self.assertLessEqual(len(overpass._cache), 3)


class AppIntegrationTests(OverpassTestCase):
    """The scan functions use the failover (their urlopen goes through overpass.run)."""

    def test_the_area_scan_survives_a_failing_primary(self):
        busy, backup = self.mirror(("status", 502)), self.mirror(("ok", None))
        with mock.patch.dict(os.environ, {"OVERPASS_URLS": f"{busy.url},{backup.url}", "OVERPASS_ATTEMPT_SECONDS": "3"}):
            venues = app.fetch_osm_overpass_live(47.37, 8.54)
        self.assertEqual([v["name"] for v in venues], ["Mirror Pub"])
        self.assertEqual((len(busy.requests), len(backup.requests)), (1, 1))
        self.assertIn("around:1500,47.37,8.54", backup.requests[0]["form"]["data"][0])

    def test_the_nationwide_scan_survives_a_failing_primary_and_gets_longer_per_attempt(self):
        busy, backup = self.mirror(("status", 504)), self.mirror(("ok", None))
        with mock.patch.dict(os.environ, {"OVERPASS_URLS": f"{busy.url},{backup.url}"}):
            venues = app.fetch_osm_switzerland_nationwide()
        self.assertEqual([v["name"] for v in venues], ["Mirror Pub"])
        with mock.patch.object(overpass, "_attempt", return_value=OK) as attempt, mock.patch.dict(os.environ, {"OVERPASS_URLS": "http://x.example/i"}):
            app.fetch_osm_overpass_live(47, 8)
            app.fetch_osm_switzerland_nationwide()
        self.assertEqual([c.args[2] for c in attempt.call_args_list], [18, 24])


class ApiTests(ApiTestCase):
    def test_every_server_busy_is_a_503_with_a_readable_message_and_retry_after(self):
        with mock.patch.object(app, "fetch_osm_overpass_live", side_effect=overpass.OverpassUnavailable()):
            status, data, resp = self.call("GET", "/api/venues?mode=osm&lat=47.0&lng=8.0")
        self.assertEqual(status, 503)
        self.assertIn("try again in a minute", data["error"])
        self.assertEqual(resp.getheader("Retry-After"), "30")

    def test_other_failures_are_still_a_500(self):
        with mock.patch.object(app, "fetch_osm_overpass_live", side_effect=ValueError("boom")):
            self.assertEqual(self.call("GET", "/api/venues?mode=osm&lat=47.0&lng=8.0")[0], 500)

    def test_the_nationwide_scan_falls_back_to_bundled_data_when_every_server_is_busy(self):
        with mock.patch.object(app, "fetch_osm_switzerland_nationwide", side_effect=overpass.OverpassUnavailable()):
            status, data, _ = self.call("GET", "/api/venues?mode=osm_ch")
        self.assertEqual((status, data["source"]), (200, "switzerland_nationwide_scan"))


if __name__ == "__main__":
    unittest.main()

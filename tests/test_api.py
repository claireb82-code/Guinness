"""End-to-end tests of the real request handler (app_server.GuinnessHandler) on a real socket."""

import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

import app_server
import storage
from tests.helpers import FakeRedis, page_server, stop

KNOWN = {
    "id": "v-known", "city": "zurich", "name": "Known Pub", "category": "pub", "address": "Zurich",
    "lat": 47.37, "lng": 8.54, "website": None, "menuCheck": {"checked": False, "foundOnMenu": False},
    "crowdCheck": {}, "reviewCheck": {},
}


class ApiTestCase(unittest.TestCase):
    """Starts the real handler with an isolated storage backend and no network access to Google."""

    vercel = False
    env = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backend = storage.FileBackend(os.path.join(self.tmp.name, "store.json"), "", ephemeral=self.vercel)
        self.start_server(self.backend)

    def start_server(self, backend):
        patches = [
            mock.patch.object(app_server, "_BACKEND", backend),
            mock.patch.object(app_server, "ON_VERCEL", self.vercel),
            mock.patch.dict(os.environ, {"RATE_LIMIT_DISABLED": "1", **self.env}, clear=False),
            mock.patch.object(app_server, "get_all_combined_venues", lambda store: [dict(KNOWN)]),
            mock.patch.object(app_server.GuinnessHandler, "log_message", lambda *a, **k: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app_server.GuinnessHandler)
        threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.02), daemon=True).start()
        self.addCleanup(stop, self.server)

    def call(self, method, path, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=20)
        hdrs = dict(headers or {})
        payload = raw
        if body is not None:
            payload = json.dumps(body)
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=payload, headers=hdrs)
        resp = conn.getresponse()
        text = resp.read().decode("utf-8")
        conn.close()
        try:
            data = json.loads(text)
        except ValueError:
            data = text
        return resp.status, data, resp

    def post(self, path, body, **kw):
        return self.call("POST", path, body, **kw)


class ConfigAndKeyTests(ApiTestCase):
    env = {"GOOGLE_PLACES_API_KEY": "SERVER_SECRET_KEY", "GOOGLE_MAPS_BROWSER_KEY": "BROWSER_KEY", "GOOGLE_MAPS_API_KEY": "LEGACY_KEY"}

    def test_config_exposes_only_the_browser_key(self):
        status, data, resp = self.call("GET", "/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(data["envApiKey"], "BROWSER_KEY")
        self.assertNotIn("SERVER_SECRET_KEY", json.dumps(data))
        self.assertNotIn("LEGACY_KEY", json.dumps(data))
        self.assertTrue(data["communitySubmissions"])

    def test_cors_only_on_reads(self):
        _, _, get = self.call("GET", "/api/config")
        self.assertEqual(get.getheader("Access-Control-Allow-Origin"), "*")
        _, _, post = self.post("/api/crowd-report", {"venueId": "v", "servingFormat": "draught"})
        self.assertIsNone(post.getheader("Access-Control-Allow-Origin"))


class LegacyKeyLocalTests(ApiTestCase):
    env = {"GOOGLE_MAPS_API_KEY": "LEGACY_KEY"}

    def test_legacy_key_still_works_locally(self):
        self.assertEqual(self.call("GET", "/api/config")[1]["envApiKey"], "LEGACY_KEY")
        self.assertEqual(app_server.resolve_places_key({}), "LEGACY_KEY")


class VercelKeyPolicyTests(ApiTestCase):
    vercel = True
    env = {"GOOGLE_PLACES_API_KEY": "SERVER_SECRET_KEY", "GOOGLE_MAPS_API_KEY": "LEGACY_KEY"}

    def setUp(self):
        super().setUp()
        os.environ.pop("GOOGLE_MAPS_BROWSER_KEY", None)
        os.environ.pop("ALLOW_PUBLIC_GOOGLE_LIVE", None)

    def test_legacy_key_is_not_exposed_on_a_public_deployment(self):
        data = self.call("GET", "/api/config")[1]
        self.assertEqual(data["envApiKey"], "")
        self.assertFalse(data["hasEnvApiKey"])
        self.assertNotIn("LEGACY_KEY", json.dumps(data))
        self.assertNotIn("SERVER_SECRET_KEY", json.dumps(data))

    def test_server_key_is_not_used_for_anonymous_visitors(self):
        self.assertEqual(app_server.resolve_places_key({}), "")
        with mock.patch.object(app_server, "fetch_google_places_live", side_effect=AssertionError("Google must not be called")):
            status, data, _ = self.call("GET", "/api/venues?mode=live&lat=47.37&lng=8.54&city=zurich")
        self.assertEqual(status, 200)
        self.assertEqual(data["source"], "demo_curated")  # fell back to curated data, no Google call

    def test_visitors_own_key_is_used_and_billed_to_them(self):
        with mock.patch.object(app_server, "fetch_google_places_live", return_value=[]) as places:
            self.call("GET", "/api/venues?mode=live&lat=47.37&lng=8.54&city=zurich", headers={"x-google-maps-key": "VISITOR_KEY_123456789012"})
        self.assertEqual(places.call_args.args[0], "VISITOR_KEY_123456789012")

    def test_server_key_can_be_explicitly_enabled(self):
        with mock.patch.dict(os.environ, {"ALLOW_PUBLIC_GOOGLE_LIVE": "1"}):
            self.assertEqual(app_server.resolve_places_key({}), "SERVER_SECRET_KEY")
            self.assertEqual(app_server.resolve_places_key({"x-google-maps-key": "mine"}), "mine")

    def test_check_google_maps_does_not_use_the_server_key_either(self):
        with mock.patch.object(app_server, "fetch_google_places_live", side_effect=AssertionError("no")):
            status, data, _ = self.post("/api/check-google-maps", {"query": "Some Pub Zurich"})
        self.assertEqual(status, 200)

    def test_malformed_visitor_keys_are_ignored(self):
        for bad in ["x" * 101, "bad\x07key"]:
            self.assertEqual(app_server.resolve_places_key({"x-google-maps-key": bad}), "")


class RequestHardeningTests(ApiTestCase):
    def test_bad_requests_get_json_errors_not_dropped_connections(self):
        self.assertEqual(self.post("/api/crowd-report", None, raw="{nope", headers={"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.call("POST", "/api/crowd-report", raw='{"venueId":"v"}', headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("POST", "/api/crowd-report", raw='[1]', headers={"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.post("/api/nope", {})[0], 404)
        status, data, _ = self.call("POST", "/api/crowd-report", raw="x" * 50_000, headers={"Content-Type": "application/json"})
        self.assertEqual(status, 413)
        self.assertIn("too large", data["error"])

    def test_bad_query_parameters_are_a_400_not_a_crash(self):
        status, data, _ = self.call("GET", "/api/venues?mode=osm&lat=abc&lng=8")
        self.assertEqual(status, 400)
        self.assertEqual(self.call("GET", "/api/venues?mode=osm&lat=999&lng=8")[0], 400)

    def test_curated_data_still_loads(self):
        status, data, _ = self.call("GET", "/api/venues?city=zurich")
        self.assertEqual((status, data["source"]), (200, "demo_curated"))
        self.assertEqual(data["venues"][0]["id"], "v-known")


class CrowdReportTests(ApiTestCase):
    def test_valid_report_is_stored_and_reflected(self):
        status, data, _ = self.post("/api/crowd-report", {"venueId": "v-known", "servingFormat": "draught", "price": "9.5", "note": " creamy ", "user": "Aoife"})
        self.assertEqual(status, 200)
        self.assertEqual(data["report"]["price"], "CHF 9.50")
        self.assertEqual(data["report"]["note"], "creamy")
        self.assertEqual(data["venue"]["crowdCheck"]["reportedPrice"], "CHF 9.50")
        self.assertEqual(self.backend.load()["crowdReports"]["v-known"][0]["user"], "Aoife")

    def test_invalid_reports_are_rejected_with_a_readable_reason(self):
        for body, needle in [
            ({"venueId": "../etc"}, "venueId"),
            ({"venueId": "v", "note": "x" * 501}, "note"),
            ({"venueId": "v", "servingFormat": "keg"}, "servingFormat"),
        ]:
            with self.subTest(body=body):
                status, data, _ = self.post("/api/crowd-report", body)
                self.assertEqual(status, 400)
                self.assertIn(needle, data["error"])
        self.assertEqual(self.backend.load()["crowdReports"], {})

    def test_stored_html_is_data_not_markup_server_side(self):
        """The server stores text verbatim (escaping is the UI's job); it must never execute or reinterpret it."""
        _, data, _ = self.post("/api/crowd-report", {"venueId": "v-known", "servingFormat": "draught", "note": "<img src=x onerror=alert(1)>", "user": "<b>x</b>"})
        self.assertEqual(data["report"]["note"], "<img src=x onerror=alert(1)>")


class SubmissionsDisabledOnEphemeralDeployTests(ApiTestCase):
    vercel = True  # Vercel with no database configured

    def test_writes_are_refused_instead_of_silently_lost(self):
        self.assertFalse(self.call("GET", "/api/config")[1]["communitySubmissions"])
        for path, body in [("/api/crowd-report", {"venueId": "v-known", "servingFormat": "draught"}), ("/api/add-venue", {"name": "X", "lat": 47.37, "lng": 8.54})]:
            status, data, _ = self.post(path, body)
            self.assertEqual(status, 503)
            self.assertIn("no database", data["error"])
        self.assertEqual(self.backend.load()["crowdReports"], {})
        self.assertEqual(self.backend.load()["customVenues"], [])


class AddVenueTests(ApiTestCase):
    OK = {"name": "New Pub", "lat": 47.37, "lng": 8.54, "category": "bar", "city": "zurich", "servingFormat": "draught", "price": "CHF 9"}

    def test_regression_how_it_is_served_must_be_said_not_assumed(self):
        """Missing servingFormat used to default to draught, and a missing rating to 4.8: invented evidence."""
        body = {k: v for k, v in self.OK.items() if k != "servingFormat"}
        status, data, _ = self.post("/api/add-venue", body)
        self.assertEqual(status, 400)
        self.assertIn("servingFormat", data["error"])
        self.assertEqual(self.backend.load()["customVenues"], [])

    def test_regression_there_is_no_pint_score(self):
        """A venue (or report) never carries a rating, even if the client still sends one."""
        v = self.post("/api/add-venue", {**self.OK, "pintRating": 5})[1]["venue"]
        self.assertNotIn("avgPintRating", v["crowdCheck"])
        self.assertNotIn("pintRating", json.dumps(self.backend.load()["customVenues"]))
        report = self.post("/api/crowd-report", {"venueId": "v-known", "servingFormat": "draught", "pintRating": 5})[1]["report"]
        self.assertNotIn("pintRating", report)

    def test_valid_venue(self):
        status, data, _ = self.post("/api/add-venue", self.OK)
        self.assertEqual(status, 200)
        v = data["venue"]
        self.assertEqual((v["name"], v["category"], v["crowdCheck"]["reportedPrice"]), ("New Pub", "bar", "CHF 9.00"))
        self.assertEqual(self.backend.load()["customVenues"][0]["id"], v["id"])

    def test_regression_a_community_venue_carries_only_the_visitors_own_report(self):
        """It used to get an invented 4.7 Google rating and a made-up review mention."""
        v = self.post("/api/add-venue", self.OK)[1]["venue"]
        self.assertEqual((v["googleRating"], v["googleReviewCount"], v["priceLevel"]), (None, 0, None))
        self.assertEqual(v["reviewCheck"]["mentionCount"], 0)
        self.assertFalse(v["menuCheck"]["foundOnMenu"], "no website was read")
        self.assertEqual(v["crowdCheck"]["confirmedCount"], 1, "the visitor's own report is real evidence")
        summary = v["guinnessSummary"]
        self.assertEqual((summary["status"], summary["statusLabel"], summary["reason"]), ("likely_serves", "Possible", "Reported by 1 visitor"))

    def test_dangerous_or_internal_websites_are_rejected(self):
        for site in ["javascript:alert(document.cookie)", "data:text/html,<script>alert(1)</script>", "http://localhost:8080/admin",
                     "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd"]:
            with self.subTest(website=site):
                status, data, _ = self.post("/api/add-venue", {**self.OK, "website": site})
                self.assertEqual(status, 400, data)
                self.assertIn("website", data["error"])
        self.assertEqual(self.backend.load()["customVenues"], [])

    def test_location_and_enum_validation(self):
        for patch in [{"lat": 10}, {"lng": 100}, {"category": "casino"}, {"city": "atlantis"}, {"name": ""}, {"lat": "nan"}]:
            with self.subTest(patch=patch):
                self.assertEqual(self.post("/api/add-venue", {**self.OK, **patch})[0], 400)

    def test_public_website_is_stored_normalised_and_scanned(self):
        hits = []
        srv, base = page_server({"/": (200, {}, b"<p>We pour Guinness daily</p>")}, hits)
        self.addCleanup(stop, srv)
        with mock.patch.object(app_server, "FETCH_ALLOW_PRIVATE", True), mock.patch("guard.clean_website", lambda v: base + "/"):
            status, data, _ = self.post("/api/add-venue", {**self.OK, "website": "pub.example"})
        self.assertEqual(status, 200)
        self.assertTrue(data["venue"]["menuCheck"]["foundOnMenu"])
        self.assertEqual(hits, ["/"])


class ScanMenuTests(ApiTestCase):
    """Venue websites are DNS names. ``*.example`` hosts are made to resolve to our local page server,
    which lets us test the realistic SSRF case: a harmless-looking hostname that points at an
    internal address (IP *literals* are already rejected earlier, at validation)."""

    def setUp(self):
        super().setUp()
        self.hits = []
        srv, base = page_server(
            {"/menu": (200, {}, b"<li>Guinness Draught CHF 9.50</li>"), "/other": (200, {}, b"<li>Guinness everywhere!</li>")}, self.hits
        )
        self.addCleanup(stop, srv)
        self.port = srv.server_address[1]
        real = __import__("socket").getaddrinfo

        def fake_dns(host, *a, **k):
            if str(host).endswith(".example"):
                return real("127.0.0.1", self.port, type=__import__("socket").SOCK_STREAM)
            return real(host, *a, **k)

        p = mock.patch("guard.socket.getaddrinfo", fake_dns)
        p.start()
        self.addCleanup(p.stop)
        known = dict(KNOWN, website=self.url("venue") + "/", menuUrl=self.url("venue") + "/menu")
        p = mock.patch.object(app_server, "get_all_combined_venues", lambda store: [dict(known)])
        p.start()
        self.addCleanup(p.stop)

    def url(self, name, path=""):
        return f"http://{name}.example:{self.port}{path}"

    def test_a_hostname_pointing_at_an_internal_address_is_never_contacted(self):
        # FETCH_ALLOW_PRIVATE stays False (the production setting).
        status, data, _ = self.post("/api/scan-menu", {"venueId": "v-known", "websiteUrl": self.url("venue", "/menu")})
        self.assertEqual(status, 200)
        self.assertFalse(data["scanResult"]["checked"])
        self.assertIn("not scanned", data["scanResult"]["snippets"][0])
        self.assertEqual(self.hits, [])
        self.assertEqual(self.backend.load()["menuScans"], {})  # a blocked scan is never saved

    def test_ip_literals_and_bad_schemes_are_refused_up_front(self):
        for url in ["http://169.254.169.254/latest/meta-data/", "http://127.0.0.1/", "javascript:alert(1)", "file:///etc/passwd", "http://[::1]/", "http://localhost/"]:
            with self.subTest(url=url):
                status, data, _ = self.post("/api/scan-menu", {"websiteUrl": url})
                self.assertEqual(status, 400)
                self.assertIn("website", data["error"])
        self.assertEqual(self.hits, [])

    def test_scan_of_the_venues_own_site_is_saved(self):
        with mock.patch.object(app_server, "FETCH_ALLOW_PRIVATE", True):
            status, data, _ = self.post("/api/scan-menu", {"venueId": "v-known", "websiteUrl": self.url("venue", "/menu")})
        self.assertTrue(data["scanResult"]["foundOnMenu"])
        self.assertEqual(self.backend.load()["menuScans"]["v-known"]["foundOnMenu"], True)
        self.assertTrue(data["venue"]["menuCheck"]["foundOnMenu"])

    def test_subdomain_of_the_venues_site_is_still_its_own_site(self):
        with mock.patch.object(app_server, "FETCH_ALLOW_PRIVATE", True):
            self.post("/api/scan-menu", {"venueId": "v-known", "websiteUrl": self.url("menu.venue", "/menu")})
        self.assertIn("v-known", self.backend.load()["menuScans"])

    def test_scan_of_a_foreign_site_cannot_overwrite_a_venues_saved_result(self):
        """Poisoning: pointing a venue's scan at someone else's page must not change what is stored."""
        with mock.patch.object(app_server, "FETCH_ALLOW_PRIVATE", True):
            status, data, _ = self.post("/api/scan-menu", {"venueId": "v-known", "websiteUrl": self.url("attacker", "/other")})
        self.assertEqual(status, 200)
        self.assertTrue(data["scanResult"]["foundOnMenu"])  # the caller sees their own result...
        self.assertEqual(self.backend.load()["menuScans"], {})  # ...but nothing is saved for everyone else
        self.assertEqual(self.hits, ["/other"])

    def test_unknown_venue_scan_is_returned_but_not_saved(self):
        with mock.patch.object(app_server, "FETCH_ALLOW_PRIVATE", True):
            status, data, _ = self.post("/api/scan-menu", {"venueId": "someone-elses-venue", "websiteUrl": self.url("venue", "/menu")})
        self.assertEqual(status, 200)
        self.assertEqual(self.backend.load()["menuScans"], {})

    def test_default_scan_uses_the_venues_own_menu_url(self):
        with mock.patch.object(app_server, "FETCH_ALLOW_PRIVATE", True):
            status, data, _ = self.post("/api/scan-menu", {"venueId": "v-known", "servingFormat": "draught"})
        self.assertTrue(data["scanResult"]["foundOnMenu"])
        self.assertEqual(self.hits, ["/menu"])

    def test_malformed_ids_and_urls_are_400(self):
        self.assertEqual(self.post("/api/scan-menu", {"venueId": "bad id!"})[0], 400)
        self.assertEqual(self.post("/api/scan-menu", {"venueId": "v-known", "websiteUrl": "a b"})[0], 400)


class CheckGoogleMapsTests(ApiTestCase):
    def test_spoofed_google_hosts_never_become_the_venue_link(self):
        for link in ["https://google.com.evil.com/maps/place/Pub/@47.37,8.54,17z", "http://www.google.com/maps/place/Pub"]:
            with self.subTest(link=link):
                status, data, _ = self.post("/api/check-google-maps", {"query": link})
                self.assertEqual(status, 200)
                uri = data["venues"][0]["googleMapsUri"]
                self.assertTrue(uri.startswith("https://www.google.com/maps/search/"), uri)

    def test_genuine_google_maps_links_are_kept(self):
        link = "https://www.google.com/maps/place/Pub/@47.37,8.54,17z"
        uri = self.post("/api/check-google-maps", {"query": link})[1]["venues"][0]["googleMapsUri"]
        self.assertEqual(uri, link)

    def test_input_limits(self):
        lines = "\n".join(f"Pub {i}" for i in range(50))
        status, data, _ = self.post("/api/check-google-maps", {"query": lines})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["venues"]), 10)
        self.assertEqual(self.post("/api/check-google-maps", {"query": "x" * 1001})[0], 400)
        self.assertEqual(self.post("/api/check-google-maps", {"query": "Pub", "radius": 10**9})[0], 400)
        self.assertEqual(self.post("/api/check-google-maps", {"query": "Pub", "website": "javascript:1"})[0], 400)
        self.assertEqual(self.post("/api/check-google-maps", {"query": "Pub", "city": "atlantis"})[0], 400)


class RateLimitTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("RATE_LIMIT_DISABLED", None)

    def test_writes_are_limited_per_client_with_retry_after(self):
        with mock.patch.object(app_server, "RATE_WRITES", (3, 3600)):
            codes = [self.post("/api/crowd-report", {"venueId": "v-known", "servingFormat": "draught"})[0] for _ in range(5)]
            status, data, resp = self.post("/api/crowd-report", {"venueId": "v-known", "servingFormat": "draught"})
        self.assertEqual(codes, [200, 200, 200, 429, 429])
        self.assertEqual(status, 429)
        self.assertEqual(resp.getheader("Retry-After"), "3600")
        self.assertIn("Too many requests", data["error"])

    def test_limits_are_independent_per_bucket(self):
        with mock.patch.object(app_server, "RATE_WRITES", (1, 3600)), mock.patch.object(app_server, "RATE_SCANS", (50, 600)):
            self.post("/api/crowd-report", {"venueId": "v-known", "servingFormat": "draught"})
            self.assertEqual(self.post("/api/crowd-report", {"venueId": "v-known", "servingFormat": "draught"})[0], 429)
            self.assertEqual(self.post("/api/scan-menu", {})[0], 200)  # scans use a different budget, unaffected

    def test_heavy_nationwide_scan_has_its_own_tight_limit(self):
        with mock.patch.object(app_server, "RATE_HEAVY", (1, 600)), mock.patch.object(app_server, "fetch_osm_switzerland_nationwide", return_value=[]) as scan:
            first = self.call("GET", "/api/venues?mode=osm_ch")[0]
            second = self.call("GET", "/api/venues?mode=osm_ch")[0]
        self.assertEqual((first, second), (200, 429))
        self.assertEqual(scan.call_count, 1)

    def test_spoofed_forwarded_for_is_ignored_off_vercel(self):
        with mock.patch.object(app_server, "RATE_WRITES", (1, 3600)):
            a = self.post("/api/crowd-report", {"venueId": "v-known", "servingFormat": "draught"}, headers={"X-Forwarded-For": "1.1.1.1"})[0]
            b = self.post("/api/crowd-report", {"venueId": "v-known", "servingFormat": "draught"}, headers={"X-Forwarded-For": "2.2.2.2"})[0]
        self.assertEqual((a, b), (200, 429))  # rotating the header does not reset the limit


class RedisIntegrationTests(unittest.TestCase):
    """Two separate 'serverless instances' sharing one database: what Vercel needs."""

    def test_submissions_are_shared_across_instances_and_survive_restarts(self):
        redis = FakeRedis().start()
        self.addCleanup(redis.stop)

        def instance():
            case = ApiTestCase("run")
            case.vercel = True
            case.tmp = tempfile.TemporaryDirectory()
            self.addCleanup(case.tmp.cleanup)
            backend = storage.RedisBackend(redis.url, "test-token", os.path.join(case.tmp.name, "s.json"), "", prefix="it:")
            case.backend = backend
            case.addCleanup = self.addCleanup
            case.start_server(backend)
            return case

        a, b = instance(), instance()
        status, data, _ = a.post("/api/crowd-report", {"venueId": "v-known", "servingFormat": "draught", "note": "from A"})
        self.assertEqual(status, 200)
        status, data, _ = b.post("/api/add-venue", {"name": "From B", "lat": 47.37, "lng": 8.54, "servingFormat": "draught"})
        self.assertEqual(status, 200)

        # Instance C starts later, cold, with an empty /tmp: it still sees both.
        c = instance()
        _, venues, _ = c.call("GET", "/api/venues?city=zurich")
        known = next(v for v in venues["venues"] if v["id"] == "v-known")
        self.assertEqual(known["crowdCheck"]["recentReports"][0]["note"], "from A")
        self.assertIn("From B", [r["name"] for r in c.backend.load()["customVenues"]])

    def test_database_outage_is_a_503_not_a_crash(self):
        redis = FakeRedis().start()
        self.addCleanup(redis.stop)
        case = ApiTestCase("run")
        case.vercel = True
        case.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(case.tmp.cleanup)
        backend = storage.RedisBackend(redis.url, "test-token", os.path.join(case.tmp.name, "s.json"), "", prefix="it:")
        case.addCleanup = self.addCleanup
        case.start_server(backend)
        redis.fail = True
        with mock.patch("sys.stderr"):
            status, data, _ = case.post("/api/crowd-report", {"venueId": "v-known", "servingFormat": "draught"})
        self.assertEqual(status, 503)
        self.assertIn("temporarily unavailable", data["error"])


if __name__ == "__main__":
    unittest.main()

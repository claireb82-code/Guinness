import http.client
import io
import socket
import time
import unittest
import urllib.error
from unittest import mock

import guard
from tests.helpers import page_server, stop, serve, QuietHandler


def http_client_error():
    return http.client.HTTPException


class NormalizeUrlTests(unittest.TestCase):
    def test_bare_host_gets_https(self):
        self.assertEqual(guard.normalize_http_url("example.com/menu"), "https://example.com/menu")
        self.assertEqual(guard.normalize_http_url("  http://example.com  "), "http://example.com")
        self.assertEqual(guard.normalize_http_url("example.com:8080/x"), "https://example.com:8080/x")

    def test_rejects_non_http_schemes_in_any_case(self):
        for bad in [
            "javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<script>1</script>",
            "file:///etc/passwd", "ftp://example.com/x", "gopher://example.com", "vbscript:x",
            "view-source:https://example.com", "mailto:a@b.c", "ws://example.com",
        ]:
            with self.subTest(url=bad), self.assertRaises(guard.UnsafeURL):
                guard.normalize_http_url(bad)

    def test_rejects_malformed_input(self):
        for bad in ["", "   ", None, 123, "//evil.com", "http://", "https://exa mple.com", "http://a.com/\nHost: x",
                    "http://user:pw@example.com/", "http://example.com:99999/", "http://example.com:abc/",
                    "https://" + "a" * 400 + ".com"]:
            with self.subTest(url=bad), self.assertRaises(guard.UnsafeURL):
                guard.normalize_http_url(bad)


class PublicAddressTests(unittest.TestCase):
    def test_private_and_special_addresses_are_not_public(self):
        for ip in [
            "127.0.0.1", "10.1.2.3", "172.16.0.1", "172.31.255.255", "192.168.1.1", "169.254.169.254",
            "100.64.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255", "::1", "::", "fe80::1", "fd00::1",
            "::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "2002:7f00:0001::1", "fe80::1%eth0", "not-an-ip",
        ]:
            with self.subTest(ip=ip):
                self.assertFalse(guard.is_public_address(ip))

    def test_public_addresses(self):
        for ip in ["8.8.8.8", "93.184.216.34", "172.32.0.1", "2606:4700:4700::1111", "::ffff:8.8.8.8"]:
            with self.subTest(ip=ip):
                self.assertTrue(guard.is_public_address(ip))

    def test_obfuscated_loopback_forms_are_caught_after_resolution(self):
        # Decimal / hex / short IPv4 spellings of 127.0.0.1 are resolved by the OS, then rejected.
        for host in ["2130706433", "0x7f.1", "127.1", "0177.0.0.1"]:
            with self.subTest(host=host):
                try:
                    guard.resolve_public(host, 80)
                except guard.UnsafeURL:
                    pass
                else:
                    self.fail(f"{host} should have been refused")

    def test_mixed_public_and_private_answers_are_refused(self):
        fake = [(socket.AF_INET, 0, 0, "", ("8.8.8.8", 80)), (socket.AF_INET, 0, 0, "", ("10.0.0.5", 80))]
        with mock.patch("guard.socket.getaddrinfo", return_value=fake), self.assertRaises(guard.UnsafeURL):
            guard.resolve_public("sneaky.example", 80)


class FetchPageTests(unittest.TestCase):
    def test_fetches_a_page(self):
        srv, base = page_server({"/": (200, {}, b"<html>Guinness 5.50</html>")})
        self.addCleanup(stop, srv)
        self.assertIn("Guinness", guard.fetch_page(base + "/", allow_private=True))

    def test_private_target_refused_by_default_and_never_contacted(self):
        hits = []
        srv, base = page_server({"/": (200, {}, b"secret")}, hits)
        self.addCleanup(stop, srv)
        with self.assertRaises(guard.UnsafeURL):
            guard.fetch_page(base + "/")  # 127.0.0.1, allow_private=False
        self.assertEqual(hits, [])

    def test_body_is_size_capped(self):
        srv, base = page_server({"/": (200, {}, b"a" * 200_000)})
        self.addCleanup(stop, srv)
        self.assertEqual(len(guard.fetch_page(base + "/", max_bytes=10_000, allow_private=True)), 10_000)

    def test_slow_drip_download_is_cut_off(self):
        class Slow(QuietHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", "1000")
                self.end_headers()
                try:
                    for _ in range(100):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.05)
                except OSError:
                    pass

        srv, base = serve(Slow)
        self.addCleanup(stop, srv)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            guard.fetch_page(base + "/", deadline=0.5, allow_private=True)
        self.assertLess(time.monotonic() - started, 3)

    def test_slow_response_headers_are_cut_off_too(self):
        """Slowloris on the *headers* (not just the body) must also hit the wall-clock deadline."""
        class SlowHeaders(QuietHandler):
            def do_GET(self):
                try:
                    self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                    for _ in range(100):
                        self.wfile.write(b"X-Pad: a")  # never completes the header line
                        self.wfile.flush()
                        time.sleep(0.05)
                except OSError:
                    pass

        srv, base = serve(SlowHeaders)
        self.addCleanup(stop, srv)
        started = time.monotonic()
        with self.assertRaises((TimeoutError, OSError, http_client_error())):
            guard.fetch_page(base + "/", deadline=0.5, allow_private=True)
        self.assertLess(time.monotonic() - started, 3)

    def test_redirect_to_a_private_address_is_refused_and_not_followed(self):
        """Every hop is validated, so a public site cannot bounce us to an internal one."""
        internal_hits = []
        internal, _ = page_server({"/secret": (200, {}, b"INTERNAL")}, internal_hits)  # 127.0.0.1
        self.addCleanup(stop, internal)
        port = internal.server_address[1]
        # The "public" site redirects to 127.0.0.2 (same loopback interface, different address).
        outer, base = page_server({"/": (302, {"Location": f"http://127.0.0.2:{port}/secret"}, b"")})
        self.addCleanup(stop, outer)
        # Treat everything except 127.0.0.2 as public so the first hop is allowed.
        with mock.patch("guard.is_public_address", lambda a: a != "127.0.0.2"):
            with self.assertRaises(guard.UnsafeURL):
                guard.fetch_page(base + "/")
        self.assertEqual(internal_hits, [])

    def test_redirect_to_file_scheme_is_refused(self):
        srv, base = page_server({"/": (302, {"Location": "file:///etc/passwd"}, b"")})
        self.addCleanup(stop, srv)
        with self.assertRaises(urllib.error.HTTPError):
            guard.fetch_page(base + "/", allow_private=True)

    def test_normal_redirect_is_followed_and_loops_are_capped(self):
        srv, base = page_server({
            "/": (301, {"Location": "/menu"}, b""),
            "/menu": (200, {}, b"landed"),
            "/loop": (302, {"Location": "/loop"}, b""),
        })
        self.addCleanup(stop, srv)
        self.assertEqual(guard.fetch_page(base + "/", allow_private=True), "landed")
        with self.assertRaises(urllib.error.HTTPError):
            guard.fetch_page(base + "/loop", allow_private=True)

    def test_connects_to_the_validated_address_with_a_single_lookup(self):
        """No second DNS lookup between the check and the connection (DNS-rebinding defence)."""
        srv, base = page_server({"/": (200, {}, b"ok")})
        self.addCleanup(stop, srv)
        port = srv.server_address[1]
        real = socket.getaddrinfo
        calls = []

        def counting(host, *a, **k):
            if host == "venue.example":
                calls.append(host)
                return real("127.0.0.1", port, type=socket.SOCK_STREAM)
            return real(host, *a, **k)

        with mock.patch("guard.socket.getaddrinfo", counting), mock.patch("guard.is_public_address", lambda a: True):
            self.assertEqual(guard.fetch_page(f"http://venue.example:{port}/"), "ok")
        self.assertEqual(len(calls), 1)

    def test_http_errors_propagate_as_urllib_errors(self):
        srv, base = page_server({})
        self.addCleanup(stop, srv)
        with self.assertRaises(urllib.error.HTTPError):
            guard.fetch_page(base + "/missing", allow_private=True)


class SameSiteTests(unittest.TestCase):
    def test_same_site(self):
        self.assertTrue(guard.same_site("https://www.pub.ch/menu", "http://pub.ch"))
        self.assertTrue(guard.same_site("https://menu.pub.ch/x", "https://pub.ch"))
        self.assertTrue(guard.same_site("pub.ch", "https://PUB.ch./"))

    def test_different_or_missing_sites(self):
        self.assertFalse(guard.same_site("https://evil.com/pub.ch", "https://pub.ch"))
        self.assertFalse(guard.same_site("https://notpub.ch", "https://pub.ch"))
        self.assertFalse(guard.same_site(None, "https://pub.ch"))
        self.assertFalse(guard.same_site("https://pub.ch", ""))


class BodyTests(unittest.TestCase):
    def body(self, raw, length=None, headers=None):
        h = {"Content-Length": str(len(raw) if length is None else length)}
        h.update(headers or {})
        return guard.read_json_body(h, io.BytesIO(raw))

    def test_valid_object(self):
        self.assertEqual(self.body(b'{"a": 1}'), {"a": 1})
        self.assertEqual(guard.read_json_body({}, io.BytesIO(b"")), {})

    def test_rejections(self):
        with self.assertRaises(guard.ValidationError) as ctx:
            self.body(b"x" * 30_000)
        self.assertEqual(ctx.exception.status, 413)
        for raw in [b"{nope", b"[1,2]", b'"text"', b"null"]:
            with self.subTest(raw=raw), self.assertRaises(guard.ValidationError):
                self.body(raw)
        for length in ["abc", "-5"]:
            with self.subTest(length=length), self.assertRaises(guard.ValidationError):
                guard.read_json_body({"Content-Length": length}, io.BytesIO(b"{}"))


class FieldValidationTests(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(guard.clean_text("  hi\x00 there\x07 ", "f", 20), "hi there")
        self.assertEqual(guard.clean_text(None, "f", 5), "")
        with self.assertRaises(guard.ValidationError):
            guard.clean_text("x" * 6, "f", 5)
        with self.assertRaises(guard.ValidationError):
            guard.clean_text("", "f", 5, required=True)
        with self.assertRaises(guard.ValidationError):
            guard.clean_text({"a": 1}, "f", 5)
        with self.assertRaises(guard.ValidationError):
            guard.clean_text(True, "f", 5)

    def test_clean_number_rejects_nan_inf_bool_and_range(self):
        self.assertEqual(guard.clean_number("4.5", "r", 1, 5), 4.5)
        self.assertEqual(guard.clean_number(None, "r", 1, 5, 3.0), 3.0)
        for bad in ["nan", "inf", float("nan"), "abc", True, 6, 0, [1]]:
            with self.subTest(value=bad), self.assertRaises(guard.ValidationError):
                guard.clean_number(bad, "r", 1, 5)

    def test_clean_choice_and_venue_id(self):
        self.assertEqual(guard.clean_choice(None, "c", ("a", "b"), "a"), "a")
        with self.assertRaises(guard.ValidationError):
            guard.clean_choice("z", "c", ("a", "b"), "a")
        self.assertEqual(guard.clean_venue_id("zh-kennedys_1:x.y"), "zh-kennedys_1:x.y")
        for bad in ["", None, "a b", "a/b", "../x", "x" * 81, 5, "<script>"]:
            with self.subTest(value=bad), self.assertRaises(guard.ValidationError):
                guard.clean_venue_id(bad)

    def test_clean_price_formats(self):
        for raw, want in [("9.5", "CHF 9.50"), ("CHF 9.50", "CHF 9.50"), ("9,50 Fr.", "CHF 9.50"), (12, "CHF 12.00"), ("", None), (None, None)]:
            with self.subTest(raw=raw):
                self.assertEqual(guard.clean_price(raw), want)
        for bad in ["free", "1000", "0", "CHF 9.5; DROP", True, "9.555"]:
            with self.subTest(raw=bad), self.assertRaises(guard.ValidationError):
                guard.clean_price(bad)

    def test_clean_website(self):
        self.assertIsNone(guard.clean_website(""))
        self.assertIsNone(guard.clean_website(None))
        self.assertEqual(guard.clean_website("pub.ch"), "https://pub.ch")
        for bad in ["javascript:alert(1)", "data:text/html,x", "http://localhost/admin", "http://127.0.0.1/", "http://169.254.169.254/",
                    "http://[::1]/", "http://printer.local/", "http://db.internal/", "ftp://x.ch"]:
            with self.subTest(url=bad), self.assertRaises(guard.ValidationError):
                guard.clean_website(bad)

    def test_safe_google_maps_uri(self):
        ok = ["https://www.google.com/maps/place/Pub/@47.1,8.2,17z", "https://maps.app.goo.gl/abc", "https://google.ch/maps?q=pub"]
        for u in ok:
            with self.subTest(url=u):
                self.assertEqual(guard.safe_google_maps_uri(u), u)
        for u in ["javascript:alert(1)", "http://www.google.com/maps/x", "https://evil.com/maps", "https://google.com.evil.com/maps",
                  "https://www.google.com/search?q=x", None, 5]:
            with self.subTest(url=u):
                self.assertIsNone(guard.safe_google_maps_uri(u))


class SubmissionValidationTests(unittest.TestCase):
    CITIES = {"all", "zurich", "geneva"}

    def test_crowd_report_defaults_and_sanitising(self):
        r = guard.validate_crowd_report({"venueId": "v-1", "servingFormat": "draught", "note": "  great\x00 pint ", "price": "9.5", "hasZero": True})
        self.assertEqual(r, {"venueId": "v-1", "user": "Swiss Guinness Scout", "servingFormat": "draught", "pintRating": None,
                             "price": "CHF 9.50", "hasZero": True, "note": "great pint"})

    def test_regression_a_report_must_say_how_it_is_served_and_a_rating_is_optional(self):
        with self.assertRaises(guard.ValidationError) as ctx:
            guard.validate_crowd_report({"venueId": "v-1"})
        self.assertIn("servingFormat", str(ctx.exception))
        self.assertIsNone(guard.validate_crowd_report({"venueId": "v-1", "servingFormat": "draught", "pintRating": ""})["pintRating"])
        self.assertEqual(guard.validate_crowd_report({"venueId": "v-1", "servingFormat": "draught", "pintRating": "4.5"})["pintRating"], 4.5)

    def test_crowd_report_none_format_has_no_rating(self):
        r = guard.validate_crowd_report({"venueId": "v", "servingFormat": "none", "pintRating": "4.0"})
        self.assertIsNone(r["pintRating"])

    def test_crowd_report_rejects_bad_input(self):
        base = {"venueId": "v"}
        for patch in [{"venueId": "bad id"}, {"servingFormat": "keg"}, {"pintRating": 9}, {"pintRating": "x"}, {"note": "x" * 501},
                      {"user": "x" * 41}, {"price": "lots"}]:
            with self.subTest(patch=patch), self.assertRaises(guard.ValidationError):
                guard.validate_crowd_report({**base, **patch})

    def test_hasZero_must_be_a_real_boolean(self):
        self.assertFalse(guard.validate_crowd_report({"venueId": "v", "servingFormat": "draught", "hasZero": "false"})["hasZero"])

    def test_new_venue_valid(self):
        v = guard.validate_new_venue({"name": " The Pub ", "lat": "47.37", "lng": 8.54, "website": "pub.ch", "city": "all", "price": "CHF 9", "servingFormat": "draught"}, self.CITIES)
        self.assertEqual((v["name"], v["city"], v["lat"], v["website"], v["price"], v["category"]),
                         ("The Pub", "zurich", 47.37, "https://pub.ch", "CHF 9.00", "pub"))

    def test_new_venue_rejections(self):
        ok = {"name": "X", "lat": 47.37, "lng": 8.54, "servingFormat": "draught"}
        for patch in [{"name": ""}, {"name": "x" * 101}, {"category": "casino"}, {"city": "atlantis"}, {"lat": 10}, {"lng": 50},
                      {"lat": "nan"}, {"website": "javascript:alert(1)"}, {"servingFormat": "keg"}, {"address": "x" * 201}]:
            with self.subTest(patch=patch), self.assertRaises(guard.ValidationError):
                guard.validate_new_venue({**ok, **patch}, self.CITIES)


class ClientIpAndRateLimitTests(unittest.TestCase):
    def test_forwarded_headers_only_trusted_behind_a_proxy(self):
        h = {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}
        self.assertEqual(guard.client_ip(h, "10.0.0.1", trust_proxy_headers=True), "203.0.113.9")
        self.assertEqual(guard.client_ip(h, "198.51.100.7", trust_proxy_headers=False), "198.51.100.7")
        self.assertEqual(guard.client_ip({"x-forwarded-for": "garbage"}, "198.51.100.7", True), "198.51.100.7")
        self.assertEqual(guard.client_ip({"x-real-ip": "203.0.113.5"}, None, True), "203.0.113.5")
        self.assertEqual(guard.client_ip({}, None, False), "unknown")

    def test_limit_applies_per_bucket_and_per_ip(self):
        class Counter:
            def __init__(self): self.n = {}
            def incr(self, key, window): self.n[key] = self.n.get(key, 0) + 1; return self.n[key]
        rl = guard.RateLimiter(Counter())
        self.assertEqual([rl.check("write", "1.1.1.1", 2, 60)[0] for _ in range(3)], [True, True, False])
        self.assertTrue(rl.check("write", "2.2.2.2", 2, 60)[0])
        self.assertTrue(rl.check("scan", "1.1.1.1", 2, 60)[0])
        self.assertEqual(rl.check("write", "1.1.1.1", 2, 60), (False, 60))

    def test_fails_open_if_the_counter_store_breaks_and_can_be_disabled(self):
        class Broken:
            def incr(self, *a): raise RuntimeError("down")
        self.assertEqual(guard.RateLimiter(Broken()).check("b", "ip", 1, 60), (True, 0))
        self.assertEqual(guard.RateLimiter(Broken(), enabled=False).check("b", "ip", 1, 60), (True, 0))


if __name__ == "__main__":
    unittest.main()

"""The website crawler (scripts/crawl_switzerland.py): safe fetching, robots.txt, which sites it reads, Overture websites,
the restaurant/hotel "mention" tier and the check that stops a bad crawl from being published."""

import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

import evidence
import guard
import overture
import app_server as app
from tests.helpers import page_server, stop, QuietHandler, serve

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "scripts", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


crawler = load_script("crawl_switzerland")
checker = load_script("check_crawl_result")

REAL_FETCH = guard.fetch_page


def local_fetch(url, **kw):
    """The crawler fetches through guard.fetch_page, which refuses loopback; let it reach the test's local servers."""
    return REAL_FETCH(url, allow_private=True, **kw)


class FetchTests(unittest.TestCase):
    def setUp(self):
        crawler._robots_cache.clear()

    def site(self, routes):
        server, base = page_server(routes)
        self.addCleanup(stop, server)
        patch = mock.patch.object(crawler.guard, "fetch_page", side_effect=local_fetch)
        patch.start()
        self.addCleanup(patch.stop)
        return base

    def test_regression_it_never_fetches_internal_addresses(self):
        """Website addresses come from OpenStreetMap tags anyone can edit: never fetch loopback or cloud-metadata hosts."""
        for url in ("http://127.0.0.1:9/", "http://localhost/", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/"):
            with self.subTest(url=url):
                status, reason = crawler.fetch_html(url)
                self.assertIsNone(status)
                self.assertRegex(reason, r"unsafe|not allowed|public|refus", msg=reason)

    def test_reads_a_page_and_respects_robots_txt(self):
        base = self.site({
            "/robots.txt": (200, {"Content-Type": "text/plain"}, b"User-agent: *\nDisallow: /private\n"),
            "/": (200, {}, b"<html>" + b"x" * 60 + b" Guinness on tap 9.50 CHF</html>"),
            "/private": (200, {}, b"<html>" + b"y" * 60 + b"</html>"),
        })
        self.assertEqual(crawler.fetch_html(base + "/")[0], 200)
        status, reason = crawler.fetch_html(base + "/private")
        self.assertEqual((status, reason), (None, "disallowed by robots.txt"))

    def test_a_site_that_bans_this_crawler_is_left_alone(self):
        base = self.site({"/robots.txt": (200, {}, b"User-agent: GuinnessGuide\nDisallow: /\n"), "/": (200, {}, b"<html>" + b"x" * 60 + b"</html>")})
        self.assertEqual(crawler.fetch_html(base + "/"), (None, "disallowed by robots.txt"))

    def test_a_missing_robots_txt_allows_everything_and_is_asked_once_per_host(self):
        hits = []
        server, base = page_server({"/": (200, {}, b"<html>" + b"x" * 60 + b"</html>"), "/a": (200, {}, b"<html>" + b"x" * 60 + b"</html>")}, hits)
        self.addCleanup(stop, server)
        with mock.patch.object(crawler.guard, "fetch_page", side_effect=local_fetch):
            crawler.fetch_html(base + "/")
            crawler.fetch_html(base + "/a")
        self.assertEqual(hits.count("/robots.txt"), 1)

    def test_scan_finds_guinness_follows_a_menu_link_and_skips_social_media(self):
        base = self.site({
            "/": (200, {}, b"<html><body><p>Welcome to our pub. " + b"w" * 40 + b'</p><a href="/drinks">Drinks</a></body></html>'),
            "/drinks": (200, {}, b"<html><body>Draught: Guinness 5dl CHF 9.80, Kilkenny 8.00</body></html>"),
        })
        res = crawler.scan_venue_website({"website": base + "/"})
        self.assertTrue(res["foundOnMenu"])
        self.assertTrue(res["checkedUrl"].endswith("/drinks"))
        self.assertIn("Guinness", " ".join(res["snippets"]))
        social = crawler.scan_venue_website({"website": "https://www.facebook.com/somepub"})
        self.assertEqual((social["reachable"], social["foundOnMenu"]), (False, False))
        self.assertFalse(crawler.scan_venue_website({"website": base + "/nope"})["reachable"])
        self.assertFalse(crawler.scan_venue_website({})["scanned"])


class SelectionTests(unittest.TestCase):
    URLS = [f"u{i}" for i in range(10)]

    def test_default_is_every_pub_and_bar_plus_400(self):
        self.assertEqual(crawler.select_target_urls(self.URLS, 3), self.URLS)  # (only 10 exist: 3 + 400 covers them)
        many = [f"u{i}" for i in range(1000)]
        self.assertEqual(len(crawler.select_target_urls(many, 100)), 500)

    def test_all_reads_every_site_and_max_urls_caps_it(self):
        many = [f"u{i}" for i in range(1000)]
        self.assertEqual(len(crawler.select_target_urls(many, 100, scan_all=True)), 1000)
        self.assertEqual(crawler.select_target_urls(many, 100, scan_all=True, max_urls=7), many[:7])

    def test_command_line(self):
        a = crawler.parse_args(["--all", "--no-overture", "--max-urls", "50"])
        self.assertEqual((a.all, a.no_overture, a.max_urls), (True, True, 50))
        d = crawler.parse_args([])
        self.assertEqual((d.all, d.no_overture, d.max_urls), (False, False, None))


class OvertureFillTests(unittest.TestCase):
    def index(self):
        return overture.Index([
            {"name": "The Old Stand", "lat": 47.3700, "lng": 8.5400, "website": "https://oldstand.example/"},
            {"name": "Pizza Roma", "lat": 47.3800, "lng": 8.5500, "website": "pizza.example"},
            {"name": "Evil", "lat": 47.3900, "lng": 8.5600, "website": "http://127.0.0.1/admin"},
        ])

    def venues(self):
        mk = lambda name, cat, lat, lng, web=None: {"name": name, "category": cat, "lat": lat, "lng": lng, "website": web, "is_pub_or_candidate": cat == "pub"}
        return [mk("Old Stand", "pub", 47.3701, 8.5401), mk("Pizza Roma", "restaurant", 47.3801, 8.5501), mk("Evil", "pub", 47.3901, 8.5601), mk("Has Site", "pub", 47.37, 8.54, "https://x.example")]

    def test_pubs_get_their_overture_website_and_restaurants_only_with_all(self):
        vs = self.venues()
        self.assertEqual(crawler.fill_websites_from_overture(vs, index=self.index()), 1)
        self.assertEqual((vs[0]["website"], vs[0]["website_source"]), ("https://oldstand.example/", "overture"))
        self.assertIsNone(vs[1]["website"])
        vs = self.venues()
        self.assertEqual(crawler.fill_websites_from_overture(vs, index=self.index(), all_categories=True), 2)
        self.assertEqual(vs[1]["website"], crawler.safe_website("pizza.example"))

    def test_an_unsafe_overture_website_is_never_used_and_an_existing_one_is_kept(self):
        vs = self.venues()
        crawler.fill_websites_from_overture(vs, index=self.index(), all_categories=True)
        self.assertIsNone(vs[2]["website"])
        self.assertEqual(vs[3]["website"], "https://x.example")


class NotTheBeerTests(unittest.TestCase):
    """Regression (crawl of 2026-11-12): an image file named guinness-pour.jpg made Caesar's Bar "Confirmed", and Kennedy's a
    "Beef & Guinness pie". Neither is evidence that the beer is poured."""

    def found(self, html):
        return crawler.parse_guinness_from_html(html)[0]

    def test_a_dish_or_a_record_is_not_a_serving(self):
        for text in ("Hungry enough to take our Beef & Guinness pie? Come & try", "Guinness Beef Stew CHF 22", "Guinness Chocolate Cake CHF 9", "we attempted the Guinness World Record"):
            self.assertFalse(self.found(f"<p>{text}</p>"), text)
            self.assertTrue(evidence.is_food_mention(text), text)

    def test_a_file_name_or_address_is_not_text_a_visitor_reads(self):
        page = '{"fileName":"guinness-pour.jpg","url":"http:\\/\\/files.x.ch\\/image\\/guinness-pour.jpg"}'
        self.assertFalse(self.found(page))
        self.assertFalse(self.found('<img src="/images/guinness/logo.png"><a href="https://x.ch/guinness-menu.pdf">menu</a>'))

    def test_a_drink_is_still_found_even_next_to_food(self):
        for text in ("Guinness Draught 5dl CHF 9.80", "Guinness vom Fass", "Guinness 5dl 10.-", "Beef stew; Guinness on tap", "Frisch gezapftes Guinness, Pie of the day"):
            self.assertTrue(self.found(f"<p>{text}</p>"), text)
            self.assertFalse(evidence.is_food_mention(text), text)

    def test_a_pub_whose_only_mention_is_food_is_a_hint_not_a_confirmation(self):
        self.assertEqual(evidence.website_mention_kind("pub", ["Hungry enough to take our Beef & Guinness pie?"]), "mention")
        self.assertEqual(evidence.website_mention_kind("pub", ["Guinness vom Fass"]), "menu")
        self.assertEqual(evidence.website_mention_kind("pub", []), "mention")


class HostNotFoundTests(unittest.TestCase):
    """A domain that does not resolve is "could not resolve", not "unsafe", and is retried on the other www form."""

    def test_a_dns_failure_is_its_own_error_but_still_an_unsafe_url(self):
        with mock.patch.object(guard.socket, "getaddrinfo", side_effect=guard.socket.gaierror(-2, "Name or service not known")):
            with self.assertRaises(guard.CouldNotResolve) as ctx:
                guard.resolve_public("nope.example", 443)
        self.assertIsInstance(ctx.exception, guard.UnsafeURL)

    def test_the_crawler_says_could_not_resolve(self):
        with mock.patch.object(guard, "fetch_page", side_effect=guard.CouldNotResolve("Could not resolve host (x)")), mock.patch.object(crawler, "robots_allows", return_value=True):
            self.assertTrue(crawler.fetch_html("https://nope.example")[1].startswith("could not resolve host"))

    def test_the_live_scan_tries_the_other_form_when_the_name_does_not_resolve(self):
        calls = []

        def fake(url, **kw):
            calls.append(url)
            if url.startswith("https://www."):
                return "<li>Guinness Draught 5dl CHF 9.80</li>"
            raise guard.CouldNotResolve("Could not resolve host (x)")

        with mock.patch.object(guard, "fetch_page", fake):
            check = app.scrape_menu_url("https://pub.example")
        self.assertTrue(check["foundOnMenu"])
        self.assertEqual(calls, ["https://pub.example", "https://www.pub.example"])


class WwwFallbackTests(unittest.TestCase):
    """Regression: a site that only answers on www (kennedys.ch vs www.kennedys.ch) must not be reported as unreachable."""

    def test_the_other_host_form(self):
        self.assertEqual(guard.other_host_form("https://kennedys.ch/drinks?x=1"), "https://www.kennedys.ch/drinks?x=1")
        self.assertEqual(guard.other_host_form("https://www.kennedys.ch/"), "https://kennedys.ch/")
        self.assertEqual(guard.other_host_form("http://pub.example:8080/a"), "http://www.pub.example:8080/a")
        for url in ("http://127.0.0.1/x", "http://[::1]/x", "http://localhost/x", "nonsense"):
            self.assertIsNone(guard.other_host_form(url), url)

    def test_a_site_that_only_answers_on_www_is_read_there(self):
        calls = []

        def fake_fetch(url, max_time=3.5):
            calls.append(url)
            return (200, "<p>Guinness Draught 5dl CHF 9.80</p>") if url.startswith("https://www.") else (None, "could not resolve host")

        with mock.patch.object(crawler, "fetch_html", fake_fetch):
            res = crawler.scan_venue_website({"website": "https://pub.example"})
        self.assertTrue(res["reachable"] and res["foundOnMenu"])
        self.assertEqual(res["checkedUrl"], "https://www.pub.example")
        self.assertEqual(calls[:2], ["https://pub.example", "https://www.pub.example"])

    def test_a_truly_dead_site_is_still_unreachable_and_robots_is_still_respected(self):
        with mock.patch.object(crawler, "fetch_html", lambda url, max_time=3.5: (None, "could not resolve host")):
            self.assertFalse(crawler.scan_venue_website({"website": "https://dead.example"})["reachable"])
        calls = []

        def blocked(url, max_time=3.5):
            calls.append(url)
            return None, "disallowed by robots.txt"

        with mock.patch.object(crawler, "fetch_html", blocked):
            self.assertFalse(crawler.scan_venue_website({"website": "https://nobots.example"})["reachable"])
        self.assertEqual(calls, ["https://nobots.example"], "a robots.txt refusal is not retried on another host")

    def test_the_live_menu_scan_also_tries_the_other_form(self):
        calls = []

        def fake_fetch(url, **kw):
            calls.append(url)
            if url.startswith("https://www."):
                return "<li>Guinness Draught 5dl CHF 9.80</li>"
            raise OSError("could not resolve host")

        with mock.patch.object(guard, "fetch_page", fake_fetch):
            check = app.scrape_menu_url("https://pub.example")
        self.assertTrue(check["checked"] and check["foundOnMenu"])
        self.assertEqual(calls, ["https://pub.example", "https://www.pub.example"])

    def test_the_live_menu_scan_of_a_dead_site_is_unknown_after_trying_both_forms(self):
        calls = []

        def dead(url, **kw):
            calls.append(url)
            raise OSError("could not resolve host")

        with mock.patch.object(guard, "fetch_page", dead):
            check = app.scrape_menu_url("https://dead.example")
        self.assertFalse(check["checked"], "could not read: unknown, never 'no Guinness'")
        self.assertEqual(calls, ["https://dead.example", "https://www.dead.example"])

    def test_the_live_menu_scan_does_not_retry_an_unsafe_address(self):
        calls = []

        def unsafe(url, **kw):
            calls.append(url)
            raise guard.UnsafeURL("private address")

        with mock.patch.object(guard, "fetch_page", unsafe):
            self.assertFalse(app.scrape_menu_url("https://pub.example")["checked"])
        self.assertEqual(calls, ["https://pub.example"])

    def test_kennedys_is_stored_with_the_address_that_works(self):
        self.assertEqual(next(v for v in app.DEMO_VENUES if v["id"] == "zh-kennedys")["website"], "https://www.kennedys.ch")


class DirectorySiteTests(unittest.TestCase):
    """Regression: a Ticino tourism listing became The Trinity Irish Pub's "website" and was reported as "read: no Guinness text found"."""

    def test_listing_and_social_pages_are_not_a_venues_own_website(self):
        for url in ("http://www.ticino.ch/it/restaurants/details/The-Trinity-Irish-Pub/128703.html", "https://www.tripadvisor.ch/Restaurant_Review-x.html",
                    "https://de.tripadvisor.com/x", "https://www.facebook.com/somepub", "https://m.facebook.com/somepub", "https://www.google.com/maps/place/x",
                    "https://www.booking.com/hotel/ch/x.html", "https://www.local.ch/de/d/lugano/x"):
            self.assertIsNone(crawler.safe_website(url), url)

    def test_a_pubs_own_website_is_kept_even_when_its_name_contains_a_directory_word(self):
        for url in ("https://www.thetrinity.ch/", "https://ticino-pub.example/", "https://notfacebook.com/", "https://maxbar.ch/menu", "https://boxing.example/"):
            self.assertEqual(crawler.is_directory_site(url), False, url)
            self.assertTrue(crawler.safe_website(url), url)

    def test_an_overture_directory_page_is_not_filled_in(self):
        vs = [{"name": "The Trinity Irish Pub", "category": "pub", "lat": 46.00688, "lng": 8.96029, "website": None, "is_pub_or_candidate": True}]
        index = overture.Index([{"name": "The Trinity Irish Pub", "lat": 46.00689, "lng": 8.96031, "website": "http://www.ticino.ch/it/restaurants/details/The-Trinity-Irish-Pub/128703.html"}])
        self.assertEqual(crawler.fill_websites_from_overture(vs, index=index), 0)
        self.assertIsNone(vs[0]["website"])


class StarterListContentTests(unittest.TestCase):
    def test_regression_a_starter_venue_whose_website_is_dead_and_that_nothing_else_verifies_is_not_listed(self):
        """The Shenanigans Irish Pub Lugano (Via Pioda 5) could not be verified anywhere and its website is dead."""
        self.assertFalse([v for v in app.DEMO_VENUES if "shenanigan" in v["name"].lower() or "shenanigan" in str(v.get("website", "")).lower()])


class MentionTierTests(unittest.TestCase):
    """Once restaurants and hotels are read, a recipe must not become a "Confirmed" venue."""

    def test_pubs_and_bars_that_name_guinness_count_as_serving_it(self):
        self.assertEqual(evidence.website_mention_kind("pub", ["Gallus Pub: Geniesst frisches Guinness"]), "menu")
        self.assertEqual(evidence.website_mention_kind("bar", ["we love Guinness"]), "menu")

    def test_restaurants_and_hotels_need_serving_wording_or_a_price(self):
        self.assertEqual(evidence.website_mention_kind("restaurant", ["Beef stew braised in Guinness, with carrots"]), "mention")
        self.assertEqual(evidence.website_mention_kind("hotel", ["St Patrick's night: Guinness and live music"]), "mention")
        self.assertEqual(evidence.website_mention_kind("restaurant", ["Guinness vom Fass 5dl CHF 9.80"]), "menu")
        self.assertEqual(evidence.website_mention_kind("hotel", ["Hardy's: Guinness im Offenausschank"]), "menu")
        self.assertEqual(evidence.website_mention_kind("restaurant", ["Guinness 0.0 alkoholfrei"]), "menu")

    def test_text_from_page_metadata_never_counts_as_a_menu(self):
        self.assertEqual(evidence.website_mention_kind("pub", ['<meta name="keywords" content="Goldau,Guinness,Kilkenny"']), "mention")

    def crawl_record(self, category, snippets):
        return {"id": "ch-node-9", "name": "X", "category": category, "address": "Switzerland", "lat": 47.3, "lng": 8.5, "website": "http://x.example",
                "menuCheck": {"checked": True, "foundOnMenu": True, "typesFound": ["Guinness (Listed on Website Menu)"], "extractedPrice": None, "snippets": snippets}}

    def test_a_restaurant_recipe_becomes_a_possible_hint_not_a_confirmation(self):
        v = evidence.sanitise_static_venue(self.crawl_record("restaurant", ["our stew braised in Guinness"]))
        self.assertEqual(v["tagCheck"]["kind"], evidence.TAG_WEB)
        self.assertFalse(v["menuCheck"]["foundOnMenu"])
        summary = app.compute_guinness_status(v)
        self.assertEqual((summary["status"], summary["statusLabel"]), ("likely_serves", "Possible"))
        self.assertEqual(summary["reason"], "Its website mentions Guinness (not clearly on a menu)")
        # and it stays that way when loaded again
        self.assertEqual(evidence.sanitise_static_venue(v), v)

    def test_a_pub_that_names_guinness_stays_confirmed(self):
        v = evidence.sanitise_static_venue(self.crawl_record("pub", ["Getränke: frisches Guinness, Kilkenny"]))
        self.assertNotIn("tagCheck", v)
        self.assertEqual(app.compute_guinness_status(v)["statusLabel"], "Confirmed")


class CheckCrawlResultTests(unittest.TestCase):
    def write(self, ids):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        path = os.path.join(d, "r.json")
        with open(path, "w") as f:
            json.dump({"confirmedVenues": [{"id": i} for i in ids]}, f)
        return path

    def test_a_normal_update_passes(self):
        ok, msg = checker.check(self.write(["a", "b", "c", "d"]), self.write(["a", "b", "c", "e", "f"]))
        self.assertTrue(ok, msg)
        self.assertIn("2 new", msg)

    def test_regression_a_crawl_that_lost_most_known_venues_is_refused(self):
        ok, msg = checker.check(self.write(list("abcdefghij")), self.write(["a", "b"]))
        self.assertFalse(ok)
        self.assertIn("network trouble", msg)

    def test_empty_missing_or_malformed_new_results_are_refused(self):
        old = self.write(["a"])
        self.assertFalse(checker.check(old, self.write([]))[0])
        self.assertFalse(checker.check(old, "/nonexistent.json")[0])
        bad = os.path.join(tempfile.mkdtemp(), "bad.json")
        with open(bad, "w") as f:
            f.write('{"nope": 1}')
        self.assertFalse(checker.check(old, bad)[0])

    def test_no_previous_results_is_fine(self):
        self.assertTrue(checker.check("/nonexistent.json", self.write(["a"]))[0])

    def test_command_line_exit_codes(self):
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(checker.main(["--old", self.write(["a", "b"]), "--new", self.write(["a", "b"])]), 0)
            self.assertEqual(checker.main(["--old", self.write(list("abcdef")), "--new", self.write(["a"])]), 1)


class StarterListCrawlTests(unittest.TestCase):
    """The hand-written starter list is not in OpenStreetMap's output, so the crawler reads those websites itself."""

    VENUES = [
        {"id": "a", "category": "pub", "website": "https://a.example", "menuUrl": "https://a.example/guessed-link"},
        {"id": "b", "category": "bar", "website": "https://b.example"},
        {"id": "c", "category": "pub", "website": "http://127.0.0.1/secret"},
        {"id": "d", "category": "pub"},
    ]

    def test_it_reads_each_venues_website_and_never_the_guessed_deep_link(self):
        seen = []

        def fake_scan(venue):
            seen.append(venue)
            return {"scanned": True, "reachable": True, "httpStatus": 200, "checkedUrl": venue["website"], "foundOnMenu": venue["website"].startswith("https://a"),
                    "typesFound": ["Guinness Draught (On Tap)"], "extractedPrice": None, "snippets": ["Guinness on tap"]}

        res = crawler.scan_starter_venues(self.VENUES, scan=fake_scan, now_iso="2026-11-11T00:00:00+00:00")
        self.assertEqual(sorted(res), ["a", "b"], "no address that is not a public website, and none without one")
        self.assertTrue(all("menuUrl" not in v for v in seen))
        self.assertEqual(res["a"]["checkedAt"], "2026-11-11T00:00:00+00:00")
        self.assertTrue(res["a"]["foundOnMenu"] and not res["b"]["foundOnMenu"])

    def test_a_crashing_scan_is_unreadable_not_no_guinness(self):
        def boom(_venue):
            raise RuntimeError("tls handshake failed")

        res = crawler.scan_starter_venues(self.VENUES[:1], scan=boom)
        self.assertFalse(res["a"]["reachable"])
        self.assertNotIn("foundOnMenu", res["a"])

    def test_the_overlay_reaches_the_venues_the_app_serves(self):
        target = app.DEMO_VENUES[0]["id"]
        check = {"reachable": True, "checkedAt": "2026-11-11T00:00:00+00:00", "checkedUrl": "https://pub.example/birre",
                 "foundOnMenu": True, "snippets": ["Guinness Draught — Pint CHF 9.20"]}
        with mock.patch.object(app, "load_starter_checks", return_value={target: check}):
            venues = {v["id"]: v for v in app.get_all_combined_venues({})}
        v = venues[target]
        self.assertEqual((v["menuCheck"]["checked"], v["menuCheck"]["foundOnMenu"]), (True, True))
        self.assertEqual(v["menuUrl"], "https://pub.example/birre")
        other = next(x for x in venues.values() if x["id"] != target and str(x["id"]).startswith(("zh-", "al-", "ge-", "ba-")))
        self.assertFalse(other["menuCheck"]["checked"], "venues without a crawler record stay unchecked")
        self.assertNotIn("menuUrl", other)

    def test_regression_the_app_stays_consistent_when_a_crawl_has_read_every_starter_website(self):
        """The first crawl that wrote starterChecks failed its own post-crawl tests (a test assumed no starter venue had been read)."""
        base = {"checkedAt": "2026-11-11T00:00:00+00:00", "reachable": True}
        checks = {}
        for i, v in enumerate(app.DEMO_VENUES):
            site = v["website"]
            checks[v["id"]] = [
                {**base, "checkedUrl": site, "foundOnMenu": True, "snippets": ["Guinness Draught 5dl CHF 9.80"]},
                {**base, "checkedUrl": site, "foundOnMenu": False, "snippets": []},
                {"reachable": False, "error": "timed out"},
            ][i % 3]
        with mock.patch.object(app, "load_starter_checks", return_value=checks):
            venues = {v["id"]: v for v in app.get_all_combined_venues({})}
        for vid, check in checks.items():
            v = venues[vid]
            if check.get("foundOnMenu"):
                self.assertTrue(v["menuCheck"]["foundOnMenu"], vid)
                self.assertNotIn("priceHint", v, "a price read from the website replaces the unchecked hint")
                self.assertEqual(app.compute_guinness_status(v)["statusLabel"], "Confirmed", vid)
            elif check.get("reachable"):
                self.assertTrue(v["menuCheck"]["checked"], vid)
                self.assertNotEqual(app.compute_guinness_status(v)["status"], "no_guinness", f"{vid}: a silent website is not proof")
            else:
                self.assertFalse(v["menuCheck"]["checked"], f"{vid}: an unreadable site changes nothing")
                self.assertEqual(v["tagCheck"]["kind"], "starter_list", vid)

    def test_a_missing_or_malformed_results_file_means_no_checks(self):
        with mock.patch.object(app, "CRAWL_RESULTS_PATH", "/nonexistent.json"):
            self.assertEqual(app.load_starter_checks(), {})
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"starterChecks": ["not", "a", "dict"]}, f)
        try:
            with mock.patch.object(app, "CRAWL_RESULTS_PATH", f.name):
                self.assertEqual(app.load_starter_checks(), {})
        finally:
            os.unlink(f.name)


class WorkflowTests(unittest.TestCase):
    def test_the_crawl_workflow_publishes_a_branch_not_a_pull_request_and_checks_first(self):
        with open(os.path.join(ROOT, ".github", "workflows", "crawl.yml"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("workflow_dispatch", text)
        self.assertIn("check_crawl_result.py", text)
        self.assertIn("git push origin", text)
        self.assertNotIn("gh pr create", text, "a PR made by the workflow would not run the checks that protect main")
        self.assertNotIn("git push origin main", text)
        self.assertLess(text.index("check_crawl_result.py"), text.index("git push origin"))


if __name__ == "__main__":
    unittest.main()

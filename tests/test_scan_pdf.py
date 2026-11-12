"""The scan-menu box accepts a link to a PDF menu: the server reads its text. A PDF it cannot read is "could not be checked", never "no Guinness"."""

import unittest
from unittest import mock

import app_server as app
import evidence
from tests.helpers import make_pdf, page_server, stop

HAVE_PYPDF = evidence.pdf_support()


class ScanPdfTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(app, "FETCH_ALLOW_PRIVATE", True)  # tests talk to a local server; production never sets this
        patch.start()
        self.addCleanup(patch.stop)

    def site(self, routes):
        server, base = page_server(routes)
        self.addCleanup(stop, server)
        return base

    @unittest.skipUnless(HAVE_PYPDF, "needs pypdf")
    def test_a_pdf_menu_with_guinness_is_read(self):
        pdf = make_pdf("DRAUGHT BEERS - GUINNESS - IRL - 4.2% - 5dl CHF 10.00 - Kilkenny 5dl CHF 10.00")
        base = self.site({"/Drinks_Menu.pdf": (200, {"Content-Type": "application/pdf"}, pdf)})
        res = app.scrape_menu_url(base + "/Drinks_Menu.pdf")
        self.assertTrue(res["checked"] and res["foundOnMenu"])
        self.assertEqual(res["extractedPrice"], "CHF 10.00")
        self.assertIn("GUINNESS", " ".join(res["snippets"]).upper())

    @unittest.skipUnless(HAVE_PYPDF, "needs pypdf")
    def test_a_readable_pdf_without_guinness_is_a_modest_negative_that_says_it_was_a_pdf(self):
        base = self.site({"/m.pdf": (200, {}, make_pdf("Pilsner CHF 5.00 - Lager CHF 5.50"))})
        res = app.scrape_menu_url(base + "/m.pdf")
        self.assertTrue(res["checked"])
        self.assertFalse(res["foundOnMenu"])
        self.assertIn("PDF", res["snippets"][0])

    @unittest.skipUnless(HAVE_PYPDF, "needs pypdf")
    def test_a_pdf_behind_a_download_address_is_found_by_its_content(self):
        pdf = make_pdf("GUINNESS draught 5dl CHF 9.80")
        base = self.site({"/download?id=7": (200, {"Content-Type": "application/pdf"}, pdf)})
        res = app.scrape_menu_url(base + "/download?id=7")
        self.assertTrue(res["checked"] and res["foundOnMenu"])

    @unittest.skipUnless(HAVE_PYPDF, "needs pypdf")
    def test_regression_a_pdf_whose_text_is_drawn_as_shapes_is_unknown_not_no_guinness(self):
        """Kennedy's drinks menu PDF lists Guinness on tap, but its letters are outlines: no program can read them."""
        base = self.site({"/Outlined_Menu.pdf": (200, {}, make_pdf(None))})
        res = app.scrape_menu_url(base + "/Outlined_Menu.pdf")
        self.assertFalse(res["checked"], "could not be checked: unknown")
        self.assertFalse(res["foundOnMenu"])
        self.assertIn("could not be checked", res["snippets"][0])
        self.assertNotIn("no explicit", res["snippets"][0])

    def test_without_the_pdf_library_the_server_says_it_cannot_read_pdfs(self):
        base = self.site({"/m.pdf": (200, {}, make_pdf("GUINNESS draught 5dl CHF 9.80"))})
        with mock.patch.object(evidence, "pdf_support", return_value=False):
            res = app.scrape_menu_url(base + "/m.pdf")
        self.assertFalse(res["checked"])
        self.assertIn("cannot read PDF", res["snippets"][0])

    def test_a_broken_oversized_or_fake_pdf_never_raises_and_is_unknown(self):
        base = self.site({"/big.pdf": (200, {}, b"%PDF-1.4\n" + b"0" * 4_000_000), "/fake.pdf": (200, {}, b"<html>Guinness 5dl CHF 9</html>"),
                          "/broken.pdf": (200, {}, b"%PDF-1.4 truncated garbage")})
        for path in ("/big.pdf", "/fake.pdf", "/broken.pdf"):
            res = app.scrape_menu_url(base + path)
            self.assertFalse(res["checked"], path)
            self.assertFalse(res["foundOnMenu"], path)

    def test_a_pdf_on_a_private_address_is_never_fetched(self):
        with mock.patch.object(app, "FETCH_ALLOW_PRIVATE", False):
            for url in ("http://127.0.0.1:9/menu.pdf", "http://169.254.169.254/menu.pdf", "http://localhost/menu.pdf"):
                res = app.scrape_menu_url(url)
                self.assertFalse(res["checked"], url)

    def test_ordinary_pages_are_still_scanned_as_before(self):
        base = self.site({"/": (200, {}, b"<html><body><p>Draught: Guinness 5dl CHF 9.80, Kilkenny 8.00</p></body></html>")})
        res = app.scrape_menu_url(base + "/")
        self.assertTrue(res["checked"] and res["foundOnMenu"])
        self.assertEqual(res["extractedPrice"], "CHF 9.80")

    def test_the_deployed_server_installs_the_pdf_library(self):
        import os

        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "requirements.txt"), encoding="utf-8") as f:
            self.assertRegex(f.read(), r"(?m)^pypdf==\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()

"""Repository hygiene: things that should never be committed, and names that should not drift."""

import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(shutil.which("git") and os.path.isdir(os.path.join(ROOT, ".git")), "needs a git checkout")
class TrackedFilesTests(unittest.TestCase):
    def test_regression_no_file_that_gitignore_excludes_is_tracked(self):
        """swiss_website_scan_audit.json (22,000 lines) was committed before it was ignored, and kept bloating diffs."""
        out = subprocess.run(["git", "ls-files", "-ci", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.split(), [])


class NamingTests(unittest.TestCase):
    def source_files(self):
        for base in ("app_server.py", "guard.py", "overpass.py", "evidence.py", "geocode.py", "storage.py", "api", "src", "public", "scripts"):
            path = os.path.join(ROOT, base)
            if os.path.isfile(path):
                yield path
            else:
                for dirpath, _dirs, files in os.walk(path):
                    for name in files:
                        if name.endswith((".py", ".js", ".jsx", ".html")):
                            yield os.path.join(dirpath, name)

    def test_regression_the_old_product_name_is_gone(self):
        """The code used three names (StoutScout, Guinness Finder, Guinness Guide). Only the saved-key storage name is kept,
        because renaming it would make browsers forget a visitor's saved Google key."""
        offenders = []
        for path in self.source_files():
            text = open(path, encoding="utf-8").read()
            text = text.replace("stoutscout_gmaps_key", "")
            if re.search(r"stoutscout", text, re.I):
                offenders.append(os.path.relpath(path, ROOT))
        self.assertEqual(offenders, [])

    def test_regression_city_fallbacks_name_cities_that_exist(self):
        """App.jsx fell back to DEFAULT_CITIES.dublin, which does not exist (an undefined map centre)."""
        text = open(os.path.join(ROOT, "src", "App.jsx"), encoding="utf-8").read()
        defined = set(re.findall(r"^  (\w+): \{ id: '", text, re.M))
        used = set(re.findall(r"DEFAULT_CITIES\.(\w+)", text))
        self.assertTrue(defined, "could not read DEFAULT_CITIES")
        self.assertEqual(used - defined, set())

    def test_the_ui_does_not_mention_other_countries(self):
        text = open(os.path.join(ROOT, "src", "components", "ApiKeyModal.jsx"), encoding="utf-8").read()
        self.assertNotRegex(text, r"Dublin|London|NYC|Chicago")


if __name__ == "__main__":
    unittest.main()

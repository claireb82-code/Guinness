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


class CiWorkflowTests(unittest.TestCase):
    def test_regression_the_browser_job_cannot_hang_for_ten_minutes_on_unreachable_package_mirrors(self):
        """`playwright install --with-deps` runs apt, which retried for ten minutes and failed the job when the runner could not
        reach Ubuntu's mirrors, before any test ran (PR runs on 2026-11-11). System packages are now a time-boxed best effort."""
        with open(os.path.join(ROOT, ".github", "workflows", "test.yml"), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("--with-deps", text)
        self.assertRegex(text, r"timeout \d+ npx playwright install-deps chromium \|\|")
        self.assertIn("npx playwright install chromium", text)
        self.assertLess(text.index("install-deps"), text.index("npm run test:e2e"))


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


class EnvFileTests(unittest.TestCase):
    """The Node server used to read .env (dotenv); the Python server now does it itself."""

    def write(self, text):
        import tempfile

        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, ".env")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_reads_values_and_skips_comments_blanks_and_empty_values(self):
        import app_server

        env = {}
        path = self.write("# comment\n\nGOOGLE_MAPS_BROWSER_KEY=abc\nGOOGLE_PLACES_API_KEY=\nPORT = 3001\nQUOTED=\"hello world\"\nSINGLE='x'\nnot a line\n")
        names = app_server.load_env_file(path, env)
        self.assertEqual(env, {"GOOGLE_MAPS_BROWSER_KEY": "abc", "PORT": "3001", "QUOTED": "hello world", "SINGLE": "x"})
        self.assertEqual(sorted(names), sorted(env))

    def test_existing_environment_variables_win(self):
        import app_server

        env = {"PORT": "4000"}
        app_server.load_env_file(self.write("PORT=3001\nOTHER=1\n"), env)
        self.assertEqual(env, {"PORT": "4000", "OTHER": "1"})

    def test_a_missing_file_is_fine(self):
        import app_server

        self.assertEqual(app_server.load_env_file("/nonexistent/.env", {}), [])


class NoSecondServerTests(unittest.TestCase):
    def test_the_python_server_is_the_only_api_server(self):
        """There used to be a second, Express copy of the API that nothing deployed; every change had to be made twice."""
        import json

        self.assertFalse(os.path.exists(os.path.join(ROOT, "server", "index.js")))
        deps = json.load(open(os.path.join(ROOT, "package.json"), encoding="utf-8"))["dependencies"]
        self.assertEqual(set(deps) & {"express", "cors", "cheerio", "dotenv"}, set())
        scripts = json.load(open(os.path.join(ROOT, "package.json"), encoding="utf-8"))["scripts"]
        self.assertEqual(scripts["start"], "python3 app_server.py")


class NoPintScoreTests(unittest.TestCase):
    def test_the_pint_score_is_gone_from_the_code(self):
        """The 1-5 pint score was removed. app_server.py keeps one defensive mention (it strips old data)."""
        allowed = {"app_server.py": 3}  # drop_pint_score() (2) and the recentReports filter (1)
        offenders = {}
        for base in ("app_server.py", "guard.py", "evidence.py", "src", "public", "scripts"):
            path = os.path.join(ROOT, base)
            files = [path] if os.path.isfile(path) else [os.path.join(d, f) for d, _s, fs in os.walk(path) for f in fs if f.endswith((".py", ".js", ".jsx", ".html"))]
            for f in files:
                n = len(re.findall(r"pintRating|avgPintRating|Pint Score|rep-rating", open(f, encoding="utf-8").read()))
                if n > allowed.get(os.path.relpath(f, ROOT), 0):
                    offenders[os.path.relpath(f, ROOT)] = n
        self.assertEqual(offenders, {})

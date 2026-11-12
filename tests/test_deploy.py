"""Guards against shipping a Vercel function that cannot start."""

import ast
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def local_imports(path):
    """Top-level project modules (``foo.py`` next to app_server.py) imported by ``path``."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return {n for n in names if os.path.exists(os.path.join(ROOT, f"{n}.py"))}


def bundled_files():
    with open(os.path.join(ROOT, "vercel.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    pattern = cfg["functions"]["api/index.py"]["includeFiles"]
    m = re.fullmatch(r"\{(.+)\}", pattern)
    return set(m.group(1).split(",")) if m else {pattern}


class VercelBundleTests(unittest.TestCase):
    def test_every_local_module_the_function_imports_is_bundled(self):
        """api/index.py -> app_server.py -> guard.py / storage.py ... must all be in includeFiles,
        otherwise the deployed function crashes with ImportError on its first request."""
        bundled = bundled_files()
        seen, todo = set(), {"app_server"}
        while todo:
            mod = todo.pop()
            seen.add(mod)
            todo |= local_imports(os.path.join(ROOT, f"{mod}.py")) - seen
        self.assertEqual({m for m in seen if f"{m}.py" not in bundled}, set(), f"bundled: {sorted(bundled)}")
        self.assertIn("guard", seen)
        self.assertIn("storage", seen)

    def test_the_function_entrypoint_imports_cleanly(self):
        import importlib.util
        import sys

        sys.path.insert(0, ROOT)  # api/index.py does this itself on Vercel
        try:
            spec = importlib.util.spec_from_file_location("vercel_entry", os.path.join(ROOT, "api", "index.py"))
            entry = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(entry)
        finally:
            sys.path.remove(ROOT)
        self.assertTrue(hasattr(entry, "handler"))

    def test_regression_include_files_stays_within_vercels_256_character_limit(self):
        """Vercel validates vercel.json before building and refuses an includeFiles string longer than 256 characters. Listing each data file by
        name outgrew it (the deploy of PR #35 failed with 'should NOT be longer than 256 characters'); a glob does not."""
        with open(os.path.join(ROOT, "vercel.json"), encoding="utf-8") as f:
            pattern = json.load(f)["functions"]["api/index.py"]["includeFiles"]
        self.assertLessEqual(len(pattern), 256, len(pattern))

    def test_data_files_the_app_reads_are_bundled(self):
        import fnmatch
        import sys

        sys.path.insert(0, ROOT)
        try:
            import app_server
        finally:
            sys.path.remove(ROOT)
        patterns = bundled_files()
        # overture.DATA_PATH is not used: other tests point it at a dummy file through OVERTURE_DATA_PATH
        read = [app_server.CRAWL_RESULTS_PATH, app_server.GOOGLE_PLACE_IDS_PATH, app_server.EXCLUDED_VENUES_PATH, app_server.MENU_READINGS_PATH,
                os.path.join(ROOT, "server", "data", "overture_ch.json")]
        for path in read:
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            self.assertTrue(any(fnmatch.fnmatch(rel, pat) for pat in patterns), f"{rel} is read by the app but not bundled: {sorted(patterns)}")
        self.assertTrue(any(p.startswith("public/") for p in patterns))
        # and no tracked data file is left out by a pattern that forgot it
        for name in os.listdir(os.path.join(ROOT, "server", "data")):
            if name.endswith(".json"):
                self.assertTrue(any(fnmatch.fnmatch(f"server/data/{name}", pat) for pat in patterns), name)

    def test_no_secrets_are_committed(self):
        pattern = re.compile(r"AIza[0-9A-Za-z_\-]{30,}")
        for dirpath, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "dist", "__pycache__")]
            for name in files:
                if name.endswith((".py", ".js", ".jsx", ".html", ".json", ".md", ".example")):
                    with open(os.path.join(dirpath, name), encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    self.assertIsNone(pattern.search(text), f"possible Google API key in {name}")


if __name__ == "__main__":
    unittest.main()

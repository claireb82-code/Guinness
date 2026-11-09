"""The deployed-commit report in /api/config and scripts/check_deploy.py."""

import importlib.util
import json
import os
import unittest
import urllib.error
from unittest import mock

from tests.test_api import ApiTestCase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHA = "0123456789abcdef0123456789abcdef01234567"

spec = importlib.util.spec_from_file_location("check_deploy", os.path.join(ROOT, "scripts", "check_deploy.py"))
check_deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_deploy)


class VercelDeploymentInfoTests(ApiTestCase):
    vercel = True
    env = {"VERCEL_GIT_COMMIT_SHA": SHA.upper(), "VERCEL_GIT_COMMIT_REF": "claude/default-guinness-filter", "VERCEL_ENV": "preview"}

    def test_config_reports_the_deployed_commit(self):
        dep = self.call("GET", "/api/config")[1]["deployment"]
        self.assertEqual(dep, {"commit": SHA, "commitShort": SHA[:7], "branch": "claude/default-guinness-filter", "environment": "preview"})

    def test_nothing_else_from_the_environment_leaks(self):
        with mock.patch.dict(os.environ, {"VERCEL_OIDC_TOKEN": "SECRET_TOKEN", "VERCEL_GIT_REPO_OWNER": "someone"}):
            body = json.dumps(self.call("GET", "/api/config")[1])
        self.assertNotIn("SECRET_TOKEN", body)
        self.assertNotIn("someone", body)

    def test_malformed_values_are_dropped_not_echoed(self):
        bad = {"VERCEL_GIT_COMMIT_SHA": "<script>alert(1)</script>", "VERCEL_GIT_COMMIT_REF": "main\n<img src=x>", "VERCEL_ENV": "evil"}
        with mock.patch.dict(os.environ, bad):
            dep = self.call("GET", "/api/config")[1]["deployment"]
        self.assertEqual(dep, {"commit": None, "commitShort": None, "branch": None, "environment": "unknown"})

    def test_short_shas_and_all_environments(self):
        for env in ("production", "preview", "development"):
            with mock.patch.dict(os.environ, {"VERCEL_GIT_COMMIT_SHA": "abc1234", "VERCEL_ENV": env}):
                dep = self.call("GET", "/api/config")[1]["deployment"]
            self.assertEqual((dep["commit"], dep["environment"]), ("abc1234", env))


class LocalDeploymentInfoTests(ApiTestCase):
    def test_a_local_run_says_so(self):
        for key in ("VERCEL_GIT_COMMIT_SHA", "VERCEL_GIT_COMMIT_REF", "VERCEL_ENV"):
            os.environ.pop(key, None)
        dep = self.call("GET", "/api/config")[1]["deployment"]
        self.assertEqual(dep, {"commit": None, "commitShort": None, "branch": None, "environment": "local"})


class CommitMatchTests(unittest.TestCase):
    def test_short_and_full_shas_match_by_prefix(self):
        self.assertTrue(check_deploy.commit_matches(SHA, SHA))
        self.assertTrue(check_deploy.commit_matches("0123456", SHA))
        self.assertTrue(check_deploy.commit_matches(SHA, "0123456"))
        self.assertTrue(check_deploy.commit_matches("0123456", SHA.upper()))

    def test_different_or_missing_commits_do_not_match(self):
        self.assertFalse(check_deploy.commit_matches("deadbee", SHA))
        self.assertFalse(check_deploy.commit_matches("", SHA))
        self.assertFalse(check_deploy.commit_matches(SHA, None))
        self.assertFalse(check_deploy.commit_matches("0123457", SHA))


def config(commit=SHA, env="production", branch="main", include=True):
    dep = {"commit": commit, "commitShort": (commit or "")[:7], "branch": branch, "environment": env}
    return {"deployment": dep} if include else {"cities": {}}


class CheckOnceTests(unittest.TestCase):
    def check(self, cfg, expected="0123456", **kw):
        return check_deploy.check_once("https://x.example", expected, fetch=lambda url: cfg, **kw)

    def test_live(self):
        status, msg = self.check(config())
        self.assertEqual(status, "ok")
        self.assertIn("LIVE", msg)

    def test_a_different_commit_is_a_mismatch_and_names_both(self):
        status, msg = self.check(config(commit="f" * 40))
        self.assertEqual(status, "mismatch")
        self.assertIn("fffffff", msg)
        self.assertIn("0123456", msg)

    def test_an_old_deployment_without_version_info(self):
        self.assertEqual(self.check(config(include=False))[0], "old")

    def test_no_commit_reported_means_this_is_not_a_vercel_deployment(self):
        status, msg = self.check(config(commit=None, env="local"))
        self.assertEqual(status, "old")
        self.assertIn("Vercel", msg)

    def test_environment_can_be_required(self):
        self.assertEqual(self.check(config(env="preview"), environment="production")[0], "mismatch")
        self.assertEqual(self.check(config(env="production"), environment="production")[0], "ok")

    def test_unreachable_is_down_not_a_crash(self):
        def boom(url):
            raise urllib.error.URLError("connection refused")

        self.assertEqual(check_deploy.check_once("https://x.example", "0123456", fetch=boom)[0], "down")


class MainTests(unittest.TestCase):
    def run_main(self, argv, configs, clock_step=1):
        """Feed ``configs`` one per fetch; fake time advances ``clock_step`` seconds per sleep."""
        queue, lines, now = list(configs), [], [0]

        def fetch(url):
            return queue.pop(0) if len(queue) > 1 else queue[0]

        def sleep(seconds):
            now[0] += seconds * clock_step

        code = check_deploy.main(argv, fetch=fetch, sleep=sleep, clock=lambda: now[0], out=lines.append)
        return code, lines

    def test_match_exits_0(self):
        code, lines = self.run_main(["https://x.example", "--commit", "0123456"], [config()])
        self.assertEqual(code, 0)
        self.assertIn("LIVE", lines[-1])

    def test_mismatch_without_wait_exits_1_after_one_check(self):
        code, lines = self.run_main(["https://x.example", "--commit", "0123456"], [config(commit="f" * 40)])
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 1)

    def test_wait_polls_until_the_new_commit_appears(self):
        old, new = config(commit="a" * 40), config()
        code, lines = self.run_main(["https://x.example", "--commit", "0123456", "--wait", "60", "--interval", "5"], [old, old, new])
        self.assertEqual(code, 0)
        self.assertEqual([l.startswith("waiting") for l in lines], [True, True, False])

    def test_wait_gives_up_at_the_deadline(self):
        code, lines = self.run_main(["https://x.example", "--commit", "0123456", "--wait", "20", "--interval", "10"], [config(commit="a" * 40)])
        self.assertEqual(code, 1)
        self.assertTrue(lines[-1].startswith("not live yet"))

    def test_unreachable_exits_2(self):
        def boom(url):
            raise urllib.error.URLError("nope")

        lines = []
        code = check_deploy.main(["https://x.example", "--commit", "0123456"], fetch=boom, out=lines.append)
        self.assertEqual(code, 2)

    def test_bad_expected_commit_is_a_usage_error(self):
        for bad in ("xyz", "123", "<script>"):
            lines = []
            self.assertEqual(check_deploy.main(["https://x.example", "--commit", bad], fetch=lambda u: config(), out=lines.append), 2, bad)

    def test_head_uses_the_current_git_commit(self):
        with mock.patch.object(check_deploy, "head_commit", return_value=SHA):
            code, _ = self.run_main(["https://x.example", "--head"], [config()])
        self.assertEqual(code, 0)

    def test_requires_exactly_one_of_commit_or_head(self):
        with self.assertRaises(SystemExit):
            check_deploy.main(["https://x.example"])
        with self.assertRaises(SystemExit):
            check_deploy.main(["https://x.example", "--head", "--commit", "0123456"])


class FetchConfigTests(ApiTestCase):
    """The script against the real server (this is what you would run against Vercel)."""

    vercel = True
    env = {"VERCEL_GIT_COMMIT_SHA": SHA, "VERCEL_ENV": "production", "VERCEL_GIT_COMMIT_REF": "main"}

    def test_end_to_end_against_a_live_server(self):
        url = f"http://127.0.0.1:{self.server.server_address[1]}"
        lines = []
        self.assertEqual(check_deploy.main([url, "--commit", SHA[:7], "--environment", "production"], out=lines.append), 0)
        self.assertEqual(check_deploy.main([url, "--commit", "deadbee"], out=lines.append), 1)

    def test_refuses_non_http_urls(self):
        for bad in ("file:///etc/passwd", "ftp://x", "javascript:1", "x.example"):
            with self.assertRaises(ValueError):
                check_deploy.fetch_config(bad)


if __name__ == "__main__":
    unittest.main()

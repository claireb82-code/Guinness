#!/usr/bin/env python3
"""
Check that a git push is actually live on a deployment.

The app reports which commit is serving it in ``/api/config`` -> ``deployment`` (Vercel exposes the
commit to the function as VERCEL_GIT_COMMIT_SHA). This script fetches that and compares it with the
commit you expect, optionally waiting while Vercel builds.

    python3 scripts/check_deploy.py https://guinness-pi.vercel.app --head
    python3 scripts/check_deploy.py https://guinness-pi.vercel.app --commit a1b2c3d --wait 300
    python3 scripts/check_deploy.py https://<preview-url> --head --environment preview

Exit status: 0 = the expected commit is live, 1 = a different/unknown commit is live (or the wait
ran out), 2 = bad usage or the deployment could not be reached.
"""

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def fetch_config(base_url, timeout=15):
    """GET <base_url>/api/config and return the parsed JSON object (raises on any problem)."""
    parts = urllib.parse.urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("URL must start with http:// or https://")
    url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/api/config", "", ""))
    req = urllib.request.Request(url, headers={"User-Agent": "guinness-check-deploy/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("unexpected response from /api/config")
    return data


def commit_matches(expected, actual):
    """Short and full SHAs both work: the shorter one must be a prefix of the other (>= 7 chars)."""
    if not expected or not actual:
        return False
    expected, actual = expected.lower(), actual.lower()
    return actual.startswith(expected) or expected.startswith(actual)


def head_commit():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def check_once(url, expected, environment=None, fetch=fetch_config):
    """Returns (status, message): status is 'ok', 'mismatch', 'old' (no version info) or 'down'."""
    try:
        config = fetch(url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return "down", f"could not reach {url}: {exc}"
    dep = config.get("deployment")
    if not isinstance(dep, dict):
        return "old", "the live app does not report its version yet (it was deployed before this check existed)"
    live = dep.get("commit")
    if not live:
        return "old", f"the live app reports no commit (environment: {dep.get('environment')}); is this a Vercel deployment?"
    if environment and dep.get("environment") != environment:
        return "mismatch", f"live environment is '{dep.get('environment')}', expected '{environment}'"
    if commit_matches(expected, live):
        return "ok", f"LIVE: {live[:7]} ({dep.get('environment')}, branch {dep.get('branch')}) matches the expected commit"
    return "mismatch", f"live commit is {live[:7]} ({dep.get('environment')}, branch {dep.get('branch')}), expected {expected[:7]}"


def main(argv=None, fetch=fetch_config, sleep=time.sleep, clock=time.monotonic, out=print):
    parser = argparse.ArgumentParser(description="Check which commit is live on a deployment.")
    parser.add_argument("url", help="deployment URL, e.g. https://guinness-pi.vercel.app")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--commit", help="expected commit SHA (7-40 hex characters)")
    which.add_argument("--head", action="store_true", help="expect the current git HEAD")
    parser.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="keep checking until it matches (default: check once)")
    parser.add_argument("--interval", type=int, default=10, metavar="SECONDS")
    parser.add_argument("--environment", choices=["production", "preview", "development"], help="also require this Vercel environment")
    args = parser.parse_args(argv)

    expected = head_commit() if args.head else args.commit.strip().lower()
    if not SHA_RE.match(expected or ""):
        out("error: the expected commit must be 7-40 hex characters")
        return 2

    deadline = clock() + max(0, args.wait)
    while True:
        status, message = check_once(args.url, expected, args.environment, fetch)
        if status == "ok":
            out(message)
            return 0
        if clock() >= deadline:
            out(("not live yet: " if args.wait else "") + message)
            return 2 if status == "down" else 1
        out(f"waiting... ({message})")
        sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())

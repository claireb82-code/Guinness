#!/usr/bin/env python3
"""
Sanity-check a fresh crawl before it is published.

A crawl that ran into network trouble reads fewer websites and so "finds" fewer Guinness venues; committing that would silently
drop venues we already know about. This compares the new results file with the committed one and fails when the new one has
lost more than ``--max-drop`` (default 30%) of the previously confirmed venues, or is empty or malformed.

    python3 scripts/check_crawl_result.py --old old.json --new server/data/swiss_crawl_results.json
"""

import argparse
import json
import sys


def venue_ids(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("confirmedVenues"), list):
        raise ValueError(f"{path}: not a crawl results file (no confirmedVenues list)")
    return {v.get("id") for v in data["confirmedVenues"] if isinstance(v, dict) and v.get("id")}


def check(old_path, new_path, max_drop=0.30):
    """Returns (ok, message)."""
    try:
        new = venue_ids(new_path)
    except (OSError, ValueError) as exc:
        return False, f"cannot read the new results: {exc}"
    if not new:
        return False, "the new results contain no confirmed venues"
    try:
        old = venue_ids(old_path)
    except (OSError, ValueError):
        return True, f"no usable previous results to compare with; {len(new)} confirmed venues"
    lost = old - new
    gained = new - old
    if old and len(lost) / len(old) > max_drop:
        return False, f"{len(lost)} of {len(old)} previously confirmed venues are missing from the new results (limit {max_drop:.0%}); the crawl probably ran into network trouble"
    return True, f"{len(new)} confirmed venues ({len(gained)} new, {len(lost)} no longer found)"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--max-drop", type=float, default=0.30)
    args = ap.parse_args(argv)
    ok, message = check(args.old, args.new, args.max_drop)
    print(("OK: " if ok else "FAILED: ") + message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

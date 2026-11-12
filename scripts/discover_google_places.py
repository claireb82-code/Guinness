#!/usr/bin/env python3
"""
One-off Google Places discovery run: attach Google place IDs to venues we already have, and find venues we don't.

What is stored, and what is not
-------------------------------
Google's terms allow place IDs to be stored; most other Places content (names, ratings, reviews, website addresses, photos) may
only be shown, not kept. So this run uses Google's answers *in memory only* and writes:

* ``placeIds``   our venue id -> Google place ID, for venues we already have (matched by name and distance);
* ``findings``   for places whose own website was read and names Guinness as served: the place ID, our venue id if there is one,
                 and what *the venue's website* said (that text is the venue's, not Google's). No Google name, address, rating,
                 review or website address is written. A person opens the place ID in Google Maps to see what it is.

Cost control: a hard cap on requests (``--max-requests``, default 240) and a stop at the first quota or permission error. Set a daily
quota limit and a budget alert in Google Cloud as well; the cap here is a second fence, not the only one.

    GOOGLE_PLACES_API_KEY=... python3 scripts/discover_google_places.py [--max-requests 240] [--dry-run]

The key is read from the environment only, never from an argument, and is never printed.
"""

import argparse
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
import overture  # noqa: E402 - name similarity and a spatial index

OUTPUT_PATH = os.path.join(ROOT_DIR, "server", "data", "google_place_ids.json")
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
# Transient fields: used in this process only (see the module docstring). nextPageToken is needed to page.
FIELD_MASK = "nextPageToken,places.id,places.displayName,places.location,places.websiteUri"
QUERIES = ("Irish pub", "pub Guinness", "bar")
MAX_PAGES = 3
DEFAULT_MAX_REQUESTS = 240
MATCH_MAX_M = 120
MATCH_MIN_SCORE = 0.8

# name, latitude, longitude, bias radius in metres
LOCATIONS = (
    ("Zurich", 47.3769, 8.5417, 6000), ("Winterthur", 47.5001, 8.7240, 4000), ("Geneva", 46.2044, 6.1432, 6000),
    ("Lausanne", 46.5197, 6.6323, 5000), ("Montreux", 46.4312, 6.9114, 5000), ("Basel", 47.5596, 7.5886, 5000),
    ("Aarau", 47.3925, 8.0442, 4000), ("Bern", 46.9480, 7.4474, 5000), ("Fribourg", 46.8065, 7.1620, 4000),
    ("Neuchatel", 46.9899, 6.9293, 4000), ("Biel", 47.1368, 7.2467, 4000), ("Thun", 46.7580, 7.6280, 4000),
    ("Lucerne", 47.0502, 8.3093, 5000), ("Zug", 47.1724, 8.5170, 4000), ("St. Gallen", 47.4245, 9.3767, 5000),
    ("Schaffhausen", 47.6970, 8.6349, 4000), ("Chur", 46.8499, 9.5329, 4000), ("Davos", 46.8027, 9.8360, 5000),
    ("St. Moritz", 46.4908, 9.8355, 5000), ("Lugano", 46.0037, 8.9511, 5000), ("Locarno", 46.1708, 8.7995, 4000),
    ("Sion", 46.2293, 7.3598, 4000), ("Interlaken", 46.6863, 7.8632, 4000), ("Zermatt", 46.0207, 7.7491, 3000),
)


class QuotaOrPermission(Exception):
    """Google refused (quota, billing, key restriction): stop at once rather than keep asking."""


def load_crawler():
    spec = importlib.util.spec_from_file_location("crawl_switzerland", os.path.join(ROOT_DIR, "scripts", "crawl_switzerland.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def http_post(url, body, headers, timeout=20):
    """POST JSON, return parsed JSON. 403/429 raise QuotaOrPermission; other failures return None (one failed request is not the run)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401, 403, 429):
            raise QuotaOrPermission(f"Google answered HTTP {exc.code}") from None
        return None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def plan(max_requests):
    """The (location, query) pairs in the order they will be tried; each costs 1-MAX_PAGES requests."""
    return [(loc, q) for q in QUERIES for loc in LOCATIONS][: max(0, max_requests)]


def search(api_key, loc, query, budget, post=http_post):
    """Yield places for one location and query (up to MAX_PAGES pages). ``budget`` is a one-item list holding the requests left."""
    _name, lat, lng, radius = loc
    token = None
    for _page in range(MAX_PAGES):
        if budget[0] <= 0:
            return
        budget[0] -= 1
        body = {"textQuery": query, "regionCode": "CH", "pageSize": 20,
                "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": float(radius)}}}
        if token:
            body["pageToken"] = token
        data = post(SEARCH_URL, body, {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK})
        if not data:
            return
        yield from data.get("places") or []
        token = data.get("nextPageToken")
        if not token:
            return
        time.sleep(0.2)


def match_known(index, place):
    name = ((place.get("displayName") or {}).get("text") or "").strip()
    loc = place.get("location") or {}
    if not name or loc.get("latitude") is None or loc.get("longitude") is None:
        return None
    return index.find(name, float(loc["latitude"]), float(loc["longitude"]), max_m=MATCH_MAX_M, min_score=MATCH_MIN_SCORE)


def run(api_key, known_venues, max_requests=DEFAULT_MAX_REQUESTS, post=http_post, crawler=None, scan=None):
    """Returns the output document. ``known_venues`` are dicts with id, name, lat, lng and (optionally) menuCheck."""
    crawler = crawler or load_crawler()
    scan = scan or crawler.scan_venue_website
    index = overture.Index([{"name": v["name"], "lat": v["lat"], "lng": v["lng"], "id": v["id"], "checked": bool((v.get("menuCheck") or {}).get("checked"))}
                            for v in known_venues if v.get("name") and v.get("lat") is not None and v.get("lng") is not None])
    budget = [max_requests]
    place_ids, findings, seen, stopped = {}, [], set(), None
    for loc, query in plan(len(LOCATIONS) * len(QUERIES)):
        if budget[0] <= 0:
            stopped = "request cap reached"
            break
        try:
            for place in search(api_key, loc, query, budget, post=post):
                pid = place.get("id")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                known = match_known(index, place)
                if known:
                    place_ids.setdefault(known["id"], pid)
                site = crawler.safe_website(place.get("websiteUri"))  # Google's address for the venue: read, never written
                if site and not (known and known.get("checked")):
                    res = scan({"website": site})
                    if res.get("foundOnMenu"):
                        findings.append({"placeId": pid, "venueId": known["id"] if known else None, "typesFound": res.get("typesFound") or [],
                                         "extractedPrice": res.get("extractedPrice"), "snippets": (res.get("snippets") or [])[:3]})
        except QuotaOrPermission as exc:
            stopped = str(exc)
            break
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "note": "Google place IDs only, plus text from venues' own websites. No other Google content is stored here.",
        "requestsUsed": max_requests - budget[0],
        "placesSeen": len(seen),
        "stopped": stopped,
        "placeIds": dict(sorted(place_ids.items())),
        "findings": sorted(findings, key=lambda f: f["placeId"]),
    }


def merge_with_existing(doc, path=OUTPUT_PATH):
    """Place IDs found earlier are kept (they do not expire quickly); a new run adds to and updates them."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            old = json.load(f)
        merged = {**(old.get("placeIds") or {}), **doc["placeIds"]}
        doc["placeIds"] = dict(sorted(merged.items()))
    except (OSError, ValueError, AttributeError):
        pass
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS, help="hard cap on Google requests (default %(default)s)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the worst-case request count; call nothing")
    args = ap.parse_args(argv)
    worst = min(args.max_requests, len(LOCATIONS) * len(QUERIES) * MAX_PAGES)
    print(f"Plan: {len(LOCATIONS)} places x {len(QUERIES)} searches x up to {MAX_PAGES} pages; at most {worst} Google requests (cap {args.max_requests}).")
    if args.dry_run:
        return 0
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        print("GOOGLE_PLACES_API_KEY is not set. Add it as a repository secret (Settings > Secrets and variables > Actions) or export it.", file=sys.stderr)
        return 2
    import app_server  # noqa: E402 - the venues we already have, as the app serves them

    known = [v for v in app_server.get_all_combined_venues({})]
    doc = merge_with_existing(run(api_key, known, max_requests=args.max_requests))
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"Requests used: {doc['requestsUsed']}; places seen: {doc['placesSeen']}; matched to our venues: {len(doc['placeIds'])}; "
          f"venue websites naming Guinness: {len(doc['findings'])}" + (f"; stopped: {doc['stopped']}" if doc["stopped"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

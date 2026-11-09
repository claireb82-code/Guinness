#!/usr/bin/env python3
"""
Import hospitality venues from Overture Maps (the open "places" dataset) into
server/data/overture_ch.json, a compact file the app uses to fill in missing venue websites
(see overture.py).

Why: OpenStreetMap lists a website for only about a third of Swiss venues; Overture lists one for
roughly half. A website is what the Guinness scanner needs.

    pip install pyarrow            # only this script needs it (the app itself is stdlib only)
    python3 scripts/import_overture.py                         # latest release, Switzerland
    python3 scripts/import_overture.py --release 2026-10-21.0  # pin a release
    python3 scripts/import_overture.py --max-row-groups 4      # quick smoke test

How it works: the places theme is ~16 Parquet files of ~750 MB each, sorted spatially. Their footers
carry per-row-group bounding boxes, so only the row groups that overlap the country are downloaded
(a few hundred MB for Switzerland), using plain HTTPS range requests (no S3 SDK, no DuckDB
extension, works through proxies). Rows are then filtered by their address country, status,
confidence and category.

Adding another country later = one entry in COUNTRIES (and a matching lookup in overture.py).

Data licence: Overture's places theme is published under CDLA-Permissive-2.0 and keeps its sources'
attributions; see server/data/OVERTURE_ATTRIBUTION.md. Check the current terms before redistributing.
"""

import argparse
import concurrent.futures
import datetime
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import guard  # noqa: E402  (shared URL rules)

BUCKET = "https://overturemaps-us-west-2.s3.amazonaws.com"
PLACES_PREFIX = "theme=places/type=place/"

# country code -> (name, (west, south, east, north) bounding box used to pick row groups)
COUNTRIES = {
    "CH": ("Switzerland", (5.9, 45.7, 10.65, 47.95)),
}

COLUMNS = ["id", "names", "taxonomy", "websites", "phones", "addresses", "confidence", "operating_status", "bbox"]

# Overture lists social/booking/aggregator pages as "websites"; none of them is a venue's own menu.
NOT_A_VENUE_SITE = re.compile(
    r"(^|\.)(facebook|fb|instagram|twitter|x|tiktok|youtube|linkedin|pinterest|whatsapp|wa|"
    r"tripadvisor|yelp|thefork|opentable|booking|expedia|hrs|airbnb|trivago|kayak|"
    r"google|goo|maps|ubereats|just-eat|justeat|wolt|smood|eat|lieferando|"
    r"linktr|linktree|business|wixsite|squarespace)\.",
    re.I,
)

# Directories, link shorteners and booking marketplaces (exact domains, subdomains included).
NOT_A_VENUE_DOMAINS = {"local.ch", "search.ch", "bit.ly", "g.co", "goo.gl", "tinyurl.com", "linktr.ee", "bnb.ch", "bookings.zenchef.com"}

HOTEL_TYPES = {"hotel", "resort", "motel", "inn", "lodge", "guest_house", "bed_and_breakfast", "hostel"}
NOT_BARS = {"hookah_bar", "smoothie_juice_bar", "juice_bar", "salad_bar", "airport_lounge", "bar_tabac", "winery", "brewery"}
PUB_TYPES = {"pub", "irish_pub", "gastropub"}


# --------------------------------------------------------------------------------------
# Pure logic (unit-tested without network or pyarrow)
# --------------------------------------------------------------------------------------


def classify(taxonomy):
    """Map an Overture taxonomy to one of our categories: pub / bar / restaurant / hotel / None.

    Overture's hierarchy looks like ["food_and_drink", "alcoholic_beverage_venue", "bar", "pub", "irish_pub"],
    ["food_and_drink", "restaurant", "french_restaurant"] or ["lodging", "hotel"].
    """
    if not isinstance(taxonomy, dict):
        return None
    primary = (taxonomy.get("primary") or "").lower()
    hierarchy = [str(h).lower() for h in (taxonomy.get("hierarchy") or [])]
    root = hierarchy[0] if hierarchy else ""
    if root == "lodging":
        return "hotel" if primary in HOTEL_TYPES else None
    if root != "food_and_drink":
        return None
    if primary in NOT_BARS:
        return None
    if primary in PUB_TYPES or "pub" in hierarchy:
        return "pub"
    if "bar" in hierarchy or primary in ("lounge", "beer_garden") or primary.endswith("_bar"):
        return "bar"
    if "restaurant" in hierarchy or primary.endswith("_restaurant") or primary == "restaurant":
        return "restaurant"
    return None


def usable_website(websites):
    """First entry that is a plausible venue website (public http(s), not a social/booking page)."""
    for raw in websites or []:
        try:
            url = guard.clean_website(raw)
        except guard.ValidationError:
            continue
        if not url:
            continue
        host = guard.host_of(url)
        if NOT_A_VENUE_SITE.search(host + ".") or any(host == d or host.endswith("." + d) for d in NOT_A_VENUE_DOMAINS):
            continue
        return url
    return None


def format_address(addresses):
    if not addresses:
        return ""
    a = addresses[0] or {}
    town = " ".join(p for p in ((a.get("postcode") or "").strip(), (a.get("locality") or "").strip()) if p)
    return ", ".join(p for p in ((a.get("freeform") or "").strip(), town) if p)


def normalize_place(row, country, min_confidence=0.5, require_website=True):
    """Turn one Overture row into our compact record, or None if it should be skipped."""
    addresses = row.get("addresses") or []
    if not addresses or (addresses[0] or {}).get("country") != country:
        return None  # also drops French/Italian/German places inside the bounding box
    if row.get("operating_status") in ("permanently_closed", "temporarily_closed", "closed"):
        return None
    confidence = row.get("confidence")
    if confidence is None or confidence < min_confidence:
        return None
    category = classify(row.get("taxonomy"))
    if not category:
        return None
    name = ((row.get("names") or {}).get("primary") or "").strip()
    box = row.get("bbox") or {}
    if not name or box.get("xmin") is None or box.get("ymin") is None:
        return None
    website = usable_website(row.get("websites"))
    if require_website and not website:
        return None
    phones = row.get("phones") or []
    return {
        "id": row["id"],
        "name": name[:120],
        "category": category,
        "lat": round(float(box["ymin"]), 5),
        "lng": round(float(box["xmin"]), 5),
        "website": website,
        "phone": (phones[0].strip()[:30] if phones and phones[0] else None),
        "address": format_address(addresses)[:160],
        "confidence": round(float(confidence), 2),
    }


def dedupe(places):
    """Drop exact repeats (same name at the same spot), keeping the most confident."""
    best = {}
    for p in places:
        key = (p["name"].lower(), round(p["lat"], 4), round(p["lng"], 4))
        if key not in best or p["confidence"] > best[key]["confidence"]:
            best[key] = p
    return sorted(best.values(), key=lambda p: p["id"])


def row_groups_overlapping(metadata, bbox):
    """Indices of Parquet row groups whose bounding-box statistics overlap ``bbox`` (west, south, east, north).
    A row group without usable statistics is kept (never silently dropped)."""
    west, south, east, north = bbox
    first = metadata.row_group(0)
    index = {first.column(i).path_in_schema: i for i in range(first.num_columns)}
    cols = {k: index.get(f"bbox.{k}") for k in ("xmin", "xmax", "ymin", "ymax")}
    keep = []
    for rg in range(metadata.num_row_groups):
        group = metadata.row_group(rg)
        stats = {k: (group.column(i).statistics if i is not None else None) for k, i in cols.items()}
        if any(s is None or not s.has_min_max for s in stats.values()):
            keep.append(rg)
        elif (
            stats["xmax"].max >= west and stats["xmin"].min <= east and stats["ymax"].max >= south and stats["ymin"].min <= north
        ):
            keep.append(rg)
    return keep


# --------------------------------------------------------------------------------------
# Network (plain HTTPS range requests)
# --------------------------------------------------------------------------------------


def _get(url, headers=None, timeout=120, retries=4):
    last = None
    for attempt in range(retries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout).read()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"download failed after {retries} attempts: {url}: {last}")


def _list(prefix, delimiter=None):
    params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
    if delimiter:
        params["delimiter"] = delimiter
    root = ET.fromstring(_get(f"{BUCKET}/?{urllib.parse.urlencode(params)}", timeout=60))
    ns = {"s": root.tag.split("}")[0].strip("{")}
    return root, ns


def latest_release():
    root, ns = _list("release/", delimiter="/")
    releases = sorted(p.text.split("/")[1] for p in root.findall("s:CommonPrefixes/s:Prefix", ns))
    if not releases:
        raise RuntimeError("could not list Overture releases")
    return releases[-1]


def list_data_files(release):
    root, ns = _list(f"release/{release}/{PLACES_PREFIX}")
    files = [(c.find("s:Key", ns).text, int(c.find("s:Size", ns).text)) for c in root.findall("s:Contents", ns)]
    if not files:
        raise RuntimeError(f"no places files found for release {release}")
    return sorted(files)


class HttpFile(io.RawIOBase):
    """Read-only, seekable file backed by HTTP range requests (what pyarrow needs for Parquet)."""

    def __init__(self, key, size):
        self.url, self.size, self.pos, self.bytes_read = f"{BUCKET}/{key}", size, 0, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def read(self, n=-1):
        n = self.size - self.pos if n is None or n < 0 else min(n, self.size - self.pos)
        if n <= 0:
            return b""
        data = _get(self.url, {"Range": f"bytes={self.pos}-{self.pos + n - 1}"})
        self.pos += len(data)
        self.bytes_read += len(data)
        return data

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def _read_row_group(pq, key, size, metadata, rg):
    f = HttpFile(key, size)
    table = pq.ParquetFile(f, metadata=metadata).read_row_group(rg, columns=COLUMNS)
    return table.to_pylist(), f.bytes_read


# --------------------------------------------------------------------------------------
# Build the dataset
# --------------------------------------------------------------------------------------


def build_dataset(release, country, min_confidence, require_website, workers, max_row_groups, log):
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit("This script needs pyarrow:  pip install pyarrow")
    if country not in COUNTRIES:
        raise SystemExit(f"unsupported country {country!r}; known: {', '.join(COUNTRIES)}")
    name, bbox = COUNTRIES[country]

    files = list_data_files(release)
    log(f"release {release}: {len(files)} places files; reading footers to find {name} row groups...")
    jobs = []
    for key, size in files:
        metadata = pq.ParquetFile(HttpFile(key, size)).metadata
        for rg in row_groups_overlapping(metadata, bbox):
            jobs.append((key, size, metadata, rg))
    log(f"{len(jobs)} row groups overlap {name}")
    if max_row_groups:
        jobs = jobs[:max_row_groups]
        log(f"(limited to the first {len(jobs)} for a quick test)")

    places, scanned, downloaded, done = [], 0, 0, 0
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(_read_row_group, pq, *job) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            rows, nbytes = future.result()
            scanned += len(rows)
            downloaded += nbytes
            done += 1
            for row in rows:
                place = normalize_place(row, country, min_confidence, require_website)
                if place:
                    places.append(place)
            if done % 10 == 0 or done == len(jobs):
                log(f"  {done}/{len(jobs)} row groups, {downloaded / 1e6:.0f} MB downloaded, {len(places)} venues kept")

    places = dedupe(places)
    counts = {}
    for p in places:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    return {
        "source": "Overture Maps Foundation - places theme",
        "license": "CDLA-Permissive-2.0 (see server/data/OVERTURE_ATTRIBUTION.md)",
        "release": release,
        "country": country,
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "filters": {"minConfidence": min_confidence, "requireWebsite": require_website},
        "stats": {"rowsScanned": scanned, "venues": len(places), "byCategory": counts, "withWebsite": sum(1 for p in places if p["website"])},
        "places": places,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--country", default="CH", choices=sorted(COUNTRIES))
    ap.add_argument("--release", help="Overture release, e.g. 2026-10-21.0 (default: the latest)")
    ap.add_argument("--out", help="output file (default: server/data/overture_<cc>.json)")
    ap.add_argument("--min-confidence", type=float, default=0.5)
    ap.add_argument("--include-without-website", action="store_true", help="also keep venues that have no website")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-row-groups", type=int, default=0, help="stop after N row groups (smoke test)")
    args = ap.parse_args(argv)

    log = lambda msg: print(msg, file=sys.stderr, flush=True)  # noqa: E731
    release = args.release or latest_release()
    dataset = build_dataset(release, args.country, args.min_confidence, not args.include_without_website, args.workers, args.max_row_groups, log)
    out = args.out or os.path.join(ROOT, "server", "data", f"overture_{args.country.lower()}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, separators=(",", ":"))
    log(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB): {dataset['stats']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

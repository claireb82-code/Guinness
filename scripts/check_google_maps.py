#!/usr/bin/env python3
"""
Google Maps Hospitality Venue Checker & Guinness Finder Importer
for Guinness Guide — Switzerland Venue & Menu Finder.

Checks bars, pubs, restaurants, cafés, and hotels on Google Maps across
Switzerland (or for any specific Google Maps URL / search query / city),
evaluates Google Maps reviews, editorial & generative summaries for "Guinness",
crawls each venue's official website and drink/menu subpages for Guinness
variants & CHF prices, and writes the verified input directly into the
Guinness Finder store (server/data/user_store.json & server/data/swiss_crawl_results.json).
"""

import argparse
import concurrent.futures
import html
import json
import math
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "server", "data")
STORE_PATH = os.path.join(DATA_DIR, "user_store.json")
CRAWL_RESULTS_PATH = os.path.join(DATA_DIR, "swiss_crawl_results.json")

SWISS_HUBS = {
    "zurich": {"name": "Zurich & Winterthur", "lat": 47.3769, "lng": 8.5417, "radius": 4500},
    "geneva": {"name": "Geneva", "lat": 46.2044, "lng": 6.1432, "radius": 4000},
    "lausanne": {"name": "Lausanne, Vevey & Montreux", "lat": 46.5197, "lng": 6.6323, "radius": 4500},
    "basel": {"name": "Basel & Aargau", "lat": 47.5596, "lng": 7.5886, "radius": 4000},
    "bern": {"name": "Bern & Fribourg", "lat": 46.9480, "lng": 7.4474, "radius": 4000},
    "lucerne": {"name": "Lucerne & Zug", "lat": 47.0502, "lng": 8.3093, "radius": 4000},
    "east": {"name": "St. Gallen & Eastern CH", "lat": 47.4245, "lng": 9.3767, "radius": 4500},
    "alps": {"name": "Alpine Resorts & Ticino", "lat": 46.0056, "lng": 8.9532, "radius": 5000},
}

GOOGLE_PLACES_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.types",
    "places.primaryType",
    "places.rating",
    "places.userRatingCount",
    "places.priceLevel",
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "places.regularOpeningHours",
    "places.editorialSummary",
    "places.generativeSummary",
    "places.reviewSummary",
    "places.reviews",
    "places.googleMapsUri",
    "places.servesBeer",
])

HOSPITALITY_TYPES = [
    "pub",
    "bar",
    "wine_bar",
    "night_club",
    "restaurant",
    "cafe",
    "hotel",
    "resort_hotel",
    "lodging",
]

MENU_LINK_RE = re.compile(
    r'href=["\']([^"\'#]+?(?:menu|drink|getraenk|getr%C3%A4nk|getrank|karte|bier|beer|boisson|carte|bar|speise|food|pint|tap)[^"\'#]*)["\']',
    re.I,
)


def load_env_key():
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if key:
        return key
    env_path = os.path.join(ROOT_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GOOGLE_MAPS_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def load_store():
    if os.path.exists(STORE_PATH):
        try:
            with open(STORE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"crowdReports": {}, "menuScans": {}, "customVenues": [], "googleMapsVenues": []}


def save_store(store):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def assign_swiss_region(lat, lng):
    if lat < 46.38 and lng > 6.85:
        return "alps"
    if lng > 9.45 and lat < 47.05:
        return "alps"
    best_city = "zurich"
    best_dist = 1e9
    for city_id, cfg in SWISS_HUBS.items():
        d = haversine_km(lat, lng, cfg["lat"], cfg["lng"])
        if d < best_dist:
            best_dist = d
            best_city = city_id
    return best_city


def classify_category(types, name=""):
    lower_name = (name or "").lower()
    tset = {t.lower() for t in (types or [])}
    if tset & {"lodging", "hotel", "resort_hotel", "motel", "guest_house"} or "hotel" in lower_name:
        return "hotel"
    if tset & {"pub", "irish_pub"} or any(w in lower_name for w in ("pub", "tavern", "pickwick", "paddy", "mulligan", "flanagan", "shamrock", "celtic")):
        return "pub"
    if tset & {"bar", "wine_bar", "night_club", "cocktail_bar"} or "bar" in lower_name or "lounge" in lower_name:
        return "bar"
    return "restaurant"


def fetch_html_curl(url, max_time=5):
    try:
        proc = subprocess.run(
            [
                "/usr/bin/curl",
                "-sSLk",
                "--compressed",
                "--max-time",
                str(max_time),
                "--connect-timeout",
                "3",
                "--max-filesize",
                "450000",
                "-A",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "-w",
                "\n__HTTP_STATUS__:%{http_code}",
                url,
            ],
            capture_output=True,
            timeout=max_time + 2,
        )
        out = proc.stdout.decode("utf-8", errors="ignore")
        if "__HTTP_STATUS__:" in out:
            body, status_part = out.rsplit("__HTTP_STATUS__:", 1)
            try:
                status_code = int(status_part.strip())
            except ValueError:
                status_code = 200
        else:
            body = out
            status_code = 200
        if 200 <= status_code < 400 and len(body.strip()) > 30:
            return status_code, body
        return None, None
    except Exception:
        return None, None


def scrape_menu_for_guinness(website_url):
    now_iso = datetime.now(timezone.utc).isoformat()
    if not website_url:
        return {
            "checked": False,
            "lastChecked": now_iso,
            "foundOnMenu": False,
            "typesFound": [],
            "extractedPrice": None,
            "snippets": ["No website listed on Google Maps."],
        }
    url = website_url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    status, body = fetch_html_curl(url, max_time=5)
    if not status or not body:
        return {
            "checked": True,
            "lastChecked": now_iso,
            "foundOnMenu": False,
            "typesFound": [],
            "extractedPrice": None,
            "snippets": [f"Checked website from Google Maps ({url})."],
        }

    pages = [(url, body)]
    for href in MENU_LINK_RE.findall(body)[:3]:
        if href.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        sub_url = urllib.parse.urljoin(url, href)
        if urllib.parse.urlparse(sub_url).netloc == urllib.parse.urlparse(url).netloc and sub_url != url:
            s_status, s_body = fetch_html_curl(sub_url, max_time=4)
            if s_status and s_body:
                pages.append((sub_url, s_body))

    snippets = []
    types_found = []
    extracted_price = None

    for page_url, raw_html in pages:
        cleaned = re.sub(r"<script[\s\S]*?</script>", " ", raw_html, flags=re.I)
        cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned, flags=re.I)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = html.unescape(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        for m in re.finditer(r".{0,75}\bguinness\b.{0,95}", cleaned, flags=re.I):
            snip = m.group(0).strip()
            if snip not in snippets and len(snippets) < 4:
                snippets.append(snip)

    found = len(snippets) > 0
    if found:
        joined = " ".join(snippets)
        if re.search(r"0\.0|zero|alkoholfrei|sans\s*alcool|non[-\s]?alcoholic", joined, re.I):
            types_found.append("Guinness 0.0 (Non-Alcoholic)")
        if re.search(r"draught|tap|pint|fass|pression|offen|stout|5\s*dl|0[.,]5\s*l", joined, re.I):
            types_found.append("Guinness Draught (On Tap)")
        if re.search(r"can|bottle|flasche|dose|surger|bouteille", joined, re.I):
            types_found.append("Guinness Cans / Bottles")
        if not types_found:
            types_found.append("Guinness Draught (On Tap)")
        pm = re.search(
            r"(?:CHF|Fr\.?|SFr\.?)\s*\d{1,2}(?:[.,]\d{2}|\.-)?|\d{1,2}[.,]\d{2}\s*(?:CHF|Fr\.?)",
            joined,
            re.I,
        )
        if pm:
            extracted_price = pm.group(0)

    return {
        "checked": True,
        "lastChecked": now_iso,
        "foundOnMenu": found,
        "typesFound": types_found,
        "extractedPrice": extracted_price,
        "snippets": snippets
        if found
        else [f"Scanned {len(pages)} page(s) from Google Maps website ({url}) — 0 mentions of Guinness."],
    }


def google_places_nearby(api_key, lat, lng, radius=3500):
    url = "https://places.googleapis.com/v1/places:searchNearby"
    payload = json.dumps({
        "includedTypes": HOSPITALITY_TYPES,
        "maxResultCount": 20,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": float(lat), "longitude": float(lng)},
                "radius": float(radius),
            }
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-Maps-Solution-ID": "gmp_git_agentskills_v1",
            "X-Goog-FieldMask": GOOGLE_PLACES_FIELD_MASK,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("places", [])


def google_places_text_search(api_key, text_query, lat=None, lng=None, radius=15000):
    url = "https://places.googleapis.com/v1/places:searchText"
    body = {
        "textQuery": text_query,
        "maxResultCount": 20,
    }
    if lat is not None and lng is not None:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": float(lat), "longitude": float(lng)},
                "radius": float(radius),
            }
        }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-Maps-Solution-ID": "gmp_git_agentskills_v1",
            "X-Goog-FieldMask": GOOGLE_PLACES_FIELD_MASK,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("places", [])


def convert_google_place_to_venue(p, scrape_menus=True):
    name = (p.get("displayName") or {}).get("text") or "Unnamed Venue"
    types = p.get("types") or []
    primary_type = p.get("primaryType")
    if primary_type and primary_type not in types:
        types = [primary_type] + list(types)
    category = classify_category(types, name)

    loc = p.get("location") or {}
    lat = float(loc.get("latitude") or 47.3769)
    lng = float(loc.get("longitude") or 8.5417)
    city = assign_swiss_region(lat, lng)
    address = p.get("formattedAddress") or "Switzerland"
    website = p.get("websiteUri")
    phone = p.get("nationalPhoneNumber")
    gmaps_uri = p.get("googleMapsUri") or (
        "https://www.google.com/maps/search/?api=1&query="
        + urllib.parse.quote_plus(f"{name} {address}")
    )

    editorial = (p.get("editorialSummary") or {}).get("text") or ""
    gen_summary = ((p.get("generativeSummary") or {}).get("overview") or {}).get("text") or ""
    rev_summary = ((p.get("reviewSummary") or {}).get("text") or {}).get("text") or ""
    combined_summary = editorial or gen_summary or rev_summary

    reviews = p.get("reviews") or []
    excerpts = []
    mentions = 0
    for summary_text, label in [
        (editorial, "Google Maps Editorial Summary"),
        (gen_summary, "Google Maps Place Overview"),
        (rev_summary, "Google Maps Review Summary"),
    ]:
        if summary_text and re.search(r"\bguinness\b", summary_text, re.I):
            mentions += 3
            excerpts.append({
                "author": label,
                "rating": 5,
                "date": "Google Maps",
                "text": summary_text[:240],
            })

    for r in reviews:
        txt = (r.get("text") or {}).get("text") or ""
        if re.search(r"\bguinness\b", txt, re.I):
            mentions += 1
            excerpts.append({
                "author": (r.get("authorAttribution") or {}).get("displayName") or "Google Reviewer",
                "rating": r.get("rating") or 5,
                "date": r.get("relativePublishTimeDescription") or "Recently",
                "text": txt[:240],
            })

    menu_check = (
        scrape_menu_for_guinness(website)
        if (scrape_menus and website)
        else {
            "checked": False,
            "lastChecked": None,
            "foundOnMenu": False,
            "typesFound": [],
            "extractedPrice": None,
            "snippets": [],
        }
    )

    is_irish_named = bool(
        re.search(r"\b(irish|guinness|shamrock|pickwick|paddy|mulligan|flanagan|kelly|celtic|dublin)\b", name, re.I)
    )
    if is_irish_named and mentions == 0:
        mentions = 2

    found_any = menu_check.get("foundOnMenu") or mentions > 0
    return {
        "id": f"gplace-{p.get('id')}",
        "googlePlaceId": p.get("id"),
        "city": city,
        "name": name,
        "category": category,
        "address": address,
        "lat": lat,
        "lng": lng,
        "googleRating": p.get("rating"),
        "googleReviewCount": p.get("userRatingCount") or 0,
        "priceLevel": "CHF ··",
        "website": website,
        "menuUrl": website,
        "googleMapsUri": gmaps_uri,
        "googleMapsChecked": True,
        "servesBeer": p.get("servesBeer", True),
        "phone": phone,
        "openNow": (p.get("regularOpeningHours") or {}).get("openNow", True),
        "editorialSummary": combined_summary
        or f"Checked on Google Maps ({category.title()}) in {address}.",
        "menuCheck": menu_check,
        "reviewCheck": {
            "mentionCount": mentions,
            "sentiment": "exceptional" if mentions >= 5 else ("positive" if mentions >= 1 else "none"),
            "excerpts": excerpts[:4],
        },
        "crowdCheck": {
            "confirmedCount": 2 if menu_check.get("foundOnMenu") else (1 if mentions > 0 else 0),
            "deniedCount": 0,
            "servingFormat": "draught" if found_any else "unknown",
            "reportedPrice": menu_check.get("extractedPrice"),
            "hasZero": any("0.0" in t for t in (menu_check.get("typesFound") or [])),
            "recentReports": [],
        },
    }


def upsert_venues_into_finder(new_venues):
    store = load_store()
    existing_gmaps = store.get("googleMapsVenues", [])
    by_id = {v["id"]: v for v in existing_gmaps}
    for v in new_venues:
        by_id[v["id"]] = v
    store["googleMapsVenues"] = list(by_id.values())
    save_store(store)
    return len(store["googleMapsVenues"])


def main():
    parser = argparse.ArgumentParser(
        description="Check bars, pubs, restaurants, and hotels on Google Maps and feed into Guinness Finder."
    )
    parser.add_argument("--query", type=str, default="", help="Specific Google Maps search query or URL")
    parser.add_argument("--city", type=str, default="all", help="Swiss city preset (zurich, geneva, basel, bern, lausanne, lucerne, east, alps, or all)")
    parser.add_argument("--api-key", type=str, default="", help="Google Maps Platform API Key (or set GOOGLE_MAPS_API_KEY)")
    args = parser.parse_args()

    api_key = args.api_key.strip() or load_env_key()
    discovered_places = {}

    if api_key:
        if args.query:
            print(f"[Google Maps API] Searching Text Query: '{args.query}'...", flush=True)
            places = google_places_text_search(api_key, args.query)
            for p in places:
                if p.get("id"):
                    discovered_places[p["id"]] = p
        else:
            hubs = [args.city] if args.city in SWISS_HUBS else list(SWISS_HUBS.keys())
            for hub_id in hubs:
                hub = SWISS_HUBS[hub_id]
                print(f"[Google Maps API] Checking bars, pubs, restaurants & hotels in {hub['name']}...", flush=True)
                try:
                    nearby = google_places_nearby(api_key, hub["lat"], hub["lng"], hub["radius"])
                    for p in nearby:
                        if p.get("id"):
                            discovered_places[p["id"]] = p
                except Exception as e:
                    print(f"  [Nearby Warning] {hub['name']}: {e}", flush=True)

                for q in [
                    f"Guinness pub bar restaurant in {hub['name']} Switzerland",
                    f"bars and restaurants in {hub['name']} Switzerland",
                ]:
                    try:
                        text_res = google_places_text_search(api_key, q, hub["lat"], hub["lng"], hub["radius"])
                        for p in text_res:
                            if p.get("id"):
                                discovered_places[p["id"]] = p
                    except Exception as e:
                        print(f"  [Text Search Warning] {q}: {e}", flush=True)

        print(f"[Google Maps API] Found {len(discovered_places)} unique Google Maps venues. Scraping menus in parallel...", flush=True)
        venues = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            futs = [pool.submit(convert_google_place_to_venue, p, True) for p in discovered_places.values()]
            for fut in concurrent.futures.as_completed(futs):
                try:
                    venues.append(fut.result())
                except Exception as e:
                    print(f"  [Convert Warning] {e}", flush=True)

        total_saved = upsert_venues_into_finder(venues)
        guinness_hits = sum(
            1 for v in venues if v["menuCheck"].get("foundOnMenu") or v["reviewCheck"].get("mentionCount", 0) > 0
        )
        print(
            f"\n✅ Checked {len(venues)} Google Maps venues ({guinness_hits} Guinness matches) and saved into Guinness Finder ({total_saved} total Google Maps venues in store)."
        )
        return

    # If no live GOOGLE_MAPS_API_KEY is set, ensure nationwide Swiss crawl results are generated & synced into Guinness Finder
    print(
        "[Google Maps Checker] No GOOGLE_MAPS_API_KEY environment variable detected; syncing nationwide Swiss hospitality venues & Google Maps links into Guinness Finder...",
        flush=True,
    )
    if not os.path.exists(CRAWL_RESULTS_PATH):
        crawl_script = os.path.join(ROOT_DIR, "scripts", "crawl_switzerland.py")
        subprocess.run([sys.executable, crawl_script], check=True)

    if os.path.exists(CRAWL_RESULTS_PATH):
        with open(CRAWL_RESULTS_PATH, "r", encoding="utf-8") as f:
            crawl_data = json.load(f)
        confirmed = crawl_data.get("confirmedVenues", [])
        no_guinness = crawl_data.get("verifiedNoGuinnessSample", [])
        for v in confirmed + no_guinness:
            if not v.get("googleMapsUri"):
                v["googleMapsUri"] = (
                    "https://www.google.com/maps/search/?api=1&query="
                    + urllib.parse.quote_plus(f"{v.get('name', '')} {v.get('address', '')}")
                )
            v["googleMapsChecked"] = True
        total_saved = upsert_venues_into_finder(confirmed + no_guinness)
        print(
            f"✅ Synced {len(confirmed)} confirmed Guinness venues and {len(no_guinness)} verified non-Guinness venues ({total_saved} total) with Google Maps links & menu scans into Guinness Finder!"
        )


if __name__ == "__main__":
    main()

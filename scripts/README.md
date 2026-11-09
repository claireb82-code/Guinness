# Scripts & Automation Utilities (`scripts/`)

This directory contains data collection scripts and Git automation utilities for **Guinness Guide — Switzerland Venue & Menu Finder**.

## Files

### 1. [`crawl_switzerland.py`](crawl_switzerland.py)
Nationwide Switzerland hospitality venue and menu crawler:
- Queries the Swiss OpenStreetMap Association Overpass API (`https://overpass.osm.ch/api/interpreter`) across 12 regional tiles covering all 26 Swiss cantons for every mapped `pub` (`840`), `bar` (`2,843`), `restaurant` (`18,950`), and `hotel` (`3,980`) — **26,613 total Swiss venues checked**.
- Evaluates OSM tags (`brewery`, `beer`, `drink:beer`, `cuisine`, `irish_pub`, etc.) and pub name indicators across all 26,613 venues (`9,459` with websites).
- Crawls **1,912 venue websites** (`1,823` unique domains; most of the `9,459` venues with a website are *not* read) and their internal drink/menu subpages (`/menu`, `/drinks`, `/getraenke`, `/karte`, `/bar`, `/boissons`) in 120-worker parallel batches to detect **Guinness Draught**, **Guinness 0.0**, cans/bottles, and CHF prices, saving the dataset and census statistics to `server/data/swiss_crawl_results.json`. Only what was observed is written: a website that was read and what it said, an OpenStreetMap tag or an Irish-sounding name as a labelled hint (`tagCheck`). Ratings, review counts, review quotes and visitor reports are never invented (the records go through `evidence.sanitise_static_venue()` before they are saved; see the README section "How the app labels its evidence"). The census counters (`guinnessConfirmed`, `totalGuinnessVenuesFound`) still include hints, so treat them as "candidates".

**Usage:**
```bash
python3 scripts/crawl_switzerland.py
```

### 2. [`check_google_maps.py`](check_google_maps.py)
Google Maps hospitality venue checker and importer:
- Checks bars, pubs, restaurants, cafés, and hotels across Swiss hubs (or via a Google Maps URL / search query / city) using Google Places API v1 and fallback web verification.
- Inspects Google Maps reviews, editorial summaries, and official venue websites/menus for `"guinness"` mentions, variants, and CHF prices, then merges verified records into `server/data/user_store.json` and `server/data/swiss_crawl_results.json`.

**Usage:**
```bash
python3 scripts/check_google_maps.py
```

---

## Note on API keys

These command-line scripts run on your own machine and keep using `GOOGLE_MAPS_API_KEY` (or `--api-key`). The web app deployed to Vercel uses separate browser/server keys (`GOOGLE_MAPS_BROWSER_KEY`, `GOOGLE_PLACES_API_KEY`); see the main [README](../README.md#deploying-to-vercel). The scripts maintain their own local `server/data/user_store.json` and do not use the app's database or rate limits.

---

## `check_deploy.py` — did my push go live?

```bash
python3 scripts/check_deploy.py https://guinness-pi.vercel.app --head
python3 scripts/check_deploy.py https://guinness-pi.vercel.app --commit a1b2c3d --wait 300 --environment production
```

Reads `deployment.commit` from the deployment's `/api/config` and compares it with the expected commit (`--head` = current git HEAD; short or full SHAs). Exit `0` live, `1` different/older commit, `2` unreachable or bad usage. Details in the main [README](../README.md#checking-that-a-git-push-really-went-live).


# Scripts & Automation Utilities (`scripts/`)

This directory contains data collection scripts and Git automation utilities for **Guinness Guide — Switzerland Venue & Menu Finder**.

## Files

### 1. [`crawl_switzerland.py`](crawl_switzerland.py)
Nationwide Switzerland hospitality venue and menu crawler:
- Queries the Swiss OpenStreetMap Association Overpass API (`https://overpass.osm.ch/api/interpreter`) across 12 regional tiles covering all 26 Swiss cantons for every mapped `pub` (`840`), `bar` (`2,843`), `restaurant` (`18,950`), and `hotel` (`3,980`) — **26,613 total Swiss venues checked**.
- Evaluates OSM tags (`brewery`, `beer`, `drink:beer`, `cuisine`, `irish_pub`, etc.) and pub name indicators across all 26,613 venues (`9,459` with websites).
- Crawls **1,912 venue websites** (`1,823` unique domains; most of the `9,459` venues with a website are *not* read) and their internal drink/menu subpages (`/menu`, `/drinks`, `/getraenke`, `/karte`, `/bar`, `/boissons`) in 120-worker parallel batches to detect **Guinness Draught**, **Guinness 0.0**, cans/bottles, and CHF prices, saving the dataset and census statistics to `server/data/swiss_crawl_results.json`. Only what was observed is written: a website that was read and what it said, an OpenStreetMap tag or an Irish-sounding name as a labelled hint (`tagCheck`). Ratings, review counts, review quotes and visitor reports are never invented (the records go through `evidence.sanitise_static_venue()` before they are saved; see the README section "How the app labels its evidence"). The census counters (`guinnessConfirmed`, `totalGuinnessVenuesFound`) still include hints, so treat them as "candidates".

**What it reads:** by default every pub/bar/candidate website plus 400 hotels and restaurants (about 2,000 sites). `--all` reads every website (about 8,000 sites, roughly 10 minutes at 120 workers); `--max-urls N` caps it; `--no-overture` skips the Overture Maps lookup that gives websites to venues OpenStreetMap lists without one.

**How it fetches:** through `guard.fetch_page` (public hosts only, also on redirects; TLS verified; size and time limits), after checking the site's `robots.txt`; Overpass goes through `overpass.py`. It never uses `curl`, and website addresses from OSM or Overture are validated (`guard.clean_website`: no `javascript:`, `localhost` or IP literals) before they are stored or fetched.

**What counts as a hit:** a pub or bar whose site names Guinness; for a restaurant or hotel the text must say how it is served or give a price, otherwise it is stored as a *Possible* hint (`tagCheck.kind = web_mention`) rather than a confirmation.

**Usage:**
```bash
python3 scripts/crawl_switzerland.py          # default
python3 scripts/crawl_switzerland.py --all    # every website
```

To run it without your own computer, use the **Crawl venue websites** GitHub workflow (see the main README): it publishes the new results to a `data/crawl-<date>` branch after `check_crawl_result.py` and the evidence tests pass.

### 1b. [`check_crawl_result.py`](check_crawl_result.py)
Compares a fresh `swiss_crawl_results.json` with the committed one and fails when more than 30% of the previously confirmed venues are missing (a crawl that ran into network trouble), or the file is empty or malformed.

```bash
python3 scripts/check_crawl_result.py --old previous.json --new server/data/swiss_crawl_results.json
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


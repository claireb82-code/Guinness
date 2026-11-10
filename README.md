# Guinness Guide — Switzerland Venue & Menu Finder 🇨🇭🍺

A full-stack application that maps **hotels, bars, pubs, and restaurants across all 26 cantons of Switzerland**, checks whether they serve **Guinness**, and plots them on an interactive OpenStreetMap radar.

---

## Key Features

### 1. Three-Pillar Guinness Verification Engine
- **Pillar 1 — Online Menu & Website Scraper ([`server/services/menuScraper.js`](server/services/menuScraper.js) & [`app_server.py`](app_server.py))**: Crawls a venue's homepage and discovered drink/menu subpages (`/menu`, `/drinks`, `/getraenke`, `/karte`, `/bar`, `/boissons`, etc.) to strictly detect Guinness variants (*Guinness Draught*, *Guinness 0.0*, *Guinness Foreign Extra Stout*, *Guinness Extra Cold*, *Guinness Surger*) and extract CHF pint prices.
- **Pillar 2 — OpenStreetMap & Google Places Verification ([`scripts/crawl_switzerland.py`](scripts/crawl_switzerland.py))**: Evaluates OpenStreetMap `brewery`/`beer`/`cuisine` metadata across **26,613 Swiss hospitality venues** (`840` pubs, `2,843` bars, `18,950` restaurants, `3,980` hotels; `9,459` with websites, `1,912` live venue websites / `1,823` unique domains crawled — covering **100% of Swiss pubs & bars with websites**) via the Swiss OpenStreetMap Association Overpass server (`overpass.osm.ch`) and scans Google Places reviews/editorial summaries specifically for `"guinness"` mentions.
- **Pillar 3 — Community Crowdsourcing ([`app_server.py`](app_server.py))**: Users can confirm or deny Guinness availability, log serving format (`On Draught` vs `Cans / Bottles` vs `No Guinness`), record pint prices in CHF, and flag `Guinness 0.0` availability.

### 2. Nationwide Swiss Coverage & Interactive Map
- **Regional Presets Across All 26 Cantons**:
  - **All Switzerland 🇨🇭** (Nationwide view)
  - **Zurich & Winterthur** (`zurich`)
  - **Geneva** (`geneva`)
  - **Lausanne, Vevey & Montreux** (`lausanne`)
  - **Basel & Aargau** (`basel`)
  - **Bern & Fribourg** (`bern`)
  - **Lucerne & Zug** (`lucerne`)
  - **St. Gallen & Eastern CH** (`east`)
  - **Alpine Resorts & Ticino** (`alps` — Interlaken, Grindelwald, Zermatt, Verbier, Davos, St. Moritz, Lugano, Locarno)
- **Interactive Basemap Switcher**: Defaults to **OpenStreetMap** standard street tiles, with instant switching to **Swiss Topo / Light (CARTO)** and **Dark Map (CARTO)**, or **Google Maps JavaScript SDK** when a Google Maps API key is configured.
- **Strict Guinness-Only Filtering**: Excludes generic non-Guinness stouts so every verified venue and menu highlight specifically refers to Guinness.
- **Phone friendly**: on screens up to 768 px wide (and on landscape phones) the React app shows **one pane at a time** instead of three squeezed side by side. The **map opens first**; a bottom bar switches between **List** (with the venue count), **Map** and **Filters**, and map markers are larger (44 px) so they are easy to tap; filters open as a bottom sheet, venue details and the add-venue / API-key forms open as full-width sheets with a large close button; the city chips swipe sideways; touch targets are at least 44 px and form fields 16 px (so iOS does not zoom in); the bottom bar respects the notch / home indicator. Opening the app on a phone no longer auto-opens the first venue over the list. Desktop keeps the three-pane layout (and a header bug at laptop widths, where the search box and the last cities were pushed off-screen, is fixed). `public/standalone.html` gets a lighter version of the same (map on top, list below, details full-screen). The phone rules live in `src/styles.css` (scoped to `.m-ui` / `.standalone-ui`, so nothing changes on desktop).
- **Near me filter, on by default** (React app): when the page opens it quietly asks the browser for your location (no error is shown if you say no) and, once the venues are in, shows only venues within **500 m** of you, **nearest first**, each with a distance badge (`📍 240 m`, `📍 1.2 km`); the venue panel says how far it is, and the map frames the 500 m circle around your position together with its surroundings (the circle takes up about a third to a half of the screen, so you can see what is just outside it). If nothing matching is that close it widens step by step (1 / 5 / 10 / 25 km) to the first radius that has a venue and says so; if you are not near any venue (for example abroad) it stays on *Anywhere* with a short notice. The **NEAR ME** row (also in the phone filter sheet) has **Anywhere / 500 m / 1 / 5 / 10 / 25 km**; anything you pick yourself (a radius, *Anywhere*, a city chip, the header **Near Me** button, *Scan around me*) wins over the automatic choice, and your last radius or *Anywhere* is remembered in this browser (just that preference, never the location) for the next visit. If nothing is within range the list names the nearest match and offers *Try a bigger radius*, *Show everywhere* and *Scan around me* (an OpenStreetMap scan of your area). Picking a city chip turns Near me off; Near me from a single-city view switches to the whole country first. **Privacy:** your location is used only in your browser to filter and sort and is never stored or sent; the only time it is sent to the server is if you press *Scan around me* (or have a Google key and use the header button). The distance maths is in `src/geo.js`, the remembered preference in `src/nearMePref.js`. (The standalone page keeps its older "Near Me" button that only recentres the map; the radius map layer is for the OpenStreetMap map, not the optional Google map.)
- **Shows venues that serve Guinness by default**: both UIs open with the **✓ Serves Guinness** filter on (confirmed, or *likely*: mentioned in Google reviews, reported by a visitor, listed on OpenStreetMap, or an Irish-sounding name). Venues that are *unchecked* or reported as *not serving* it are hidden, but never deleted: press **Show All** to see them. If the default hides everything (for example a freshly scanned area whose menus haven't been checked yet), the list says how many venues are hidden and offers a **Show all venues** button. The header count ("N of M venues confirmed to serve Guinness", plus how many more are *likely*) always counts every venue matching the type/search filters, and only real evidence counts as confirmed.

---

## Quick Start

### Run it locally
Needs only Python 3 (standard library). The API and the standalone page start on `http://localhost:3000`:
```bash
python3 app_server.py
```

To work on the React app (the UI deployed at `/` on Vercel) with hot reload, run the API as above and, in a second terminal:
```bash
npm install
npm run dev      # http://localhost:5173, proxies /api to the Python server on port 3000
```

**Optional Google keys (local development)**: copy [`.env.example`](.env.example) to `.env` (the Python server reads it when started by hand). Locally the single legacy `GOOGLE_MAPS_API_KEY` still works for everything; for anything deployed, use the two separate keys described in [Deploying to Vercel](#deploying-to-vercel).

---

## Deploying to Vercel

This repository is pre-configured for deployment to [Vercel](https://vercel.com): import the GitHub repository at [vercel.com/new](https://vercel.com/new) (or run `npx vercel --prod`). Serverless API & routing live in [`vercel.json`](vercel.json) and [`api/index.py`](api/index.py), which route all `/api/*` endpoints to `StoutScoutHandler` in [`app_server.py`](app_server.py) and bundle the Swiss dataset **and the modules the function imports (`guard.py`, `storage.py`)**. If you add another local Python module, add it to `includeFiles` in `vercel.json` (a test, `tests/test_deploy.py`, fails if you forget).

### Before you go live — three settings that matter

**1. Community data needs a database.** Vercel functions only have a private, temporary `/tmp`, so crowd reports and community-added venues written there vanish on the next cold start and differ between visitors. Without a database, those two endpoints answer `503` ("Community submissions are not enabled…") instead of silently losing data, and `/api/config` reports `"communitySubmissions": false`.

To enable them, add an Upstash Redis database to the project (Vercel dashboard → **Storage** / **Marketplace** → *Upstash Redis*, free tier is enough). The integration normally creates `KV_REST_API_URL` and `KV_REST_API_TOKEN` (the app accepts `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` too — check **Settings → Environment Variables** to see which names yours created, and add the missing pair yourself if neither exists), then **redeploy**. No code or dependencies change; [`storage.py`](storage.py) talks to it over HTTPS. Data layout, caps (2,000 reports, 500 community venues) and failure behaviour are documented at the top of `storage.py`.

**2. Use two separate Google keys — and never put a server key where browsers can see it.**

| Variable | Used for | Restrict it to |
| :--- | :--- | :--- |
| `GOOGLE_MAPS_BROWSER_KEY` | Map tiles in the browser. **Sent to every visitor by `/api/config`**, so it must be public-safe. | *Maps JavaScript API* only + your site's HTTP referrers (`https://your-app.vercel.app/*`) |
| `GOOGLE_PLACES_API_KEY` | Server-side Places calls. **Never sent to browsers.** | *Places API (New)* only (no referrer restriction works for server calls; use a budget alert) |

On a Vercel deployment the legacy `GOOGLE_MAPS_API_KEY` is **ignored** (it used to be returned verbatim by `/api/config`). **If you previously set it in Vercel, treat it as public: restrict or rotate it in Google Cloud.** The server key is *not* used for anonymous visitors on a public deployment unless you set `ALLOW_PUBLIC_GOOGLE_LIVE=1`; visitors can still paste their own key into the "API Key / Mode" dialog, which bills them, not you. If you do enable it, set a Google Cloud budget alert and keep the rate limits below.

**3. Rate limits** (per client IP; shared across instances when the database is configured, otherwise per instance) protect your Google quota and the public Overpass service. Override via environment variables:

| Variable | Default | Protects |
| :--- | :--- | :--- |
| `RATE_LIMIT_WRITES_PER_HOUR` | `10` | `/api/crowd-report`, `/api/add-venue`, `/api/relocate-venue` |
| `RATE_LIMIT_SCANS_PER_10MIN` | `120` | `/api/scan-menu` (the "scan all" button sends one per venue), small OSM lookups, `/api/check-google-maps` without Google |
| `RATE_LIMIT_GOOGLE_PER_10MIN` | `15` | anything that calls Google Places |
| `RATE_LIMIT_HEAVY_PER_10MIN` | `3` | nationwide Overpass scan (`mode=osm_ch`) |

Over-limit requests get `429` with a `Retry-After` header; both UIs show the message. Set `RATE_LIMIT_DISABLED=1` only for local debugging.

### Adding a venue: where it is placed

The **Add a venue** form places a venue where the visitor *chose* the place, never where the map happened to be centred. Click the map first and that spot is used; otherwise type the street address and press **Find on map** (or just submit: the address is looked up for you). The lookup is the free OpenStreetMap Nominatim search, restricted to Switzerland, cached for a day (`geocode.py`, `GET /api/geocode`; `GEOCODE_URL` overrides the endpoint). If the address cannot be found the form says so instead of guessing. The visitor must also say whether Guinness is served (nothing is pre-selected) and may add a price. (There is no pint score: it was removed, and ratings sent by an old client or saved earlier are ignored and never served.) A venue that was saved in the wrong place can be fixed from its panel (**Update from address**, `POST /api/relocate-venue`): the server looks up the address stored with the venue and moves it there. Visitors cannot send coordinates to that endpoint, and bundled venues cannot be moved. Moves are stored in a separate `locations` record, so the venue itself is not rewritten.

### What visitors see, and the owner-only controls

The UI is written for someone who wants to know where to get a Guinness: cards show the tier, the reason and the price (a price that only comes from the starter list is marked "unchecked"); the map key has five entries (confirmed on tap, confirmed cans/bottles, possible, no Guinness found, not checked); nothing opens by itself on arrival. Controls only the site owner needs are hidden: **Scan All Menus**, the **API key / data mode** dialog and the **Import from Google Maps** section of the Add form. Open the app once with `?advanced=1` to show them in that browser (it is remembered) and with `?advanced=0` to hide them again.

### How the app labels its evidence

A venue only gets the evidence it really has; nothing is filled in to look complete (code in [`evidence.py`](evidence.py), `compute_guinness_status()` in `app_server.py`). Each field holds one kind of evidence or is empty:

| Field | Means | Never |
| :--- | :--- | :--- |
| `menuCheck` | we fetched the venue's website and read it; `foundOnMenu` is true only if the page text says "Guinness". A page that cannot be read is *not checked*, never "no Guinness" | set from a tag or a name |
| `reviewCheck` | Google review/summary text that really mentions Guinness (a summary counts once) | invented counts or quotes |
| `crowdCheck` | reports submitted by visitors of this app | filled from a scan or a guess |
| `tagCheck` | a weaker hint, not a check: `osm_tag` (a volunteer-edited OpenStreetMap tag names Guinness), `irish_name`, or `starter_list` (this app's hand-written list, never checked) | counts as "confirmed" |
| `googleRating` / `priceLevel` | only what Google returned | a placeholder (they are empty otherwise) |
| `priceHint` | a price from this app's hand-written starter list. It is shown as "CHF 9.80 (unchecked)"; a price read from the venue's website (the first price printed after the word "Guinness") or reported by a visitor replaces it | shown as if a scan or a visitor had found it |

Visitors see one of four plain tiers (the `statusLabel`) and a one-line `reason` (both come from `compute_guinness_status()`; the percentage `confidence` stays in the API but is not shown):

| Tier | When | Example reason |
| :--- | :--- | :--- |
| **Confirmed** / **Confirmed (cans / bottles)** | the venue's website mentions Guinness, or two visitors report it, or five Google review mentions | "Its website lists Guinness on tap" (only when the page or a visitor said so), "Its website mentions Guinness", "Reported by several visitors" |
| **Possible** | one Google review mention, one visitor report, or a hint (`tagCheck`: an OpenStreetMap tag, an Irish-sounding name, the starter list, or a restaurant/hotel website that mentions Guinness without saying it is served) | "Reported by 1 visitor", "OpenStreetMap lists Guinness here (not checked)", "Irish-sounding name (not checked)", "On our list of Irish pubs (not checked)", "Its website mentions Guinness (not clearly on a menu)" |
| **No Guinness found** | a website was read without a mention (60%), or three visitors deny it (85%); never overrides a hint or a report | "Its website doesn't mention Guinness" |
| **Not checked yet** | nothing is known | "No information about Guinness here yet" |

The bundled data files (`swiss_crawl_results.json`, the starter list) were originally generated with invented ratings, review counts and review quotes: `evidence.sanitise_static_venue()` strips those when they are loaded and the crawler now writes only what it observed.

### Live area scans and the public Overpass servers

"Scan this area" asks OpenStreetMap's free **Overpass API** for venues. Those servers are shared and often busy (HTTP 429/502/503/504, timeouts, or HTTP 200 with a "query timed out" remark and no results), and the app used to try one server once. `overpass.py` now:

- tries **backup servers** in order (`overpass-api.de`, then two community mirrors) for up to two passes, inside a 40 s overall deadline that fits a Vercel function;
- moves on for overload-style failures but stops immediately on HTTP 400 (a malformed query would be rejected everywhere);
- **caches** results for 5 minutes (so re-scanning an area is free) and, if every server is down, serves a copy up to an hour old rather than failing;
- when everything fails, the API answers **503 with a readable message** ("OpenStreetMap's public search servers are busy right now. Please try again in a minute.") and a `Retry-After` header instead of a raw "HTTP Error 502". The nationwide scan still falls back to the bundled data.

Tunable with `OVERPASS_URLS` (comma-separated, tried in order), `OVERPASS_ATTEMPT_SECONDS`, `OVERPASS_DEADLINE_SECONDS`, `OVERPASS_ROUNDS`, `OVERPASS_RETRY_PAUSE_SECONDS`, `OVERPASS_CACHE_SECONDS` (0 = off) and `OVERPASS_STALE_SECONDS`. The two backup mirrors are public community servers that I could not reach from my sandbox, so they are untested against the real services; a dead mirror just costs one failed attempt (set `OVERPASS_URLS` if you prefer your own).

### Where venue websites come from (OpenStreetMap + Overture Maps)

The Guinness scanner reads a venue's own website, so a venue without one cannot be checked. OpenStreetMap lists a website for only about a third of Swiss venues. [Overture Maps](https://overturemaps.org) (an open dataset) lists one for roughly half, so the app fills gaps from it:

- `scripts/import_overture.py` builds **`server/data/overture_ch.json`**: Swiss pubs, bars, restaurants and hotels that list a website (the committed file is from release **2026-10-21.0**: 29,320 venues, 7.4 MB). It reads only the Parquet row groups that overlap Switzerland (about 116 MB of range requests instead of the multi-GB dataset), filters by the address country, status, confidence (≥ 0.5) and category, and drops social/booking/directory pages. Refresh it with `pip install pyarrow && python3 scripts/import_overture.py` (add `--release …` to pin one). Only this script needs `pyarrow`; the app itself stays standard-library only.
- At runtime `overture.py` matches a venue found through OpenStreetMap that has **no website** to an Overture venue (similar name after dropping words like "Restaurant"/"Hotel", within 75 m) and borrows its website and phone number. The venue is marked `websiteSource: "overture"` and the venue panel credits Overture Maps. An OpenStreetMap website always wins. If the data file is missing, nothing changes.
- **Measured accuracy (a rough estimate):** of the 203 bundled Swiss venues with a known website, Overture finds a match for about 60%, and for about 84% of those it returns the same website host; most of the rest are the same venue under a second domain (`goldauerhof.ch` vs `.com`) rather than a wrong venue. Treat a borrowed website as a good guess, not a certainty: scanning it can only ever produce the same "mentioned on the website" evidence as any other website.
- **Licence:** Overture's places theme is CDLA-Permissive-2.0; see [`server/data/OVERTURE_ATTRIBUTION.md`](server/data/OVERTURE_ATTRIBUTION.md) and check Overture's current terms before redistributing the file. Only Switzerland is imported for now; adding a country later means adding it to `COUNTRIES` in the script.

### Checking that a git push really went live

Vercel deploys automatically when the repository is connected: a push to the **Production Branch** (`main`) updates the live site, any other branch or PR gets its own **preview** URL. To confirm a deploy, the app reports the commit it is running in `/api/config`:

```json
"deployment": { "commit": "0123456789abcdef…", "commitShort": "0123456", "branch": "main", "environment": "production" }
```

(`environment` is `production`, `preview`, `development` or `local`; the values come from variables Vercel sets for every deployment, and only these four fields are exposed.) Compare it with the commit you pushed:

```bash
python3 scripts/check_deploy.py https://guinness-pi.vercel.app --head                       # is my current commit live?
python3 scripts/check_deploy.py https://guinness-pi.vercel.app --commit a1b2c3d --wait 300  # wait up to 5 min for the build
python3 scripts/check_deploy.py https://<preview-url> --head --environment preview          # check a preview
```

Exit status: `0` the commit is live · `1` a different commit (or an older deployment without this feature) is live · `2` bad usage or unreachable. Preview URLs are behind Vercel login by default, so check previews from the Vercel dashboard or disable protection for them. Tests: `tests/test_deploy_info.py`.

If a push does not deploy: the Vercel GitHub app may not have access to the repository (GitHub → Settings → Applications → Vercel → Configure), the Production Branch may not be `main` (Project → Settings → Git), or the connection may have broken when the repository was renamed. Environment variables are scoped per environment (Production / Preview / Development) and only apply to *new* deployments.

---

## Security Notes

What the Python API ([`app_server.py`](app_server.py) + [`guard.py`](guard.py)) enforces — each point has tests in `tests/`:

- **No server-side request forgery.** Every venue-website fetch goes through `guard.fetch_page`: only `http(s)`; the hostname is resolved and **all** addresses must be public (no loopback, private, link-local/cloud-metadata, CGNAT, multicast, IPv4-mapped/NAT64/6to4 tricks); the connection is made to the *validated* IP (no DNS re-resolution), **every redirect hop is re-validated**, `file://`/`ftp://` redirects are refused, and downloads are capped at 1.5 MB with a hard 10 s wall-clock deadline (slow-drip servers are cut off). Unsafe URLs are reported as "not scanned", never as "no Guinness".
- **Submissions are validated and bounded**: JSON-only bodies (≤ 20 KB, which also blocks cross-site form posts), whitelisted enums, length limits, price normalised to `CHF 9.50`, coordinates must be inside Switzerland, websites must be public `http(s)` URLs (`javascript:`, `data:`, IP literals, `localhost` are rejected). Errors come back as readable JSON, never a dropped connection.
- **No result poisoning.** A menu scan is only *saved* for a known venue and only when the scanned page is on that venue's own site; otherwise the caller sees their result but nothing is stored for other visitors. Spoofed Google Maps links (e.g. `google.com.evil.com`) are replaced by a safe search link.
- **No scripted links.** Both UIs only ever link to `http(s)` website URLs (`safeHttpUrl`; a test keeps `standalone.html` and `src/safeUrl.js` identical and checks no website `href` bypasses it). All other venue text is HTML-escaped / rendered by React.
- **Keys**: see "Deploying to Vercel" above. `/api/config` never returns a server key.

**Not covered / known limitations**

- Rate limits are per client IP; a determined attacker with many IPs is not stopped. They bound accidental and casual abuse and your Google bill together with a budget alert.
- Community submissions are unauthenticated by design. Capped list sizes bound the damage; add moderation or sign-in before relying on them.
- The Redis REST client is exercised against a fake server in tests (the Upstash protocol as documented), **not yet against a live Upstash instance** — deploy and submit one test report to confirm.

---

## Testing

```bash
npm test            # everything below except the browser tests (no network, no browser needed)
npm run test:py     # python3 -m unittest   (stdlib only; ~150 tests)
npm run test:js     # node --test           (UI helpers: distance, price, map clicks, layout, safe URLs)
npm run test:e2e    # builds the React app, then drives real pages in Chromium (needs Playwright; skipped automatically if it is missing)
```

[`.github/workflows/test.yml`](.github/workflows/test.yml) runs all of these on every push and pull request.

| File | Covers |
| :--- | :--- |
| `tests/test_core.py` | **the app's core logic**: Guinness status scoring (every branch, "unchecked is never *no*"), venue enrichment & community-report merging, Google Places and OpenStreetMap mappings against realistic fake responses, bundled-data integrity (unique ids, Swiss coordinates, valid categories, plain-http(s) websites), HTTP routes (static pages, no file exposure, venue modes, error paths) |
| `tests/test_guard.py` | URL normalisation, public-address rules, SSRF-safe fetching against real local servers (redirect hops, DNS pinning, size/time caps, slow-drip & slow-header attacks), input validation, rate limiter |
| `tests/test_storage.py` | file backend, Redis backend against a fake Upstash server (sharing across instances, caps, outages, bad tokens, atomic expiring counters), backend selection |
| `tests/test_api.py` | the real request handler end to end: key exposure, Vercel key policy, hardening, validation, persistence across "instances", poisoning, rate limiting, 503 behaviour |
| `tests/test_deploy.py` | `vercel.json` bundles every module the function imports; entrypoint imports; no committed API keys |
| `tests/test_overpass.py` | failover across real local HTTP servers that play busy/broken mirrors: every retryable status, timeouts, HTML/garbage/JSON-array answers, HTTP 200 with a timeout remark, dead servers, HTTP 400 stops at once, giving up with a friendly error, the overall deadline, pauses between passes, the cache (hit, expiry, off, stale-if-error, bounded), and the scan functions + API (503 + `Retry-After`) |
| `tests/test_overture.py`, `tests/test_import_overture.py` | name matching and the spatial lookup (including cases measured on real data), how OpenStreetMap importers use it, and the importer end to end against synthetic Parquet files in Overture's real schema served by a fake S3 (needs `pyarrow`; skipped without it) |
| `tests/test_evidence.py`, `tests/e2e/evidence.e2e.mjs` | **honest evidence**: the bundled data files and every importer carry no invented ratings, review counts, quotes or visitor reports (checked over all ~230 real venues); a tag or a name is a labelled hint, never "confirmed" or "found on a menu"; an unreadable website is *unknown*, not *no Guinness*; "On Tap" only when the page says so; the header counts confirmed and likely apart; the venue panel explains a hint; **prices**: the one printed after "Guinness" (not a neighbouring beer's) is extracted from a scan, starter-list prices stay visible but marked "unchecked" |
| `tests/test_geocode.py`, `tests/e2e/location.e2e.mjs` | **venues land at their address**: the geocoder against a fake Nominatim (Switzerland only, polite User-Agent, cache, busy vs not-found, malformed answers), `/api/geocode`, `/api/relocate-venue` (only a venue's own stored address is used, bundled venues are never moved, errors), and the form in both UIs (the address is looked up when no spot was clicked, a clicked spot is kept, an unknown address blocks the submit, a venue saved in the wrong place can be moved) |
| `tests/test_crawler.py` | the website crawler: it never fetches internal addresses (loopback, cloud metadata, private ranges) and honours `robots.txt`, finds Guinness and follows a menu link on real local pages, picks which sites to read (`--all`, `--max-urls`), fills websites from Overture (unsafe ones refused), keeps a restaurant recipe out of *Confirmed*, refuses a crawl that lost most known venues, and the workflow publishes a branch (never a PR or `main`) after checking |
| `tests/test_repo.py` | repository hygiene: nothing that `.gitignore` excludes is tracked, the old product name is gone, city fallbacks name cities that exist, the UI mentions no other countries, the Python server is the only API server, and the `.env` reader |
| `tests/e2e/evidence.e2e.mjs`, `tests/js/mobileLayout.test.js` (UI part) | plain labels and reasons on cards and in the panel, no zero-count noise, nothing auto-opens, owner-only controls hidden unless `?advanced=1`, the Add and report forms assume nothing (no pre-selected serving format) and there is no pint score |
| `tests/test_deploy_info.py` | the deployed-commit report in `/api/config` (nothing else from the environment leaks, malformed values dropped) and `scripts/check_deploy.py` (match/mismatch/old/unreachable, `--wait` polling, usage errors) |
| `tests/js/*.test.js` | UI helpers: distance maths, price display, map click timing, phone layout rules, `safeHttpUrl` parity between both UIs, href lint |
| `tests/fixtures/shared_cases.json` | a table of Guinness-status and Google-Maps-link scenarios that `tests/test_core.py` runs through the Python server |
| `tests/e2e/nearme.e2e.mjs`, `tests/js/geo.test.js` | the Near me filter with emulated geolocation (Zürich, London, denied permission), including the on-by-default behaviour (starts at 500 m, widens and says so, stays on Anywhere far from every venue, silent when denied, remembers the choice, user clicks win, no request carries the position, phone): the right venues, nearest first, distances, tighter radii, Anywhere restoring the list, the map position/circle, the details distance, the header button, the explained denial, **no request carries the position**, city chips turning it off, the empty state with the nearest match and its three actions, *Scan around me* (sends the position exactly once) and a busy-server message, plus the phone filter sheet; the unit tests cover the haversine distance (known city pairs, antimeridian, invalid input), formatting, filtering/sorting, boundaries and error messages |
| `tests/e2e/map.e2e.mjs`, `tests/js/mapClick.test.js` | map gestures in both UIs with real Leaflet: **a double-click zooms and does not open the add-venue form**; a lone click on empty map still offers to add a venue there (after a 300 ms wait to rule out a double-click); **dialogs open in front of the map's zoom buttons and floating controls**; the click/double-click timing logic with a fake clock |
| `tests/e2e/mobile.e2e.mjs` | the **phone / tablet / desktop layouts** of the built React app (plus the standalone page) with real Leaflet and the real API: no sideways scroll on iPhone SE / 13, Pixel 5, landscape and iPad; the list comes first and no sheet covers it; Leaflet markers do not swallow taps; List / Map tabs; the filters sheet; every control ≥ 44 px and fields ≥ 16 px; the full-width add-venue sheet; and a desktop regression check at 1024 / 1280 / 1920 px. Against the old stylesheet all 16 fail. `tests/js/mobileLayout.test.js` keeps the breakpoint identical in the CSS, the React app and the standalone page |
| `tests/e2e/ui.e2e.mjs` | the real `standalone.html` in a browser: no `javascript:` links, hostile text stays inert, server errors and rate limits are shown to the user |

**Not covered:** the React UI (`src/`) has no browser test (only a build check in CI and the `safeHttpUrl` lint); map rendering is replaced by a stub; live Google, Overpass and Upstash are never called (fakes of their documented response shapes are used instead).

When fixing a bug, add a failing test first (name it `regression: ...`). Tests never call Google or any external site.


---

## Nationwide Switzerland Crawler & Google Maps Venue Checker

### Finding more venues: the website crawl

The crawler (`scripts/crawl_switzerland.py`) asks OpenStreetMap for Swiss pubs, bars, restaurants and hotels, adds the website Overture Maps knows for venues OpenStreetMap lists without one, and reads each website looking for Guinness. A hit is real evidence (the page text is kept). It re-runs the nationwide OpenStreetMap query and a 120-worker website scanner across all 26 cantons:

```bash
python3 scripts/crawl_switzerland.py          # every pub/bar website plus 400 hotels/restaurants (about 2,000 sites)
python3 scripts/crawl_switzerland.py --all    # every website, restaurants and hotels too (about 8,000 sites, roughly 10 minutes)
```

Options: `--max-urls N`, `--no-overture`. It only fetches through the app's SSRF-safe fetcher (`guard.fetch_page`: public hosts only, TLS verified, size and time limits, never an address from a tag without validating it), honours each site's `robots.txt`, and uses the app's Overpass client (mirrors and retries). A pub or bar that names Guinness counts as serving it; a restaurant or hotel needs serving wording or a price, otherwise it becomes a *Possible* hint ("Its website mentions Guinness (not clearly on a menu)"), so a recipe or an event is never shown as Confirmed.

**Running it on GitHub (recommended):** Actions -> **Crawl venue websites** -> *Run workflow* (it also runs monthly). The job crawls, checks the result (`scripts/check_crawl_result.py` refuses a crawl that lost more than 30% of the venues we already know, which means it ran into network trouble; `tests/test_evidence.py` re-checks the data) and pushes the new `server/data/swiss_crawl_results.json` to a branch named `data/crawl-<date>`. It does not open the pull request itself, because a pull request made by a workflow does not run the checks that protect `main`: open the PR from that branch yourself.

To check bars, pubs, restaurants, cafés, and hotels on Google Maps (via Google Places API New `places:searchNearby` & `places:searchText`, or by cross-checking Swiss venues and Google Maps URLs), scrape their online menus for Guinness, and feed the verified input directly into the Guinness Finder:

```bash
python3 scripts/check_google_maps.py
```

See [`scripts/README.md`](scripts/README.md) for full details on crawler options, Google Maps checking flags, output datasets, and git sync utilities.

---

## REST API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/config` | Returns regional presets (`CITY_PRESETS`), the **browser** map key (never the server key) and `communitySubmissions` (whether a database is available for reports / new venues) |
| `GET` | `/api/venues` | Returns filtered Swiss venues (`city`, `lat`, `lng`, `radius`, `scrapeMenus`) |
| `POST` | `/api/check-google-maps` | Checks Google Maps / Places or a Google Maps URL/query for Guinness and imports venues |
| `POST` | `/api/scan-switzerland` | Queries OpenStreetMap Overpass API live across Switzerland for Guinness/Irish pubs |
| `POST` | `/api/scan-menu` | Live-scrapes a specific venue's website or menu URL for Guinness variants & CHF price |
| `POST` | `/api/crowd-report` | Submits a community report: serving format (required), price, and Guinness 0.0 |
| `POST` | `/api/add-venue` | Adds a new hospitality venue to the map and optionally scrapes its menu URL |
| `GET` | `/api/geocode?q=` | Looks up a Swiss address (OpenStreetMap Nominatim, cached): `{found, lat, lng, label}`; 503 if the lookup service is busy |
| `POST` | `/api/relocate-venue` | Moves a visitor-added venue to its stored address (`{venueId}`); the visitor cannot supply coordinates |

---

All `POST` endpoints require `Content-Type: application/json` and answer errors as `{"error": "..."}` with status `400` (invalid input), `413` (body > 20 KB), `415` (wrong content type), `429` (rate limited, with `Retry-After`) or `503` (no database / database down). See [Security Notes](#security-notes).

---

## Project Structure

```text
Guinness/
├── README.md                        # Main project documentation
├── vercel.json                      # Vercel serverless routing & bundle configuration
├── api/
│   └── index.py                     # Vercel Python Serverless Function entrypoint
├── app_server.py                    # Zero-dependency Python 3 server + embedded Swiss dataset
├── guard.py                         # SSRF-safe fetching, input validation, rate limiting (stdlib only)
├── geocode.py                       # Swiss address -> map position (Nominatim; stdlib only)
├── evidence.py                      # What counts as evidence for a venue; strips invented data from the bundled files (stdlib only)
├── storage.py                       # File + Upstash/Vercel-KV persistence for community data (stdlib only)
├── overture.py                      # Fills missing venue websites from the Overture extract (stdlib only)
├── overpass.py                      # Overpass API access: backup servers, retries, cache, friendly errors (stdlib only)
├── tests/                           # python3 -m unittest suites; tests/js (UI helpers), tests/e2e (browser), tests/fixtures
├── .github/workflows/test.yml       # CI: runs every test suite on push / PR
├── .github/workflows/crawl.yml      # Crawl venue websites (manual + monthly); pushes the result to a data/crawl-<date> branch
├── index.html                       # Vite React entry HTML
├── package.json                     # React/Vite build and test scripts (no Node server)
├── public/
│   └── standalone.html              # Self-contained React + Leaflet UI served by app_server.py
├── scripts/
│   ├── check_deploy.py              # Checks which commit is live on a deployment (git push -> Vercel)
│   ├── import_overture.py           # Builds server/data/overture_ch.json from Overture Maps (needs pyarrow)
│   ├── README.md                    # Documentation for scripts & automation utilities
│   ├── check_google_maps.py         # Google Maps venue & review verifier / importer
│   ├── check_crawl_result.py        # Refuses a crawl that lost most of the known venues (used by crawl.yml)
│   └── crawl_switzerland.py         # Nationwide Swiss OSM Overpass + website menu crawler
├── server/
│   └── data/                        # swiss_crawl_results.json (website scans), overture_ch.json (websites), attribution
└── src/
    ├── App.jsx                      # Main React application component
    ├── main.jsx                     # React DOM bootstrap
    ├── safeUrl.js                   # http(s)-only link helper (mirrored in standalone.html)
    ├── styles.css                   # Styling and theme variables
    └── components/
        ├── AddVenueModal.jsx        # Modal for submitting new venues (opened by a single click on the map)
        ├── ApiKeyModal.jsx          # Modal for switching Map modes & Google API key
        ├── MapCanvas.jsx            # Leaflet / Google Maps interactive map canvas
        ├── PintIcon.jsx             # Custom SVG Guinness pint markers & badges
        └── VenueDetailPanel.jsx     # 3-pillar verification & crowdsource side panel
```

---

## Contributing

- Work on a feature branch and open a pull request into `main`; CI (`.github/workflows/test.yml`) must pass. `main` deploys to production on Vercel, so nothing is pushed to it directly.
- A behaviour change needs a test (a bug fix needs a failing `regression:` test first) and an update to this README, `scripts/README.md` and the module docstring it touches.
- Use one product name, **Guinness Guide**, in the UI and the docs, and Guinness-only wording (no other beers or countries yet).

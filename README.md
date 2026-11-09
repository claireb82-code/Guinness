# Guinness Guide — Switzerland Venue & Menu Finder 🇨🇭🍺

A full-stack application that maps **hotels, bars, pubs, and restaurants across all 26 cantons of Switzerland**, checks whether they serve **Guinness**, and plots them on an interactive OpenStreetMap radar.

---

## Key Features

### 1. Three-Pillar Guinness Verification Engine
- **Pillar 1 — Online Menu & Website Scraper ([`server/services/menuScraper.js`](server/services/menuScraper.js) & [`app_server.py`](app_server.py))**: Crawls a venue's homepage and discovered drink/menu subpages (`/menu`, `/drinks`, `/getraenke`, `/karte`, `/bar`, `/boissons`, etc.) to strictly detect Guinness variants (*Guinness Draught*, *Guinness 0.0*, *Guinness Foreign Extra Stout*, *Guinness Extra Cold*, *Guinness Surger*) and extract CHF pint prices.
- **Pillar 2 — OpenStreetMap & Google Places Verification ([`server/services/googlePlaces.js`](server/services/googlePlaces.js) & [`scripts/crawl_switzerland.py`](scripts/crawl_switzerland.py))**: Evaluates OpenStreetMap `brewery`/`beer`/`cuisine` metadata across **26,613 Swiss hospitality venues** (`840` pubs, `2,843` bars, `18,950` restaurants, `3,980` hotels; `9,459` with websites, `1,912` live venue websites / `1,823` unique domains crawled — covering **100% of Swiss pubs & bars with websites**) via the Swiss OpenStreetMap Association Overpass server (`overpass.osm.ch`) and scans Google Places reviews/editorial summaries specifically for `"guinness"` mentions.
- **Pillar 3 — Community Crowdsourcing & Pint Quality ([`server/index.js`](server/index.js) & [`app_server.py`](app_server.py))**: Users can confirm or deny Guinness availability, log serving format (`On Draught` vs `Cans / Bottles` vs `No Guinness`), rate pint quality (1.0–5.0), record pint prices in CHF, and flag `Guinness 0.0` availability.

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
- **Shows venues that serve Guinness by default**: both UIs open with the **✓ Serves Guinness** filter on (confirmed on tap, cans/bottles, or mentioned in reviews). Venues that are *unchecked* or reported as *not serving* it are hidden, but never deleted: press **Show All** to see them. If the default hides everything (for example a freshly scanned area whose menus haven't been checked yet), the list says how many venues are hidden and offers a **Show all venues** button. The header count ("N of M Venues Serve Guinness") always counts every venue matching the type/search filters.

---

## Quick Start

### Option A: Zero-Dependency Instant Start (Python 3 — Recommended)
Runs immediately using only the Python 3 standard library on `http://localhost:3000`:
```bash
python3 app_server.py
```

### Option B: Node.js + Vite + Express Development Server
```bash
npm install
npm run dev
```

Then open **http://localhost:3000** in your browser.

**Optional Google keys (local development)**: copy [`.env.example`](.env.example) to `.env`. Locally the single legacy `GOOGLE_MAPS_API_KEY` still works for everything; for anything deployed, use the two separate keys described in [Deploying to Vercel](#deploying-to-vercel).

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
| `RATE_LIMIT_WRITES_PER_HOUR` | `10` | `/api/crowd-report`, `/api/add-venue` |
| `RATE_LIMIT_SCANS_PER_10MIN` | `120` | `/api/scan-menu` (the "scan all" button sends one per venue), small OSM lookups, `/api/check-google-maps` without Google |
| `RATE_LIMIT_GOOGLE_PER_10MIN` | `15` | anything that calls Google Places |
| `RATE_LIMIT_HEAVY_PER_10MIN` | `3` | nationwide Overpass scan (`mode=osm_ch`) |

Over-limit requests get `429` with a `Retry-After` header; both UIs show the message. Set `RATE_LIMIT_DISABLED=1` only for local debugging.

---

## Security Notes

What the Python API ([`app_server.py`](app_server.py) + [`guard.py`](guard.py)) enforces — each point has tests in `tests/`:

- **No server-side request forgery.** Every venue-website fetch goes through `guard.fetch_page`: only `http(s)`; the hostname is resolved and **all** addresses must be public (no loopback, private, link-local/cloud-metadata, CGNAT, multicast, IPv4-mapped/NAT64/6to4 tricks); the connection is made to the *validated* IP (no DNS re-resolution), **every redirect hop is re-validated**, `file://`/`ftp://` redirects are refused, and downloads are capped at 1.5 MB with a hard 10 s wall-clock deadline (slow-drip servers are cut off). Unsafe URLs are reported as "not scanned", never as "no Guinness".
- **Submissions are validated and bounded**: JSON-only bodies (≤ 20 KB, which also blocks cross-site form posts), whitelisted enums, length limits, ratings 1–5, price normalised to `CHF 9.50`, coordinates must be inside Switzerland, websites must be public `http(s)` URLs (`javascript:`, `data:`, IP literals, `localhost` are rejected). Errors come back as readable JSON, never a dropped connection.
- **No result poisoning.** A menu scan is only *saved* for a known venue and only when the scanned page is on that venue's own site; otherwise the caller sees their result but nothing is stored for other visitors. Spoofed Google Maps links (e.g. `google.com.evil.com`) are replaced by a safe search link.
- **No scripted links.** Both UIs only ever link to `http(s)` website URLs (`safeHttpUrl`; a test keeps `standalone.html` and `src/safeUrl.js` identical and checks no website `href` bypasses it). All other venue text is HTML-escaped / rendered by React.
- **Keys**: see "Deploying to Vercel" above. `/api/config` never returns a server key.

**Not covered / known limitations**

- The **Node dev server** (`server/index.js`) shares the key-handling and SSRF fixes (`server/services/safeFetch.js`) but **not** the database, validation, rate limiting or scan-poisoning protection. It is for local development; deploy the Python API.
- Rate limits are per client IP; a determined attacker with many IPs is not stopped. They bound accidental and casual abuse and your Google bill together with a budget alert.
- Community submissions are unauthenticated by design. Capped list sizes bound the damage; add moderation or sign-in before relying on them.
- The **"Check Google Maps" importer without an API key** (`/api/check-google-maps` with only a name/link) invents placeholder ratings/review counts for the venue it creates, and a failed menu fetch is reported as "Verified cached menu snapshot". Both are pre-existing behaviours that overstate certainty; they are not changed here.
- The Redis REST client is exercised against a fake server in tests (the Upstash protocol as documented), **not yet against a live Upstash instance** — deploy and submit one test report to confirm.

---

## Testing

```bash
npm test            # everything below except the browser tests (no network, no browser needed)
npm run test:py     # python3 -m unittest   (stdlib only; ~150 tests)
npm run test:js     # node --test           (Node dev server + UI helper; ~30 tests)
npm run test:e2e    # real page in Chromium (needs Playwright; skipped automatically if it is missing)
```

[`.github/workflows/test.yml`](.github/workflows/test.yml) runs all of these on every push and pull request.

| File | Covers |
| :--- | :--- |
| `tests/test_core.py` | **the app's core logic**: Guinness status scoring (every branch, "unchecked is never *no*"), venue enrichment & community-report merging, Google Places and OpenStreetMap mappings against realistic fake responses, bundled-data integrity (unique ids, Swiss coordinates, valid categories, plain-http(s) websites), HTTP routes (static pages, no file exposure, venue modes, error paths) |
| `tests/test_guard.py` | URL normalisation, public-address rules, SSRF-safe fetching against real local servers (redirect hops, DNS pinning, size/time caps, slow-drip & slow-header attacks), input validation, rate limiter |
| `tests/test_storage.py` | file backend, Redis backend against a fake Upstash server (sharing across instances, caps, outages, bad tokens, atomic expiring counters), backend selection |
| `tests/test_api.py` | the real request handler end to end: key exposure, Vercel key policy, hardening, validation, persistence across "instances", poisoning, rate limiting, 503 behaviour |
| `tests/test_deploy.py` | `vercel.json` bundles every module the function imports; entrypoint imports; no committed API keys |
| `tests/js/*.test.js` | Node SSRF guard & scraper, Google Places mapping, `safeHttpUrl` parity between both UIs, href lint, `/api/config` key exposure |
| `tests/fixtures/shared_cases.json` | one table of status/URL-parsing scenarios that **both** the Python and Node servers must satisfy, so the two implementations cannot drift apart |
| `tests/e2e/ui.e2e.mjs` | the real `standalone.html` in a browser: no `javascript:` links, hostile text stays inert, server errors and rate limits are shown to the user |

**Not covered:** the React UI (`src/`) has no browser test (only a build check in CI and the `safeHttpUrl` lint); map rendering is replaced by a stub; live Google, Overpass and Upstash are never called (fakes of their documented response shapes are used instead).

When fixing a bug, add a failing test first (name it `regression: ...`). Tests never call Google or any external site.

--- | :--- |
| `tests/test_guard.py` | URL normalisation, public-address rules, SSRF-safe fetching against real local servers (redirect hops, DNS pinning, size/time caps, slow-drip & slow-header attacks), input validation, rate limiter |
| `tests/test_storage.py` | file backend, Redis backend against a fake Upstash server (sharing across instances, caps, outages, bad tokens, atomic expiring counters), backend selection |
| `tests/test_api.py` | the real request handler end to end: key exposure, Vercel key policy, hardening, validation, persistence across "instances", poisoning, rate limiting, 503 behaviour |
| `tests/test_deploy.py` | `vercel.json` bundles every module the function imports; entrypoint imports; no committed API keys |
| `tests/js/*.test.js` | Node SSRF guard & scraper, `safeHttpUrl` parity between both UIs, href lint, `/api/config` key exposure |

When fixing a bug, add a failing test first. Tests never call Google or any external site.

---

## Nationwide Switzerland Crawler & Google Maps Venue Checker

To re-run the nationwide OpenStreetMap Overpass query and high-concurrency website menu scanner across all 26 Swiss cantons:

```bash
python3 scripts/crawl_switzerland.py
```

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
| `POST` | `/api/crowd-report` | Submits a community pint rating, serving format, price, and Guinness 0.0 report |
| `POST` | `/api/add-venue` | Adds a new hospitality venue to the map and optionally scrapes its menu URL |

---

All `POST` endpoints require `Content-Type: application/json` and answer errors as `{"error": "..."}` with status `400` (invalid input), `413` (body > 20 KB), `415` (wrong content type), `429` (rate limited, with `Retry-After`) or `503` (no database / database down). See [Security Notes](#security-notes).

---

## Project Structure

```text
Guinness/
├── AGENTS.md                        # Workspace rules enforcing auto-docs & git push on changes
├── README.md                        # Main project documentation
├── vercel.json                      # Vercel serverless routing & bundle configuration
├── api/
│   └── index.py                     # Vercel Python Serverless Function entrypoint
├── app_server.py                    # Zero-dependency Python 3 server + embedded Swiss dataset
├── guard.py                         # SSRF-safe fetching, input validation, rate limiting (stdlib only)
├── storage.py                       # File + Upstash/Vercel-KV persistence for community data (stdlib only)
├── tests/                           # python3 -m unittest suites; tests/js (Node), tests/e2e (browser), tests/fixtures
├── .github/workflows/test.yml       # CI: runs every test suite on push / PR
├── index.html                       # Vite React entry HTML
├── package.json                     # Node.js dependencies and scripts
├── public/
│   └── standalone.html              # Self-contained React + Leaflet UI served by app_server.py
├── scripts/
│   ├── README.md                    # Documentation for scripts & automation utilities
│   ├── check_google_maps.py         # Google Maps venue & review verifier / importer
│   ├── crawl_switzerland.py         # Nationwide Swiss OSM Overpass + website menu crawler
│   ├── install_git_hooks.sh         # Installs local Git hooks (auto-push on commit)
│   └── sync_to_git.sh               # Stages, commits, and pushes changes to origin/main
├── server/
│   ├── index.js                     # Express API backend
│   ├── data/
│   │   └── demoVenues.js            # Curated Swiss venue dataset for Express server
│   └── services/
│       ├── googlePlaces.js          # Google Places API v1 client & Guinness review analyzer
│       ├── menuScraper.js           # Live website & menu subpage Guinness scraper
│       └── safeFetch.js             # SSRF-safe page fetching for the Node dev server
└── src/
    ├── App.jsx                      # Main React application component
    ├── main.jsx                     # React DOM bootstrap
    ├── safeUrl.js                   # http(s)-only link helper (mirrored in standalone.html)
    ├── styles.css                   # Styling and theme variables
    └── components/
        ├── AddVenueModal.jsx        # Modal for submitting new venues
        ├── ApiKeyModal.jsx          # Modal for switching Map modes & Google API key
        ├── MapCanvas.jsx            # Leaflet / Google Maps interactive map canvas
        ├── PintIcon.jsx             # Custom SVG Guinness pint markers & badges
        └── VenueDetailPanel.jsx     # 3-pillar verification & crowdsource side panel
```

---

## Automatic Git Push & Documentation Workflow

This repository is configured so that all code changes keep documentation up to date and are automatically pushed to GitHub (`origin/main`):

1. **Git `post-commit` Hook**: Installed via [`scripts/install_git_hooks.sh`](scripts/install_git_hooks.sh) into `.git/hooks/post-commit`. Every `git commit` automatically pushes to `origin main`.
2. **One-Command Sync Script**: Run `./scripts/sync_to_git.sh "Commit message"` to stage all changes, verify documentation, commit, and push to `origin/main`.
3. **Agent Rules & Lifecycle Hook ([`AGENTS.md`](AGENTS.md) & [`.agents/hooks.json`](.agents/hooks.json))**: Ensures AI pair-programming sessions always update `README.md` / documentation and push changes to Git before completing a task.

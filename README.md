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

---

## Deploying to Vercel

This repository is pre-configured for one-click deployment to [Vercel](https://vercel.com):
1. **Serverless API & Routing ([`vercel.json`](vercel.json) & [`api/index.py`](api/index.py))**: Routes all `/api/*` endpoints (`/api/config`, `/api/venues`, `/api/check-google-maps`, `/api/scan-menu`, `/api/crowd-report`, `/api/add-venue`) to `StoutScoutHandler` in [`app_server.py`](app_server.py) and bundles the Swiss dataset.
2. **Serverless Storage Fallback**: When `VERCEL=1` is present at runtime, both [`app_server.py`](app_server.py) and [`server/index.js`](server/index.js) seed initial venue/report data from `server/data/user_store.json` and write runtime updates to `/tmp/user_store.json`.
3. **Deploy**: Import the GitHub repository at [vercel.com/new](https://vercel.com/new) (or run `npx vercel --prod`). Optionally set `GOOGLE_MAPS_API_KEY` in Vercel Project Settings → Environment Variables.

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
| `GET` | `/api/config` | Returns regional presets (`CITY_PRESETS`) and server API key status |
| `GET` | `/api/venues` | Returns filtered Swiss venues (`city`, `lat`, `lng`, `radius`, `scrapeMenus`) |
| `POST` | `/api/check-google-maps` | Checks Google Maps / Places or a Google Maps URL/query for Guinness and imports venues |
| `POST` | `/api/scan-switzerland` | Queries OpenStreetMap Overpass API live across Switzerland for Guinness/Irish pubs |
| `POST` | `/api/scan-menu` | Live-scrapes a specific venue's website or menu URL for Guinness variants & CHF price |
| `POST` | `/api/crowd-report` | Submits a community pint rating, serving format, price, and Guinness 0.0 report |
| `POST` | `/api/add-venue` | Adds a new hospitality venue to the map and optionally scrapes its menu URL |

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
│       └── menuScraper.js           # Live website & menu subpage Guinness scraper
└── src/
    ├── App.jsx                      # Main React application component
    ├── main.jsx                     # React DOM bootstrap
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

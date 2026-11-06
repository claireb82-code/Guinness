# Guinness Guide — Switzerland Venue & Menu Finder 🇨🇭🍺

A full-stack application that maps **hotels, bars, pubs, and restaurants across all 26 cantons of Switzerland**, checks whether they serve **Guinness**, and plots them on an interactive OpenStreetMap radar.

---

## Key Features

### 1. Three-Pillar Guinness Verification Engine
- **Pillar 1 — Online Menu & Website Scraper ([`server/services/menuScraper.js`](server/services/menuScraper.js) & [`app_server.py`](app_server.py))**: Crawls a venue's homepage and discovered drink/menu subpages (`/menu`, `/drinks`, `/getraenke`, `/karte`, `/bar`, `/boissons`, etc.) to strictly detect Guinness variants (*Guinness Draught*, *Guinness 0.0*, *Guinness Foreign Extra Stout*, *Guinness Extra Cold*, *Guinness Surger*) and extract CHF pint prices.
- **Pillar 2 — OpenStreetMap & Google Places Verification ([`server/services/googlePlaces.js`](server/services/googlePlaces.js) & [`scripts/crawl_switzerland.py`](scripts/crawl_switzerland.py))**: Evaluates OpenStreetMap `brewery`/`beer`/`cuisine` metadata across 24,523 Swiss hospitality venues and scans Google Places reviews/editorial summaries specifically for `"guinness"` mentions.
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

## Nationwide Switzerland Crawler

To re-run the nationwide OpenStreetMap Overpass query and high-concurrency website menu scanner across all 26 Swiss cantons:

```bash
python3 scripts/crawl_switzerland.py
```

See [`scripts/README.md`](scripts/README.md) for full details on crawler options, output datasets, and git sync utilities.

---

## REST API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/config` | Returns regional presets (`CITY_PRESETS`) and server API key status |
| `GET` | `/api/venues` | Returns filtered Swiss venues (`city`, `lat`, `lng`, `radius`, `scrapeMenus`) |
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
├── app_server.py                    # Zero-dependency Python 3 server + embedded Swiss dataset
├── index.html                       # Vite React entry HTML
├── package.json                     # Node.js dependencies and scripts
├── public/
│   └── standalone.html              # Self-contained React + Leaflet UI served by app_server.py
├── scripts/
│   ├── README.md                    # Documentation for scripts & automation utilities
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

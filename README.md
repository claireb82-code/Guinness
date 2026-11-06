# StoutScout — Guinness Venue & Menu Finder

A full-stack React + Node.js/Express application that locates **hotels, bars, pubs, and restaurants**, checks whether they serve **Guinness**, and plots them on an interactive dark-themed map.

## Features

1. **Three-Pillar Guinness Verification Engine**
   - **Pillar 1 — Online Menu & Website Scraper (`server/services/menuScraper.js`)**: Crawls a venue's website homepage and discovered menu subpages (`/menu`, `/drinks`, `/bar`, etc.) to detect Guinness variants (*Guinness Draught*, *Guinness 0.0*, *Guinness Foreign Extra Stout*, *West Indies Porter*) and extract pint prices.
   - **Pillar 2 — Google Places Reviews & Editorial Analysis (`server/services/googlePlaces.js`)**: Scans Google Places reviews and editorial summaries for mentions of `"guinness"`, `"stout"`, `"pint"`, `"creamy"`, `"two-part pour"`, and `"split the G"`, highlighting matching review quotes.
   - **Pillar 3 — Community Crowdsourcing & Pint Quality (`server/index.js`)**: Users can confirm or deny Guinness availability, log serving format (`On Draught` vs `Cans / Bottles` vs `No Guinness`), rate pint quality (1.0–5.0), record pint prices, and flag `Guinness 0.0` availability.

2. **Interactive Map with Dual Mode Support**
   - **Demo + Live Scraper Mode (Zero Config)**: Works immediately out-of-the-box with curated venues across Dublin, London, New York, and Chicago plus live website menu scraping and persistent crowdsourcing.
   - **Google Maps & Places Live Mode**: Enter your Google Maps Platform API key via the in-app **API Key / Mode** button (or `.env`) to query the Google Places API for all nearby hotels, bars, pubs, and restaurants and render them on the Google Maps JavaScript SDK with custom Guinness pint markers.

## Quick Start

### Option A: Zero-Dependency Instant Start (Python 3 — No install needed)
```bash
python3 app_server.py
```

### Option B: Node.js + Vite + Express Development Server
```bash
npm install
npm run dev
```

Then open **http://localhost:3000** in your browser.

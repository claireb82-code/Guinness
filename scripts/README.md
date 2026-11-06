# Scripts & Automation Utilities (`scripts/`)

This directory contains data collection scripts and Git automation utilities for **Guinness Guide — Switzerland Venue & Menu Finder**.

## Files

### 1. [`crawl_switzerland.py`](crawl_switzerland.py)
Nationwide Switzerland hospitality venue and menu crawler:
- Queries OpenStreetMap Overpass API (`ISO3166-1=CH`) across concurrent Overpass mirrors for every mapped `bar`, `pub`, `biergarten`, `restaurant`, and `hotel`/`hostel`/`guest_house`/`alpine_hut` across all 26 Swiss cantons.
- Evaluates OSM tags (`brewery`, `beer`, `drink:beer`, `cuisine`, `irish_pub`, etc.), pub name indicators, and generates Google Maps lookup URIs (`googleMapsUri`).
- Crawls venue websites and drink menu links (`/menu`, `/drinks`, `/getraenke`, `/karte`, `/bar`, `/boissons`) in parallel batches to detect **Guinness Draught**, **Guinness 0.0**, cans/bottles, and CHF prices.

**Usage:**
```bash
python3 scripts/crawl_switzerland.py
```

### 2. [`sync_to_git.sh`](sync_to_git.sh)
Stages all tracked/untracked repository changes, commits them with a descriptive message, and pushes to `origin/main`.

**Usage:**
```bash
./scripts/sync_to_git.sh "Update venue dataset and documentation"
```

### 3. [`install_git_hooks.sh`](install_git_hooks.sh)
Configures `.git/hooks/post-commit` so that every local `git commit` automatically pushes to `origin/main`.

**Usage:**
```bash
./scripts/install_git_hooks.sh
```

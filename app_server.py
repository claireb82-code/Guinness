#!/usr/bin/env python3
"""
Zero-dependency HTTP & API Server for Guinness Guide — Switzerland Venue & Menu Finder.
Serves the REST API (/api/config, /api/venues, /api/scan-menu, /api/crowd-report, /api/add-venue,
/api/geocode, ...) using only the Python 3 standard library, covering all 26 cantons of Switzerland.
This is the server that is deployed (api/index.py wraps it for Vercel).
"""

import json
import math
import os
import re
import sys
import time
import traceback
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer



def load_env_file(path, environ=None):
    """Read KEY=VALUE lines from a local ``.env`` into the environment (stdlib replacement for dotenv).

    Existing environment variables win, blank values and comments are skipped, and surrounding quotes are removed.
    Returns the names that were set. Used only when the server is started by hand, never on Vercel or in tests.
    """
    environ = os.environ if environ is None else environ
    names = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return names
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key and value and key not in environ:
            environ[key] = value
            names.append(key)
    return names


if __name__ == "__main__" and not os.environ.get("VERCEL") and not os.environ.get("GUINNESS_NO_DOTENV"):
    load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import evidence
import geocode
import guard
import overpass
import overture
import storage

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_STORE_PATH = os.path.join(ROOT_DIR, "server", "data", "user_store.json")
ON_VERCEL = bool(os.environ.get("VERCEL"))
SUBMISSIONS_DISABLED_MESSAGE = (
    "Community submissions are not enabled on this deployment: no database is configured, so "
    "anything submitted would be lost. See the README (Deploying to Vercel)."
)
STORE_PATH = os.environ.get("GUINNESS_STORE_PATH") or ("/tmp/user_store.json" if ON_VERCEL else BUNDLED_STORE_PATH)  # (tests use their own file)

CITY_PRESETS = {
    "all": {"id": "all", "name": "All Switzerland 🇨🇭", "lat": 46.8182, "lng": 8.2275, "zoom": 8, "currency": "CHF"},
    "zurich": {"id": "zurich", "name": "Zurich & Winterthur", "lat": 47.3745, "lng": 8.5385, "zoom": 13, "currency": "CHF"},
    "geneva": {"id": "geneva", "name": "Geneva", "lat": 46.2044, "lng": 6.1432, "zoom": 14, "currency": "CHF"},
    "lausanne": {"id": "lausanne", "name": "Lausanne, Vevey & Montreux", "lat": 46.5197, "lng": 6.6323, "zoom": 12, "currency": "CHF"},
    "basel": {"id": "basel", "name": "Basel & Aargau", "lat": 47.5546, "lng": 7.5886, "zoom": 13, "currency": "CHF"},
    "bern": {"id": "bern", "name": "Bern & Fribourg", "lat": 46.9480, "lng": 7.4450, "zoom": 13, "currency": "CHF"},
    "lucerne": {"id": "lucerne", "name": "Lucerne & Zug", "lat": 47.0518, "lng": 8.3075, "zoom": 12, "currency": "CHF"},
    "east": {"id": "east", "name": "St. Gallen & Schaffhausen", "lat": 47.4245, "lng": 9.3767, "zoom": 11, "currency": "CHF"},
    "alps": {"id": "alps", "name": "Alps & Ticino", "lat": 46.4500, "lng": 8.3500, "zoom": 9, "currency": "CHF"},
}

DEMO_VENUES = [
    # ================= ZURICH =================
    {
        "id": "zh-kennedys",
        "city": "zurich",
        "name": "Kennedy's Irish Pub",
        "category": "pub",
        "address": "Freischützgasse 14, 8004 Zürich, Switzerland",
        "lat": 47.3768,
        "lng": 8.5326,
        "googleRating": 4.5,
        "googleReviewCount": 2410,
        "priceLevel": "CHF ··",
        "website": "https://www.kennedys.ch",
        "menuUrl": "https://kennedys.ch/drinks",
        "phone": "+41 44 242 11 00",
        "openNow": True,
        "editorialSummary": "Authentic Irish pub & restaurant just steps from Zürich HB and Europaallee, renowned for its master-quality Guinness Draught pour.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:30:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)", "Guinness 0.0", "Black & Tan (Guinness + Kilkenny)"],
            "extractedPrice": "CHF 9.80",
            "snippets": [
                "DRAUGHT BEERS: Guinness Irish Dry Stout — 5dl Pint CHF 9.80 / 2.5dl CHF 5.50",
                "NON-ALCOHOLIC: Guinness 0.0 Draught Can — CHF 8.80",
                "PUB CLASSICS: Traditional Irish Lamb Stew braised in Guinness — CHF 28.50",
            ],
        },
        "reviewCheck": {
            "mentionCount": 412,
            "sentiment": "exceptional",
            "excerpts": [
                {
                    "author": "Lukas S.",
                    "rating": 5,
                    "date": "3 days ago",
                    "text": "Best pint of Guinness in Zurich. Proper two-part pour, cold and super creamy.",
                },
                {
                    "author": "Ciara O.",
                    "rating": 5,
                    "date": "2 weeks ago",
                    "text": "Even has Guinness 0.0 and great fish & chips. Always our go-to spot near Zürich HB.",
                },
            ],
        },
        "crowdCheck": {
            "confirmedCount": 39,
            "deniedCount": 0,
            "servingFormat": "draught",
            "reportedPrice": "CHF 9.80",
            "hasZero": True,
            "recentReports": [
                {
                    "id": "ch-101",
                    "user": "Rory M.",
                    "servingFormat": "draught",
                    "price": "CHF 9.80",
                    "note": "High turnover on the Guinness line, clean glasses, proper dome.",
                    "createdAt": "2026-11-05T20:15:00Z",
                }
            ],
        },
    },
    {
        "id": "zh-paddy-reillys",
        "city": "zurich",
        "name": "Paddy Reilly's Irish Pub & Restaurant",
        "category": "pub",
        "address": "Talstrasse 82, 8001 Zürich, Switzerland",
        "lat": 47.3712,
        "lng": 8.5356,
        "googleRating": 4.4,
        "googleReviewCount": 3180,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 43 497 31 20",
        "openNow": True,
        "editorialSummary": "Spacious Irish pub and kitchen in central Zurich pouring fresh Guinness Draught alongside live sports and full pub food menu.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:32:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)", "Guinness 0.0"],
            "extractedPrice": "CHF 9.50",
            "snippets": [
                "ON TAP: Guinness Draught (4.2%) — Imperial Pint CHF 9.50",
                "HOUSE SPECIAL: Homemade Steak & Guinness Pie with Champ Mash — CHF 27.50",
            ],
        },
        "reviewCheck": {
            "mentionCount": 530,
            "sentiment": "exceptional",
            "excerpts": [
                {
                    "author": "Marc B.",
                    "rating": 5,
                    "date": "5 days ago",
                    "text": "Reliable pint of Guinness on Talstrasse and the Steak & Guinness pie is delicious.",
                }
            ],
        },
        "crowdCheck": {
            "confirmedCount": 44,
            "deniedCount": 0,
            "servingFormat": "draught",
            "reportedPrice": "CHF 9.50",
            "hasZero": True,
            "recentReports": [],
        },
    },
    {
        "id": "zh-james-joyce",
        "city": "zurich",
        "name": "James Joyce Pub & Restaurant",
        "category": "bar",
        "address": "Pelikanstrasse 8, 8001 Zürich, Switzerland",
        "lat": 47.3715,
        "lng": 8.5378,
        "googleRating": 4.6,
        "googleReviewCount": 920,
        "priceLevel": "CHF ···",
        "website": "https://jamesjoyce.ch",
        "menuUrl": "https://jamesjoyce.ch/drinks-menu",
        "phone": "+41 44 221 18 28",
        "openNow": True,
        "editorialSummary": "Historic antique-wood bar near Bahnhofstrasse whose interior hails from Jury’s Antique Bar in Dublin (featured in James Joyce’s Ulysses).",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:15:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 10.20",
            "snippets": [
                "BIER VOM FASS / DRAUGHT: Guinness Irish Stout — 5dl CHF 10.20 | 3dl CHF 6.80",
            ],
        },
        "reviewCheck": {
            "mentionCount": 165,
            "sentiment": "positive",
            "excerpts": [
                {
                    "author": "Stefan W.",
                    "rating": 5,
                    "date": "1 week ago",
                    "text": "Drinking a pint of Guinness inside an authentic 19th-century Dublin bar right off Bahnhofstrasse is special.",
                }
            ],
        },
        "crowdCheck": {
            "confirmedCount": 22,
            "deniedCount": 0,
            "servingFormat": "draught",
            "reportedPrice": "CHF 10.20",
            "hasZero": False,
            "recentReports": [],
        },
    },
    {
        "id": "zh-baur-au-lac",
        "city": "zurich",
        "name": "Baur au Lac — Le Hall Bar",
        "category": "hotel",
        "address": "Talstrasse 1, 8001 Zürich, Switzerland",
        "lat": 47.3673,
        "lng": 8.5398,
        "googleRating": 4.8,
        "googleReviewCount": 1650,
        "priceLevel": "CHF ····",
        "website": "https://bauraulac.ch",
        "menuUrl": "https://bauraulac.ch/en/culinary/le-hall",
        "phone": "+41 44 220 50 20",
        "openNow": True,
        "editorialSummary": "Legendary 5-star luxury hotel beside Lake Zurich with an elegant lobby lounge and garden terrace.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:20:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught Surger / Can"],
            "extractedPrice": "CHF 13.50",
            "snippets": [
                "INTERNATIONAL BEERS: Guinness Draught — CHF 13.50 | Turbinenbräu Sprint — CHF 9.50",
            ],
        },
        "reviewCheck": {
            "mentionCount": 12,
            "sentiment": "positive",
            "excerpts": [
                {
                    "author": "David G.",
                    "rating": 5,
                    "date": "3 weeks ago",
                    "text": "Impeccable service in Le Hall—they even had cold Guinness available upon request.",
                }
            ],
        },
        "crowdCheck": {
            "confirmedCount": 5,
            "deniedCount": 0,
            "servingFormat": "cans_bottles",
            "reportedPrice": "CHF 13.50",
            "hasZero": False,
            "recentReports": [],
        },
    },
    {
        "id": "zh-zeughauskeller",
        "city": "zurich",
        "name": "Restaurant Zeughauskeller",
        "category": "restaurant",
        "address": "Bahnhofstrasse 28A, 8001 Zürich, Switzerland",
        "lat": 47.3702,
        "lng": 8.5396,
        "googleRating": 4.5,
        "googleReviewCount": 7420,
        "priceLevel": "CHF ··",
        "website": "https://zeughauskeller.ch",
        "menuUrl": "https://zeughauskeller.ch/en/food-and-drinks",
        "phone": "+41 44 220 15 15",
        "openNow": True,
        "editorialSummary": "Historic 1487 weapons armory at Paradeplatz serving traditional Swiss sausages, rösti, and local Swiss draught beers.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:25:00Z",
            "foundOnMenu": False,
            "typesFound": [],
            "extractedPrice": None,
            "snippets": [
                "OFFENBIER / DRAUGHT: Zeughauskeller Hausbier CHF 7.50 | Feldschlösschen Dunkel CHF 7.50 (No Guinness on menu)"
            ],
        },
        "reviewCheck": {
            "mentionCount": 0,
            "sentiment": "none",
            "excerpts": [],
        },
        "crowdCheck": {
            "confirmedCount": 0,
            "deniedCount": 6,
            "servingFormat": "none",
            "reportedPrice": None,
            "hasZero": False,
            "recentReports": [],
        },
    },
    # ================= GENEVA =================
    {
        "id": "ge-mr-pickwick",
        "city": "geneva",
        "name": "Mr. Pickwick Pub Geneva",
        "category": "pub",
        "address": "Rue de Lausanne 80, 1202 Genève, Switzerland",
        "lat": 46.2158,
        "lng": 6.1465,
        "googleRating": 4.4,
        "googleReviewCount": 2890,
        "priceLevel": "CHF ··",
        "website": "https://pickwick.ch",
        "menuUrl": "https://pickwick.ch/en/geneva/drinks",
        "phone": "+41 22 731 67 97",
        "openNow": True,
        "editorialSummary": "Opened in 1969 as Switzerland’s oldest English & Irish pub, pouring high-volume pints of Guinness Draught across two floors.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:35:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)", "Guinness 0.0"],
            "extractedPrice": "CHF 9.50",
            "snippets": [
                "DRAUGHT STOUT: Guinness Draught (4.2% ABV) — Pint 5dl CHF 9.50 / Half 2.5dl CHF 5.20",
                "ALCOHOL-FREE: Guinness 0.0 — CHF 8.50",
            ],
        },
        "reviewCheck": {
            "mentionCount": 380,
            "sentiment": "exceptional",
            "excerpts": [
                {
                    "author": "Pierre-Alain M.",
                    "rating": 5,
                    "date": "4 days ago",
                    "text": "A Geneva institution for watching rugby with a proper pint of Guinness.",
                }
            ],
        },
        "crowdCheck": {
            "confirmedCount": 34,
            "deniedCount": 0,
            "servingFormat": "draught",
            "reportedPrice": "CHF 9.50",
            "hasZero": True,
            "recentReports": [],
        },
    },
    {
        "id": "ge-mulligans",
        "city": "geneva",
        "name": "Mulligan's Irish Pub Geneva",
        "category": "pub",
        "address": "Rue de la Tour-Maîtresse 14, 1204 Genève, Switzerland",
        "lat": 46.2036,
        "lng": 6.1498,
        "googleRating": 4.5,
        "googleReviewCount": 1620,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 22 310 99 88",
        "openNow": True,
        "editorialSummary": "Lively Irish pub near Rive in central Geneva known for friendly Irish staff and well-kept Guinness taps.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:36:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 9.80",
            "snippets": ["BIÈRES PRESSION / ON TAP: Guinness Draught — Pint CHF 9.80"],
        },
        "reviewCheck": {
            "mentionCount": 295,
            "sentiment": "exceptional",
            "excerpts": [
                {
                    "author": "Aidan C.",
                    "rating": 5,
                    "date": "1 week ago",
                    "text": "Creamiest pint of Guinness in Geneva, poured properly in two stages.",
                }
            ],
        },
        "crowdCheck": {
            "confirmedCount": 29,
            "deniedCount": 0,
            "servingFormat": "draught",
            "reportedPrice": "CHF 9.80",
            "hasZero": True,
            "recentReports": [],
        },
    },
    {
        "id": "ge-angleterre",
        "city": "geneva",
        "name": "Hotel d'Angleterre — The Leopard Room Bar",
        "category": "hotel",
        "address": "Quai du Mont-Blanc 17, 1201 Genève, Switzerland",
        "lat": 46.2089,
        "lng": 6.1494,
        "googleRating": 4.7,
        "googleReviewCount": 940,
        "priceLevel": "CHF ····",
        "website": "https://dangleterrehotel.com",
        "menuUrl": "https://dangleterrehotel.com/dining-and-drinks/the-leopard-room-bar",
        "phone": "+41 22 906 55 55",
        "openNow": True,
        "editorialSummary": "Boutique 5-star hotel overlooking Lake Geneva and the Jet d’Eau with the British-inspired Leopard Room Bar.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:20:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Surger / Draught Can"],
            "extractedPrice": "CHF 14.00",
            "snippets": ["BEERS & CIDERS: Guinness Irish Stout — CHF 14.00"],
        },
        "reviewCheck": {
            "mentionCount": 18,
            "sentiment": "positive",
            "excerpts": [
                {
                    "author": "Charlotte R.",
                    "rating": 5,
                    "date": "2 weeks ago",
                    "text": "Cosy leather armchairs, live piano, and you can order a Guinness or single malt.",
                }
            ],
        },
        "crowdCheck": {
            "confirmedCount": 8,
            "deniedCount": 0,
            "servingFormat": "cans_bottles",
            "reportedPrice": "CHF 14.00",
            "hasZero": False,
            "recentReports": [],
        },
    },
    # ================= BASEL =================
    {
        "id": "bs-paddys",
        "city": "basel",
        "name": "Paddy's Irish Pub Basel",
        "category": "pub",
        "address": "Steinentorstrasse 45, 4051 Basel, Switzerland",
        "lat": 47.5515,
        "lng": 7.5878,
        "googleRating": 4.5,
        "googleReviewCount": 2540,
        "priceLevel": "CHF ··",
        "website": "https://paddys.ch",
        "menuUrl": "https://paddys.ch/drinks-menu",
        "phone": "+41 61 283 20 83",
        "openNow": True,
        "editorialSummary": "Basel’s flagship Irish pub and courtyard garden near Heuwaage & SBB station, pouring thousands of pints of Guinness weekly.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:30:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)", "Guinness 0.0", "Guinness Foreign Extra"],
            "extractedPrice": "CHF 9.60",
            "snippets": [
                "DRAUGHT: Guinness Irish Stout — Pint CHF 9.60 | Half Pint CHF 5.40",
                "ALCOHOL FREE: Guinness 0.0 — CHF 8.60",
            ],
        },
        "reviewCheck": {
            "mentionCount": 460,
            "sentiment": "exceptional",
            "excerpts": [
                {
                    "author": "Niall D.",
                    "rating": 5,
                    "date": "2 days ago",
                    "text": "Top quality Guinness in Basel. Clean lines and great atmosphere in the courtyard.",
                }
            ],
        },
        "crowdCheck": {
            "confirmedCount": 42,
            "deniedCount": 0,
            "servingFormat": "draught",
            "reportedPrice": "CHF 9.60",
            "hasZero": True,
            "recentReports": [],
        },
    },
    {
        "id": "bs-flanagans",
        "city": "basel",
        "name": "Flanagan's Irish Pub Basel",
        "category": "bar",
        "address": "Freie Strasse 103, 4051 Basel, Switzerland",
        "lat": 47.5542,
        "lng": 7.5904,
        "googleRating": 4.4,
        "googleReviewCount": 890,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 61 271 33 11",
        "openNow": True,
        "editorialSummary": "Welcoming Irish bar right on Freie Strasse in Basel Old Town serving Guinness Draught and pub snacks.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:10:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 9.50",
            "snippets": ["ON TAP: Guinness Draught — Pint CHF 9.50"],
        },
        "reviewCheck": {
            "mentionCount": 140,
            "sentiment": "positive",
            "excerpts": [
                {
                    "author": "Tobias K.",
                    "rating": 5,
                    "date": "6 days ago",
                    "text": "Great stop on Freie Strasse for a fresh pint of Guinness.",
                }
            ],
        },
        "crowdCheck": {
            "confirmedCount": 19,
            "deniedCount": 0,
            "servingFormat": "draught",
            "reportedPrice": "CHF 9.50",
            "hasZero": False,
            "recentReports": [],
        },
    },
    # ================= BERN =================
    {
        "id": "be-pickwick-bern",
        "city": "bern",
        "name": "Mr. Pickwick Pub Bern",
        "category": "pub",
        "address": "Wallgasse 8, 3011 Bern, Switzerland",
        "lat": 46.9472,
        "lng": 7.4426,
        "googleRating": 4.4,
        "googleReviewCount": 2150,
        "priceLevel": "CHF ··",
        "website": "https://pickwick.ch",
        "menuUrl": "https://pickwick.ch/en/bern/drinks",
        "phone": "+41 31 311 06 11",
        "openNow": True,
        "editorialSummary": "Traditional pub in the UNESCO Old Town of Bern pouring Guinness Draught and serving classic pub grub.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:30:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)", "Guinness 0.0"],
            "extractedPrice": "CHF 9.20",
            "snippets": [
                "DRAUGHT BEERS: Guinness Draught — Pint CHF 9.20",
                "NON-ALCOHOLIC: Guinness 0.0 — CHF 8.40",
            ],
        },
        "reviewCheck": {
            "mentionCount": 310,
            "sentiment": "exceptional",
            "excerpts": [
                {
                    "author": "Fabian H.",
                    "rating": 5,
                    "date": "3 days ago",
                    "text": "Always a well-poured Guinness and friendly service in central Bern.",
                }
            ],
        },
        "crowdCheck": {
            "confirmedCount": 31,
            "deniedCount": 0,
            "servingFormat": "draught",
            "reportedPrice": "CHF 9.20",
            "hasZero": True,
            "recentReports": [],
        },
    },
    {
        "id": "be-kornhauskeller",
        "city": "bern",
        "name": "Kornhauskeller Restaurant & Galerie Bar",
        "category": "restaurant",
        "address": "Kornhausplatz 18, 3011 Bern, Switzerland",
        "lat": 46.9488,
        "lng": 7.4475,
        "googleRating": 4.5,
        "googleReviewCount": 3120,
        "priceLevel": "CHF ···",
        "website": "https://kornhauskeller.ch",
        "menuUrl": "https://kornhauskeller.ch/bar-lounge",
        "phone": "+41 31 327 72 72",
        "openNow": True,
        "editorialSummary": "Magnificent vaulted baroque granary cellar in Bern with an upstairs cocktail & whiskey gallery bar.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:12:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Stout (Bottle/Can in Galerie Bar)"],
            "extractedPrice": "CHF 10.50",
            "snippets": ["GALERIE BAR BOTTLED STOUTS: Guinness — CHF 10.50"],
        },
        "reviewCheck": {
            "mentionCount": 15,
            "sentiment": "positive",
            "excerpts": [
                {
                    "author": "Reto L.",
                    "rating": 5,
                    "date": "3 weeks ago",
                    "text": "Stunning architecture; the upstairs gallery bar has a huge spirits & beer selection including Guinness.",
                }
            ],
        },
        "crowdCheck": {
            "confirmedCount": 6,
            "deniedCount": 0,
            "servingFormat": "cans_bottles",
            "reportedPrice": "CHF 10.50",
            "hasZero": False,
            "recentReports": [],
        },
    },
    # ================= LAUSANNE =================
    {
        "id": "ls-great-escape",
        "city": "lausanne",
        "name": "The Great Escape",
        "category": "bar",
        "address": "Rue de la Madeleine 18, 1003 Lausanne, Switzerland",
        "lat": 46.5224,
        "lng": 6.6335,
        "googleRating": 4.5,
        "googleReviewCount": 2940,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 21 312 14 26",
        "openNow": True,
        "editorialSummary": "Lausanne’s favorite Anglo-Swiss bar & terrace near Place de la Riponne, known for homemade burgers and fresh draught Guinness.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:30:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 9.50",
            "snippets": ["BIÈRES PRESSION / DRAUGHT: Guinness Irish Stout — 5dl CHF 9.50"],
        },
        "reviewCheck": {
            "mentionCount": 245,
            "sentiment": "exceptional",
            "excerpts": [
                {
                    "author": "Julien V.",
                    "rating": 5,
                    "date": "4 days ago",
                    "text": "Best terrace in Lausanne for a burger and a cold pint of Guinness on tap.",
                }
            ],
        },
        "crowdCheck": {
            "confirmedCount": 27,
            "deniedCount": 0,
            "servingFormat": "draught",
            "reportedPrice": "CHF 9.50",
            "hasZero": False,
            "recentReports": [],
        },
    },
    {
        "id": "ls-beau-rivage",
        "city": "lausanne",
        "name": "Beau-Rivage Palace — BAR",
        "category": "hotel",
        "address": "Chemin de Beau-Rivage 21, 1006 Lausanne, Switzerland",
        "lat": 46.5080,
        "lng": 6.6305,
        "googleRating": 4.8,
        "googleReviewCount": 1980,
        "priceLevel": "CHF ····",
        "website": "https://brp.ch",
        "menuUrl": "https://brp.ch/en/restaurants-bars/bars",
        "phone": "+41 21 613 33 33",
        "openNow": True,
        "editorialSummary": "Historic 5-star palace hotel on the shores of Lake Geneva in Ouchy with an acclaimed lounge bar.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:15:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Stout (Can/Bottle)"],
            "extractedPrice": "CHF 14.50",
            "snippets": ["INTERNATIONAL BEERS: Guinness — CHF 14.50"],
        },
        "reviewCheck": {
            "mentionCount": 9,
            "sentiment": "positive",
            "excerpts": [],
        },
        "crowdCheck": {
            "confirmedCount": 4,
            "deniedCount": 0,
            "servingFormat": "cans_bottles",
            "reportedPrice": "CHF 14.50",
            "hasZero": False,
            "recentReports": [],
        },
    },
    # ================= LUCERNE =================
    {
        "id": "lu-pickwick-luzern",
        "city": "lucerne",
        "name": "Mr. Pickwick Pub Luzern",
        "category": "pub",
        "address": "Rathausquai 6, 6004 Luzern, Switzerland",
        "lat": 47.0519,
        "lng": 8.3079,
        "googleRating": 4.4,
        "googleReviewCount": 1870,
        "priceLevel": "CHF ··",
        "website": "https://pickwick.ch",
        "menuUrl": "https://pickwick.ch/en/lucerne/drinks",
        "phone": "+41 41 410 59 27",
        "openNow": True,
        "editorialSummary": "Riverside pub on the Rathausquai overlooking the Chapel Bridge (Kapellbrücke) and Reuss river, pouring fresh Guinness Draught.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T08:30:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)", "Guinness 0.0"],
            "extractedPrice": "CHF 9.50",
            "snippets": [
                "DRAUGHT: Guinness Irish Stout — Pint CHF 9.50",
                "ALCOHOL-FREE: Guinness 0.0 — CHF 8.50",
            ],
        },
        "reviewCheck": {
            "mentionCount": 280,
            "sentiment": "exceptional",
            "excerpts": [
                {
                    "author": "Connor B.",
                    "rating": 5,
                    "date": "2 days ago",
                    "text": "Having a pint of Guinness right on the river looking at the Chapel Bridge and Mt Pilatus is unbeatable.",
                }
            ],
        },
        "crowdCheck": {
            "confirmedCount": 33,
            "deniedCount": 0,
            "servingFormat": "draught",
            "reportedPrice": "CHF 9.50",
            "hasZero": True,
            "recentReports": [],
        },
    },
    # ================= ADDITIONAL NATIONWIDE SWISS VENUES =================
    {
        "id": "zh-oliver-twist",
        "city": "zurich",
        "name": "Oliver Twist Pub",
        "category": "pub",
        "address": "Rindermarkt 6, 8001 Zürich (Niederdorf), Switzerland",
        "lat": 47.3728,
        "lng": 8.5446,
        "googleRating": 4.5,
        "googleReviewCount": 1940,
        "priceLevel": "CHF ··",
        "website": "https://pickwick.ch",
        "menuUrl": "https://pickwick.ch/en/zurich",
        "phone": "+41 44 252 47 10",
        "openNow": True,
        "editorialSummary": "Beloved Niederdorf Old Town pub with cosy snugs, courtyard seating, and high-turnover Guinness Draught lines.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:05:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)", "Guinness 0.0"],
            "extractedPrice": "CHF 9.60",
            "snippets": ["DRAUGHT STOUT: Guinness Draught 5dl — CHF 9.60 | Guinness 0.0 — CHF 8.60"],
        },
        "reviewCheck": {
            "mentionCount": 310,
            "sentiment": "exceptional",
            "excerpts": [{"author": "Patrick K.", "rating": 5, "date": "4 days ago", "text": "Best spot in Niederdorf for a pint of Guinness and fish & chips."}],
        },
        "crowdCheck": {
            "confirmedCount": 35,
            "deniedCount": 0,
            "servingFormat": "draught",
            "reportedPrice": "CHF 9.60",
            "hasZero": True,
            "recentReports": [],
        },
    },
    {
        "id": "zh-lion-pub",
        "city": "zurich",
        "name": "The Lion Pub",
        "category": "pub",
        "address": "Oetenbachgasse 26, 8001 Zürich, Switzerland",
        "lat": 47.3731,
        "lng": 8.5395,
        "googleRating": 4.5,
        "googleReviewCount": 1120,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 44 211 49 69",
        "openNow": True,
        "editorialSummary": "Classic Anglo-Irish pub tucked off Rennweg in central Zurich pouring Guinness Draught on tap.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:05:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 9.80",
            "snippets": ["ON TAP: Guinness Irish Stout — Pint CHF 9.80"],
        },
        "reviewCheck": {
            "mentionCount": 185,
            "sentiment": "positive",
            "excerpts": [],
        },
        "crowdCheck": {
            "confirmedCount": 24,
            "deniedCount": 0,
            "servingFormat": "draught",
            "reportedPrice": "CHF 9.80",
            "hasZero": False,
            "recentReports": [],
        },
    },
    {
        "id": "ge-flannagans",
        "city": "geneva",
        "name": "Flannagan's Irish Bar",
        "category": "bar",
        "address": "Rue du Cheval-Blanc 4, 1204 Genève (Vieille-Ville), Switzerland",
        "lat": 46.2011,
        "lng": 6.1489,
        "googleRating": 4.4,
        "googleReviewCount": 1180,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 22 310 20 88",
        "openNow": True,
        "editorialSummary": "Cobblestone Old Town Geneva Irish bar pouring Guinness Draught with a sunny terrace near St. Pierre Cathedral.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:10:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 9.50",
            "snippets": ["PRESSION: Guinness Irish Stout — Pint CHF 9.50"],
        },
        "reviewCheck": {"mentionCount": 210, "sentiment": "positive", "excerpts": []},
        "crowdCheck": {"confirmedCount": 21, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 9.50", "hasZero": False, "recentReports": []},
    },
    {
        "id": "ge-charly-oneills",
        "city": "geneva",
        "name": "Charly O'Neill's Irish Pub & Restaurant",
        "category": "restaurant",
        "address": "Rue Hoffmann 18, 1202 Genève, Switzerland",
        "lat": 46.2141,
        "lng": 6.1352,
        "googleRating": 4.5,
        "googleReviewCount": 1340,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 22 733 77 30",
        "openNow": True,
        "editorialSummary": "Traditional Irish pub & restaurant in Geneva Servette serving Guinness beef stew, burgers, and fresh Guinness Draught.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:10:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)", "Guinness 0.0"],
            "extractedPrice": "CHF 9.50",
            "snippets": [
                "DRAUGHT: Guinness — CHF 9.50 | Guinness 0.0 — CHF 8.50",
                "PLATS: Ragoût de Boeuf à la Guinness (Irish Beef & Guinness Stew) — CHF 26.00",
            ],
        },
        "reviewCheck": {"mentionCount": 260, "sentiment": "exceptional", "excerpts": []},
        "crowdCheck": {"confirmedCount": 25, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 9.50", "hasZero": True, "recentReports": []},
    },
    {
        "id": "ls-king-size",
        "city": "lausanne",
        "name": "King Size Pub Lausanne",
        "category": "pub",
        "address": "Rue Saint-Martin 16, 1003 Lausanne, Switzerland",
        "lat": 46.5231,
        "lng": 6.6368,
        "googleRating": 4.5,
        "googleReviewCount": 1860,
        "priceLevel": "CHF ··",
        "website": "https://kingsizepub.ch",
        "menuUrl": "https://kingsizepub.ch/bieres",
        "phone": "+41 21 311 48 88",
        "openNow": True,
        "editorialSummary": "One of Romandie’s largest pubs featuring 39 draught taps including dedicated Guinness Draught lines.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:12:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)", "Guinness Extra Stout (Bottle)"],
            "extractedPrice": "CHF 9.50",
            "snippets": ["PRESSION IRLANDE: Guinness Draught (4.2%) — 5dl CHF 9.50"],
        },
        "reviewCheck": {"mentionCount": 190, "sentiment": "exceptional", "excerpts": []},
        "crowdCheck": {"confirmedCount": 26, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 9.50", "hasZero": True, "recentReports": []},
    },
    {
        "id": "ls-mccarthys-vevey",
        "city": "lausanne",
        "name": "McCarthy's Irish Pub Vevey",
        "category": "pub",
        "address": "Rue des Deux-Marchés 17, 1800 Vevey, Switzerland",
        "lat": 46.4603,
        "lng": 6.8439,
        "googleRating": 4.6,
        "googleReviewCount": 780,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 21 922 74 44",
        "openNow": True,
        "editorialSummary": "Authentic lakeside-town Irish pub in Vevey pouring Guinness Draught on tap.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:12:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 9.20",
            "snippets": ["ON TAP: Guinness Draught — Pint CHF 9.20"],
        },
        "reviewCheck": {"mentionCount": 145, "sentiment": "exceptional", "excerpts": []},
        "crowdCheck": {"confirmedCount": 19, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 9.20", "hasZero": False, "recentReports": []},
    },
    {
        "id": "ls-barrel-oak-montreux",
        "city": "lausanne",
        "name": "Barrel Oak Pub Montreux",
        "category": "pub",
        "address": "Grand-Rue 92, 1820 Montreux, Switzerland",
        "lat": 46.4312,
        "lng": 6.9108,
        "googleRating": 4.5,
        "googleReviewCount": 910,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 21 963 14 14",
        "openNow": True,
        "editorialSummary": "Popular Montreux pub along the Grand-Rue pouring Guinness Draught and craft beers steps from Lake Geneva.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:12:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 9.50",
            "snippets": ["DRAUGHT BEERS: Guinness Irish Stout — Pint CHF 9.50"],
        },
        "reviewCheck": {"mentionCount": 130, "sentiment": "positive", "excerpts": []},
        "crowdCheck": {"confirmedCount": 16, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 9.50", "hasZero": False, "recentReports": []},
    },
    {
        "id": "bs-pickwick-basel",
        "city": "basel",
        "name": "Mr. Pickwick Pub Basel",
        "category": "pub",
        "address": "Steinenvorstadt 13, 4051 Basel, Switzerland",
        "lat": 47.5531,
        "lng": 7.5882,
        "googleRating": 4.4,
        "googleReviewCount": 1740,
        "priceLevel": "CHF ··",
        "website": "https://pickwick.ch",
        "menuUrl": "https://pickwick.ch/en/basel/drinks",
        "phone": "+41 61 281 40 04",
        "openNow": True,
        "editorialSummary": "Classic pub on Steinenvorstadt pouring fresh Guinness Draught and showing live football and rugby.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:12:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)", "Guinness 0.0"],
            "extractedPrice": "CHF 9.40",
            "snippets": ["DRAUGHT: Guinness Draught — Pint CHF 9.40 | Guinness 0.0 — CHF 8.40"],
        },
        "reviewCheck": {"mentionCount": 230, "sentiment": "exceptional", "excerpts": []},
        "crowdCheck": {"confirmedCount": 28, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 9.40", "hasZero": True, "recentReports": []},
    },
    {
        "id": "bs-trois-rois",
        "city": "basel",
        "name": "Grand Hotel Les Trois Rois — The Bar",
        "category": "hotel",
        "address": "Blumenrain 8, 4001 Basel, Switzerland",
        "lat": 47.5604,
        "lng": 7.5877,
        "googleRating": 4.8,
        "googleReviewCount": 1620,
        "priceLevel": "CHF ····",
        "website": "https://lestroisrois.com",
        "menuUrl": "https://lestroisrois.com/en/restaurants/bar",
        "phone": "+41 61 260 50 50",
        "openNow": True,
        "editorialSummary": "One of Europe’s oldest city hotels (1681) directly on the Rhine with an award-winning hotel bar.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:12:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Stout (Bottle/Can)"],
            "extractedPrice": "CHF 14.00",
            "snippets": ["BIERE / BEERS: Guinness Irish Stout — CHF 14.00"],
        },
        "reviewCheck": {"mentionCount": 11, "sentiment": "positive", "excerpts": []},
        "crowdCheck": {"confirmedCount": 5, "deniedCount": 0, "servingFormat": "cans_bottles", "reportedPrice": "CHF 14.00", "hasZero": False, "recentReports": []},
    },
    {
        "id": "bs-penny-farthing-aarau",
        "city": "basel",
        "name": "Penny Farthing Pub Aarau",
        "category": "pub",
        "address": "Bahnhofstrasse 36, 5000 Aarau, Switzerland",
        "lat": 47.3917,
        "lng": 8.0492,
        "googleRating": 4.5,
        "googleReviewCount": 690,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 62 824 55 55",
        "openNow": True,
        "editorialSummary": "Aargau’s favorite British & Irish pub on Bahnhofstrasse pouring fresh Guinness Draught.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:12:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 9.20",
            "snippets": ["VOM FASS: Guinness Draught 5dl — CHF 9.20"],
        },
        "reviewCheck": {"mentionCount": 95, "sentiment": "positive", "excerpts": []},
        "crowdCheck": {"confirmedCount": 14, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 9.20", "hasZero": False, "recentReports": []},
    },
    {
        "id": "be-mccarthys-bern",
        "city": "bern",
        "name": "McCarthy's Irish Pub Bern",
        "category": "pub",
        "address": "Aarbergergasse 61, 3011 Bern, Switzerland",
        "lat": 46.9502,
        "lng": 7.4408,
        "googleRating": 4.5,
        "googleReviewCount": 870,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 31 311 91 31",
        "openNow": True,
        "editorialSummary": "Atmospheric vaulted cellar Irish pub on Aarbergergasse in Bern pouring creamy Guinness Draught.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:14:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 9.40",
            "snippets": ["ON TAP: Guinness Irish Stout — Pint CHF 9.40"],
        },
        "reviewCheck": {"mentionCount": 205, "sentiment": "exceptional", "excerpts": []},
        "crowdCheck": {"confirmedCount": 26, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 9.40", "hasZero": True, "recentReports": []},
    },
    {
        "id": "lu-shamrock-luzern",
        "city": "lucerne",
        "name": "Shamrock Irish Pub Luzern",
        "category": "pub",
        "address": "Weggisgasse 19, 6004 Luzern, Switzerland",
        "lat": 47.0531,
        "lng": 8.3088,
        "googleRating": 4.5,
        "googleReviewCount": 960,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 41 410 73 73",
        "openNow": True,
        "editorialSummary": "Authentic Irish pub on Weggisgasse in Lucerne Old Town with live music and creamy Guinness Draught.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:15:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 9.40",
            "snippets": ["ON TAP: Guinness Draught — Pint CHF 9.40"],
        },
        "reviewCheck": {"mentionCount": 210, "sentiment": "exceptional", "excerpts": []},
        "crowdCheck": {"confirmedCount": 24, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 9.40", "hasZero": False, "recentReports": []},
    },
    {
        "id": "lu-pickwick-zug",
        "city": "lucerne",
        "name": "Mr. Pickwick Pub Zug",
        "category": "pub",
        "address": "Alpenstrasse 11, 6300 Zug, Switzerland",
        "lat": 47.1715,
        "lng": 8.5152,
        "googleRating": 4.4,
        "googleReviewCount": 1290,
        "priceLevel": "CHF ··",
        "website": "https://pickwick.ch",
        "menuUrl": "https://pickwick.ch/en/zug/drinks",
        "phone": "+41 41 711 75 22",
        "openNow": True,
        "editorialSummary": "Popular expat and local pub near Zug train station and Lake Zug, pouring fresh Guinness Draught.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:15:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)", "Guinness 0.0"],
            "extractedPrice": "CHF 9.50",
            "snippets": ["DRAUGHT: Guinness Draught — Pint CHF 9.50 | Guinness 0.0 — CHF 8.50"],
        },
        "reviewCheck": {"mentionCount": 225, "sentiment": "exceptional", "excerpts": []},
        "crowdCheck": {"confirmedCount": 29, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 9.50", "hasZero": True, "recentReports": []},
    },
    {
        "id": "lu-rathaus-brauerei",
        "city": "lucerne",
        "name": "Rathaus Brauerei Luzern",
        "category": "restaurant",
        "address": "Unter der Egg 2, 6004 Luzern, Switzerland",
        "lat": 47.0518,
        "lng": 8.3065,
        "googleRating": 4.6,
        "googleReviewCount": 2450,
        "priceLevel": "CHF ··",
        "website": "https://rathausbrauerei.ch",
        "menuUrl": "https://rathausbrauerei.ch/speisekarte",
        "phone": "+41 41 410 52 57",
        "openNow": True,
        "editorialSummary": "Historic riverside microbrewery & Swiss restaurant under the Lucerne Town Hall brewing its own Rathaus Bier.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:15:00Z",
            "foundOnMenu": False,
            "typesFound": [],
            "extractedPrice": None,
            "snippets": ["HAUSGEBRAUTE BIERE: Rathaus Naturtrüb & Rathaus Dunkel (No Guinness served — house brewery only)"],
        },
        "reviewCheck": {"mentionCount": 0, "sentiment": "none", "excerpts": []},
        "crowdCheck": {"confirmedCount": 0, "deniedCount": 5, "servingFormat": "none", "reportedPrice": None, "hasZero": False, "recentReports": []},
    },
    {
        "id": "ea-einstein-stgallen",
        "city": "east",
        "name": "Hotel Einstein St. Gallen — Einstein Bar",
        "category": "hotel",
        "address": "Berneggstrasse 2, 9000 St. Gallen, Switzerland",
        "lat": 47.4222,
        "lng": 9.3775,
        "googleRating": 4.7,
        "googleReviewCount": 1410,
        "priceLevel": "CHF ···",
        "website": "https://einstein.ch",
        "menuUrl": "https://einstein.ch/de/gastronomie/einstein-bar",
        "phone": "+41 71 227 55 55",
        "openNow": True,
        "editorialSummary": "First-class hotel beside the St. Gallen Abbey District featuring a classic wood-paneled cigar & whiskey lounge bar.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:16:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Stout (Bottle/Can)"],
            "extractedPrice": "CHF 11.50",
            "snippets": ["INTERNATIONAL BEERS: Guinness — CHF 11.50"],
        },
        "reviewCheck": {"mentionCount": 14, "sentiment": "positive", "excerpts": []},
        "crowdCheck": {"confirmedCount": 6, "deniedCount": 0, "servingFormat": "cans_bottles", "reportedPrice": "CHF 11.50", "hasZero": False, "recentReports": []},
    },
    {
        "id": "al-brown-cow-zermatt",
        "city": "alps",
        "name": "Brown Cow Pub — Unique Hotel Post Zermatt",
        "category": "hotel",
        "address": "Bahnhofstrasse 41, 3920 Zermatt, Switzerland",
        "lat": 46.0218,
        "lng": 7.7481,
        "googleRating": 4.5,
        "googleReviewCount": 1680,
        "priceLevel": "CHF ··",
        "website": "https://hotelpost.ch",
        "menuUrl": "https://hotelpost.ch/en/eat-drink/brown-cow-pub",
        "phone": "+41 27 967 19 31",
        "openNow": True,
        "editorialSummary": "Iconic Zermatt après-ski pub inside Unique Hotel Post on Bahnhofstrasse, pouring fresh Guinness Draught at the foot of the Matterhorn.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:18:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 9.80",
            "snippets": ["DRAUGHT BEERS: Guinness Irish Stout — Pint CHF 9.80"],
        },
        "reviewCheck": {
            "mentionCount": 240,
            "sentiment": "exceptional",
            "excerpts": [{"author": "Callum R.", "rating": 5, "date": "3 days ago", "text": "Nothing beats a cold pint of Guinness at the Brown Cow after skiing down from Gornergrat."}],
        },
        "crowdCheck": {"confirmedCount": 31, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 9.80", "hasZero": False, "recentReports": []},
    },
    {
        "id": "al-victoria-jungfrau",
        "city": "alps",
        "name": "Victoria-Jungfrau Grand Hotel & Spa — Victoria Bar",
        "category": "hotel",
        "address": "Höheweg 41, 3800 Interlaken, Switzerland",
        "lat": 46.6858,
        "lng": 7.8559,
        "googleRating": 4.8,
        "googleReviewCount": 2240,
        "priceLevel": "CHF ····",
        "website": "https://victoria-jungfrau.ch",
        "menuUrl": "https://victoria-jungfrau.ch/en/restaurants-bars/victoria-bar",
        "phone": "+41 33 828 28 28",
        "openNow": True,
        "editorialSummary": "5-star grand hotel in Interlaken facing the Jungfrau massif with the classic Victoria Bar & terrace.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:18:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Stout (Bottle/Can)"],
            "extractedPrice": "CHF 14.00",
            "snippets": ["BEERS: Guinness Irish Stout — CHF 14.00"],
        },
        "reviewCheck": {"mentionCount": 12, "sentiment": "positive", "excerpts": []},
        "crowdCheck": {"confirmedCount": 6, "deniedCount": 0, "servingFormat": "cans_bottles", "reportedPrice": "CHF 14.00", "hasZero": False, "recentReports": []},
    },
    {
        "id": "al-ex-bar-davos",
        "city": "alps",
        "name": "Ex Bar Davos",
        "category": "bar",
        "address": "Promenade 63, 7270 Davos Platz, Switzerland",
        "lat": 46.7985,
        "lng": 9.8242,
        "googleRating": 4.5,
        "googleReviewCount": 890,
        "priceLevel": "CHF ··",
        "website": None,
        "phone": "+41 81 413 55 88",
        "openNow": True,
        "editorialSummary": "Legendary Davos Promenade pub & restaurant pouring Guinness Draught and serving burgers since 1974.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:18:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 9.50",
            "snippets": ["DRAUGHT: Guinness Irish Stout — Pint CHF 9.50"],
        },
        "reviewCheck": {"mentionCount": 115, "sentiment": "positive", "excerpts": []},
        "crowdCheck": {"confirmedCount": 17, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 9.50", "hasZero": False, "recentReports": []},
    },
    {
        "id": "al-bobbys-stmoritz",
        "city": "alps",
        "name": "Bobby's Pub St. Moritz",
        "category": "pub",
        "address": "Via dal Bagn 52, 7500 St. Moritz, Switzerland",
        "lat": 46.4892,
        "lng": 9.8378,
        "googleRating": 4.5,
        "googleReviewCount": 720,
        "priceLevel": "CHF ···",
        "website": None,
        "phone": "+41 81 833 47 67",
        "openNow": True,
        "editorialSummary": "Engadin valley’s go-to pub in St. Moritz Bad pouring fresh Guinness Draught on tap.",
        "menuCheck": {
            "checked": True,
            "lastChecked": "2026-11-06T09:18:00Z",
            "foundOnMenu": True,
            "typesFound": ["Guinness Draught (On Tap)"],
            "extractedPrice": "CHF 10.50",
            "snippets": ["ON TAP: Guinness Draught — Pint CHF 10.50"],
        },
        "reviewCheck": {"mentionCount": 98, "sentiment": "positive", "excerpts": []},
        "crowdCheck": {"confirmedCount": 15, "deniedCount": 0, "servingFormat": "draught", "reportedPrice": "CHF 10.50", "hasZero": False, "recentReports": []},
    },
]


_BACKEND = None


def get_backend():
    """The active storage backend (file locally; Redis/KV when configured; see storage.py)."""
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = storage.build_backend(os.environ, STORE_PATH, BUNDLED_STORE_PATH, ON_VERCEL)
    return _BACKEND


def load_store():
    return get_backend().load()


def save_store(store):
    """Persist the whole local store (derived venue cache). Community writes use add_* below."""
    get_backend().save(store)


# (max requests, window seconds) per client IP. Override with the env vars in .env.example.
# Separate budgets so cheap actions (the UI's "scan all" button calls scan-menu once per venue) are not
# throttled by the tight limits on expensive or billed ones.
RATE_WRITES = (int(os.environ.get("RATE_LIMIT_WRITES_PER_HOUR", "10")), 3600)  # reports, new venues
RATE_SCANS = (int(os.environ.get("RATE_LIMIT_SCANS_PER_10MIN", "120")), 600)  # menu scans, small OSM lookups
RATE_GOOGLE = (int(os.environ.get("RATE_LIMIT_GOOGLE_PER_10MIN", "15")), 600)  # anything that calls Google Places
RATE_HEAVY = (int(os.environ.get("RATE_LIMIT_HEAVY_PER_10MIN", "3")), 600)  # nationwide Overpass scan


def get_rate_limiter():
    return guard.RateLimiter(get_backend(), enabled=os.environ.get("RATE_LIMIT_DISABLED") != "1")


def server_google_key_allowed():
    """The server's own Google key may serve anonymous visitors locally, but on a public (Vercel)
    deployment only when explicitly enabled - otherwise anyone could spend your Google quota."""
    return (not ON_VERCEL) or os.environ.get("ALLOW_PUBLIC_GOOGLE_LIVE") == "1"


def browser_maps_key():
    """The key that is deliberately sent to browsers (map tiles). It must be a *browser* key
    restricted to your site's referrers; it is never used for server-side Places calls.
    On a public deployment only GOOGLE_MAPS_BROWSER_KEY is ever exposed; the legacy
    GOOGLE_MAPS_API_KEY name is honoured for local development only."""
    key = os.environ.get("GOOGLE_MAPS_BROWSER_KEY", "")
    if not key and not ON_VERCEL:
        key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    return key


def deployment_info():
    """Which build is serving this request. None of it is secret (the repository is public), and it
    lets you check that a git push really went live: compare ``commit`` with the commit you pushed
    (see scripts/check_deploy.py). Values come from variables Vercel sets for every deployment;
    anything malformed is dropped so a bad value can never reach clients."""
    sha = os.environ.get("VERCEL_GIT_COMMIT_SHA", "").strip().lower()
    ref = os.environ.get("VERCEL_GIT_COMMIT_REF", "").strip()
    env = os.environ.get("VERCEL_ENV", "").strip()
    valid_sha = bool(re.fullmatch(r"[0-9a-f]{7,40}", sha))
    return {
        "commit": sha if valid_sha else None,
        "commitShort": sha[:7] if valid_sha else None,
        "branch": ref if re.fullmatch(r"[A-Za-z0-9_./\-]{1,100}", ref) else None,
        "environment": env if env in ("production", "preview", "development") else ("unknown" if ON_VERCEL else "local"),
    }


def resolve_places_key(headers):
    """Key for a server-side Google Places call: the visitor's own key (their quota), else the
    server key if allowed. Returns "" when no key may be used."""
    own = (headers.get("x-google-maps-key") or "").strip()
    if own:
        return own if len(own) <= 100 and own.isprintable() else ""
    if server_google_key_allowed():
        key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
        if not key and not ON_VERCEL:
            key = os.environ.get("GOOGLE_MAPS_API_KEY", "")  # legacy single-key local setups
        return key
    return ""


CRAWL_RESULTS_PATH = os.path.join(ROOT_DIR, "server", "data", "swiss_crawl_results.json")


def load_crawl_venues():
    if os.path.exists(CRAWL_RESULTS_PATH):
        try:
            with open(CRAWL_RESULTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return (data.get("confirmedVenues") or []) + (data.get("verifiedNoGuinnessSample") or [])
        except Exception:
            pass
    return []


def load_starter_checks():
    """What the crawler really read on the starter-list venues' own websites, keyed by venue id (see evidence.apply_site_check)."""
    if os.path.exists(CRAWL_RESULTS_PATH):
        try:
            with open(CRAWL_RESULTS_PATH, "r", encoding="utf-8") as f:
                checks = json.load(f).get("starterChecks")
                return checks if isinstance(checks, dict) else {}
        except Exception:
            pass
    return {}


def load_crawl_stats():
    if os.path.exists(CRAWL_RESULTS_PATH):
        try:
            with open(CRAWL_RESULTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("stats") or {}
        except Exception:
            pass
    return {}


def distance_km(lat1, lng1, lat2, lng2):
    try:
        p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
        h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(float(lng2) - float(lng1)) / 2) ** 2
        return 2 * 6371.0088 * math.asin(math.sqrt(h))
    except (TypeError, ValueError):
        return 0.0


def drop_pint_score(venue):
    """The pint score was removed. Venues saved before that (a community venue in the database, the crawl file) may still
    carry an average rating; it is never served."""
    cc = venue.get("crowdCheck") if isinstance(venue, dict) else None
    if isinstance(cc, dict) and "avgPintRating" in cc:
        return {**venue, "crowdCheck": {k: val for k, val in cc.items() if k != "avgPintRating"}}
    return venue


def place_community_venue(venue, locations):
    """A community venue re-placed from its address (see /api/relocate-venue) uses the stored position."""
    loc = (locations or {}).get(venue.get("id")) if isinstance(venue, dict) else None
    if loc:
        return {**venue, "lat": loc["lat"], "lng": loc["lng"]}
    return venue


def fix_legacy_community_venue(venue):
    """Community venues saved before the evidence clean-up carry an invented 4.7 Google rating and one
    invented review mention. Drop exactly those values; real visitor reports (crowdCheck) stay."""
    if not isinstance(venue, dict):
        return venue
    v = dict(venue)
    if v.get("googleRating") == 4.7 and v.get("googleReviewCount") == 1:
        v["googleRating"], v["googleReviewCount"] = None, 0
    if (v.get("reviewCheck") or {}).get("mentionCount") == 1 and not (v["reviewCheck"].get("excerpts")):
        v["reviewCheck"] = evidence.no_reviews()
    if v.get("priceLevel") == "CHF ··":
        v["priceLevel"] = None
    return v


def get_all_combined_venues(store):
    # The bundled files were generated with invented ratings, counts and quotes: strip them (see evidence.py).
    crawl_venues = [evidence.sanitise_static_venue(v) for v in load_crawl_venues()]
    starter_checks = load_starter_checks()
    starter_venues = [
        evidence.apply_site_check(evidence.sanitise_static_venue(v), starter_checks.get(v.get("id")) if isinstance(v, dict) else None)
        for v in DEMO_VENUES
    ]
    raw_list = (
        [place_community_venue(fix_legacy_community_venue(v), store.get("venueLocations")) for v in (store.get("customVenues") or [])]
        + (store.get("googleMapsVenues") or [])
        + starter_venues
        + crawl_venues
    )
    seen_ids = set()
    seen_names = set()
    deduped = []
    for v in raw_list:
        if not v or not v.get("id"):
            continue
        v = drop_pint_score(v)
        norm_key = f"{(v.get('name') or '').strip().lower()}::{(v.get('city') or '').strip().lower()}"
        if v["id"] in seen_ids or norm_key in seen_names:
            continue
        seen_ids.add(v["id"])
        seen_names.add(norm_key)
        if not v.get("googleMapsUri"):
            v["googleMapsUri"] = (
                "https://www.google.com/maps/search/?api=1&query="
                + urllib.parse.quote_plus(f"{v.get('name', '')} {v.get('address', 'Switzerland')}")
            )
        v["googleMapsChecked"] = True
        deduped.append(v)
    return deduped


def upsert_gmaps_venues_into_store(store, new_venues):
    existing = store.get("googleMapsVenues") or []
    by_id = {v["id"]: v for v in existing if v and v.get("id")}
    for v in new_venues or []:
        if v and v.get("id"):
            by_id[v["id"]] = v
    store["googleMapsVenues"] = list(by_id.values())
    save_store(store)


def parse_google_maps_url_or_query(raw_input):
    raw = (raw_input or "").strip()
    if not raw:
        return {"name": "", "lat": None, "lng": None, "isUrl": False, "rawQuery": ""}
    is_url = bool(re.match(r"^https?://(www\.)?(google\.[a-z.]+/maps|maps\.app\.goo\.gl|goo\.gl/maps)", raw, re.I))
    lat, lng = None, None
    m_coord = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", raw) or re.search(r"[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)", raw)
    if m_coord:
        lat, lng = float(m_coord.group(1)), float(m_coord.group(2))
    extracted_name = ""
    m_place = re.search(r"/maps/place/([^/@?]+)", raw, re.I)
    if m_place:
        extracted_name = urllib.parse.unquote_plus(m_place.group(1)).strip()
    elif not is_url:
        extracted_name = raw
    return {
        "name": extracted_name,
        "lat": lat,
        "lng": lng,
        "isUrl": is_url,
        "rawQuery": extracted_name or raw,
    }


def compute_guinness_status(venue):
    """How sure are we that a venue serves Guinness, and on what evidence.

    Confirmed needs real evidence: a website that says so (with serving wording), two visitor reports, or
    five Google review mentions. One mention, one report, an OpenStreetMap tag or an Irish-sounding name
    only make a venue "likely". Each label says which of those it is, so a guess never reads as a fact.
    """
    menu = venue.get("menuCheck") or {}
    menu_found = bool(menu.get("foundOnMenu"))
    menu_checked = bool(menu.get("checked"))
    review_mentions = (venue.get("reviewCheck") or {}).get("mentionCount", 0) or 0
    crowd = venue.get("crowdCheck") or {}
    crowd_confirmed = crowd.get("confirmedCount", 0) or 0
    crowd_denied = crowd.get("deniedCount", 0) or 0
    tag = (venue.get("tagCheck") or {}).get("kind")
    serving_format = crowd.get("servingFormat") or "unknown"

    menu_text = " ".join((menu.get("snippets") or []) + (menu.get("typesFound") or []))
    menu_says_draught = bool(evidence.DRAUGHT_RE.search(menu_text))
    menu_says_cans = bool(evidence.CAN_RE.search(menu_text)) and not menu_says_draught
    # How it is served is only ever what a visitor reported or the website said, never assumed.
    if serving_format in ("draught", "cans_bottles"):
        known_format = serving_format
    elif menu_found and menu_says_draught:
        known_format = "draught"
    elif menu_found and menu_says_cans:
        known_format = "cans_bottles"
    else:
        known_format = "unknown"

    # Negative: only when nothing points the other way. A website that does not mention Guinness is not proof
    # that none is served, so that case says exactly that and stays at modest confidence.
    if not menu_found and crowd_confirmed == 0 and review_mentions == 0 and not tag and (crowd_denied >= 3 or menu_checked):
        reported = crowd_denied >= 3
        return {
            "status": "no_guinness",
            "statusLabel": "No Guinness found",
            "reason": "Visitors say it isn't served" if reported else "Its website doesn't mention Guinness",
            "confidence": 85 if reported else 60,
            "servingFormat": "none",
        }

    score = 0
    if menu_found:
        score += 55
    if review_mentions > 0:
        score += min(30, 12 + math.log10(review_mentions + 1) * 10)
    if crowd_confirmed > 0:
        score += min(25, 10 + crowd_confirmed * 2)
    confidence = min(99, int(round(score)))

    # Wording shown to visitors: a short tier ("Confirmed", "Possible", ...) and, separately, the reason.
    if menu_found or crowd_confirmed >= 2 or review_mentions >= 5:
        if known_format == "cans_bottles":
            status, label = "cans_or_bottles", "Confirmed (cans / bottles)"
            reason = "Its website says cans or bottles" if menu_found and menu_says_cans else "Visitors report cans or bottles"
        elif known_format == "draught":
            status, label = "confirmed_draught", "Confirmed"
            if menu_found and menu_says_draught:
                reason = "Its website lists Guinness on tap"
            elif menu_found:
                reason = "Its website mentions Guinness and a visitor reports it on tap"
            else:
                reason = "Visitors report it on tap"
        else:
            status, label = "confirmed_draught", "Confirmed"
            reason = (
                "Its website mentions Guinness" if menu_found
                else "Reported by several visitors" if crowd_confirmed >= 2
                else "Mentioned in several Google reviews"
            )
        return {"status": status, "statusLabel": label, "reason": reason, "confidence": max(78, confidence), "servingFormat": known_format}

    def possible(reason, conf, fmt="unknown"):
        return {"status": "likely_serves", "statusLabel": "Possible", "reason": reason, "confidence": conf, "servingFormat": fmt}

    if review_mentions >= 1:
        return possible("Mentioned in a Google review", max(55, confidence), known_format)
    if crowd_confirmed == 1:
        return possible("Reported by 1 visitor", max(55, confidence), known_format)
    if tag == evidence.TAG_OSM:
        return possible("OpenStreetMap lists Guinness here (not checked)", 50)
    if tag == evidence.TAG_WEB:
        return possible("Its website mentions Guinness (not clearly on a menu)", 45)
    if tag == evidence.TAG_NAME:
        return possible("Irish-sounding name (not checked)", 35)
    if tag == evidence.TAG_STARTER:
        return possible("On our list of Irish pubs (not checked)", 35)

    return {
        "status": "unverified",
        "statusLabel": "Not checked yet",
        "reason": "No information about Guinness here yet",
        "confidence": max(15, confidence),
        "servingFormat": "unknown",
    }


def enrich_venue(venue, store):
    v = json.loads(json.dumps(venue))
    vid = v["id"]
    if vid in store.get("menuScans", {}):
        v["menuCheck"] = {**v.get("menuCheck", {}), **store["menuScans"][vid]}

    saved_reports = store.get("crowdReports", {}).get(vid, [])
    if saved_reports:
        cc = v.get("crowdCheck", {})
        pos = [r for r in saved_reports if r.get("servingFormat") != "none"]
        neg = [r for r in saved_reports if r.get("servingFormat") == "none"]
        confirmed = (cc.get("confirmedCount") or 0) + len(pos)
        denied = (cc.get("deniedCount") or 0) + len(neg)
        latest_format = saved_reports[0].get("servingFormat") or cc.get("servingFormat") or "draught"
        latest_price = next((r.get("price") for r in saved_reports if r.get("price")), cc.get("reportedPrice"))
        has_zero = any(r.get("hasZero") for r in saved_reports) or bool(cc.get("hasZero"))

        v["crowdCheck"] = {
            "confirmedCount": confirmed,
            "deniedCount": denied,
            "servingFormat": latest_format,
            "reportedPrice": latest_price,
            "hasZero": has_zero,
            # (stored reports from before the pint score was removed may still carry a rating: it is not served)
            "recentReports": [{k: val for k, val in r.items() if k != "pintRating"} for r in (saved_reports + (cc.get("recentReports") or []))[:8]],
        }

    v["guinnessSummary"] = compute_guinness_status(v)
    return v


# Tests point this at a local server; production never sets it (see guard.fetch_page).
FETCH_ALLOW_PRIVATE = False


def _not_scanned(now_iso, reason):
    return {
        "checked": False,
        "lastChecked": now_iso,
        "foundOnMenu": False,
        "typesFound": [],
        "extractedPrice": None,
        "snippets": [f"Menu URL not scanned: {reason}."],
    }


def clean_public_url(value):
    """A website taken from third-party data. OpenStreetMap tags can be edited by anyone, so keep a
    value only if it is a plain http(s) URL (normalised, e.g. "www.pub.ch" -> "https://www.pub.ch");
    otherwise None. Rendering is protected too (safeHttpUrl in the UIs); this keeps junk out of storage."""
    try:
        return guard.normalize_http_url(value) if value else None
    except guard.UnsafeURL:
        return None


def fill_from_overture(name, lat, lng, website, menu_url, phone):
    """OpenStreetMap often has no website for a venue. Borrow it from the bundled Overture Maps extract
    when the same venue is there (similar name, within ~75 m); see overture.py.
    Returns (website, menu_url, phone, website_source) where website_source is "openstreetmap",
    "overture" or None."""
    if website:
        return website, menu_url, phone, "openstreetmap"
    hit = overture.find_match(name, lat, lng)
    if not hit:
        return website, menu_url, phone, None
    return hit["website"], menu_url or hit["website"], phone or hit.get("phone"), "overture"


def scrape_menu_url(url, existing_check=None):
    """Fetch a venue's website/menu page and look for Guinness.

    All fetching goes through ``guard.fetch_page``: only public http(s) hosts are contacted
    (also on redirects), downloads are size- and time-limited. Unsafe URLs are reported as
    "not scanned" rather than as a negative result.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    if not url:
        return {
            "checked": False,
            "lastChecked": now_iso,
            "foundOnMenu": False,
            "typesFound": [],
            "extractedPrice": None,
            "snippets": ["No website URL provided."],
        }
    try:
        url = guard.normalize_http_url(url)
    except guard.UnsafeURL as exc:
        return _not_scanned(now_iso, str(exc))
    try:
        try:
            html = guard.fetch_page(url, timeout=5, allow_private=FETCH_ALLOW_PRIVATE)
        except guard.UnsafeURL as exc:
            if not isinstance(exc, guard.CouldNotResolve):
                raise  # a private or malformed address is never retried
            alt = guard.other_host_form(url)
            if not alt:
                raise
            html = guard.fetch_page(alt, timeout=5, allow_private=FETCH_ALLOW_PRIVATE)
            url = alt
        except Exception:
            # Never call a site unreachable before trying its other form (with / without "www.").
            alt = guard.other_host_form(url)
            if not alt:
                raise
            html = guard.fetch_page(alt, timeout=5, allow_private=FETCH_ALLOW_PRIVATE)
            url = alt
        text_lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in re.sub(r"<[^>]+>", "\n", html).splitlines()
            if len(line.strip()) > 3
        ]
        snippets = [ln[:180] for ln in text_lines if re.search(r"guinness", ln, re.I)][:5]
        found = len(snippets) > 0
        return {
            "checked": True,
            "lastChecked": now_iso,
            "foundOnMenu": found,
            "typesFound": evidence.serving_types(snippets) if found else [],
            "extractedPrice": evidence.price_near_guinness(snippets) if found else None,
            "snippets": snippets
            if found
            else [f"Scanned {url} — no explicit 'Guinness' text found on public HTML page."],
        }
    except guard.UnsafeURL as exc:
        return _not_scanned(now_iso, str(exc))
    except Exception:
        if existing_check and existing_check.get("checked"):
            return {**existing_check, "lastChecked": now_iso}
        # We could not read the page: that is "unknown", never "no Guinness".
        return _not_scanned(now_iso, f"could not read {url}")


def fetch_google_places_live(api_key, lat, lng, radius=3500, scrape_menus=True, query="", city="all"):
    nearby_url = "https://places.googleapis.com/v1/places:searchNearby"
    text_url = "https://places.googleapis.com/v1/places:searchText"
    field_mask = ",".join([
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.types",
        "places.primaryType",
        "places.rating",
        "places.userRatingCount",
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
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-Maps-Solution-ID": "gmp_git_agentskills_v1",
        "X-Goog-FieldMask": field_mask,
    }
    discovered = {}

    if query and query.strip():
        parsed_q = parse_google_maps_url_or_query(query)
        c_lat = parsed_q["lat"] if parsed_q["lat"] is not None else float(lat)
        c_lng = parsed_q["lng"] if parsed_q["lng"] is not None else float(lng)
        body = {
            "textQuery": parsed_q["rawQuery"],
            "maxResultCount": 20,
            "locationBias": {
                "circle": {
                    "center": {"latitude": float(c_lat), "longitude": float(c_lng)},
                    "radius": float(radius or 5000),
                }
            },
        }
        req = urllib.request.Request(text_url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=9) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for p in data.get("places", []):
                if p.get("id"):
                    discovered[p["id"]] = p
    else:
        nearby_payload = json.dumps({
            "includedTypes": [
                "pub",
                "bar",
                "wine_bar",
                "night_club",
                "restaurant",
                "cafe",
                "hotel",
                "resort_hotel",
                "lodging",
            ],
            "maxResultCount": 20,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": float(lat), "longitude": float(lng)},
                    "radius": float(radius),
                }
            },
        }).encode("utf-8")
        try:
            req = urllib.request.Request(nearby_url, data=nearby_payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for p in data.get("places", []):
                    if p.get("id"):
                        discovered[p["id"]] = p
        except Exception:
            pass

        for text_q in ["Guinness pub bar restaurant hotel", "bars pubs restaurants"]:
            try:
                t_payload = json.dumps({
                    "textQuery": text_q,
                    "maxResultCount": 20,
                    "locationBias": {
                        "circle": {
                            "center": {"latitude": float(lat), "longitude": float(lng)},
                            "radius": float(radius),
                        }
                    },
                }).encode("utf-8")
                req_t = urllib.request.Request(text_url, data=t_payload, headers=headers, method="POST")
                with urllib.request.urlopen(req_t, timeout=8) as resp_t:
                    t_data = json.loads(resp_t.read().decode("utf-8"))
                    for p in t_data.get("places", []):
                        if p.get("id"):
                            discovered[p["id"]] = p
            except Exception:
                pass

    venues = []
    for p in discovered.values():
        name = p.get("displayName", {}).get("text", "Venue")
        types = [t.lower() for t in (p.get("types", []) + ([p["primaryType"]] if p.get("primaryType") else []))]
        if any(t in types for t in ("lodging", "hotel", "resort_hotel")) or "hotel" in name.lower():
            category = "hotel"
        elif "pub" in types or "pub" in name.lower() or "tavern" in name.lower():
            category = "pub"
        elif any(t in types for t in ("bar", "wine_bar", "night_club")) or "bar" in name.lower():
            category = "bar"
        else:
            category = "restaurant"

        editorial = p.get("editorialSummary", {}).get("text", "")
        gen_sum = (p.get("generativeSummary", {}).get("overview") or {}).get("text", "")
        rev_sum = (p.get("reviewSummary", {}).get("text") or {}).get("text", "")
        reviews = p.get("reviews", [])
        excerpts = []
        mentions = 0
        for s_txt, s_lbl in [
            (editorial, "Google Maps Editorial Summary"),
            (gen_sum, "Google Maps Place Overview"),
            (rev_sum, "Google Maps Review Summary"),
        ]:
            if s_txt and re.search(r"\bguinness\b", s_txt, re.I):
                mentions += 1  # a Google summary that names Guinness counts once, not as several reviews
                excerpts.append({"author": s_lbl, "rating": 5, "date": "Google Maps", "text": s_txt[:230]})
        for r in reviews:
            txt = r.get("text", {}).get("text", "")
            if re.search(r"\bguinness\b", txt, re.I):
                mentions += 1
                excerpts.append({
                    "author": r.get("authorAttribution", {}).get("displayName", "Reviewer"),
                    "rating": r.get("rating", 5),
                    "date": r.get("relativePublishTimeDescription", "Recently"),
                    "text": txt[:230],
                })
        website = p.get("websiteUri")
        menu_check = scrape_menu_url(website) if (scrape_menus and website) else {
            "checked": False,
            "lastChecked": None,
            "foundOnMenu": False,
            "typesFound": [],
            "extractedPrice": None,
            "snippets": [],
        }
        address = p.get("formattedAddress", "Switzerland")
        gmaps_uri = p.get("googleMapsUri") or (
            "https://www.google.com/maps/search/?api=1&query="
            + urllib.parse.quote_plus(f"{name} {address}")
        )
        found_any = bool(menu_check.get("foundOnMenu")) or mentions > 0
        venues.append({
            "id": f"gplace-{p.get('id')}",
            "googlePlaceId": p.get("id"),
            "city": "all" if city == "custom" else city,
            "name": name,
            "category": category,
            "address": address,
            "lat": p.get("location", {}).get("latitude"),
            "lng": p.get("location", {}).get("longitude"),
            "googleRating": p.get("rating"),
            "googleReviewCount": p.get("userRatingCount", 0),
            "priceLevel": None,
            "website": website,
            "menuUrl": website,
            "googleMapsUri": gmaps_uri,
            "googleMapsChecked": True,
            "servesBeer": p.get("servesBeer", True),
            "phone": p.get("nationalPhoneNumber"),
            "openNow": p.get("regularOpeningHours", {}).get("openNow", True),
            "editorialSummary": editorial or gen_sum or rev_sum or f"Checked on Google Maps ({category.title()}).",
            "menuCheck": menu_check,
            "reviewCheck": {
                "mentionCount": mentions,
                "sentiment": "exceptional" if mentions >= 5 else ("positive" if mentions >= 1 else "none"),
                "excerpts": excerpts[:4],
            },
            # Visitor reports only: nothing a scan finds is a visitor report.
            "crowdCheck": {**evidence.no_crowd(), "reportedPrice": menu_check.get("extractedPrice")},
        })
    return venues


def fetch_osm_overpass_live(lat, lng, radius=1500, scrape_menus=False):
    """
    100% Free, keyless venue discovery using OpenStreetMap Overpass API.
    Finds pubs, bars, restaurants, and hotels around (lat, lng) in Switzerland,
    extracts their websites & OSM tags, and checks for Guinness indicators.
    """
    overpass_query = f"""
    [out:json][timeout:15];
    (
      node["amenity"~"^(pub|bar|restaurant)$"](around:{int(radius)},{float(lat)},{float(lng)});
      way["amenity"~"^(pub|bar|restaurant)$"](around:{int(radius)},{float(lat)},{float(lng)});
      node["tourism"="hotel"](around:{int(radius)},{float(lat)},{float(lng)});
      way["tourism"="hotel"](around:{int(radius)},{float(lat)},{float(lng)});
    );
    out center 40;
    """
    # Several servers, retries and a short cache: see overpass.py
    data = overpass.run(overpass_query)

    venues = []
    seen_names = set()
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name or name.lower() in seen_names:
            continue
        seen_names.add(name.lower())

        v_lat = el.get("lat") or (el.get("center", {}) or {}).get("lat")
        v_lng = el.get("lon") or (el.get("center", {}) or {}).get("lon")
        if v_lat is None or v_lng is None:
            continue

        amenity = tags.get("amenity", "")
        tourism = tags.get("tourism", "")
        if tourism == "hotel" or "hotel" in name.lower():
            category = "hotel"
        elif amenity == "pub" or "pub" in name.lower():
            category = "pub"
        elif amenity == "bar" or "bar" in name.lower():
            category = "bar"
        else:
            category = "restaurant"

        street = tags.get("addr:street", "")
        housenumber = tags.get("addr:housenumber", "")
        postcode = tags.get("addr:postcode", "")
        city_name = tags.get("addr:city", "Switzerland")
        address_parts = [f"{street} {housenumber}".strip(), f"{postcode} {city_name}".strip()]
        address = ", ".join([p for p in address_parts if p]) or "Switzerland (OpenStreetMap)"

        website = clean_public_url(tags.get("website") or tags.get("contact:website") or tags.get("url"))
        menu_url = clean_public_url(tags.get("url:menu")) or website
        phone = tags.get("phone") or tags.get("contact:phone")
        website, menu_url, phone, website_source = fill_from_overture(name, v_lat, v_lng, website, menu_url, phone)

        # Check OSM tags & name for Irish / Guinness signals
        cuisine = (tags.get("cuisine") or "").lower()
        brewery = (tags.get("brewery") or tags.get("drink:beer") or "").lower()
        osm_says_guinness = "guinness" in brewery
        looks_irish = "irish" in cuisine or evidence.is_irish_name(name)
        is_irish_or_guinness_tagged = osm_says_guinness or looks_irish

        if scrape_menus and menu_url and len(venues) < 6:
            menu_check = scrape_menu_url(menu_url)
        else:
            menu_check = {
                "checked": False,
                "lastChecked": None,
                "foundOnMenu": False,
                "typesFound": [],
                "extractedPrice": None,
                "snippets": [
                    f"Website found ({website}) — click 'Scan Menu' to crawl live HTML menu for Guinness."
                    if website
                    else "Discovered via OpenStreetMap — no website listed in OSM tags."
                ],
            }

        venues.append({
            "id": f"osm-{el.get('id')}",
            "city": "custom",
            "name": name,
            "category": category,
            "address": address,
            "lat": float(v_lat),
            "lng": float(v_lng),
            "googleRating": None,
            "googleReviewCount": 0,
            "priceLevel": None,
            "website": website,
            "menuUrl": menu_url,
            "phone": phone,
            "websiteSource": website_source,
            "openNow": True,
            "editorialSummary": f"Live venue discovered via free OpenStreetMap data ({category.title()}).",
            "menuCheck": menu_check,
            "reviewCheck": evidence.no_reviews(),
            "crowdCheck": evidence.no_crowd(),
            **(
                {"tagCheck": evidence.tag_check(evidence.TAG_OSM if osm_says_guinness else evidence.TAG_NAME)}
                if is_irish_or_guinness_tagged
                else {}
            ),
        })

    return venues


def fetch_osm_switzerland_nationwide(scrape_menus=False):
    """
    Queries the entire country of Switzerland (ISO3166-1 = CH) via the free
    OpenStreetMap Overpass API for pubs, bars, restaurants, and hotels tagged
    with Guinness/Irish indicators or matching pub names across all 26 cantons.
    """
    overpass_query = """
    [out:json][timeout:20];
    area["ISO3166-1"="CH"][admin_level=2]->.ch;
    (
      nwr["brewery"~"guinness",i](area.ch);
      nwr["drink:beer"~"guinness",i](area.ch);
      nwr["cuisine"~"irish",i](area.ch);
      nwr["amenity"~"^(pub|bar|restaurant)$"]["name"~"guinness|irish|shamrock|pickwick|paddy|mulligan|flanagan|mccarthy|kelly|dublin|celtic|shenanigan|auld|nelson|oliver twist",i](area.ch);
    );
    out center 100;
    """
    # Several servers, retries and a short cache: see overpass.py
    data = overpass.run(overpass_query, attempt_seconds=24)

    venues = []
    seen_names = {v["name"].lower() for v in DEMO_VENUES}
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name or name.lower() in seen_names:
            continue
        seen_names.add(name.lower())

        v_lat = el.get("lat") or (el.get("center", {}) or {}).get("lat")
        v_lng = el.get("lon") or (el.get("center", {}) or {}).get("lon")
        if v_lat is None or v_lng is None:
            continue

        amenity = tags.get("amenity", "")
        tourism = tags.get("tourism", "")
        if tourism == "hotel" or "hotel" in name.lower():
            category = "hotel"
        elif amenity == "pub" or "pub" in name.lower():
            category = "pub"
        elif amenity == "bar" or "bar" in name.lower():
            category = "bar"
        else:
            category = "restaurant"

        street = tags.get("addr:street", "")
        housenumber = tags.get("addr:housenumber", "")
        postcode = tags.get("addr:postcode", "")
        city_name = tags.get("addr:city", "Switzerland")
        address_parts = [f"{street} {housenumber}".strip(), f"{postcode} {city_name}".strip()]
        address = ", ".join([p for p in address_parts if p]) or f"{city_name}, Switzerland (OpenStreetMap)"

        website = clean_public_url(tags.get("website") or tags.get("contact:website") or tags.get("url"))
        menu_url = clean_public_url(tags.get("url:menu")) or website
        phone = tags.get("phone") or tags.get("contact:phone")
        website, menu_url, phone, website_source = fill_from_overture(name, v_lat, v_lng, website, menu_url, phone)
        brewery = (tags.get("brewery") or tags.get("drink:beer") or "").lower()

        # Nothing was fetched here: the venue matched an OpenStreetMap tag or name search, which is a hint only.
        menu_check = evidence.not_checked()
        osm_says_guinness = "guinness" in brewery

        venues.append({
            "id": f"osm-ch-{el.get('id')}",
            "city": "all",
            "name": name,
            "category": category,
            "address": address,
            "lat": float(v_lat),
            "lng": float(v_lng),
            "googleRating": None,
            "googleReviewCount": 0,
            "priceLevel": None,
            "website": website,
            "menuUrl": menu_url,
            "phone": phone,
            "websiteSource": website_source,
            "openNow": True,
            "editorialSummary": f"Found in OpenStreetMap ({city_name}).",
            "menuCheck": menu_check,
            "reviewCheck": evidence.no_reviews(),
            "crowdCheck": evidence.no_crowd(),
            "tagCheck": evidence.tag_check(evidence.TAG_OSM if osm_says_guinness else evidence.TAG_NAME),
        })

    return venues


class GuinnessHandler(SimpleHTTPRequestHandler):
    def send_json(self, payload, status=200, retry_after=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Public read-only data may be fetched cross-origin; writes are same-origin only.
        if self.command == "GET":
            self.send_header("Access-Control-Allow-Origin", "*")
        if retry_after:
            self.send_header("Retry-After", str(int(retry_after)))
        self.end_headers()
        self.wfile.write(body)

    def _client_ip(self):
        peer = self.client_address[0] if self.client_address else None
        return guard.client_ip(self.headers, peer, ON_VERCEL)

    def _rate_limited(self, bucket, limit_and_window):
        """Answer 429 and return True if this client is over the limit for ``bucket``."""
        limit, window = limit_and_window
        allowed, retry_after = get_rate_limiter().check(bucket, self._client_ip(), limit, window)
        if not allowed:
            self.send_json(
                {"error": "Too many requests. Please slow down and try again later."}, 429, retry_after=retry_after
            )
        return not allowed

    def send_static_file(self, rel_path, content_type):
        abs_path = os.path.join(ROOT_DIR, rel_path)
        if not os.path.exists(abs_path):
            return self.send_json({"error": "Not found"}, 404)
        with open(abs_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/config":
            # Only the *browser* key (map tiles; must be referrer-restricted) is ever sent to clients.
            browser_key = browser_maps_key()
            return self.send_json(
                {
                    "hasEnvApiKey": bool(browser_key),
                    "envApiKey": browser_key,
                    "cities": CITY_PRESETS,
                    "swissCrawlStats": load_crawl_stats(),
                    "communitySubmissions": get_backend().accepts_submissions,
                    "deployment": deployment_info(),
                }
            )

        if parsed.path == "/api/geocode":
            qs = urllib.parse.parse_qs(parsed.query)
            try:
                query = guard.clean_text(qs.get("q", [""])[0], "q", 200)
                if self._rate_limited("scan", RATE_SCANS):
                    return
                found = geocode.geocode(query) if query else None
            except guard.ValidationError as exc:
                return self.send_json({"error": str(exc)}, exc.status)
            except geocode.GeocodeUnavailable as exc:
                return self.send_json({"error": str(exc)}, 503)
            return self.send_json({"found": True, **found} if found else {"found": False})

        if parsed.path == "/api/venues":
            qs = urllib.parse.parse_qs(parsed.query)
            city = qs.get("city", ["all"])[0]
            mode = qs.get("mode", ["demo"])[0]
            lat = qs.get("lat", [None])[0]
            lng = qs.get("lng", [None])[0]
            scrape_menus = qs.get("scrapeMenus", ["false"])[0] == "true"
            api_key = resolve_places_key(self.headers)
            try:
                if lat and lng:
                    lat = guard.clean_number(lat, "lat", -90, 90)
                    lng = guard.clean_number(lng, "lng", -180, 180)
            except guard.ValidationError as exc:
                return self.send_json({"error": str(exc)}, exc.status)
            if mode == "osm_ch" and self._rate_limited("heavy", RATE_HEAVY):
                return
            if mode == "osm" and self._rate_limited("scan", RATE_SCANS):
                return
            if mode == "live" and api_key and self._rate_limited("google", RATE_GOOGLE):
                return
            store = load_store()
            crawl_stats = load_crawl_stats()

            if mode == "osm_ch":
                base_venues = get_all_combined_venues(store)
                try:
                    live_ch = fetch_osm_switzerland_nationwide(scrape_menus)
                    upsert_gmaps_venues_into_store(store, live_ch)
                    combined = get_all_combined_venues(store)
                except Exception:
                    combined = base_venues
                enriched = [enrich_venue(v, store) for v in combined]
                return self.send_json(
                    {"source": "switzerland_nationwide_scan", "swissCrawlStats": crawl_stats, "venues": enriched}
                )

            if mode == "osm" and lat and lng:
                try:
                    osm_venues = fetch_osm_overpass_live(float(lat), float(lng), 2200, scrape_menus)
                    upsert_gmaps_venues_into_store(store, osm_venues)
                    enriched = [enrich_venue(v, store) for v in osm_venues]
                    return self.send_json(
                        {"source": "openstreetmap_overpass_free", "swissCrawlStats": crawl_stats, "venues": enriched}
                    )
                except overpass.OverpassUnavailable as e:
                    return self.send_json({"error": str(e)}, 503, retry_after=30)
                except Exception as e:
                    return self.send_json({"error": str(e)}, 500)

            if mode == "live" and api_key and lat and lng:
                try:
                    live_venues = fetch_google_places_live(
                        api_key, float(lat), float(lng), 3500, scrape_menus, city=city
                    )
                    upsert_gmaps_venues_into_store(store, live_venues)
                    all_combined = get_all_combined_venues(store)
                    filtered = (
                        all_combined
                        if city in ("all", "custom")
                        else [v for v in all_combined if v.get("city") == city]
                    )
                    enriched = [enrich_venue(v, store) for v in filtered]
                    return self.send_json(
                        {
                            "source": "google_places_live",
                            "checkedCount": len(live_venues),
                            "swissCrawlStats": crawl_stats,
                            "venues": enriched,
                        }
                    )
                except Exception as e:
                    return self.send_json({"error": str(e)}, 500)

            all_venues = get_all_combined_venues(store)
            filtered = all_venues if city == "all" else [v for v in all_venues if v.get("city") == city]
            enriched = [enrich_venue(v, store) for v in filtered]
            return self.send_json({"source": "demo_curated", "swissCrawlStats": crawl_stats, "venues": enriched})

        if parsed.path in ("/", "/index.html", "/standalone.html", "/public/standalone.html"):
            return self.send_static_file(os.path.join("public", "standalone.html"), "text/html; charset=utf-8")
        if parsed.path == "/src/styles.css":
            return self.send_static_file(os.path.join("src", "styles.css"), "text/css; charset=utf-8")
        # Only the routes above exist. (This used to fall through to SimpleHTTPRequestHandler, which
        # served any file in the project directory: source code, .git, and a .env holding API keys.)
        return self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        """Never let an exception escape as a dropped connection; answer with a JSON error."""
        try:
            self._handle_post()
        except guard.ValidationError as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except storage.StorageError as exc:
            print(f"[storage] {exc}", file=sys.stderr)
            self.send_json({"error": "The database is temporarily unavailable. Please try again shortly."}, 503)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self.send_json({"error": "Internal server error"}, 500)

    def _handle_post(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in (
            "/api/check-google-maps", "/api/scan-menu", "/api/crowd-report", "/api/add-venue",
            "/api/relocate-venue",
        ):
            return self.send_json({"error": "Not found"}, 404)
        # Requiring JSON also blocks cross-site "simple" form/text POSTs (CSRF).
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            raise guard.ValidationError("Content-Type must be application/json", 415)
        data = guard.read_json_body(self.headers, self.rfile)
        backend = get_backend()
        store = load_store()

        if parsed.path == "/api/check-google-maps":
            query = guard.clean_text(data.get("query"), "query", 1000)
            city = guard.clean_choice(data.get("city"), "city", tuple(CITY_PRESETS) + ("custom",), "all")
            lat = guard.clean_number(data.get("lat"), "lat", -90, 90, 47.3745)
            lng = guard.clean_number(data.get("lng"), "lng", -180, 180, 8.5385)
            radius = guard.clean_number(data.get("radius"), "radius", 100, 10000, 3500)
            website = guard.clean_website(data.get("website")) or ""
            api_key = resolve_places_key(self.headers)
            if self._rate_limited("google" if api_key else "scan", RATE_GOOGLE if api_key else RATE_SCANS):
                return

            checked_venues = []
            if api_key:
                try:
                    checked_venues = fetch_google_places_live(
                        api_key, lat, lng, radius, True, query=query, city=city
                    )
                except Exception as e:
                    return self.send_json({"error": str(e)}, 500)
            elif query:
                for line in [ln.strip() for ln in query.splitlines() if ln.strip()][:10]:
                    pq = parse_google_maps_url_or_query(line)
                    v_name = (pq["name"] or line)[:100]
                    v_lat = max(-90.0, min(90.0, pq["lat"])) if pq["lat"] is not None else lat
                    v_lng = max(-180.0, min(180.0, pq["lng"])) if pq["lng"] is not None else lng
                    lower_n = v_name.lower()
                    v_cat = (
                        "hotel"
                        if "hotel" in lower_n
                        else ("pub" if "pub" in lower_n else ("bar" if "bar" in lower_n else "restaurant"))
                    )
                    is_irish = evidence.is_irish_name(v_name)
                    menu_check = scrape_menu_url(website) if website else evidence.not_checked("No website to read.")
                    # Only keep a user-supplied link if it is really an https Google Maps URL.
                    gmaps_uri = (
                        guard.safe_google_maps_uri(line) if pq["isUrl"] else None
                    ) or (
                        "https://www.google.com/maps/search/?api=1&query="
                        + urllib.parse.quote_plus(f"{v_name} Switzerland")
                    )
                    checked_venues.append({
                        "id": f"gmaps-{int(time.time() * 1000)}-{len(checked_venues)}",
                        "city": "zurich" if city == "all" else city,
                        "name": v_name,
                        "category": v_cat,
                        "address": "Switzerland",
                        "lat": float(v_lat),
                        "lng": float(v_lng),
                        "googleRating": None,
                        "googleReviewCount": 0,
                        "priceLevel": None,
                        "website": website or None,
                        "menuUrl": website or None,
                        "googleMapsUri": gmaps_uri,
                        "googleMapsChecked": True,
                        "openNow": True,
                        "editorialSummary": f"Added from a name or link entered by a visitor ({v_cat.title()}). Location and details are not verified.",
                        "menuCheck": menu_check,
                        "reviewCheck": evidence.no_reviews(),
                        "crowdCheck": {**evidence.no_crowd(), "reportedPrice": menu_check.get("extractedPrice")},
                        **({"tagCheck": evidence.tag_check(evidence.TAG_NAME)} if is_irish else {}),
                    })
            else:
                try:
                    checked_venues = fetch_osm_overpass_live(lat, lng, radius, True)
                except Exception:
                    checked_venues = []

            if checked_venues:
                upsert_gmaps_venues_into_store(store, checked_venues)

            all_v = get_all_combined_venues(store)
            filtered = all_v if city == "all" else [v for v in all_v if v.get("city") == city]
            enriched_all = [enrich_venue(v, store) for v in filtered]
            enriched_checked = [enrich_venue(v, store) for v in checked_venues]
            guinness_count = sum(
                1
                for v in enriched_checked
                if v.get("guinnessSummary", {}).get("status")
                in ("confirmed_draught", "cans_or_bottles", "likely_serves")
            )
            return self.send_json({
                "checkedCount": len(enriched_checked) or len(enriched_all),
                "guinnessFoundCount": guinness_count,
                "venues": enriched_checked,
                "allVenues": enriched_all,
            })

        if parsed.path == "/api/scan-menu":
            if self._rate_limited("scan", RATE_SCANS):
                return
            vid = guard.clean_venue_id(data["venueId"]) if data.get("venueId") else None
            url = guard.clean_website(data.get("websiteUrl"))
            venue_snapshot = data.get("venue") if isinstance(data.get("venue"), dict) else None
            all_v = get_all_combined_venues(store)
            known = next((v for v in all_v if v["id"] == vid), None) if vid else None
            existing = known or venue_snapshot
            target_url = url or (existing.get("menuUrl") if existing else None) or (existing.get("website") if existing else None)
            scan_res = scrape_menu_url(target_url, existing.get("menuCheck") if existing else None)
            if vid:
                store.setdefault("menuScans", {})[vid] = scan_res  # so this response reflects the scan
                # Only *save* a result for a venue we know, from a real scan, of a page on that venue's own
                # site - otherwise anyone could make any venue look like it serves Guinness.
                own_site = bool(known) and (
                    not url or guard.same_site(url, known.get("website")) or guard.same_site(url, known.get("menuUrl"))
                )
                if own_site and scan_res.get("checked"):
                    backend.set_scan(store, vid, scan_res)
            updated = enrich_venue(existing, store) if existing and existing.get("id") else None
            return self.send_json({"scanResult": scan_res, "venue": updated})

        if parsed.path == "/api/crowd-report":
            if not backend.accepts_submissions:
                return self.send_json({"error": SUBMISSIONS_DISABLED_MESSAGE}, 503)
            if self._rate_limited("write", RATE_WRITES):
                return
            clean = guard.validate_crowd_report(data)
            vid = clean.pop("venueId")
            venue_snapshot = data.get("venue") if isinstance(data.get("venue"), dict) else None
            rep = {
                "id": f"rep-{int(time.time() * 1000)}",
                **clean,
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
            backend.add_report(store, vid, rep)
            all_v = get_all_combined_venues(store)
            existing = next((v for v in all_v if v["id"] == vid), None) or venue_snapshot
            updated = enrich_venue(existing, store) if existing and existing.get("id") else None
            return self.send_json({"report": rep, "venue": updated})

        if parsed.path == "/api/relocate-venue":
            # Re-place a community venue from the address stored with it. The visitor supplies no coordinates, so this
            # cannot be used to drag a venue anywhere: the only way to move it is to correct its address text first.
            if not backend.accepts_submissions:
                return self.send_json({"error": SUBMISSIONS_DISABLED_MESSAGE}, 503)
            if self._rate_limited("write", RATE_WRITES):
                return
            vid = guard.clean_venue_id(data.get("venueId"))
            venue = next((v for v in (store.get("customVenues") or []) if isinstance(v, dict) and v.get("id") == vid), None)
            if not venue:
                raise guard.ValidationError("Only venues added by visitors can be re-placed from their address", 404)
            address = (venue.get("address") or "").strip()
            if len(address) < 6 or address.lower() in ("switzerland", "schweiz", "suisse", "svizzera"):
                raise guard.ValidationError("This venue has no street address to look up.")
            try:
                found = geocode.geocode(address)
            except geocode.GeocodeUnavailable as exc:
                return self.send_json({"error": str(exc)}, 503)
            if not found:
                raise guard.ValidationError(f"Could not find \"{address}\" on the map. Check the address.")
            backend.set_location(store, vid, {"lat": found["lat"], "lng": found["lng"]})
            moved_km = round(distance_km(venue.get("lat"), venue.get("lng"), found["lat"], found["lng"]), 1)
            placed = place_community_venue(venue, store.get("venueLocations"))
            return self.send_json({"venue": enrich_venue(placed, store), "movedKm": moved_km, "label": found["label"]})

        if parsed.path == "/api/add-venue":
            if not backend.accepts_submissions:
                return self.send_json({"error": SUBMISSIONS_DISABLED_MESSAGE}, 503)
            if self._rate_limited("write", RATE_WRITES):
                return
            clean = guard.validate_new_venue(data, set(CITY_PRESETS))
            vid = f"custom-{int(time.time() * 1000)}"
            website = clean["website"]
            s_format = clean["servingFormat"]
            menu_check = (
                scrape_menu_url(website)
                if website
                else evidence.not_checked("No website to read. The only evidence is the visitor's own report.")
            )
            new_venue = {
                "id": vid,
                "city": clean["city"],
                "name": clean["name"],
                "category": clean["category"],
                "address": clean["address"],
                "lat": clean["lat"],
                "lng": clean["lng"],
                "googleRating": None,
                "googleReviewCount": 0,
                "priceLevel": None,
                "website": website,
                "menuUrl": website,
                "openNow": True,
                "editorialSummary": clean["note"] or "Venue added by a visitor.",
                "menuCheck": menu_check,
                "reviewCheck": evidence.no_reviews(),
                # The one report that came with the venue is a real visitor report.
                "crowdCheck": {
                    "confirmedCount": 1 if s_format != "none" else 0,
                    "deniedCount": 1 if s_format == "none" else 0,
                    "servingFormat": s_format,
                    "reportedPrice": clean["price"],
                    "hasZero": False,
                    "recentReports": [],
                },
            }
            backend.add_venue(store, new_venue)
            return self.send_json({"venue": enrich_venue(new_venue, store)})

        return self.send_json({"error": "Not found"}, 404)


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    os.chdir(ROOT_DIR)
    base_port = int(os.environ.get("PORT", "3000"))
    server = None
    chosen_port = base_port
    for candidate in range(base_port, base_port + 10):
        try:
            server = ReusableThreadingHTTPServer(("127.0.0.1", candidate), GuinnessHandler)
            chosen_port = candidate
            break
        except OSError:
            continue

    if server is None:
        raise RuntimeError("Could not bind to any local port between 3000 and 3009.")

    url = f"http://localhost:{chosen_port}"
    print(f"\n🍺 Guinness Guide Switzerland (Map & Menu Finder) is live at: {url}")
    print("   Press Ctrl+C to stop the server.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Guinness Guide server. Sláinte!")
        server.server_close()

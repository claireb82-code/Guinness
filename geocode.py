"""
Turn a Swiss street address into a map position (standard library only).

Why this exists: the "Add venue" form took its position from wherever the map happened to be centred, and the address
the visitor typed was only text. A pub in Davos added while looking at the whole country was therefore pinned in the
middle of Switzerland. The form now looks the address up here, and a community venue can be re-placed from its stored
address.

Uses the free OpenStreetMap Nominatim search (https://operations.osmfoundation.org/policies/nominatim/): restricted to
Switzerland, one lookup per request, a descriptive User-Agent, and results cached so a repeated address is not looked up
again. Nothing the visitor types can choose the host: only the query string varies.

    GEOCODE_URL   override the search endpoint (tests point it at a local server)
"""

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import guard

DEFAULT_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "GuinnessGuideSwitzerland/1.0 (venue finder; https://guinness-pi.vercel.app)"
CACHE_SECONDS = 24 * 3600
MISS_SECONDS = 600
MAX_CACHE = 500

_cache = {}
_lock = threading.Lock()


class GeocodeUnavailable(RuntimeError):
    """The lookup service could not be reached or answered nonsense. The message is safe to show visitors."""


def reset_cache():
    with _lock:
        _cache.clear()


def _in_switzerland(lat, lng):
    b = guard.CH_BOUNDS
    return b["south"] <= lat <= b["north"] and b["west"] <= lng <= b["east"]


def geocode(query, timeout=6):
    """``{"lat", "lng", "label"}`` for the best match in Switzerland, or None if the address is not found."""
    q = " ".join(str(query or "").split())[:200]
    if len(q) < 4:
        return None
    key = q.lower()
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]

    url = os.environ.get("GEOCODE_URL") or DEFAULT_URL
    params = urllib.parse.urlencode({"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "ch", "addressdetails": 0})
    req = urllib.request.Request(f"{url}?{params}", headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read(200_000).decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        raise GeocodeUnavailable("The address lookup is busy right now. Please try again, or click the map to place the venue.") from None

    result = None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        try:
            lat, lng = float(data[0]["lat"]), float(data[0]["lon"])
        except (KeyError, TypeError, ValueError):
            lat = lng = None
        if lat is not None and _in_switzerland(lat, lng):
            result = {"lat": round(lat, 5), "lng": round(lng, 5), "label": str(data[0].get("display_name") or q)[:200]}

    with _lock:
        if len(_cache) >= MAX_CACHE:
            _cache.clear()
        _cache[key] = (now + (CACHE_SECONDS if result else MISS_SECONDS), result)
    return result

"""
Fill in missing venue websites from the bundled Overture Maps extract.

OpenStreetMap lists a website for only about a third of Swiss venues; Overture lists one for roughly
half. A website is what the Guinness scanner needs, so when a venue found through OpenStreetMap has
none, we look for the same venue in Overture: same-ish name, within MAX_DISTANCE_M metres.

The extract (server/data/overture_ch.json) is produced by scripts/import_overture.py. If the file is
missing the lookup quietly finds nothing, so the app works without it. Pure standard library.

Data: © Overture Maps Foundation, places theme, CDLA-Permissive-2.0 (server/data/OVERTURE_ATTRIBUTION.md).
"""

import difflib
import json
import math
import os
import re
import threading
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.environ.get("OVERTURE_DATA_PATH") or os.path.join(ROOT, "server", "data", "overture_ch.json")

CELL_DEGREES = 0.005  # grid cell for the spatial index (~550 m north-south)
MAX_DISTANCE_M = 75
MIN_SCORE = 0.8
MIN_SINGLE_WORD = 6  # letters a one-word name needs to count as "contained" in a longer name

# Words that say what kind of place it is, not which one: ignoring them lets "Restaurant Rössli"
# match "Rössli" while "Bar Rouge" does not match "Bar Bleu". German, French, Italian and English.
STOPWORDS = frozenset(
    "the and und et e restaurant ristorante bar pub hotel hôtel cafe café caffe caffè bistro brasserie pizzeria trattoria "
    "osteria taverne tavern gasthaus gasthof wirtshaus beizli buvette auberge grill lounge club kneipe haus "
    "zum zur zu der die das dem den im am an auf bei le la les l du de des d al alla da il lo i gli un una of at in".split()
)


def normalize_tokens(name):
    """Lower-case, accent-free word list without 'kind of place' words (falls back to all words)."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii").lower()
    words = re.findall(r"[a-z0-9]+", text)
    kept = [w for w in words if w not in STOPWORDS and (len(w) > 1 or w.isdigit())]
    return kept or words


def name_score(a, b):
    """0..1 similarity of two venue names."""
    ta, tb = normalize_tokens(a), normalize_tokens(b)
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta), set(tb)
    if sa == sb:
        return 1.0
    small, large = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    # One name inside the other ("Old Stand" in "The Old Stand Irish Pub"). A single short word is too
    # weak ("Penny" is not "Penny Farthing Pub"): measured on real data it adds false matches.
    if small <= large and (len(small) >= 2 or len(next(iter(small))) >= MIN_SINGLE_WORD):
        return 0.9
    return difflib.SequenceMatcher(None, " ".join(sorted(sa)), " ".join(sorted(sb))).ratio()


def distance_m(lat1, lng1, lat2, lng2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


class Index:
    def __init__(self, places):
        self.places = places
        self.grid = {}
        for place in places:
            self.grid.setdefault(self._cell(place["lat"], place["lng"]), []).append(place)

    @staticmethod
    def _cell(lat, lng):
        return (int(math.floor(lat / CELL_DEGREES)), int(math.floor(lng / CELL_DEGREES)))

    def candidates(self, lat, lng):
        ci, cj = self._cell(lat, lng)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                yield from self.grid.get((ci + di, cj + dj), ())

    def find(self, name, lat, lng, max_m=MAX_DISTANCE_M, min_score=MIN_SCORE):
        best = None
        for place in self.candidates(lat, lng):
            d = distance_m(lat, lng, place["lat"], place["lng"])
            if d > max_m:
                continue
            score = name_score(name, place["name"])
            if score < min_score:
                continue
            if best is None or (score, -d) > (best[0], -best[1]):
                best = (score, d, place)
        return None if best is None else {**best[2], "score": round(best[0], 2), "distanceM": round(best[1])}


_cache = {"path": None, "index": None}
_lock = threading.Lock()


def load_index(path=None):
    """Load (once per process) the extract; an absent or unreadable file gives an empty index."""
    path = path or DATA_PATH
    with _lock:
        if _cache["path"] == path and _cache["index"] is not None:
            return _cache["index"]
        try:
            with open(path, "r", encoding="utf-8") as f:
                places = [p for p in json.load(f).get("places", []) if p.get("website") and p.get("lat") is not None]
        except (OSError, ValueError):
            places = []
        _cache.update(path=path, index=Index(places))
        return _cache["index"]


def reset_cache():
    with _lock:
        _cache.update(path=None, index=None)


def find_match(name, lat, lng, index=None, **kw):
    """The Overture venue that is probably the same place, or None. ``lat``/``lng`` may be None."""
    if not name or lat is None or lng is None:
        return None
    return (index or load_index()).find(name, float(lat), float(lng), **kw)

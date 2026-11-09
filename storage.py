"""
Persistence for community data (crowd reports, community-added venues, menu-scan results).

Why this exists: on Vercel the only writable place is ``/tmp``, which is private to one function
instance and wiped on every cold start. Reports saved there silently disappear and different
visitors see different data. So there are two backends with the same interface:

* ``FileBackend``  - a JSON file. Used for local development (``python3 app_server.py``).
  On Vercel without a database it is flagged *ephemeral* and community submissions are refused
  rather than accepted and then lost.
* ``RedisBackend`` - Upstash Redis / Vercel KV over its HTTPS REST API (standard library only, no
  new dependency). Selected when ``KV_REST_API_URL`` + ``KV_REST_API_TOKEN`` (Vercel's Upstash
  integration) or ``UPSTASH_REDIS_REST_URL`` + ``UPSTASH_REDIS_REST_TOKEN`` are set.

Redis layout (all keys prefixed, default ``guinness:``). Every write is a single atomic command,
so two visitors submitting at once cannot overwrite each other:

====================  ======  ==========================================================
key                   type    content
====================  ======  ==========================================================
``reports``           list    JSON crowd reports, newest first, capped at MAX_REPORTS
``venues``            list    JSON community venues, newest first, capped at MAX_CUSTOM_VENUES
``scans``             hash    venueId -> JSON menu-scan result
``rl:<bucket>:<ip>``  string  rate-limit counters (expire automatically)
====================  ======  ==========================================================

``googleMapsVenues`` (venues discovered by live OpenStreetMap / Google scans) stays in the local
file cache on purpose: it is derived, re-creatable data and can be large.
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_REPORTS = 2000
MAX_CUSTOM_VENUES = 500


class StorageError(RuntimeError):
    """The database could not be reached or returned an error."""


def _empty_store():
    return {"crowdReports": {}, "menuScans": {}, "customVenues": [], "googleMapsVenues": []}


class FileBackend:
    name = "file"

    def __init__(self, path, bundled_path, ephemeral=False):
        self.path = path
        self.bundled_path = bundled_path
        self.ephemeral = ephemeral
        self._lock = threading.Lock()
        self._counters = {}

    @property
    def accepts_submissions(self):
        """False when anything we accept would be lost (serverless /tmp with no database)."""
        return not self.ephemeral

    # -- reading ---------------------------------------------------------------------
    def load(self):
        for candidate in (self.path, self.bundled_path):
            if candidate and os.path.exists(candidate):
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return {
                        "crowdReports": data.get("crowdReports", {}),
                        "menuScans": data.get("menuScans", {}),
                        "customVenues": data.get("customVenues", []),
                        "googleMapsVenues": data.get("googleMapsVenues", []),
                    }
                except Exception:  # noqa: BLE001 - a corrupt cache must not take the API down
                    continue
        return _empty_store()

    def save(self, store):
        """Write the whole store (used for the derived-venue cache and for file-mode submissions)."""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with self._lock, open(self.path, "w", encoding="utf-8") as f:
                json.dump(store, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    # -- community writes (also update the in-memory ``store`` so the response is current) --
    def add_report(self, store, venue_id, report):
        reports = store.setdefault("crowdReports", {}).setdefault(venue_id, [])
        reports.insert(0, report)
        del reports[200:]
        self.save(store)

    def add_venue(self, store, venue):
        venues = store.setdefault("customVenues", [])
        venues.insert(0, venue)
        del venues[MAX_CUSTOM_VENUES:]
        self.save(store)

    def set_scan(self, store, venue_id, scan):
        store.setdefault("menuScans", {})[venue_id] = scan
        self.save(store)

    # -- rate-limit counters (per process) --------------------------------------------
    def incr(self, key, window_seconds):
        now = time.time()
        with self._lock:
            if len(self._counters) > 10000:
                self._counters = {k: v for k, v in self._counters.items() if v[0] > now}
            expires, count = self._counters.get(key, (0, 0))
            if expires <= now:
                expires, count = now + window_seconds, 0
            count += 1
            self._counters[key] = (expires, count)
            return count


class RedisBackend(FileBackend):
    name = "redis"

    def __init__(self, url, token, path, bundled_path, prefix="guinness:", timeout=4):
        super().__init__(path, bundled_path, ephemeral=False)
        parts = urllib.parse.urlsplit(url)
        local = parts.hostname in ("localhost", "127.0.0.1", "::1")
        if parts.scheme != "https" and not (parts.scheme == "http" and local):
            raise ValueError("Redis REST URL must be https (the token is sent with every request)")
        self.url = url.rstrip("/")
        self.token = token
        self.prefix = prefix
        self.timeout = timeout

    def _key(self, name):
        return f"{self.prefix}{name}"

    # -- transport -------------------------------------------------------------------
    def _pipeline(self, commands):
        req = urllib.request.Request(
            f"{self.url}/pipeline",
            data=json.dumps(commands).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                results = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise StorageError(f"database rejected the request (HTTP {exc.code})") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise StorageError(f"database unreachable: {exc}") from None
        if not isinstance(results, list) or len(results) != len(commands):
            raise StorageError("unexpected database response")
        out = []
        for item in results:
            if isinstance(item, dict) and item.get("error"):
                raise StorageError(f"database error: {item['error']}")
            out.append(item.get("result") if isinstance(item, dict) else item)
        return out

    # -- reading ---------------------------------------------------------------------
    def load(self):
        store = super().load()  # derived venue cache (+ bundled seed data) from the local file
        try:
            reports, venues, scans = self._pipeline(
                [
                    ["LRANGE", self._key("reports"), 0, MAX_REPORTS - 1],
                    ["LRANGE", self._key("venues"), 0, MAX_CUSTOM_VENUES - 1],
                    ["HGETALL", self._key("scans")],
                ]
            )
        except StorageError as exc:
            # Reads degrade: show what we have rather than failing the whole page.
            print(f"[storage] {exc}", file=sys.stderr)
            return store

        grouped = {}
        for raw in reports or []:
            try:
                rep = json.loads(raw)
                grouped.setdefault(rep.pop("venueId"), []).append(rep)
            except (ValueError, KeyError, AttributeError, TypeError):
                continue  # skip a malformed entry instead of failing the request
        store["crowdReports"] = grouped

        custom = []
        for raw in venues or []:
            try:
                custom.append(json.loads(raw))
            except (ValueError, TypeError):
                continue
        store["customVenues"] = custom

        if isinstance(scans, list):  # REST returns HGETALL as a flat [field, value, ...] list
            scans = dict(zip(scans[0::2], scans[1::2]))
        parsed_scans = {}
        for vid, raw in (scans or {}).items():
            try:
                parsed_scans[vid] = json.loads(raw)
            except (ValueError, TypeError):
                continue
        store["menuScans"] = parsed_scans
        return store

    # -- writes ----------------------------------------------------------------------
    def add_report(self, store, venue_id, report):
        entry = json.dumps({**report, "venueId": venue_id}, ensure_ascii=False)
        key = self._key("reports")
        self._pipeline([["LPUSH", key, entry], ["LTRIM", key, 0, MAX_REPORTS - 1]])
        store.setdefault("crowdReports", {}).setdefault(venue_id, []).insert(0, report)

    def add_venue(self, store, venue):
        key = self._key("venues")
        self._pipeline([["LPUSH", key, json.dumps(venue, ensure_ascii=False)], ["LTRIM", key, 0, MAX_CUSTOM_VENUES - 1]])
        store.setdefault("customVenues", []).insert(0, venue)

    def set_scan(self, store, venue_id, scan):
        self._pipeline([["HSET", self._key("scans"), venue_id, json.dumps(scan, ensure_ascii=False)]])
        store.setdefault("menuScans", {})[venue_id] = scan

    # -- shared rate-limit counters ----------------------------------------------------
    def incr(self, key, window_seconds):
        k = self._key(key)
        # SET .. EX .. NX creates the key *with* its expiry if (and only if) it is absent, then INCR
        # counts. One round trip, and a key can never be left without an expiry.
        _set, count = self._pipeline([["SET", k, 0, "EX", int(window_seconds), "NX"], ["INCR", k]])
        return int(count)


def build_backend(env, path, bundled_path, on_vercel):
    """Pick a backend from environment variables (see module docstring)."""
    url = env.get("KV_REST_API_URL") or env.get("UPSTASH_REDIS_REST_URL")
    token = env.get("KV_REST_API_TOKEN") or env.get("UPSTASH_REDIS_REST_TOKEN")
    if url and token:
        return RedisBackend(url, token, path, bundled_path, prefix=env.get("GUINNESS_KEY_PREFIX", "guinness:"))
    return FileBackend(path, bundled_path, ephemeral=bool(on_vercel))

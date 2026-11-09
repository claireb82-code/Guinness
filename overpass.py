"""
Reliable access to the public OpenStreetMap Overpass API (standard library only).

The free Overpass servers are shared and often busy. They answer 429/502/503/504, time out, or even
answer HTTP 200 with a "remark" saying the query ran out of time or memory (and no results). With one
hard-coded server and a single try, the "scan this area" feature simply failed whenever that happened.

``run(query)`` therefore:

* tries several servers in order (the primary first), for up to ROUNDS passes, within one overall
  deadline that fits a serverless function;
* moves on to the next server for overload-style failures (429/5xx, timeouts, network errors, HTML or
  garbage instead of JSON, HTTP 200 with a "runtime error"/timeout remark) but stops at once for
  HTTP 400, which means our query is malformed and no other server would accept it either;
* keeps a short cache so scanning the same area again does not hit Overpass, and, if every server is
  down, serves an older cached copy rather than failing;
* raises ``OverpassUnavailable`` with a message that is safe to show to visitors.

Configuration (all optional, read at call time):

    OVERPASS_URLS              comma-separated endpoints, tried in order (default: three public servers)
    OVERPASS_ATTEMPT_SECONDS   per-server time limit                       (default 18)
    OVERPASS_DEADLINE_SECONDS  overall limit for one query                 (default 40)
    OVERPASS_ROUNDS            passes over the server list                 (default 2)
    OVERPASS_RETRY_PAUSE_SECONDS  pause between passes                     (default 1)
    OVERPASS_CACHE_SECONDS     how long a result counts as fresh; 0 = off  (default 300)
    OVERPASS_STALE_SECONDS     how old a result may be when all servers fail (default 3600)

Only the first default server has been used by this app before; the others are public community
mirrors that may come and go. A dead mirror just costs one failed attempt.
"""

import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
USER_AGENT = "GuinnessGuideSwitzerland/1.0 (venue finder; https://guinness-pi.vercel.app)"
FRIENDLY_MESSAGE = "OpenStreetMap's public search servers are busy right now. Please try again in a minute."

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
FAILURE_REMARK = re.compile(r"runtime error|timed out|time ?out|out of memory|too many requests|rate.?limit", re.I)
MAX_CACHE_ENTRIES = 64


class OverpassError(RuntimeError):
    """The query itself was rejected (HTTP 400): retrying elsewhere would not help."""


class OverpassUnavailable(OverpassError):
    """Every server failed. ``str(error)`` is safe to show to visitors."""

    def __init__(self, message=FRIENDLY_MESSAGE, attempts=None):
        super().__init__(message)
        self.attempts = attempts or []


class _Retry(Exception):
    """Internal: this server did not give a usable answer; try the next one."""


# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------


def _number(name, default, minimum=0.0):
    try:
        return max(minimum, float(os.environ.get(name, default)))
    except ValueError:
        return default


def endpoints(raw=None):
    """The configured server URLs (http/https only); the defaults if none are valid."""
    raw = os.environ.get("OVERPASS_URLS", "") if raw is None else raw
    urls = []
    for item in raw.split(","):
        item = item.strip()
        parts = urllib.parse.urlsplit(item)
        if parts.scheme in ("http", "https") and parts.netloc:
            urls.append(item)
    return tuple(urls) or DEFAULT_URLS


# --------------------------------------------------------------------------------------
# Cache (per process: shared by all requests handled by the same server instance)
# --------------------------------------------------------------------------------------

_cache = {}
_lock = threading.Lock()


def clear_cache():
    with _lock:
        _cache.clear()


def _key(query):
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _cache_get(key, max_age, wall):
    if max_age <= 0:
        return None
    with _lock:
        entry = _cache.get(key)
    if entry and wall() - entry[0] <= max_age:
        return entry[1]
    return None


def _cache_put(key, data, wall):
    with _lock:
        _cache[key] = (wall(), data)
        while len(_cache) > MAX_CACHE_ENTRIES:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))


# --------------------------------------------------------------------------------------
# One attempt
# --------------------------------------------------------------------------------------


def _attempt(url, query, timeout):
    """POST the query to one server. Returns the parsed JSON; raises _Retry or OverpassError."""
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode({"data": query}).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 400:
            detail = ""
            try:
                detail = exc.read(300).decode("utf-8", "replace").strip()
            except Exception:  # noqa: BLE001
                pass
            raise OverpassError(f"Overpass rejected the query (HTTP 400){': ' + detail if detail else ''}") from None
        raise _Retry(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise _Retry(f"{type(reason).__name__}: {reason}") from None

    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise _Retry("the answer was not JSON (probably an error page)") from None
    if not isinstance(data, dict):
        raise _Retry("the answer was not a JSON object")
    remark = data.get("remark")
    if isinstance(remark, str) and FAILURE_REMARK.search(remark):
        raise _Retry(f"HTTP 200 but the server reported: {remark[:120]}")
    return data


# --------------------------------------------------------------------------------------
# The public entry point
# --------------------------------------------------------------------------------------


def run(query, attempt_seconds=None, deadline_seconds=None, rounds=None, urls=None, clock=time.monotonic, wall=time.time, sleep=time.sleep):
    """Run an Overpass QL query (``[out:json]``) and return the parsed JSON.

    Raises :class:`OverpassError` for a malformed query and :class:`OverpassUnavailable` when every
    server failed and there is no cached copy to fall back on.
    """
    urls = tuple(urls) if urls else endpoints()
    attempt_seconds = _number("OVERPASS_ATTEMPT_SECONDS", 18, 0.1) if attempt_seconds is None else attempt_seconds
    deadline_seconds = _number("OVERPASS_DEADLINE_SECONDS", 40, 1) if deadline_seconds is None else deadline_seconds
    rounds = int(_number("OVERPASS_ROUNDS", 2, 1)) if rounds is None else rounds
    pause = _number("OVERPASS_RETRY_PAUSE_SECONDS", 1.0)
    cache_seconds = _number("OVERPASS_CACHE_SECONDS", 300)
    stale_seconds = _number("OVERPASS_STALE_SECONDS", 3600)

    key = _key(query)
    fresh = _cache_get(key, cache_seconds, wall)
    if fresh is not None:
        return fresh

    deadline = clock() + deadline_seconds
    attempts = []
    for round_number in range(rounds):
        for url in urls:
            remaining = deadline - clock()
            if remaining < 0.5:
                break
            try:
                data = _attempt(url, query, min(attempt_seconds, remaining))
            except _Retry as exc:
                attempts.append((url, str(exc)))
                print(f"[overpass] {url}: {exc}", file=sys.stderr)
                continue
            if cache_seconds > 0:
                _cache_put(key, data, wall)
            return data
        else:
            if round_number < rounds - 1 and deadline - clock() > pause + 1:
                sleep(pause)
            continue
        break  # the deadline ran out in the inner loop

    stale = _cache_get(key, stale_seconds, wall) if cache_seconds > 0 else None
    if stale is not None:
        print("[overpass] all servers failed; serving an older cached copy", file=sys.stderr)
        return stale
    raise OverpassUnavailable(FRIENDLY_MESSAGE, attempts)

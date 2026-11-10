"""
Request / URL safety helpers for the Guinness Guide server (Python standard library only).

This module exists because the public API accepts input from anonymous visitors and fetches
URLs on their behalf. It provides:

* ``normalize_http_url`` / ``fetch_page``  - SSRF-safe page fetching. Every connection (including
  every redirect hop) resolves the hostname, refuses private / loopback / link-local / CGNAT /
  metadata addresses, and connects to the *validated* IP, so DNS tricks cannot swap the target
  between the check and the connection.
* ``read_json_body``                       - bounded, validated JSON request bodies.
* ``validate_crowd_report`` / ``validate_new_venue`` - strict whitelisting of what visitors may store.
* ``RateLimiter``                          - fixed-window per-client limits (shared across serverless
  instances when the storage backend supports it).
* ``same_site``                            - host comparison used to stop a scan result for one
  venue being poisoned with a page from an unrelated site.

Nothing here talks to Google or the database; see ``storage.py`` and ``app_server.py``.
"""

import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request

MAX_BODY_BYTES = 20_000
MAX_PAGE_BYTES = 1_500_000
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) GuinnessGuide/1.0"

# Switzerland (incl. Liechtenstein border margin). Community-added venues must fall inside.
CH_BOUNDS = {"south": 45.7, "north": 47.95, "west": 5.9, "east": 10.65}
CATEGORIES = ("pub", "bar", "restaurant", "hotel")
SERVING_FORMATS = ("draught", "cans_bottles", "none")


class ValidationError(ValueError):
    """Bad client input. ``status`` is the HTTP status to answer with."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class UnsafeURL(ValueError):
    """The URL is malformed, not http(s), or points at a non-public address."""


# --------------------------------------------------------------------------------------
# URL validation
# --------------------------------------------------------------------------------------

_EXPLICIT_SCHEME = re.compile(r"^([a-z][a-z0-9+.\-]*)://", re.I)
_DANGEROUS_SCHEME = re.compile(
    r"^(javascript|data|file|vbscript|ftp|ftps|gopher|mailto|tel|blob|about|ws|wss|view-source):", re.I
)


def normalize_http_url(raw, max_len=300):
    """Return a clean ``http(s)://`` URL or raise :class:`UnsafeURL`.

    Bare hosts such as ``example.com/menu`` get ``https://`` prepended (as the app always did);
    any other scheme (``javascript:``, ``file://``, ``ftp://`` ...) is rejected, as are URLs with
    embedded credentials, control characters or spaces.
    """
    if not isinstance(raw, str):
        raise UnsafeURL("URL must be text")
    s = raw.strip()
    if not s:
        raise UnsafeURL("URL is empty")
    if len(s) > max_len:
        raise UnsafeURL("URL is too long")
    if any(ord(c) < 33 or ord(c) == 127 for c in s):
        raise UnsafeURL("URL contains spaces or control characters")
    m = _EXPLICIT_SCHEME.match(s)
    if m:
        if m.group(1).lower() not in ("http", "https"):
            raise UnsafeURL("Only http(s) URLs are allowed")
    elif _DANGEROUS_SCHEME.match(s):
        raise UnsafeURL("Only http(s) URLs are allowed")
    else:
        s = "https://" + s
    try:
        parts = urllib.parse.urlsplit(s)
        host = parts.hostname
        port = parts.port  # raises ValueError on a bad port
    except ValueError:
        raise UnsafeURL("Malformed URL") from None
    if not host:
        raise UnsafeURL("URL has no host")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURL("URLs with credentials are not allowed")
    if port is not None and not (1 <= port <= 65535):
        raise UnsafeURL("Invalid port")
    return parts.geturl()


def is_public_address(addr):
    """True only for globally routable unicast addresses (v4 or v6)."""
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in ipaddress.ip_network("64:ff9b::/96"):  # NAT64: embedded IPv4
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        elif ip in ipaddress.ip_network("2002::/16"):  # 6to4: embedded IPv4
            ip = ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF)
    return ip.is_global and not ip.is_multicast


def resolve_public(host, port, allow_private=False):
    """Resolve ``host`` and return ``[(family, sockaddr), ...]``; refuse non-public results.

    *All* returned addresses must be public: a host that resolves to a mix of public and private
    addresses is refused rather than gambled on.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURL(f"Could not resolve host ({exc.strerror or exc})") from None
    addrs = [(fam, sa) for fam, _t, _p, _c, sa in infos]
    if not addrs:
        raise UnsafeURL("Could not resolve host")
    if not allow_private:
        for _fam, sa in addrs:
            if not is_public_address(sa[0]):
                raise UnsafeURL("Host resolves to a non-public address")
    return addrs


def _connect_validated(host, port, timeout, allow_private):
    last_exc = None
    for fam, sa in resolve_public(host, port, allow_private):
        sock = socket.socket(fam, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            sock.connect(sa)  # connect to the IP we validated, not to the name again
            return sock
        except OSError as exc:
            last_exc = exc
            sock.close()
    raise last_exc or OSError("connection failed")


def _make_opener(allow_private, sockets):
    """Build an opener that only ever connects to validated addresses. Every socket it opens is
    appended to ``sockets`` so the caller's watchdog can shut them down on timeout."""
    ssl_ctx = ssl.create_default_context()

    class _Conn(http.client.HTTPConnection):
        def connect(self):
            self.sock = _connect_validated(self.host, self.port, self.timeout, allow_private)
            sockets.append(self.sock)

    class _SConn(http.client.HTTPSConnection):
        def connect(self):
            sock = _connect_validated(self.host, self.port, self.timeout, allow_private)
            sockets.append(sock)
            self.sock = ssl_ctx.wrap_socket(sock, server_hostname=self.host)

    class _HTTP(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(_Conn, req)

    class _HTTPS(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(_SConn, req, context=ssl_ctx)

    class _Redirect(urllib.request.HTTPRedirectHandler):
        max_redirections = 4

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urllib.parse.urlsplit(newurl).scheme.lower() not in ("http", "https"):
                raise urllib.error.HTTPError(newurl, code, "redirect to a non-http(s) URL refused", headers, fp)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    # Built from scratch on purpose: no env proxies, and no file:// or ftp:// handlers.
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.UnknownHandler(),
        _HTTP(),
        _HTTPS(),
        urllib.request.HTTPDefaultErrorHandler(),
        _Redirect(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def fetch_page(url, timeout=5, max_bytes=MAX_PAGE_BYTES, deadline=10, allow_private=False):
    """Fetch a public web page and return its text.

    Raises :class:`UnsafeURL` for unsafe targets (including unsafe redirect hops) and the usual
    ``urllib`` / ``OSError`` exceptions for ordinary network failures. The body is capped at
    ``max_bytes``. ``timeout`` limits each socket operation; ``deadline`` is a hard wall-clock limit
    for the *whole* fetch, enforced by a watchdog that shuts the sockets down - a server that
    drip-feeds bytes (resetting per-operation timeouts) cannot hold a serverless function open.
    """
    clean = normalize_http_url(url)
    sockets = []
    opener = _make_opener(allow_private, sockets)
    req = urllib.request.Request(clean, headers={"User-Agent": USER_AGENT})

    timed_out = threading.Event()

    def watchdog():
        timed_out.set()
        for sock in list(sockets):
            try:
                sock.shutdown(socket.SHUT_RDWR)  # wakes any thread blocked in recv()
            except OSError:
                pass

    timer = threading.Timer(deadline, watchdog)
    timer.daemon = True
    timer.start()
    try:
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, UnsafeURL):
                raise exc.reason from None
            raise
        with resp:
            chunks, size = [], 0
            while size < max_bytes:
                chunk = resp.read(min(65536, max_bytes - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
        if timed_out.is_set():
            raise TimeoutError("page took too long to download")
        return b"".join(chunks).decode("utf-8", errors="ignore")
    except UnsafeURL:
        raise
    except Exception:
        if timed_out.is_set():
            raise TimeoutError("page took too long to download") from None
        raise
    finally:
        timer.cancel()


def host_of(url):
    try:
        host = urllib.parse.urlsplit(url if "://" in url else "https://" + url).hostname or ""
    except ValueError:
        return ""
    return host.lower().rstrip(".")


def same_site(url_a, url_b):
    """True if both URLs are on the same site (``www.`` ignored; a subdomain of the other counts)."""
    a, b = host_of(url_a or ""), host_of(url_b or "")
    if not a or not b:
        return False
    a, b = re.sub(r"^www\.", "", a), re.sub(r"^www\.", "", b)
    return a == b or a.endswith("." + b) or b.endswith("." + a)


# --------------------------------------------------------------------------------------
# Request bodies and field validation
# --------------------------------------------------------------------------------------


def read_json_body(headers, rfile, max_bytes=MAX_BODY_BYTES):
    """Read a JSON object from a request, enforcing a size limit. Raises ValidationError."""
    try:
        length = int(headers.get("Content-Length") or 0)
    except ValueError:
        raise ValidationError("Invalid Content-Length") from None
    if length < 0:
        raise ValidationError("Invalid Content-Length")
    if length > max_bytes:
        raise ValidationError("Request body too large", 413)
    raw = rfile.read(length).decode("utf-8", errors="replace") if length else "{}"
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        raise ValidationError("Request body must be valid JSON") from None
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")
    return data


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,80}$")


def clean_text(value, field, max_len, required=False):
    if value is None or value == "":
        if required:
            raise ValidationError(f"{field} is required")
        return ""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValidationError(f"{field} must be text")
    text = _CONTROL.sub("", str(value)).strip()
    if required and not text:
        raise ValidationError(f"{field} is required")
    if len(text) > max_len:
        raise ValidationError(f"{field} is too long (max {max_len} characters)")
    return text


def clean_number(value, field, lo, hi, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ValidationError(f"{field} must be a number")
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a number") from None
    if not math.isfinite(num) or not (lo <= num <= hi):
        raise ValidationError(f"{field} must be between {lo} and {hi}")
    return num


_PRICE_RE = re.compile(r"^(?:CHF|SFR?\.?|FR\.?)?\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:CHF|SFR?\.?|FR\.?)?$", re.I)


def clean_price(value, field="price"):
    """Accept what people type ("9.5", "CHF 9.50", "9,50 Fr.") and normalise to "CHF 9.50"."""
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValidationError(f"{field} must look like CHF 9.50")
    m = _PRICE_RE.match(str(value).strip())
    amount = float(m.group(1).replace(",", ".")) if m else None
    if amount is None or not (0.01 <= amount <= 100):
        raise ValidationError(f"{field} must look like CHF 9.50")
    return f"CHF {amount:.2f}"


def clean_choice(value, field, allowed, default):
    if value is None or value == "":
        return default
    if value not in allowed:
        raise ValidationError(f"{field} must be one of: {', '.join(allowed)}")
    return value


def clean_venue_id(value):
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ValidationError("venueId is missing or malformed")
    return value


def clean_website(value):
    """Empty -> None. Otherwise a normalized http(s) URL (no private-address lookup here)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        url = normalize_http_url(value)
    except UnsafeURL as exc:
        raise ValidationError(f"website: {exc}") from None
    host = host_of(url)
    internal_name = host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan"))
    literal_ip = False
    try:
        ipaddress.ip_address(host)
        literal_ip = True
    except ValueError:
        pass
    if internal_name or (literal_ip and not is_public_address(host)):
        raise ValidationError("website: must be a public website address")
    return url


def clean_serving_format(value):
    """How Guinness is served is something the visitor must say: nothing is assumed when it is missing."""
    if value is None or value == "":
        raise ValidationError("servingFormat is required: say whether Guinness is served (draught, cans_bottles or none)")
    return clean_choice(value, "servingFormat", SERVING_FORMATS, None)


def validate_crowd_report(data):
    """Whitelist + bound everything a visitor may submit as a pint report."""
    venue_id = clean_venue_id(data.get("venueId"))
    note = clean_text(data.get("note"), "note", 500)
    fmt = clean_serving_format(data.get("servingFormat"))
    return {
        "venueId": venue_id,
        "user": clean_text(data.get("user"), "user", 40) or "Swiss Guinness Scout",
        "servingFormat": fmt,
        "price": clean_price(data.get("price")),
        "hasZero": data.get("hasZero") is True,
        "note": note,
    }


def validate_new_venue(data, city_ids):
    """Whitelist + bound everything a visitor may submit when adding a venue."""
    city = data.get("city") or "zurich"
    if city == "all":
        city = "zurich"
    if city not in city_ids:
        raise ValidationError("city is not a known region")
    lat = clean_number(data.get("lat"), "lat", -90, 90, 47.3745)
    lng = clean_number(data.get("lng"), "lng", -180, 180, 8.5385)
    if not (CH_BOUNDS["south"] <= lat <= CH_BOUNDS["north"] and CH_BOUNDS["west"] <= lng <= CH_BOUNDS["east"]):
        raise ValidationError("Venues must be located in Switzerland")
    fmt = clean_serving_format(data.get("servingFormat"))
    return {
        "city": city,
        "name": clean_text(data.get("name"), "name", 100, required=True),
        "category": clean_choice(data.get("category"), "category", CATEGORIES, "pub"),
        "address": clean_text(data.get("address"), "address", 200) or "Switzerland",
        "lat": lat,
        "lng": lng,
        "website": clean_website(data.get("website")),
        "servingFormat": fmt,
        "price": clean_price(data.get("price")),
        "note": clean_text(data.get("note"), "note", 500),
    }


def safe_google_maps_uri(value):
    """Keep a user-supplied Google Maps link only if it really is an https Google Maps URL."""
    if not isinstance(value, str):
        return None
    try:
        parts = urllib.parse.urlsplit(value.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    # google.<tld> where <tld> is one label ("ch"), or "co."/"com." + a country code ("co.uk", "com.au").
    # A loose [a-z.]+ would also accept hosts like google.com.evil.com.
    ok_host = (
        re.match(r"^(www\.)?google\.(?:[a-z]{2,3}|co\.[a-z]{2}|com\.[a-z]{2})$", host) and parts.path.startswith("/maps")
    ) or host in ("maps.app.goo.gl", "goo.gl")
    return value.strip() if parts.scheme == "https" and ok_host else None


# --------------------------------------------------------------------------------------
# Client identity and rate limiting
# --------------------------------------------------------------------------------------


def client_ip(headers, peer_ip, trust_proxy_headers):
    """The caller's IP. Forwarded headers are only believed behind a trusted proxy (Vercel)."""
    if trust_proxy_headers:
        forwarded = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
        for candidate in (forwarded, (headers.get("x-real-ip") or "").strip()):
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                continue
    return peer_ip or "unknown"


class RateLimiter:
    """Fixed-window limiter. ``backend.incr(key, window_seconds)`` must return the new count."""

    def __init__(self, backend, enabled=True):
        self.backend = backend
        self.enabled = enabled

    def check(self, bucket, ip, limit, window_seconds):
        """Return ``(allowed, retry_after_seconds)``. Fails open if the counter store is down."""
        if not self.enabled:
            return True, 0
        try:
            count = self.backend.incr(f"rl:{bucket}:{ip}", window_seconds)
        except Exception:  # noqa: BLE001 - never take the API down because the limiter broke
            return True, 0
        return (count <= limit), window_seconds

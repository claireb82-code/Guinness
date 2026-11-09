/**
 * SSRF-safe fetching of third-party web pages (Node dev server).
 *
 * Mirrors guard.py (the Python server that is deployed to Vercel): only public http(s) hosts are
 * contacted, every redirect hop is re-validated, and downloads are size- and time-limited.
 *
 * Known limitation: the hostname is resolved and checked, then fetch() resolves it again to connect,
 * so a DNS-rebinding attacker could still race the check. guard.py avoids that by connecting to the
 * validated IP; Node's global fetch cannot do that without the `undici` package. This server is
 * for local development - do not expose it publicly.
 */
import dns from 'node:dns/promises';
import net from 'node:net';

const DANGEROUS_SCHEME = /^(javascript|data|file|vbscript|ftp|ftps|gopher|mailto|tel|blob|about|ws|wss|view-source):/i;
const EXPLICIT_SCHEME = /^([a-z][a-z0-9+.-]*):\/\//i;

/** Returns a clean http(s) URL string, or throws. Bare hosts get https:// prepended. */
export function normalizeHttpUrl(raw, maxLen = 300) {
  if (typeof raw !== 'string') throw new Error('URL must be text');
  let s = raw.trim();
  if (!s) throw new Error('URL is empty');
  if (s.length > maxLen) throw new Error('URL is too long');
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u0020\u007f]/.test(s)) throw new Error('URL contains spaces or control characters');
  const m = EXPLICIT_SCHEME.exec(s);
  if (m) {
    if (!['http', 'https'].includes(m[1].toLowerCase())) throw new Error('Only http(s) URLs are allowed');
  } else if (DANGEROUS_SCHEME.test(s)) {
    throw new Error('Only http(s) URLs are allowed');
  } else {
    s = `https://${s}`;
  }
  let u;
  try {
    u = new URL(s);
  } catch {
    throw new Error('Malformed URL');
  }
  if (!u.hostname) throw new Error('URL has no host');
  if (u.username || u.password) throw new Error('URLs with credentials are not allowed');
  return u.href;
}

function ipv4ToInt(ip) {
  return ip.split('.').reduce((acc, part) => acc * 256 + Number(part), 0);
}

const V4_BLOCKS = [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8], ['169.254.0.0', 16],
  ['172.16.0.0', 12], ['192.0.0.0', 24], ['192.0.2.0', 24], ['192.168.0.0', 16], ['198.18.0.0', 15],
  ['198.51.100.0', 24], ['203.0.113.0', 24], ['224.0.0.0', 4], ['240.0.0.0', 4],
];

function isPublicV4(ip) {
  const n = ipv4ToInt(ip);
  return !V4_BLOCKS.some(([base, bits]) => {
    const size = 2 ** (32 - bits);
    const start = ipv4ToInt(base);
    return n >= start && n < start + size;
  });
}

/** True only for globally routable unicast addresses. */
export function isPublicAddress(addr) {
  const ip = String(addr).split('%')[0].toLowerCase();
  if (net.isIPv4(ip)) return isPublicV4(ip);
  if (net.isIPv6(ip)) {
    const mapped = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/.exec(ip);
    if (mapped) return isPublicV4(mapped[1]);
    // ::ffff:7f00:1 style (hex) mapped addresses and NAT64 / 6to4 wrappers around IPv4
    const hexMapped = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(ip);
    if (hexMapped) {
      const hi = parseInt(hexMapped[1], 16);
      const lo = parseInt(hexMapped[2], 16);
      return isPublicV4(`${hi >> 8}.${hi & 255}.${lo >> 8}.${lo & 255}`);
    }
    if (ip === '::' || ip === '::1') return false;
    if (/^f[cd]/.test(ip) || /^fe[89ab]/.test(ip) || /^ff/.test(ip)) return false; // ULA, link-local, multicast
    if (/^64:ff9b:/.test(ip) || /^2002:/.test(ip)) return false; // IPv4 embedded: refuse rather than decode
    return true;
  }
  return false;
}

export async function assertPublicHost(hostname, lookup = dns.lookup) {
  const bare = hostname.replace(/^\[|\]$/g, '');
  const addrs = net.isIP(bare) ? [{ address: bare }] : await lookup(bare, { all: true });
  if (!addrs.length || addrs.some((a) => !isPublicAddress(a.address))) {
    throw new Error('Host resolves to a non-public address');
  }
}

/**
 * Fetch a public page and return { url, text }. Throws on unsafe targets or HTTP errors.
 * @param {object} [o] { timeoutMs, maxBytes, maxRedirects, fetchImpl, lookup, allowPrivate, headers }
 */
export async function fetchPublicPage(url, o = {}) {
  const {
    timeoutMs = 6500,
    maxBytes = 1_500_000,
    maxRedirects = 4,
    fetchImpl = fetch,
    lookup = dns.lookup,
    allowPrivate = false,
    headers = {},
  } = o;
  const deadline = Date.now() + timeoutMs;
  let current = normalizeHttpUrl(url);
  for (let hop = 0; hop <= maxRedirects; hop++) {
    const u = new URL(current);
    if (!/^https?:$/.test(u.protocol)) throw new Error('Only http(s) URLs are allowed');
    if (!allowPrivate) await assertPublicHost(u.hostname, lookup);
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw new Error('page took too long to download');

    const res = await fetchImpl(u, { redirect: 'manual', signal: AbortSignal.timeout(remaining), headers });
    if (res.status >= 300 && res.status < 400 && res.headers.get('location')) {
      current = normalizeHttpUrl(new URL(res.headers.get('location'), u).toString());
      continue;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const type = res.headers.get('content-type') || '';
    if (!type.includes('text/html') && !type.includes('text/plain')) throw new Error('unsupported content type');
    const reader = res.body.getReader();
    const chunks = [];
    let size = 0;
    for (;;) {
      if (Date.now() > deadline) {
        await reader.cancel();
        throw new Error('page took too long to download');
      }
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      chunks.push(value);
      if (size >= maxBytes) {
        await reader.cancel();
        break;
      }
    }
    return { url: current, text: Buffer.concat(chunks).subarray(0, maxBytes).toString('utf8') };
  }
  throw new Error('too many redirects');
}

import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeHttpUrl, isPublicAddress, assertPublicHost, fetchPublicPage } from '../../server/services/safeFetch.js';

const publicLookup = async () => [{ address: '93.184.216.34' }];
const html = (body, headers = {}) => new Response(body, { status: 200, headers: { 'content-type': 'text/html', ...headers } });

test('normalizeHttpUrl: bare hosts get https, other schemes are refused', () => {
  assert.equal(normalizeHttpUrl('example.com/menu'), 'https://example.com/menu');
  assert.equal(normalizeHttpUrl(' http://example.com '), 'http://example.com/');
  for (const bad of ['javascript:alert(1)', 'JaVaScRiPt:1', 'data:text/html,x', 'file:///etc/passwd', 'ftp://x.com', 'view-source:https://x.com']) {
    assert.throws(() => normalizeHttpUrl(bad), /http\(s\)/, bad);
  }
});

test('normalizeHttpUrl: malformed input is refused', () => {
  for (const bad of ['', '   ', null, 5, 'http://', 'https://exa mple.com', 'http://u:p@example.com/', 'a'.repeat(400), 'http://a.com/\nHost: x']) {
    assert.throws(() => normalizeHttpUrl(bad), undefined, String(bad));
  }
});

test('isPublicAddress: private, loopback, link-local, CGNAT, mapped and special addresses are not public', () => {
  for (const ip of ['127.0.0.1', '10.0.0.1', '172.16.5.5', '172.31.255.255', '192.168.0.1', '169.254.169.254', '100.64.0.1', '0.0.0.0',
    '224.0.0.1', '255.255.255.255', '::1', '::', 'fe80::1', 'fd00::1', 'ff02::1', '::ffff:127.0.0.1', '::ffff:10.0.0.1', '::ffff:7f00:1',
    '64:ff9b::7f00:1', '2002:7f00:1::1', 'nonsense']) {
    assert.equal(isPublicAddress(ip), false, ip);
  }
});

test('isPublicAddress: public addresses', () => {
  for (const ip of ['8.8.8.8', '93.184.216.34', '172.32.0.1', '2606:4700:4700::1111', '::ffff:8.8.8.8']) {
    assert.equal(isPublicAddress(ip), true, ip);
  }
});

test('assertPublicHost: refuses hosts that resolve to private addresses, including mixed answers', async () => {
  await assert.rejects(assertPublicHost('x.example', async () => [{ address: '10.0.0.5' }]), /non-public/);
  await assert.rejects(assertPublicHost('x.example', async () => [{ address: '8.8.8.8' }, { address: '127.0.0.1' }]), /non-public/);
  await assert.rejects(assertPublicHost('169.254.169.254'), /non-public/);
  await assert.rejects(assertPublicHost('[::1]'), /non-public/);
  await assert.doesNotReject(assertPublicHost('x.example', publicLookup));
});

test('fetchPublicPage: fetches html and never contacts a private host', async () => {
  const calls = [];
  const fetchImpl = async (u) => (calls.push(String(u)), html('<p>hi</p>'));
  assert.equal((await fetchPublicPage('https://ok.example/', { fetchImpl, lookup: publicLookup })).text, '<p>hi</p>');
  calls.length = 0;
  await assert.rejects(fetchPublicPage('http://internal.example/', { fetchImpl, lookup: async () => [{ address: '10.0.0.5' }] }), /non-public/);
  assert.deepEqual(calls, []);
});

test('fetchPublicPage: every redirect hop is re-validated', async () => {
  const calls = [];
  const lookup = async (host) => [{ address: host === 'internal.example' ? '192.168.1.1' : '93.184.216.34' }];
  const fetchImpl = async (u) => {
    calls.push(String(u));
    return String(u).startsWith('https://public.example')
      ? new Response(null, { status: 302, headers: { location: 'http://internal.example/admin' } })
      : html('SECRET');
  };
  await assert.rejects(fetchPublicPage('https://public.example/', { fetchImpl, lookup }), /non-public/);
  assert.deepEqual(calls, ['https://public.example/']);
});

test('fetchPublicPage: redirects to non-http schemes and redirect loops are refused', async () => {
  const toFile = async () => new Response(null, { status: 302, headers: { location: 'file:///etc/passwd' } });
  await assert.rejects(fetchPublicPage('https://a.example/', { fetchImpl: toFile, lookup: publicLookup }), /http\(s\)/);
  const loop = async () => new Response(null, { status: 302, headers: { location: '/loop' } });
  await assert.rejects(fetchPublicPage('https://a.example/', { fetchImpl: loop, lookup: publicLookup }), /too many redirects/);
});

test('fetchPublicPage: follows a normal redirect and reports the final URL', async () => {
  const fetchImpl = async (u) => (String(u) === 'https://a.example/' ? new Response(null, { status: 301, headers: { location: '/menu' } }) : html('landed'));
  const r = await fetchPublicPage('https://a.example/', { fetchImpl, lookup: publicLookup });
  assert.deepEqual([r.url, r.text], ['https://a.example/menu', 'landed']);
});

test('fetchPublicPage: rejects non-text content, HTTP errors, and caps the body', async () => {
  const pdf = async () => new Response('%PDF', { headers: { 'content-type': 'application/pdf' } });
  await assert.rejects(fetchPublicPage('https://a.example/', { fetchImpl: pdf, lookup: publicLookup }), /content type/);
  const missing = async () => new Response('no', { status: 404, headers: { 'content-type': 'text/html' } });
  await assert.rejects(fetchPublicPage('https://a.example/', { fetchImpl: missing, lookup: publicLookup }), /HTTP 404/);
  const big = async () => html('a'.repeat(50_000));
  const r = await fetchPublicPage('https://a.example/', { fetchImpl: big, lookup: publicLookup, maxBytes: 1000 });
  assert.ok(r.text.length <= 1000);
});

test('fetchPublicPage: the wall-clock deadline applies', async () => {
  // AbortSignal.timeout() timers are unref'd, so keep the loop alive the way a real socket would.
  const keepAlive = setTimeout(() => {}, 2000);
  const hang = (u, { signal }) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))));
  const started = Date.now();
  await assert.rejects(fetchPublicPage('https://a.example/', { fetchImpl: hang, lookup: publicLookup, timeoutMs: 50 }));
  clearTimeout(keepAlive);
  assert.ok(Date.now() - started < 1500);
});

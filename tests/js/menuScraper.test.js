import test from 'node:test';
import assert from 'node:assert/strict';
import { scrapeVenueMenuForGuinness } from '../../server/services/menuScraper.js';

const publicLookup = async () => [{ address: '93.184.216.34' }];
const page = (body) => new Response(`<html><body>${body}</body></html>`, { headers: { 'content-type': 'text/html' } });
const opts = (pages, calls = []) => ({
  lookup: publicLookup,
  fetchImpl: async (u) => {
    calls.push(String(u));
    return pages[String(u)] ? page(pages[String(u)]) : new Response('nope', { status: 404, headers: { 'content-type': 'text/html' } });
  },
});

test('finds Guinness on a followed menu page and extracts the price', async () => {
  const pages = {
    'https://pub.example/': '<a href="/drinks">Drinks</a> Welcome to our pub',
    'https://pub.example/drinks': '<li>Guinness Draught CHF 9.50</li><li>Heineken</li>',
  };
  const r = await scrapeVenueMenuForGuinness('pub.example', null, opts(pages));
  assert.equal(r.checked, true);
  assert.equal(r.foundOnMenu, true);
  assert.equal(r.extractedPrice, 'CHF 9.50');
  assert.ok(r.typesFound.includes('Guinness Draught (On Tap)'));
});

test('reports "no mention" for a readable site without Guinness', async () => {
  const r = await scrapeVenueMenuForGuinness('https://pasta.example/', null, opts({ 'https://pasta.example/': 'Carbonara, Tiramisu' }));
  assert.equal(r.checked, true);
  assert.equal(r.foundOnMenu, false);
});

test('unsafe URLs are reported as "not scanned" and never fetched', async () => {
  const calls = [];
  for (const url of ['javascript:alert(1)', 'file:///etc/passwd', 'ftp://x.example', 'http://169.254.169.254/latest/meta-data/', 'http://127.0.0.1:3000/api/config', 'http://[::1]/']) {
    const r = await scrapeVenueMenuForGuinness(url, null, opts({}, calls));
    assert.equal(r.checked, false, url);
    assert.equal(r.foundOnMenu, false, url);
    assert.equal(r.mode, 'blocked', url);
    assert.match(r.snippets[0], /not scanned/, url);
  }
  assert.deepEqual(calls, []);
});

test('a hostname that resolves to an internal address is not scanned', async () => {
  const calls = [];
  const r = await scrapeVenueMenuForGuinness('https://sneaky.example/', null, { ...opts({}, calls), lookup: async () => [{ address: '10.1.2.3' }] });
  assert.equal(r.mode, 'blocked');
  assert.deepEqual(calls, []);
});

test('a menu link that points at an internal host is skipped, not followed', async () => {
  const lookup = async (host) => [{ address: host === 'internal.example' ? '10.0.0.9' : '93.184.216.34' }];
  const calls = [];
  const fetchImpl = async (u) => (calls.push(String(u)), page(String(u) === 'https://pub.example/' ? '<a href="https://internal.example/menu">Menu</a> hi' : 'Guinness'));
  const r = await scrapeVenueMenuForGuinness('https://pub.example/', null, { lookup, fetchImpl });
  assert.equal(r.foundOnMenu, false);
  assert.ok(!calls.some((c) => c.includes('internal.example')));
});

test('no URL -> not checked', async () => {
  const r = await scrapeVenueMenuForGuinness('', null);
  assert.equal(r.checked, false);
});

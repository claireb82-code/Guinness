// Browser tests of the real page (public/standalone.html) against the real Python server.
//   npm run test:e2e        (needs Playwright + Chromium; set PLAYWRIGHT_PATH if it is not resolvable)
// Skipped automatically when Playwright is unavailable, so `npm test` never depends on a browser.
// The Leaflet map library normally comes from a CDN; it is replaced by an inert stub (these tests
// are about the sidebar/drawer behaviour, not map rendering).
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import net from 'node:net';

const require = createRequire(import.meta.url);
let chromium = null;
for (const spec of [process.env.PLAYWRIGHT_PATH, 'playwright'].filter(Boolean)) {
  try {
    ({ chromium } = require(spec));
    break;
  } catch {
    /* try next */
  }
}

const freePort = () => new Promise((resolve) => { const s = net.createServer().listen(0, () => { const { port } = s.address(); s.close(() => resolve(port)); }); });

const evil = { id: 'evil-1', city: 'zurich', name: 'Evil Pub <img src=x onerror=window.pwned=1>', category: 'pub', address: '1 Bad St', lat: 47.37, lng: 8.54,
  website: 'javascript:window.pwned=1', menuUrl: 'javascript:window.pwned=1', googleRating: 4.5, googleReviewCount: 3,
  menuCheck: { checked: true, foundOnMenu: true, typesFound: ['Guinness Draught (On Tap)'], snippets: ['<b>Guinness</b> <script>window.pwned=1</script>'] }, crowdCheck: {}, reviewCheck: {} };
const good = { ...evil, id: 'good-1', name: 'Good Pub', website: 'https://good-pub.example/', menuUrl: 'https://good-pub.example/menu', lat: 47.38,
  menuCheck: { checked: false, foundOnMenu: false, typesFound: [], snippets: [] } };

const leafletStub = `
  const chain = () => new Proxy(function () {}, { get: (t, p) => (p === Symbol.toPrimitive ? () => '' : p === 'then' ? undefined : chain()), apply: () => chain(), construct: () => chain() });
  window.L = chain();`;

let server, base, browser;

test.before(async () => {
  if (!chromium) return;
  const port = await freePort();
  base = `http://127.0.0.1:${port}`;
  server = spawn('python3', ['app_server.py'], { env: { ...process.env, PORT: String(port), RATE_LIMIT_DISABLED: '1' }, stdio: 'ignore' });
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`${base}/api/config`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
  }
  browser = await chromium.launch();
});

test.after(async () => {
  await browser?.close();
  server?.kill();
});

async function openPage({ dialogs = [] } = {}) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('dialog', async (d) => { dialogs.push(d.message()); await d.dismiss(); });
  await page.route('https://unpkg.com/**', (r) => r.fulfill({ contentType: 'text/javascript', body: leafletStub }));
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.route('**/api/venues*', async (route) => {
    const resp = await route.fetch();
    const json = await resp.json();
    json.venues = [evil, good, ...json.venues.slice(0, 3)];
    route.fulfill({ response: resp, json });
  });
  await page.goto(`${base}/`);
  await page.waitForSelector('.venue-card', { timeout: 15000 });
  return { page, errors, dialogs };
}

const skip = () => !chromium && 'Playwright is not installed';

test('the page loads real data without script errors', { skip: skip() }, async () => {
  const { page, errors } = await openPage();
  assert.ok((await page.locator('.venue-card').count()) >= 3);
  assert.deepEqual(errors, []);
  await page.close();
});

test('a venue with a javascript: website gets no link, and hostile text stays inert', { skip: skip() }, async () => {
  const { page, errors } = await openPage();
  await page.click('.venue-card[data-vid="evil-1"]');
  await page.waitForSelector('text=Online Menu & Website Check');
  assert.equal(await page.locator('a[href^="javascript" i]').count(), 0);
  assert.equal(await page.locator('a:has-text("Venue Website")').count(), 0);
  assert.equal(await page.evaluate(() => window.pwned), undefined, 'injected script ran');
  assert.match(await page.locator('text=Evil Pub').first().textContent(), /<img/); // shown as text
  assert.deepEqual(errors, []);
  await page.close();
});

test('a normal website gets a hardened external link', { skip: skip() }, async () => {
  const { page } = await openPage();
  await page.click('.venue-card[data-vid="good-1"]');
  const link = await page.locator('a:has-text("Venue Website")').first().evaluate((a) => ({ href: a.href, rel: a.rel, target: a.target }));
  assert.deepEqual(link, { href: 'https://good-pub.example/', rel: 'noopener noreferrer', target: '_blank' });
  await page.close();
});

test('a rejected submission shows the server\'s reason instead of failing silently', { skip: skip() }, async () => {
  const { page, dialogs } = await openPage();
  await page.route('**/api/crowd-report', (r) => r.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ error: 'note is too long (max 500 characters)' }) }));
  await page.click('.venue-card[data-vid="good-1"]');
  await page.click('#btn-toggle-report');
  await page.click('#form-crowd-report button[type=submit]');
  await page.waitForFunction(() => true);
  await new Promise((r) => setTimeout(r, 400));
  assert.deepEqual(dialogs, ['note is too long (max 500 characters)']);
  await page.close();
});

test('"database not configured" is explained to the user', { skip: skip() }, async () => {
  const { page, dialogs } = await openPage();
  await page.route('**/api/crowd-report', (r) => r.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Community submissions are not enabled on this deployment' }) }));
  await page.click('.venue-card[data-vid="good-1"]');
  await page.click('#btn-toggle-report');
  await page.click('#form-crowd-report button[type=submit]');
  await new Promise((r) => setTimeout(r, 400));
  assert.match(dialogs[0], /not enabled/);
  await page.close();
});

test('"scan all" stops at the first rate-limit response and tells the user', { skip: skip() }, async () => {
  const { page, dialogs } = await openPage();
  let calls = 0;
  await page.route('**/api/scan-menu', (r) => { calls += 1; r.fulfill({ status: 429, contentType: 'application/json', body: JSON.stringify({ error: 'Too many requests. Please slow down and try again later.' }) }); });
  await page.click('#btn-batch-scan');
  await new Promise((r) => setTimeout(r, 600));
  assert.equal(calls, 1, 'must not keep hammering after a 429');
  assert.match(dialogs[0], /Too many requests/);
  await page.close();
});

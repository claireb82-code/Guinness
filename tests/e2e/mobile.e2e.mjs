// Phone / tablet / desktop layout of the real React app (built dist/ + Python API + real Leaflet) and of the
// standalone page. Run with: npm run test:e2e  (needs Playwright; skipped automatically without it).
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadPlaywright, startApp, routeOffline, haveLeaflet, haveBuild } from './helpers.mjs';

const pw = loadPlaywright();
const unavailable = !pw ? 'Playwright is not installed' : !haveLeaflet() ? 'leaflet dev dependency missing (npm install)' : !haveBuild() ? 'dist/ missing (npm run build)' : false;

let app;
let browser;
test.before(async () => {
  if (unavailable) return;
  app = await startApp();
  browser = await pw.chromium.launch();
});
test.after(async () => {
  await browser?.close();
  app?.stop();
});

const PHONES = ['iPhone SE', 'iPhone 13', 'Pixel 5'];

async function open(base, { device, viewport, waitFor = '.venue-card' } = {}) {
  const context = await browser.newContext(device ? { ...pw.devices[device], deviceScaleFactor: 1 } : { viewport, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await routeOffline(page);
  await page.goto(`${base}/`);
  await page.waitForSelector(waitFor, { timeout: 20000 });
  await page.waitForTimeout(300);
  return { page, context, errors, tap: (target, options) => (device ? page.locator(target).first().tap(options) : page.locator(target).first().click(options)) };
}

const box = (page, selector) => page.locator(selector).first().boundingBox();
const viewportSize = (page) => page.evaluate(() => ({ w: document.documentElement.clientWidth, h: window.innerHeight }));
const skip = () => unavailable;

for (const device of ['iPhone SE', 'iPhone 13', 'Pixel 5', 'iPhone 13 landscape', 'iPad Mini']) {
  test(`${device}: the page never scrolls sideways and has no script errors`, { skip: skip() }, async () => {
    const { page, context, errors } = await open(app.react, { device });
    const { scrollW, clientW } = await page.evaluate(() => ({ scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth }));
    assert.equal(scrollW, clientW, `content is ${scrollW}px wide in a ${clientW}px screen`);
    assert.deepEqual(errors, []);
    await context.close();
  });
}

test('phone: the venue list comes first and nothing covers it', { skip: skip() }, async () => {
  const { page, context } = await open(app.react, { device: 'iPhone 13' });
  assert.equal(await page.locator('.sidebar-list').isVisible(), true);
  assert.equal(await page.locator('.detail-drawer').count(), 0, 'the details sheet must not open by itself on a phone');
  assert.equal(await page.locator('.mobile-nav').isVisible(), true);
  assert.deepEqual(await page.$$eval('.mobile-nav button', (b) => b.map((x) => x.querySelector('span').textContent)), ['List', 'Map', 'Filters']);
  assert.equal(await page.locator('.toolbar-strip').isVisible(), false, 'filters live in a sheet until opened');
  await context.close();
});

test('phone: tapping a venue opens a full-screen sheet, and closing it returns to the list', { skip: skip() }, async () => {
  const { page, context, tap } = await open(app.react, { device: 'iPhone 13' });
  await tap('.venue-card >> nth=0'); // fails if Leaflet markers sit on top of the list and swallow the tap
  await page.waitForSelector('.detail-drawer');
  await page.waitForTimeout(350); // let the 0.2s slide-up finish before measuring
  const { w, h } = await viewportSize(page);
  const sheet = await box(page, '.detail-drawer');
  assert.deepEqual([Math.round(sheet.x), Math.round(sheet.y), Math.round(sheet.width), Math.round(sheet.height)], [0, 0, w, h]);
  const close = await box(page, '.drawer-close');
  assert.ok(close.width >= 44 && close.height >= 44, `close button is ${close.width}x${close.height}`);
  await tap('.drawer-close');
  assert.equal(await page.locator('.detail-drawer').count(), 0);
  assert.equal(await page.locator('.sidebar-list').isVisible(), true);
  await context.close();
});

test('phone: the Map tab shows a working map and the List tab brings the list back', { skip: skip() }, async () => {
  const { page, context, tap } = await open(app.react, { device: 'iPhone 13' });
  await tap('.mobile-nav button:has-text("Map")');
  assert.equal(await page.locator('.sidebar-list').isVisible(), false);
  const map = await box(page, '.leaflet-container');
  assert.ok(map.width >= 300 && map.height >= 300, `map is ${map.width}x${map.height}`);
  assert.equal(await page.getAttribute('.mobile-nav button:has-text("Map")', 'aria-current'), 'page');
  assert.ok((await page.locator('.leaflet-marker-icon').count()) > 5, 'markers are drawn');
  await tap('.leaflet-marker-icon', { force: true }); // markers overlap near Zurich; whichever is on top opens its venue
  await page.waitForSelector('.detail-drawer');
  await tap('.drawer-close');
  await tap('.mobile-nav button:has-text("List")');
  assert.equal(await page.locator('.sidebar-list').isVisible(), true);
  assert.equal(await page.getAttribute('.mobile-nav button:has-text("List")', 'aria-current'), 'page');
  await context.close();
});

test('phone: the filters sheet opens from the bottom bar and changes the list', { skip: skip() }, async () => {
  const { page, context, tap } = await open(app.react, { device: 'iPhone 13' });
  const count = async () => Number(await page.textContent('.nav-count'));
  const before = await count();
  assert.equal(await page.locator('.nav-dot').count(), 0);
  await tap('.mobile-nav button:has-text("Filters")');
  await page.waitForSelector('.toolbar-strip.open');
  await page.waitForTimeout(350);
  const sheet = await box(page, '.toolbar-strip');
  const { w, h } = await viewportSize(page);
  assert.ok(Math.abs(sheet.width - w) <= 1 && sheet.y + sheet.height <= h + 1 && sheet.y > 0, 'a sheet pinned to the bottom, not full screen');
  await tap('.toolbar-strip .filter-pill:has-text("Show All")');
  await page.waitForTimeout(150);
  assert.ok((await count()) > before, 'showing all venues grows the count');
  await tap('.sheet-header .btn-gold'); // "Show N venues" closes the sheet
  await page.waitForTimeout(350);
  assert.equal(await page.locator('.toolbar-strip').isVisible(), false);
  assert.equal(await page.locator('.nav-dot').count(), 1, 'a dot reminds you that filters are not the default');
  await tap('.mobile-nav button:has-text("Filters")');
  await page.waitForSelector('.toolbar-strip.open');
  await page.mouse.click(195, 60); // tapping the dimmed area closes it
  await page.waitForTimeout(350);
  assert.equal(await page.locator('.toolbar-strip').isVisible(), false);
  await context.close();
});

test('phone: every visible control is at least 44px, and form fields are 16px (no iOS zoom)', { skip: skip() }, async () => {
  const { page, context, tap } = await open(app.react, { device: 'iPhone 13' });
  const tooSmall = () =>
    page.evaluate(() =>
      [...document.querySelectorAll('button, a, input, select, textarea, [role=button]')]
        .filter((e) => !e.closest('.leaflet-container') && !e.closest('.toolbar-strip:not(.open)'))
        .map((e) => ({ e, r: e.getBoundingClientRect(), cs: getComputedStyle(e) }))
        .filter(({ r, cs }) => r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && r.top < innerHeight && r.bottom > 0)
        .filter(({ r, e }) => r.height < 43.5 || (e.tagName === 'BUTTON' && r.width < 43.5))
        .map(({ e, r }) => `${e.tagName}.${e.className} ${Math.round(r.width)}x${Math.round(r.height)} "${(e.textContent || e.getAttribute('aria-label') || '').trim().slice(0, 24)}"`),
    );
  assert.deepEqual(await tooSmall(), [], 'list view');
  await tap('.header-actions .btn-outline');
  await page.waitForSelector('.modal-card');
  assert.deepEqual(await tooSmall(), [], 'add-venue sheet');
  const smallText = await page.$$eval('.modal-card .stout-input, .modal-card .stout-select, .modal-card .stout-textarea, .header-search input', (els) =>
    els.map((e) => parseFloat(getComputedStyle(e).fontSize)).filter((px) => px < 16));
  assert.deepEqual(smallText, [], 'fields below 16px make iOS zoom the page when focused');
  await context.close();
});

test('phone: the add-venue form is a full-width bottom sheet with a single column', { skip: skip() }, async () => {
  const { page, context, tap } = await open(app.react, { device: 'iPhone SE' });
  await tap('.header-actions .btn-outline');
  await page.waitForSelector('.modal-card');
  const { w, h } = await viewportSize(page);
  const card = await box(page, '.modal-card');
  assert.ok(Math.abs(card.width - w) <= 1, `card is ${card.width}px in a ${w}px screen`);
  assert.ok(Math.abs(card.y + card.height - h) <= 1, 'anchored to the bottom');
  const columns = await page.$$eval('.modal-card .stack-sm', (els) => els.map((e) => getComputedStyle(e).gridTemplateColumns.split(' ').length));
  assert.ok(columns.length >= 2 && columns.every((n) => n === 1), `form grids: ${columns}`);
  assert.equal((await page.evaluate(() => document.documentElement.scrollWidth)) <= w, true);
  await tap('.modal-close');
  assert.equal(await page.locator('.modal-card').count(), 0);
  await context.close();
});

test('landscape phone gets the phone layout, not the cramped desktop one', { skip: skip() }, async () => {
  const { page, context } = await open(app.react, { device: 'iPhone 13 landscape' });
  assert.equal(await page.locator('.mobile-nav').isVisible(), true);
  assert.equal(await page.locator('.detail-drawer').count(), 0);
  const list = await box(page, '.sidebar-list');
  assert.ok(list.height >= 200, `list is only ${list.height}px tall`);
  await context.close();
});

for (const [w, h] of [[1024, 768], [1280, 720], [1920, 1080]]) {
  test(`desktop ${w}x${h}: three panes side by side, no bottom bar, search and cities reachable`, { skip: skip() }, async () => {
    const { page, context } = await open(app.react, { viewport: { width: w, height: h } });
    assert.equal(await page.locator('.mobile-nav').isVisible(), false);
    assert.equal(await page.locator('.sheet-header').isVisible(), false);
    assert.equal(await page.locator('.toolbar-strip').isVisible(), true, 'filters are shown inline on desktop');
    await page.waitForSelector('.detail-drawer'); // the first venue opens in the side panel
    const [list, map, drawer] = await Promise.all(['.sidebar-list', '.map-pane', '.detail-drawer'].map((s) => box(page, s)));
    assert.ok(list.x + list.width <= map.x + 1, 'list is left of the map');
    assert.ok(drawer.x >= map.x + map.width - 1 || drawer.x >= list.x + list.width, 'details are beside, not on top of, the list');
    const search = await box(page, '.header-search input');
    assert.ok(search.x >= 0 && search.x + search.width <= w, 'the search box is on screen');
    const { scrollW, clientW } = await page.evaluate(() => ({ scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth }));
    assert.equal(scrollW, clientW);
    await context.close();
  });
}

test('standalone page on a phone: no sideways scroll, list not covered, details are a full-screen sheet', { skip: skip() }, async () => {
  const { page, context, errors, tap } = await open(app.standalone, { device: 'iPhone 13' });
  const { scrollW, clientW } = await page.evaluate(() => ({ scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth }));
  assert.equal(scrollW, clientW);
  assert.equal(await page.locator('.detail-drawer').count(), 0, 'no sheet on load');
  const map = await box(page, '.map-pane');
  assert.ok(map.height >= 150 && map.width >= 300, `map is ${map.width}x${map.height}`);
  const header = await box(page, '.top-header');
  assert.ok(header.height <= 230, `header takes ${header.height}px of a phone screen`);
  await tap('.venue-card >> nth=0');
  await page.waitForSelector('.detail-drawer');
  await page.waitForTimeout(350);
  const { w, h } = await viewportSize(page);
  const sheet = await box(page, '.detail-drawer');
  assert.deepEqual([Math.round(sheet.width), Math.round(sheet.height)], [w, h]);
  assert.deepEqual(errors, []);
  await context.close();
});

// Map gestures in the built React app (real Leaflet). A double-click must zoom the map; a single click on empty map
// still offers to add a venue there, but only once it is clear the click was not the first half of a double-click.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadPlaywright, startApp, routeOffline, haveLeaflet, haveBuild } from './helpers.mjs';

const pw = loadPlaywright();
const unavailable = !pw ? 'Playwright is not installed' : !haveLeaflet() ? 'leaflet dev dependency missing (npm install)' : !haveBuild() ? 'dist/ missing (npm run build)' : false;
const skip = () => unavailable;

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

async function open() {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  await context.addInitScript(() => localStorage.setItem('guinness.nearMe', '{"mode":"off"}'));
  const page = await context.newPage();
  await routeOffline(page);
  await page.goto(`${app.react}/`);
  await page.waitForSelector('.venue-card', { state: 'attached', timeout: 20000 });
  await page.waitForSelector('.leaflet-tile', { state: 'attached' });
  await page.waitForTimeout(1500); // the opening fly-to animation
  return { page, context };
}

// The zoom level, read from the tiles Leaflet asked for (/z/x/y.png).
const zoomOf = (page) =>
  page.$$eval('img.leaflet-tile', (imgs) => Math.max(...imgs.map((i) => Number(i.src.match(/\/(\d+)\/\d+\/\d+\.png/)?.[1] ?? 0))));

// A point on the map that is plain map (not a pin, a control or a panel).
async function emptySpot(page) {
  const box = await page.locator('.leaflet-container').first().boundingBox();
  for (const [fx, fy] of [[0.5, 0.75], [0.4, 0.6], [0.6, 0.85], [0.3, 0.7], [0.7, 0.5]]) {
    const x = box.x + box.width * fx;
    const y = box.y + box.height * fy;
    const plain = await page.evaluate(([px, py]) => {
      const el = document.elementFromPoint(px, py);
      return !!el && !el.closest('.leaflet-marker-icon, .leaflet-control, .detail-drawer, .map-legend, .leaflet-popup');
    }, [x, y]);
    if (plain) return { x, y };
  }
  throw new Error('no empty spot on the map');
}

test('regression: double-clicking the map zooms in and does not open the add-venue form', { skip: skip() }, async () => {
  const { page, context } = await open();
  const before = await zoomOf(page);
  const { x, y } = await emptySpot(page);
  await page.mouse.dblclick(x, y);
  await page.waitForTimeout(1200); // zoom animation + the delay before a single click is acted on
  assert.ok((await zoomOf(page)) > before, `zoomed in from ${before}`);
  assert.equal(await page.locator('.modal-card, [role="dialog"]').count(), 0, 'no add-venue form');
  await context.close();
});

test('a single click on empty map still offers to add a venue there', { skip: skip() }, async () => {
  const { page, context } = await open();
  const { x, y } = await emptySpot(page);
  await page.mouse.click(x, y);
  await page.waitForSelector('.modal-card, [role="dialog"]', { timeout: 3000 });
  await context.close();
});

test('regression: the same holds on the standalone page', { skip: skip() }, async () => {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await routeOffline(page);
  await page.goto(`${app.standalone}/`);
  await page.waitForSelector('.leaflet-tile', { state: 'attached', timeout: 20000 });
  await page.waitForTimeout(1500);
  const before = await zoomOf(page);
  const { x, y } = await emptySpot(page);
  await page.mouse.dblclick(x, y);
  await page.waitForTimeout(1200);
  assert.ok((await zoomOf(page)) > before, `zoomed in from ${before}`);
  assert.equal(await page.locator('#add-venue-form, .modal-card, [role="dialog"], .modal-backdrop').count(), 0, 'no add-venue form');
  await page.mouse.click(x + 40, y);
  await page.waitForSelector('.modal-card, [role="dialog"], .modal-backdrop, #add-venue-form', { timeout: 3000 });
  await context.close();
});

// Leaflet's panes and controls use z-index 400-1000; a dialog has to paint above all of them.
async function dialogIsOnTop(page) {
  return page.evaluate(() => {
    const card = document.querySelector('.modal-card');
    const backdrop = document.querySelector('.modal-backdrop');
    const r = card.getBoundingClientRect();
    const centre = document.elementFromPoint(r.left + r.width / 2, r.top + 24);
    // the map's own zoom buttons must be covered by the backdrop, not painted over it
    const zoom = document.querySelector('.leaflet-control-zoom-in').getBoundingClientRect();
    const overZoom = document.elementFromPoint(zoom.left + zoom.width / 2, zoom.top + zoom.height / 2);
    // and so must the scan buttons / legend / map switcher that float on the map
    const floating = [...document.querySelectorAll('.map-legend, .map-scan-buttons, #map-style-switcher')]
      .map((el) => el.getBoundingClientRect())
      .filter((b) => b.width > 0)
      .map((b) => document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2));
    const covered = (el) => !!el && !!el.closest('.modal-backdrop');
    return { cardOnTop: !!centre && !!centre.closest('.modal-card'), zoomCovered: covered(overZoom), floatingCovered: floating.every(covered), hasBackdrop: !!backdrop };
  });
}

test('regression: the "Add / Check Venue" form opens in front of the map, not behind it', { skip: skip() }, async () => {
  const { page, context } = await open();
  await page.locator('button:has-text("Add / Check Venue")').first().click();
  await page.waitForSelector('.modal-card');
  assert.deepEqual(await dialogIsOnTop(page), { cardOnTop: true, zoomCovered: true, floatingCovered: true, hasBackdrop: true });
  await context.close();
});

test('regression: the same on the standalone page', { skip: skip() }, async () => {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await routeOffline(page);
  await page.goto(`${app.standalone}/`);
  await page.waitForSelector('.leaflet-tile', { state: 'attached', timeout: 20000 });
  await page.waitForTimeout(1000);
  await page.locator('#btn-open-add').click();
  await page.waitForSelector('.modal-card');
  assert.deepEqual(await dialogIsOnTop(page), { cardOnTop: true, zoomCovered: true, floatingCovered: true, hasBackdrop: true });
  await context.close();
});

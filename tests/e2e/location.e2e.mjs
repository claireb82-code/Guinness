// Venues added through the form land at their address, not wherever the map happened to be centred. The address lookup
// is a local fake of Nominatim; the app, the API and the database file are real (and private to this test run).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { loadPlaywright, startApp, routeOffline, haveLeaflet, haveBuild, freePort } from './helpers.mjs';

const pw = loadPlaywright();
const unavailable = !pw ? 'Playwright is not installed' : !haveLeaflet() ? 'leaflet dev dependency missing (npm install)' : !haveBuild() ? 'dist/ missing (npm run build)' : false;
const skip = () => unavailable;

const DAVOS = { lat: 46.80282, lng: 9.83572 };
const ADDRESS = 'Promenade 119, 7270 Davos';

let app;
let browser;
let geo;
let geoQueries = [];
let tmp;
test.before(async () => {
  if (unavailable) return;
  geo = http.createServer((req, res) => {
    const q = new URL(req.url, 'http://x').searchParams.get('q') || '';
    geoQueries.push(q);
    const body = q.toLowerCase().startsWith('promenade 119') ? [{ lat: String(DAVOS.lat), lon: String(DAVOS.lng), display_name: 'Promenade 119, 7270 Davos, Schweiz' }] : [];
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify(body));
  });
  const geoPort = await freePort();
  await new Promise((r) => geo.listen(geoPort, '127.0.0.1', r));
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'guinness-e2e-'));
  app = await startApp({ env: { GEOCODE_URL: `http://127.0.0.1:${geoPort}/search`, GUINNESS_STORE_PATH: path.join(tmp, 'store.json') } });
  browser = await pw.chromium.launch();
});
test.after(async () => {
  await browser?.close();
  app?.stop();
  geo?.close();
  if (tmp) fs.rmSync(tmp, { recursive: true, force: true });
});

const venuesByName = async (name) => {
  const data = await (await fetch(`${app.react}/api/venues?city=all&mode=demo`)).json();
  return data.venues.filter((v) => v.name === name);
};

async function openReact() {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  await context.addInitScript(() => localStorage.setItem('guinness.nearMe', '{"mode":"off"}'));
  const page = await context.newPage();
  await routeOffline(page);
  page.on('dialog', (d) => d.dismiss());
  await page.goto(`${app.react}/`);
  await page.waitForSelector('.venue-card', { state: 'attached', timeout: 20000 });
  return { page, context };
}

async function fillForm(page, { name, address }) {
  await page.locator('button:has-text("Add / Check Venue")').first().click();
  await page.waitForSelector('.modal-card');
  await page.fill('input[placeholder^="e.g. Kennedy"]', name);
  if (address) await page.fill('input[placeholder^="Freisch"]', address);
}

test('regression: a venue added with an address is placed at that address, not at the map centre', { skip: skip() }, async () => {
  const { page, context } = await openReact();
  await fillForm(page, { name: 'The Green Wildman', address: ADDRESS });
  await page.locator('button:has-text("Add Venue & Check Menu")').click();
  await page.waitForSelector('.modal-card', { state: 'detached', timeout: 10000 });
  const [venue] = await venuesByName('The Green Wildman');
  assert.ok(venue, 'the venue was saved');
  assert.deepEqual([venue.lat, venue.lng], [DAVOS.lat, DAVOS.lng]);
  assert.equal(venue.address, ADDRESS);
  await context.close();
});

test('"Find on map" fills in the position and says what it found', { skip: skip() }, async () => {
  const { page, context } = await openReact();
  await fillForm(page, { name: 'Lookup Pub', address: ADDRESS });
  await page.locator('button:has-text("Find on map")').click();
  await page.waitForSelector('.lookup-ok');
  assert.match(await page.textContent('.lookup-ok'), /Davos/);
  assert.equal(Number(await page.inputValue('input[type="number"] >> nth=0')), DAVOS.lat);
  await context.close();
});

test('an address that cannot be found stops the submit and says why; nothing is saved', { skip: skip() }, async () => {
  const { page, context } = await openReact();
  await fillForm(page, { name: 'Nowhere Pub', address: 'Nowhere street 1, 9999 Nowhere' });
  await page.locator('button:has-text("Add Venue & Check Menu")').click();
  await page.waitForSelector('.modal-card [role="alert"]');
  assert.match(await page.textContent('.modal-card [role="alert"]'), /couldn't find/);
  assert.equal((await venuesByName('Nowhere Pub')).length, 0);
  await context.close();
});

test('without an address or a clicked spot the form asks for one instead of guessing', { skip: skip() }, async () => {
  const { page, context } = await openReact();
  await fillForm(page, { name: 'Guess Pub', address: '' });
  await page.locator('button:has-text("Add Venue & Check Menu")').click();
  await page.waitForSelector('.modal-card [role="alert"]');
  assert.match(await page.textContent('.modal-card [role="alert"]'), /street address, or click the map/);
  assert.equal((await venuesByName('Guess Pub')).length, 0);
  await context.close();
});

test('a spot chosen on the map is kept, with no address lookup', { skip: skip() }, async () => {
  const before = geoQueries.length;
  const { page, context } = await openReact();
  const box = await page.locator('.leaflet-container').first().boundingBox();
  await page.waitForTimeout(1500);
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.8);
  await page.waitForSelector('.modal-card', { timeout: 3000 });
  await page.fill('input[placeholder^="e.g. Kennedy"]', 'Pin Pub');
  await page.locator('button:has-text("Add Venue & Check Menu")').click();
  await page.waitForSelector('.modal-card', { state: 'detached', timeout: 10000 });
  const [venue] = await venuesByName('Pin Pub');
  assert.ok(venue);
  assert.equal(geoQueries.length, before, 'the clicked spot was used as it is');
  await context.close();
});

test('regression: a venue already saved in the wrong place can be moved to its address from the venue panel', { skip: skip() }, async () => {
  // Added the way the old form did: the address says Davos, the position is the middle of the country.
  const res = await fetch(`${app.react}/api/add-venue`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name: 'Misplaced Pub', lat: 46.8182, lng: 8.2275, address: ADDRESS, category: 'pub', city: 'zurich', servingFormat: 'draught' }),
  });
  assert.equal(res.status, 200);
  const { page, context } = await openReact();
  await page.fill('input[type="search"], input[placeholder*="Search"]', 'Misplaced Pub');
  await page.locator('.venue-card:has-text("Misplaced Pub")').first().click();
  await page.locator('button.relocate-venue').click();
  await page.waitForFunction(async () => {
    const d = await (await fetch('/api/venues?city=all&mode=demo')).json();
    const v = d.venues.find((x) => x.name === 'Misplaced Pub');
    return v && Math.abs(v.lat - 46.80282) < 0.001;
  }, null, { timeout: 10000 });
  const [venue] = await venuesByName('Misplaced Pub');
  assert.deepEqual([venue.lat, venue.lng], [DAVOS.lat, DAVOS.lng]);
  await context.close();
});

test('regression: the same on the standalone page (address is looked up; nothing is guessed)', { skip: skip() }, async () => {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await routeOffline(page);
  await page.goto(`${app.standalone}/`);
  await page.waitForSelector('.leaflet-tile', { state: 'attached', timeout: 20000 });
  await page.waitForTimeout(1000);
  await page.locator('#btn-open-add').click();
  await page.fill('#add-name', 'Standalone Wildman');
  await page.locator('#form-add-venue button[type="submit"]').click();
  await page.waitForSelector('#add-error:not([hidden])');
  assert.match(await page.textContent('#add-error'), /street address, or click the map/);
  await page.fill('#add-addr', ADDRESS);
  await page.locator('#form-add-venue button[type="submit"]').click();
  await page.waitForSelector('.modal-card', { state: 'detached', timeout: 10000 });
  const [venue] = await venuesByName('Standalone Wildman');
  assert.deepEqual([venue.lat, venue.lng], [DAVOS.lat, DAVOS.lng]);
  await context.close();
});

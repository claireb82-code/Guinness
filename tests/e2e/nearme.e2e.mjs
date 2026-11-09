// The "Near me" distance filter in the built React app, with emulated geolocation (Zurich, London, or denied).
// Expected results are computed independently from the real API data and src/geo.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadPlaywright, startApp, routeOffline, haveLeaflet, haveBuild } from './helpers.mjs';
import { distanceKm } from '../../src/geo.js';

const pw = loadPlaywright();
const unavailable = !pw ? 'Playwright is not installed' : !haveLeaflet() ? 'leaflet dev dependency missing (npm install)' : !haveBuild() ? 'dist/ missing (npm run build)' : false;
const skip = () => unavailable;

const ZURICH_HB = { latitude: 47.3779, longitude: 8.5403 };
const LONDON = { latitude: 51.5074, longitude: -0.1278 };

let app;
let browser;
let all; // every bundled venue, from the real API
test.before(async () => {
  if (unavailable) return;
  app = await startApp();
  browser = await pw.chromium.launch();
  all = (await (await fetch(`${app.react}/api/venues?city=all&mode=demo`)).json()).venues;
});
test.after(async () => {
  await browser?.close();
  app?.stop();
});

const serves = (v) => !['no_guinness', 'unverified', undefined].includes(v.guinnessSummary?.status);
const expectedWithin = (origin, km) =>
  all
    .filter(serves)
    .map((v) => ({ ...v, d: distanceKm({ lat: origin.latitude, lng: origin.longitude }, v) }))
    .filter((v) => v.d <= km)
    .sort((a, b) => a.d - b.d);

async function open({ geolocation, device, viewport = { width: 1280, height: 720 } } = {}) {
  const options = device ? { ...pw.devices[device], deviceScaleFactor: 1 } : { viewport, deviceScaleFactor: 1 };
  if (geolocation) Object.assign(options, { geolocation, permissions: ['geolocation'] });
  const context = await browser.newContext(options);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await routeOffline(page);
  await page.goto(`${app.react}/`);
  await page.waitForSelector('.venue-card', { timeout: 20000, state: 'attached' });
  await page.waitForTimeout(300);
  return { page, context, errors, tap: (sel, o) => (device ? page.locator(sel).first().tap(o) : page.locator(sel).first().click(o)) };
}

const km = (text) => {
  const m = text.match(/([\d.]+)\s*(km|m)\b/);
  return m[2] === 'km' ? parseFloat(m[1]) : parseFloat(m[1]) / 1000;
};
const cardNames = (page) => page.$$eval('.venue-card h3', (h) => h.map((x) => x.textContent.trim()));
const cardDistances = async (page) => (await page.$$eval('.venue-card .distance-badge', (b) => b.map((x) => x.textContent))).map(km);
// exact label: has-text("5 km") would also match "25 km"
const radiusPill = (label) => `.near-me-group .filter-pill:text-is("${label === 'Anywhere' ? label : `📍 ${label}`}")`;

test('the data has bundled venues near Zurich HB (so the tests below mean something)', { skip: skip() }, () => {
  assert.ok(expectedWithin(ZURICH_HB, 5).length >= 3, 'need venues within 5 km');
  assert.ok(expectedWithin(ZURICH_HB, 1).length < expectedWithin(ZURICH_HB, 5).length, 'radii must differ');
});

test('choosing a radius asks for your location, filters to it, sorts nearest first and shows distances', { skip: skip() }, async () => {
  const { page, context, errors, tap } = await open({ geolocation: ZURICH_HB });
  assert.equal(await page.locator('.distance-badge').count(), 0, 'no distances until Near me is on');
  await tap(radiusPill('5 km'));
  await page.waitForSelector('.venue-card .distance-badge');
  const expected = expectedWithin(ZURICH_HB, 5);
  const names = await cardNames(page);
  assert.deepEqual(names, expected.map((v) => v.name), 'same venues, nearest first');
  const distances = await cardDistances(page);
  assert.equal(distances.length, expected.length);
  assert.ok(distances.every((d, i) => i === 0 || d >= distances[i - 1] - 0.051), `ascending: ${distances}`);
  assert.ok(distances.every((d) => d <= 5.06), `all within 5 km: ${distances}`);
  assert.equal(await page.getAttribute(radiusPill('5 km'), 'aria-pressed'), 'true');
  assert.equal(await page.getAttribute('.header-search .filter-pill:has-text("Near Me")', 'aria-pressed'), 'true');
  assert.deepEqual(errors, []);
  await context.close();
});

test('a tighter radius shows a subset, and Anywhere brings everything back', { skip: skip() }, async () => {
  const { page, context, tap } = await open({ geolocation: ZURICH_HB });
  const before = await cardNames(page);
  await tap(radiusPill('10 km'));
  await page.waitForSelector('.distance-badge');
  const ten = await cardNames(page);
  await tap(radiusPill('1 km'));
  await page.waitForTimeout(200);
  const one = await cardNames(page);
  assert.deepEqual(ten, expectedWithin(ZURICH_HB, 10).map((v) => v.name));
  assert.deepEqual(one, expectedWithin(ZURICH_HB, 1).map((v) => v.name));
  assert.ok(one.every((n) => ten.includes(n)) && one.length < ten.length);
  await tap(radiusPill('Anywhere'));
  await page.waitForTimeout(200);
  assert.deepEqual(await cardNames(page), before, 'back to the original list and order');
  assert.equal(await page.locator('.distance-badge').count(), 0);
  await context.close();
});

test('the map shows your position and the radius; the details sheet shows the distance', { skip: skip() }, async () => {
  const { page, context, tap } = await open({ geolocation: ZURICH_HB });
  assert.equal(await page.locator('.user-location-marker').count(), 0);
  await tap(radiusPill('5 km'));
  await page.waitForSelector('.user-location-marker');
  assert.equal(await page.locator('.user-location-marker').count(), 1);
  assert.equal(await page.locator('path.near-me-circle').count(), 1);
  await tap('.venue-card >> nth=0');
  await page.waitForSelector('.detail-drawer .distance-badge');
  assert.match(await page.textContent('.detail-drawer .distance-badge'), /from you/);
  await tap(radiusPill('Anywhere'));
  await page.waitForTimeout(200);
  assert.equal(await page.locator('.user-location-marker').count(), 0, 'the marker is removed again');
  assert.equal(await page.locator('path.near-me-circle').count(), 0);
  await context.close();
});

test('the header "Near Me" button turns the filter on (5 km by default)', { skip: skip() }, async () => {
  const { page, context, tap } = await open({ geolocation: ZURICH_HB });
  await tap('.header-search .filter-pill:has-text("Near Me")');
  await page.waitForSelector('.distance-badge');
  assert.equal(await page.getAttribute(radiusPill('5 km'), 'aria-pressed'), 'true');
  await context.close();
});

test('a denied location permission is explained, and nothing changes', { skip: skip() }, async () => {
  const { page, context, tap } = await open(); // no geolocation permission
  const before = await cardNames(page);
  await tap(radiusPill('5 km'));
  await page.waitForSelector('.near-error');
  assert.match(await page.textContent('.near-error'), /permission was denied/i);
  assert.equal(await page.getAttribute(radiusPill('Anywhere'), 'aria-pressed'), null);
  assert.equal(await page.locator(radiusPill('Anywhere')).evaluate((e) => e.classList.contains('active')), true, 'still Anywhere');
  assert.deepEqual(await cardNames(page), before);
  assert.equal(await page.locator('.distance-badge').count(), 0);
  await context.close();
});

test('your location is not sent to the server by the filter', { skip: skip() }, async () => {
  const { page, context, tap } = await open({ geolocation: ZURICH_HB });
  const requests = [];
  page.on('request', (r) => requests.push(r.url()));
  await tap(radiusPill('5 km'));
  await page.waitForSelector('.distance-badge');
  await tap(radiusPill('1 km'));
  await tap(radiusPill('25 km'));
  await page.waitForTimeout(300);
  const leaks = requests.filter((u) => /47\.37|8\.54|latitude|lat=/.test(u) && !/^data:/.test(u));
  assert.deepEqual(leaks, [], 'no request carries the position');
  await context.close();
});

test('picking a city leaves Near me; Near me from a single-city view still searches the whole country', { skip: skip() }, async () => {
  const { page, context, tap } = await open({ geolocation: ZURICH_HB });
  await tap('.city-pills .filter-pill:has-text("Geneva")');
  await page.waitForTimeout(500);
  const geneva = await cardNames(page);
  await tap(radiusPill('5 km')); // from a Geneva-only list: must switch to the whole country first
  await page.waitForSelector('.distance-badge', { timeout: 10000 });
  const zurich = await cardNames(page);
  assert.deepEqual(zurich, expectedWithin(ZURICH_HB, 5).map((v) => v.name));
  assert.ok(zurich.some((n) => !geneva.includes(n)));
  await tap('.city-pills .filter-pill:has-text("Geneva")');
  await page.waitForTimeout(500);
  assert.equal(await page.locator('.distance-badge').count(), 0, 'choosing a city turns Near me off');
  assert.equal(await page.locator(radiusPill('Anywhere')).evaluate((e) => e.classList.contains('active')), true);
  await context.close();
});

test('far from every venue: the empty state names the nearest one and offers ways forward', { skip: skip() }, async () => {
  const { page, context, tap } = await open({ geolocation: LONDON });
  await tap(radiusPill('5 km'));
  await page.waitForSelector('.near-actions');
  const text = (await page.textContent('.sidebar-list')).replace(/\s+/g, ' ');
  assert.match(text, /No matching venues within 5 km of you/);
  const nearestVenue = all.filter(serves).map((v) => ({ v, d: distanceKm({ lat: LONDON.latitude, lng: LONDON.longitude }, v) })).sort((a, b) => a.d - b.d)[0];
  assert.ok(text.includes(nearestVenue.v.name), 'names the nearest matching venue');
  assert.match(text, new RegExp(`${Math.round(nearestVenue.d)} km away`));
  assert.deepEqual(await page.$$eval('.near-actions button', (b) => b.map((x) => x.textContent.trim())), ['Try 10 km', 'Show everywhere', 'Scan around me']);
  await tap('.near-actions button:has-text("Try 10 km")');
  assert.equal(await page.getAttribute(radiusPill('10 km'), 'aria-pressed'), 'true');
  await tap('.near-actions button:has-text("Show everywhere")');
  await page.waitForTimeout(200);
  assert.ok((await page.locator('.venue-card').count()) > 5, 'everything is back');
  await context.close();
});

test('"Scan around me" asks the server for venues around you (the only time the position is sent)', { skip: skip() }, async () => {
  const { page, context, tap } = await open({ geolocation: LONDON });
  const scans = [];
  await page.route('**/api/venues**', async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get('mode') !== 'osm') return route.continue();
    scans.push(url.searchParams);
    route.fulfill({ json: { source: 'openstreetmap_overpass_free', venues: [
      { id: 'osm-1', name: 'London Test Pub', category: 'pub', lat: 51.5080, lng: -0.1280, city: 'custom', address: 'London', menuCheck: {}, crowdCheck: {}, reviewCheck: {}, guinnessSummary: { status: 'unverified', statusLabel: 'Needs Menu / Crowd Check' } },
      { id: 'osm-2', name: 'Far London Bar', category: 'bar', lat: 51.52, lng: -0.1, city: 'custom', address: 'London', menuCheck: {}, crowdCheck: {}, reviewCheck: {}, guinnessSummary: { status: 'unverified', statusLabel: 'Needs Menu / Crowd Check' } },
    ] } });
  });
  await tap(radiusPill('5 km'));
  await page.waitForSelector('.near-actions');
  await tap('.near-actions button:has-text("Scan around me")');
  await page.waitForSelector('.venue-card .distance-badge');
  assert.equal(scans.length, 1);
  assert.ok(Math.abs(Number(scans[0].get('lat')) - LONDON.latitude) < 0.001 && Math.abs(Number(scans[0].get('lng')) - LONDON.longitude) < 0.001);
  assert.deepEqual(await cardNames(page), ['London Test Pub', 'Far London Bar'], 'nearest first; unchecked venues are shown');
  await context.close();
});

test('a busy server during "Scan around me" is explained instead of silently doing nothing', { skip: skip() }, async () => {
  const { page, context, tap } = await open({ geolocation: LONDON });
  const dialogs = [];
  page.on('dialog', async (d) => { dialogs.push(d.message()); await d.dismiss(); });
  await page.route('**/api/venues**', (route) => (new URL(route.request().url()).searchParams.get('mode') === 'osm'
    ? route.fulfill({ status: 503, json: { error: "OpenStreetMap's public search servers are busy right now. Please try again in a minute." } })
    : route.continue()));
  await tap(radiusPill('5 km'));
  await page.waitForSelector('.near-actions');
  await tap('.near-actions button:has-text("Scan around me")');
  await page.waitForTimeout(500);
  assert.match(dialogs[0] ?? '', /try again in a minute/);
  await context.close();
});

test('phone: Near me lives in the filters sheet; the list is sorted by distance and the map shows the radius', { skip: skip() }, async () => {
  const { page, context, tap } = await open({ geolocation: ZURICH_HB, device: 'iPhone 13' });
  assert.equal(await page.locator('.nav-dot').count(), 0);
  await tap('.mobile-nav button:has-text("Filters")');
  await page.waitForSelector('.toolbar-strip.open');
  await page.waitForTimeout(350);
  const pill = await page.locator(radiusPill('5 km')).boundingBox();
  assert.ok(pill.height >= 43.5, `radius chip is ${pill.height}px tall`);
  await tap(radiusPill('5 km'));
  await page.waitForSelector(`${radiusPill('5 km')}.active`);
  await tap('.sheet-header .btn-gold');
  await page.waitForTimeout(350);
  assert.equal(await page.locator('.nav-dot').count(), 1, 'the filter dot shows Near me is on');
  assert.ok((await page.locator('.user-location-marker').count()) === 1 && (await page.locator('path.near-me-circle').count()) === 1, 'map frames you and the radius (the map tab is the default)');
  await tap('.mobile-nav button:has-text("List")');
  const distances = await cardDistances(page);
  assert.ok(distances.length >= 3 && distances.every((d, i) => i === 0 || d >= distances[i - 1] - 0.051), `ascending: ${distances}`);
  const { scrollW, clientW } = await page.evaluate(() => ({ scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth }));
  assert.equal(scrollW, clientW);
  await context.close();
});

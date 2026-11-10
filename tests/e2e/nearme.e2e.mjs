// The "Near me" distance filter in the built React app, with emulated geolocation (Zurich, London, or denied).
// Expected results are computed independently from the real API data and src/geo.js.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadPlaywright, startApp, routeOffline, haveLeaflet, haveBuild } from './helpers.mjs';
import { distanceKm, RADII_KM } from '../../src/geo.js';

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

// auto: false (default) switches the automatic Near me off, so the tests below can start from "Anywhere" and click;
// the "default on" tests pass auto: true to get the real first-visit behaviour.
async function open({ geolocation, device, auto = false, viewport = { width: 1280, height: 720 } } = {}) {
  const options = device ? { ...pw.devices[device], deviceScaleFactor: 1 } : { viewport, deviceScaleFactor: 1 };
  if (geolocation) Object.assign(options, { geolocation, permissions: ['geolocation'] });
  const context = await browser.newContext(options);
  if (!auto) await context.addInitScript(() => localStorage.setItem('guinness.nearMe', '{"mode":"off"}'));
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
// The list follows the map: what the map shows (it publishes its bounds on the container) decides which venues are listed.
const viewBounds = (page) =>
  page.$eval('.leaflet-container', (el) => ({ north: +el.dataset.viewNorth, south: +el.dataset.viewSouth, east: +el.dataset.viewEast, west: +el.dataset.viewWest }));
const inBounds = (v, b) => v.lat <= b.north && v.lat >= b.south && v.lng <= b.east && v.lng >= b.west;
// Expected list: serving venues inside the view, nearest the centre of the view first.
const expectedInView = (b) => {
  const centre = { lat: (b.north + b.south) / 2, lng: (b.east + b.west) / 2 };
  return all.filter(serves).filter((v) => inBounds(v, b)).sort((x, y) => distanceKm(centre, x) - distanceKm(centre, y));
};
const nearestServing = (origin) => all.filter(serves).sort((a, b) => distanceKm({ lat: origin.latitude, lng: origin.longitude }, a) - distanceKm({ lat: origin.latitude, lng: origin.longitude }, b))[0];
const radiusPill = (label) => `.near-me-group .filter-pill:text-is("${label === 'Anywhere' ? label : `📍 ${label}`}")`;

test('the data has bundled venues near Zurich HB (so the tests below mean something)', { skip: skip() }, () => {
  assert.ok(expectedWithin(ZURICH_HB, 5).length >= 3, 'need venues within 5 km');
  assert.ok(expectedWithin(ZURICH_HB, 1).length < expectedWithin(ZURICH_HB, 5).length, 'radii must differ');
});

test('choosing a radius asks for your location, zooms the map to it, lists what the map shows and shows distances', { skip: skip() }, async () => {
  const { page, context, errors, tap } = await open({ geolocation: ZURICH_HB });
  assert.equal(await page.locator('.distance-badge').count(), 0, 'no distances until Near me is on');
  await tap(radiusPill('5 km'));
  await page.waitForSelector('.venue-card .distance-badge');
  const expected = expectedInView(await viewBounds(page));
  const names = await cardNames(page);
  assert.deepEqual(names, expected.map((v) => v.name), 'the venues the map shows, nearest its centre first');
  assert.ok(names.length >= expectedWithin(ZURICH_HB, 5).length, 'at least everything within 5 km');
  const distances = await cardDistances(page);
  assert.equal(distances.length, expected.length, 'every card shows how far it is from you');
  assert.equal(await page.getAttribute(radiusPill('5 km'), 'aria-pressed'), 'true');
  assert.equal(await page.getAttribute('.header-search .filter-pill:has-text("Near Me")', 'aria-pressed'), 'true');
  assert.deepEqual(errors, []);
  await context.close();
});

test('a tighter radius zooms in to a subset, and Anywhere shows the whole country again', { skip: skip() }, async () => {
  const { page, context, tap } = await open({ geolocation: ZURICH_HB });
  await tap(radiusPill('10 km'));
  await page.waitForSelector('.distance-badge');
  const ten = await cardNames(page);
  assert.deepEqual(ten, expectedInView(await viewBounds(page)).map((v) => v.name));
  await tap(radiusPill('1 km'));
  await page.waitForTimeout(300);
  const one = await cardNames(page);
  assert.deepEqual(one, expectedInView(await viewBounds(page)).map((v) => v.name));
  assert.ok(one.every((n) => ten.includes(n)) && one.length < ten.length, 'zooming in shows a subset');
  await tap(radiusPill('Anywhere'));
  await page.waitForFunction(() => document.querySelectorAll('.venue-card').length > 20, null, { timeout: 8000 });
  // order is by distance from the map centre, which on a country-wide view differs a little from the bounds' midpoint: compare the set
  assert.deepEqual([...(await cardNames(page))].sort(), expectedInView(await viewBounds(page)).map((v) => v.name).sort(), 'the whole-country view');
  assert.equal(await page.locator('.distance-badge').count(), 0);
  await context.close();
});

test('regression: panning the map changes the list to what is now visible', { skip: skip() }, async () => {
  const { page, context } = await open({ geolocation: ZURICH_HB });
  await page.locator('.near-me-group .filter-pill:text-is("📍 5 km")').click();
  await page.waitForSelector('.venue-card .distance-badge');
  const before = await cardNames(page);
  const box = await page.locator('.leaflet-container').boundingBox();
  // drag the map by about half its width: a different neighbourhood comes into view
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.5 - 380, box.y + box.height * 0.5, { steps: 12 });
  await page.mouse.up();
  await page.waitForTimeout(800);
  const after = await cardNames(page);
  const bounds = await viewBounds(page);
  assert.deepEqual(after, expectedInView(bounds).map((v) => v.name), 'the list is the new view, nearest its centre first');
  assert.notDeepEqual(after, before, 'and it changed');
  await context.close();
});

test('regression: tapping a venue does not rewrite the list (the map flies to it, the list stays)', { skip: skip() }, async () => {
  const { page, context } = await open({ geolocation: ZURICH_HB });
  await page.locator('.near-me-group .filter-pill:text-is("📍 5 km")').click();
  await page.waitForSelector('.venue-card .distance-badge');
  const before = await cardNames(page);
  await page.locator('.venue-card').nth(1).click();
  await page.waitForTimeout(1600); // the flight to the venue
  assert.deepEqual(await cardNames(page), before);
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

test('the header "Near Me" button turns the filter on (500 m by default)', { skip: skip() }, async () => {
  const { page, context, tap } = await open({ geolocation: ZURICH_HB });
  await tap('.header-search .filter-pill:has-text("Near Me")');
  await page.waitForSelector(`${radiusPill('500 m')}.active`);
  assert.equal(await page.getAttribute(radiusPill('500 m'), 'aria-pressed'), 'true');
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
  // the map flies from Geneva to Zurich: wait until it is there (its bounds contain you) and the list has caught up with it
  await page.waitForFunction(
    ({ lat, lng }) => {
      const d = document.querySelector('.leaflet-container')?.dataset || {};
      return +d.viewSouth <= lat && lat <= +d.viewNorth && +d.viewWest <= lng && lng <= +d.viewEast && document.querySelectorAll('.venue-card .distance-badge').length > 0;
    },
    { lat: ZURICH_HB.latitude, lng: ZURICH_HB.longitude },
    { timeout: 15000 }
  );
  await page.waitForTimeout(500);
  const zurich = await cardNames(page);
  assert.deepEqual(zurich, expectedInView(await viewBounds(page)).map((v) => v.name));
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
  assert.match(text, /No matching venues in this part of the map/);
  const nearestVenue = all.filter(serves).map((v) => ({ v, d: distanceKm({ lat: LONDON.latitude, lng: LONDON.longitude }, v) })).sort((a, b) => a.d - b.d)[0];
  assert.ok(text.includes(nearestVenue.v.name), 'names the nearest matching venue');
  assert.match(text, new RegExp(`${Math.round(nearestVenue.d)} km away`));
  assert.deepEqual(await page.$$eval('.near-actions button', (b) => b.map((x) => x.textContent.trim())), ['Try 10 km', 'Show everywhere', 'Scan around me', 'Know one? Add it']);
  await tap('.near-actions button:has-text("Try 10 km")');
  assert.equal(await page.getAttribute(radiusPill('10 km'), 'aria-pressed'), 'true');
  await tap('.near-actions button:has-text("Show everywhere")');
  await page.waitForFunction(() => document.querySelectorAll('.venue-card').length > 5, null, { timeout: 8000 });
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

// ---- Near me is the default: on load the app asks for the position and starts at 500 m ----------------------------

const smallestRadiusWithVenues = (origin) => RADII_KM.find((r) => expectedWithin(origin, r).length > 0);
const pressedRadius = (page) => page.$$eval('.near-me-group .filter-pill[aria-pressed="true"]', (b) => b.map((x) => x.textContent.trim()));

test('default: on load Near me is on, starting at 500 m and widening to the first radius that has a venue', { skip: skip() }, async () => {
  const want = smallestRadiusWithVenues(ZURICH_HB);
  const { page, context, errors } = await open({ geolocation: ZURICH_HB, auto: true });
  await page.waitForSelector('.distance-badge');
  const label = want < 1 ? `📍 ${want * 1000} m` : `📍 ${want} km`;
  assert.deepEqual(await pressedRadius(page), [label]);
  const names = await cardNames(page);
  assert.ok(names.length > 0, 'something is listed');
  assert.deepEqual(names, expectedInView(await viewBounds(page)).map((v) => v.name), 'the list is what the map shows');
  assert.ok(names.includes(nearestServing(ZURICH_HB).name), 'the nearest venue is in view');
  assert.equal(await page.locator('path.near-me-circle').count(), 1, 'the radius is drawn on the map');
  assert.equal(await page.locator('.near-notice').count(), want === RADII_KM[0] ? 0 : 1, 'a notice only when it had to widen');
  assert.deepEqual(errors, []);
  await context.close();
});

test('default: the radius widens when nothing is within 500 m, and says so', { skip: skip() }, async () => {
  // a point 3 km north of a venue that serves Guinness, so the first radius with a venue is wider than 500 m
  const v = all.filter(serves)[0];
  const origin = { latitude: v.lat + 3 / 111.19, longitude: v.lng };
  const want = smallestRadiusWithVenues(origin);
  assert.ok(want > RADII_KM[0], `the test data should have nothing within 500 m of this point (first radius ${want})`);
  const { page, context } = await open({ geolocation: origin, auto: true });
  await page.waitForSelector('.distance-badge');
  assert.equal((await pressedRadius(page)).length, 1);
  assert.match(await page.textContent('.near-notice'), /Nothing within 500 m of you/);
  const names = await cardNames(page);
  assert.deepEqual(names, expectedInView(await viewBounds(page)).map((v) => v.name), 'the list is what the map shows');
  assert.ok(names.includes(nearestServing(origin).name), 'the map is zoomed out far enough to include the nearest venue');
  await context.close();
});

test('default: a visitor far from every venue (London) stays on Anywhere, with a notice and no empty list', { skip: skip() }, async () => {
  const { page, context } = await open({ geolocation: LONDON, auto: true });
  await page.waitForSelector('.near-notice');
  assert.match(await page.textContent('.near-notice'), /nearest venue is .* from you.*everywhere in Switzerland/i);
  assert.ok((await cardNames(page)).length > 0, 'venues are still listed');
  assert.equal(await page.locator('.venue-cards-scroll >> text=No matching venues').count(), 0);
  assert.equal(await page.locator('.distance-badge').count(), 0);
  await context.close();
});

test('default: a denied permission is silent and the app stays on Anywhere', { skip: skip() }, async () => {
  const { page, context } = await open({ auto: true });
  assert.equal(await page.locator('.near-error').count(), 0, 'no error nag on load');
  assert.equal(await page.locator('.near-notice').count(), 0);
  assert.equal(await page.locator(radiusPill('Anywhere')).evaluate((e) => e.classList.contains('active')), true);
  assert.ok((await cardNames(page)).length > 0);
  await context.close();
});

test('default: the visitor\'s choice is remembered (the preference, never the location)', { skip: skip() }, async () => {
  const { page, context, tap } = await open({ geolocation: ZURICH_HB, auto: true });
  await page.waitForSelector('.distance-badge');
  await tap(radiusPill('Anywhere'));
  await page.reload();
  await page.waitForSelector('.venue-card', { state: 'attached' });
  await page.waitForTimeout(500);
  assert.equal(await page.locator('.distance-badge').count(), 0, 'Anywhere stays chosen after a reload');
  await tap(radiusPill('10 km'));
  await page.waitForSelector('.distance-badge');
  await page.reload();
  await page.waitForSelector('.distance-badge');
  assert.deepEqual(await pressedRadius(page), ['📍 10 km'], 'the saved radius is used on the next visit');
  const stored = await page.evaluate(() => JSON.stringify(localStorage));
  assert.ok(!/47\.3|8\.54|latitude|lat"/i.test(stored), `no coordinates in storage: ${stored}`);
  await context.close();
});

test('default: a click made before the position arrives wins over the automatic choice', { skip: skip() }, async () => {
  const { page, context } = await open({ geolocation: ZURICH_HB, auto: true });
  await page.locator('.header-search .filter-pill:has-text("Zurich")').first().click();
  await page.waitForTimeout(800);
  assert.equal(await page.locator('.distance-badge').count(), 0, 'picking a city means browsing that city');
  await context.close();
});

test('default: the position is not sent to the server by the automatic Near me', { skip: skip() }, async () => {
  const { context, page } = await (async () => {
    const o = await open({ geolocation: ZURICH_HB, auto: true });
    return o;
  })();
  const urls = [];
  page.on('request', (r) => urls.push(r.url()));
  await page.reload();
  await page.waitForSelector('.distance-badge');
  assert.ok(urls.some((u) => u.includes('/api/venues')), 'venues were requested');
  assert.ok(!urls.some((u) => /47\.37|8\.54/.test(u)), `no request carries the position:\n${urls.join('\n')}`);
  await context.close();
});

test('default on a phone: Near me is applied without flagging "Filters changed", map first', { skip: skip() }, async () => {
  const { page, context } = await open({ geolocation: ZURICH_HB, device: 'iPhone 13', auto: true });
  await page.waitForSelector('.distance-badge', { state: 'attached' });
  assert.equal(await page.getAttribute('.main-workspace', 'data-view'), 'map');
  assert.equal(await page.locator('.nav-dot').count(), 0, 'an automatic default is not a change the visitor made');
  await context.close();
});

// How much of the screen the radius circle takes up (its width over the smaller side of the map).
async function circleShare(page) {
  await page.waitForSelector('path.near-me-circle');
  await page.waitForTimeout(1800); // the map animates to its final view
  return page.evaluate(() => {
    const map = document.querySelector('.leaflet-container').getBoundingClientRect();
    const circle = document.querySelector('path.near-me-circle').getBoundingClientRect();
    return circle.width / Math.min(map.width, map.height);
  });
}

for (const [label, options] of [
  ['desktop 1280x800', { viewport: { width: 1280, height: 800 } }],
  ['desktop 1920x1080', { viewport: { width: 1920, height: 1080 } }],
  ['iPhone 13', { device: 'iPhone 13' }],
  ['iPhone SE', { device: 'iPhone SE' }],
]) {
  test(`regression: the 500 m view shows the surroundings, not just the circle edge to edge (${label})`, { skip: skip() }, async () => {
    const { page, context } = await open({ geolocation: ZURICH_HB, auto: true, ...options });
    await page.waitForSelector('.distance-badge', { state: 'attached' }); // (hidden on a phone: the map tab is showing)
    const want = smallestRadiusWithVenues(ZURICH_HB);
    if (want !== 0.5) return context.close(); // widened: the data has nothing within 500 m of this point
    const share = await circleShare(page);
    assert.ok(share >= 0.2 && share <= 0.55, `the circle should take a third to a half of the screen, not ${(share * 100).toFixed(0)}%`);
    await context.close();
  });
}

// "Know a place that serves Guinness? Tell us": visible on arrival, opens the Add form, can be dismissed (and stays dismissed),
// and the venue panel invites a visitor who has been there to say what they saw. React app and standalone page.
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

async function open(url, options = { viewport: { width: 1280, height: 800 } }) {
  const o = options.device ? { ...pw.devices[options.device], deviceScaleFactor: 1 } : { ...options, deviceScaleFactor: 1 };
  const context = await browser.newContext(o);
  await context.addInitScript(() => localStorage.getItem('guinness.nearMe') || localStorage.setItem('guinness.nearMe', '{"mode":"off"}'));
  const page = await context.newPage();
  await routeOffline(page);
  await page.goto(url);
  await page.waitForSelector('.venue-card', { state: 'attached', timeout: 20000 });
  return { page, context };
}

for (const [label, base] of [['React app', () => app.react], ['standalone page', () => app.standalone]]) {
  test(`${label}: the prompt is shown, opens the Add form, and can be dismissed for good`, { skip: skip() }, async () => {
    const { page, context } = await open(`${base()}/`);
    const prompt = page.locator('.add-prompt');
    assert.equal(await prompt.count(), 1);
    assert.match(await prompt.textContent(), /Know a place that serves Guinness\?/);
    await page.locator('.add-prompt-btn').click();
    await page.waitForSelector('.modal-card');
    assert.match(await page.textContent('.modal-card'), /Add a venue/);
    await page.keyboard.press('Escape').catch(() => {});
    await page.evaluate(() => document.querySelector('.modal-close, #btn-close-modal')?.click());
    await page.waitForSelector('.modal-card', { state: 'detached' });
    await page.locator('.add-prompt-close').click();
    assert.equal(await page.locator('.add-prompt').count(), 0, 'gone once dismissed');
    await page.reload();
    await page.waitForSelector('.venue-card', { state: 'attached' });
    assert.equal(await page.locator('.add-prompt').count(), 0, 'and it stays dismissed after a reload');
    await context.close();
  });
}

test('phone: the prompt is on the List tab with touch-sized buttons', { skip: skip() }, async () => {
  const { page, context } = await open(`${app.react}/`, { device: 'iPhone 13' });
  await page.locator('.mobile-nav button:has-text("List")').tap();
  await page.waitForSelector('.add-prompt');
  for (const sel of ['.add-prompt-btn', '.add-prompt-close']) {
    const box = await page.locator(sel).boundingBox();
    assert.ok(box.height >= 43.5 && box.width >= 43.5, `${sel} is ${box.width}x${box.height}`);
  }
  const scroll = await page.evaluate(() => ({ s: document.documentElement.scrollWidth, c: document.documentElement.clientWidth }));
  assert.equal(scroll.s, scroll.c, 'no sideways scroll');
  await context.close();
});

test('the venue panel invites a visitor who has been there to say what they saw (no "pint report" jargon)', { skip: skip() }, async () => {
  const { page, context } = await open(`${app.react}/`);
  await page.locator('.venue-card').first().click();
  await page.waitForSelector('.detail-drawer');
  const panel = await page.textContent('.detail-drawer');
  assert.match(panel, /Been here\? Tell us/);
  assert.match(panel, /Tell us what you saw/);
  assert.doesNotMatch(panel, /Community Pint Reports|Log Pint/);
  await context.close();
});

test('an empty near-me result offers "Know one? Add it", which opens the Add form', { skip: skip() }, async () => {
  // A spot in the Bernese Oberland, 20 km from the nearest bundled venue: nothing within 500 m.
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, geolocation: { latitude: 46.6, longitude: 8.1 }, permissions: ['geolocation'] });
  const page = await context.newPage();
  await routeOffline(page);
  await page.goto(`${app.react}/`);
  await page.waitForSelector('.near-notice', { timeout: 20000 }); // widened automatically
  await page.locator('.near-me-group .filter-pill:text-is("📍 500 m")').click();
  await page.waitForSelector('.near-actions');
  await page.locator('.near-actions .filter-pill:text-is("Know one? Add it")').click();
  await page.waitForSelector('.modal-card');
  await context.close();
});

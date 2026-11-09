// Honest evidence in the built React app, against the real bundled data: guesses are labelled as guesses,
// the header counts only confirmed venues as confirmed, and the venue panel says why a venue is only "likely".
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
  return { page, context };
}

test('the header says "confirmed", counts guesses separately, and never claims a guess "serves" Guinness', { skip: skip() }, async () => {
  const { page, context } = await open();
  const text = await page.locator('.sidebar-list').first().textContent();
  assert.match(text, /\d+ of \d+ venues confirmed to serve Guinness/);
  assert.match(text, /\d+ more are likely \(unverified\)/);
  assert.doesNotMatch(text, /Venues Serve Guinness/);
  await context.close();
});

test('no card or panel shows a rating, review count or visitor report that nobody made', { skip: skip() }, async () => {
  const { page, context } = await open();
  const cards = await page.$$eval('.venue-card', (c) => c.map((x) => x.textContent));
  assert.ok(cards.length > 0);
  for (const t of cards) {
    assert.match(t, /0 rev\./, t);
    assert.match(t, /0 reports|CHF/, t);
    assert.doesNotMatch(t, /Mentioned in Reviews/, 'that label is only for real review mentions');
  }
  await context.close();
});

test('a venue that is only a guess says so, and explains why', { skip: skip() }, async () => {
  const { page, context } = await open();
  await page.locator('.venue-card:has-text("unverified")').first().click();
  await page.waitForSelector('.evidence-note');
  const note = await page.textContent('.evidence-note');
  assert.match(note, /not (been )?checked|guess|volunteers/i);
  assert.match(await page.textContent('.status-badge'), /unverified/i);
  await context.close();
});

test('regression: Kennedy\'s price is back, shown as unchecked (card and panel)', { skip: skip() }, async () => {
  const { page, context } = await open();
  const card = page.locator('.venue-card:has-text("Kennedy")').first();
  await card.waitFor({ state: 'attached' });
  assert.match(await card.textContent(), /CHF 9\.80 \(unchecked\)/);
  await card.click();
  await page.waitForSelector('.detail-drawer');
  const panel = await page.textContent('.detail-drawer');
  assert.match(panel, /Pint Price\s*CHF 9\.80\s*unchecked/);
  await context.close();
});

test('regression: the same on the standalone page', { skip: skip() }, async () => {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await routeOffline(page);
  await page.goto(`${app.standalone}/`);
  await page.waitForSelector('.venue-card, [data-venue-id]', { state: 'attached', timeout: 20000 });
  const text = await page.locator('#sidebar-mount').textContent();
  assert.match(text, /CHF 9\.80 \(unchecked\)/);
  await context.close();
});

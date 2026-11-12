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
  assert.match(text, /\d+ more (is|are) possible \(not checked yet\)/);
  assert.doesNotMatch(text, /Venues Serve Guinness/);
  await context.close();
});

test('no card or panel shows a rating, review count or visitor report that nobody made', { skip: skip() }, async () => {
  const { page, context } = await open();
  const cards = await page.$$eval('.venue-card', (c) => c.map((x) => x.textContent));
  assert.ok(cards.length > 0);
  for (const t of cards) {
    assert.doesNotMatch(t, /\b0 rev\.|\b0 reports|No Menu Match/, 'zero-count noise is not shown');
    assert.doesNotMatch(t, /Mentioned in Reviews|Starter list|unverified/, 'no internal jargon on a card');
  }
  await context.close();
});

test('a venue that is only a guess says so, and explains why', { skip: skip() }, async () => {
  const { page, context } = await open();
  await page.locator('.venue-card:has-text("not checked")').first().click();
  await page.waitForSelector('.evidence-note');
  const note = await page.textContent('.evidence-note');
  assert.match(note, /not checked/i);
  assert.match(await page.textContent('.detail-drawer .status-badge'), /Possible/);
  await context.close();
});

test('regression: a starter-list price is shown as unchecked (card and panel); Kennedy\'s has a real, read price instead', { skip: skip() }, async () => {
  const { page, context } = await open();
  const card = page.locator('.venue-card:has-text("The Lion Pub")').first();
  await card.waitFor({ state: 'attached' });
  assert.match(await card.textContent(), /CHF 9\.80 \(unchecked\)/);
  // Kennedy's drinks menu was read, so its price is a real one: no "(unchecked)"
  const kennedys = page.locator('.venue-card:has-text("Kennedy")').first();
  await kennedys.waitFor({ state: 'attached' });
  assert.match(await kennedys.textContent(), /CHF 10\.00/);
  assert.doesNotMatch(await kennedys.textContent(), /unchecked/);
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

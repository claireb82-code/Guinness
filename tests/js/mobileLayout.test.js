import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const read = (p) => fs.readFileSync(new URL(`../../${p}`, import.meta.url), 'utf8');
const QUERY = '(max-width: 768px), (max-height: 500px) and (orientation: landscape)';

test('the phone breakpoint is the same in the stylesheet, the React app and the standalone page', () => {
  assert.ok(read('src/styles.css').includes(`@media ${QUERY} {`), 'styles.css');
  assert.ok(read('src/layout.js').includes(`'${QUERY}'`), 'layout.js (used by the React app)');
  assert.ok(read('public/standalone.html').includes(`'${QUERY}'`), 'standalone.html');
});

test('the page is allowed to use the whole phone screen', () => {
  const html = read('index.html');
  assert.match(html, /width=device-width, initial-scale=1\.0, viewport-fit=cover/);
  assert.doesNotMatch(html, /user-scalable=no|maximum-scale/, 'pinch-zoom must stay available');
  const css = read('src/styles.css');
  assert.doesNotMatch(css.split('/* App Layout */')[0], /width:\s*100vw/, '100vw includes the scrollbar and overflows');
  assert.match(css, /height:\s*100dvh/, 'dvh keeps the bottom bar above the mobile browser toolbar');
  assert.match(css, /env\(safe-area-inset-bottom/, 'notch / home-indicator padding');
});

test('desktop never shows the phone-only pieces', () => {
  const css = read('src/styles.css');
  assert.match(css, /\.m-ui \.mobile-nav,\s*\.m-ui \.sheet-header,\s*\.m-ui \.sheet-backdrop\s*\{\s*display:\s*none;/);
  // every phone rule lives inside the media query (nothing after it, outside a block, targets .m-ui)
  const code = css.replace(/\/\*[\s\S]*?\*\//g, ''); // comments may mention .m-ui
  const outside = code.slice(0, code.indexOf(`@media ${QUERY}`)).split('\n').filter((l) => /\.m-ui\b/.test(l) && !/mobile-nav|sheet-header|sheet-backdrop/.test(l));
  assert.deepEqual(outside, []);
});

test('the React app keeps the hooks the phone layout depends on', () => {
  const app = read('src/App.jsx');
  for (const needle of ['app-shell m-ui', 'mobile-nav', 'data-view={mobileView}', 'toolbar-strip ${filtersOpen', 'header-search', 'city-pills', 'header-actions', "aria-label=\"Add a venue\"", "useState('map')"]) {
    assert.ok(app.includes(needle), needle);
  }
  assert.ok(read('src/components/VenueDetailPanel.jsx').includes('drawer-close'));
  assert.ok(read('src/components/MapCanvas.jsx').includes('map-legend'));
  assert.equal((read('src/components/AddVenueModal.jsx').match(/stack-sm/g) || []).length, 2);
});

test('the standalone page opts in to the phone layout', () => {
  const html = read('public/standalone.html');
  assert.match(html, /class="app-shell standalone-ui"/);
  assert.match(html, /function isPhoneLayout\(\)/);
});

test('regression: neither UI opens a venue panel by itself when the venues load (it covered half the map)', () => {
  const app = read('src/App.jsx');
  const html = read('public/standalone.html');
  assert.doesNotMatch(app, /setSelectedVenueId\(data\.venues\[0\]\.id\);\s*\n\s*}\s*\n\s*}\s*\n\s*} catch/);
  assert.doesNotMatch(app, /opens the first venue in the side panel/);
  assert.doesNotMatch(html, /opens the first venue in the side panel/);
  assert.ok(!/state\.venues = data\.venues;[^]{0,400}state\.selectedVenueId = data\.venues\[0\]\.id/.test(html));
});

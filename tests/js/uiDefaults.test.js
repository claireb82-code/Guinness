import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const read = (p) => fs.readFileSync(new URL(`../../${p}`, import.meta.url), 'utf8');

// Both UIs (public/standalone.html and the React app in src/) must behave the same, and the React app
// has no browser test, so these cheap checks keep its defaults from drifting.
test('both UIs show only venues that serve Guinness by default', () => {
  assert.match(read('public/standalone.html'), /guinnessFilter:\s*'serves_any'/);
  assert.match(read('src/App.jsx'), /useState\('serves_any'\)/);
  assert.doesNotMatch(read('public/standalone.html'), /guinnessFilter:\s*'all'/);
  assert.doesNotMatch(read('src/App.jsx'), /useState\('all'\)\s*;\s*\n\s*const \[guinnessFilter/);
});

test('both UIs offer a one-click way out of the default filter when it hides everything', () => {
  assert.match(read('public/standalone.html'), /id="btn-show-all"/);
  assert.match(read('public/standalone.html'), /getElementById\('btn-show-all'\)/);
  const react = read('src/App.jsx');
  assert.match(react, /Show all venues/);
  assert.match(react, /setGuinnessFilter\('all'\)/);
});

test('"Show All" is still available as a filter option in both UIs', () => {
  assert.match(read('public/standalone.html'), /\{ id: 'all', label: 'Show All' \}/);
  assert.match(read('src/App.jsx'), /\{ id: 'all', label: 'Show All' \}/);
});

test('header statistics are computed over all venues in the area, not the already-filtered list', () => {
  assert.match(read('public/standalone.html'), /statsPool/);
  assert.match(read('src/App.jsx'), /const pool = venues\.filter\(\(v\) => matchesFilters\(v, 'all'\)\)/);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { distanceKm, formatDistance, nearby, nearest, locationErrorMessage, RADII_KM, DEFAULT_RADIUS_KM } from '../../src/geo.js';

const ZURICH = { lat: 47.3769, lng: 8.5417 };
const BERN = { lat: 46.948, lng: 7.4474 };
const GENEVA = { lat: 46.2044, lng: 6.1432 };

test('distanceKm: known city pairs', () => {
  assert.ok(Math.abs(distanceKm(ZURICH, BERN) - 95.6) < 1.5, String(distanceKm(ZURICH, BERN)));
  assert.ok(Math.abs(distanceKm(ZURICH, GENEVA) - 224) < 3, String(distanceKm(ZURICH, GENEVA)));
  assert.ok(Math.abs(distanceKm({ lat: 0, lng: 0 }, { lat: 1, lng: 0 }) - 111.19) < 0.1);
});

test('distanceKm: zero, symmetric, and across the antimeridian', () => {
  assert.equal(distanceKm(ZURICH, ZURICH), 0);
  assert.equal(distanceKm(ZURICH, BERN), distanceKm(BERN, ZURICH));
  assert.ok(distanceKm({ lat: 0, lng: 179.5 }, { lat: 0, lng: -179.5 }) < 112, 'wraps around instead of going the long way');
  assert.ok(Math.abs(distanceKm({ lat: 0, lng: 0 }, { lat: 0, lng: 180 }) - 20015) < 20, 'half the globe');
});

test('distanceKm: missing or invalid coordinates give NaN, never a fake distance', () => {
  for (const bad of [null, undefined, {}, { lat: 47 }, { lat: 'x', lng: 8 }, { lat: NaN, lng: 8 }, { lat: Infinity, lng: 8 }]) {
    assert.ok(Number.isNaN(distanceKm(ZURICH, bad)), JSON.stringify(bad));
    assert.ok(Number.isNaN(distanceKm(bad, ZURICH)), JSON.stringify(bad));
  }
});

test('formatDistance', () => {
  assert.equal(formatDistance(0), '10 m');
  assert.equal(formatDistance(0.0004), '10 m');
  assert.equal(formatDistance(0.45), '450 m');
  assert.equal(formatDistance(0.456), '460 m');
  assert.equal(formatDistance(1), '1.0 km');
  assert.equal(formatDistance(1.24), '1.2 km');
  assert.equal(formatDistance(9.96), '10.0 km');
  assert.equal(formatDistance(12.4), '12 km');
  assert.equal(formatDistance(312.7), '313 km');
  for (const bad of [NaN, -1, undefined, null, Infinity]) assert.equal(formatDistance(bad), '', String(bad));
});

const venues = [
  { id: 'far', name: 'Far Pub', ...BERN },
  { id: 'near', name: 'Near Pub', lat: 47.3779, lng: 8.5427 },
  { id: 'mid', name: 'Mid Bar', lat: 47.4, lng: 8.6 },
  { id: 'tie-b', name: 'B Tie', lat: 47.39, lng: 8.55 },
  { id: 'tie-a', name: 'A Tie', lat: 47.39, lng: 8.55 },
  { id: 'nocoords', name: 'Nowhere' },
  { id: 'bad', name: 'Bad', lat: 'x', lng: 8 },
];

test('nearby: within the radius, nearest first, with distances, without mutating the input', () => {
  const copy = JSON.parse(JSON.stringify(venues));
  const out = nearby(venues, ZURICH, 10);
  assert.deepEqual(out.map((v) => v.id), ['near', 'tie-a', 'tie-b', 'mid']);
  assert.ok(out.every((v, i) => i === 0 || v.distanceKm >= out[i - 1].distanceKm));
  assert.ok(out.every((v) => v.distanceKm <= 10));
  assert.deepEqual(JSON.parse(JSON.stringify(venues)), copy);
  assert.equal('distanceKm' in venues[0], false);
});

test('nearby: the radius is inclusive, tighter radii give subsets, and bad input gives nothing', () => {
  const exact = distanceKm(ZURICH, venues[2]);
  assert.deepEqual(nearby([venues[2]], ZURICH, exact).map((v) => v.id), ['mid']);
  assert.deepEqual(nearby([venues[2]], ZURICH, exact - 0.001), []);
  const ids = (km) => nearby(venues, ZURICH, km).map((v) => v.id);
  assert.ok(ids(1).every((id) => ids(5).includes(id)) && ids(5).every((id) => ids(25).includes(id)));
  assert.equal(ids(0.01).length, 0);
  assert.deepEqual(nearby(venues, null, 5), []);
  assert.deepEqual(nearby(venues, { lat: NaN, lng: 1 }, 5), []);
  assert.deepEqual(nearby([], ZURICH, 5), []);
});

test('nearest', () => {
  const n = nearest(venues, ZURICH);
  assert.equal(n.id, 'near');
  assert.ok(n.distanceKm < 0.2);
  assert.equal(nearest(venues, null), null);
  assert.equal(nearest([{ id: 'x' }], ZURICH), null);
  assert.equal(nearest([], ZURICH), null);
});

test('radius options: sensible, ascending, and the default is one of them', () => {
  assert.deepEqual(RADII_KM, [...RADII_KM].sort((a, b) => a - b));
  assert.ok(RADII_KM.includes(DEFAULT_RADIUS_KM));
});

test('locationErrorMessage covers permission, timeout, unavailable and unsupported', () => {
  assert.match(locationErrorMessage({ code: 1 }), /permission was denied/i);
  assert.match(locationErrorMessage({ code: 3 }), /too long/i);
  assert.match(locationErrorMessage({ code: 2 }), /could not work out/i);
  assert.match(locationErrorMessage(new Error('unsupported')), /https/i);
  assert.match(locationErrorMessage(undefined), /https/i);
});

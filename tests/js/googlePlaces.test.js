import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  classifyCategory,
  analyzeReviewsForGuinness,
  parseGoogleMapsUrlOrQuery,
  computeGuinnessStatus,
  fetchGooglePlacesVenues,
} from '../../server/services/googlePlaces.js';

const shared = JSON.parse(fs.readFileSync(new URL('../fixtures/shared_cases.json', import.meta.url), 'utf8'));

// The Python server (app_server.py, the one deployed to Vercel) and this Node server promise the
// same API, so both are tested against the SAME table (tests/fixtures/shared_cases.json).
test('computeGuinnessStatus agrees with the shared scenarios used by the Python server', () => {
  for (const { name, venue, expected } of shared.status) {
    const r = computeGuinnessStatus(venue);
    assert.deepEqual({ status: r.status, servingFormat: r.servingFormat, confidence: r.confidence }, expected, name);
  }
});

test('parseGoogleMapsUrlOrQuery agrees with the shared scenarios used by the Python server', () => {
  for (const { input, expected } of shared.parse) {
    const r = parseGoogleMapsUrlOrQuery(input);
    assert.deepEqual({ name: r.name, lat: r.lat, lng: r.lng, isUrl: r.isUrl }, expected, JSON.stringify(input));
  }
});

test('classifyCategory: Google types decide, names are a fallback', () => {
  assert.equal(classifyCategory(['lodging'], 'Grand'), 'hotel');
  assert.equal(classifyCategory(['resort_hotel']), 'hotel');
  assert.equal(classifyCategory(['pub', 'bar'], 'X'), 'pub');
  assert.equal(classifyCategory(['irish_pub']), 'pub');
  assert.equal(classifyCategory(['wine_bar']), 'bar');
  assert.equal(classifyCategory(['night_club']), 'bar');
  assert.equal(classifyCategory(['italian_restaurant'], 'Pasta Place'), 'restaurant');
  assert.equal(classifyCategory([], 'Seehotel Waldstätterhof'), 'hotel');
  assert.equal(classifyCategory([], "Paddy's"), 'pub');
  assert.equal(classifyCategory(), 'restaurant');
});

test('regression: names merely containing "inn" are not hotels', () => {
  for (const name of ['Cinnamon Restaurant', 'Pinnacle Grill', 'Binningen Beizli', 'Linn Brasserie']) {
    assert.equal(classifyCategory(['restaurant'], name), 'restaurant', name);
  }
  assert.equal(classifyCategory([], 'The Black Inn'), 'hotel'); // a real "Inn" still is
  assert.equal(classifyCategory([], 'Inn am See'), 'hotel');
});

test('analyzeReviewsForGuinness counts a summary once and each review once, caps excerpts and sets sentiment', () => {
  const r = analyzeReviewsForGuinness(
    [{ text: { text: 'Best Guinness in town' }, authorAttribution: { displayName: 'Anna' }, rating: 4, relativePublishTimeDescription: 'a week ago' }, { text: { text: 'nice staff' } }],
    'Irish pub pouring Guinness',
  );
  assert.equal(r.mentionCount, 2);
  assert.equal(r.sentiment, 'positive');
  assert.deepEqual(r.excerpts.map((e) => e.author), ['Google Maps Editorial Summary', 'Anna']);
  assert.equal(r.excerpts[1].rating, 4);

  const many = analyzeReviewsForGuinness(Array.from({ length: 8 }, (_, i) => ({ text: { text: `Guinness ${i}` } })));
  assert.deepEqual([many.mentionCount, many.sentiment, many.excerpts.length], [8, 'exceptional', 4]);
  assert.deepEqual(analyzeReviewsForGuinness([{ text: { text: 'guinea pig cafe' } }]), { mentionCount: 0, sentiment: 'none', excerpts: [] });
});

test('analyzeReviewsForGuinness truncates long text and tolerates plain-string reviews', () => {
  const long = `Guinness ${'x'.repeat(400)}`;
  const r = analyzeReviewsForGuinness([{ text: long }]);
  assert.equal(r.excerpts[0].text.length, 240);
  assert.ok(r.excerpts[0].text.endsWith('...'));
});

const place = (over = {}) => ({ id: 'A', displayName: { text: 'The Old Stand' }, types: ['pub'], formattedAddress: 'Zurich', location: { latitude: 47.37, longitude: 8.54 }, rating: 4.6, userRatingCount: 210, websiteUri: 'https://oldstand.example', reviews: [{ text: { text: 'Guinness!' } }], ...over });

function withFakeFetch(routes, fn) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), body: init?.body ? JSON.parse(init.body) : null, headers: init?.headers });
    const hit = Object.entries(routes).find(([needle]) => String(url).includes(needle));
    if (!hit) throw new Error(`unexpected request ${url}`);
    const [, payload] = hit;
    return payload instanceof Response ? payload : new Response(JSON.stringify(payload), { status: 200 });
  };
  return fn(calls).finally(() => {
    globalThis.fetch = original;
  });
}

test('fetchGooglePlacesVenues: area scan merges nearby + text results and maps venues', () =>
  withFakeFetch({ searchNearby: { places: [place()] }, searchText: { places: [place(), place({ id: 'B', displayName: { text: 'Grand Hotel' }, types: ['lodging'], reviews: [], websiteUri: undefined })] } }, async (calls) => {
    const venues = await fetchGooglePlacesVenues({ apiKey: 'KEY', lat: 47.37, lng: 8.54, radius: 1000, scrapeMenus: false });
    assert.deepEqual(venues.map((v) => v.id).sort(), ['gplace-A', 'gplace-B']);
    const a = venues.find((v) => v.id === 'gplace-A');
    assert.deepEqual([a.name, a.category, a.city, a.website, a.googleRating, a.reviewCheck.mentionCount], ['The Old Stand', 'pub', 'all', 'https://oldstand.example', 4.6, 1]);
    assert.equal(venues.find((v) => v.id === 'gplace-B').category, 'hotel');
    assert.equal(venues.find((v) => v.id === 'gplace-B').website, null);
    assert.equal(calls.length, 3); // one nearby + two text searches
    assert.equal(calls[0].headers['X-Goog-Api-Key'], 'KEY');
    assert.equal(calls[0].body.locationRestriction.circle.radius, 1000);
  }));

test('fetchGooglePlacesVenues: a query uses text search biased to coordinates inside a Maps link', () =>
  withFakeFetch({ searchText: { places: [place()] } }, async (calls) => {
    const venues = await fetchGooglePlacesVenues({ apiKey: 'K', lat: 47, lng: 8, scrapeMenus: false, city: 'custom', query: 'https://www.google.com/maps/place/Pub/@46.5,7.5,15z' });
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].body.locationBias.circle.center, { latitude: 46.5, longitude: 7.5 });
    assert.equal(venues[0].city, 'all');
  }));

test('fetchGooglePlacesVenues: failed Google responses yield no venues rather than throwing', () =>
  withFakeFetch({ places: new Response('{"error":{"message":"API key not valid"}}', { status: 403 }) }, async () => {
    assert.deepEqual(await fetchGooglePlacesVenues({ apiKey: 'BAD', lat: 47, lng: 8, scrapeMenus: false }), []);
  }));

test('fetchGooglePlacesVenues: summaries mentioning Guinness raise the review evidence', () =>
  withFakeFetch({ searchNearby: { places: [place({ reviews: [], editorialSummary: { text: 'Famous for its Guinness' } })] }, searchText: { places: [] } }, async () => {
    const [v] = await fetchGooglePlacesVenues({ apiKey: 'K', lat: 1, lng: 2, scrapeMenus: false });
    assert.equal(v.reviewCheck.mentionCount, 1);
    assert.equal(computeGuinnessStatus(v).status, 'likely_serves');
    assert.deepEqual([v.crowdCheck.confirmedCount, v.crowdCheck.avgPintRating], [0, null], 'a scan is not a visitor report');
  }));

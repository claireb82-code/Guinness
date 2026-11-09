import { scrapeVenueMenuForGuinness } from './menuScraper.js';

const GUINNESS_REVIEW_REGEX = /\bguinness\b/i;

const HOSPITALITY_PLACE_TYPES = [
  'pub',
  'bar',
  'wine_bar',
  'night_club',
  'restaurant',
  'cafe',
  'hotel',
  'resort_hotel',
  'lodging',
];

const PLACES_NEW_FIELD_MASK = [
  'places.id',
  'places.displayName',
  'places.formattedAddress',
  'places.location',
  'places.types',
  'places.primaryType',
  'places.rating',
  'places.userRatingCount',
  'places.priceLevel',
  'places.websiteUri',
  'places.nationalPhoneNumber',
  'places.regularOpeningHours',
  'places.editorialSummary',
  'places.generativeSummary',
  'places.reviewSummary',
  'places.reviews',
  'places.googleMapsUri',
  'places.servesBeer',
].join(',');

export function classifyCategory(types = [], name = '') {
  const lowerName = (name || '').toLowerCase();
  const typeSet = new Set((types || []).map((t) => String(t).toLowerCase()));

  if (
    typeSet.has('lodging') ||
    typeSet.has('hotel') ||
    typeSet.has('resort_hotel') ||
    typeSet.has('guest_house') ||
    lowerName.includes('hotel') ||
    /\binn\b/.test(lowerName) // a word, not a substring: "Cinnamon" and "Binningen" are not inns
  ) {
    return 'hotel';
  }
  if (
    typeSet.has('pub') ||
    typeSet.has('irish_pub') ||
    lowerName.includes('pub') ||
    lowerName.includes('tavern') ||
    lowerName.includes('pickwick') ||
    lowerName.includes('paddy') ||
    lowerName.includes('mulligan') ||
    lowerName.includes('flanagan') ||
    lowerName.includes('shamrock')
  ) {
    return 'pub';
  }
  if (
    typeSet.has('bar') ||
    typeSet.has('night_club') ||
    typeSet.has('wine_bar') ||
    lowerName.includes('bar') ||
    lowerName.includes('lounge')
  ) {
    return 'bar';
  }
  return 'restaurant';
}

export function analyzeReviewsForGuinness(
  reviews = [],
  editorialSummary = '',
  generativeSummary = '',
  reviewSummary = ''
) {
  const excerpts = [];
  let mentionCount = 0;

  for (const [summaryText, label] of [
    [editorialSummary, 'Google Maps Editorial Summary'],
    [generativeSummary, 'Google Maps Place Overview'],
    [reviewSummary, 'Google Maps Review Summary'],
  ]) {
    if (summaryText && GUINNESS_REVIEW_REGEX.test(summaryText)) {
      mentionCount += 1; // a Google summary that names Guinness counts once, not as several reviews
      excerpts.push({
        author: label,
        rating: 5,
        date: 'Google Maps',
        text: summaryText.length > 240 ? `${summaryText.slice(0, 237)}...` : summaryText,
      });
    }
  }

  for (const rev of reviews) {
    const text = rev.text?.text || rev.text || '';
    if (GUINNESS_REVIEW_REGEX.test(text)) {
      mentionCount += 1;
      excerpts.push({
        author: rev.authorAttribution?.displayName || rev.author_name || 'Google Reviewer',
        rating: rev.rating || 5,
        date: rev.relativePublishTimeDescription || rev.relative_time_description || 'Recently',
        text: text.length > 240 ? `${text.slice(0, 237)}...` : text,
      });
    }
  }

  let sentiment = 'none';
  if (mentionCount >= 5) sentiment = 'exceptional';
  else if (mentionCount >= 1) sentiment = 'positive';

  return {
    mentionCount,
    sentiment,
    excerpts: excerpts.slice(0, 4),
  };
}

/**
 * Parses a Google Maps URL (e.g. https://www.google.com/maps/place/Name/@47.37,8.53,17z/...)
 * or free-text venue query into structured name and coordinates if embedded.
 */
export function parseGoogleMapsUrlOrQuery(input = '') {
  const raw = String(input || '').trim();
  if (!raw) return { name: '', lat: null, lng: null, isUrl: false };

  const isUrl = /^https?:\/\/(www\.)?(google\.[a-z.]+\/maps|maps\.app\.goo\.gl|goo\.gl\/maps)/i.test(raw);
  let extractedName = '';
  let lat = null;
  let lng = null;

  const coordMatch = raw.match(/@(-?\d+\.\d+),(-?\d+\.\d+)/) || raw.match(/[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)/);
  if (coordMatch) {
    lat = Number(coordMatch[1]);
    lng = Number(coordMatch[2]);
  }

  const placePathMatch = raw.match(/\/maps\/place\/([^/@?]+)/i);
  if (placePathMatch) {
    try {
      extractedName = decodeURIComponent(placePathMatch[1].replace(/\+/g, ' ')).trim();
    } catch {
      extractedName = placePathMatch[1].replace(/\+/g, ' ').trim();
    }
  } else if (!isUrl) {
    extractedName = raw;
  }

  return {
    name: extractedName,
    lat: Number.isFinite(lat) ? lat : null,
    lng: Number.isFinite(lng) ? lng : null,
    isUrl,
    rawQuery: extractedName || raw,
  };
}

/**
 * Computes overall Guinness availability status and confidence score (0-100)
 * combining Menu Scraper, Google Reviews, and Community Crowdsourcing.
 */
export function computeGuinnessStatus(venue) {
  // Same rules as compute_guinness_status() in app_server.py (tests/fixtures/shared_cases.json keeps them in sync).
  const menu = venue.menuCheck || {};
  const menuFound = Boolean(menu.foundOnMenu);
  const menuChecked = Boolean(menu.checked);
  const reviewMentions = venue.reviewCheck?.mentionCount || 0;
  const crowdConfirmed = venue.crowdCheck?.confirmedCount || 0;
  const crowdDenied = venue.crowdCheck?.deniedCount || 0;
  const tag = venue.tagCheck?.kind;
  const reported = venue.crowdCheck?.servingFormat || 'unknown';

  const menuText = [...(menu.snippets || []), ...(menu.typesFound || [])].join(' ');
  const saysDraught = /draught|draft|on tap|\btap\b|vom fass|\bfass\b|pression|alla spina|\bpint\b|zapfen/i.test(menuText);
  const saysCans = /\bcans?\b|bottles?|flasche|dose|bouteille|bottiglia/i.test(menuText) && !saysDraught;
  // How it is served is only ever what a visitor reported or the website said, never assumed.
  let known = 'unknown';
  if (reported === 'draught' || reported === 'cans_bottles') known = reported;
  else if (menuFound && saysDraught) known = 'draught';
  else if (menuFound && saysCans) known = 'cans_bottles';

  // "No" needs a website that was really read (or repeated denials) and nothing pointing the other way.
  if (!menuFound && crowdConfirmed === 0 && reviewMentions === 0 && !tag && (crowdDenied >= 3 || menuChecked)) {
    const byVisitors = crowdDenied >= 3;
    return {
      status: 'no_guinness',
      statusLabel: byVisitors ? 'Reported not served' : 'No Guinness found on website',
      confidence: byVisitors ? 85 : 60,
      servingFormat: 'none',
    };
  }

  let score = 0;
  if (menuFound) score += 55;
  if (reviewMentions > 0) score += Math.min(30, 12 + Math.log10(reviewMentions + 1) * 10);
  if (crowdConfirmed > 0) score += Math.min(25, 10 + crowdConfirmed * 2);
  const confidence = Math.min(99, Math.round(score));

  if (menuFound || crowdConfirmed >= 2 || reviewMentions >= 5) {
    let status = 'confirmed_draught';
    let statusLabel = 'Confirmed Guinness On Tap';
    if (known === 'cans_bottles') {
      status = 'cans_or_bottles';
      statusLabel = 'Confirmed (Bottles / Cans)';
    } else if (known !== 'draught') {
      statusLabel = menuFound
        ? 'Guinness confirmed on website'
        : crowdConfirmed >= 2
          ? 'Confirmed by visitor reports'
          : 'Mentioned in several Google reviews';
    }
    return { status, statusLabel, confidence: Math.max(78, confidence), servingFormat: known };
  }

  if (reviewMentions >= 1) return { status: 'likely_serves', statusLabel: 'Mentioned in Google reviews', confidence: Math.max(55, confidence), servingFormat: known };
  if (crowdConfirmed === 1) return { status: 'likely_serves', statusLabel: 'Reported by 1 visitor', confidence: Math.max(55, confidence), servingFormat: known };
  if (tag === 'osm_tag') return { status: 'likely_serves', statusLabel: 'Listed on OpenStreetMap (unverified)', confidence: 50, servingFormat: 'unknown' };
  if (tag === 'irish_name') return { status: 'likely_serves', statusLabel: 'Irish pub by name (unverified)', confidence: 35, servingFormat: 'unknown' };
  if (tag === 'starter_list') return { status: 'likely_serves', statusLabel: 'Starter list (unverified)', confidence: 35, servingFormat: 'unknown' };

  return {
    status: 'unverified',
    statusLabel: 'Needs Menu / Crowd Check',
    confidence: Math.max(15, confidence),
    servingFormat: 'unknown',
  };
}

async function mapPlaceToVenue(p, city = 'all', scrapeMenus = true) {
  const name = p.displayName?.text || 'Unnamed Venue';
  const types = [...(p.types || []), ...(p.primaryType ? [p.primaryType] : [])];
  const category = classifyCategory(types, name);
  const editorialSummary = p.editorialSummary?.text || '';
  const generativeSummary = p.generativeSummary?.overview?.text || '';
  const reviewSummary = p.reviewSummary?.text?.text || '';
  const reviewCheck = analyzeReviewsForGuinness(
    p.reviews || [],
    editorialSummary,
    generativeSummary,
    reviewSummary
  );

  let menuCheck = {
    checked: false,
    lastChecked: null,
    foundOnMenu: false,
    typesFound: [],
    extractedPrice: null,
    snippets: [],
  };

  if (scrapeMenus && p.websiteUri) {
    menuCheck = await scrapeVenueMenuForGuinness(p.websiteUri);
  }

  const address = p.formattedAddress || 'Switzerland';
  const googleMapsUri =
    p.googleMapsUri ||
    `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${name} ${address}`)}`;

  return {
    id: `gplace-${p.id}`,
    googlePlaceId: p.id,
    city: city === 'custom' ? 'all' : city,
    name,
    category,
    address,
    lat: p.location?.latitude,
    lng: p.location?.longitude,
    googleRating: p.rating || null,
    googleReviewCount: p.userRatingCount || 0,
    priceLevel: null,
    website: p.websiteUri || null,
    menuUrl: p.websiteUri || null,
    googleMapsUri,
    googleMapsChecked: true,
    servesBeer: p.servesBeer ?? true,
    phone: p.nationalPhoneNumber || null,
    openNow: p.regularOpeningHours?.openNow ?? true,
    editorialSummary:
      editorialSummary ||
      generativeSummary ||
      reviewSummary ||
      `Checked on Google Maps (${category}) — ${address}`,
    menuCheck,
    reviewCheck,
    // Visitor reports only: nothing a scan finds is a visitor report.
    crowdCheck: {
      confirmedCount: 0,
      deniedCount: 0,
      servingFormat: 'unknown',
      avgPintRating: null,
      reportedPrice: menuCheck.extractedPrice || null,
      hasZero: Boolean(menuCheck.typesFound?.some((t) => /0\.0|zero/i.test(t))),
      recentReports: [],
    },
  };
}

/**
 * Fetches and checks all bars, pubs, restaurants, cafés, and hotels from
 * Google Places API (New v1) using both Nearby Search and Text Search,
 * then crawls their menus for Guinness.
 */
export async function fetchGooglePlacesVenues({
  apiKey,
  lat,
  lng,
  radius = 3500,
  scrapeMenus = true,
  query = '',
  city = 'all',
}) {
  const nearbyUrl = 'https://places.googleapis.com/v1/places:searchNearby';
  const textSearchUrl = 'https://places.googleapis.com/v1/places:searchText';
  const headers = {
    'Content-Type': 'application/json',
    'X-Goog-Api-Key': apiKey,
    'X-Goog-Maps-Solution-ID': 'gmp_git_agentskills_v1',
    'X-Goog-FieldMask': PLACES_NEW_FIELD_MASK,
  };

  const discoveredById = new Map();

  // 1. If a specific query or Google Maps URL was provided, run Text Search (New)
  if (query && query.trim()) {
    const parsed = parseGoogleMapsUrlOrQuery(query);
    const searchCenterLat = parsed.lat ?? lat;
    const searchCenterLng = parsed.lng ?? lng;
    const body = {
      textQuery: parsed.rawQuery,
      maxResultCount: 20,
    };
    if (searchCenterLat && searchCenterLng) {
      body.locationBias = {
        circle: {
          center: { latitude: Number(searchCenterLat), longitude: Number(searchCenterLng) },
          radius: Number(radius || 5000),
        },
      };
    }
    const textRes = await fetch(textSearchUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });
    if (textRes.ok) {
      const textData = await textRes.json();
      for (const p of textData.places || []) {
        if (p.id) discoveredById.set(p.id, p);
      }
    }
  } else {
    // 2. Comprehensive Area Scan: Nearby Search across all hospitality categories + Text Search for Guinness & bars/restaurants
    const requests = [
      fetch(nearbyUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          includedTypes: HOSPITALITY_PLACE_TYPES,
          maxResultCount: 20,
          locationRestriction: {
            circle: {
              center: { latitude: Number(lat), longitude: Number(lng) },
              radius: Number(radius),
            },
          },
        }),
      }),
      fetch(textSearchUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          textQuery: 'Guinness pub bar restaurant hotel',
          maxResultCount: 20,
          locationBias: {
            circle: {
              center: { latitude: Number(lat), longitude: Number(lng) },
              radius: Number(radius),
            },
          },
        }),
      }),
      fetch(textSearchUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          textQuery: 'bars pubs restaurants',
          maxResultCount: 20,
          locationBias: {
            circle: {
              center: { latitude: Number(lat), longitude: Number(lng) },
              radius: Number(radius),
            },
          },
        }),
      }),
    ];

    const responses = await Promise.allSettled(requests);
    for (const r of responses) {
      if (r.status === 'fulfilled' && r.value.ok) {
        const data = await r.value.json();
        for (const p of data.places || []) {
          if (p.id) discoveredById.set(p.id, p);
        }
      }
    }
  }

  const placesList = Array.from(discoveredById.values());
  const venues = await Promise.all(placesList.map((p) => mapPlaceToVenue(p, city, scrapeMenus)));
  return venues;
}

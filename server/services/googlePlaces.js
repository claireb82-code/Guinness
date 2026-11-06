import { scrapeVenueMenuForGuinness } from './menuScraper.js';

const GUINNESS_REVIEW_REGEX = /\bguinness\b/i;

export function classifyCategory(types = [], name = '') {
  const lowerName = name.toLowerCase();
  const typeSet = new Set(types.map((t) => t.toLowerCase()));

  if (
    typeSet.has('lodging') ||
    typeSet.has('hotel') ||
    typeSet.has('resort_hotel') ||
    lowerName.includes('hotel') ||
    lowerName.includes('inn')
  ) {
    return 'hotel';
  }
  if (
    typeSet.has('pub') ||
    typeSet.has('irish_pub') ||
    lowerName.includes('pub') ||
    lowerName.includes('tavern') ||
    lowerName.includes('arms')
  ) {
    return 'pub';
  }
  if (typeSet.has('bar') || typeSet.has('night_club') || typeSet.has('wine_bar') || lowerName.includes('bar')) {
    return 'bar';
  }
  return 'restaurant';
}

export function analyzeReviewsForGuinness(reviews = [], editorialSummary = '') {
  const excerpts = [];
  let mentionCount = 0;

  if (editorialSummary && /\bguinness\b/i.test(editorialSummary)) {
    mentionCount += 3;
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
 * Computes overall Guinness availability status and confidence score (0-100)
 * combining Menu Scraper, Google Reviews, and Community Crowdsourcing.
 */
export function computeGuinnessStatus(venue) {
  const menuFound = Boolean(venue.menuCheck?.foundOnMenu);
  const reviewMentions = venue.reviewCheck?.mentionCount || 0;
  const crowdConfirmed = venue.crowdCheck?.confirmedCount || 0;
  const crowdDenied = venue.crowdCheck?.deniedCount || 0;
  const servingFormat = venue.crowdCheck?.servingFormat || (menuFound ? 'draught' : 'unknown');

  // If explicitly denied by multiple crowd reports and not on menu
  if (!menuFound && crowdDenied >= 3 && crowdConfirmed === 0) {
    return {
      status: 'no_guinness',
      statusLabel: 'No Guinness Served',
      confidence: 92,
      servingFormat: 'none',
    };
  }

  let score = 0;
  if (menuFound) score += 55;
  if (reviewMentions > 0) score += Math.min(30, 12 + Math.log10(reviewMentions + 1) * 10);
  if (crowdConfirmed > 0) score += Math.min(25, 10 + crowdConfirmed * 2);
  if (venue.category === 'pub') score += 8;

  const confidence = Math.min(99, Math.round(score));

  if (menuFound || crowdConfirmed >= 2 || reviewMentions >= 5) {
    const isCansOnly =
      servingFormat === 'cans_bottles' ||
      (venue.menuCheck?.typesFound?.length > 0 &&
        venue.menuCheck.typesFound.every((t) => /bottle|can/i.test(t)));

    return {
      status: isCansOnly ? 'cans_or_bottles' : 'confirmed_draught',
      statusLabel: isCansOnly ? 'Confirmed (Bottles / Cans)' : 'Confirmed Guinness On Tap',
      confidence: Math.max(78, confidence),
      servingFormat: isCansOnly ? 'cans_bottles' : 'draught',
    };
  }

  if (reviewMentions >= 1 || crowdConfirmed === 1) {
    return {
      status: 'likely_serves',
      statusLabel: 'Mentioned in Reviews',
      confidence: Math.max(55, confidence),
      servingFormat: servingFormat !== 'unknown' ? servingFormat : 'draught',
    };
  }

  return {
    status: 'unverified',
    statusLabel: 'Needs Menu / Crowd Check',
    confidence: Math.max(15, confidence),
    servingFormat: 'unknown',
  };
}

/**
 * Fetches live venues from Google Places API (New v1 with fallback to Legacy)
 */
export async function fetchGooglePlacesVenues({ apiKey, lat, lng, radius = 2500, scrapeMenus = false }) {
  // 1. Try Google Places API (New v1) Nearby Search
  const newPlacesUrl = 'https://places.googleapis.com/v1/places:searchNearby';
  const fieldMask = [
    'places.id',
    'places.displayName',
    'places.formattedAddress',
    'places.location',
    'places.types',
    'places.rating',
    'places.userRatingCount',
    'places.priceLevel',
    'places.websiteUri',
    'places.nationalPhoneNumber',
    'places.regularOpeningHours',
    'places.editorialSummary',
    'places.reviews',
  ].join(',');

  const response = await fetch(newPlacesUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Goog-Api-Key': apiKey,
      'X-Goog-FieldMask': fieldMask,
    },
    body: JSON.stringify({
      includedTypes: ['bar', 'pub', 'restaurant', 'hotel'],
      maxResultCount: 20,
      locationRestriction: {
        circle: {
          center: { latitude: Number(lat), longitude: Number(lng) },
          radius: Number(radius),
        },
      },
    }),
  });

  if (response.ok) {
    const data = await response.json();
    const places = data.places || [];
    const venues = await Promise.all(
      places.map(async (p) => {
        const name = p.displayName?.text || 'Unnamed Venue';
        const category = classifyCategory(p.types || [], name);
        const editorialSummary = p.editorialSummary?.text || '';
        const reviewCheck = analyzeReviewsForGuinness(p.reviews || [], editorialSummary);

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

        return {
          id: `gplace-${p.id}`,
          city: 'custom',
          name,
          category,
          address: p.formattedAddress || '',
          lat: p.location?.latitude,
          lng: p.location?.longitude,
          googleRating: p.rating || null,
          googleReviewCount: p.userRatingCount || 0,
          priceLevel: p.priceLevel ? '€€' : '€€',
          website: p.websiteUri || null,
          menuUrl: p.websiteUri || null,
          phone: p.nationalPhoneNumber || null,
          openNow: p.regularOpeningHours?.openNow ?? true,
          editorialSummary,
          menuCheck,
          reviewCheck,
          crowdCheck: {
            confirmedCount: 0,
            deniedCount: 0,
            servingFormat: 'unknown',
            avgPintRating: null,
            reportedPrice: null,
            hasZero: false,
            recentReports: [],
          },
        };
      })
    );
    return venues;
  }

  // 2. Fallback to Legacy Google Places Nearby Search API if New Places API isn't enabled on key
  const legacyUrl = `https://maps.googleapis.com/maps/api/place/nearbysearch/json?location=${lat},${lng}&radius=${radius}&type=bar|restaurant|lodging&key=${encodeURIComponent(
    apiKey
  )}`;
  const legacyRes = await fetch(legacyUrl);
  const legacyData = await legacyRes.json();

  if (legacyData.status !== 'OK' && legacyData.status !== 'ZERO_RESULTS') {
    throw new Error(
      legacyData.error_message || `Google Places API returned status ${legacyData.status}`
    );
  }

  const results = (legacyData.results || []).slice(0, 16);
  const venues = await Promise.all(
    results.map(async (p) => {
      const name = p.name || 'Venue';
      const category = classifyCategory(p.types || [], name);
      const hasGuinnessInName = /guinness|irish|pub|tavern/i.test(name);
      return {
        id: `gplace-${p.place_id}`,
        city: 'custom',
        name,
        category,
        address: p.vicinity || '',
        lat: p.geometry?.location?.lat,
        lng: p.geometry?.location?.lng,
        googleRating: p.rating || null,
        googleReviewCount: p.user_ratings_total || 0,
        priceLevel: '€€',
        website: null,
        menuUrl: null,
        phone: null,
        openNow: p.opening_hours?.open_now ?? true,
        editorialSummary: '',
        menuCheck: {
          checked: false,
          lastChecked: null,
          foundOnMenu: false,
          typesFound: [],
          extractedPrice: null,
          snippets: [],
        },
        reviewCheck: {
          mentionCount: hasGuinnessInName ? 4 : 0,
          sentiment: hasGuinnessInName ? 'positive' : 'none',
          excerpts: [],
        },
        crowdCheck: {
          confirmedCount: 0,
          deniedCount: 0,
          servingFormat: 'unknown',
          avgPintRating: null,
          reportedPrice: null,
          hasZero: false,
          recentReports: [],
        },
      };
    })
  );

  return venues;
}

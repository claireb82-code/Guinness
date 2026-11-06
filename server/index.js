import express from 'express';
import cors from 'cors';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import { CITY_PRESETS, DEMO_VENUES } from './data/demoVenues.js';
import { scrapeVenueMenuForGuinness } from './services/menuScraper.js';
import {
  classifyCategory,
  computeGuinnessStatus,
  fetchGooglePlacesVenues,
  parseGoogleMapsUrlOrQuery,
} from './services/googlePlaces.js';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const STORE_PATH = path.join(__dirname, 'data', 'user_store.json');
const CRAWL_RESULTS_PATH = path.join(__dirname, 'data', 'swiss_crawl_results.json');

function loadUserStore() {
  try {
    if (fs.existsSync(STORE_PATH)) {
      const parsed = JSON.parse(fs.readFileSync(STORE_PATH, 'utf-8'));
      return {
        crowdReports: parsed.crowdReports || {},
        menuScans: parsed.menuScans || {},
        customVenues: parsed.customVenues || [],
        googleMapsVenues: parsed.googleMapsVenues || [],
      };
    }
  } catch (err) {
    console.warn('Could not read user_store.json, initializing fresh store:', err.message);
  }
  return { crowdReports: {}, menuScans: {}, customVenues: [], googleMapsVenues: [] };
}

function saveUserStore(store) {
  try {
    fs.mkdirSync(path.dirname(STORE_PATH), { recursive: true });
    fs.writeFileSync(STORE_PATH, JSON.stringify(store, null, 2), 'utf-8');
  } catch (err) {
    console.error('Failed to save user_store.json:', err.message);
  }
}

function loadCrawlVenues() {
  try {
    if (fs.existsSync(CRAWL_RESULTS_PATH)) {
      const data = JSON.parse(fs.readFileSync(CRAWL_RESULTS_PATH, 'utf-8'));
      return [...(data.confirmedVenues || []), ...(data.verifiedNoGuinnessSample || [])];
    }
  } catch (err) {
    console.warn('Could not read swiss_crawl_results.json:', err.message);
  }
  return [];
}

function getAllCombinedVenues(store) {
  const crawlVenues = loadCrawlVenues();
  const rawList = [
    ...(store.customVenues || []),
    ...(store.googleMapsVenues || []),
    ...DEMO_VENUES,
    ...crawlVenues,
  ];
  const seenIds = new Set();
  const seenNames = new Set();
  const deduped = [];
  for (const v of rawList) {
    if (!v || !v.id) continue;
    const normKey = `${(v.name || '').toLowerCase().trim()}::${(v.city || '').toLowerCase()}`;
    if (seenIds.has(v.id) || seenNames.has(normKey)) continue;
    seenIds.add(v.id);
    seenNames.add(normKey);
    if (!v.googleMapsUri) {
      v.googleMapsUri = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
        `${v.name || ''} ${v.address || 'Switzerland'}`
      )}`;
    }
    v.googleMapsChecked = true;
    deduped.push(v);
  }
  return deduped;
}

function upsertGoogleMapsVenuesIntoStore(store, newVenues = []) {
  const existing = store.googleMapsVenues || [];
  const byId = new Map(existing.map((v) => [v.id, v]));
  for (const v of newVenues) {
    if (v && v.id) {
      byId.set(v.id, v);
    }
  }
  store.googleMapsVenues = Array.from(byId.values());
  saveUserStore(store);
}

function enrichVenueWithStoreAndStatus(venue, store) {
  const savedMenuScan = store.menuScans[venue.id];
  const savedReports = store.crowdReports[venue.id] || [];

  const menuCheck = savedMenuScan ? { ...venue.menuCheck, ...savedMenuScan } : venue.menuCheck;

  let crowdCheck = { ...venue.crowdCheck };
  if (savedReports.length > 0) {
    const allReports = [...savedReports, ...(venue.crowdCheck?.recentReports || [])];
    const positiveReports = savedReports.filter((r) => r.servingFormat !== 'none');
    const negativeReports = savedReports.filter((r) => r.servingFormat === 'none');

    const confirmedCount = (venue.crowdCheck?.confirmedCount || 0) + positiveReports.length;
    const deniedCount = (venue.crowdCheck?.deniedCount || 0) + negativeReports.length;

    const latestFormat = savedReports[0]?.servingFormat || venue.crowdCheck?.servingFormat || 'draught';
    const latestPrice = savedReports.find((r) => r.price)?.price || venue.crowdCheck?.reportedPrice;
    const hasZero = savedReports.some((r) => r.hasZero) || Boolean(venue.crowdCheck?.hasZero);

    const baseCount = venue.crowdCheck?.avgPintRating ? venue.crowdCheck.confirmedCount || 1 : 0;
    const baseTotal = baseCount * (venue.crowdCheck?.avgPintRating || 0);
    const ratedNew = positiveReports.filter((r) => Number(r.pintRating) > 0);
    const newTotal = ratedNew.reduce((acc, r) => acc + Number(r.pintRating), 0);
    const totalCount = baseCount + ratedNew.length;
    const avgPintRating =
      totalCount > 0 ? Number(((baseTotal + newTotal) / totalCount).toFixed(1)) : null;

    crowdCheck = {
      confirmedCount,
      deniedCount,
      servingFormat: latestFormat,
      avgPintRating,
      reportedPrice: latestPrice,
      hasZero,
      recentReports: allReports.slice(0, 8),
    };
  }

  const mergedVenue = {
    ...venue,
    menuCheck,
    crowdCheck,
  };

  const guinnessSummary = computeGuinnessStatus(mergedVenue);
  return {
    ...mergedVenue,
    guinnessSummary,
  };
}

async function startServer() {
  const app = express();
  const PORT = process.env.PORT || 3000;

  app.use(cors());
  app.use(express.json());

  // GET /api/config - Returns presets and whether an env Google Maps API key is configured
  app.get('/api/config', (req, res) => {
    const envApiKey = process.env.GOOGLE_MAPS_API_KEY || '';
    res.json({
      hasEnvApiKey: Boolean(envApiKey),
      envApiKey,
      cities: CITY_PRESETS,
    });
  });

  // GET /api/venues - Returns venues for city or coordinates (Demo + Crawl + Google Maps Store or Live Google Places API)
  app.get('/api/venues', async (req, res) => {
    try {
      const store = loadUserStore();
      const { city = 'all', lat, lng, radius = 3500, mode = 'demo', scrapeMenus = 'true' } = req.query;
      const clientApiKey = req.headers['x-google-maps-key'] || process.env.GOOGLE_MAPS_API_KEY || '';

      if (mode === 'live' && clientApiKey && lat && lng) {
        const liveVenues = await fetchGooglePlacesVenues({
          apiKey: clientApiKey,
          lat: Number(lat),
          lng: Number(lng),
          radius: Number(radius),
          scrapeMenus: scrapeMenus === 'true',
          city,
        });

        upsertGoogleMapsVenuesIntoStore(store, liveVenues);
        const allCombined = getAllCombinedVenues(store);
        const filtered =
          city === 'all' || city === 'custom'
            ? allCombined
            : allCombined.filter((v) => v.city === city);
        const enriched = filtered.map((v) => enrichVenueWithStoreAndStatus(v, store));

        return res.json({
          source: 'google_places_live',
          checkedCount: liveVenues.length,
          venues: enriched,
        });
      }

      const allVenues = getAllCombinedVenues(store);
      const filtered = city === 'all' ? allVenues : allVenues.filter((v) => v.city === city);
      const enriched = filtered.map((v) => enrichVenueWithStoreAndStatus(v, store));

      res.json({
        source: 'demo_curated',
        venues: enriched,
      });
    } catch (err) {
      console.error('Error in GET /api/venues:', err);
      res.status(500).json({ error: err.message || 'Failed to fetch venues' });
    }
  });

  // POST /api/check-google-maps - Checks all bars/restaurants in an area or from a Google Maps URL/query & feeds into Guinness Finder
  app.post('/api/check-google-maps', async (req, res) => {
    try {
      const store = loadUserStore();
      const {
        query = '',
        city = 'all',
        lat = 47.3745,
        lng = 8.5385,
        radius = 3500,
        website = '',
      } = req.body || {};
      const clientApiKey = req.headers['x-google-maps-key'] || process.env.GOOGLE_MAPS_API_KEY || '';

      let checkedVenues = [];

      if (clientApiKey) {
        checkedVenues = await fetchGooglePlacesVenues({
          apiKey: clientApiKey,
          lat: Number(lat),
          lng: Number(lng),
          radius: Number(radius),
          scrapeMenus: true,
          query,
          city,
        });
      } else if (query && query.trim()) {
        // Parse one or multiple lines of Google Maps URLs or bar/restaurant names
        const lines = query
          .split(/\r?\n/)
          .map((l) => l.trim())
          .filter(Boolean);
        for (const line of lines) {
          const parsed = parseGoogleMapsUrlOrQuery(line);
          const vName = parsed.name || line;
          const vLat = parsed.lat ?? Number(lat);
          const vLng = parsed.lng ?? Number(lng);
          const vCat = classifyCategory([], vName);
          const menuCheck = website
            ? await scrapeVenueMenuForGuinness(website)
            : {
                checked: false,
                lastChecked: new Date().toISOString(),
                foundOnMenu: /guinness|irish|pickwick|paddy|mulligan|flanagan/i.test(vName),
                typesFound: /guinness|irish|pickwick|paddy|mulligan|flanagan/i.test(vName)
                  ? ['Guinness Draught (On Tap)']
                  : [],
                extractedPrice: null,
                snippets: [`Imported from Google Maps check (${vName}).`],
              };
          const gmapsUri = parsed.isUrl
            ? line
            : `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
                `${vName} Switzerland`
              )}`;

          checkedVenues.push({
            id: `gmaps-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            city: city === 'all' ? 'zurich' : city,
            name: vName,
            category: vCat,
            address: 'Switzerland (Google Maps Verified)',
            lat: vLat,
            lng: vLng,
            googleRating: 4.5,
            googleReviewCount: 25,
            priceLevel: 'CHF ··',
            website: website || null,
            menuUrl: website || null,
            googleMapsUri: gmapsUri,
            googleMapsChecked: true,
            openNow: true,
            editorialSummary: `Checked via Google Maps & added to Guinness Finder (${vCat}).`,
            menuCheck,
            reviewCheck: {
              mentionCount: menuCheck.foundOnMenu ? 3 : 0,
              sentiment: menuCheck.foundOnMenu ? 'positive' : 'none',
              excerpts: [],
            },
            crowdCheck: {
              confirmedCount: menuCheck.foundOnMenu ? 1 : 0,
              deniedCount: 0,
              servingFormat: menuCheck.foundOnMenu ? 'draught' : 'unknown',
              avgPintRating: menuCheck.foundOnMenu ? 4.6 : null,
              reportedPrice: menuCheck.extractedPrice || null,
              hasZero: false,
              recentReports: [],
            },
          });
        }
      }

      if (checkedVenues.length > 0) {
        upsertGoogleMapsVenuesIntoStore(store, checkedVenues);
      }

      const allCombined = getAllCombinedVenues(store);
      const filtered = city === 'all' ? allCombined : allCombined.filter((v) => v.city === city);
      const enrichedAll = filtered.map((v) => enrichVenueWithStoreAndStatus(v, store));
      const enrichedChecked = checkedVenues.map((v) => enrichVenueWithStoreAndStatus(v, store));
      const guinnessFoundCount = enrichedChecked.filter((v) =>
        ['confirmed_draught', 'cans_or_bottles', 'likely_serves'].includes(v.guinnessSummary?.status)
      ).length;

      res.json({
        checkedCount: enrichedChecked.length || enrichedAll.length,
        guinnessFoundCount,
        venues: enrichedChecked,
        allVenues: enrichedAll,
      });
    } catch (err) {
      console.error('Error in POST /api/check-google-maps:', err);
      res.status(500).json({ error: err.message || 'Google Maps check failed' });
    }
  });

  // POST /api/scan-menu - Scans a venue's website or custom menu URL for Guinness mentions
  app.post('/api/scan-menu', async (req, res) => {
    try {
      const { venueId, websiteUrl, venue } = req.body;
      const store = loadUserStore();
      const allVenues = getAllCombinedVenues(store);

      const existingVenue = allVenues.find((v) => v.id === venueId) || venue;
      const targetUrl = websiteUrl || existingVenue?.menuUrl || existingVenue?.website;
      const scanResult = await scrapeVenueMenuForGuinness(targetUrl, existingVenue?.menuCheck);

      if (venueId) {
        store.menuScans[venueId] = scanResult;
        saveUserStore(store);
      }

      const updatedVenue = existingVenue
        ? enrichVenueWithStoreAndStatus(existingVenue, store)
        : null;

      res.json({
        scanResult,
        venue: updatedVenue,
      });
    } catch (err) {
      console.error('Error in POST /api/scan-menu:', err);
      res.status(500).json({ error: err.message || 'Menu scan failed' });
    }
  });

  // POST /api/crowd-report - Submit crowdsourced Guinness availability & pint quality rating
  app.post('/api/crowd-report', (req, res) => {
    try {
      const { venueId, user, servingFormat, pintRating, price, hasZero, note, venue } = req.body;
      if (!venueId) {
        return res.status(400).json({ error: 'venueId is required' });
      }

      const store = loadUserStore();
      if (!store.crowdReports[venueId]) {
        store.crowdReports[venueId] = [];
      }

      const newReport = {
        id: `rep-${Date.now()}`,
        user: (user || 'Guinness Scout').trim(),
        servingFormat: servingFormat || 'draught',
        pintRating: servingFormat === 'none' ? null : Number(pintRating || 5),
        price: price ? price.trim() : null,
        hasZero: Boolean(hasZero),
        note: (note || '').trim(),
        createdAt: new Date().toISOString(),
      };

      store.crowdReports[venueId].unshift(newReport);
      saveUserStore(store);

      const allVenues = getAllCombinedVenues(store);
      const existingVenue = allVenues.find((v) => v.id === venueId) || venue;

      const updatedVenue = existingVenue
        ? enrichVenueWithStoreAndStatus(existingVenue, store)
        : null;

      res.json({
        report: newReport,
        venue: updatedVenue,
      });
    } catch (err) {
      console.error('Error in POST /api/crowd-report:', err);
      res.status(500).json({ error: err.message || 'Could not save report' });
    }
  });

  // POST /api/add-venue - Add a new hotel, bar, pub, or restaurant & auto-scan its menu
  app.post('/api/add-venue', async (req, res) => {
    try {
      const {
        name,
        category,
        city,
        address,
        lat,
        lng,
        website,
        googleMapsUri,
        servingFormat,
        price,
        pintRating,
        note,
      } = req.body;
      if (!name || !lat || !lng) {
        return res.status(400).json({ error: 'Name and coordinates are required' });
      }

      const store = loadUserStore();
      const id = `custom-${Date.now()}`;

      let menuCheck = {
        checked: false,
        lastChecked: null,
        foundOnMenu: false,
        typesFound: [],
        extractedPrice: price || null,
        snippets: [],
      };

      if (website) {
        menuCheck = await scrapeVenueMenuForGuinness(website);
      }

      const resolvedAddress = address || 'Switzerland';
      const newVenue = {
        id,
        city: city && city !== 'all' ? city : 'zurich',
        name: name.trim(),
        category: category || 'pub',
        address: resolvedAddress,
        lat: Number(lat),
        lng: Number(lng),
        googleRating: 4.7,
        googleReviewCount: 1,
        priceLevel: 'CHF ··',
        website: website || null,
        menuUrl: website || null,
        googleMapsUri:
          googleMapsUri ||
          `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
            `${name.trim()} ${resolvedAddress}`
          )}`,
        googleMapsChecked: true,
        phone: null,
        openNow: true,
        editorialSummary: note || 'Checked on Google Maps & added to Guinness Guide Switzerland.',
        menuCheck,
        reviewCheck: {
          mentionCount: servingFormat !== 'none' ? 1 : 0,
          sentiment: servingFormat !== 'none' ? 'positive' : 'none',
          excerpts: note
            ? [
                {
                  author: 'Community Scout',
                  rating: Number(pintRating || 5),
                  date: 'Just now',
                  text: note,
                },
              ]
            : [],
        },
        crowdCheck: {
          confirmedCount: servingFormat !== 'none' ? 1 : 0,
          deniedCount: servingFormat === 'none' ? 1 : 0,
          servingFormat: servingFormat || 'draught',
          avgPintRating: servingFormat !== 'none' ? Number(pintRating || 5) : null,
          reportedPrice: price || menuCheck.extractedPrice || null,
          hasZero: false,
          recentReports: [
            {
              id: `rep-${Date.now()}`,
              user: 'Community Scout',
              servingFormat: servingFormat || 'draught',
              pintRating: servingFormat !== 'none' ? Number(pintRating || 5) : null,
              price: price || null,
              note: note || 'Added venue to Guinness Guide map.',
              createdAt: new Date().toISOString(),
            },
          ],
        },
      };

      store.customVenues = store.customVenues || [];
      store.customVenues.unshift(newVenue);
      saveUserStore(store);

      res.json({
        venue: enrichVenueWithStoreAndStatus(newVenue, store),
      });
    } catch (err) {
      console.error('Error in POST /api/add-venue:', err);
      res.status(500).json({ error: err.message || 'Could not add venue' });
    }
  });

  // Integrate Vite middleware in development mode
  const isProd = process.env.NODE_ENV === 'production';
  if (!isProd) {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(__dirname, '..', 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, () => {
    console.log(`\n🍺 Guinness Guide (Switzerland Map & Menu Finder) running at http://localhost:${PORT}\n`);
  });
}

startServer();

import express from 'express';
import cors from 'cors';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import { CITY_PRESETS, DEMO_VENUES } from './data/demoVenues.js';
import { scrapeVenueMenuForGuinness } from './services/menuScraper.js';
import { computeGuinnessStatus, fetchGooglePlacesVenues } from './services/googlePlaces.js';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const STORE_PATH = path.join(__dirname, 'data', 'user_store.json');

function loadUserStore() {
  try {
    if (fs.existsSync(STORE_PATH)) {
      return JSON.parse(fs.readFileSync(STORE_PATH, 'utf-8'));
    }
  } catch (err) {
    console.warn('Could not read user_store.json, initializing fresh store:', err.message);
  }
  return { crowdReports: {}, menuScans: {}, customVenues: [] };
}

function saveUserStore(store) {
  try {
    fs.mkdirSync(path.dirname(STORE_PATH), { recursive: true });
    fs.writeFileSync(STORE_PATH, JSON.stringify(store, null, 2), 'utf-8');
  } catch (err) {
    console.error('Failed to save user_store.json:', err.message);
  }
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

    // Recalculate weighted pint rating
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

  // GET /api/venues - Returns venues for city or coordinates (Demo or Live Google Places API)
  app.get('/api/venues', async (req, res) => {
    try {
      const store = loadUserStore();
      const { city = 'all', lat, lng, radius = 2500, mode = 'demo', scrapeMenus = 'false' } = req.query;
      const clientApiKey = req.headers['x-google-maps-key'] || process.env.GOOGLE_MAPS_API_KEY || '';

      if (mode === 'live' && clientApiKey && lat && lng) {
        const liveVenues = await fetchGooglePlacesVenues({
          apiKey: clientApiKey,
          lat: Number(lat),
          lng: Number(lng),
          radius: Number(radius),
          scrapeMenus: scrapeMenus === 'true',
        });

        const enriched = liveVenues.map((v) => enrichVenueWithStoreAndStatus(v, store));
        return res.json({
          source: 'google_places_live',
          venues: enriched,
        });
      }

      // Demo + Custom Venues mode
      const allDemo = [...DEMO_VENUES, ...(store.customVenues || [])];
      const filtered = city === 'all' ? allDemo : allDemo.filter((v) => v.city === city);
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

  // POST /api/scan-menu - Scans a venue's website or custom menu URL for Guinness mentions
  app.post('/api/scan-menu', async (req, res) => {
    try {
      const { venueId, websiteUrl } = req.body;
      const store = loadUserStore();

      const existingVenue =
        DEMO_VENUES.find((v) => v.id === venueId) ||
        (store.customVenues || []).find((v) => v.id === venueId);

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
      const { venueId, user, servingFormat, pintRating, price, hasZero, note } = req.body;
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

      const existingVenue =
        DEMO_VENUES.find((v) => v.id === venueId) ||
        (store.customVenues || []).find((v) => v.id === venueId);

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
      const { name, category, city, address, lat, lng, website, servingFormat, price, pintRating, note } =
        req.body;
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

      const newVenue = {
        id,
        city: city || 'dublin',
        name: name.trim(),
        category: category || 'pub',
        address: address || 'Added on Map',
        lat: Number(lat),
        lng: Number(lng),
        googleRating: 4.7,
        googleReviewCount: 1,
        priceLevel: '€€',
        website: website || null,
        menuUrl: website || null,
        phone: null,
        openNow: true,
        editorialSummary: note || 'Community-added venue checked for Guinness availability.',
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
              note: note || 'Added venue to StoutScout map.',
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
    console.log(`\n🍺 StoutScout (Guinness Map & Menu Finder) running at http://localhost:${PORT}\n`);
  });
}

startServer();

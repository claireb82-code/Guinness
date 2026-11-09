import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  Search,
  MapPin,
  KeyRound,
  PlusCircle,
  Navigation,
  Star,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  FileSearch,
  MessageSquare,
  Users,
  List,
  Map as MapIcon,
  SlidersHorizontal,
} from 'lucide-react';
import { PintIcon, formatCategoryLabel } from './components/PintIcon.jsx';
import { isPhoneLayout } from './layout.js';
import { RADII_KM, DEFAULT_RADIUS_KM, distanceKm, formatDistance, formatRadius, nearest, pickRadius, locationErrorMessage } from './geo.js';
import { readNearMePref, writeNearMePref } from './nearMePref.js';
import { MapCanvas } from './components/MapCanvas.jsx';
import { VenueDetailPanel } from './components/VenueDetailPanel.jsx';
import { ApiKeyModal } from './components/ApiKeyModal.jsx';
import { AddVenueModal } from './components/AddVenueModal.jsx';

const DEFAULT_CITIES = {
  all: { id: 'all', name: 'All Switzerland 🇨🇭', lat: 46.8182, lng: 8.2275, zoom: 8 },
  zurich: { id: 'zurich', name: 'Zurich', lat: 47.3745, lng: 8.5385, zoom: 14 },
  geneva: { id: 'geneva', name: 'Geneva', lat: 46.2044, lng: 6.1432, zoom: 14 },
  basel: { id: 'basel', name: 'Basel', lat: 47.5546, lng: 7.5886, zoom: 14 },
  bern: { id: 'bern', name: 'Bern', lat: 46.948, lng: 7.445, zoom: 14 },
  lausanne: { id: 'lausanne', name: 'Lausanne', lat: 46.521, lng: 6.6323, zoom: 14 },
  lucerne: { id: 'lucerne', name: 'Lucerne', lat: 47.0518, lng: 8.3075, zoom: 14 },
};

export default function App() {
  const [cities, setCities] = useState(DEFAULT_CITIES);
  const [activeCity, setActiveCity] = useState('all');
  const [mapCenter, setMapCenter] = useState({ lat: 46.8182, lng: 8.2275, zoom: 8 });

  const [venues, setVenues] = useState([]);
  const [loading, setLoading] = useState(true);
  const [batchScanning, setBatchScanning] = useState(false);
  const [selectedVenueId, setSelectedVenueId] = useState(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('all');
  // Default: only venues that serve Guinness ("Show All" is one click away).
  const [guinnessFilter, setGuinnessFilter] = useState('serves_any');
  // Phone layout: one pane at a time (map or list) plus a bottom "Filters" sheet. The map comes first. Desktop ignores these.
  const [mobileView, setMobileView] = useState('map');
  const [filtersOpen, setFiltersOpen] = useState(false);
  // "Near me": the position stays in this browser (never stored); it is sent to the server only if the visitor
  // asks to scan their area. nearbyKm === null means "anywhere".
  const [userLocation, setUserLocation] = useState(null);
  const [nearbyKm, setNearbyKm] = useState(null);
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState('');
  // Near me is on by default: on load we quietly ask for the position (see the effects below). Only the visitor's
  // on/off + radius preference is remembered, never the location. Anything the visitor picks themselves wins.
  const [nearAuto, setNearAuto] = useState(false); // near me was switched on automatically (not by a click)
  const [nearMeNotice, setNearMeNotice] = useState('');
  const [autoPending, setAutoPending] = useState(false); // position known, waiting for venues to pick a radius
  const userChoseRef = useRef(false);
  const autoStartedRef = useRef(false);
  const nearMePrefRef = useRef(null);
  if (nearMePrefRef.current === null) {
    nearMePrefRef.current = typeof localStorage === 'undefined' ? {} : readNearMePref(localStorage);
  }
  const rememberNearMe = (pref) => {
    nearMePrefRef.current = pref;
    if (typeof localStorage !== 'undefined') writeNearMePref(localStorage, pref);
  };
  const userPicked = () => {
    userChoseRef.current = true;
    setNearAuto(false);
    setNearMeNotice('');
  };

  // Google Maps & Mode State
  const [googleApiKey, setGoogleApiKey] = useState(() => localStorage.getItem('stoutscout_gmaps_key') || '');
  const [mode, setMode] = useState('demo');
  const [autoScrapeMenus, setAutoScrapeMenus] = useState(true);

  // Modals
  const [apiKeyModalOpen, setApiKeyModalOpen] = useState(false);
  const [addVenueModalOpen, setAddVenueModalOpen] = useState(false);
  const [clickedCoords, setClickedCoords] = useState(null);

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((cfg) => {
        if (cfg.cities) setCities(cfg.cities);
        if (cfg.envApiKey && !googleApiKey) {
          setGoogleApiKey(cfg.envApiKey);
        }
      })
      .catch(() => {});
  }, []);

  const loadVenues = async ({
    cityKey = activeCity,
    targetLat = mapCenter.lat,
    targetLng = mapCenter.lng,
    targetMode = mode,
    overrideKey = googleApiKey,
  } = {}) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        city: cityKey,
        lat: String(targetLat),
        lng: String(targetLng),
        mode: targetMode,
        scrapeMenus: String(autoScrapeMenus),
      });

      const res = await fetch(`/api/venues?${params.toString()}`, {
        headers: overrideKey ? { 'x-google-maps-key': overrideKey } : {},
      });
      const data = await res.json();
      if (!res.ok && data.error && targetMode !== 'demo') window.alert(data.error);
      if (data.venues) {
        setVenues(data.venues);
        // Desktop opens the first venue in the side panel; on a phone that would cover the whole list.
        if (data.venues.length > 0 && !selectedVenueId && !isPhoneLayout()) {
          setSelectedVenueId(data.venues[0].id);
        }
      }
    } catch (err) {
      console.error('Failed to load venues:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const preset = cities[activeCity] || DEFAULT_CITIES.dublin;
    setMapCenter({ lat: preset.lat, lng: preset.lng, zoom: preset.zoom || 14 });
    loadVenues({
      cityKey: activeCity,
      targetLat: preset.lat,
      targetLng: preset.lng,
      targetMode: mode,
    });
  }, [activeCity, mode]);

  const handleSaveApiKey = (newKey) => {
    setGoogleApiKey(newKey);
    localStorage.setItem('stoutscout_gmaps_key', newKey);
  };

  // One-shot position request (no watching: it would drain the battery). Resolves { loc } or { error }.
  const locateMe = () =>
    new Promise((resolve) => {
      setLocationError('');
      if (!navigator.geolocation) {
        const error = locationErrorMessage();
        setLocationError(error);
        resolve({ error });
        return;
      }
      setLocating(true);
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const loc = { lat: pos.coords.latitude, lng: pos.coords.longitude };
          setUserLocation(loc);
          setLocating(false);
          resolve({ loc });
        },
        (err) => {
          const error = locationErrorMessage(err);
          setLocationError(error);
          setLocating(false);
          resolve({ error });
        },
        { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 }
      );
    });

  // Default Near me, step 1: on load, quietly ask for the position - unless the visitor switched Near me off last
  // time or the browser already says no. No error is shown if it fails: the app just stays on "Anywhere".
  useEffect(() => {
    if (autoStartedRef.current) return;
    autoStartedRef.current = true;
    if (nearMePrefRef.current.mode === 'off' || !navigator.geolocation) return;
    const ask = () => {
      setLocating(true);
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setLocating(false);
          if (userChoseRef.current) return;
          setUserLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude });
          setAutoPending(true);
        },
        () => setLocating(false),
        { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 }
      );
    };
    const permissions = navigator.permissions?.query ? navigator.permissions.query({ name: 'geolocation' }) : null;
    if (!permissions) return ask();
    permissions.then((p) => (p.state === 'denied' ? undefined : ask()), ask);
  }, []);

  // Step 2: once the venues are in, start at the saved radius (default 500 m) and widen until something is in range.
  // Venues that the current type/search/Guinness filters hide don't count, so the list is never empty on arrival.
  useEffect(() => {
    if (!autoPending || loading) return;
    setAutoPending(false);
    if (userChoseRef.current || venues.length === 0) return;
    const wanted = nearMePrefRef.current.km ?? DEFAULT_RADIUS_KM;
    const candidates = venues.filter((v) => matchesFilters(v, guinnessFilter, { ignoreRadius: true }));
    const radius = pickRadius(candidates, userLocation, wanted);
    if (radius === null) {
      const closest = nearest(candidates, userLocation);
      setNearMeNotice(
        closest
          ? `The nearest venue is ${formatDistance(closest.distanceKm)} from you, so we're showing everywhere in Switzerland.`
          : ''
      );
      return;
    }
    showWholeCountry();
    setNearbyKm(radius);
    setNearAuto(true);
    if (radius > wanted) setNearMeNotice(`Nothing within ${formatRadius(wanted)} of you, so we're showing ${formatRadius(radius)}.`);
  }, [autoPending, loading, venues]);

  // Near-me works on the whole country: leave a single-city view first.
  const showWholeCountry = () => {
    if (activeCity !== 'all' && mode === 'demo') setActiveCity('all');
  };

  const chooseRadius = async (km) => {
    userPicked();
    if (km === null) {
      setNearbyKm(null);
      setLocationError('');
      rememberNearMe({ mode: 'off' });
      return;
    }
    const { loc } = userLocation ? { loc: userLocation } : await locateMe();
    if (loc) {
      showWholeCountry();
      setNearbyKm(km);
      rememberNearMe({ mode: 'on', km });
    }
  };

  // The header "Near Me" button: refresh the position and filter to the default radius.
  const handleUseMyLocation = async () => {
    userPicked();
    const { loc, error } = await locateMe();
    if (!loc) {
      window.alert(error);
      return;
    }
    showWholeCountry();
    setNearbyKm((km) => km ?? nearMePrefRef.current.km ?? DEFAULT_RADIUS_KM);
    rememberNearMe({ mode: 'on', km: nearbyKm ?? nearMePrefRef.current.km ?? DEFAULT_RADIUS_KM });
    if (googleApiKey) {
      setMode('live');
      loadVenues({ cityKey: 'custom', targetLat: loc.lat, targetLng: loc.lng, targetMode: 'live' });
    }
  };

  // Ask the server to look for venues around the visitor (OpenStreetMap). This is the one place the position leaves the browser.
  const scanAroundMe = () => {
    if (!userLocation) return;
    userPicked();
    setGuinnessFilter('all'); // freshly scanned venues are unchecked, so the default "Serves Guinness" filter would hide them
    loadVenues({ cityKey: 'custom', targetLat: userLocation.lat, targetLng: userLocation.lng, targetMode: 'osm' });
  };

  const handleScanSingleMenu = async (venueId, websiteUrl) => {
    const res = await fetch('/api/scan-menu', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ venueId, websiteUrl }),
    });
    const data = await res.json();
    if (res.status === 429) {
      window.alert(data.error || 'Scan limit reached. Please wait a few minutes and try again.');
      return { ...data, rateLimited: true };
    }
    if (data.venue) {
      setVenues((prev) => prev.map((v) => (v.id === venueId ? data.venue : v)));
    }
    return data;
  };

  const handleBatchScanMenus = async () => {
    setBatchScanning(true);
    try {
      for (const v of filteredVenues) {
        if (v.website || v.menuUrl) {
          const result = await handleScanSingleMenu(v.id, v.menuUrl || v.website);
          if (result && result.rateLimited) break;
        }
      }
    } finally {
      setBatchScanning(false);
    }
  };

  const handleSubmitCrowdReport = async (payload) => {
    const res = await fetch('/api/crowd-report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      window.alert(data.error || 'Could not save your report. Please try again.');
      return;
    }
    if (data.venue) {
      setVenues((prev) => prev.map((v) => (v.id === payload.venueId ? data.venue : v)));
    }
  };

  const handleAddVenue = async (newVenueData) => {
    const res = await fetch('/api/add-venue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newVenueData),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      window.alert(data.error || 'Could not add the venue. Please try again.');
      return;
    }
    if (data.venue) {
      setVenues((prev) => [data.venue, ...prev]);
      setSelectedVenueId(data.venue.id);
      setMapCenter({ lat: data.venue.lat, lng: data.venue.lng, zoom: 15 });
    }
  };

  const handleCheckGoogleMaps = async ({ query = '', website = '', city = activeCity, lat = mapCenter.lat, lng = mapCenter.lng } = {}) => {
    setLoading(true);
    try {
      const res = await fetch('/api/check-google-maps', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(googleApiKey ? { 'x-google-maps-key': googleApiKey } : {}),
        },
        body: JSON.stringify({ query, website, city, lat, lng, radius: 3500 }),
      });
      const data = await res.json();
      if (data.allVenues) {
        setVenues(data.allVenues);
        if (data.venues?.[0]) {
          setSelectedVenueId(data.venues[0].id);
          setMapCenter({ lat: data.venues[0].lat, lng: data.venues[0].lng, zoom: 15 });
        }
      }
      return data;
    } finally {
      setLoading(false);
    }
  };

  // Filtered Venues
  const nearMeActive = nearbyKm !== null && userLocation !== null;

  const matchesFilters = (v, guinnessMode, { ignoreRadius = false } = {}) => {
    // Category Filter
    if (categoryFilter !== 'all' && v.category !== categoryFilter) return false;

    // Near me: within the chosen radius of the visitor
    if (nearMeActive && !ignoreRadius && !(distanceKm(userLocation, v) <= nearbyKm)) return false;

    // Guinness Availability Filter
    const status = v.guinnessSummary?.status;
    if (guinnessMode === 'serves_any') {
      if (status === 'no_guinness' || status === 'unverified') return false;
    } else if (guinnessMode === 'draught_only') {
      if (status !== 'confirmed_draught') return false;
    } else if (guinnessMode === 'on_menu') {
      if (!v.menuCheck?.foundOnMenu) return false;
    } else if (guinnessMode === 'in_reviews') {
      if (!(v.reviewCheck?.mentionCount > 0)) return false;
    } else if (guinnessMode === 'guinness_zero') {
      const hasZero = v.crowdCheck?.hasZero || v.menuCheck?.typesFound?.some((t) => /0\.0|zero/i.test(t));
      if (!hasZero) return false;
    }

    // Search Query Filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const inName = v.name?.toLowerCase().includes(q);
      const inAddr = v.address?.toLowerCase().includes(q);
      const inMenu = v.menuCheck?.snippets?.some((s) => s.toLowerCase().includes(q));
      const inSummary = v.editorialSummary?.toLowerCase().includes(q);
      if (!inName && !inAddr && !inMenu && !inSummary) return false;
    }

    return true;
  };

  const distanceById = useMemo(
    () => (nearMeActive ? new Map(venues.map((v) => [v.id, distanceKm(userLocation, v)])) : new Map()),
    [venues, nearMeActive, userLocation]
  );

  // With Near me on, the list is sorted nearest first.
  const filteredVenues = useMemo(() => {
    const list = venues.filter((v) => matchesFilters(v, guinnessFilter));
    return nearMeActive ? [...list].sort((a, b) => (distanceById.get(a.id) ?? Infinity) - (distanceById.get(b.id) ?? Infinity)) : list;
  }, [venues, categoryFilter, guinnessFilter, searchQuery, nearbyKm, userLocation, distanceById]);

  // When nothing is near: the closest venue that would otherwise match, and the next radius up.
  const nearestMatch = useMemo(
    () =>
      nearMeActive && filteredVenues.length === 0
        ? nearest(venues.filter((v) => matchesFilters(v, guinnessFilter, { ignoreRadius: true })), userLocation)
        : null,
    [venues, categoryFilter, guinnessFilter, searchQuery, nearbyKm, userLocation, filteredVenues.length]
  );
  const nextRadius = nearbyKm === null ? null : RADII_KM.find((r) => r > nearbyKm) ?? null;

  // Venues hidden only because the default "Serves Guinness" filter is on (not by type or search).
  const hiddenByGuinnessFilter = useMemo(
    () => (guinnessFilter === 'all' ? 0 : venues.filter((v) => matchesFilters(v, 'all')).length - filteredVenues.length),
    [venues, categoryFilter, guinnessFilter, searchQuery, nearbyKm, userLocation, filteredVenues]
  );

  const selectedVenue = useMemo(
    () => venues.find((v) => v.id === selectedVenueId) || null,
    [venues, selectedVenueId]
  );

  // Header stats count every venue matching the type/search filters, so they stay meaningful
  // while the (default) "Serves Guinness" filter hides the rest of the list.
  const stats = useMemo(() => {
    const pool = venues.filter((v) => matchesFilters(v, 'all'));
    // "Confirmed" is real evidence only; guesses (an Irish-sounding name, an OpenStreetMap tag) are counted apart as "likely".
    const confirmed = pool.filter(
      (v) => v.guinnessSummary?.status === 'confirmed_draught' || v.guinnessSummary?.status === 'cans_or_bottles'
    ).length;
    const likely = pool.filter((v) => v.guinnessSummary?.status === 'likely_serves').length;
    const onMenuCount = pool.filter((v) => v.menuCheck?.foundOnMenu).length;
    return { total: pool.length, confirmed, likely, onMenuCount };
  }, [venues, categoryFilter, searchQuery, nearbyKm, userLocation]);

  return (
    <div className="app-shell m-ui">
      <div className="foam-accent-bar" />

      {/* Top Navigation Header */}
      <header className="top-header">
        <div className="brand-group">
          <PintIcon size={36} status="confirmed_draught" />
          <div>
            <div className="brand-title">
              Guinness Guide
              <span
                style={{
                  fontSize: '0.66rem',
                  fontFamily: 'Inter, sans-serif',
                  padding: '0.15rem 0.5rem',
                  borderRadius: 999,
                  background: 'rgba(200, 164, 93, 0.18)',
                  border: '1px solid rgba(200, 164, 93, 0.4)',
                  color: '#e2be75',
                  fontWeight: 600,
                }}
              >
                🇨🇭 SWITZERLAND
              </span>
            </div>
            <div className="brand-subtitle">
              Swiss Hotels · Bars · Pubs · Restaurants — Guinness Menu Radar
            </div>
          </div>
        </div>

        {/* City Selector + Search Bar */}
        <div className="header-search" style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', flex: 1, maxWidth: 640 }}>
          <div className="city-pills" style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            {Object.values(cities).map((c) => (
              <button
                key={c.id}
                type="button"
                className={`filter-pill ${activeCity === c.id && mode === 'demo' ? 'active' : ''}`}
                onClick={() => {
                  userPicked();
                  setNearbyKm(null); // picking a city means "browse that city", not "near me"
                  setMode('demo');
                  setActiveCity(c.id);
                }}
              >
                <MapPin size={12} /> {c.name.split(',')[0]}
              </button>
            ))}
            <button
              type="button"
              className="filter-pill"
              onClick={handleUseMyLocation}
              aria-pressed={nearbyKm !== null && userLocation !== null}
              title="Show venues near you, nearest first. Your location stays in your browser."
            >
              <Navigation size={12} /> Near Me
            </button>
          </div>

          <div style={{ position: 'relative', flex: 1, minWidth: 180 }}>
            <Search
              size={14}
              color="#9c8e7b"
              style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)' }}
            />
            <input
              type="text"
              className="stout-input"
              style={{ width: '100%', paddingLeft: 30, fontSize: '0.79rem' }}
              placeholder="Search venues, streets, or menu items (e.g. '0.0', 'oysters')..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        {/* Right Action Controls */}
        <div className="header-actions" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <button
            type="button"
            className="btn-outline"
            aria-label="Add or check a venue"
            onClick={() => {
              setClickedCoords({ lat: mapCenter.lat, lng: mapCenter.lng });
              setAddVenueModalOpen(true);
            }}
          >
            <PlusCircle size={14} color="#c8a45d" /> <span className="btn-label">Add / Check Venue</span>
          </button>

          <button
            type="button"
            className="btn-gold"
            aria-label="API key and data mode"
            onClick={() => setApiKeyModalOpen(true)}
            title="Configure Google Maps API Key or switch between Demo and Live Google Places mode"
          >
            <KeyRound size={14} />
            <span className="btn-label">{mode === 'live' && googleApiKey ? 'Google Places: Live' : 'API Key / Mode'}</span>
          </button>
        </div>
      </header>

      {/* Secondary Filter Strip (a bottom sheet on phones) */}
      {filtersOpen && <div className="sheet-backdrop" onClick={() => setFiltersOpen(false)} />}
      <div className={`toolbar-strip ${filtersOpen ? 'open' : ''}`} role="group" aria-label="Filters">
        <div className="sheet-header">
          <strong>Filters</strong>
          <button type="button" className="btn-gold" onClick={() => setFiltersOpen(false)}>
            Show {filteredVenues.length} venue{filteredVenues.length === 1 ? '' : 's'}
          </button>
        </div>
        {/* Venue Categories */}
        <div className="pill-group">
          <span style={{ fontSize: '0.72rem', color: '#9c8e7b', fontWeight: 600, marginRight: 4 }}>
            VENUE TYPE:
          </span>
          {[
            { id: 'all', label: 'All Venues' },
            { id: 'pub', label: '🍺 Pubs' },
            { id: 'bar', label: '🍸 Bars' },
            { id: 'restaurant', label: '🍽️ Restaurants' },
            { id: 'hotel', label: '🏨 Hotels' },
          ].map((cat) => (
            <button
              key={cat.id}
              type="button"
              className={`filter-pill ${categoryFilter === cat.id ? 'active' : ''}`}
              onClick={() => setCategoryFilter(cat.id)}
            >
              {cat.label}
            </button>
          ))}
        </div>

        {/* Guinness Verification Filter */}
        <div className="pill-group">
          <span style={{ fontSize: '0.72rem', color: '#9c8e7b', fontWeight: 600, marginRight: 4 }}>
            GUINNESS FILTER:
          </span>
          {[
            { id: 'all', label: 'Show All' },
            { id: 'serves_any', label: '✓ Serves Guinness' },
            { id: 'draught_only', label: '🍺 Draught On Tap' },
            { id: 'on_menu', label: '📜 Found on Menu' },
            { id: 'in_reviews', label: '💬 In Google Reviews' },
            { id: 'guinness_zero', label: '0.0 Available' },
          ].map((gf) => (
            <button
              key={gf.id}
              type="button"
              className={`filter-pill ${guinnessFilter === gf.id ? 'active' : ''}`}
              onClick={() => setGuinnessFilter(gf.id)}
            >
              {gf.label}
            </button>
          ))}
        </div>

        {/* Near me: filter by distance from the visitor (nearest first). The position never leaves the browser. */}
        <div className="pill-group near-me-group" role="group" aria-label="Distance from you">
          <span style={{ fontSize: '0.72rem', color: '#9c8e7b', fontWeight: 600, marginRight: 4 }} title="Your location is only used in your browser to filter and sort this list.">
            NEAR ME:
          </span>
          <button type="button" className={`filter-pill ${nearbyKm === null ? 'active' : ''}`} onClick={() => chooseRadius(null)}>
            Anywhere
          </button>
          {RADII_KM.map((km) => (
            <button
              key={km}
              type="button"
              className={`filter-pill ${nearbyKm === km ? 'active' : ''}`}
              aria-pressed={nearbyKm === km}
              onClick={() => chooseRadius(km)}
            >
              📍 {formatRadius(km)}
            </button>
          ))}
          {locating && <span className="near-status" role="status">Locating you…</span>}
          {locationError && (
            <span className="near-error" role="alert">
              {locationError}
            </span>
          )}
          {nearMeNotice && (
            <span className="near-notice" role="status">
              {nearMeNotice}
            </span>
          )}
        </div>
      </div>

      {/* Main Split Workspace */}
      <div className="main-workspace" data-view={mobileView}>
        {/* Left Sidebar List */}
        <div className="sidebar-list">
          <div
            style={{
              padding: '0.7rem 0.9rem',
              borderBottom: '1px solid #332a21',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: '#14110e',
            }}
          >
            <div>
              <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#f5efe6' }}>
                {stats.confirmed} of {stats.total} venues confirmed to serve Guinness
              </div>
              <div style={{ fontSize: '0.7rem', color: '#9c8e7b' }}>
                {stats.likely} more are likely (unverified) · {stats.onMenuCount} mention it on their website
              </div>
            </div>

            <button
              type="button"
              className="btn-outline"
              style={{ padding: '0.32rem 0.6rem', fontSize: '0.72rem' }}
              onClick={handleBatchScanMenus}
              disabled={batchScanning}
              title="Crawl & verify online menus for all listed venues"
            >
              <RefreshCw size={12} /> {batchScanning ? 'Scanning...' : 'Scan All Menus'}
            </button>
          </div>

          <div className="venue-cards-scroll">
            {loading ? (
              <div style={{ padding: '2rem 1rem', textAlign: 'center', color: '#b8ab99', fontSize: '0.84rem' }}>
                Scanning area for hotels, bars, pubs & restaurants...
              </div>
            ) : filteredVenues.length === 0 ? (
              <div style={{ padding: '2rem 1rem', textAlign: 'center', color: '#b8ab99', fontSize: '0.84rem' }}>
                {nearMeActive ? (
                  <>
                    No matching venues within {formatRadius(nearbyKm)} of you.
                    {nearestMatch && (
                      <>
                        <br />
                        The nearest match is {formatDistance(nearestMatch.distanceKm)} away: {nearestMatch.name}.
                      </>
                    )}
                    <div className="near-actions">
                      {nextRadius && (
                        <button type="button" className="filter-pill" onClick={() => chooseRadius(nextRadius)}>
                          Try {formatRadius(nextRadius)}
                        </button>
                      )}
                      <button type="button" className="filter-pill" onClick={() => chooseRadius(null)}>
                        Show everywhere
                      </button>
                      <button type="button" className="filter-pill" onClick={scanAroundMe}>
                        Scan around me
                      </button>
                    </div>
                  </>
                ) : hiddenByGuinnessFilter > 0 ? (
                  <>
                    No venues here are confirmed to serve Guinness yet.
                    <br />
                    {hiddenByGuinnessFilter} other venue{hiddenByGuinnessFilter === 1 ? ' is' : 's are'} hidden because{' '}
                    {hiddenByGuinnessFilter === 1 ? "it hasn't" : "they haven't"} been checked or reported as serving it.
                    <br />
                    <button type="button" className="filter-pill" style={{ marginTop: '0.8rem' }} onClick={() => setGuinnessFilter('all')}>
                      Show all venues
                    </button>
                  </>
                ) : (
                  'No venues match your current filters. Try another category or clear the search.'
                )}
              </div>
            ) : (
              filteredVenues.map((venue) => {
                const summary = venue.guinnessSummary || {};
                const isSelected = selectedVenueId === venue.id;

                return (
                  <div
                    key={venue.id}
                    className={`venue-card ${isSelected ? 'selected' : ''}`}
                    onClick={() => setSelectedVenueId(venue.id)}
                  >
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'flex-start',
                        gap: '0.5rem',
                        marginBottom: '0.35rem',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                        <span
                          style={{
                            fontSize: '0.65rem',
                            textTransform: 'uppercase',
                            letterSpacing: '0.08em',
                            padding: '0.1rem 0.42rem',
                            borderRadius: 4,
                            background: '#2b231b',
                            color: '#c8a45d',
                            fontWeight: 700,
                          }}
                        >
                          {formatCategoryLabel(venue.category)}
                        </span>
                        <span className={`status-badge status-${summary.status}`}>
                          {summary.status === 'confirmed_draught' || summary.status === 'cans_or_bottles' ? (
                            <CheckCircle2 size={11} />
                          ) : summary.status === 'no_guinness' ? (
                            <XCircle size={11} />
                          ) : (
                            <AlertTriangle size={11} />
                          )}
                          {summary.statusLabel}
                        </span>
                        {nearMeActive && Number.isFinite(distanceById.get(venue.id)) && (
                          <span className="distance-badge" title="Distance from you">
                            📍 {formatDistance(distanceById.get(venue.id))}
                          </span>
                        )}
                      </div>

                      {venue.crowdCheck?.avgPintRating && (
                        <span
                          style={{
                            fontSize: '0.76rem',
                            fontWeight: 700,
                            color: '#f5efe6',
                            background: 'rgba(200, 164, 93, 0.2)',
                            padding: '0.12rem 0.45rem',
                            borderRadius: 6,
                            whiteSpace: 'nowrap',
                          }}
                        >
                          🍺 {venue.crowdCheck.avgPintRating}
                        </span>
                      )}
                    </div>

                    <h3
                      className="font-serif-guinness"
                      style={{ fontSize: '1rem', color: '#f5efe6', marginBottom: '0.2rem' }}
                    >
                      {venue.name}
                    </h3>

                    <div style={{ fontSize: '0.73rem', color: '#9c8e7b', marginBottom: '0.5rem' }}>
                      {venue.address}
                    </div>

                    {/* Menu Snippet Preview */}
                    {venue.menuCheck?.snippets?.[0] && (
                      <div
                        style={{
                          fontSize: '0.72rem',
                          background: '#14110e',
                          borderLeft: `2px solid ${
                            venue.menuCheck.foundOnMenu ? '#c8a45d' : '#57493a'
                          }`,
                          padding: '0.35rem 0.55rem',
                          borderRadius: '0 4px 4px 0',
                          color: '#d7cbb8',
                          marginBottom: '0.55rem',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                      >
                        📜 {venue.menuCheck.snippets[0]}
                      </div>
                    )}

                    {/* 3-Pillar Mini Indicators */}
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        fontSize: '0.7rem',
                        color: '#b8ab99',
                        borderTop: '1px solid #2b231b',
                        paddingTop: '0.45rem',
                      }}
                    >
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 4,
                          color: venue.menuCheck?.foundOnMenu ? '#6ee7b7' : '#8f7e68',
                        }}
                      >
                        <FileSearch size={12} />
                        {venue.menuCheck?.foundOnMenu ? 'Menu Verified' : 'No Menu Match'}
                      </span>

                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                        <MessageSquare size={12} color="#c8a45d" />
                        {venue.reviewCheck?.mentionCount || 0} rev.
                      </span>

                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                        <Users size={12} color="#c8a45d" />
                        {venue.crowdCheck?.reportedPrice ||
                          venue.menuCheck?.extractedPrice ||
                          `${venue.crowdCheck?.confirmedCount || 0} reports`}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Center Map View */}
        <div className="map-pane">
          <MapCanvas
            center={mapCenter}
            zoom={mapCenter.zoom}
            venues={filteredVenues}
            selectedVenue={selectedVenue}
            onSelectVenue={(v) => setSelectedVenueId(v.id)}
            googleApiKey={mode === 'live' ? googleApiKey : ''}
            userLocation={nearMeActive ? userLocation : null}
            radiusKm={nearMeActive ? nearbyKm : null}
            onMapClickForNewVenue={(coords) => {
              setClickedCoords(coords);
              setAddVenueModalOpen(true);
            }}
          />
        </div>

        {/* Right Venue Inspection & Crowdsourcing Drawer */}
        {selectedVenue && (
          <VenueDetailPanel
            venue={selectedVenue}
            distanceKm={nearMeActive ? distanceById.get(selectedVenue.id) : null}
            onClose={() => setSelectedVenueId(null)}
            onScanMenu={handleScanSingleMenu}
            onSubmitCrowdReport={handleSubmitCrowdReport}
          />
        )}
      </div>

      {/* Phone navigation: one pane at a time. Hidden on larger screens by CSS. */}
      <nav className="mobile-nav" aria-label="Views">
        <button
          type="button"
          className={mobileView === 'list' ? 'active' : ''}
          aria-current={mobileView === 'list' ? 'page' : undefined}
          onClick={() => setMobileView('list')}
        >
          <List size={20} aria-hidden="true" />
          <span>List</span>
          <span className="nav-count">{filteredVenues.length}</span>
        </button>
        <button
          type="button"
          className={mobileView === 'map' ? 'active' : ''}
          aria-current={mobileView === 'map' ? 'page' : undefined}
          onClick={() => setMobileView('map')}
        >
          <MapIcon size={20} aria-hidden="true" />
          <span>Map</span>
        </button>
        <button type="button" aria-expanded={filtersOpen} onClick={() => setFiltersOpen((open) => !open)}>
          <SlidersHorizontal size={20} aria-hidden="true" />
          <span>Filters</span>
          {(categoryFilter !== 'all' || guinnessFilter !== 'serves_any' || (nearbyKm !== null && !nearAuto)) && <i className="nav-dot" title="Filters changed" />}
        </button>
      </nav>

      {/* Modals */}
      <ApiKeyModal
        isOpen={apiKeyModalOpen}
        onClose={() => setApiKeyModalOpen(false)}
        googleApiKey={googleApiKey}
        onSaveApiKey={handleSaveApiKey}
        mode={mode}
        onChangeMode={setMode}
        autoScrapeMenus={autoScrapeMenus}
        onChangeAutoScrape={setAutoScrapeMenus}
        onTriggerLiveScan={(overrideKey) =>
          loadVenues({
            cityKey: 'custom',
            targetLat: mapCenter.lat,
            targetLng: mapCenter.lng,
            targetMode: 'live',
            overrideKey,
          })
        }
      />

      <AddVenueModal
        isOpen={addVenueModalOpen}
        onClose={() => setAddVenueModalOpen(false)}
        initialCoords={clickedCoords || mapCenter}
        activeCity={activeCity}
        onAddVenue={handleAddVenue}
        onCheckGoogleMaps={handleCheckGoogleMaps}
      />
    </div>
  );
}

import React, { useState, useEffect, useMemo } from 'react';
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
} from 'lucide-react';
import { PintIcon, formatCategoryLabel } from './components/PintIcon.jsx';
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
  const [guinnessFilter, setGuinnessFilter] = useState('all');

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
      if (data.venues) {
        setVenues(data.venues);
        if (data.venues.length > 0 && !selectedVenueId) {
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

  const handleUseMyLocation = () => {
    if (!navigator.geolocation) {
      alert('Geolocation is not supported by your browser.');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        setMapCenter({ lat, lng, zoom: 14 });
        if (googleApiKey) {
          setMode('live');
          loadVenues({ cityKey: 'custom', targetLat: lat, targetLng: lng, targetMode: 'live' });
        }
      },
      () => {
        alert('Could not access your GPS location. Please check browser permissions.');
      }
    );
  };

  const handleScanSingleMenu = async (venueId, websiteUrl) => {
    const res = await fetch('/api/scan-menu', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ venueId, websiteUrl }),
    });
    const data = await res.json();
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
          await handleScanSingleMenu(v.id, v.menuUrl || v.website);
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
    if (data.venue) {
      setVenues((prev) => [data.venue, ...prev]);
      setSelectedVenueId(data.venue.id);
      setMapCenter({ lat: data.venue.lat, lng: data.venue.lng, zoom: 15 });
    }
  };

  // Filtered Venues
  const filteredVenues = useMemo(() => {
    return venues.filter((v) => {
      // Category Filter
      if (categoryFilter !== 'all' && v.category !== categoryFilter) {
        return false;
      }

      // Guinness Availability Filter
      const status = v.guinnessSummary?.status;
      if (guinnessFilter === 'serves_any') {
        if (status === 'no_guinness' || status === 'unverified') return false;
      } else if (guinnessFilter === 'draught_only') {
        if (status !== 'confirmed_draught') return false;
      } else if (guinnessFilter === 'on_menu') {
        if (!v.menuCheck?.foundOnMenu) return false;
      } else if (guinnessFilter === 'in_reviews') {
        if (!(v.reviewCheck?.mentionCount > 0)) return false;
      } else if (guinnessFilter === 'guinness_zero') {
        const hasZero =
          v.crowdCheck?.hasZero ||
          v.menuCheck?.typesFound?.some((t) => /0\.0|zero/i.test(t));
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
    });
  }, [venues, categoryFilter, guinnessFilter, searchQuery]);

  const selectedVenue = useMemo(
    () => venues.find((v) => v.id === selectedVenueId) || null,
    [venues, selectedVenueId]
  );

  const stats = useMemo(() => {
    const serving = filteredVenues.filter(
      (v) =>
        v.guinnessSummary?.status === 'confirmed_draught' ||
        v.guinnessSummary?.status === 'cans_or_bottles' ||
        v.guinnessSummary?.status === 'likely_serves'
    ).length;
    const onMenuCount = filteredVenues.filter((v) => v.menuCheck?.foundOnMenu).length;
    return {
      total: filteredVenues.length,
      serving,
      onMenuCount,
    };
  }, [filteredVenues]);

  return (
    <div className="app-shell">
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', flex: 1, maxWidth: 640 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            {Object.values(cities).map((c) => (
              <button
                key={c.id}
                type="button"
                className={`filter-pill ${activeCity === c.id && mode === 'demo' ? 'active' : ''}`}
                onClick={() => {
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
              title="Locate venues near your current GPS coordinates"
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <button
            type="button"
            className="btn-outline"
            onClick={() => {
              setClickedCoords({ lat: mapCenter.lat, lng: mapCenter.lng });
              setAddVenueModalOpen(true);
            }}
          >
            <PlusCircle size={14} color="#c8a45d" /> Add / Check Venue
          </button>

          <button
            type="button"
            className="btn-gold"
            onClick={() => setApiKeyModalOpen(true)}
            title="Configure Google Maps API Key or switch between Demo and Live Google Places mode"
          >
            <KeyRound size={14} />
            {mode === 'live' && googleApiKey ? 'Google Places: Live' : 'API Key / Mode'}
          </button>
        </div>
      </header>

      {/* Secondary Filter Strip */}
      <div className="toolbar-strip">
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
      </div>

      {/* Main Split Workspace */}
      <div className="main-workspace">
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
                {stats.serving} of {stats.total} Venues Serve Guinness
              </div>
              <div style={{ fontSize: '0.7rem', color: '#9c8e7b' }}>
                {stats.onMenuCount} confirmed directly via online menu scan
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
                No venues match your current filters. Try switching to "Show All" or another category.
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
            onClose={() => setSelectedVenueId(null)}
            onScanMenu={handleScanSingleMenu}
            onSubmitCrowdReport={handleSubmitCrowdReport}
          />
        )}
      </div>

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
      />
    </div>
  );
}

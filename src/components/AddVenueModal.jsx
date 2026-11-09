import React, { useState, useEffect } from 'react';
import { PlusCircle, X, Search, Globe2 } from 'lucide-react';

export function AddVenueModal({
  isOpen,
  onClose,
  initialCoords,
  coordsFromClick = false,
  activeCity,
  onAddVenue,
  onCheckGoogleMaps,
}) {
  const [gmapsQuery, setGmapsQuery] = useState('');
  const [gmapsWebsite, setGmapsWebsite] = useState('');
  const [checkingGmaps, setCheckingGmaps] = useState(false);

  const [name, setName] = useState('');
  const [category, setCategory] = useState('pub');
  const [address, setAddress] = useState('');
  const [lat, setLat] = useState(initialCoords?.lat || 47.3745);
  const [lng, setLng] = useState(initialCoords?.lng || 8.5385);
  const [website, setWebsite] = useState('');
  const [servingFormat, setServingFormat] = useState('draught');
  const [price, setPrice] = useState('');
  const [pintRating, setPintRating] = useState('4.8');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  // Where the position came from. Only a click on the map, a successful address lookup or typed coordinates count as
  // the visitor choosing a place; "default" is just wherever the map was centred, which is not the venue's position.
  const [coordsSource, setCoordsSource] = useState(coordsFromClick ? 'map' : 'default');
  const [lookup, setLookup] = useState({ status: 'idle', label: '', address: '' });
  const [formError, setFormError] = useState('');

  // Each time the form opens: start from the clicked spot (or the map centre, which does not count as a chosen place).
  useEffect(() => {
    if (!isOpen) return;
    if (initialCoords) {
      setLat(initialCoords.lat);
      setLng(initialCoords.lng);
    }
    setCoordsSource(coordsFromClick ? 'map' : 'default');
    setLookup({ status: 'idle', label: '', address: '' });
    setFormError('');
  }, [isOpen]);

  // Ask the server where an address is. Resolves { lat, lng, label }, or { error } with a message for the visitor.
  const findAddress = async (text) => {
    setLookup({ status: 'busy', label: '', address: text });
    try {
      const res = await fetch(`/api/geocode?q=${encodeURIComponent(text)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'The address lookup is busy right now. Please try again.');
      if (!data.found) {
        const error = `We couldn't find "${text}" in Switzerland. Check the address, or click the map to place the venue.`;
        setLookup({ status: 'notfound', label: '', address: text });
        return { error };
      }
      setLat(data.lat);
      setLng(data.lng);
      setCoordsSource('lookup');
      setLookup({ status: 'found', label: data.label, address: text });
      return { lat: data.lat, lng: data.lng, label: data.label };
    } catch (err) {
      setLookup({ status: 'error', label: '', address: text });
      return { error: err.message || 'The address lookup is busy right now. Please try again.' };
    }
  };

  if (!isOpen) return null;

  const handleGmapsCheckSubmit = async (e) => {
    e.preventDefault();
    if (!onCheckGoogleMaps) return;
    setCheckingGmaps(true);
    try {
      await onCheckGoogleMaps({
        query: gmapsQuery,
        website: gmapsWebsite,
        city: activeCity,
        lat: Number(lat),
        lng: Number(lng),
      });
      setGmapsQuery('');
      setGmapsWebsite('');
      onClose();
    } finally {
      setCheckingGmaps(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setFormError('');
    setSubmitting(true);
    try {
      let useLat = Number(lat);
      let useLng = Number(lng);
      // The position must come from the visitor (a click, typed coordinates) or from the address they typed.
      const addressChangedSinceLookup = coordsSource === 'lookup' && lookup.address !== address.trim();
      if (coordsSource === 'default' || addressChangedSinceLookup) {
        if (!address.trim()) {
          setFormError('Enter the street address, or click the map to place the venue.');
          return;
        }
        const found = await findAddress(address.trim());
        if (found.error) {
          setFormError(found.error);
          return;
        }
        useLat = found.lat;
        useLng = found.lng;
      }
      await onAddVenue({
        name,
        category,
        city: activeCity,
        address: address || `${useLat}, ${useLng}`,
        lat: useLat,
        lng: useLng,
        website,
        servingFormat,
        price,
        pintRating: Number(pintRating),
        note,
      });
      setName('');
      setAddress('');
      setWebsite('');
      setNote('');
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 580 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.85rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <PlusCircle size={20} color="#c8a45d" />
            <h3 className="font-serif-guinness" style={{ fontSize: '1.15rem' }}>
              Check Google Maps & Add Bars / Restaurants to Guinness Finder
            </h3>
          </div>
          <button
            onClick={onClose}
            className="modal-close"
            aria-label="Close"
            style={{ background: 'transparent', border: 'none', color: '#b8ab99', cursor: 'pointer' }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Google Maps Direct Checker & Importer */}
        <form
          onSubmit={handleGmapsCheckSubmit}
          style={{
            background: '#120f0c',
            border: '1px solid #473928',
            borderRadius: '0.65rem',
            padding: '0.85rem',
            marginBottom: '1rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.55rem',
          }}
        >
          <div style={{ fontSize: '0.82rem', fontWeight: 700, color: '#e2be75', display: 'flex', alignItems: 'center', gap: 6 }}>
            <Globe2 size={15} color="#c8a45d" />
            1. Check Google Maps Bars, Pubs, Restaurants & Hotels → Feed into Finder
          </div>
          <div style={{ fontSize: '0.74rem', color: '#b8ab99', lineHeight: 1.4 }}>
            Paste any Google Maps place link, bar/restaurant name, or multiple lines of venues (or leave blank to check all bars & restaurants in the current map area) and automatically scan their menus & reviews for Guinness.
          </div>
          <textarea
            className="stout-textarea"
            rows={2}
            placeholder="Paste Google Maps URL (https://www.google.com/maps/place/...), venue name, or search query (e.g. 'bars and restaurants in Zurich')..."
            value={gmapsQuery}
            onChange={(e) => setGmapsQuery(e.target.value)}
          />
          <div className="stack-row" style={{ display: 'flex', gap: '0.5rem' }}>
            <input
              type="text"
              className="stout-input"
              style={{ flex: 1 }}
              placeholder="Optional: Venue Website / Menu URL to crawl for Guinness"
              value={gmapsWebsite}
              onChange={(e) => setGmapsWebsite(e.target.value)}
            />
            <button type="submit" className="btn-gold" disabled={checkingGmaps}>
              <Search size={14} />
              {checkingGmaps ? 'Checking Google Maps...' : 'Check on Google Maps & Import'}
            </button>
          </div>
        </form>

        <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#d7cbb8', marginBottom: '0.55rem' }}>
          2. Or Add & Inspect a Specific Venue Directly
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.7rem' }}>
          <div className="stack-sm" style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '0.55rem' }}>
            <div>
              <label style={{ fontSize: '0.72rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
                Venue Name *
              </label>
              <input
                type="text"
                required
                className="stout-input"
                style={{ width: '100%' }}
                placeholder="e.g. Kennedy's Irish Pub / Baur au Lac"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>

            <div>
              <label style={{ fontSize: '0.72rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
                Category
              </label>
              <select
                className="stout-select"
                style={{ width: '100%' }}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="pub">🍺 Pub</option>
                <option value="bar">🍸 Bar</option>
                <option value="restaurant">🍽️ Restaurant</option>
                <option value="hotel">🏨 Hotel</option>
              </select>
            </div>
          </div>

          <div>
            <label style={{ fontSize: '0.72rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
              Street Address
            </label>
            <input
              type="text"
              className="stout-input"
              style={{ width: '100%' }}
              placeholder="Freischützgasse 14, 8004 Zürich, Switzerland"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
            />
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: 4, flexWrap: 'wrap' }}>
              <button
                type="button"
                className="btn-outline"
                style={{ padding: '0.3rem 0.6rem', fontSize: '0.72rem' }}
                disabled={address.trim().length < 4 || lookup.status === 'busy'}
                onClick={() => findAddress(address.trim())}
              >
                {lookup.status === 'busy' ? 'Looking…' : '📍 Find on map'}
              </button>
              {lookup.status === 'found' && (
                <span className="lookup-ok" role="status" style={{ fontSize: '0.72rem', color: '#6ee7b7' }}>
                  Found: {lookup.label}
                </span>
              )}
              {coordsSource === 'default' && address.trim().length < 4 && (
                <span style={{ fontSize: '0.72rem', color: '#9c8e7b' }}>or click the map to place it</span>
              )}
            </div>
            {formError && (
              <p className="near-error" role="alert" style={{ marginTop: 6 }}>
                {formError}
              </p>
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.55rem' }}>
            <div>
              <label style={{ fontSize: '0.72rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
                Latitude
              </label>
              <input
                type="number"
                step="any"
                className="stout-input"
                style={{ width: '100%' }}
                value={lat}
                onChange={(e) => {
                  setLat(e.target.value);
                  setCoordsSource('typed');
                }}
              />
            </div>
            <div>
              <label style={{ fontSize: '0.72rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
                Longitude
              </label>
              <input
                type="number"
                step="any"
                className="stout-input"
                style={{ width: '100%' }}
                value={lng}
                onChange={(e) => {
                  setLng(e.target.value);
                  setCoordsSource('typed');
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ fontSize: '0.72rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
              Website or Online Menu URL (Auto-scanned for Guinness)
            </label>
            <input
              type="text"
              className="stout-input"
              style={{ width: '100%' }}
              placeholder="https://example.ch/drinks-menu"
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
            />
          </div>

          <div className="stack-sm" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.55rem' }}>
            <div>
              <label style={{ fontSize: '0.72rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
                Guinness Status
              </label>
              <select
                className="stout-select"
                style={{ width: '100%' }}
                value={servingFormat}
                onChange={(e) => setServingFormat(e.target.value)}
              >
                <option value="draught">Draught On Tap</option>
                <option value="cans_bottles">Cans / Bottles</option>
                <option value="none">No Guinness</option>
              </select>
            </div>
            <div>
              <label style={{ fontSize: '0.72rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
                Pint Score
              </label>
              <select
                className="stout-select"
                style={{ width: '100%' }}
                value={pintRating}
                onChange={(e) => setPintRating(e.target.value)}
                disabled={servingFormat === 'none'}
              >
                <option value="5.0">5.0 ★</option>
                <option value="4.8">4.8 ★</option>
                <option value="4.5">4.5 ★</option>
                <option value="4.0">4.0 ★</option>
                <option value="3.5">3.5 ★</option>
              </select>
            </div>
            <div>
              <label style={{ fontSize: '0.72rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
                Pint Price
              </label>
              <input
                type="text"
                className="stout-input"
                style={{ width: '100%' }}
                placeholder="CHF 9.50"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </div>
          </div>

          <div>
            <label style={{ fontSize: '0.72rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
              Scout Notes / Review
            </label>
            <textarea
              className="stout-textarea"
              style={{ width: '100%' }}
              rows={2}
              placeholder="Creamy head, proper temperature, served in tulip glass..."
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>

          <div className="modal-actions" style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '0.35rem' }}>
            <button type="button" className="btn-outline" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-gold" disabled={submitting}>
              <Search size={14} /> {submitting ? 'Scanning & Saving...' : 'Add Venue & Check Menu'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

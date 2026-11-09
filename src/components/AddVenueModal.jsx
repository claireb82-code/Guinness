import React, { useState, useEffect } from 'react';
import { PlusCircle, X, Search, Globe2 } from 'lucide-react';

export function AddVenueModal({
  isOpen,
  onClose,
  initialCoords,
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

  useEffect(() => {
    if (initialCoords) {
      setLat(initialCoords.lat);
      setLng(initialCoords.lng);
    }
  }, [initialCoords?.lat, initialCoords?.lng]);

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
    setSubmitting(true);
    try {
      await onAddVenue({
        name,
        category,
        city: activeCity,
        address: address || `${lat}, ${lng}`,
        lat: Number(lat),
        lng: Number(lng),
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
                onChange={(e) => setLat(e.target.value)}
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
                onChange={(e) => setLng(e.target.value)}
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

import React, { useState, useEffect } from 'react';
import { PlusCircle, X, Search } from 'lucide-react';

export function AddVenueModal({ isOpen, onClose, initialCoords, activeCity, onAddVenue }) {
  const [name, setName] = useState('');
  const [category, setCategory] = useState('pub');
  const [address, setAddress] = useState('');
  const [lat, setLat] = useState(initialCoords?.lat || 53.3441);
  const [lng, setLng] = useState(initialCoords?.lng || -6.2675);
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
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.85rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <PlusCircle size={20} color="#c8a45d" />
            <h3 className="font-serif-guinness" style={{ fontSize: '1.15rem' }}>
              Add & Inspect Hotel, Bar, Pub or Restaurant
            </h3>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'transparent', border: 'none', color: '#b8ab99', cursor: 'pointer' }}
          >
            <X size={18} />
          </button>
        </div>

        <p style={{ fontSize: '0.78rem', color: '#b8ab99', marginBottom: '0.9rem', lineHeight: 1.45 }}>
          Add a venue to the map. If you include its website or online menu URL, Guinness Guide will automatically crawl and
          check the menu for Guinness!
        </p>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.7rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '0.55rem' }}>
            <div>
              <label style={{ fontSize: '0.72rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
                Venue Name *
              </label>
              <input
                type="text"
                required
                className="stout-input"
                style={{ width: '100%' }}
                placeholder="e.g. The Long Hall / The Merrion Hotel"
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
              placeholder="51 South Great George's St, Dublin 2"
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
              placeholder="https://example-pub.com/drinks-menu"
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.55rem' }}>
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
                placeholder="€6.20"
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

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '0.35rem' }}>
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

import React, { useState } from 'react';
import { KeyRound, X, Globe2, Sparkles, CheckCircle2 } from 'lucide-react';

export function ApiKeyModal({
  isOpen,
  onClose,
  googleApiKey,
  onSaveApiKey,
  mode,
  onChangeMode,
  autoScrapeMenus,
  onChangeAutoScrape,
  onTriggerLiveScan,
}) {
  const [keyInput, setKeyInput] = useState(googleApiKey || '');

  if (!isOpen) return null;

  const handleSave = (e) => {
    e.preventDefault();
    onSaveApiKey(keyInput.trim());
    if (keyInput.trim()) {
      onChangeMode('live');
    }
    onClose();
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.9rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem' }}>
            <KeyRound size={20} color="#c8a45d" />
            <h3 className="font-serif-guinness" style={{ fontSize: '1.18rem' }}>
              Google Maps & Places API Settings
            </h3>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#b8ab99',
              cursor: 'pointer',
            }}
          >
            <X size={18} />
          </button>
        </div>

        <p style={{ fontSize: '0.81rem', color: '#b8ab99', lineHeight: 1.5, marginBottom: '1rem' }}>
          Guinness Guide works immediately in <strong>Curated Demo Mode</strong> (with real live menu URL scraping &
          crowdsourcing), or connects directly to your <strong>Google Maps JavaScript API & Places API</strong> key to
          discover every hotel, bar, pub, and restaurant in any radius.
        </p>

        {/* Data Source Toggle */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: '0.6rem',
            marginBottom: '1rem',
          }}
        >
          <button
            type="button"
            onClick={() => onChangeMode('demo')}
            style={{
              padding: '0.75rem',
              borderRadius: '0.6rem',
              border: mode === 'demo' ? '1px solid #c8a45d' : '1px solid #332a21',
              background: mode === 'demo' ? 'rgba(200, 164, 93, 0.14)' : '#120f0c',
              color: '#f5efe6',
              textAlign: 'left',
              cursor: 'pointer',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontWeight: 700, fontSize: '0.82rem', color: '#e2be75' }}>Demo + Live Scraper</span>
              {mode === 'demo' && <CheckCircle2 size={15} color="#34d399" />}
            </div>
            <div style={{ fontSize: '0.72rem', color: '#b8ab99' }}>
              No API key needed. Explore Dublin, London, NYC & Chicago with live menu scanner.
            </div>
          </button>

          <button
            type="button"
            onClick={() => onChangeMode('live')}
            style={{
              padding: '0.75rem',
              borderRadius: '0.6rem',
              border: mode === 'live' ? '1px solid #c8a45d' : '1px solid #332a21',
              background: mode === 'live' ? 'rgba(200, 164, 93, 0.14)' : '#120f0c',
              color: '#f5efe6',
              textAlign: 'left',
              cursor: 'pointer',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontWeight: 700, fontSize: '0.82rem', color: '#e2be75' }}>Google Places Live</span>
              {mode === 'live' && <CheckCircle2 size={15} color="#34d399" />}
            </div>
            <div style={{ fontSize: '0.72rem', color: '#b8ab99' }}>
              Queries Google Places API for nearby hotels, pubs, bars & restaurants + review analysis.
            </div>
          </button>
        </div>

        <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          <div>
            <label style={{ fontSize: '0.76rem', color: '#d7cbb8', display: 'block', marginBottom: '0.35rem' }}>
              Google Maps Platform API Key (Maps JS + Places API)
            </label>
            <input
              type="password"
              className="stout-input"
              style={{ width: '100%' }}
              placeholder="AIzaSy..."
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
            />
            <span style={{ fontSize: '0.69rem', color: '#8f7e68', display: 'block', marginTop: '0.25rem' }}>
              You can also set <code>GOOGLE_MAPS_API_KEY=...</code> in a <code>.env</code> file in the project root.
            </span>
          </div>

          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              fontSize: '0.78rem',
              color: '#d7cbb8',
              cursor: 'pointer',
            }}
          >
            <input
              type="checkbox"
              checked={autoScrapeMenus}
              onChange={(e) => onChangeAutoScrape(e.target.checked)}
            />
            Automatically crawl & scan venue websites for Guinness menus during Google Places searches
          </label>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.55rem', marginTop: '0.3rem' }}>
            {keyInput.trim() && (
              <button
                type="button"
                className="btn-outline"
                onClick={() => {
                  onSaveApiKey(keyInput.trim());
                  onChangeMode('live');
                  onTriggerLiveScan(keyInput.trim());
                  onClose();
                }}
              >
                <Globe2 size={14} /> Save & Scan Current Map Area
              </button>
            )}
            <button type="submit" className="btn-gold">
              <Sparkles size={14} /> Save Configuration
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

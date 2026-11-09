import React, { useState, useEffect } from 'react';
import {
  X,
  Globe,
  MapPin,
  Star,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RefreshCw,
  MessageSquare,
  Users,
  FileSearch,
  ExternalLink,
  Sparkles,
} from 'lucide-react';
import { PintIcon, formatCategoryLabel } from './PintIcon.jsx';
import { safeHttpUrl } from '../safeUrl.js';
import { formatDistance } from '../geo.js';

function highlightGuinnessText(text) {
  if (!text) return null;
  const parts = text.split(/(guinness(?:\s*0\.?0|\s*draught|\s*foreign\s*extra|\s*extra\s*cold|\s*surger)?)/gi);
  return parts.map((part, idx) =>
    /^guinness/i.test(part) ? (
      <mark
        key={idx}
        style={{
          background: 'rgba(200, 164, 93, 0.28)',
          color: '#f7e2b0',
          padding: '0 3px',
          borderRadius: 3,
          fontWeight: 600,
        }}
      >
        {part}
      </mark>
    ) : (
      part
    )
  );
}

export function VenueDetailPanel({ venue, distanceKm = null, onClose, onScanMenu, onSubmitCrowdReport }) {
  const [scanning, setScanning] = useState(false);
  const [customMenuUrl, setCustomMenuUrl] = useState(venue?.menuUrl || venue?.website || '');
  const [showReportForm, setShowReportForm] = useState(false);

  // Crowdsource Form State
  const [userName, setUserName] = useState('');
  const [servingFormat, setServingFormat] = useState('draught');
  const [pintRating, setPintRating] = useState('4.8');
  const [price, setPrice] = useState('');
  const [hasZero, setHasZero] = useState(false);
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setCustomMenuUrl(venue?.menuUrl || venue?.website || '');
    setPrice(venue?.crowdCheck?.reportedPrice || venue?.menuCheck?.extractedPrice || '');
    setHasZero(Boolean(venue?.crowdCheck?.hasZero));
  }, [venue?.id]);

  if (!venue) return null;

  const summary = venue.guinnessSummary || {};
  const menuCheck = venue.menuCheck || {};
  const reviewCheck = venue.reviewCheck || {};
  const crowdCheck = venue.crowdCheck || {};

  const handleRunMenuScan = async (e) => {
    e.preventDefault();
    setScanning(true);
    try {
      await onScanMenu(venue.id, customMenuUrl);
    } finally {
      setScanning(false);
    }
  };

  const handleCrowdSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onSubmitCrowdReport({
        venueId: venue.id,
        user: userName || 'Guinness Scout',
        servingFormat,
        pintRating: servingFormat === 'none' ? null : Number(pintRating),
        price,
        hasZero,
        note,
      });
      setNote('');
      setShowReportForm(false);
    } finally {
      setSubmitting(false);
    }
  };

  const googleMapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
    `${venue.name} ${venue.address}`
  )}`;

  return (
    <aside className="detail-drawer">
      {/* Sticky Drawer Header */}
      <div
        style={{
          padding: '1rem 1.15rem',
          borderBottom: '1px solid #332a21',
          background: '#14110e',
          position: 'sticky',
          top: 0,
          zIndex: 5,
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: '0.75rem',
        }}
      >
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
          <PintIcon size={38} status={summary.status} />
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: '0.25rem' }}>
              <span
                style={{
                  fontSize: '0.68rem',
                  textTransform: 'uppercase',
                  letterSpacing: '0.09em',
                  padding: '0.12rem 0.48rem',
                  borderRadius: 4,
                  background: '#272019',
                  color: '#c8a45d',
                  fontWeight: 700,
                }}
              >
                {formatCategoryLabel(venue.category)}
              </span>
              {venue.googleRating && (
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.2rem',
                    fontSize: '0.75rem',
                    color: '#e2be75',
                    fontWeight: 600,
                  }}
                >
                  <Star size={12} fill="#e2be75" /> {venue.googleRating} ({venue.googleReviewCount})
                </span>
              )}
              {Number.isFinite(distanceKm) && (
                <span className="distance-badge" title="Distance from you">
                  📍 {formatDistance(distanceKm)} from you
                </span>
              )}
            </div>
            <h2 className="font-serif-guinness" style={{ fontSize: '1.18rem', lineHeight: 1.25 }}>
              {venue.name}
            </h2>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.3rem',
                fontSize: '0.76rem',
                color: '#b8ab99',
                marginTop: '0.25rem',
              }}
            >
              <MapPin size={12} style={{ flexShrink: 0, color: '#c8a45d' }} />
              <span>{venue.address}</span>
            </div>
          </div>
        </div>

        <button
          onClick={onClose}
          className="drawer-close"
          aria-label="Close details"
          style={{
            background: '#241e18',
            border: '1px solid #382e24',
            color: '#f5efe6',
            borderRadius: '0.4rem',
            padding: '0.35rem',
            cursor: 'pointer',
          }}
          title="Close details"
        >
          <X size={16} />
        </button>
      </div>

      {/* Main Content */}
      <div style={{ padding: '1rem 1.15rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {/* Overall Verification Summary Card */}
        <div
          style={{
            background: 'linear-gradient(145deg, #241d16 0%, #18130f 100%)',
            border: '1px solid #473928',
            borderRadius: '0.75rem',
            padding: '0.95rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.6rem' }}>
            <span className={`status-badge status-${summary.status}`}>
              {summary.status === 'confirmed_draught' || summary.status === 'cans_or_bottles' ? (
                <CheckCircle2 size={13} />
              ) : summary.status === 'no_guinness' ? (
                <XCircle size={13} />
              ) : (
                <AlertTriangle size={13} />
              )}
              {summary.statusLabel}
            </span>
            <span style={{ fontSize: '0.76rem', color: '#c8a45d', fontWeight: 700 }}>
              {summary.confidence}% Match Confidence
            </span>
          </div>

          {venue.tagCheck?.text && (
            <p className="evidence-note" style={{ fontSize: '0.74rem', color: '#9c8e7b', lineHeight: 1.4, marginBottom: '0.6rem' }}>
              {venue.tagCheck.text}
            </p>
          )}

          {venue.editorialSummary && (
            <p style={{ fontSize: '0.8rem', color: '#d7cbb8', lineHeight: 1.45, marginBottom: '0.75rem' }}>
              {highlightGuinnessText(venue.editorialSummary)}
            </p>
          )}

          {/* Quick Pint Metrics Grid */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '0.5rem',
              borderTop: '1px solid #332a21',
              paddingTop: '0.7rem',
            }}
          >
            <div>
              <div style={{ fontSize: '0.66rem', color: '#9c8e7b', textTransform: 'uppercase' }}>Pint Score</div>
              <div style={{ fontSize: '0.95rem', fontWeight: 700, color: '#f5efe6', marginTop: '0.1rem' }}>
                {crowdCheck.avgPintRating ? `${crowdCheck.avgPintRating} / 5.0 🍺` : 'Unrated'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '0.66rem', color: '#9c8e7b', textTransform: 'uppercase' }}>Pint Price</div>
              <div style={{ fontSize: '0.95rem', fontWeight: 700, color: '#e2be75', marginTop: '0.1rem' }}>
                {crowdCheck.reportedPrice || menuCheck.extractedPrice || venue.priceLevel || '—'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '0.66rem', color: '#9c8e7b', textTransform: 'uppercase' }}>Guinness 0.0</div>
              <div style={{ fontSize: '0.88rem', fontWeight: 600, color: '#f5efe6', marginTop: '0.1rem' }}>
                {crowdCheck.hasZero ||
                menuCheck.typesFound?.some((t) => /0\.0|zero/i.test(t))
                  ? 'Available ✓'
                  : 'Unconfirmed'}
              </div>
            </div>
          </div>

          {/* External Links */}
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
            <a
              href={googleMapsUrl}
              target="_blank"
              rel="noreferrer"
              className="btn-outline"
              style={{ textDecoration: 'none', flex: 1, justifyContent: 'center', fontSize: '0.75rem' }}
            >
              <ExternalLink size={13} /> Open in Google Maps
            </a>
            {safeHttpUrl(venue.website) && (
              <a
                href={safeHttpUrl(venue.website)}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-outline"
                style={{ textDecoration: 'none', flex: 1, justifyContent: 'center', fontSize: '0.75rem' }}
              >
                <Globe size={13} /> Venue Website
              </a>
            )}
          </div>
          {venue.websiteSource === 'overture' && safeHttpUrl(venue.website) && (
            <div style={{ fontSize: '0.68rem', color: '#9c8e7b', marginTop: '0.4rem' }}>
              Website listed by{' '}
              <a href="https://overturemaps.org" target="_blank" rel="noopener noreferrer" style={{ color: '#c8a45d' }}>
                Overture Maps
              </a>{' '}
              (CDLA-Permissive-2.0).
            </div>
          )}
        </div>

        {/* PILLAR 1: WEBSITE & ONLINE MENU SCANNER */}
        <div
          style={{
            background: '#1b1612',
            border: '1px solid #332a21',
            borderRadius: '0.75rem',
            padding: '0.95rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontWeight: 700, fontSize: '0.86rem' }}>
              <FileSearch size={16} color="#c8a45d" />
              <span>1. Online Menu & Website Check</span>
            </div>
            <span
              style={{
                fontSize: '0.7rem',
                padding: '0.15rem 0.5rem',
                borderRadius: 99,
                background: menuCheck.foundOnMenu ? 'rgba(52,211,153,0.15)' : 'rgba(184,171,153,0.12)',
                color: menuCheck.foundOnMenu ? '#6ee7b7' : '#b8ab99',
                fontWeight: 600,
              }}
            >
              {menuCheck.foundOnMenu
                ? 'Found on Menu'
                : menuCheck.checked
                ? 'Not on HTML Menu'
                : 'Not Scanned Yet'}
            </span>
          </div>

          {menuCheck.typesFound?.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem', marginBottom: '0.6rem' }}>
              {menuCheck.typesFound.map((type, idx) => (
                <span
                  key={idx}
                  style={{
                    fontSize: '0.71rem',
                    background: 'rgba(200, 164, 93, 0.16)',
                    border: '1px solid rgba(200, 164, 93, 0.35)',
                    color: '#f3d999',
                    padding: '0.18rem 0.5rem',
                    borderRadius: '0.35rem',
                    fontWeight: 600,
                  }}
                >
                  🍺 {type}
                </span>
              ))}
            </div>
          )}

          {menuCheck.snippets?.length > 0 && (
            <div
              style={{
                background: '#120f0c',
                border: '1px solid #2b231b',
                borderRadius: '0.5rem',
                padding: '0.6rem 0.7rem',
                fontSize: '0.76rem',
                color: '#d7cbb8',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.35rem',
                marginBottom: '0.65rem',
              }}
            >
              {menuCheck.snippets.map((line, i) => (
                <div key={i} style={{ lineHeight: 1.4 }}>
                  “{highlightGuinnessText(line)}”
                </div>
              ))}
            </div>
          )}

          <form onSubmit={handleRunMenuScan} style={{ display: 'flex', gap: '0.4rem', marginTop: '0.35rem' }}>
            <input
              type="text"
              className="stout-input"
              style={{ flex: 1, fontSize: '0.76rem', padding: '0.4rem 0.65rem' }}
              placeholder="Menu or website URL to scan..."
              value={customMenuUrl}
              onChange={(e) => setCustomMenuUrl(e.target.value)}
            />
            <button type="submit" className="btn-gold" disabled={scanning} style={{ fontSize: '0.75rem' }}>
              <RefreshCw size={13} className={scanning ? 'spin' : ''} />
              {scanning ? 'Scanning...' : 'Scan Menu'}
            </button>
          </form>
        </div>

        {/* PILLAR 2: GOOGLE PLACES REVIEWS & EDITORIAL ANALYSIS */}
        <div
          style={{
            background: '#1b1612',
            border: '1px solid #332a21',
            borderRadius: '0.75rem',
            padding: '0.95rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.55rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontWeight: 700, fontSize: '0.86rem' }}>
              <MessageSquare size={16} color="#c8a45d" />
              <span>2. Google Reviews Mention Check</span>
            </div>
            <span
              style={{
                fontSize: '0.72rem',
                color: reviewCheck.mentionCount > 0 ? '#e2be75' : '#9c8e7b',
                fontWeight: 600,
              }}
            >
              {reviewCheck.mentionCount || 0} Mentions
            </span>
          </div>

          {reviewCheck.excerpts?.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {reviewCheck.excerpts.map((ex, i) => (
                <div
                  key={i}
                  style={{
                    background: '#120f0c',
                    border: '1px solid #2b231b',
                    borderRadius: '0.5rem',
                    padding: '0.6rem 0.7rem',
                    fontSize: '0.76rem',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      color: '#b8ab99',
                      fontSize: '0.7rem',
                      marginBottom: '0.25rem',
                    }}
                  >
                    <span style={{ fontWeight: 600, color: '#f5efe6' }}>{ex.author}</span>
                    <span>
                      {'★'.repeat(ex.rating || 5)} · {ex.date}
                    </span>
                  </div>
                  <p style={{ color: '#d7cbb8', lineHeight: 1.4 }}>{highlightGuinnessText(ex.text)}</p>
                </div>
              ))}
            </div>
          ) : (
            <p style={{ fontSize: '0.76rem', color: '#9c8e7b' }}>
              No explicit "Guinness" mentions detected in the sampled Google Places reviews yet.
            </p>
          )}
        </div>

        {/* PILLAR 3: CROWDSOURCED PINT QUALITY & AVAILABILITY */}
        <div
          style={{
            background: '#1b1612',
            border: '1px solid #332a21',
            borderRadius: '0.75rem',
            padding: '0.95rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.6rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontWeight: 700, fontSize: '0.86rem' }}>
              <Users size={16} color="#c8a45d" />
              <span>3. Community Pint Reports</span>
            </div>
            <button
              type="button"
              className="btn-gold"
              style={{ padding: '0.3rem 0.65rem', fontSize: '0.73rem' }}
              onClick={() => setShowReportForm(!showReportForm)}
            >
              <Sparkles size={12} /> {showReportForm ? 'Cancel' : '+ Log Pint / Confirm'}
            </button>
          </div>

          <div style={{ fontSize: '0.75rem', color: '#b8ab99', marginBottom: '0.6rem' }}>
            Confirmed by <strong style={{ color: '#6ee7b7' }}>{crowdCheck.confirmedCount || 0}</strong> scouts ·{' '}
            Denied by <strong style={{ color: '#fca5a5' }}>{crowdCheck.deniedCount || 0}</strong>
          </div>

          {showReportForm && (
            <form
              onSubmit={handleCrowdSubmit}
              style={{
                background: '#120f0c',
                border: '1px solid #c8a45d',
                borderRadius: '0.6rem',
                padding: '0.8rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.6rem',
                marginBottom: '0.75rem',
              }}
            >
              <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#e2be75' }}>
                Submit Your Guinness Inspection
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
                <div>
                  <label style={{ fontSize: '0.7rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
                    Serving Format
                  </label>
                  <select
                    className="stout-select"
                    style={{ width: '100%' }}
                    value={servingFormat}
                    onChange={(e) => setServingFormat(e.target.value)}
                  >
                    <option value="draught">🍺 On Draught (Tap)</option>
                    <option value="cans_bottles">🥫 Cans / Bottles Only</option>
                    <option value="none">❌ No Guinness Served</option>
                  </select>
                </div>

                {servingFormat !== 'none' && (
                  <div>
                    <label style={{ fontSize: '0.7rem', color: '#b8ab99', display: 'block', marginBottom: 3 }}>
                      Pint Quality (1-5)
                    </label>
                    <select
                      className="stout-select"
                      style={{ width: '100%' }}
                      value={pintRating}
                      onChange={(e) => setPintRating(e.target.value)}
                    >
                      <option value="5.0">5.0 — Creamiest Dream Pint</option>
                      <option value="4.8">4.8 — Exceptional Pour</option>
                      <option value="4.5">4.5 — Very Solid Pint</option>
                      <option value="4.0">4.0 — Good Standard Pour</option>
                      <option value="3.5">3.5 — Average / Acceptable</option>
                      <option value="2.5">2.5 — Poor Pour / Warm</option>
                    </select>
                  </div>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
                <input
                  type="text"
                  className="stout-input"
                  placeholder="Your Name (optional)"
                  value={userName}
                  onChange={(e) => setUserName(e.target.value)}
                />
                <input
                  type="text"
                  className="stout-input"
                  placeholder="Pint Price (e.g. €6.30)"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                />
              </div>

              <label
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.45rem',
                  fontSize: '0.76rem',
                  color: '#d7cbb8',
                  cursor: 'pointer',
                }}
              >
                <input
                  type="checkbox"
                  checked={hasZero}
                  onChange={(e) => setHasZero(e.target.checked)}
                />
                Also serves Guinness 0.0 (Non-Alcoholic)
              </label>

              <textarea
                className="stout-textarea"
                rows={2}
                placeholder="Notes on pour, dome, glass type, temperature..."
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />

              <button type="submit" className="btn-gold" disabled={submitting} style={{ justifyContent: 'center' }}>
                {submitting ? 'Saving Report...' : 'Save Guinness Report'}
              </button>
            </form>
          )}

          {crowdCheck.recentReports?.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
              {crowdCheck.recentReports.map((rep) => (
                <div
                  key={rep.id}
                  style={{
                    background: '#120f0c',
                    border: '1px solid #2b231b',
                    borderRadius: '0.5rem',
                    padding: '0.55rem 0.7rem',
                    fontSize: '0.75rem',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.2rem' }}>
                    <span style={{ fontWeight: 600, color: '#f5efe6' }}>{rep.user}</span>
                    <span style={{ color: '#c8a45d', fontWeight: 600 }}>
                      {rep.servingFormat === 'none'
                        ? '❌ No Guinness'
                        : `${rep.pintRating ? `${rep.pintRating} ★` : ''} ${
                            rep.price ? `· ${rep.price}` : ''
                          }`}
                    </span>
                  </div>
                  {rep.note && <p style={{ color: '#d7cbb8', lineHeight: 1.35 }}>{rep.note}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

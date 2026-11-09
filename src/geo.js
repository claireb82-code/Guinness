// Distance helpers for the "Near me" filter. Pure functions (no browser APIs), unit-tested in tests/js/geo.test.js.

export const RADII_KM = [0.5, 1, 5, 10, 25];
// Where Near me starts (and what the map first frames): 500 m around the visitor. The automatic default widens
// from here until it finds a venue, so it never starts on an empty list.
export const DEFAULT_RADIUS_KM = 0.5;

const EARTH_RADIUS_KM = 6371.0088;
const toRad = (deg) => (deg * Math.PI) / 180;
const isCoord = (p) => p != null && Number.isFinite(p.lat) && Number.isFinite(p.lng);

/** Great-circle (haversine) distance in km between two {lat, lng} points; NaN if either is missing/invalid. */
export function distanceKm(a, b) {
  if (!isCoord(a) || !isCoord(b)) return NaN;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** "500 m", "1 km", "25 km" - labels for the radius pills. */
export function formatRadius(km) {
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km} km`;
}

/** "450 m", "1.2 km", "12 km", "312 km" - short enough for a badge. */
export function formatDistance(km) {
  if (!Number.isFinite(km) || km < 0) return '';
  if (km < 1) return `${Math.max(10, Math.round((km * 1000) / 10) * 10)} m`;
  if (km < 10) return `${km.toFixed(1)} km`;
  return `${Math.round(km)} km`;
}

/**
 * Venues within ``radiusKm`` of ``origin`` (inclusive), nearest first. Venues without coordinates are
 * left out. Returns new objects with a ``distanceKm`` field; the input is not modified.
 */
export function nearby(venues, origin, radiusKm) {
  if (!isCoord(origin)) return [];
  return venues
    .map((v) => ({ ...v, distanceKm: distanceKm(origin, v) }))
    .filter((v) => Number.isFinite(v.distanceKm) && v.distanceKm <= radiusKm)
    .sort((a, b) => a.distanceKm - b.distanceKm || String(a.name).localeCompare(String(b.name)));
}

/** The closest venue to ``origin`` (with ``distanceKm``), or null. */
export function nearest(venues, origin) {
  if (!isCoord(origin)) return null;
  let best = null;
  for (const v of venues) {
    const d = distanceKm(origin, v);
    if (Number.isFinite(d) && (best === null || d < best.distanceKm)) best = { ...v, distanceKm: d };
  }
  return best;
}

/**
 * The smallest radius (>= ``minKm``) that has at least one venue in range, or null if none does.
 * Used for the automatic Near me default: never start on an empty list.
 */
export function pickRadius(venues, origin, minKm = DEFAULT_RADIUS_KM, radii = RADII_KM) {
  if (!isCoord(origin)) return null;
  for (const r of [...radii].sort((a, b) => a - b)) {
    if (r < minKm) continue;
    if (venues.some((v) => distanceKm(origin, v) <= r)) return r;
  }
  return null;
}

/** A friendly message for a geolocation failure (the browser's GeolocationPositionError codes). */
export function locationErrorMessage(error) {
  if (!error || error.message === 'unsupported') {
    return 'Your browser cannot share its location (this needs a secure https:// page).';
  }
  if (error.code === 1) return 'Location permission was denied. Allow location access in your browser settings to use Near me.';
  if (error.code === 3) return 'Finding your location took too long. Please try again.';
  return 'Could not work out where you are. Please try again.';
}

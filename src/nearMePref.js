// What the visitor last chose for "Near me": "on" with a preferred radius, or "off". Only this preference is
// remembered (in localStorage), never the location itself. The storage is passed in so it can be unit-tested,
// and every access is guarded: localStorage throws in some private-browsing modes and when site data is blocked.
import { RADII_KM } from './geo.js';

export const NEAR_ME_PREF_KEY = 'guinness.nearMe';

/** @returns {{mode?: 'on'|'off', km?: number}} only well-formed values; {} if nothing usable is stored */
export function readNearMePref(storage) {
  try {
    const raw = JSON.parse(storage.getItem(NEAR_ME_PREF_KEY));
    if (!raw || typeof raw !== 'object') return {};
    const pref = {};
    if (raw.mode === 'on' || raw.mode === 'off') pref.mode = raw.mode;
    if (RADII_KM.includes(raw.km)) pref.km = raw.km;
    return pref;
  } catch {
    return {};
  }
}

export function writeNearMePref(storage, pref) {
  try {
    storage.setItem(NEAR_ME_PREF_KEY, JSON.stringify(pref));
    return true;
  } catch {
    return false;
  }
}

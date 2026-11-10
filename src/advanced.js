// Owner-only controls (scanning every menu at once, the Google key / data-mode dialog) are hidden from visitors. Open the
// app once with ?advanced=1 to show them in this browser (it is remembered), and with ?advanced=0 to hide them again.
export const ADVANCED_KEY = 'guinness.advanced';

export function isAdvanced(win = typeof window === 'undefined' ? null : window) {
  if (!win) return false;
  let flag = null;
  try {
    flag = new URLSearchParams(win.location.search).get('advanced');
  } catch {
    /* no usable location: treat as a normal visit */
  }
  try {
    if (flag === '1') win.localStorage.setItem(ADVANCED_KEY, '1');
    if (flag === '0') win.localStorage.removeItem(ADVANCED_KEY);
    if (flag === '1') return true;
    if (flag === '0') return false;
    return win.localStorage.getItem(ADVANCED_KEY) === '1';
  } catch {
    return flag === '1'; // storage blocked: honour the link for this page view only
  }
}

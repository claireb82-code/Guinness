// The "Know a place that serves Guinness? Tell us" prompt above the venue list can be dismissed; only that choice is remembered
// (in localStorage). The storage is passed in so it can be unit-tested, and every access is guarded: localStorage throws in some
// private-browsing modes and when site data is blocked.
export const ADD_PROMPT_KEY = 'guinness.hideAddPrompt';

export function readPromptHidden(storage) {
  try {
    return storage.getItem(ADD_PROMPT_KEY) === '1';
  } catch {
    return false;
  }
}

export function writePromptHidden(storage, hidden) {
  try {
    if (hidden) storage.setItem(ADD_PROMPT_KEY, '1');
    else storage.removeItem(ADD_PROMPT_KEY);
    return true;
  } catch {
    return false;
  }
}

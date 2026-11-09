// The phone breakpoint. Must match the media query in styles.css (tests/js/mobileLayout.test.js checks that).
// On a phone the app shows one pane at a time, with a bottom bar to switch between them.
export const PHONE_QUERY = '(max-width: 768px), (max-height: 500px) and (orientation: landscape)';

export const isPhoneLayout = () => typeof window !== 'undefined' && window.matchMedia(PHONE_QUERY).matches;

/** Map marker size in px. Phones get larger markers: with the map as the first view they are the main thing to tap. */
export const markerSize = (isSelected) => (isSelected ? 44 : 36) + (isPhoneLayout() ? 8 : 0);

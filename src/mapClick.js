// A single click on the map offers to add a venue there, but a double-click must zoom the map instead. A double-click
// delivers two "click" events before its "dblclick", and the first would open the add-venue form over the map, so a
// click is only acted on after DOUBLE_CLICK_MS without a second click, double-click or map movement.
export const DOUBLE_CLICK_MS = 300;

/**
 * @param {(coords: {lat: number, lng: number}) => void} onSingleClick
 * @param {{delay?: number, setTimer?: Function, clearTimer?: Function}} [options] timers are injectable for tests
 */
export function createSingleClickHandler(onSingleClick, { delay = DOUBLE_CLICK_MS, setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  let pending = null;
  const cancel = () => {
    if (pending !== null) clearTimer(pending);
    pending = null;
  };
  return {
    /** Call from the map's click event. A second click before the delay cancels the first (it is a double-click). */
    click(coords) {
      const wasPending = pending !== null;
      cancel();
      if (wasPending) return;
      pending = setTimer(() => {
        pending = null;
        onSingleClick(coords);
      }, delay);
    },
    /** Call from dblclick, zoomstart and movestart. */
    cancel,
  };
}

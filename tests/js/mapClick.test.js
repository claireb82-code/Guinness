import test from 'node:test';
import assert from 'node:assert/strict';
import { createSingleClickHandler, DOUBLE_CLICK_MS } from '../../src/mapClick.js';

// A fake clock: timers run only when the test advances time.
function fakeClock() {
  let now = 0;
  let nextId = 1;
  const timers = new Map();
  return {
    setTimer: (fn, ms) => { const id = nextId++; timers.set(id, { fn, at: now + ms }); return id; },
    clearTimer: (id) => timers.delete(id),
    advance(ms) {
      now += ms;
      for (const [id, t] of [...timers]) if (t.at <= now) { timers.delete(id); t.fn(); }
    },
  };
}
const setup = () => {
  const clock = fakeClock();
  const seen = [];
  return { clock, seen, handler: createSingleClickHandler((c) => seen.push(c), { setTimer: clock.setTimer, clearTimer: clock.clearTimer }) };
};

test('a lone click is acted on after the double-click delay, not before', () => {
  const { clock, seen, handler } = setup();
  handler.click({ lat: 1, lng: 2 });
  clock.advance(DOUBLE_CLICK_MS - 1);
  assert.deepEqual(seen, []);
  clock.advance(1);
  assert.deepEqual(seen, [{ lat: 1, lng: 2 }]);
});

test('regression: the two clicks of a double-click do not open the add-venue form', () => {
  const { clock, seen, handler } = setup();
  handler.click({ lat: 1, lng: 2 });
  clock.advance(100);
  handler.click({ lat: 1, lng: 2 });
  handler.cancel(); // dblclick
  clock.advance(1000);
  assert.deepEqual(seen, []);
});

test('even without a dblclick event, a second click inside the delay cancels the first', () => {
  const { clock, seen, handler } = setup();
  handler.click({ lat: 1, lng: 2 });
  clock.advance(100);
  handler.click({ lat: 1, lng: 2 });
  clock.advance(1000);
  assert.deepEqual(seen, []);
});

test('moving or zooming the map cancels a pending click', () => {
  const { clock, seen, handler } = setup();
  handler.click({ lat: 1, lng: 2 });
  handler.cancel();
  clock.advance(1000);
  assert.deepEqual(seen, []);
});

test('two separate clicks, well apart, each count', () => {
  const { clock, seen, handler } = setup();
  handler.click({ lat: 1, lng: 2 });
  clock.advance(1000);
  handler.click({ lat: 3, lng: 4 });
  clock.advance(1000);
  assert.deepEqual(seen, [{ lat: 1, lng: 2 }, { lat: 3, lng: 4 }]);
});

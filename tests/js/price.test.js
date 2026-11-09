import test from 'node:test';
import assert from 'node:assert/strict';
import { priceDisplay } from '../../src/price.js';

test('a visitor-reported price beats a scanned one, and both count as checked', () => {
  assert.deepEqual(priceDisplay({ crowdCheck: { reportedPrice: 'CHF 9.50' }, menuCheck: { extractedPrice: 'CHF 8.00' } }), { text: 'CHF 9.50', checked: true });
  assert.deepEqual(priceDisplay({ crowdCheck: {}, menuCheck: { extractedPrice: 'CHF 8.00' } }), { text: 'CHF 8.00', checked: true });
});

test('regression: a starter-list price is still shown, but marked unchecked', () => {
  assert.deepEqual(priceDisplay({ priceHint: { price: 'CHF 9.80' }, crowdCheck: {}, menuCheck: {} }), { text: 'CHF 9.80', checked: false });
});

test('a checked price wins over a starter-list one', () => {
  assert.deepEqual(priceDisplay({ priceHint: { price: 'CHF 9.80' }, menuCheck: { extractedPrice: 'CHF 10.00' } }), { text: 'CHF 10.00', checked: true });
});

test('no price at all, and junk input, give no text', () => {
  assert.deepEqual(priceDisplay({}), { text: null, checked: false });
  assert.deepEqual(priceDisplay(null), { text: null, checked: false });
  assert.deepEqual(priceDisplay({ priceHint: {} }), { text: null, checked: false });
});

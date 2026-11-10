import test from 'node:test';
import assert from 'node:assert/strict';
import { readPromptHidden, writePromptHidden, ADD_PROMPT_KEY } from '../../src/addPrompt.js';

const fakeStorage = (initial = {}) => {
  const data = { ...initial };
  return { data, getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); }, removeItem: (k) => { delete data[k]; } };
};

test('the prompt shows by default and stays hidden once dismissed', () => {
  const s = fakeStorage();
  assert.equal(readPromptHidden(s), false);
  assert.equal(writePromptHidden(s, true), true);
  assert.equal(readPromptHidden(s), true);
  assert.equal(writePromptHidden(s, false), true);
  assert.equal(readPromptHidden(s), false);
});

test('only the exact stored value hides it', () => {
  for (const junk of ['0', 'true', 'yes', '']) assert.equal(readPromptHidden(fakeStorage({ [ADD_PROMPT_KEY]: junk })), false, junk);
});

test('blocked or missing storage never throws and just shows the prompt', () => {
  const blocked = { getItem() { throw new Error('SecurityError'); }, setItem() { throw new Error('QuotaExceededError'); }, removeItem() { throw new Error('x'); } };
  assert.equal(readPromptHidden(blocked), false);
  assert.equal(writePromptHidden(blocked, true), false);
  assert.equal(readPromptHidden(undefined), false);
});

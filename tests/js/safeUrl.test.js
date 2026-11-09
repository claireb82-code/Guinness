import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { safeHttpUrl } from '../../src/safeUrl.js';

const CASES = [
  ['https://pub.ch/menu', 'https://pub.ch/menu'],
  ['http://pub.ch', 'http://pub.ch/'],
  ['pub.ch/drinks', 'https://pub.ch/drinks'],
  ['  https://pub.ch  ', 'https://pub.ch/'],
  ['javascript:alert(1)', ''],
  ['JaVaScRiPt:alert(document.cookie)', ''],
  ['data:text/html,<script>alert(1)</script>', ''],
  ['vbscript:x', ''],
  ['file:///etc/passwd', ''],
  ['ftp://pub.ch', ''],
  ['', ''],
  [null, ''],
  [undefined, ''],
  [42, ''],
];

test('src/safeUrl.js only ever returns http(s) URLs', () => {
  for (const [input, expected] of CASES) assert.equal(safeHttpUrl(input), expected, String(input));
});

function standaloneHelper() {
  const html = fs.readFileSync(new URL('../../public/standalone.html', import.meta.url), 'utf8');
  const m = html.match(/\/\/ <safeHttpUrl>([\s\S]*?)\/\/ <\/safeHttpUrl>/);
  assert.ok(m, 'standalone.html must contain the // <safeHttpUrl> ... // </safeHttpUrl> block');
  const sandbox = { URL };
  vm.runInNewContext(`${m[1]}; this.safeHttpUrl = safeHttpUrl;`, sandbox);
  return sandbox.safeHttpUrl;
}

test('public/standalone.html has the same helper behaviour as src/safeUrl.js', () => {
  const standalone = standaloneHelper();
  for (const [input] of CASES) assert.equal(standalone(input), safeHttpUrl(input), String(input));
});

test('no user-supplied website reaches an href without going through safeHttpUrl', () => {
  const html = fs.readFileSync(new URL('../../public/standalone.html', import.meta.url), 'utf8');
  // Every href that interpolates a venue field in the standalone page must wrap it in safeHttpUrl().
  for (const m of html.matchAll(/href="\$\{([\s\S]*?)\}"/g)) {
    if (/website|menuUrl|googleMapsUri/.test(m[1])) assert.match(m[1], /safeHttpUrl/, `unsafe href: ${m[0]}`);
  }
  const jsx = fs.readFileSync(new URL('../../src/components/VenueDetailPanel.jsx', import.meta.url), 'utf8');
  for (const m of jsx.matchAll(/href=\{([^}]*)\}/g)) {
    if (/website|menuUrl|googleMapsUri/.test(m[1])) assert.match(m[1], /safeHttpUrl/, `unsafe href: ${m[0]}`);
  }
  assert.match(html, /showApiError\(res, data\)/, 'write handlers must surface API errors');
});

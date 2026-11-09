import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import net from 'node:net';

const freePort = () => new Promise((resolve) => { const s = net.createServer().listen(0, () => { const { port } = s.address(); s.close(() => resolve(port)); }); });

test('the Node dev server never returns the server-side Places key from /api/config', async (t) => {
  const port = await freePort();
  const child = spawn(process.execPath, ['server/index.js'], {
    env: { ...process.env, NODE_ENV: 'production', PORT: String(port), GOOGLE_PLACES_API_KEY: 'SERVER_SECRET_KEY', GOOGLE_MAPS_BROWSER_KEY: 'BROWSER_KEY', GOOGLE_MAPS_API_KEY: '' },
    stdio: 'ignore',
  });
  t.after(() => child.kill());
  let body;
  for (let i = 0; i < 50 && !body; i++) {
    try {
      body = await (await fetch(`http://127.0.0.1:${port}/api/config`)).text();
    } catch {
      await new Promise((r) => setTimeout(r, 100));
    }
  }
  assert.ok(body, 'server did not start');
  const config = JSON.parse(body);
  assert.equal(config.envApiKey, 'BROWSER_KEY');
  assert.ok(!body.includes('SERVER_SECRET_KEY'));
});

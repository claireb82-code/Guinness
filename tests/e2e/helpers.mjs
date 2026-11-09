// Shared harness for the browser tests: the real deployed shape (built React app served statically, API from the
// Python server) plus real Leaflet (a dev dependency, so no CDN is needed), fonts and map tiles blocked.
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

export function loadPlaywright() {
  for (const spec of [process.env.PLAYWRIGHT_PATH, 'playwright'].filter(Boolean)) {
    try {
      return require(spec);
    } catch {
      /* try the next one */
    }
  }
  return null;
}

export const freePort = () =>
  new Promise((resolve) => {
    const s = net.createServer().listen(0, () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' };
const LEAFLET_DIR = path.join(ROOT, 'node_modules', 'leaflet', 'dist');

export const haveLeaflet = () => fs.existsSync(path.join(LEAFLET_DIR, 'leaflet.js'));
export const haveBuild = () => fs.existsSync(path.join(ROOT, 'dist', 'index.html'));

/** Starts the Python API and a static server for dist/ that proxies /api to it. */
export async function startApp({ env = {} } = {}) {
  const apiPort = await freePort();
  const webPort = await freePort();
  const api = spawn('python3', ['app_server.py'], { cwd: ROOT, env: { ...process.env, PORT: String(apiPort), RATE_LIMIT_DISABLED: '1', GUINNESS_NO_DOTENV: '1', ...env }, stdio: 'ignore' });
  for (let i = 0; i < 80; i++) {
    try {
      if ((await fetch(`http://127.0.0.1:${apiPort}/api/config`)).ok) break;
    } catch {
      await new Promise((r) => setTimeout(r, 100));
    }
  }
  const dist = path.join(ROOT, 'dist');
  const web = http.createServer((req, res) => {
    if (req.url.startsWith('/api/')) {
      const upstream = http.request({ host: '127.0.0.1', port: apiPort, path: req.url, method: req.method, headers: req.headers }, (r) => {
        res.writeHead(r.statusCode, r.headers);
        r.pipe(res);
      });
      req.pipe(upstream);
      return;
    }
    let file = path.join(dist, req.url.split('?')[0]);
    if (!file.startsWith(dist) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(dist, 'index.html');
    res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  await new Promise((r) => web.listen(webPort, '127.0.0.1', r));
  return {
    react: `http://127.0.0.1:${webPort}`, // the built React app (what Vercel serves at /)
    standalone: `http://127.0.0.1:${apiPort}`, // public/standalone.html, served by the Python server
    stop: () => {
      api.kill();
      web.close();
    },
  };
}

/** Real Leaflet from node_modules instead of unpkg; no web fonts, no map tiles (they would need the internet). */
export async function routeOffline(page) {
  await page.route('https://unpkg.com/leaflet@1.9.4/dist/**', (route) => {
    const file = route.request().url().split('/dist/')[1];
    route.fulfill({ path: path.join(LEAFLET_DIR, file), contentType: file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'image/png' });
  });
  await page.route(/fonts\.(googleapis|gstatic)\.com|tile\.openstreetmap|basemaps\.cartocdn|tile\.opentopomap/, (route) => route.abort());
}

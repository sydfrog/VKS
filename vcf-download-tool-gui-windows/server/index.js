const path = require('path');
const http = require('http');
const express = require('express');
const lifecycle = require('./lib/lifecycle');
const { APP_HOME, SETTINGS_FILE, active: settings } = require('./lib/appSettings');

lifecycle.teeConsoleToFile(path.join(APP_HOME, 'logs', 'app.log'));
lifecycle.installSignalHandlers();

const { PORT, LISTEN_HOST, INTERNAL_PORT, DEPOT_DIR, TOKEN_DIR, APP_VERSION } = require('./lib/config');
const apiRouter = require('./routes');
const internalRouter = require('./routes-internal');
const refreshScheduler = require('./lib/refreshScheduler');

const argv = process.argv.slice(2);
const RESTARTED = argv.includes('--restarted');
const NO_OPEN = argv.includes('--no-open');
const APP_ID = 'vcf-download-tool-gui';

const uiHost = LISTEN_HOST === '0.0.0.0' ? 'localhost' : LISTEN_HOST;
const UI_URL = `http://${uiHost}:${PORT}/`;

// In the packaged .exe the front-end files are embedded as SEA assets
// rather than sitting next to the binary - serve them from there.
const CONTENT_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.json': 'application/json',
};

function staticFiles() {
  if (!lifecycle.isSea()) return express.static(path.join(__dirname, 'public'));
  const sea = require('node:sea');
  const cache = new Map();
  return (req, res, next) => {
    if (req.method !== 'GET' && req.method !== 'HEAD') return next();
    let rel = decodeURIComponent(req.path);
    if (rel.endsWith('/')) rel += 'index.html';
    const key = `public${rel}`;
    let body = cache.get(key);
    if (!body) {
      try {
        body = Buffer.from(sea.getAsset(key));
      } catch (err) {
        return next();
      }
      cache.set(key, body);
    }
    res.type(CONTENT_TYPES[path.extname(rel).toLowerCase()] || 'application/octet-stream');
    res.send(body);
  };
}

// The API has no login (same as the container build), and on a desktop the
// thing most likely to poke at it is some other web page open in the same
// browser. Two cheap guards close that off:
//   - Host must be this machine (blocks DNS-rebinding) unless network
//     access was switched on in Settings;
//   - state-changing requests must carry X-VCF-GUI, which a cross-site page
//     can't add without a CORS preflight this server never approves.
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);
function guard(req, res, next) {
  if (LISTEN_HOST !== '0.0.0.0') {
    const host = String(req.headers.host || '').replace(/:\d+$/, '').toLowerCase();
    if (!LOCAL_HOSTS.has(host)) {
      res.status(403).json({ error: 'Forbidden host' });
      return;
    }
  }
  if (req.method !== 'GET' && req.method !== 'HEAD' && req.get('X-VCF-GUI') !== '1') {
    res.status(403).json({ error: 'Missing X-VCF-GUI header' });
    return;
  }
  next();
}

const publicApp = express();
publicApp.use(guard);
publicApp.use(express.json());
publicApp.use('/api', apiRouter);
publicApp.use(staticFiles());

// Is whatever owns the port already us? Then this launch is just a
// double-click on a running app: bring the window up and bow out.
function probeExisting() {
  return new Promise((resolve) => {
    const req = http.get({ host: '127.0.0.1', port: PORT, path: '/api/version', timeout: 1500 }, (res) => {
      let body = '';
      res.on('data', (d) => (body += d));
      res.on('end', () => {
        try {
          resolve(JSON.parse(body).app === APP_ID);
        } catch (err) {
          resolve(false);
        }
      });
    });
    req.on('timeout', () => req.destroy());
    req.on('error', () => resolve(false));
  });
}

function waitForEnterThenExit(code) {
  if (!process.stdin.isTTY) {
    process.exit(code);
    return;
  }
  console.log('\nPress Enter to close this window.');
  process.stdin.resume();
  process.stdin.once('data', () => process.exit(code));
}

function printBanner() {
  const line = '-'.repeat(68);
  console.log(line);
  console.log(` VCF Download Tool GUI v${APP_VERSION} (${process.platform === 'win32' ? 'Windows' : process.platform})`);
  console.log(line);
  console.log(`  Open in browser : ${UI_URL}`);
  console.log(`  Depot folder    : ${DEPOT_DIR}`);
  console.log(`  App data        : ${TOKEN_DIR}`);
  console.log(`  Settings file   : ${SETTINGS_FILE}`);
  if (LISTEN_HOST === '0.0.0.0') {
    console.log('  Network access  : ON - other computers can reach this GUI (no login!)');
  }
  console.log(line);
  console.log(' Keep this window open while you use the tool.');
  console.log(' Closing it stops the GUI and any download that is running.');
  console.log(line);
}

function listen(attempt = 0) {
  const server = publicApp.listen(PORT, LISTEN_HOST);
  server.once('listening', () => {
    printBanner();
    refreshScheduler.start();
    if (!NO_OPEN) lifecycle.openUi(UI_URL, settings.openMode);
    startInternal();
  });
  server.once('error', async (err) => {
    if (err.code !== 'EADDRINUSE') {
      console.error(`Could not start the web server: ${err.message}`);
      waitForEnterThenExit(1);
      return;
    }
    // After an in-app restart the old instance may still be letting go.
    if (RESTARTED && attempt < 40) {
      setTimeout(() => listen(attempt + 1), 250);
      return;
    }
    if (await probeExisting()) {
      console.log(`VCF Download Tool GUI is already running - opening ${UI_URL}`);
      lifecycle.openUi(UI_URL, settings.openMode === 'none' ? 'browser' : settings.openMode);
      setTimeout(() => process.exit(0), 500);
      return;
    }
    console.error(`Port ${PORT} is already used by another program.`);
    console.error(`Change "port" in ${SETTINGS_FILE} (or set the PORT environment variable) and start again.`);
    waitForEnterThenExit(1);
  });
}

// Separate Express instance (not a second app.listen() on the same app) so
// these internal, unauthenticated, filesystem-exposing routes can never
// become reachable through the public port's middleware stack - see
// routes-internal.js. Off unless internalPort is set in settings.json.
function startInternal() {
  if (!INTERNAL_PORT) return;
  const internalApp = express();
  internalApp.use('/internal', internalRouter);
  internalApp
    .listen(INTERNAL_PORT, LISTEN_HOST, () => {
      console.log(`Internal depot API listening on ${LISTEN_HOST}:${INTERNAL_PORT}`);
    })
    .on('error', (err) => console.error(`Internal depot API not started: ${err.message}`));
}

listen();

module.exports = { APP_ID };

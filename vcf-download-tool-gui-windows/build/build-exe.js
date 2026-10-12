#!/usr/bin/env node
// Builds dist/VCF-Download-Tool-GUI.exe - one self-contained Windows
// executable (Node.js runtime + server + web UI), using Node's Single
// Executable Application support. Runs on Windows or Linux:
//
//   npm install
//   npm run build                  # Windows x64 .exe (default)
//   npm run build -- --target=host # binary for the machine you're on (testing)
//
// The SEA blob must be produced by the same Node version as the runtime it
// is injected into, so the Windows node.exe downloaded below always matches
// the Node running this script.

const fs = require('fs');
const path = require('path');
const https = require('https');
const crypto = require('crypto');
const { execFileSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(__dirname, 'out');
const DIST = path.join(ROOT, 'dist');
const target = (process.argv.find((a) => a.startsWith('--target=')) || '--target=win').split('=')[1];
const forWindows = target === 'win' || (target === 'host' && process.platform === 'win32');
const EXE_NAME = forWindows ? 'VCF-Download-Tool-GUI.exe' : 'vcf-download-tool-gui';
const FUSE = 'NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2';

const [major] = process.versions.node.split('.').map(Number);
if (major < 20) {
  console.error(`Node 20 or newer is required to build (found ${process.version}).`);
  process.exit(1);
}

function log(msg) {
  console.log(`[build] ${msg}`);
}

function get(url) {
  return new Promise((resolve, reject) => {
    https
      .get(url, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          resolve(get(new URL(res.headers.location, url).toString()));
          return;
        }
        if (res.statusCode !== 200) {
          reject(new Error(`GET ${url} -> HTTP ${res.statusCode}`));
          return;
        }
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => resolve(Buffer.concat(chunks)));
        res.on('error', reject);
      })
      .on('error', reject);
  });
}

// Official node.exe for this exact Node version, checked against
// nodejs.org's published SHA-256 list. Cached in build/cache.
async function windowsNodeExe() {
  if (process.platform === 'win32' && process.arch === 'x64') return process.execPath;
  const cacheDir = path.join(__dirname, 'cache', process.version);
  const cached = path.join(cacheDir, 'node.exe');
  if (fs.existsSync(cached)) return cached;

  const base = `https://nodejs.org/dist/${process.version}`;
  log(`downloading ${base}/win-x64/node.exe`);
  const [exe, sums] = await Promise.all([get(`${base}/win-x64/node.exe`), get(`${base}/SHASUMS256.txt`)]);
  const expected = sums
    .toString('utf8')
    .split('\n')
    .map((l) => l.trim().split(/\s+/))
    .find(([, name]) => name === 'win-x64/node.exe');
  const actual = crypto.createHash('sha256').update(exe).digest('hex');
  if (!expected || expected[0] !== actual) {
    throw new Error(`node.exe checksum mismatch (expected ${expected && expected[0]}, got ${actual})`);
  }
  fs.mkdirSync(cacheDir, { recursive: true });
  fs.writeFileSync(cached, exe);
  return cached;
}

function listFiles(dir, prefix = '') {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const rel = prefix ? `${prefix}/${e.name}` : e.name;
    if (e.isDirectory()) out.push(...listFiles(path.join(dir, e.name), rel));
    else out.push(rel);
  }
  return out;
}

async function main() {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  fs.mkdirSync(DIST, { recursive: true });

  // 1. One CommonJS file with express/multer inlined.
  log('bundling server with esbuild');
  const esbuild = require('esbuild');
  await esbuild.build({
    entryPoints: [path.join(ROOT, 'server', 'index.js')],
    bundle: true,
    platform: 'node',
    target: `node${major}`,
    format: 'cjs',
    outfile: path.join(OUT, 'server.cjs'),
    logLevel: 'warning',
    // express' view engine loader does require(dynamicName); the GUI never
    // renders views, so leaving that unresolved is harmless.
    logOverride: { 'unsupported-require-call': 'silent' },
  });

  // 2. SEA blob: the bundle plus every front-end file as an embedded asset.
  const publicDir = path.join(ROOT, 'server', 'public');
  const assets = {};
  for (const rel of listFiles(publicDir)) assets[`public/${rel}`] = path.join(publicDir, ...rel.split('/'));
  const seaConfig = {
    main: path.join(OUT, 'server.cjs'),
    output: path.join(OUT, 'sea-prep.blob'),
    disableExperimentalSEAWarning: true,
    useSnapshot: false,
    useCodeCache: false, // must stay off when building for another OS
    assets,
  };
  fs.writeFileSync(path.join(OUT, 'sea-config.json'), JSON.stringify(seaConfig, null, 2));
  log(`creating SEA blob (${Object.keys(assets).length} UI assets)`);
  execFileSync(process.execPath, ['--experimental-sea-config', path.join(OUT, 'sea-config.json')], { stdio: 'inherit' });

  // 3. Copy a node runtime and inject the blob.
  const runtime = forWindows ? await windowsNodeExe() : process.execPath;
  const exe = path.join(DIST, EXE_NAME);
  fs.rmSync(exe, { force: true });
  fs.copyFileSync(runtime, exe);
  fs.chmodSync(exe, 0o755);

  log(`injecting into ${path.relative(ROOT, exe)}`);
  const postjectCli = require.resolve('postject/dist/cli.js');
  const pjArgs = [postjectCli, exe, 'NODE_SEA_BLOB', seaConfig.output, '--sentinel-fuse', FUSE];
  if (!forWindows && process.platform === 'darwin') pjArgs.push('--macho-segment-name', 'NODE_SEA');
  execFileSync(process.execPath, pjArgs, { stdio: 'inherit' });

  const mb = (fs.statSync(exe).size / 1024 / 1024).toFixed(1);
  log(`done: ${exe} (${mb} MB)`);
}

main().catch((err) => {
  console.error(`[build] FAILED: ${err.stack || err.message}`);
  process.exit(1);
});

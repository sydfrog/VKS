#!/usr/bin/env node
// End-to-end smoke test against a fake CLI (test/fake-cli). Exercises the
// parts that differ on Windows: uploading/extracting the tar.gz with the
// system tar, launching bin\vcf-download-tool.bat through cmd.exe with
// awkward paths, process handling, and the depot folder scan.
//
//   node test/smoke.js                       # runs server/index.js
//   node test/smoke.js --exe=dist\VCF-Download-Tool-GUI.exe

const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');
const { spawn, execFileSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const IS_WIN = process.platform === 'win32';
const exeArg = process.argv.find((a) => a.startsWith('--exe='));
const PORT = 18000 + Math.floor(Math.random() * 1000);
const BASE = `http://127.0.0.1:${PORT}`;

// Deliberately hostile-but-legal folder names: spaces, parentheses and an
// ampersand all mean something to cmd.exe outside quotes.
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'vcfgui smoke '));
const home = path.join(work, 'app home');
const depot = path.join(work, 'My Depot (lab) & co');
fs.mkdirSync(home, { recursive: true });
fs.writeFileSync(
  path.join(home, 'settings.json'),
  JSON.stringify({ depotDir: depot, port: PORT, openMode: 'none' }, null, 2)
);

let server;
let serverLog = '';
let failed = false;

function step(name) {
  console.log(`- ${name}`);
}

async function api(p, opts = {}) {
  const res = await fetch(`${BASE}/api${p}`, {
    ...opts,
    headers: { 'X-VCF-GUI': '1', ...(opts.body && typeof opts.body === 'string' ? { 'Content-Type': 'application/json' } : {}), ...(opts.headers || {}) },
  });
  const body = await res.json().catch(() => ({}));
  return { status: res.status, body };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, what, timeoutMs = 30000) {
  const start = Date.now();
  for (;;) {
    try {
      const v = await fn();
      if (v) return v;
    } catch (err) {
      // retry
    }
    if (Date.now() - start > timeoutMs) throw new Error(`timed out waiting for ${what}`);
    await sleep(300);
  }
}

function makeFakeCliArchive() {
  const archive = path.join(work, 'vcf-download-tool-fake.tar.gz');
  const tar = IS_WIN ? path.join(process.env.SystemRoot, 'System32', 'tar.exe') : 'tar';
  execFileSync(tar, ['-czf', archive, '-C', path.join(__dirname, 'fake-cli'), 'bin']);
  return archive;
}

async function main() {
  const archive = makeFakeCliArchive();

  const cmd = exeArg ? path.resolve(exeArg.slice(6)) : process.execPath;
  const args = exeArg ? ['--no-open'] : [path.join(ROOT, 'server', 'index.js'), '--no-open'];
  step(`starting ${path.basename(cmd)} on port ${PORT}`);
  server = spawn(cmd, args, {
    env: { ...process.env, VCFGUI_HOME: home, FAKE_CLI_NODE: process.execPath },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  server.stdout.on('data', (d) => (serverLog += d));
  server.stderr.on('data', (d) => (serverLog += d));
  await waitFor(async () => (await api('/version')).body.app === 'vcf-download-tool-gui', 'server');

  step('guards: state-changing request without X-VCF-GUI is refused');
  let res = await fetch(`${BASE}/api/token`, { method: 'DELETE' });
  assert.strictEqual(res.status, 403);
  // fetch() won't let us forge Host, so use a raw request (DNS-rebinding case).
  const rebindStatus = await new Promise((resolve, reject) => {
    require('http')
      .get({ host: '127.0.0.1', port: PORT, path: '/api/version', headers: { Host: 'evil.example' } }, (r) => {
        r.resume();
        resolve(r.statusCode);
      })
      .on('error', reject);
  });
  assert.strictEqual(rebindStatus, 403, 'foreign Host header should be refused');

  step('no CLI yet -> cli-version null, friendly error on list');
  assert.strictEqual((await api('/cli-version')).body.cliVersion, null);

  step('upload the fake CLI tar.gz');
  const form = new FormData();
  form.append('archive', new Blob([fs.readFileSync(archive)]), 'vcf-download-tool-fake.tar.gz');
  res = await api('/cli/install', { method: 'POST', body: form });
  assert.strictEqual(res.status, 200, JSON.stringify(res.body));
  assert.strictEqual(res.body.installed, true);

  step('cli-version is read through the launcher');
  const ver = (await api('/cli-version')).body;
  assert.strictEqual(ver.cliVersion, '9.1.1.0', JSON.stringify(ver));
  assert.strictEqual(ver.artifactsSupported, true);

  step('generate software depot ID');
  res = await api('/depot-id/generate', { method: 'POST' });
  assert.strictEqual(res.status, 200, JSON.stringify(res.body));
  assert.ok(res.body.set && /^[0-9a-f-]{36}$/.test(res.body.id), JSON.stringify(res.body));

  step('save activation code');
  res = await api('/token', { method: 'POST', body: JSON.stringify({ token: 'FAKE-ACTIVATION-CODE-1234' }) });
  assert.strictEqual(res.body.saved, true);

  step('release discovery');
  res = await api('/releases?refresh=true');
  assert.strictEqual(res.status, 200, JSON.stringify(res.body));
  assert.ok(JSON.stringify(res.body).includes('9.1.0.0'), JSON.stringify(res.body));

  step('list binaries');
  res = await api('/binaries?version=9.1.0.0&sku=VCF&type=INSTALL');
  assert.strictEqual(res.status, 200, JSON.stringify(res.body));
  const vc = res.body.binaries.find((b) => b.component === 'VCENTER');
  assert.ok(vc && vc.downloaded === false, JSON.stringify(res.body));

  step('download into a depot path with spaces, parentheses and &');
  res = await api('/download', { method: 'POST', body: JSON.stringify({ ids: [vc.id], binaries: [vc] }) });
  assert.strictEqual(res.status, 200, JSON.stringify(res.body));
  const jobId = res.body.jobId;
  const job = await waitFor(async () => {
    const j = (await api('/downloads')).body.jobs.find((x) => x.id === jobId);
    return j && j.status !== 'running' ? j : null;
  }, 'download job');
  assert.strictEqual(job.status, 'complete', JSON.stringify(job));
  assert.strictEqual(job.binaries[0].status, 'done');

  const argvLog = fs
    .readFileSync(path.join(home, 'data', 'cli', 'argv.jsonl'), 'utf8')
    .trim()
    .split('\n')
    .map((l) => JSON.parse(l));
  const dl = argvLog.find((a) => a[0] === 'binaries' && a[1] === 'download');
  assert.ok(dl.includes(`--depot-store=${path.resolve(depot)}`), `CLI saw: ${JSON.stringify(dl)}`);
  assert.ok(
    fs.existsSync(path.join(depot, 'PROD', 'COMP', 'VCENTER', 'VCENTER-9.1.0.0.25000001.iso')),
    'downloaded file missing from depot'
  );

  step('downloaded state, storage, stats, logs');
  res = await api('/binaries?version=9.1.0.0&sku=VCF&type=INSTALL');
  assert.strictEqual(res.body.binaries.find((b) => b.component === 'VCENTER').downloaded, true);
  assert.ok((await api('/storage')).body.totalBytes > 0);
  const stats = (await api('/system-stats')).body;
  assert.ok(stats.memory && stats.memory.usedBytes > 0, JSON.stringify(stats));
  const logs = (await api('/cli-logs')).body;
  assert.ok(logs.exists && logs.entries.some((e) => e.name === 'vdt.log'), JSON.stringify(logs));
  const logContent = (await api('/cli-logs/vdt.log')).body;
  assert.ok(String(logContent.content).includes('ran:'), JSON.stringify(logContent));
  assert.strictEqual((await api('/cli-logs/..%2F..%2Factivation-code.txt')).status, 400);

  step('delete downloaded binary');
  res = await api('/delete', { method: 'POST', body: JSON.stringify({ binaries: [vc] }) });
  assert.strictEqual(res.body.removed.length, 1, JSON.stringify(res.body));

  if (IS_WIN) {
    step('cmd.exe metacharacters in user input are refused, not executed');
    const marker = path.join(work, 'pwned.txt');
    res = await api(`/binaries?version=${encodeURIComponent(`9.1" & echo x > "${marker}`)}&sku=VCF&type=INSTALL`);
    assert.strictEqual(res.status, 400, JSON.stringify(res.body));
    assert.ok(!fs.existsSync(marker), 'injected command ran!');
  }

  step('application settings round-trip');
  res = await api('/app-settings');
  assert.strictEqual(path.resolve(res.body.active.depotDir), path.resolve(depot));
  res = await api('/app-settings', { method: 'POST', body: JSON.stringify({ port: PORT + 1 }) });
  assert.strictEqual(res.body.saved.port, PORT + 1);
  res = await api('/app-settings', { method: 'POST', body: JSON.stringify({ depotDir: 'relative\\path' }) });
  assert.strictEqual(res.status, 400);

  console.log('\nSMOKE TEST PASSED');
}

main()
  .catch((err) => {
    failed = true;
    console.error(`\nSMOKE TEST FAILED: ${err.stack || err.message}`);
    console.error(`\n--- server output ---\n${serverLog}`);
  })
  .finally(() => {
    if (server && server.exitCode === null) {
      if (IS_WIN) {
        try {
          execFileSync('taskkill', ['/pid', String(server.pid), '/T', '/F'], { stdio: 'ignore' });
        } catch (err) {
          // already gone
        }
      } else {
        server.kill();
      }
    }
    setTimeout(() => {
      fs.rmSync(work, { recursive: true, force: true, maxRetries: 5 });
      process.exit(failed ? 1 : 0);
    }, 500);
  });

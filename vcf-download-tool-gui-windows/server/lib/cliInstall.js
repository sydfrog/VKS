const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { CLI_DIR, CLI_STAGING_DIR } = require('./config');
const { acquireCliLock, cliEnv } = require('./cliRunner');
const { CLI_LAUNCHER_NAME, spawnLauncher, killTree, tarBin } = require('./platform');
const cliVersion = require('./cliVersion');

class CliInstallError extends Error {}

// Windows Defender and the search indexer briefly lock freshly extracted
// files (the bundled JRE is a few thousand of them), so deletes and the
// final rename are retried rather than failing the install on EBUSY/EPERM.
function rmrf(p) {
  fs.rmSync(p, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

function renameWithRetry(from, to) {
  for (let attempt = 0; ; attempt++) {
    try {
      fs.renameSync(from, to);
      return;
    } catch (err) {
      if (attempt >= 20 || !['EBUSY', 'EPERM', 'EACCES'].includes(err.code)) throw err;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250);
    }
  }
}

const EXTRACT_TIMEOUT_MS = 3 * 60 * 1000;
const VALIDATE_TIMEOUT_MS = 90 * 1000;

function extractArchive(archivePath, destDir) {
  return new Promise((resolve, reject) => {
    // No -P/--absolute-names - tar's own default protection against
    // absolute-path/traversal entries applies. On Windows this is the
    // built-in bsdtar (System32\tar.exe), which handles .tar.gz natively.
    const child = spawn(tarBin(), ['-xzf', archivePath, '-C', destDir], { windowsHide: true });
    let stderr = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new CliInstallError(`Extraction timed out after ${EXTRACT_TIMEOUT_MS / 1000}s.`));
    }, EXTRACT_TIMEOUT_MS);

    child.stderr.on('data', (d) => (stderr += d.toString('utf8')));
    child.on('error', (err) => {
      clearTimeout(timer);
      reject(new CliInstallError(`Failed to run tar: ${err.message}`));
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        reject(new CliInstallError(`Extraction failed - is this a valid vcf-download-tool tar.gz? (tar exit ${code}: ${stderr.trim()})`));
        return;
      }
      resolve();
    });
  });
}

// Broadcom's own tar.gz has no top-level wrapper directory - bin/, conf/,
// jre/ sit directly at the archive root (confirmed against a real
// download). But if someone uploads a re-packaged copy that does have one
// (e.g. they tar'd up their own already-extracted copy), detect and
// unwrap it one level rather than failing validation.
function hasLauncher(dir) {
  return fs.existsSync(path.join(dir, 'bin', CLI_LAUNCHER_NAME)) || fs.existsSync(path.join(dir, 'bin', 'vcf-download-tool'));
}

function unwrapIfNeeded(destDir) {
  if (hasLauncher(destDir)) return;

  const entries = fs.readdirSync(destDir);
  if (entries.length !== 1) return;

  const wrapped = path.join(destDir, entries[0]);
  if (!fs.statSync(wrapped).isDirectory()) return;
  if (!hasLauncher(wrapped)) return;

  for (const child of fs.readdirSync(wrapped)) {
    renameWithRetry(path.join(wrapped, child), path.join(destDir, child));
  }
  fs.rmdirSync(wrapped);
}

async function extract(archivePath, destDir) {
  fs.mkdirSync(destDir, { recursive: true });
  await extractArchive(archivePath, destDir);
  unwrapIfNeeded(destDir);
}

// Uploading the archive fresh from Broadcom (rather than extract-then-copy
// through several hops, which is how earlier bind-mount deployments ended
// up with mangled permissions) means tar's own default permission
// preservation should already be correct. This is just a defensive
// fallback, not the primary fix it was in the bind-mount days.
function relaxPermissions(dir) {
  try {
    fs.chmodSync(dir, 0o755);
  } catch (err) {
    // best-effort
  }
}

function validate(stagingBin) {
  return new Promise((resolve) => {
    if (!fs.existsSync(stagingBin)) {
      resolve({
        ok: false,
        reason: `bin/${CLI_LAUNCHER_NAME} wasn't found in the uploaded archive - is this the vcf-download-tool tar.gz from the Broadcom portal?`,
      });
      return;
    }

    let child;
    try {
      child = spawnLauncher(stagingBin, ['--version'], {
        cwd: path.dirname(stagingBin),
        env: cliEnv,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (err) {
      resolve({ ok: false, reason: `Could not run the extracted CLI: ${err.message}` });
      return;
    }
    let stdout = '';
    const timer = setTimeout(() => {
      killTree(child);
      resolve({
        ok: false,
        reason: `The extracted CLI did not respond to --version within ${VALIDATE_TIMEOUT_MS / 1000}s (partial output: ${stdout.trim().slice(0, 300) || '<none>'}).`,
      });
    }, VALIDATE_TIMEOUT_MS);

    child.stdout.on('data', (d) => (stdout += d.toString('utf8')));
    child.on('error', (err) => {
      clearTimeout(timer);
      resolve({ ok: false, reason: `Could not run the extracted CLI: ${err.message}` });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (code !== 0 || !/^Version:/m.test(stdout)) {
        const tail = stdout.trim().split(/\r?\n/).slice(-3).join(' / ').slice(0, 300);
        resolve({
          ok: false,
          reason: `The extracted CLI did not run correctly (exit code ${code}${tail ? `: ${tail}` : ''}).`,
        });
        return;
      }
      resolve({ ok: true });
    });
  });
}

// The whole extract+validate+swap runs under the same mutex as every other
// CLI invocation, so an install can't race an in-flight list/download and
// vice versa - it just queues, same as a second download already queues
// behind a first one.
async function installFromUpload(archivePath) {
  const release = await acquireCliLock();
  try {
    rmrf(CLI_STAGING_DIR);
    await extract(archivePath, CLI_STAGING_DIR);
    relaxPermissions(CLI_STAGING_DIR);

    const stagingBin = path.join(CLI_STAGING_DIR, 'bin', CLI_LAUNCHER_NAME);
    const result = await validate(stagingBin);
    if (!result.ok) {
      rmrf(CLI_STAGING_DIR);
      throw new CliInstallError(result.reason);
    }

    rmrf(CLI_DIR);
    renameWithRetry(CLI_STAGING_DIR, CLI_DIR);

    cliVersion.invalidate();
  } finally {
    fs.rm(archivePath, { force: true }, () => {});
    release();
  }
}

function getInstallStatus() {
  const installed = fs.existsSync(CLI_DIR);
  let installedAt = null;
  if (installed) {
    try {
      installedAt = fs.statSync(CLI_DIR).mtime.toISOString();
    } catch (err) {
      installedAt = null;
    }
  }
  return { installed, installedAt };
}

module.exports = { installFromUpload, getInstallStatus, CliInstallError };

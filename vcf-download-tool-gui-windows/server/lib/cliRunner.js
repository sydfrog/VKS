const fs = require('fs');
const os = require('os');
const path = require('path');
const { CLI_BIN, TOKEN_FILE, XDG_DATA_HOME, CLI_JAVA_TOOL_OPTIONS } = require('./config');
const { spawnLauncher, killTree } = require('./platform');

// JAVA_TOOL_OPTIONS is read by the JVM directly regardless of Broadcom's
// launcher script, so it's the one reliable way to tune the CLI's heap
// (e.g. -Xmx2g if a newer CLI runs out of memory). Only set when configured
// in Settings > Application - unlike the 1 GB container, a desktop has no
// memory cap that makes the JVM's default heap too small.
const cliEnv = { ...process.env, XDG_DATA_HOME };
if (CLI_JAVA_TOOL_OPTIONS) cliEnv.JAVA_TOOL_OPTIONS = CLI_JAVA_TOOL_OPTIONS;

function cliMissingError() {
  return new CliError(
    'The VCF Download Tool CLI is not installed yet. Upload the tar.gz from the Broadcom portal in Settings.'
  );
}

function scratchDir() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vdt-run-'));
  const cleanup = () => fs.rm(dir, { recursive: true, force: true }, () => {});
  return { dir, cleanup };
}

// The CLI's own application-prodv2.properties pins its scratch/staging dir
// to ${user.home}/tmpRootDir - a single fixed path per OS user, not per
// process, with no per-invocation override. Two invocations running at once
// (our concurrent INSTALL/UPGRADE list calls, or a list happening alongside
// a download) step on each other's temp files there and intermittently fail
// with a NoSuchFileException. The only safe fix is a hard mutex: never let
// two CLI processes run at once. acquireCliLock() resolves with a release()
// function once it's this caller's turn.
let cliLockTail = Promise.resolve();
function acquireCliLock() {
  let release;
  const held = new Promise((res) => {
    release = res;
  });
  const myTurn = cliLockTail;
  cliLockTail = held;
  return myTurn.then(() => release);
}

class CliError extends Error {
  constructor(message, { code, stdout, stderr } = {}) {
    super(message);
    this.name = 'CliError';
    this.code = code;
    this.stdout = stdout;
    this.stderr = stderr;
  }
}

function assertTokenPresent() {
  if (!fs.existsSync(TOKEN_FILE)) {
    throw new CliError(
      'No activation code configured yet. Add one in Settings before browsing or downloading binaries.'
    );
  }
}

// Runs the CLI to completion and returns combined stdout/stderr. Used for
// `binaries list` calls where we need the full table before we can respond.
//
// `--ceip` is only understood by the `binaries` subcommands (list/download/
// cleanup) - `configuration generate|get` reject it outright with "Unknown
// option", so callers for those must pass `ceip: false`.
async function runCli(args, { timeoutMs = 120000, requireToken = true, ceip = true } = {}) {
  if (requireToken) assertTokenPresent();
  const fullArgs = ceip ? [...args, '--ceip=DISABLE'] : args;

  if (!fs.existsSync(CLI_BIN)) throw cliMissingError();

  const release = await acquireCliLock();
  const { dir: cwd, cleanup } = scratchDir();

  try {
    return await new Promise((resolve, reject) => {
      const child = spawnLauncher(CLI_BIN, fullArgs, {
        cwd,
        env: cliEnv,
        stdio: ['ignore', 'pipe', 'pipe'],
      });

      let stdout = '';
      let stderr = '';
      const timer = setTimeout(() => {
        killTree(child);
        reject(new CliError(`vcf-download-tool timed out after ${timeoutMs}ms`, { stdout, stderr }));
      }, timeoutMs);

      child.stdout.on('data', (d) => (stdout += d.toString('utf8')));
      child.stderr.on('data', (d) => (stderr += d.toString('utf8')));

      child.on('error', (err) => {
        clearTimeout(timer);
        reject(new CliError(`Failed to launch vcf-download-tool: ${err.message}`, { stdout, stderr }));
      });

      child.on('close', (code) => {
        clearTimeout(timer);
        if (code !== 0) {
          reject(new CliError(extractErrorMessage(stdout, stderr, code), { code, stdout, stderr }));
          return;
        }
        resolve({ stdout, stderr });
      });
    });
  } finally {
    cleanup();
    release();
  }
}

// Runs the CLI and streams each line of output to `onLine` as it arrives.
// Used for `binaries download` so the GUI can show live progress. Holds the
// CLI lock for the whole lifetime of the process (releasing on close), so
// list calls queue behind an in-flight download rather than racing it.
async function streamCli(args, onLine) {
  assertTokenPresent();
  const fullArgs = [...args, '--ceip=DISABLE'];

  if (!fs.existsSync(CLI_BIN)) throw cliMissingError();

  const release = await acquireCliLock();
  const { dir: cwd, cleanup } = scratchDir();

  let child;
  try {
    child = spawnLauncher(CLI_BIN, fullArgs, {
      cwd,
      env: cliEnv,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch (err) {
    cleanup();
    release();
    throw err;
  }
  // 'error' (launch failure) may fire without a following 'close' - make
  // sure the lock is released exactly once either way.
  let released = false;
  const done = () => {
    if (released) return;
    released = true;
    cleanup();
    release();
  };
  child.on('close', done);
  child.on('error', (err) => {
    onLine(`Failed to launch vcf-download-tool: ${err.message}`);
    done();
  });

  const wire = (stream) => {
    let buf = '';
    stream.on('data', (chunk) => {
      buf += chunk.toString('utf8');
      // The CLI redraws progress with carriage returns, not just newlines.
      let idx;
      while ((idx = buf.search(/[\r\n]/)) !== -1) {
        const line = buf.slice(0, idx);
        buf = buf.slice(idx + 1);
        if (line.trim().length > 0) onLine(line);
      }
    });
    stream.on('end', () => {
      if (buf.trim().length > 0) onLine(buf);
    });
  };

  wire(child.stdout);
  wire(child.stderr);

  return child;
}

function extractErrorMessage(stdout, stderr, code) {
  const combined = `${stdout}\n${stderr}`;
  const lines = combined
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);

  // Prefer known error markers over generic banner/usage noise.
  // "ERROR:" / "Fail to ..." cover the artifacts command's auth + filter
  // messages, which don't use the same casing as the binaries command's.
  const markers = ['Error', 'ERROR', 'Exception', 'Invalid', 'invalid', 'failed', 'Failed', 'Fail'];
  const hit = lines.find((l) => markers.some((m) => l.includes(m)));
  return hit || `vcf-download-tool exited with code ${code}`;
}

module.exports = { runCli, streamCli, acquireCliLock, CliError, cliEnv };

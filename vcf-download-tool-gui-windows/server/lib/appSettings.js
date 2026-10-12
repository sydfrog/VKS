const fs = require('fs');
const os = require('os');
const path = require('path');
const { IS_WIN } = require('./platform');

// The container build configured itself through environment variables and
// Docker volumes. A desktop app has neither, so the same knobs live in a
// small JSON file instead, editable from the Settings page:
//
//   %LOCALAPPDATA%\VCF-Download-Tool-GUI\settings.json
//
// Environment variables (DEPOT_DIR, TOKEN_DIR, PORT, ...) still win when
// set, which keeps scripted/portable setups working.

const APP_HOME =
  process.env.VCFGUI_HOME ||
  (IS_WIN
    ? path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'VCF-Download-Tool-GUI')
    : path.join(os.homedir(), '.vcf-download-tool-gui'));

const SETTINGS_FILE = path.join(APP_HOME, 'settings.json');

const DEFAULTS = {
  // Where downloaded binaries land (the CLI's --depot-store). Can be a local
  // folder, a mapped drive or a UNC path (\\server\share\vcf-depot).
  depotDir: path.join(os.homedir(), 'vcf-depot'),
  port: 8080,
  // 127.0.0.1 = only this PC can open the GUI. The API has no login, so
  // 0.0.0.0 (other machines on the network) is opt-in.
  listenHost: '127.0.0.1',
  // 'app' = Edge app window, 'browser' = default browser, 'none'.
  openMode: 'app',
  // Passed to the CLI's JVM as JAVA_TOOL_OPTIONS (e.g. -Xmx2g). Empty means
  // the JVM default (a quarter of RAM), which is plenty outside a container.
  javaToolOptions: '',
  // Internal depot API for the companion vcf-web-depot container. Off (0)
  // by default on a desktop; always bound to listenHost when on.
  internalPort: 0,
};

function load() {
  try {
    const parsed = JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
    return { ...DEFAULTS, ...parsed };
  } catch (err) {
    return { ...DEFAULTS };
  }
}

// Snapshot taken at startup - what the running server actually uses. Saving
// new settings only takes effect after a restart (see routes.js).
const active = load();

function validate(input) {
  const out = {};
  if (input.depotDir !== undefined) {
    const dir = String(input.depotDir).trim();
    if (!dir) throw new Error('Depot folder cannot be empty.');
    if (!path.isAbsolute(dir)) throw new Error('Depot folder must be a full path, e.g. D:\\vcf-depot or \\\\server\\share\\vcf-depot');
    if (/["%!\r\n]/.test(dir)) throw new Error('Depot folder cannot contain " % or ! characters.');
    try {
      fs.mkdirSync(dir, { recursive: true });
      const probe = path.join(dir, `.vcfgui-write-test-${process.pid}`);
      fs.writeFileSync(probe, 'ok');
      fs.unlinkSync(probe);
    } catch (err) {
      throw new Error(`Can't write to ${dir}: ${err.message}`);
    }
    out.depotDir = dir;
  }
  if (input.port !== undefined) {
    const port = Number(input.port);
    if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Port must be between 1024 and 65535.');
    out.port = port;
  }
  if (input.listenHost !== undefined) {
    if (!['127.0.0.1', '0.0.0.0'].includes(input.listenHost)) throw new Error('Invalid listen address.');
    out.listenHost = input.listenHost;
  }
  if (input.openMode !== undefined) {
    if (!['app', 'browser', 'none'].includes(input.openMode)) throw new Error('Invalid window option.');
    out.openMode = input.openMode;
  }
  if (input.javaToolOptions !== undefined) {
    const opts = String(input.javaToolOptions).trim();
    if (/[\r\n"%!]/.test(opts)) throw new Error('Java options cannot contain line breaks, " % or !');
    out.javaToolOptions = opts;
  }
  return out;
}

function save(input) {
  const next = { ...load(), ...validate(input || {}) };
  fs.mkdirSync(APP_HOME, { recursive: true });
  fs.writeFileSync(SETTINGS_FILE, JSON.stringify(next, null, 2));
  return next;
}

module.exports = { APP_HOME, SETTINGS_FILE, DEFAULTS, active, load, save };

const fs = require('fs');
const os = require('os');
const path = require('path');
const { DEPOT_ID_FILE } = require('./config');
const { runCli } = require('./cliRunner');
const { IS_WIN } = require('./platform');

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UUID_ANYWHERE_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

// On Linux the CLI keeps the depot ID at $XDG_DATA_HOME/vmware/vdt/machine_id,
// and we point XDG_DATA_HOME into our data folder. Whether the Windows build
// of the CLI honours XDG_DATA_HOME isn't documented, so also look where a
// Java app would put it by default on Windows. DEPOT_ID_FILE stays first so
// that's where we read from and write to whenever it exists.
function candidateFiles() {
  const home = os.homedir();
  const rel = path.join('vmware', 'vdt', 'machine_id');
  const list = [DEPOT_ID_FILE, path.join(home, '.local', 'share', rel)];
  if (IS_WIN) {
    if (process.env.APPDATA) list.push(path.join(process.env.APPDATA, rel));
    if (process.env.LOCALAPPDATA) list.push(path.join(process.env.LOCALAPPDATA, rel));
  }
  return list;
}

function findIdFile() {
  return candidateFiles().find((f) => {
    try {
      return UUID_RE.test(fs.readFileSync(f, 'utf8').trim());
    } catch (err) {
      return false;
    }
  });
}

function statusFor(id) {
  return {
    set: true,
    id,
    registerUrl: `https://vcf.broadcom.com/vcf/clm/download-manager/register?serviceId=${id}`,
  };
}

function getStatus() {
  const file = findIdFile();
  if (!file) return { set: false };
  return statusFor(fs.readFileSync(file, 'utf8').trim());
}

// Generates a brand new random depot ID via the CLI itself (no token
// required for this command) - for first-time setups with no existing ID.
async function generate() {
  const { stdout } = await runCli(['configuration', 'generate', '--software-depot-id', '--force'], {
    requireToken: false,
    ceip: false,
  });

  // If the CLI wrote the ID somewhere we don't look, fall back to the UUID
  // it printed and mirror it into DEPOT_ID_FILE so the GUI can show it.
  let status = getStatus();
  const registerLine = extractRegisterLine(stdout);
  const printed = (registerLine || stdout).match(UUID_ANYWHERE_RE);
  if (printed && (!status.set || status.id.toLowerCase() !== printed[0].toLowerCase())) {
    writeId(DEPOT_ID_FILE, printed[0]);
    status = statusFor(printed[0]);
  }
  return { ...status, cliOutput: registerLine };
}

function writeId(file, id) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${id}\n`, { mode: 0o600 });
}

// Writes a pre-existing depot ID directly (e.g. one already registered on
// the Broadcom portal against the user's activation code from a previous
// install of the CLI elsewhere). Also updates any other machine_id file the
// CLI is already using, so the two can never disagree.
function setExisting(id) {
  const trimmed = (id || '').trim();
  if (!UUID_RE.test(trimmed)) {
    throw new Error('Software depot ID must be a UUID, e.g. c3d3d097-73cc-4260-abd9-75e528ebbf33');
  }
  writeId(DEPOT_ID_FILE, trimmed);
  for (const f of candidateFiles().slice(1)) {
    if (fs.existsSync(f)) writeId(f, trimmed);
  }
  return getStatus();
}

function extractRegisterLine(stdout) {
  const line = stdout.split(/\r?\n/).find((l) => l.includes('Use this link to register'));
  return line ? line.trim() : null;
}

module.exports = { getStatus, generate, setExisting };

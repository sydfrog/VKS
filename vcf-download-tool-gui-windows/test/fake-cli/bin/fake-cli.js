// Stand-in for Broadcom's vcf-download-tool, used only by test/smoke.js.
// Records exactly the argv it received (after cmd.exe / the .bat have had
// their go at it) and behaves just enough like the real CLI for the GUI.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const args = process.argv.slice(2);
const opt = (name) => {
  const a = args.find((x) => x.startsWith(`--${name}=`));
  return a ? a.slice(name.length + 3) : undefined;
};

const installDir = path.resolve(__dirname, '..');
fs.appendFileSync(path.join(installDir, 'argv.jsonl'), JSON.stringify(args) + '\n');
fs.mkdirSync(path.join(installDir, 'log'), { recursive: true });
fs.appendFileSync(path.join(installDir, 'log', 'vdt.log'), `ran: ${args.join(' ')}\n`);

const banner = () => console.log('VMware Cloud Foundation Download Tool (fake)\n');
const table = (header, rows) => {
  console.log('-'.repeat(40));
  console.log(header.join(' | '));
  console.log('-'.repeat(40));
  for (const r of rows) console.log(r.join(' | '));
  console.log('-'.repeat(40));
  console.log(`${rows.length} elements`);
};

const ROWS = [
  ['id-vc-1', 'VCENTER', 'VMware vCenter', '9.1.0.0.25000001', 'INSTALL', '2026-05-01', '1.0 KiB'],
  ['id-sddc-1', 'SDDC_MANAGER_VCF', 'SDDC Manager', '9.1.0.0.25000002', 'INSTALL', '2026-05-01', '2.0 KiB'],
];

if (args[0] === '--version') {
  console.log('Version: 9.1.1.0.25999999');
  process.exit(0);
}

if (args[0] === 'configuration' && args[1] === 'generate') {
  const id = crypto.randomUUID();
  const xdg = process.env.XDG_DATA_HOME;
  const f = path.join(xdg, 'vmware', 'vdt', 'machine_id');
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, id + '\n');
  console.log(`Use this link to register: https://vcf.broadcom.com/vcf/clm/download-manager/register?serviceId=${id}`);
  process.exit(0);
}

const tokenFile = opt('depot-download-activation-code-file');
if (tokenFile && !fs.existsSync(tokenFile)) {
  console.error(`ERROR: activation code file not found: ${tokenFile}`);
  process.exit(2);
}

if (args[0] === 'binaries' && args[1] === 'list') {
  banner();
  const comp = opt('component');
  table(
    ['ID', 'Component', 'Component Full Name', 'Version', 'Type', 'Release Date', 'Size'],
    ROWS.filter((r) => !comp || r[1] === comp)
  );
  process.exit(0);
}

if (args[0] === 'binaries' && args[1] === 'download') {
  banner();
  const depot = opt('depot-store');
  const ids = (opt('id') || '').split(',');
  const done = [];
  for (const row of ROWS.filter((r) => ids.includes(r[0]))) {
    const dir = path.join(depot, 'PROD', 'COMP', row[1]);
    fs.mkdirSync(dir, { recursive: true });
    const file = `${row[1]}-${row[3]}.${row[1] === 'VCENTER' ? 'iso' : 'tgz'}`;
    fs.writeFileSync(path.join(dir, file), Buffer.alloc(1024));
    console.log(`Download Progress of : ${file} : 0.001 MB`);
    done.push([row[1], row[2], row[3], row[4], 'SUCCESS']);
  }
  console.log('Binary Download Summary');
  table(['Component', 'Component Full Name', 'Version', 'Image Type', 'Status'], done);
  process.exit(0);
}

console.error(`ERROR: fake CLI does not know: ${args.join(' ')}`);
process.exit(1);

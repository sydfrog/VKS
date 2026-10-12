const fs = require('fs');
const path = require('path');
const { spawn, execFileSync } = require('child_process');

// Everything that differs between the original Linux container and a plain
// Windows desktop lives here, so the rest of the server can stay as close to
// upstream (leaha00/vcf-download-tool-gui) as possible.

const IS_WIN = process.platform === 'win32';

// Broadcom ships both launchers in the same tar.gz: bin/vcf-download-tool
// (bash, uses the bundled Linux JRE under jre/lin64) and
// bin/vcf-download-tool.bat (uses the bundled Windows JRE under jre/win32).
const CLI_LAUNCHER_NAME = IS_WIN ? 'vcf-download-tool.bat' : 'vcf-download-tool';

// --- Argument quoting for cmd.exe ----------------------------------------
//
// Node refuses to spawn a .bat directly without a shell (CVE-2024-27980), so
// on Windows every CLI invocation goes through `cmd.exe /d /s /c "..."`, and
// we build that command line ourselves rather than trusting shell: true.
//
// Every argument is wrapped in double quotes. Inside quotes cmd.exe treats
// & | < > ^ ( ) and spaces literally, which covers every path a user is
// realistically going to pick. What quotes can't protect against:
//   "  ends the quoted section early
//   %  expanded as an environment variable (%PATH% etc.)
//   !  expanded if Broadcom's .bat enables delayed expansion
//   CR/LF/NUL  terminate the command
// Those are refused outright. They can only ever come from a depot path or a
// query parameter, and failing loudly beats running a mangled command.
const UNSAFE_ARG_RE = /["%!\r\n\0]/;

class UnsafeArgumentError extends Error {}

function quoteCmdArg(arg) {
  const s = String(arg);
  if (UNSAFE_ARG_RE.test(s)) {
    throw new UnsafeArgumentError(
      `Refusing to pass an argument containing " % ! or a line break to the CLI on Windows: ${s}`
    );
  }
  // Backslashes immediately before the closing quote would escape it for
  // the Java launcher's argument parser ("C:\depot\" -> C:\depot"), so
  // double any trailing run of them.
  return `"${s.replace(/(\\+)$/, '$1$1')}"`;
}

// Generated launcher scripts don't always cope with a space in their own
// install path (%~dp0 unquoted somewhere). When the CLI lives under such a
// path (e.g. C:\Users\Jane Smith\AppData\...), call it via its 8.3 short
// name instead, if the volume has short names enabled. Cached per path.
const shortPathCache = new Map();
function shortPath(p) {
  if (!IS_WIN || !/\s/.test(p)) return p;
  if (shortPathCache.has(p)) return shortPathCache.get(p);
  let result = p;
  try {
    const out = execFileSync(
      process.env.ComSpec || 'cmd.exe',
      ['/d', '/s', '/c', `"for %I in (${quoteCmdArg(p)}) do @echo %~sI"`],
      { windowsVerbatimArguments: true, encoding: 'utf8', timeout: 10000 }
    ).trim();
    if (out && fs.existsSync(out)) result = out;
  } catch (err) {
    // short names disabled on this volume - fall back to the long path
  }
  shortPathCache.set(p, result);
  return result;
}

// Every live CLI child, so a console-window close or an in-app restart can
// take running downloads (and the JVM under cmd.exe) down with it instead of
// leaving orphaned java.exe processes writing into the depot.
const liveChildren = new Set();

// Drop-in for spawn(launcherPath, args, opts) that also works for a .bat.
function spawnLauncher(launcherPath, args, opts = {}) {
  let child;
  if (IS_WIN && /\.(bat|cmd)$/i.test(launcherPath)) {
    const line = [quoteCmdArg(shortPath(launcherPath)), ...args.map(quoteCmdArg)].join(' ');
    child = spawn(process.env.ComSpec || 'cmd.exe', ['/d', '/s', '/c', `"${line}"`], {
      ...opts,
      windowsVerbatimArguments: true,
      windowsHide: true,
    });
  } else {
    child = spawn(launcherPath, args, { ...opts, windowsHide: true });
  }
  liveChildren.add(child);
  child.on('close', () => liveChildren.delete(child));
  child.on('error', () => liveChildren.delete(child));
  return child;
}

// child.kill() on Windows only terminates cmd.exe - the JVM it started keeps
// running. taskkill /T takes the whole tree down.
function killTree(child) {
  if (!child || child.exitCode !== null || child.pid === undefined) return;
  if (IS_WIN) {
    try {
      execFileSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
    } catch (err) {
      // already gone
    }
    return;
  }
  try {
    child.kill('SIGKILL');
  } catch (err) {
    // already gone
  }
}

function killAllChildren() {
  for (const child of liveChildren) killTree(child);
}

// Windows 10 1803+ ships bsdtar as C:\Windows\System32\tar.exe, which reads
// .tar.gz natively. Use it by absolute path so a GNU tar from Git Bash or
// Cygwin on PATH (which misreads "C:\..." as a remote host) never wins.
function tarBin() {
  if (!IS_WIN) return 'tar';
  const sys = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'tar.exe');
  return fs.existsSync(sys) ? sys : 'tar';
}

// Path containment check that respects Windows' case-insensitive
// filesystem (realpath can hand back C:\ where the config said c:\).
function isWithin(root, candidate) {
  const norm = (p) => (IS_WIN ? path.resolve(p).toLowerCase() : path.resolve(p));
  const r = norm(root);
  const c = norm(candidate);
  return c === r || c.startsWith(r.endsWith(path.sep) ? r : r + path.sep);
}

module.exports = {
  IS_WIN,
  CLI_LAUNCHER_NAME,
  UnsafeArgumentError,
  quoteCmdArg,
  spawnLauncher,
  killTree,
  killAllChildren,
  tarBin,
  isWithin,
};

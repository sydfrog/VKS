const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { IS_WIN, killAllChildren } = require('./platform');

// Desktop-app plumbing the container never needed: opening a window,
// relaunching after a settings change, and making sure closing the console
// doesn't leave a JVM downloading in the background.

function edgePath() {
  const roots = [process.env['ProgramFiles(x86)'], process.env.ProgramFiles, process.env.LOCALAPPDATA].filter(Boolean);
  for (const root of roots) {
    const p = path.join(root, 'Microsoft', 'Edge', 'Application', 'msedge.exe');
    if (fs.existsSync(p)) return p;
  }
  return null;
}

// 'app' opens a chromeless Edge window (every Windows 10/11 box has Edge),
// which feels like a normal desktop application; anything else falls back
// to the default browser.
function openUi(url, mode) {
  if (mode === 'none') return;
  try {
    if (IS_WIN) {
      const edge = mode === 'app' ? edgePath() : null;
      if (edge) {
        spawn(edge, [`--app=${url}`, '--new-window'], { detached: true, stdio: 'ignore' }).unref();
      } else {
        spawn(process.env.ComSpec || 'cmd.exe', ['/d', '/s', '/c', `"start "" "${url}""`], {
          detached: true,
          stdio: 'ignore',
          windowsHide: true,
          windowsVerbatimArguments: true,
        }).unref();
      }
    } else if (process.platform === 'darwin') {
      spawn('open', [url], { detached: true, stdio: 'ignore' }).unref();
    } else {
      spawn('xdg-open', [url], { detached: true, stdio: 'ignore' }).on('error', () => {}).unref();
    }
  } catch (err) {
    console.log(`Open ${url} in your browser.`);
  }
}

function isSea() {
  try {
    return require('node:sea').isSea();
  } catch (err) {
    return false;
  }
}

// Re-run ourselves (the packaged .exe, or node + script in dev) in a fresh
// console window, then exit. The new instance waits for this one to free
// the port (see index.js listen retry).
function relaunch() {
  // argv[1] is the script in dev and a copy of the exe path in a packaged
  // build; user flags start at argv[2] either way.
  const userArgs = process.argv.slice(2).filter((a) => a !== '--restarted' && a !== '--no-open');
  const args = isSea() ? [] : [...process.execArgv, process.argv[1]];
  args.push(...userArgs, '--restarted', '--no-open');
  if (IS_WIN) {
    const quote = (a) => `"${String(a).replace(/"/g, '')}"`;
    const line = ['start', '"VCF Download Tool GUI"', quote(process.execPath), ...args.map(quote)].join(' ');
    spawn(process.env.ComSpec || 'cmd.exe', ['/d', '/s', '/c', `"${line}"`], {
      detached: true,
      stdio: 'ignore',
      windowsVerbatimArguments: true,
      windowsHide: true,
    }).unref();
  } else {
    spawn(process.execPath, args, { detached: true, stdio: 'inherit' }).unref();
  }
  shutdown(0);
}

let shuttingDown = false;
function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  killAllChildren();
  // Give the job store a tick to flush, then go.
  setTimeout(() => process.exit(code), 300);
}

// Closing the console window sends SIGHUP on Windows (with ~5s grace),
// Ctrl+C sends SIGINT. Either way, stop any running CLI first.
function installSignalHandlers() {
  for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGBREAK']) {
    try {
      process.on(sig, () => shutdown(0));
    } catch (err) {
      // signal not supported on this platform
    }
  }
}

// Mirror console output to a log file so there's something to look at
// after the console window is gone.
function teeConsoleToFile(file) {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    try {
      if (fs.statSync(file).size > 5 * 1024 * 1024) fs.renameSync(file, `${file}.1`);
    } catch (err) {
      // no previous log
    }
    const stream = fs.createWriteStream(file, { flags: 'a' });
    stream.on('error', () => {});
    for (const level of ['log', 'warn', 'error']) {
      const orig = console[level].bind(console);
      console[level] = (...args) => {
        orig(...args);
        stream.write(`${new Date().toISOString()} ${args.map(String).join(' ')}\n`);
      };
    }
  } catch (err) {
    // logging is best-effort
  }
}

module.exports = { isSea, openUi, relaunch, shutdown, installSignalHandlers, teeConsoleToFile };

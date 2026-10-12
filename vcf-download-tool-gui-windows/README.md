# VCF Download Tool GUI for Windows

A native Windows build of [leaha00/vcf-download-tool-gui](https://github.com/leaha00/vcf-download-tool-gui),
the web GUI for Broadcom's `vcf-download-tool`. It does the same job without
Docker or WSL. It's a single `.exe`: double-click it and the GUI opens in its
own window.

The features are the same as the Docker version: browse releases, list and
download binaries, download OCI artifacts on CLI 9.1.1+, generate a depot ID,
upload or upgrade the CLI from the UI, see downloaded state, delete files,
view download history and logs, change colours, and schedule refreshes.
All credit for the app goes to the original author. This folder only ports
it to Windows.

## Why this works without Docker

Broadcom's `vcf-download-tool` tar.gz is the same file for every platform.
It includes `bin\vcf-download-tool.bat` and its own Windows Java runtime
(`jre\win32`), and Broadcom documents running it this way on Windows. The
container build only needed Docker because it uses the Linux launcher. This
build calls the `.bat` instead, so nothing else needs to be installed: no
Java, no Node.js, no Docker.

## Using it

1. **Get the exe.** Download `VCF-Download-Tool-GUI.exe` from the latest run
   of the *VCF Download Tool GUI (Windows)* GitHub Actions workflow
   (Actions tab → latest run → Artifacts), or [build it yourself](#building).
2. **Run it.** Double-click `VCF-Download-Tool-GUI.exe`. A console window
   shows where everything lives, and the GUI opens in an Edge app window.
   - Windows SmartScreen will warn because the exe is unsigned. Choose
     *More info → Run anyway*.
   - **Leave the console window open.** Closing it stops the app and any
     download that's running. Running the exe again while the app is already
     open just brings the window back.
3. **Settings → Application.** Pick your **Depot folder**, which is where
   downloads go. It can be a local folder (`D:\vcf-depot`), a mapped drive,
   or a UNC share (`\\fileserver\share\vcf-depot`). This setting replaces the
   `vcf-depot` volume. Save, then let the app restart.
4. **Settings → Upload CLI.** Upload the `vcf-download-tool-*.tar.gz` from
   the Broadcom portal. Don't extract it first.
5. **Software depot ID** and **activation code**: set these up the same way
   as in the [original README](https://github.com/leaha00/vcf-download-tool-gui#first-time-setup).

After that, everything works as it does in the Docker version.

## Where things are stored

| What | Docker version | Windows version |
|---|---|---|
| Activation code, depot ID, CLI, job history, download logs | `vcf-token` volume (`/data/token`) | `%LOCALAPPDATA%\VCF-Download-Tool-GUI\data` |
| Downloaded binaries | `vcf-depot` volume (`/mnt/vcf-depot`) | Settings → Application → Depot folder (default `%USERPROFILE%\vcf-depot`) |
| Port, Java heap, etc. | `docker-compose.yml` environment | Settings → Application, saved to `%LOCALAPPDATA%\VCF-Download-Tool-GUI\settings.json` |
| App log | `docker logs` | `%LOCALAPPDATA%\VCF-Download-Tool-GUI\logs\app.log` |

You can still set environment variables, and they take priority over
`settings.json`: `DEPOT_DIR`, `TOKEN_DIR`, `PORT`, `LISTEN_HOST`,
`CLI_JAVA_TOOL_OPTIONS`, `INTERNAL_PORT`. `VCFGUI_HOME` moves the whole app
folder, which is useful for running it from a USB stick.

## Differences from the Docker version

- **Only this PC can open the GUI by default.** The app listens on
  `127.0.0.1`. To let other computers use it, tick *Let other computers on
  the network open this GUI* in Settings. There is still no login, so only do
  this on a trusted network. To block other websites in your browser from
  using the local API, the app also rejects requests that have an unexpected
  `Host` header or are missing its own request header.
- **No Java heap cap by default.** The container set `-Xmx768m` to fit its
  1 GB limit. A desktop has no such limit, so the JVM default is used. If a
  newer CLI runs out of memory, set *CLI Java options* to something like
  `-Xmx2g`.
- **Resource Usage** shows the whole PC's CPU and memory instead of the
  container's cgroup.
- The **internal depot API** for the companion `vcf-web-depot` container is
  off by default. To turn it on, set `"internalPort": 10080` in
  `settings.json`.
- **Unsupported characters in paths:** depot folder and data paths can't
  contain `"`, `%` or `!`. The CLI is a `.bat`, so every argument passes
  through `cmd.exe`, and those characters can't be passed through it safely.
  Spaces, `&`, and brackets are fine.

## Proxies and TLS inspection

These work the same as with the CLI on its own. If your network intercepts
TLS, import the proxy's CA into the CLI's Java truststore
(`%LOCALAPPDATA%\VCF-Download-Tool-GUI\data\cli\jre\win32\lib\security\cacerts`)
as described in Broadcom's VCFDT documentation. Re-uploading the CLI replaces
that folder, so do the import again after an upgrade.

## Building

You need Node.js 20 or later. The build works on Windows or Linux:

```powershell
cd vcf-download-tool-gui-windows
npm install
npm run build          # -> dist\VCF-Download-Tool-GUI.exe
npm test               # end-to-end smoke test against a fake CLI
```

The build bundles the server with esbuild, embeds the web UI, and injects
both into an official `node.exe` using Node's
[single executable application](https://nodejs.org/api/single-executable-applications.html)
support. On Linux, it downloads the matching `node.exe` from nodejs.org and
checks its SHA-256. To run from source instead, use `npm start`.

The GitHub Actions workflow
(`.github/workflows/vcf-download-tool-gui-windows.yml`) runs on
`windows-latest`. It runs the smoke test against the source and against the
built exe, then publishes the exe as an artifact. The smoke test uses a fake
CLI with a real `.bat` launcher and a depot path containing spaces, brackets
and `&`. It checks upload/extract, version detection, depot ID, release
discovery, listing, downloading, the downloaded state, deleting, logs, and
that `cmd.exe` metacharacters in input are rejected rather than executed.

## Code layout

The `server/` folder is upstream v1.5.1 with Windows changes in these places:

- `server/lib/platform.js` *(new)*: launches the `.bat` through `cmd.exe`
  with safe quoting, kills process trees, finds the system `tar.exe`, and
  checks path containment without case sensitivity.
- `server/lib/appSettings.js`, `server/lib/lifecycle.js` *(new)*:
  `settings.json`, opening the window, single-instance handling, restart,
  and stopping running downloads on exit.
- `config.js`, `cliRunner.js`, `cliInstall.js`, `cliLogs.js`,
  `depotServe.js`, `depotId.js`, `systemStats.js`, `index.js`, `routes.js`:
  small edits to use the above.
- `public/`: the *Application* settings section, the `X-VCF-GUI` request
  header, and wording changes from container to PC.

The Broadcom CLI is not included in any form, the same as upstream.

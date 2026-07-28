# VCF Depot Manager — Orchestration File

> **Status:** Draft for review. Nothing has been built.
> **Purpose:** Single source of truth for what we are building, what is still undecided,
> and what I need from you before any code is written.
> **How to use this:** Read top to bottom. Every `▢ DECISION` block needs an answer
> (or a "go with the recommendation"). Every `▢ NEED` block is something only you can
> supply. Edit this file directly — your edits are the spec.

---

## 1. What this is

A web application, hosted on a Linux server on your network, that turns the
**VCF Download Tool (VCDT)** from a command-line exercise into a managed local
depot with a UI.

Two halves, in order of the user journey:

1. **Choose** — browse what Broadcom's depot offers, tick the releases and
   components you actually want, and queue the download.
2. **Inspect** — see everything that has landed on disk: every file, its size,
   its checksum status, which release it belongs to, when it arrived.

Everything else in this document is in service of those two sentences.

---

## 2. Glossary (so we mean the same things)

| Term | Meaning here |
|---|---|
| **VCDT** | VMware Cloud Foundation Download Tool — the Broadcom-supplied CLI that authenticates to the Broadcom depot and pulls binaries down. The thing this app drives. |
| **Depot** | The on-disk tree VCDT writes into. The "local download repository" of your request. |
| **Catalog / manifest** | The upstream index of what is available to download (releases, components, bundles, sizes, checksums). |
| **Bundle** | A downloadable unit — an ESX install image, a vCenter patch, a Supervisor service, an add-on, etc. |
| **Job** | One invocation of VCDT for a selected set of bundles, with progress and a terminal outcome. |
| **Offline depot serving** | Exposing the local depot over HTTP(S) so SDDC Manager / VCF Installer can consume it as an upstream. Optional — see §4.1. |

---

## 3. What I need from you

These are hard blockers. I cannot write the VCDT integration without them.

### ▢ NEED 3.1 — The VCDT binary or image

You said you can provide the latest VCDT. Please drop it (or tell me the exact
version string and where it lives on the server) so I can pin the adapter to a
real CLI rather than a guessed one.

### ▢ NEED 3.2 — VCDT's actual command surface

Paste the output of the tool's own help. Specifically I need:

```
<vcdt> --version
<vcdt> --help
<vcdt> <list-ish subcommand> --help      # whatever enumerates available content
<vcdt> <download subcommand> --help      # whatever performs a download
```

### ▢ NEED 3.3 — One real sample of each output

- A catalog/list output (JSON if it can emit JSON — `--output json` or similar).
- ~40 lines of a download in progress, so I can see exactly how it reports
  percentage / bytes / current file. **This determines whether the progress bar
  is real or a spinner.** See Risk R1.
- The tail of a successful run, and the tail of a failed run (bad token,
  network drop, disk full — whichever you can produce).

### ▢ NEED 3.4 — Depot layout

`tree -L 3` (or `find . -maxdepth 3`) of an existing depot directory, plus
whether VCDT writes a manifest/index file alongside the binaries. If it does,
that file is our best inventory source and changes §6 substantially.

### ▢ NEED 3.5 — Credentials shape

What does VCDT authenticate with — a Broadcom portal token, a downloaded
`.json` credentials file, username+password, or an entitlement/site ID? I need
the shape, not the value. Do **not** paste the actual secret into this file or
into chat; §9 covers how it gets stored.

### ▢ NEED 3.6 — The server

- Distro + version, and CPU arch.
- Mount point and free space for the depot. VCF release trains are large —
  a single full release can run into the hundreds of GB, so retention (§4.3)
  matters more than it might seem.
- Does the box have direct outbound HTTPS to the Broadcom depot, or is there a
  proxy in the path? If a proxy: does VCDT honour `HTTPS_PROXY`, or does it
  need its own flag?

---

## 4. Decision points

Each has a recommendation. If the recommendation is right, write "yes" and move on.

### ▢ DECISION 4.1 — Scope

Which of these are in v1?

| # | Capability | Recommendation |
|---|---|---|
| A | **Download orchestration** — browse catalog, select, queue, run, live progress, retry | **In v1.** This is the core ask. |
| B | **Inventory & detail** — every file on disk, size, date, parent release, drill-down | **In v1.** This is the other half of the core ask. |
| C | **Serve as offline depot** — nginx/static serving so SDDC Manager can point at this host | **v1.1.** Small once B exists, but it's a separate concern and a separate security posture. |
| D | **Storage lifecycle** — disk dashboards, prune old bundles, retention rules, orphan detection | **v1.1**, except a plain "free space" readout which is v1 and trivial. |
| E | **Verification** — checksum/signature validation, "have vs. offered" diff, exportable listings | **Checksum verify + have/offered diff in v1**; export in v1.1. Verification is what makes the inventory trustworthy rather than decorative. |

My default if you say nothing: **A + B + checksum verify + have/offered diff.**

### ▢ DECISION 4.2 — Where VCDT runs

| Option | Trade-off |
|---|---|
| **Local binary on the same host** ⭐ | App shells out to a subprocess. Fewest moving parts, easiest to debug, direct filesystem access for the inventory scanner. |
| Container per job | Cleaner isolation and version pinning; adds a runtime dependency and volume plumbing, and complicates progress capture. |
| Remote host over SSH | Only justified if the depot must live on separate storage. Adds key management and makes the inventory scanner remote too. |

**Recommendation: local binary, same host.** Move to containers only if you want
to run several VCDT versions side by side. Note the adapter (§7.2) is written so
this can change later without touching the UI.

### ▢ DECISION 4.3 — Authentication

| Option | Trade-off |
|---|---|
| **Single admin user + root-only secrets file** ⭐ | One login. Broadcom credential in a `0600` file or systemd credential, never in the database, never rendered back to the browser. Right-sized for a lab or a single-operator setup. |
| Multi-user with roles | Viewer vs. operator, per-user audit. Worth it only if other people will touch this. |
| No auth, trusted LAN | Don't. This app holds a credential that can pull licensed binaries and it can fill a disk. Even on a flat home network, one login is cheap. |
| SSO / OIDC / LDAP | Correct if this sits next to other managed infrastructure. Materially more work. |

**Recommendation: single admin user + secrets file, with the design leaving room
for roles later.** Tell me if more than one person operates this.

### ▢ DECISION 4.4 — Stack

| Option | Trade-off |
|---|---|
| **Python + FastAPI** ⭐ | Best fit: the job runner is mostly "supervise a subprocess and stream its stdout", which Python does cleanly with asyncio. Server-rendered templates + WebSocket for live progress means no separate frontend build. SQLite for state. systemd unit behind nginx. |
| Node + React | Richer UI ceiling; a build pipeline to maintain on a server whose job is storing files. |
| Go single binary | Nicest deploy story — one static binary, embedded assets, no runtime drift. Slower to iterate on the UI. |

**Recommendation: Python + FastAPI + SQLite + server-rendered UI with HTMX,
WebSocket for progress, systemd + nginx.** If you'd rather have a single binary
to drop on the box, say so and I'll write it in Go instead — the architecture
below is language-agnostic.

### ▢ DECISION 4.8 — How the app is packaged and run

Independent of 4.2. **4.2 is "where does VCDT run"; this is "how does the app
itself get deployed".** Either answer gives you the same thing in the browser —
a web server on this host that you reach at e.g. `https://depot.lab.local`.

| Option | Trade-off |
|---|---|
| **Docker Compose** ⭐ | Two services: `app` and `nginx`. Depot bind-mounted in, SQLite on a named volume, TLS certs mounted read-only. Clean install and clean uninstall, no Python on the host, trivially reproducible. |
| systemd unit on the host | Fewer layers, direct filesystem access, nothing to rebuild. Requires the right Python on the box and drifts as the distro upgrades. |
| Single Go binary + systemd | Only if 4.4 lands on Go. Copy one file, no runtime at all. |

**If you go with containers, bind-mount VCDT from the host rather than baking it
into the image** — `/opt/vcdt:/opt/vcdt:ro`. Broadcom updates VCDT on their
schedule; you shouldn't have to rebuild an image to take a new version, and
`version_pin` in §11 then reflects what's actually mounted.

Two consequences to be aware of either way:

- **The depot bind mount must be the real depot path**, and the container user's
  UID needs write access to it. Mismatched UIDs on a bind mount is the most
  common way this setup fails on first run.
- **Free-space reporting reads the host mount**, not the container's overlay
  filesystem. The scanner must `statvfs` the depot path specifically, or the
  dashboard will confidently report the wrong number.

**Recommendation: Docker Compose, VCDT bind-mounted from the host.** It matches
how you'd likely run other infrastructure tooling, and it makes the "wipe it and
start again" path painless while we iterate.

### ▢ DECISION 4.5 — Catalog freshness

Does the UI's "what can I download" list come from:

- **(a)** a live VCDT catalog call each time you open the page (accurate, slow, needs the token to be valid at page load), or
- **(b)** a cached catalog snapshot refreshed on demand and on a schedule ⭐

**Recommendation: (b)**, with a visible "catalog last refreshed *N* hours ago"
stamp and a manual refresh button. Live calls make the UI feel broken whenever
the depot is slow.

### ▢ DECISION 4.6 — Concurrency

One download job at a time, or several in parallel?

**Recommendation: a serialised queue, depth-1 by default, configurable.**
Parallel downloads of very large files usually make total wall-clock time worse,
not better, and they make disk-full failures much messier to unwind. The queue
model also gives you "select five releases, walk away" for free.

### ▢ DECISION 4.7 — Selection granularity

When you pick things to download, is the unit:

- release only ("VCF 9.0.2, everything"), or
- **release → component → individual bundle**, with a parent checkbox that
  selects all children ⭐

**Recommendation: the tree.** Your compatibility page already thinks in terms of
VCF ↔ Supervisor ↔ VKS component versions, so the selector should match how you
already reason about it. Depends on VCDT exposing that granularity — NEED 3.3
will confirm.

---

## 5. Architecture

```
                        browser
                           │  HTTPS
                    ┌──────▼───────┐
                    │    nginx     │  TLS, static assets, optional depot serving
                    └──────┬───────┘
                           │
      ┌────────────────────▼─────────────────────┐
      │            app (FastAPI)                 │
      │                                          │
      │  ┌────────────┐   ┌──────────────────┐   │
      │  │  Web /API  │   │  WebSocket hub   │   │  live job progress
      │  └─────┬──────┘   └────────▲─────────┘   │
      │        │                   │             │
      │  ┌─────▼───────────────────┴─────────┐   │
      │  │          Job queue + runner       │   │  serialised, depth-1
      │  └─────┬───────────────────┬─────────┘   │
      │        │                   │             │
      │  ┌─────▼──────┐    ┌───────▼──────────┐  │
      │  │ VCDT       │    │ Inventory        │  │
      │  │ adapter    │    │ scanner          │  │
      │  └─────┬──────┘    └───────┬──────────┘  │
      └────────┼───────────────────┼─────────────┘
               │ subprocess        │ read-only walk
        ┌──────▼──────┐     ┌──────▼──────────┐
        │    VCDT     │────▶│  depot on disk  │
        └──────┬──────┘     └─────────────────┘
               │ HTTPS
        ┌──────▼──────────┐        ┌──────────────┐
        │ Broadcom depot  │        │   SQLite     │  catalog cache, jobs,
        └─────────────────┘        └──────────────┘  file index, audit log
```

**The load-bearing idea:** the app never parses Broadcom's depot protocol itself
and never writes into the depot tree. VCDT owns the network and the writes; the
app owns selection, scheduling, observation, and presentation. That boundary is
what keeps this maintainable when VCDT changes.

---

## 6. Data model (SQLite)

```
catalog_release      id, product, version, release_date, notes_url,
                     first_seen, last_seen_in_catalog
catalog_component    id, release_id→, name, kind, version
catalog_bundle       id, component_id→, vcdt_ref, filename, size_bytes,
                     checksum, checksum_algo, is_mandatory
                     -- vcdt_ref is whatever opaque handle VCDT wants back
                     -- to download this thing. Shape TBD by NEED 3.3.

job                  id, state, created_at, started_at, finished_at,
                     requested_by, exit_code, error_summary
job_item             id, job_id→, bundle_id→, state, bytes_expected,
                     bytes_done, error
job_log              id, job_id→, ts, stream, line     -- raw VCDT output

depot_file           id, rel_path, size_bytes, mtime, sha_observed,
                     bundle_id→ (nullable), verify_state, last_scanned
                     -- nullable bundle_id is deliberate: files that map to
                     -- nothing in the catalog are the orphan report (4.1 D)

setting              key, value
audit                id, ts, actor, action, detail
```

**Job state machine:**

```
queued → running → ┬→ succeeded
                   ├→ failed      (retryable; job_items keep per-item state
                   │                so a retry only re-fetches what's missing)
                   └→ cancelled
```

`depot_file.verify_state` ∈ `unverified | ok | checksum_mismatch | size_mismatch | orphan`.

---

## 7. Components

### 7.1 Web / API layer

Thin. Validates input, writes to the queue, reads projections for display.
No business logic, no subprocess handling.

### 7.2 VCDT adapter — the critical seam

A single module, the **only** place in the codebase that knows VCDT's command
syntax and output format. It exposes exactly three operations:

```python
fetch_catalog()  -> list[Release]          # parse into our model
plan(selection)  -> list[CommandInvocation]
run(invocation)  -> stream[ProgressEvent]  # yields as VCDT emits
```

Everything above it works in our own vocabulary. When Broadcom changes a flag,
one file changes.

**Every parser in this module must degrade rather than crash.** If VCDT emits a
line we don't recognise, it goes to `job_log` verbatim and the job carries on.
The failure mode of a strict parser here is "download silently marked failed
after successfully transferring 200 GB", which is much worse than an unstyled
log line.

### 7.3 Job runner

Owns the subprocess: spawn, stream stdout/stderr line-by-line, translate to
progress events, persist, broadcast over WebSocket, reap, record outcome.
Handles cancellation (terminate → wait → kill) and survives app restart by
marking orphaned `running` jobs as `failed (interrupted)` on boot.

### 7.4 Inventory scanner

Read-only walk of the depot. Runs after every job, on a schedule, and on demand.
Reconciles disk against `catalog_bundle` to produce three answers:

- **Have** — file present, size and checksum match.
- **Missing** — catalogued, selected previously, not on disk.
- **Orphan** — on disk, matches nothing in the catalog.

Checksums are the expensive part; hash on first sight and on explicit re-verify,
not on every scan.

### 7.5 Scheduler

Catalog refresh and periodic rescan. A plain interval loop is enough — no cron
dependency.

---

## 8. UI

Five screens. Dark-first, matching the visual language of the existing
`vcf-vks-compatibility.html` so the two feel like one tool.

1. **Dashboard** — free space and depot size, current/last job, catalog age,
   verification summary (*n* verified / *m* mismatched / *k* orphans).
2. **Select & download** — the tree from §4.7. Checkboxes with parent/child
   propagation, a running "selected: 12 bundles, 214 GB" total, and a
   **projected free space after download** figure. Rows already present on disk
   are visibly marked so you don't re-queue them. Submit → job.
3. **Jobs** — queue and history. Detail view streams live progress plus the raw
   VCDT log. Cancel, and retry-failed-items-only.
4. **Repository** — the file inventory. Group by release → component → file, or
   flat and sortable. Per-file: size, mtime, checksum state, path. Filter by
   state; the orphan and mismatch filters are the useful ones.
5. **Settings** — depot path, concurrency, schedule, credential status
   (*configured / not configured / last used at* — never the value itself).

---

## 9. Security

- **The Broadcom credential never enters the database and is never rendered
  back to the browser**, not even masked. It lives in a `0600` file owned by the
  service user (or a systemd `LoadCredential`), read at spawn time, passed to
  VCDT via environment or file reference — never as an argv flag, since argv is
  world-readable in `/proc`.
- Job logs are scrubbed for anything token-shaped before being persisted.
- Depot path is confined to a configured root; every path derived from user
  input or from VCDT output is resolved and checked against that root before
  any filesystem operation. The inventory scanner does not follow symlinks out
  of the root.
- The app runs as a dedicated unprivileged user, with systemd hardening
  (`ProtectSystem=strict`, `ReadWritePaths=<depot>`, `NoNewPrivileges`,
  `PrivateTmp`).
- nginx terminates TLS. If §4.1 C lands, depot serving is a **separate**
  read-only vhost/location — no auth needed by SDDC Manager, no write path, and
  no overlap with the control UI's session.
- Audit table records who queued, cancelled, or deleted what.

---

## 10. Deployment

Shape depends on **DECISION 4.8**. Under either answer you get the same thing
from a browser: a web server on this host, TLS-terminated by nginx.

**If Docker Compose (recommended):**

```yaml
services:
  app:                    # FastAPI + job runner + scanner
    volumes:
      - /srv/vcf-depot:/srv/vcf-depot      # the depot, read-write
      - /opt/vcdt:/opt/vcdt:ro             # vendor binary, host-owned
      - state:/var/lib/vcf-depot           # SQLite
      - /etc/vcf-depot:/etc/vcf-depot:ro   # config + credential, 0600 on host
    user: "<uid>:<gid>"                    # must match depot ownership
  nginx:
    ports: ["443:443"]
    volumes:
      - certs:/etc/nginx/certs:ro
```

**If systemd:** unit for the app, nginx in front, hardening flags per §9.

**Common to both:**

- Depot on its own mount if possible — a full disk should degrade downloads,
  not take out the OS.
- SQLite in WAL mode, and **not** on the depot mount.
- Backup: the SQLite file (small, and the only irreplaceable state). The depot
  itself is re-downloadable.
- Config: one YAML file, environment-overridable. Draft in §11.
- The container does not need `--privileged`, host networking, or the Docker
  socket. If a future change appears to need any of those, that's a design
  error worth raising rather than granting.

---

## 11. Draft configuration file

Illustrative — the keys marked `# TBD` firm up once NEED 3.2 lands.

```yaml
app:
  bind: "127.0.0.1:8080"
  base_url: "https://depot.lab.local"
  session_secret_file: "/etc/vcf-depot/session.key"

auth:
  mode: single_user            # single_user | multi_user | oidc
  username: "admin"
  password_hash_file: "/etc/vcf-depot/admin.hash"

vcdt:
  mode: local                  # local | container | ssh
  binary: "/opt/vcdt/vcf-download-tool"
  version_pin: ""              # TBD — filled from NEED 3.1
  credential_file: "/etc/vcf-depot/broadcom.cred"   # 0600, never read by UI
  extra_args: []
  proxy: ""                    # empty = inherit HTTPS_PROXY
  catalog_command: []          # TBD — NEED 3.2
  download_command: []         # TBD — NEED 3.2
  progress_parser: "auto"      # auto | regex:<pattern> | json | none

depot:
  root: "/srv/vcf-depot"
  min_free_gb: 100             # refuse to queue below this
  follow_symlinks: false

jobs:
  max_concurrent: 1
  retry_attempts: 2
  retry_backoff_seconds: 30
  log_retention_days: 90

scan:
  after_every_job: true
  interval_minutes: 360
  checksum_policy: on_first_sight   # on_first_sight | always | never

catalog:
  refresh_interval_hours: 12
  stale_warning_hours: 48

serving:
  enabled: false               # DECISION 4.1 C
  path_prefix: "/depot"
```

---

## 12. Build order

| Phase | Deliverable | Depends on |
|---|---|---|
| 0 | Repo skeleton, config loader, systemd unit, "it starts and serves a page" | 4.4 |
| 1 | **VCDT adapter + a `--dry-run` CLI that prints the parsed catalog** — proves the integration before any UI exists | 3.1–3.3 |
| 2 | Catalog cache, selection tree UI, size/space projection | 1, 4.5, 4.7 |
| 3 | Job queue, runner, live progress over WebSocket, job history | 2, 4.6 |
| 4 | Inventory scanner, repository screen, have/missing/orphan reconciliation | 3, 3.4 |
| 5 | Checksum verification, mismatch reporting | 4 |
| 6 | Auth, hardening, audit | 4.3 |
| 7 | *(v1.1)* Depot serving, retention/prune, export | 4.1 C+D |

Phase 1 is the one that can invalidate assumptions. Nothing else should start
until a real catalog parses.

---

## 13. Risks

| # | Risk | Mitigation |
|---|---|---|
| **R1** | **VCDT reports progress in a form we can't parse** — no machine-readable output, or a redrawing TTY progress bar that produces unusable output when not attached to a terminal. This is the single most likely thing to make the UI worse than planned. | NEED 3.3 answers it before we commit. Fallbacks, in order: run under a pseudo-terminal to coax the interactive renderer; derive progress from watching file sizes in the depot; degrade to "running, *N* minutes elapsed, *X* GB written" with the raw log visible. Plan for the fallback; be pleased if we don't need it. |
| R2 | Catalog granularity is coarser than §4.7 assumes | Selector collapses to whatever level VCDT exposes. UI copes; the model already allows a release with one implicit bundle. |
| R3 | Long downloads outlive sessions, proxies, or the app process | Job state lives in SQLite, not memory; runner is a subprocess whose output is persisted as it arrives; interrupted jobs are detected on boot and are resumable per-item. |
| R4 | Disk fills mid-job | `min_free_gb` pre-flight check at queue time, projected-usage figure at selection time, and a runtime abort with a clear message rather than a truncated file. |
| R5 | Credential expires or is revoked; every job fails identically | Adapter classifies auth failures distinctly from transfer failures and surfaces "credential rejected" on the dashboard rather than *n* identical red rows. |
| R6 | VCDT version changes flags between releases | Single adapter module (§7.2), `version_pin` recorded in config and stamped onto every job so a behaviour change is traceable. |
| R7 | Broadcom's terms on redistribution if §4.1 C is enabled | Depot serving stays on the internal network. Worth your own check before enabling — I'll gate it behind an explicit opt-in rather than shipping it on. |

---

## 14. Explicitly out of scope for v1

Deploying or patching anything (this manages files, it does not drive SDDC
Manager); multi-depot federation or peer sync; bandwidth shaping; email/Slack
notification; anything touching vCenter or NSX APIs; mobile-specific UI.

---

## 15. Open questions summary

Copy this block, fill it in, hand it back — that's all I need to start Phase 0.

```
4.1  Scope:              A+B+verify (default)  /  also C  /  also D  /  other:
4.2  VCDT execution:     local (default)  /  container  /  ssh
4.8  App packaging:      compose (default)  /  systemd on host  /  Go binary
     ^ if compose: depot path to bind-mount = 
                   UID:GID that owns it     = 
4.3  Auth:               single user (default)  /  multi-user  /  none  /  SSO
4.4  Stack:              Python+FastAPI (default)  /  Node+React  /  Go
4.5  Catalog:            cached+refresh (default)  /  live
4.6  Concurrency:        serial queue (default)  /  parallel, N=
4.7  Selection:          bundle tree (default)  /  release only

3.1  VCDT version/path:
3.5  Credential shape:
3.6  Distro / arch / depot mount / free space:
3.6  Proxy in path?      yes/no  —  honours HTTPS_PROXY?
```

Attachments needed: `--help` output (3.2), sample catalog + progress + failure
output (3.3), depot `tree -L 3` (3.4).

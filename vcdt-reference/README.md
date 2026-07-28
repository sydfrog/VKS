# VCDT reference capture

Drop point for the VCDT information needed to build the depot manager
(see `../ORCHESTRATION.md` §3, needs 3.1–3.4).

## Do not put here

- **The VCDT binary, image tarball, or any vendor archive.** Licensed, large,
  and unusable from my side — I have no Broadcom entitlement and no route to
  the depot, so I can't run it regardless. `.gitignore` blocks these.
- **Credentials of any kind** — tokens, credential files, entitlement or site
  IDs, portal passwords. I never need the value. §9 of the orchestration file
  covers how the real credential is stored on your server.

## Do put here

Plain text only. All of it small.

| File | What it is | Orchestration ref |
|---|---|---|
| `version.txt` | `vcdt --version` | 3.1 |
| `help-root.txt` | `vcdt --help` | 3.2 |
| `help-<subcommand>.txt` | `--help` for each subcommand | 3.2 |
| `catalog-sample.txt` / `.json` | Output of whatever lists available content. JSON if the tool can emit it. | 3.3 |
| `progress-sample.txt` | ~40 lines of a download actually running | 3.3 |
| `failure-sample.txt` | Tail of a failed run — any failure will do | 3.3 |
| `depot-tree.txt` | `tree -L 3` or `find . -maxdepth 3` of an existing depot | 3.4 |
| `depot-manifest-sample.*` | Any index/manifest file VCDT writes into the depot | 3.4 |
| `env.txt` | Distro, arch, depot mount, free space, proxy in path? | 3.6 |

## No Linux machine yet?

VCFDT is a Java application with a **bundled Linux JRE**, so it needs a Linux
userspace — but not a Linux server. Any of these is enough to produce the
capture (see `../ORCHESTRATION.md` §3A):

- **Windows → WSL2.** Broadcom's supported Windows route. `wsl --install`,
  then run VCFDT inside the Linux distro. Roughly ten minutes.
- **macOS → override the bundled JRE** with a native macOS Java runtime. The
  bundled Linux one produces `Exec format error`; the tool itself is fine.
- **A small cloud VM**, or a Linux VM on any hypervisor you already have.

None of these is the eventual production host — that needs real disk for the
depot. They only need to run VCFDT long enough to capture its interface.

## Fastest path

Run `capture.sh` on the server that has VCDT:

```sh
./capture.sh /opt/vcdt/vcf-download-tool /srv/vcf-depot
```

It writes everything above into `./capture-out/`, runs a redaction pass over it,
and prints what it collected. **Read the files before you send them** — the
redaction is a safety net, not a guarantee. It cannot know what's sensitive in
output it's never seen.

`progress-sample.txt` and `failure-sample.txt` need a real download, so the
script won't produce those on its own. Capture them by hand:

```sh
vcdt <download subcommand> <args> 2>&1 | tee progress-sample.txt
```

Let it run a minute or two, then interrupt it — that's enough to see how it
reports progress, which is the single biggest open question (Risk R1).

## ⚠ This repository is public

`sydfrog/VKS` is a **public** GitHub repository. Two consequences:

**Never commit the VCDT binary here.** Publishing a licensed Broadcom binary to
a public repo is redistribution, and git retains blobs after deletion — undoing
it means rewriting history, not removing a file.

**Review capture output before committing it.** The redaction pass catches
credential-shaped patterns, but catalog and manifest output may also carry
things you'd rather not publish: entitlement or site identifiers, account
references, internal hostnames and IPs, proxy addresses, depot URLs specific to
your organisation. None of that is secret in the credential sense, and none of
it is something I need.

If in doubt, paste into chat instead of committing. Nothing here is so large
that the repo is the only viable channel.

## Getting the files to me

1. **Paste into chat.** Best default. Fine for `--help`, catalog samples and
   progress output, and nothing lands in a public repo.
2. **Commit to this branch** (`claude/vcf-download-repo-web-8etf58`) — good for
   anything we'll want to re-read across sessions, once reviewed per the note
   above.
3. **Attach the files** in the Claude interface if your client supports it.

### If you want me to have the binary itself

Understand what it buys first — less than it seems. From my side it yields
`--version`, `--help`, subcommand discovery, and static inspection of the flag
surface. It cannot yield a catalog listing, progress output, or failure
behaviour: those need authentication and a route to the Broadcom depot, and
this environment has neither (egress to Broadcom is blocked at the proxy).

That is the same information you can capture in a minute with `capture.sh`, so
it's rarely worth the trouble. If you do want it available anyway, put it in a
**separate private repository** and I can be given access to that — never here.

### The part that has to happen on your server either way

No copy of the binary lets me validate the parser against *real* catalog JSON or
*real* progress output — that data exists only on an entitled, connected host.
So Phase 1 (§12) ships as a self-testing adapter: a `selftest` command you run
on your server that exercises the parser against live VCDT and prints a
structured mismatch report. You paste the report back; I fix the parser. The
binary never leaves your network and the loop stays tight.

## Why progress output matters so much

If VCDT draws a redrawing terminal progress bar, piping it to a file gives
either nothing or a wall of escape codes — and a web UI can't show a real
progress bar from that. There are workarounds (run it under a pseudo-terminal,
or infer progress by watching file sizes land in the depot), but they're
meaningfully more code and less accurate.

So: if `progress-sample.txt` comes out empty or full of `\r` and `\033[`
sequences, that's not a broken capture — that's the answer to the question, and
worth sending exactly as-is.

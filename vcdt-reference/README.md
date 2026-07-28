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

## Getting the files to me

Any of these work:

1. **Paste into chat.** Fine for `--help` output; easiest for a quick answer on
   one specific thing.
2. **Commit them to this branch** (`claude/vcf-download-repo-web-8etf58`) from
   your machine, or add them through the GitHub web UI. Best option — they
   become part of the repo's record and I can re-read them later.
3. **Attach the files** in the Claude interface if your client supports it.

## Why progress output matters so much

If VCDT draws a redrawing terminal progress bar, piping it to a file gives
either nothing or a wall of escape codes — and a web UI can't show a real
progress bar from that. There are workarounds (run it under a pseudo-terminal,
or infer progress by watching file sizes land in the depot), but they're
meaningfully more code and less accurate.

So: if `progress-sample.txt` comes out empty or full of `\r` and `\033[`
sequences, that's not a broken capture — that's the answer to the question, and
worth sending exactly as-is.

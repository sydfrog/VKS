#!/usr/bin/env bash
# Capture VCDT's interface for the depot manager build.
# Collects help text, a catalog sample, depot layout and host facts.
# Run on the server that has VCDT. Read the output before sending it.
#
#   ./capture.sh <path-to-vcdt> [depot-path]
#
# Deliberately does NOT touch credentials and does NOT download anything.

set -uo pipefail

VCDT="${1:-}"
DEPOT="${2:-}"
OUT="$(dirname "$0")/capture-out"

if [ -z "$VCDT" ]; then
  echo "usage: $0 <path-to-vcdt> [depot-path]" >&2
  exit 2
fi
if ! command -v "$VCDT" >/dev/null 2>&1 && [ ! -x "$VCDT" ]; then
  echo "error: '$VCDT' is not executable or not on PATH" >&2
  exit 2
fi

mkdir -p "$OUT"
echo "==> writing to $OUT"

# Run a command, capture stdout+stderr and the exit code, never fail the script.
# A non-zero exit is itself useful information, so it gets recorded.
grab() {
  local file="$1"; shift
  { "$@" 2>&1; echo "--- exit code: $? ---"; } > "$OUT/$file"
  echo "  - $file  ($(wc -l < "$OUT/$file") lines)"
}

echo "==> version and root help"
grab version.txt   "$VCDT" --version
grab help-root.txt "$VCDT" --help

# We don't know the subcommand names yet, so probe the plausible ones and keep
# whatever answers. Empty or error results are discarded below.
echo "==> probing subcommands"
for sub in list ls catalog list-releases releases products search show \
           download get fetch sync init config depot verify; do
  grab "help-${sub}.txt" "$VCDT" "$sub" --help
done

echo "==> probing for machine-readable output"
for fmt in json yaml; do
  grab "catalog-sample-${fmt}.txt" "$VCDT" list --output "$fmt"
done
grab catalog-sample.txt "$VCDT" list

# Drop probes that clearly hit a non-existent subcommand, so the output
# directory only contains things worth reading.
echo "==> pruning empty probes"
for f in "$OUT"/help-*.txt "$OUT"/catalog-sample*.txt; do
  [ -f "$f" ] || continue
  # 2 lines or fewer is just the exit-code marker plus maybe one error line.
  if [ "$(wc -l < "$f")" -le 2 ] \
     || grep -qiE 'unknown (command|flag)|not a (valid|known) command|no such command' "$f"; then
    rm -f "$f"
  fi
done

echo "==> depot layout"
if [ -n "$DEPOT" ] && [ -d "$DEPOT" ]; then
  if command -v tree >/dev/null 2>&1; then
    tree -L 3 --du -h "$DEPOT" > "$OUT/depot-tree.txt" 2>&1
  else
    find "$DEPOT" -maxdepth 3 -printf '%10s  %p\n' > "$OUT/depot-tree.txt" 2>&1
  fi
  echo "  - depot-tree.txt"

  # Any index/manifest sitting in the depot is our best inventory source.
  find "$DEPOT" -maxdepth 3 \
       \( -iname '*manifest*' -o -iname '*index*' -o -iname '*.json' \) \
       -type f -size -2M > "$OUT/depot-manifest-candidates.txt" 2>&1
  echo "  - depot-manifest-candidates.txt (copy any that look relevant)"
else
  echo "  (no depot path given or path not found — skipping)"
fi

echo "==> host facts"
{
  echo "## os"
  cat /etc/os-release 2>/dev/null | grep -E '^(NAME|VERSION)=' || uname -a
  echo
  echo "## arch / kernel"
  uname -m; uname -r
  echo
  echo "## depot mount and free space"
  if [ -n "$DEPOT" ]; then df -h "$DEPOT" 2>&1; else echo "(no depot path given)"; fi
  echo
  echo "## proxy environment"
  env | grep -iE '^(https?_proxy|no_proxy)=' || echo "(none set)"
  echo
  echo "## container runtimes"
  for c in docker podman; do
    command -v $c >/dev/null 2>&1 && $c --version 2>&1 || echo "$c: not installed"
  done
} > "$OUT/env.txt" 2>&1
echo "  - env.txt"

# Redaction pass. A safety net, not a guarantee — it can only catch patterns it
# knows. Checksums and version strings are deliberately left alone; they matter.
echo "==> redacting"
find "$OUT" -type f -print0 | while IFS= read -r -d '' f; do
  sed -i -E \
    -e 's/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._-]+/<REDACTED-JWT>/g' \
    -e 's/([Bb]earer|[Bb]asic)[[:space:]]+[A-Za-z0-9._~+\/-]{12,}=*/\1 <REDACTED>/g' \
    -e 's/((token|secret|password|passwd|apikey|api_key|auth|credential|entitlement|siteid|site_id)[[:space:]]*[:=][[:space:]]*)[^[:space:],;"]+/\1<REDACTED>/gI' \
    -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/<REDACTED-EMAIL>/g' \
    -e 's/([?&](X-Amz-[A-Za-z-]+|Signature|Expires|AWSAccessKeyId)=)[^&[:space:]]+/\1<REDACTED>/g' \
    "$f" 2>/dev/null
done

echo
echo "==> collected:"
ls -la "$OUT"
cat <<'EOF'

Still needed, by hand — these require a real download:

  vcdt <download subcommand> <args> 2>&1 | tee capture-out/progress-sample.txt
      Let it run a minute or two, then Ctrl-C.
      If the file comes out empty or full of escape codes, send it anyway —
      that is itself the answer (see README, Risk R1).

  Tail of any failed run -> capture-out/failure-sample.txt

Read every file before sending. The redaction pass is a safety net, not a
guarantee.
EOF

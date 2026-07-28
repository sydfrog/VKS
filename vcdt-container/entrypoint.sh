#!/usr/bin/env bash
# Locate VCFDT inside the bind-mounted /opt/vcdt and exec it with the caller's
# arguments. Fails loudly and specifically rather than emitting a bare
# "not found", because every failure here has a distinct fix.
set -euo pipefail

VCDT_HOME="${VCDT_HOME:-/opt/vcdt}"

die() { printf '\nvcdt-runner: %s\n\n' "$1" >&2; exit 1; }

if [ ! -d "$VCDT_HOME" ] || [ -z "$(ls -A "$VCDT_HOME" 2>/dev/null)" ]; then
  die "$VCDT_HOME is empty.

Mount your VCFDT installation there:
    -v /path/to/vcf-download-tool:/opt/vcdt:ro

The image intentionally ships without VCFDT — it is licensed Broadcom software
and cannot be redistributed inside an image. Download it from the Broadcom
support portal and unpack it on the host."
fi

# The launcher's name and depth vary by release, so search rather than assume.
BIN="${VCDT_BIN:-}"
if [ -z "$BIN" ]; then
  BIN="$(find "$VCDT_HOME" -maxdepth 3 -type f \
             \( -name 'vcf-download-tool' -o -name 'vcf-download-tool.sh' \) \
             2>/dev/null | head -n1)"
fi
[ -n "$BIN" ] || die "no 'vcf-download-tool' launcher found under $VCDT_HOME.

Looked 3 levels deep. If yours is named differently or nested further, set it
explicitly:
    -e VCDT_BIN=/opt/vcdt/some/path/vcf-download-tool"

# A read-only bind mount can carry the executable bit from the host; if it
# doesn't, invoke through the shell rather than failing.
if [ -x "$BIN" ]; then
  exec "$BIN" "$@"
else
  exec bash "$BIN" "$@"
fi

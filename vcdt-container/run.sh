#!/usr/bin/env bash
# Convenience wrapper around the vcdt-runner image.
#
#   ./run.sh binaries --help
#   ./run.sh binaries list --vcf-version 9.0.2 --sku VCF \
#            --depot-download-token-file /etc/vcf-depot/token.txt
#
# Paths are overridable by environment variable so this works unchanged on a
# laptop and on the depot VM.
set -euo pipefail

VCDT_DIR="${VCDT_DIR:-/opt/vcdt}"          # VCFDT installation on the host
DEPOT_DIR="${DEPOT_DIR:-/srv/vcf-depot}"   # depot store on the host
CONF_DIR="${CONF_DIR:-/etc/vcf-depot}"     # token file lives here
IMAGE="${IMAGE:-vcdt-runner}"

for d in "$VCDT_DIR" "$DEPOT_DIR" "$CONF_DIR"; do
  [ -d "$d" ] || { echo "run.sh: '$d' does not exist. Create it, or override the matching *_DIR variable." >&2; exit 1; }
done

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "run.sh: building $IMAGE (first run only)..." >&2
  docker build --build-arg UID="$(id -u)" --build-arg GID="$(id -g)" \
               -t "$IMAGE" "$(dirname "$0")"
fi

# -t gives VCFDT a TTY so any interactive progress rendering behaves as it does
# natively. Dropped automatically when output is piped, which is what
# capture.sh wants — and the difference between the two is exactly the Risk R1
# question, so it is worth being able to test both.
TTY_FLAGS=()
[ -t 1 ] && TTY_FLAGS+=(-t)
[ -t 0 ] && TTY_FLAGS+=(-i)

exec docker run --rm "${TTY_FLAGS[@]}" \
  -v "$VCDT_DIR:/opt/vcdt:ro" \
  -v "$DEPOT_DIR:/srv/vcf-depot" \
  -v "$CONF_DIR:/etc/vcf-depot:ro" \
  -e VCDT_BIN="${VCDT_BIN:-}" \
  ${HTTPS_PROXY:+-e HTTPS_PROXY="$HTTPS_PROXY"} \
  ${HTTP_PROXY:+-e HTTP_PROXY="$HTTP_PROXY"} \
  ${NO_PROXY:+-e NO_PROXY="$NO_PROXY"} \
  "$IMAGE" "$@"

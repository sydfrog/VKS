#!/usr/bin/env bash
# Convenience wrapper around the vcdt-runner image.
#
#   ./run.sh binaries --help
#   ./run.sh binaries list --vcf-version 9.0.2 --sku VCF \
#            --depot-download-token-file /etc/vcf-depot/token.txt
#
# Works with docker or podman — whichever is present. Paths are overridable by
# environment variable so this behaves the same on a laptop and on the depot VM.
set -euo pipefail

VCDT_DIR="${VCDT_DIR:-/opt/vcdt}"          # VCFDT installation on the host
DEPOT_DIR="${DEPOT_DIR:-/srv/vcf-depot}"   # depot store on the host
CONF_DIR="${CONF_DIR:-/etc/vcf-depot}"     # token file lives here
IMAGE="${IMAGE:-vcdt-runner}"

# Engine: docker if present, else podman. Override with ENGINE=podman.
ENGINE="${ENGINE:-}"
if [ -z "$ENGINE" ]; then
  if command -v docker >/dev/null 2>&1; then ENGINE=docker
  elif command -v podman >/dev/null 2>&1; then ENGINE=podman
  else echo "run.sh: neither docker nor podman found." >&2; exit 1
  fi
fi

for d in "$VCDT_DIR" "$DEPOT_DIR" "$CONF_DIR"; do
  [ -d "$d" ] || { echo "run.sh: '$d' does not exist. Create it, or override the matching *_DIR variable." >&2; exit 1; }
done

# SELinux: a bind mount the container cannot read looks like a permission bug
# but is a labelling one, so check up front and say exactly what to run.
#
# We deliberately do NOT append :z to the mounts. That flag relabels
# recursively on every invocation, which is fine for a small directory and
# unacceptable for a multi-terabyte depot. setup-depot-host.sh sets the labels
# once, persistently.
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce)" = "Enforcing" ]; then
  for d in "$VCDT_DIR" "$DEPOT_DIR"; do
    label="$(ls -dZ "$d" 2>/dev/null | awk '{print $1}')"
    case "$label" in
      *container_file_t*|*svirt_sandbox_file_t*) ;;
      *)
        cat >&2 <<EOF
run.sh: SELinux is enforcing and '$d' is not labelled for container access.
        Current label: ${label:-unknown}

        Fix it once, persistently:
            sudo semanage fcontext -a -t container_file_t "${d}(/.*)?"
            sudo restorecon -R "$d"

        Or re-run scripts/setup-depot-host.sh, which does this for you.
EOF
        exit 1
        ;;
    esac
  done
fi

if ! "$ENGINE" image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "run.sh: building $IMAGE with $ENGINE (first run only)..." >&2
  "$ENGINE" build --build-arg UID="$(id -u)" --build-arg GID="$(id -g)" \
                  -t "$IMAGE" "$(dirname "$0")"
fi

# -t gives VCFDT a TTY so any interactive progress rendering behaves as it does
# natively. Dropped automatically when output is piped, which is what
# capture.sh wants — and the difference between the two is exactly the Risk R1
# question, so it is worth being able to test both.
TTY_FLAGS=()
[ -t 1 ] && TTY_FLAGS+=(-t)
[ -t 0 ] && TTY_FLAGS+=(-i)

exec "$ENGINE" run --rm "${TTY_FLAGS[@]}" \
  -v "$VCDT_DIR:/opt/vcdt:ro" \
  -v "$DEPOT_DIR:/srv/vcf-depot" \
  -v "$CONF_DIR:/etc/vcf-depot:ro" \
  -e VCDT_BIN="${VCDT_BIN:-}" \
  ${HTTPS_PROXY:+-e HTTPS_PROXY="$HTTPS_PROXY"} \
  ${HTTP_PROXY:+-e HTTP_PROXY="$HTTP_PROXY"} \
  ${NO_PROXY:+-e NO_PROXY="$NO_PROXY"} \
  "$IMAGE" "$@"

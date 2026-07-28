#!/usr/bin/env bash
# Prepare a freshly installed host to run the VCF depot manager.
#
#   sudo ./setup-depot-host.sh --depot-device /dev/sdb
#   sudo ./setup-depot-host.sh --depot-device /dev/sdb --dry-run
#
# Targets RHEL-family (Rocky, AlmaLinux, CentOS Stream, RHEL) and also works on
# Debian/Ubuntu. Idempotent: safe to re-run after a partial failure.
#
# It will NOT format a device that already carries a filesystem. Formatting the
# wrong disk is the one unrecoverable mistake available here, so the device is
# a required argument rather than a guess, and it is checked before use.
set -euo pipefail

DEPOT_DEV=""
DEPOT_DIR="/srv/vcf-depot"
VCDT_DIR="/opt/vcdt"
CONF_DIR="/etc/vcf-depot"
SERVICE_USER="${SUDO_USER:-$(id -un)}"
DRY_RUN=0
OPEN_FIREWALL=1

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  cat <<EOF

Options:
  --depot-device <dev>   Block device for the depot (e.g. /dev/sdb). Required
                         unless --no-depot-disk is given.
  --no-depot-disk        Use a plain directory instead of a dedicated disk.
  --depot-dir <path>     Depot mount point           (default: $DEPOT_DIR)
  --user <name>          Owner of the depot          (default: $SERVICE_USER)
  --no-firewall          Skip opening http/https
  --dry-run              Print what would happen, change nothing
EOF
}

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning: %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }
run()  {
  if [ "$DRY_RUN" -eq 1 ]; then printf '  [dry-run] %s\n' "$*"; else "$@"; fi
}

USE_DISK=1
while [ $# -gt 0 ]; do
  case "$1" in
    --depot-device) DEPOT_DEV="${2:?}"; shift 2 ;;
    --no-depot-disk) USE_DISK=0; shift ;;
    --depot-dir) DEPOT_DIR="${2:?}"; shift 2 ;;
    --user) SERVICE_USER="${2:?}"; shift 2 ;;
    --no-firewall) OPEN_FIREWALL=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || [ "$DRY_RUN" -eq 1 ] || die "must run as root (use sudo)"

# --------------------------------------------------------------------------
# Distro detection
# --------------------------------------------------------------------------
. /etc/os-release 2>/dev/null || die "cannot read /etc/os-release"
case "${ID}${ID_LIKE:-}" in
  *rhel*|*fedora*|*centos*|rocky*|almalinux*) FAMILY=rhel ;;
  *debian*|ubuntu*)                           FAMILY=debian ;;
  *) die "unsupported distribution: ${PRETTY_NAME:-$ID}" ;;
esac
log "Detected ${PRETTY_NAME:-$ID} (${FAMILY} family)"

# --------------------------------------------------------------------------
# Packages
# --------------------------------------------------------------------------
log "Installing packages"
ENGINE=""
if [ "$FAMILY" = rhel ]; then
  run dnf -y install dnf-plugins-core tar tree jq unzip xfsprogs \
      policycoreutils-python-utils open-vm-tools

  # Docker CE's CentOS repo is keyed on $releasever and does not always carry
  # packages for the newest CentOS Stream. Podman ships natively on RHEL 10 and
  # CentOS Stream 10 and provides a compatible CLI, so fall back to it rather
  # than failing the build.
  install_docker_rhel() {
    if [ "$DRY_RUN" -eq 1 ]; then
      printf '  [dry-run] add docker-ce repo and install docker-ce\n'
      return 0
    fi
    dnf config-manager --add-repo \
        https://download.docker.com/linux/centos/docker-ce.repo >/dev/null 2>&1 \
      && dnf -y install docker-ce docker-ce-cli containerd.io \
             docker-buildx-plugin docker-compose-plugin >/dev/null 2>&1
  }

  if command -v docker >/dev/null 2>&1; then
    ENGINE=docker
  elif [ "${PREFER_ENGINE:-auto}" != "podman" ] && install_docker_rhel; then
    ENGINE=docker
  else
    warn "docker-ce unavailable for $PRETTY_NAME — using podman instead"
    run rm -f /etc/yum.repos.d/docker-ce.repo
    run dnf -y install podman podman-docker podman-compose
    ENGINE=podman
  fi
else
  run apt-get update
  run apt-get install -y ca-certificates curl gnupg tar tree jq unzip xfsprogs \
      open-vm-tools
  if ! command -v docker >/dev/null 2>&1; then
    run install -m 0755 -d /etc/apt/keyrings
    run curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc
    run chmod a+r /etc/apt/keyrings/docker.asc
    if [ "$DRY_RUN" -eq 0 ]; then
      echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    fi
    run apt-get update
    run apt-get install -y docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
  fi
  ENGINE=docker
fi

if [ "$ENGINE" = docker ]; then
  run systemctl enable --now docker
  id -nG "$SERVICE_USER" 2>/dev/null | grep -qw docker \
    || run usermod -aG docker "$SERVICE_USER"
else
  # Podman runs rootless, so there is no daemon to enable and no group to join.
  # Lingering lets the user's containers survive logout.
  run loginctl enable-linger "$SERVICE_USER"
fi
log "Container engine: ${ENGINE:-none}"

# --------------------------------------------------------------------------
# Depot storage
#
# The guard below is the important part: a device that already has a
# filesystem is never touched, so re-running this cannot destroy a populated
# depot.
# --------------------------------------------------------------------------
log "Preparing depot storage at $DEPOT_DIR"
if [ "$USE_DISK" -eq 1 ]; then
  [ -n "$DEPOT_DEV" ] || { echo; lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT; echo;
    die "--depot-device is required. Pick an unused device from the list above, or pass --no-depot-disk."; }
  [ -b "$DEPOT_DEV" ] || die "$DEPOT_DEV is not a block device"

  if findmnt -S "$DEPOT_DEV" >/dev/null 2>&1; then
    die "$DEPOT_DEV is already mounted. Refusing to touch it."
  fi

  EXISTING="$(blkid -o value -s TYPE "$DEPOT_DEV" 2>/dev/null || true)"
  EXISTING_LABEL="$(blkid -o value -s LABEL "$DEPOT_DEV" 2>/dev/null || true)"

  if [ -z "$EXISTING" ]; then
    warn "About to format $DEPOT_DEV ($(lsblk -dno SIZE "$DEPOT_DEV" | tr -d ' ')) as XFS. All data on it will be lost."
    if [ "$DRY_RUN" -eq 0 ]; then
      read -r -p "Type the device path again to confirm: " CONFIRM
      [ "$CONFIRM" = "$DEPOT_DEV" ] || die "confirmation did not match, aborting"
    fi
    run mkfs.xfs -L vcfdepot "$DEPOT_DEV"
  elif [ "$EXISTING_LABEL" = "vcfdepot" ]; then
    log "$DEPOT_DEV already carries the vcfdepot filesystem — reusing it"
  else
    die "$DEPOT_DEV already contains a '$EXISTING' filesystem (label: ${EXISTING_LABEL:-none}).
Refusing to format. Use a different device, or wipe it deliberately first."
  fi

  run mkdir -p "$DEPOT_DIR"
  if ! grep -q "LABEL=vcfdepot" /etc/fstab 2>/dev/null; then
    if [ "$DRY_RUN" -eq 0 ]; then
      echo "LABEL=vcfdepot $DEPOT_DIR xfs defaults,noatime 0 2" >> /etc/fstab
    else
      printf '  [dry-run] append fstab entry for LABEL=vcfdepot\n'
    fi
  fi
  run mount -a
  findmnt "$DEPOT_DIR" >/dev/null 2>&1 || [ "$DRY_RUN" -eq 1 ] || die "$DEPOT_DIR failed to mount"
else
  run mkdir -p "$DEPOT_DIR"
fi

# --------------------------------------------------------------------------
# Directory layout
# --------------------------------------------------------------------------
log "Creating $VCDT_DIR and $CONF_DIR"
run mkdir -p "$VCDT_DIR" "$CONF_DIR"
run chown -R "$SERVICE_USER" "$DEPOT_DIR" "$VCDT_DIR" "$CONF_DIR"
run chmod 750 "$CONF_DIR"   # the depot token lives here

# --------------------------------------------------------------------------
# SELinux
#
# Without this, containers cannot read /opt/vcdt or write the depot, and the
# failure looks like a permission bug rather than a labelling one.
#
# Labels are set persistently rather than via docker's :z flag: :z relabels
# recursively on every run, which on a multi-terabyte depot is unacceptable.
# --------------------------------------------------------------------------
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce)" != "Disabled" ]; then
  log "Labelling for SELinux ($(getenforce))"
  if command -v semanage >/dev/null 2>&1; then
    for d in "$DEPOT_DIR" "$VCDT_DIR"; do
      run semanage fcontext -a -t container_file_t "${d}(/.*)?" 2>/dev/null \
        || run semanage fcontext -m -t container_file_t "${d}(/.*)?"
      run restorecon -R "$d"
    done
  else
    warn "semanage not found; install policycoreutils-python-utils and re-run"
  fi
else
  log "SELinux disabled or absent — no labelling needed"
fi

# --------------------------------------------------------------------------
# Firewall
# --------------------------------------------------------------------------
if [ "$OPEN_FIREWALL" -eq 1 ] && systemctl is-active --quiet firewalld 2>/dev/null; then
  log "Opening http/https in firewalld"
  run firewall-cmd --permanent --add-service=http
  run firewall-cmd --permanent --add-service=https
  run firewall-cmd --reload
elif [ "$OPEN_FIREWALL" -eq 1 ]; then
  log "firewalld not active — nothing to open"
fi

# --------------------------------------------------------------------------
# Summary — this block is what to send back (fills ORCHESTRATION.md NEED 3.6)
# --------------------------------------------------------------------------
log "Done. Send the following back:"
cat <<EOF

## os
$(grep -E '^(NAME|VERSION)=' /etc/os-release | tr '\n' ' ')
## arch
$(uname -m)  kernel $(uname -r)
## depot
$(df -h "$DEPOT_DIR" 2>/dev/null | tail -1)
$(ls -ldZ "$DEPOT_DIR" 2>/dev/null || ls -ld "$DEPOT_DIR" 2>/dev/null || echo '(not created)')
## service user
$(id "$SERVICE_USER")
## container engine
$(docker --version 2>/dev/null || podman --version 2>/dev/null || echo 'not available')
$(docker compose version 2>/dev/null || podman-compose --version 2>/dev/null || echo 'compose not available')
## selinux
$(getenforce 2>/dev/null || echo 'not present')
## firewall
$(firewall-cmd --list-services 2>/dev/null || echo 'firewalld not active')
## proxy
$(env | grep -iE '^(https?_proxy|no_proxy)=' || echo none)

EOF

if [ "$DRY_RUN" -eq 0 ]; then
  echo "Log out and back in so '$SERVICE_USER' picks up the docker group."
fi

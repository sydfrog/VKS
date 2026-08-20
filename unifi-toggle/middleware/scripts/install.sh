#!/usr/bin/env bash
#
# Install the middleware on a Linux VM. Idempotent, safe to re-run after an edit.
#
# Run from the middleware directory:
#   sudo scripts/install.sh
#
# It does not start the service, because the env file needs your values first.
# The script prints the exact next commands when it finishes.
set -euo pipefail

APP_USER="unifi-toggle"
APP_DIR="/opt/unifi-toggle"
ETC_DIR="/etc/unifi-toggle"
ENV_FILE="${ETC_DIR}/unifi-toggle.env"
UNIT="/etc/systemd/system/unifi-toggle.service"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$(id -u)" != "0" ]; then
  echo "run this with sudo" >&2
  exit 1
fi

echo "Source directory: ${SRC}"

die() { echo; echo "ERROR: $*" >&2; exit 1; }

# Debian and Ubuntu ship venv and ensurepip in a separate package, so name it.
print_venv_hint() {
  local id like
  id="$(. /etc/os-release 2>/dev/null && echo "${ID:-}")"
  like="$(. /etc/os-release 2>/dev/null && echo "${ID_LIKE:-}")"
  echo
  case "${id} ${like}" in
    *debian*|*ubuntu*)
      echo "    sudo apt update"
      echo "    sudo apt install -y python3-venv python3-pip"
      ;;
    *fedora*|*rhel*|*centos*)
      echo "    sudo dnf install -y python3-pip"
      ;;
    *)
      echo "    install your distribution's python3 venv and pip packages"
      ;;
  esac
  echo
}

# Fail before creating users or directories, so a missing package leaves
# nothing half built behind.
echo "Checking prerequisites"
command -v python3 >/dev/null 2>&1 || die "python3 is not installed."

PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "$(python3 -c 'import sys; print(1 if sys.version_info[:2] >= (3, 10) else 0)')" != "1" ]; then
  die "python3 is ${PY_VER}, and this needs 3.10 or newer."
fi
if [ "$(python3 -c 'import sys; print(1 if sys.version_info[:2] >= (3, 11) else 0)')" != "1" ]; then
  echo "  note: python3 is ${PY_VER}. That works, but 3.11 is what this was tested on."
fi

if ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
  echo
  echo "python3 ${PY_VER} cannot build a virtualenv, because the venv or"
  echo "ensurepip module is missing. On Debian and Ubuntu these are packaged"
  echo "separately from python3 itself. Install them with:"
  print_venv_hint
  die "missing python3 venv support."
fi
echo "  python3 ${PY_VER}, venv support present"

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  echo "Creating system user ${APP_USER}"
  useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
else
  echo "System user ${APP_USER} already exists"
fi

echo "Installing application into ${APP_DIR}"
install -d -o root -g root -m 0755 "$APP_DIR"
rm -rf "${APP_DIR}/unifi_toggle"
cp -r "${SRC}/unifi_toggle" "${APP_DIR}/unifi_toggle"
cp "${SRC}/requirements.txt" "${APP_DIR}/requirements.txt"
install -d -o root -g root -m 0755 "${APP_DIR}/scripts"
cp "${SRC}"/scripts/*.sh "${APP_DIR}/scripts/"
chmod 0755 "${APP_DIR}"/scripts/*.sh

# A failed "python3 -m venv" still leaves bin/python behind, and only fails
# later at ensurepip. Testing bin/python alone therefore treats a broken venv
# as a good one, so require pip as well and rebuild when it is missing.
venv_is_usable() {
  [ -x "${APP_DIR}/venv/bin/python" ] && [ -x "${APP_DIR}/venv/bin/pip" ]
}

if venv_is_usable; then
  echo "Reusing the existing virtualenv"
else
  if [ -e "${APP_DIR}/venv" ]; then
    echo "The existing virtualenv is incomplete, rebuilding it"
    rm -rf "${APP_DIR}/venv"
  fi
  echo "Creating virtualenv"
  if ! python3 -m venv "${APP_DIR}/venv"; then
    echo
    echo "Creating the virtualenv failed. The usual cause is a missing package:"
    print_venv_hint
    die "could not create the virtualenv."
  fi
  if ! venv_is_usable; then
    echo
    echo "The virtualenv was created but has no pip in it. Install the package"
    echo "shown below and re-run this script:"
    print_venv_hint
    die "virtualenv has no pip."
  fi
fi

echo "Installing Python dependencies"
"${APP_DIR}/venv/bin/pip" install --quiet --upgrade pip
"${APP_DIR}/venv/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"

echo "Preparing ${ETC_DIR}"
install -d -o root -g "$APP_USER" -m 0750 "$ETC_DIR"
install -d -o root -g "$APP_USER" -m 0750 "${ETC_DIR}/tls"

if [ ! -f "$ENV_FILE" ]; then
  cp "${SRC}/unifi-toggle.env.example" "$ENV_FILE"
  chown root:"$APP_USER" "$ENV_FILE"
  chmod 0640 "$ENV_FILE"
  echo "Created ${ENV_FILE} from the example. Edit it before starting."
  NEEDS_EDIT=1
else
  chown root:"$APP_USER" "$ENV_FILE"
  chmod 0640 "$ENV_FILE"
  echo "Kept the existing ${ENV_FILE}"
  NEEDS_EDIT=0
fi

# Verify the install before touching systemd. A broken venv is much easier to
# read about here than as a systemd start failure.
echo "Checking the installed application"
if ! "${APP_DIR}/venv/bin/python" -c "import unifi_toggle, fastapi, uvicorn, httpx" 2>/dev/null; then
  echo "the virtualenv is not usable, the install did not complete" >&2
  exit 1
fi
echo "  imports fine, version $("${APP_DIR}/venv/bin/python" -c 'import unifi_toggle; print(unifi_toggle.__version__)')"

HAVE_SYSTEMD=0
if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
  HAVE_SYSTEMD=1
fi

if [ "$HAVE_SYSTEMD" = "1" ]; then
  echo "Installing systemd unit"
  cp "${SRC}/systemd/unifi-toggle.service" "$UNIT"
  chmod 0644 "$UNIT"
  systemctl daemon-reload
else
  echo
  echo "NOTE: systemd was not detected on this host, so the unit was not"
  echo "      installed. Everything else is in place. This is expected inside"
  echo "      a container. On a normal VM this step installs the service."
  echo
fi

echo
echo "Install complete."
echo
if [ "$NEEDS_EDIT" = "1" ]; then
  echo "Next, in order:"
  echo
  echo "  1. Generate a bearer token and note it down:"
  echo "       ${APP_DIR}/scripts/gen-token.sh"
  echo
  echo "  2. Generate the TLS certificate, using this VM's LAN address:"
  echo "       sudo ${APP_DIR}/scripts/make-cert.sh <vm-ip> ${ETC_DIR}/tls"
  echo "       sudo chown root:${APP_USER} ${ETC_DIR}/tls/*"
  echo "       sudo chmod 0640 ${ETC_DIR}/tls/server.key ${ETC_DIR}/tls/ca.key"
  echo
  echo "  3. Edit the env file. UNIFI_HOST and UNIFI_POLICY_NAME are already"
  echo "     filled in, so you only need API_TOKEN and UNIFI_API_KEY, plus the"
  echo "     two TLS paths from step 2:"
  echo "       sudo nano ${ENV_FILE}"
  echo
  echo "  4. Then enable and start:"
else
  echo "Then restart to pick up the new code:"
fi
if [ "$HAVE_SYSTEMD" = "1" ]; then
  echo "       sudo systemctl enable --now unifi-toggle"
  echo "       sudo systemctl status unifi-toggle"
  echo "       journalctl -u unifi-toggle -f"
  echo
  echo "  5. Then check it end to end:"
  echo "       sudo ${APP_DIR}/scripts/smoke-test.sh"
else
  echo "       (no systemd here, so run it in the foreground instead)"
  echo "       sudo -u ${APP_USER} env \$(grep -v \"^#\" ${ENV_FILE} | xargs) \\"
  echo "         ${APP_DIR}/venv/bin/python -m unifi_toggle"
fi

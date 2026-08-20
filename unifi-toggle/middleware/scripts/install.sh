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

if [ ! -x "${APP_DIR}/venv/bin/python" ]; then
  echo "Creating virtualenv"
  python3 -m venv "${APP_DIR}/venv"
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

echo "Installing systemd unit"
cp "${SRC}/systemd/unifi-toggle.service" "$UNIT"
chmod 0644 "$UNIT"
systemctl daemon-reload

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
  echo "  3. Edit the env file and fill in API_TOKEN, UNIFI_HOST,"
  echo "     UNIFI_API_KEY and UNIFI_POLICY_ID:"
  echo "       sudo nano ${ENV_FILE}"
  echo
  echo "  4. Then enable and start:"
else
  echo "Then restart to pick up the new code:"
fi
echo "       sudo systemctl enable --now unifi-toggle"
echo "       sudo systemctl status unifi-toggle"
echo "       journalctl -u unifi-toggle -f"

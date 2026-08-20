#!/usr/bin/env bash
#
# End to end test with no real UniFi console involved.
#
# Starts a fake UniFi OS console on 127.0.0.1:18443 over TLS, starts the real
# middleware on 127.0.0.1:18080 over TLS pointing at it, then runs the same
# smoke test you would run against the real thing. Proves the whole path:
# uvicorn, TLS, bearer auth, the UniFi client, read modify write.
#
# Usage, from the middleware directory:
#   scripts/local-e2e.sh
#
# Uses the virtualenv at .venv if present, otherwise python3 from PATH.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
CONSOLE_PORT=18443
SERVICE_PORT=18080

if [ -x "${HERE}/.venv/bin/python" ]; then
  PY="${HERE}/.venv/bin/python"
else
  PY="$(command -v python3)"
fi

cleanup() {
  [ -n "${CONSOLE_PID:-}" ] && kill "$CONSOLE_PID" 2>/dev/null || true
  [ -n "${SERVICE_PID:-}" ] && kill "$SERVICE_PID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "Work directory: ${WORK}"
"${HERE}/scripts/make-cert.sh" 127.0.0.1 "${WORK}/tls" >/dev/null

TOKEN="$("${HERE}/scripts/gen-token.sh")"

cat > "${WORK}/console.py" <<PYEOF
import sys
sys.path.insert(0, "${HERE}")
import uvicorn
from tests.fake_unifi import create_fake_unifi
app, _state = create_fake_unifi()
uvicorn.run(
    app, host="127.0.0.1", port=${CONSOLE_PORT}, log_level="warning",
    ssl_certfile="${WORK}/tls/server-fullchain.pem",
    ssl_keyfile="${WORK}/tls/server.key",
)
PYEOF

cat > "${WORK}/service.env" <<ENVEOF
API_TOKEN=${TOKEN}
BIND_HOST=127.0.0.1
PORT=${SERVICE_PORT}
TLS_CERT_FILE=${WORK}/tls/server-fullchain.pem
TLS_KEY_FILE=${WORK}/tls/server.key
LOG_LEVEL=info
UNIFI_HOST=https://127.0.0.1:${CONSOLE_PORT}
UNIFI_CONTROLLER_TYPE=unifi-os
UNIFI_SITE=default
UNIFI_API_KEY=fake-api-key-0123456789
UNIFI_AUTH_MODE=apikey
UNIFI_VERIFY_SSL=false
UNIFI_TIMEOUT=10
# Selected by name, the same way the shipped env file does it.
UNIFI_POLICY_NAME="Block Kids from Internet"
UNIFI_POLICY_KIND=auto
ENVEOF

wait_for() {
  local url="$1" name="$2" i
  for i in $(seq 1 60); do
    if curl -sk --max-time 2 -o /dev/null "$url" 2>/dev/null; then return 0; fi
    sleep 0.25
  done
  echo "${name} did not come up in time" >&2
  return 1
}

echo "Starting fake UniFi console on https://127.0.0.1:${CONSOLE_PORT}"
"$PY" "${WORK}/console.py" > "${WORK}/console.log" 2>&1 &
CONSOLE_PID=$!
wait_for "https://127.0.0.1:${CONSOLE_PORT}/proxy/network/v2/api/site/default/firewall-policies" "fake console"

echo "Starting middleware on https://127.0.0.1:${SERVICE_PORT}"
( set -a; . "${WORK}/service.env"; set +a; cd "$HERE" && exec "$PY" -m unifi_toggle ) \
  > "${WORK}/service.log" 2>&1 &
SERVICE_PID=$!
wait_for "https://127.0.0.1:${SERVICE_PORT}/healthz" "middleware"

echo
BASE_URL="https://127.0.0.1:${SERVICE_PORT}" "${HERE}/scripts/smoke-test.sh" "${WORK}/service.env"
RESULT=$?

echo
echo "=== middleware log ==="
cat "${WORK}/service.log"

exit $RESULT

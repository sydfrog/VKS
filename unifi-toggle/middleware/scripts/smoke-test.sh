#!/usr/bin/env bash
#
# Exercise the running service end to end: status, enable, status, disable,
# status, plus a check that an unauthenticated call is refused.
#
# Usage:
#   scripts/smoke-test.sh                       uses /etc/unifi-toggle/unifi-toggle.env
#   scripts/smoke-test.sh path/to/env           uses that env file
#
# Set BASE_URL to override the address, for example https://192.168.0.50:8080
set -euo pipefail

ENV_FILE="${1:-/etc/unifi-toggle/unifi-toggle.env}"
if [ -r "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
else
  echo "cannot read ${ENV_FILE}, falling back to the current environment" >&2
fi

: "${API_TOKEN:?API_TOKEN is not set}"
PORT="${PORT:-8080}"
if [ -n "${TLS_CERT_FILE:-}" ]; then SCHEME="https"; else SCHEME="http"; fi
BASE_URL="${BASE_URL:-${SCHEME}://127.0.0.1:${PORT}}"

# -k because the certificate names the VM address, not 127.0.0.1.
CURL=(curl -sk --max-time 15)

call() {
  local method="$1" path="$2"
  "${CURL[@]}" -X "$method" -H "Authorization: Bearer ${API_TOKEN}" \
    -w '\n  HTTP %{http_code}\n' "${BASE_URL}${path}"
}

fail=0
step() { echo; echo "--- $*"; }

step "unauthenticated GET /status should be 401"
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "${BASE_URL}/status")"
echo "  HTTP ${code}"
[ "$code" = "401" ] || { echo "  UNEXPECTED, wanted 401"; fail=1; }

step "wrong token GET /status should be 403"
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' -H "Authorization: Bearer wrong" "${BASE_URL}/status")"
echo "  HTTP ${code}"
[ "$code" = "403" ] || { echo "  UNEXPECTED, wanted 403"; fail=1; }

step "GET /healthz"; call GET /healthz
step "GET /status (before)"; call GET /status
step "POST /enable"; call POST /enable
step "GET /status (should be enabled true)"; call GET /status
step "POST /disable"; call POST /disable
step "GET /status (should be enabled false)"; call GET /status

echo
if [ "$fail" = "0" ]; then
  echo "Smoke test finished. Check that enabled flipped true then false above."
else
  echo "Smoke test finished WITH PROBLEMS. See the UNEXPECTED lines above."
  exit 1
fi

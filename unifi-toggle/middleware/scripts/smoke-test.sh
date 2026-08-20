#!/usr/bin/env bash
#
# Exercise a running service against the real console, then put the policy back
# exactly as it was found.
#
# The test flips the policy away from its current state and back again, rather
# than enabling and then disabling. Two reasons. It proves both write
# directions no matter which state the policy starts in, and it leaves your
# firewall the way it was. A fixed enable then disable sequence silently turns
# a policy off if it happened to already be on when you started.
#
# Usage:
#   scripts/smoke-test.sh                       uses /etc/unifi-toggle/unifi-toggle.env
#   scripts/smoke-test.sh path/to/env           uses that env file
#
# Set BASE_URL to override the address, for example https://192.168.0.50:8080
set -uo pipefail

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
CURL=(curl -sk --max-time 20)

fail=0
BODY=""
CODE=""

note()  { echo; echo "--- $*"; }
bad()   { echo "  PROBLEM: $*"; fail=1; }

call() {
  local method="$1" path="$2" raw
  raw=$("${CURL[@]}" -X "$method" -H "Authorization: Bearer ${API_TOKEN}" \
        -w $'\n%{http_code}' "${BASE_URL}${path}")
  CODE=$(printf '%s' "$raw" | tail -n1)
  BODY=$(printf '%s' "$raw" | sed '$d')
}

# Reads one field out of the last response. Returns the literal string
# "true", "false", "null", or the value.
field() {
  printf '%s' "$BODY" | python3 -c '
import json, sys
try:
    value = json.load(sys.stdin).get(sys.argv[1])
except Exception:
    print("null"); raise SystemExit
print("true" if value is True else "false" if value is False else str(value))
' "$1"
}

expect_code() {
  if [ "$CODE" != "$1" ]; then bad "expected HTTP $1, got $CODE. Body: $BODY"; return 1; fi
  return 0
}

# ------------------------------------------------------------------- auth

note "unauthenticated GET /status should be 401"
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "${BASE_URL}/status")"
echo "  HTTP ${code}"
[ "$code" = "401" ] || bad "wanted 401"

note "wrong token GET /status should be 403"
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' -H "Authorization: Bearer wrong" "${BASE_URL}/status")"
echo "  HTTP ${code}"
[ "$code" = "403" ] || bad "wanted 403"

note "GET /healthz"
call GET /healthz
echo "  ${BODY}"
echo "  HTTP ${CODE}"
expect_code 200

# -------------------------------------------------------------- baseline

note "GET /status, reading the starting state"
call GET /status
echo "  ${BODY}"
echo "  HTTP ${CODE}"
if ! expect_code 200; then
  echo
  echo "Cannot reach the policy, so the toggle test was skipped."
  exit 1
fi

ORIGINAL="$(field enabled)"
POLICY_NAME="$(field name)"
POLICY_ID="$(field policy_id)"
if [ "$ORIGINAL" != "true" ] && [ "$ORIGINAL" != "false" ]; then
  bad "could not read the current enabled state"
  exit 1
fi

echo
echo "  policy: ${POLICY_NAME}"
echo "  id:     ${POLICY_ID}"
echo "  state:  ${ORIGINAL}"

if [ "$ORIGINAL" = "true" ]; then
  AWAY_VERB="disable"; AWAY_STATE="false"
  BACK_VERB="enable";  BACK_STATE="true"
else
  AWAY_VERB="enable";  AWAY_STATE="true"
  BACK_VERB="disable"; BACK_STATE="false"
fi

echo
echo "  This will ${AWAY_VERB} it, then ${BACK_VERB} it again, leaving it ${ORIGINAL}."

# ---------------------------------------------------------- flip away

note "POST /${AWAY_VERB} (should report changed true, this is a real write)"
call POST "/${AWAY_VERB}"
echo "  ${BODY}"
echo "  HTTP ${CODE}"
expect_code 200
[ "$(field enabled)" = "$AWAY_STATE" ] || bad "enabled should now be ${AWAY_STATE}"
if [ "$(field changed)" != "true" ]; then
  bad "changed was not true, so nothing was actually written to the console"
fi

note "GET /status, independent read back"
call GET /status
echo "  ${BODY}"
[ "$(field enabled)" = "$AWAY_STATE" ] || bad "console did not keep the change"

note "POST /${AWAY_VERB} again (should report changed false, no second write)"
call POST "/${AWAY_VERB}"
echo "  HTTP ${CODE}"
[ "$(field changed)" = "false" ] || bad "repeating the call should not report a change"

# ----------------------------------------------------------- flip back

note "POST /${BACK_VERB} (should report changed true, putting it back)"
call POST "/${BACK_VERB}"
echo "  ${BODY}"
echo "  HTTP ${CODE}"
expect_code 200
[ "$(field enabled)" = "$BACK_STATE" ] || bad "enabled should be back to ${BACK_STATE}"
[ "$(field changed)" = "true" ] || bad "changed was not true on the way back"

note "GET /status, confirming it is back as found"
call GET /status
echo "  ${BODY}"
FINAL="$(field enabled)"
[ "$FINAL" = "$ORIGINAL" ] || bad "policy left as ${FINAL} but started as ${ORIGINAL}"

# -------------------------------------------------------------- verdict

echo
echo "=============================================================="
if [ "$fail" = "0" ]; then
  echo " PASS. Both directions performed real writes and were confirmed"
  echo " by a separate read. The policy is back to enabled=${ORIGINAL},"
  echo " exactly as it was before this ran."
  echo
  echo " Now check the UniFi UI shows enabled=${ORIGINAL} for"
  echo " ${POLICY_NAME}, and you are done with the middleware."
else
  echo " FAILED. See the PROBLEM lines above."
  echo " The policy may have been left as enabled=${FINAL:-unknown}"
  echo " when it started as enabled=${ORIGINAL}. Check it."
fi
echo "=============================================================="
[ "$fail" = "0" ] || exit 1

#!/usr/bin/env bash
#
# List every firewall policy, traffic rule and legacy firewall rule on the
# console, with the ID you need for UNIFI_POLICY_ID.
#
# Usage:
#   UNIFI_HOST=192.168.1.1 UNIFI_API_KEY=xxxx scripts/probe-unifi.sh
#   scripts/probe-unifi.sh /etc/unifi-toggle/unifi-toggle.env
#
# Reads the env file if you pass one, otherwise uses the current environment.
set -euo pipefail

if [ $# -ge 1 ]; then
  # shellcheck disable=SC1090
  set -a; . "$1"; set +a
fi

: "${UNIFI_HOST:?set UNIFI_HOST, for example 192.168.1.1}"
: "${UNIFI_API_KEY:?set UNIFI_API_KEY, create one at Control Plane > Integrations}"
SITE="${UNIFI_SITE:-default}"
TYPE="${UNIFI_CONTROLLER_TYPE:-unifi-os}"

case "$UNIFI_HOST" in
  http://*|https://*) BASE="${UNIFI_HOST%/}" ;;
  *)                  BASE="https://${UNIFI_HOST}" ;;
esac

if [ "$TYPE" = "unifi-os" ]; then PREFIX="/proxy/network"; else PREFIX=""; fi

fetch() {
  curl -sk --max-time 15 -H "X-API-KEY: ${UNIFI_API_KEY}" -H "Accept: application/json" \
    -w '\n%{http_code}' "$1"
}

show() {
  local label="$1" url="$2"
  echo
  echo "=== ${label}"
  echo "    ${url}"
  local raw status body
  raw="$(fetch "$url" || true)"
  status="$(printf '%s' "$raw" | tail -n1)"
  body="$(printf '%s' "$raw" | sed '$d')"
  if [ "$status" != "200" ]; then
    echo "    HTTP ${status}. Skipping."
    if [ "$status" = "401" ] || [ "$status" = "403" ]; then
      echo "    The API key was refused. Check Control Plane > Integrations."
    fi
    return
  fi
  printf '%s' "$body" | python3 -c '
import json, sys
try:
    payload = json.load(sys.stdin)
except ValueError:
    print("    response was not JSON"); raise SystemExit
items = payload.get("data", payload) if isinstance(payload, dict) else payload
if not isinstance(items, list) or not items:
    print("    none found"); raise SystemExit
for item in items:
    if not isinstance(item, dict):
        continue
    name = item.get("name") or item.get("description") or "(unnamed)"
    flag = "enabled " if item.get("enabled") else "disabled"
    tag = "  [predefined, cannot be toggled]" if item.get("predefined") else ""
    print(f"    {item.get(\"_id\",\"?\")}  {flag}  {name}{tag}")
'
}

echo "Console: ${BASE}   site: ${SITE}"
show "Firewall policies (Network 9.x zone based)" "${BASE}${PREFIX}/v2/api/site/${SITE}/firewall-policies"
show "Traffic rules"                              "${BASE}${PREFIX}/v2/api/site/${SITE}/trafficrules"
show "Legacy firewall rules"                      "${BASE}${PREFIX}/api/s/${SITE}/rest/firewallrule"
echo
echo "Copy the ID of the policy you want into UNIFI_POLICY_ID."

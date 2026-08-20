#!/usr/bin/env bash
#
# Print a diagnostic report that is safe to paste into a chat or an issue.
#
# Secrets are masked: API_TOKEN, UNIFI_API_KEY and UNIFI_PASSWORD are shown only
# as their first four characters and a length. Everything else is printed as is,
# because policy names, policy IDs and site names are not secrets.
#
# Usage:
#   sudo scripts/report.sh                    reads /etc/unifi-toggle/unifi-toggle.env
#   sudo scripts/report.sh path/to/env        reads that env file instead
#
# sudo is needed because the env file is deliberately not world readable.
set -uo pipefail

ENV_FILE="${1:-/etc/unifi-toggle/unifi-toggle.env}"

echo "=============================================================="
echo " unifi-toggle diagnostic report"
echo " generated $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================================="

mask() {
  local value="${1:-}"
  if [ -z "$value" ]; then echo "(not set)"; return; fi
  local n=${#value}
  if [ "$n" -le 4 ]; then echo "(set, $n chars, too short to be valid)"; return; fi
  echo "${value:0:4}... ($n chars)"
}

echo
echo "--- host"
echo "kernel:  $(uname -srm)"
echo "distro:  $(. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown}")"
echo "python:  $(python3 -V 2>&1)"

echo
echo "--- env file"
if [ ! -r "$ENV_FILE" ]; then
  echo "cannot read ${ENV_FILE}"
  echo "run this with sudo, or pass the path to your env file as an argument."
  exit 1
fi
echo "path:    ${ENV_FILE}"
echo "perms:   $(stat -c '%A %U:%G' "$ENV_FILE" 2>/dev/null)"

# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

echo
echo "--- configuration (secrets masked)"
printf '%-24s %s\n' "UNIFI_HOST"            "${UNIFI_HOST:-(not set)}"
printf '%-24s %s\n' "UNIFI_CONTROLLER_TYPE" "${UNIFI_CONTROLLER_TYPE:-unifi-os (default)}"
printf '%-24s %s\n' "UNIFI_SITE"            "${UNIFI_SITE:-default (default)}"
printf '%-24s %s\n' "UNIFI_AUTH_MODE"       "${UNIFI_AUTH_MODE:-auto (default)}"
printf '%-24s %s\n' "UNIFI_API_KEY"         "$(mask "${UNIFI_API_KEY:-}")"
printf '%-24s %s\n' "UNIFI_USERNAME"        "${UNIFI_USERNAME:-(not set)}"
printf '%-24s %s\n' "UNIFI_PASSWORD"        "$(mask "${UNIFI_PASSWORD:-}")"
printf '%-24s %s\n' "UNIFI_VERIFY_SSL"      "${UNIFI_VERIFY_SSL:-false (default)}"
printf '%-24s %s\n' "UNIFI_POLICY_NAME"     "${UNIFI_POLICY_NAME:-(not set)}"
printf '%-24s %s\n' "UNIFI_POLICY_ID"       "${UNIFI_POLICY_ID:-(not set)}"
printf '%-24s %s\n' "UNIFI_POLICY_KIND"     "${UNIFI_POLICY_KIND:-auto (default)}"
printf '%-24s %s\n' "API_TOKEN"             "$(mask "${API_TOKEN:-}")"
printf '%-24s %s\n' "BIND_HOST"             "${BIND_HOST:-0.0.0.0 (default)}"
printf '%-24s %s\n' "PORT"                  "${PORT:-8080 (default)}"
printf '%-24s %s\n' "TLS_CERT_FILE"         "${TLS_CERT_FILE:-(not set, serving plain HTTP)}"
printf '%-24s %s\n' "TLS_KEY_FILE"          "${TLS_KEY_FILE:-(not set, serving plain HTTP)}"

echo
echo "--- TLS certificate"
if [ -n "${TLS_CERT_FILE:-}" ] && [ -r "${TLS_CERT_FILE}" ]; then
  openssl x509 -in "${TLS_CERT_FILE}" -noout -subject -ext subjectAltName -dates 2>/dev/null \
    || echo "could not read the certificate"
  echo "The Subject Alternative Name above must match BASE_URL in the Android Config.kt."
else
  echo "(no certificate configured or it is not readable by this user)"
fi

echo
echo "--- systemd"
if command -v systemctl >/dev/null 2>&1; then
  echo "enabled: $(systemctl is-enabled unifi-toggle 2>&1)"
  echo "active:  $(systemctl is-active unifi-toggle 2>&1)"
else
  echo "(systemctl not available on this host)"
fi

PORT="${PORT:-8080}"
if [ -n "${TLS_CERT_FILE:-}" ]; then SCHEME="https"; else SCHEME="http"; fi
BASE_URL="${BASE_URL:-${SCHEME}://127.0.0.1:${PORT}}"

echo
echo "--- service responses (${BASE_URL})"
if [ -z "${API_TOKEN:-}" ]; then
  echo "API_TOKEN is not set, cannot query the service"
else
  for path in /healthz /status; do
    echo "GET ${path}"
    curl -sk --max-time 20 -H "Authorization: Bearer ${API_TOKEN}" \
      -w '\n  HTTP %{http_code}\n' "${BASE_URL}${path}" 2>&1 | sed 's/^/  /'
  done
fi

echo
echo "--- policies visible on the console"
if [ -n "${UNIFI_API_KEY:-}" ] && [ -n "${UNIFI_HOST:-}" ]; then
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [ -x "${HERE}/probe-unifi.sh" ]; then
    "${HERE}/probe-unifi.sh" "$ENV_FILE" 2>&1 | sed 's/^/  /'
  else
    echo "  probe-unifi.sh not found next to this script"
  fi
else
  echo "  (UNIFI_API_KEY or UNIFI_HOST not set, skipping)"
fi

echo
echo "--- recent log"
if command -v journalctl >/dev/null 2>&1; then
  journalctl -u unifi-toggle -n 30 --no-pager 2>&1 | sed 's/^/  /'
else
  echo "  (journalctl not available on this host)"
fi

echo
echo "=============================================================="
echo " End of report. Secrets above are masked and it is safe to"
echo " paste this whole block."
echo "=============================================================="

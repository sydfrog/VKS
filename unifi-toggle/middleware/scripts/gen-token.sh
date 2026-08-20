#!/usr/bin/env bash
# Print a random bearer token suitable for API_TOKEN.
set -euo pipefail
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'

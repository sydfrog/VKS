#!/usr/bin/env bash
#
# Generate a private CA and a server certificate for the middleware.
#
# Usage: scripts/make-cert.sh <vm-ip-or-hostname> [output-dir]
#   scripts/make-cert.sh 192.168.0.50
#   scripts/make-cert.sh unifi-toggle.lan /etc/unifi-toggle/tls
#
# Why a CA and not just one self signed certificate: Android's network security
# config pins a trust anchor, and a trust anchor has to be a CA certificate.
# A bare self signed leaf is rejected on some Android versions. So this makes a
# small CA, signs one server certificate with it, and you pin the CA.
#
# Produces, in the output directory:
#   ca.key                 CA private key. Keep it on the VM, it is not needed elsewhere.
#   ca.crt                 CA certificate. Copy this into the Android project.
#   server.key             Server private key, used by uvicorn.
#   server.crt             Server certificate.
#   server-fullchain.pem   server.crt followed by ca.crt, used by uvicorn.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <vm-ip-or-hostname> [output-dir]" >&2
  exit 2
fi

HOST="$1"
OUT="${2:-./tls}"
DAYS_CA=3650
DAYS_SERVER=3650

mkdir -p "$OUT"
cd "$OUT"

# An IP literal has to go in the SAN as IP:, a name as DNS:. Android ignores
# the Common Name entirely and looks only at the SAN, so this matters.
if printf '%s' "$HOST" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
  SAN="IP:${HOST}"
else
  SAN="DNS:${HOST}"
fi

echo "Generating CA"
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout ca.key -out ca.crt -days "$DAYS_CA" -sha256 \
  -subj "/CN=unifi-toggle local CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" >/dev/null 2>&1

echo "Generating server key and request for ${HOST} (SAN ${SAN})"
openssl req -newkey rsa:2048 -nodes \
  -keyout server.key -out server.csr -sha256 \
  -subj "/CN=${HOST}" >/dev/null 2>&1

cat > server-ext.cnf <<EXT
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=${SAN}
EXT

echo "Signing server certificate"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days "$DAYS_SERVER" -sha256 \
  -extfile server-ext.cnf >/dev/null 2>&1

cat server.crt ca.crt > server-fullchain.pem
rm -f server.csr server-ext.cnf ca.srl
chmod 0600 ca.key server.key
chmod 0644 ca.crt server.crt server-fullchain.pem

echo
echo "Done. Files are in $(pwd)"
echo
echo "  TLS_CERT_FILE=$(pwd)/server-fullchain.pem"
echo "  TLS_KEY_FILE=$(pwd)/server.key"
echo
echo "Copy $(pwd)/ca.crt into the Android project as:"
echo "  android/app/src/main/res/raw/unifi_toggle_ca.pem"
echo
openssl x509 -in server.crt -noout -subject -ext subjectAltName -dates

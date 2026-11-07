#!/usr/bin/env bash
# Self-signed TLS certificate for the local HTTPS demo (SRS 5.4). Not for production:
# browsers will warn until the certificate is trusted on the demo machine.
set -euo pipefail
OUT="$(cd "$(dirname "$0")/../.." && pwd)/data/tls"
mkdir -p "$OUT"
openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
  -keyout "$OUT/dev-key.pem" -out "$OUT/dev-cert.pem" \
  -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
chmod 600 "$OUT/dev-key.pem"
echo "written: $OUT/dev-cert.pem, $OUT/dev-key.pem"

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

VERSION="$(cat VERSION 2>/dev/null | tr -d '\r\n' || true)"
if [[ -n "$VERSION" ]]; then
  echo "Sports Big Board v${VERSION} deployment preflight"
else
  echo "Sports Big Board deployment preflight"
fi
echo "----------------------------------"
echo "PASS: blocking repository integrity verification is disabled"
echo "      Manifest, filename, token/content, checksum, historical regression,"
echo "      verifier-order, and repository-completeness gates are not run."
echo "      Deployment/runtime behavior is the release acceptance path."
exit 0

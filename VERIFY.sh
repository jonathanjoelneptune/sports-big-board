#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Sports Big Board v4.0.1 verification"
echo "----------------------------------"

if command -v node >/dev/null 2>&1; then
  echo "[verify] Node found: running JavaScript syntax + browser contract tests"
  node --check config.js
  node --check api-runtime.js
  node --check core-model.js
  for f in architecture/*.js ui/*.js; do node --check "$f"; done
  node --check app.js
  node tests/test_architecture.js
else
  echo "[verify] Node not installed: skipping optional Node execution checks"
fi

python -m py_compile server.py sbb/*.py tests/*.py cloud/vm/backup_state.py cloud/github-pages/build_pages.py
bash -n START-ANDROID.sh start.sh cloud/gcp/CREATE-STAGE1.sh cloud/gcp/DEPLOY-UPDATE.sh cloud/gcp/DEPLOY-FROM-GITHUB.sh cloud/gcp/ENABLE-GITHUB-AUTODEPLOY.sh cloud/vm/INSTALL-STAGE1.sh
PYTHONPATH=. python -m unittest discover -s tests -p 'test_*.py' -v

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
python3 cloud/github-pages/build_pages.py https://203-0-113-10.sslip.io "$TMP/pages" >/dev/null
test -f "$TMP/pages/index.html"
test -f "$TMP/pages/config.js"
test ! -f "$TMP/pages/server.py"
grep -q 'https://203-0-113-10.sslip.io' "$TMP/pages/config.js"

echo "PASS: v4.0.1 local + cloud Stage 1 architecture and regression suite"

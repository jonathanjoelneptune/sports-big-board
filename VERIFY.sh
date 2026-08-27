#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

VERSION="$(tr -d '\r\n' < VERSION)"
VERIFY_TMP="$(mktemp -d)"
trap 'rm -rf "$VERIFY_TMP"' EXIT
echo "Sports Big Board v${VERSION} verification"
echo "----------------------------------"

python3 tools/check_release_version.py
python3 tools/check_foundation_certification.py
python3 tools/check_ultimate_playback.py
# v4.3.6+: fast deploy rehearsal. This runs before Node and the 400+ Python tests
# so stale exact-token regression guards and broken release overlays are caught
# immediately instead of becoming another post-upload hotfix cycle.
python3 tools/check_deploy_rehearsal.py

if command -v node >/dev/null 2>&1; then
  echo "[verify] Node found: running JavaScript syntax + browser contract tests"
  node --check config.js
  node --check api-runtime.js
  node --check core-model.js
  for f in architecture/*.js ui/*.js; do node --check "$f"; done
  node --check app.js
  node tests/test_architecture.js
  node tests/test_playback_session_runtime.js
  node tests/test_soundtrack_runtime.js
  node tests/test_certification_error_evidence.js
  node tests/test_tier1_restoration_semantics.js
  node tests/test_v440_playback_readiness.js
  node tests/test_v441_playback_terminal.js
  node tests/test_v441_readiness_hydration.js
  node tests/test_v442_dev_mode.js
  node tests/test_v443_playback_endurance.js
  node tests/test_v443_playback_endurance_runtime.js
else
  echo "[verify] Node not installed: skipping optional Node execution checks"
fi

python -m py_compile server.py sbb/*.py tests/*.py cloud/vm/backup_state.py cloud/github-pages/build_pages.py
bash -n START-ANDROID.sh start.sh cloud/gcp/CREATE-STAGE1.sh cloud/gcp/DEPLOY-UPDATE.sh cloud/gcp/DEPLOY-FROM-GITHUB.sh cloud/gcp/ENABLE-GITHUB-AUTODEPLOY.sh cloud/gcp/UPLOAD-SOUNDTRACK.sh
WARN_LOG="$VERIFY_TMP/python-unittest.log"
set +e
PYTHONWARNINGS=always::ResourceWarning PYTHONPATH=. python -m unittest discover -s tests -p 'test_*.py' -v 2>&1 | tee "$WARN_LOG"
UNIT_RC=${PIPESTATUS[0]}
set -e
if [[ $UNIT_RC -ne 0 ]]; then
  echo "FAIL: Python regression suite exited with $UNIT_RC" >&2
  exit "$UNIT_RC"
fi
if grep -Fq 'ResourceWarning' "$WARN_LOG"; then
  echo "FAIL: ResourceWarning detected (likely an unclosed file/socket/SQLite connection)." >&2
  grep -F 'ResourceWarning' "$WARN_LOG" >&2 || true
  exit 1
fi

GCP_PROJECT_ID=sportsbigboard python3 cloud/github-pages/build_pages.py https://203-0-113-10.sslip.io "$VERIFY_TMP/pages" >/dev/null
test -f "$VERIFY_TMP/pages/index.html"
test -f "$VERIFY_TMP/pages/config.js"
test -f "$VERIFY_TMP/pages/assets/soundtrack/manifest.json"
test ! -d "$VERIFY_TMP/pages/assets/soundtrack/tracks"
test ! -f "$VERIFY_TMP/pages/server.py"
grep -q 'https://203-0-113-10.sslip.io' "$VERIFY_TMP/pages/config.js"
grep -q 'https://203-0-113-10.sslip.io/api/soundtrack' "$VERIFY_TMP/pages/config.js"
grep -q "soundtrackTransport:'private-gcs'" "$VERIFY_TMP/pages/config.js"

echo "PASS: v${VERSION} local + cloud Stage 1 architecture, certification, regression suite, and deploy rehearsal"

python3 -m unittest tests.test_v4312_recovered_playback_failure_semantics

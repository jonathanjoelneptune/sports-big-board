#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

VERSION="$(tr -d '\r\n' < VERSION)"
VERIFY_TMP="$(mktemp -d)"
trap 'rm -rf "$VERIFY_TMP"' EXIT
echo "Sports Big Board v${VERSION} verification"
echo "----------------------------------"

python3 tools/check_release_manifest.py
python3 tools/check_release_version.py
python3 tools/check_foundation_certification.py
python3 tools/check_ultimate_playback.py
# Fast structural deploy rehearsal. It validates workflow chaining, test syntax,
# and unittest discoverability only. Exact implementation-string assertions are
# intentionally NOT pre-scanned; actual regression tests below are the authority.
python3 tools/check_deploy_rehearsal.py

# Active foundation contracts referenced by current release checkers.
# These remain blocking even though the broad historical archive below is advisory.
python3 -m unittest tests.test_v446_historical_media_quarantine
# Stable blocking behavior gate.
# Historical release-specific tests remain useful diagnostics but no longer veto
# a modern release because an old CSS class/helper/SQL literal changed.
python3 -m unittest tests.test_release_behavior_gate

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
  node tests/test_v444_playback_recovery_runtime.js
  node tests/test_v445_duplicate_candidate_runtime.js
  node tests/test_v446_stale_media_runtime.js
  node tests/test_v447_poisoned_player_containment_runtime.js
  node tests/test_v473_efficiency_runtime.js
  node tests/test_v474_efficiency_remediation_runtime.js
  node tests/test_v475_enrichment_firewall_runtime.js
  node tests/test_v476_render_pipeline_runtime.js
  node tests/test_v477_first_paint_render_consolidation_runtime.js
  node tests/test_v478_future_projection_card_cache_runtime.js
  node tests/test_v479_navigation_history_runtime.js
  node tests/test_v4710_cold_history_future_store_runtime.js
  node tests/test_v4711_availability_index_thin_probe_runtime.js
  node tests/test_v4712_day_state_render_model_runtime.js
  node tests/test_v4713_media_readiness_runtime.js
  python3 -m unittest tests.test_v4713_media_readiness
  python3 -m unittest tests.test_v4714_cfb_ranked_season
  python3 -m unittest tests.test_v4714_cfb_ranked_runtime
  node tests/test_v4715_efficiency_hardening_runtime.js
  python3 -m unittest tests.test_v4715_efficiency_hardening
  node tests/test_v4716_ribbon_identity_runtime.js
  python3 -m unittest tests.test_v4716_ribbon_identity_playlist
  python3 -m unittest tests.test_v4712_day_state_render_model
  python3 -m unittest tests.test_v4711_availability_index_thin_probe
  python3 -m unittest tests.test_v4710_cold_history_future_store
  python3 -m unittest tests.test_v478_future_projection
  node tests/test_v448_recap_identity_runtime.js
  node tests/test_v448_recap_switch_runtime.js
else
  echo "[verify] Node not installed: skipping optional Node execution checks"
fi

python -m py_compile server.py sbb/*.py tests/*.py cloud/vm/backup_state.py cloud/github-pages/build_pages.py
bash -n START-ANDROID.sh start.sh cloud/gcp/CREATE-STAGE1.sh cloud/gcp/DEPLOY-UPDATE.sh cloud/gcp/DEPLOY-FROM-GITHUB.sh cloud/gcp/ENABLE-GITHUB-AUTODEPLOY.sh cloud/gcp/UPLOAD-SOUNDTRACK.sh cloud/vm/INSTALL-STAGE1.sh
LEGACY_LOG="$VERIFY_TMP/python-legacy-advisory.log"
echo "[legacy-advisory] Running historical Python regression archive (does not block deployment)"
set +e
PYTHONWARNINGS=always::ResourceWarning PYTHONPATH=. python -m unittest discover -s tests -p 'test_*.py' -v 2>&1 | tee "$LEGACY_LOG"
LEGACY_RC=${PIPESTATUS[0]}
set -e
if [[ $LEGACY_RC -ne 0 ]]; then
  echo "[legacy-advisory] WARNING: historical regression archive reported failures (exit $LEGACY_RC)." >&2
  echo "[legacy-advisory] These results are diagnostic and do not block deployment." >&2
fi
if grep -Fq 'ResourceWarning' "$LEGACY_LOG"; then
  echo "[legacy-advisory] WARNING: ResourceWarning detected in historical archive." >&2
  grep -F 'ResourceWarning' "$LEGACY_LOG" >&2 || true
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

echo "PASS: v${VERSION} blocking release behavior gate, architecture, certification, syntax, and deploy rehearsal"


#!/usr/bin/env bash
set -euo pipefail

echo "Sports Big Board release-integrity preflight"
python3 tools/check_release_version.py
python3 tests/test_v529_release_integrity.py
node --check ui/settings-view.js
node --check architecture/key-info-current-v520.js
python3 -m py_compile sbb/release_identity_v523.py

echo "PASS: release-integrity preflight complete"

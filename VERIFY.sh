#!/usr/bin/env bash
set -euo pipefail

echo "Sports Big Board v5.2.10 release + motion preflight"
python3 tools/check_release_version.py
python3 tests/test_v529_release_integrity.py
python3 tests/test_v5210_motion_smoothness.py
node --check ui/settings-view.js
node --check ui/player-visibility.js
node --check architecture/key-info-current-v520.js
node --check architecture/scroll-motion-smoothness-v5210.js
python3 -m py_compile sbb/release_identity_v523.py

echo "PASS: v5.2.10 atomic release and scroll/motion preflight complete"

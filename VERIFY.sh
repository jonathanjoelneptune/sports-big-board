#!/usr/bin/env bash
set -euo pipefail

echo "Sports Big Board v5.2.14 atomic release + Premium Masthead preflight"
python3 tools/check_release_version.py
python3 tests/test_v529_release_integrity.py
python3 tests/test_v5210_motion_smoothness.py
python3 tests/test_v5211_openai_rate_limit.py
python3 tests/test_v5212_splash_preload.py
python3 tests/test_v5213_broadcast_design.py
python3 tests/test_v5214_premium_masthead.py
node --check ui/settings-view.js
node --check ui/player-visibility.js
node --check architecture/key-info-current-v520.js
node --check architecture/scroll-motion-smoothness-v5210.js
node --check architecture/splash-preload-v5212.js
python3 -m py_compile sbb/release_identity_v523.py sbb/current_news_v523.py

echo "PASS: v5.2.14 atomic release + Premium Masthead preflight complete"

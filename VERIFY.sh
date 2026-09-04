#!/usr/bin/env bash
set -euo pipefail

echo "Sports Big Board v5.4.8 Controller Polish + Browse Parity + Fullscreen Exit preflight"
python3 tools/check_release_version.py
python3 tests/test_v529_release_integrity.py
python3 tests/test_v5210_motion_smoothness.py
python3 tests/test_v5211_openai_rate_limit.py
python3 tests/test_v5212_splash_preload.py
python3 tests/test_v5213_broadcast_design.py
python3 tests/test_v5214_premium_masthead.py
python3 tests/test_v5215_now_watching.py
python3 tests/test_v5216_up_next_editorial_slugs.py
python3 tests/test_v5217_drawer_polish.py
python3 tests/test_v5218_workspace_reflow.py
python3 tests/test_v5219_game_center_readability.py
python3 tests/test_v5220_gc_scroll_interrupt_queue.py
python3 tests/test_v5221_collapse_viewport_fit.py
python3 tests/test_v530_browse_curated_programming.py
python3 tests/test_v531_browse_ux_timeline.py
python3 tests/test_v532_team_browse_queue_flow.py
python3 tests/test_v533_browse_integration.py
python3 tests/test_v534_complete_browse_deploy_safety.py
python3 tests/test_v535_persistent_browse_context_identity.py
python3 tests/test_v536_team_focus_enrichment.py
python3 tests/test_v537_focus_integration_theme.py
python3 tests/test_v538_league_view_theme_hardening.py
python3 tests/test_v539_team_context_drawer_sync.py
python3 tests/test_v5310_special_event_playback_league_view.py
python3 tests/test_v5311_playback_context_league_view.py
python3 tests/test_v5312_special_event_playback_standings.py
python3 tests/test_v5313_special_event_ownership_symmetry.py
python3 tests/test_v5314_league_navigation_event_brackets.py
python3 tests/test_v5315_wildcard_media_match_center.py
python3 tests/test_v5316_score_ribbon_league_day_queue.py
python3 tests/test_v5317_queue_performance_match_center.py
python3 tests/test_v5318_verified_play_all_fast_start.py
python3 tests/test_v5319_game_center_score_transition_bumper.py
python3 tests/test_v5320_startup_unfreeze_progress.py
python3 tests/test_v540_controller_readiness.py
python3 tests/test_v541_core_controller_mode.py
python3 tests/test_v542_controller_radials_live_input.py
python3 tests/test_v543_stealth_ultra_hid_bridge.py
python3 tests/test_v544_native_controller_bridge.py
python3 tests/test_v545_controller_navigation_fullscreen_playback_follow.py
python3 tests/test_v546_hierarchical_radials_drawer_fullscreen.py
python3 tests/test_v547_controller_native_browse_sendinput.py
python3 tests/test_v548_controller_polish.py
node --check ui/settings-view.js
node --check ui/up-next-experience-v5217.js
node --check ui/harmonized-controls-drawer-v5217.js
node --check ui/viewing-workspace-v5218.js
node --check ui/game-center-readability-v5219.js
node --check ui/game-center-scroll-v5220.js
node --check ui/collapse-viewport-fit-v5221.js
node --check ui/browse-curated-programming-v537.js
node --check ui/league-view-v538.js
node --check architecture/playback-progress-watchdog-v5310.js
node --check architecture/playback-early-pause-recovery-v538.js
python3 -m py_compile sbb/team_focus_v537.py sbb/league_view_v538.py sbb/__init__.py
node --check ui/workspace-viewport-fit-v531.js
node --check ui/sport-match-center-v5317.js
node --check ui/game-center-score-authority-v5319.js
node --check architecture/playback-transition-bumper-v5319.js
node --check architecture/score-interrupt-queue-v5220.js
node --check ui/player-visibility.js
node --check architecture/key-info-current-v520.js
node --check architecture/scroll-motion-smoothness-v5210.js
node --check architecture/splash-preload-v5212.js
node --check architecture/controller-readiness-v540.js
node --check architecture/controller-mode-v542.js
node --check architecture/controller-native-bridge-v544.js
node --check architecture/controller-hid-bridge-v543.js
node --check ui/fullscreen-controller-v545.js
node --check ui/score-ribbon-playback-follow-v545.js
python3 -m py_compile sbb/release_identity_v523.py sbb/current_news_v523.py
bash -n cloud/gcp/DEPLOY-FROM-GITHUB.sh

echo "PASS: v5.4.8 Controller Polish + Browse Parity + Fullscreen Exit preflight complete"

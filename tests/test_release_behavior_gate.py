import re
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
INDEX=(ROOT/"index.html").read_text(encoding="utf-8")
CORE=(ROOT/"core-model.js").read_text(encoding="utf-8")
DAY_BACKEND=(ROOT/"sbb"/"day_state.py").read_text(encoding="utf-8")
DAY_UI=(ROOT/"architecture"/"day-state.js").read_text(encoding="utf-8")
REG_UI=(ROOT/"architecture"/"competition-registry-projection.js").read_text(encoding="utf-8")
EFFICIENCY=(ROOT/"architecture"/"efficiency-certification.js").read_text(encoding="utf-8")
BROKER=(ROOT/"architecture"/"request-broker.js").read_text(encoding="utf-8")
DATE_COORD=(ROOT/"architecture"/"date-transition-coordinator.js").read_text(encoding="utf-8")
OPERATOR_LOADER=(ROOT/"architecture"/"operator-module-loader.js").read_text(encoding="utf-8")
HIST_MEDIA=(ROOT/"architecture"/"historical-media-v4610.js").read_text(encoding="utf-8")
VERIFY=(ROOT/"VERIFY.sh").read_text(encoding="utf-8")


class ReleaseBehaviorGate(unittest.TestCase):
    """Stable blocking deploy contracts.

    These tests intentionally describe behavior/architecture instead of
    release-specific CSS class names, exact SQL text, or private helper names.
    """

    def test_release_version_and_frontend_cache_handshake(self):
        self.assertRegex(VERSION,r"^\d+\.\d+\.\d+$")
        refs=re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',INDEX)
        self.assertTrue(refs)
        self.assertTrue(all(v==VERSION for _,v in refs))

    def test_launch_screen_has_interactive_start_control(self):
        self.assertIn('id="launchScreen"',INDEX)
        self.assertIn('id="launchPlayBtn"',INDEX)
        self.assertNotIn("new MutationObserver",REG_UI)
        self.assertNotIn(".observe(document.documentElement",REG_UI)

    def test_day_state_endpoint_is_nonblocking_and_cold_ribbon_build_is_serialized(self):
        day_read=DAY_BACKEND[DAY_BACKEND.index("def serve_day_state"):DAY_BACKEND.index("def serve_ribbon")]
        ribbon=DAY_BACKEND[DAY_BACKEND.index("def serve_ribbon"):DAY_BACKEND.index("def engine()")]
        self.assertIn("allow_build=False",day_read)
        self.assertIn("COLD_WARMING",day_read)
        self.assertIn("STALE_REFRESHING",day_read)
        self.assertIn("allow_build=False",ribbon)
        self.assertIn("allow_build=True",ribbon)
        self.assertIn("COLD_FALLBACK_REBUILT",ribbon)
        self.assertIn("self.build_locks",DAY_BACKEND)

    def test_browser_day_state_has_bounded_fallback(self):
        self.assertIn("AbortController",DAY_UI)
        self.assertIn("pending",DAY_UI)
        self.assertIn("fallback(date)",DAY_UI)
        self.assertNotIn("new MutationObserver",DAY_UI)
        self.assertNotIn(".observe(document.documentElement",DAY_UI)

    def test_dynamic_competitions_have_registry_builder_and_local_fallback(self):
        self.assertIn("/api/competition-builder/catalog",REG_UI)
        self.assertIn("/api/competition-registry",REG_UI)
        self.assertIn("localStorage",REG_UI)
        self.assertIn("visibleSpecial",REG_UI)
        self.assertIn("sbbSpecialEventsWrap",REG_UI)
        self.assertIn("sbbSpecialEventsMenu",REG_UI)
        self.assertIn("SPECIAL EVENTS",REG_UI)

    def test_core_model_accepts_dynamic_competition_projection(self):
        self.assertIn("SBB_FRONTEND_REGISTRY?.competitionMap?.()",CORE)
        self.assertIn("SBB_COMPETITION_BUILDER?.competitionMap?.()",CORE)

    def test_registry_render_is_idempotent(self):
        self.assertIn("specialRenderKey",REG_UI)
        self.assertIn("leagueRenderKey",REG_UI)

    def test_efficiency_certification_is_loaded_and_non_destructive(self):
        self.assertIn(f"architecture/efficiency-certification.js?v={VERSION}",INDEX)
        self.assertIn("window.SBB_EFFICIENCY",EFFICIENCY)
        self.assertIn("runAutoTest",EFFICIENCY)
        self.assertIn("runHammer",EFFICIENCY)
        self.assertIn("restoreState",EFFICIENCY)
        self.assertIn("PerformanceObserver",EFFICIENCY)
        self.assertIn("duplicateConcurrent",EFFICIENCY)
        self.assertNotIn("new MutationObserver",EFFICIENCY)
        self.assertNotIn("method:'POST'",EFFICIENCY)
        self.assertNotIn('method:"POST"',EFFICIENCY)

    def test_request_broker_coalesces_and_cancels_superseded_date_work(self):
        self.assertIn("window.SBB_REQUEST_BROKER",BROKER)
        self.assertIn("coalesced",BROKER)
        self.assertIn("cache-hit",BROKER)
        self.assertIn("superseded-date",BROKER)
        self.assertIn("beginDate",BROKER)

    def test_date_transition_coordinator_makes_day_state_primary(self):
        self.assertIn("window.SBB_DATE_TRANSITIONS",DATE_COORD)
        self.assertIn("load:false",DATE_COORD)
        self.assertIn("__sbbFallback",DATE_COORD)
        self.assertIn("scheduleEnrichment",DATE_COORD)
        self.assertIn("SBB_REQUEST_BROKER?.beginDate",DATE_COORD)

    def test_efficiency_reads_broker_network_truth(self):
        self.assertIn("sbb:request-broker",EFFICIENCY)
        self.assertIn("slowestEndpoints",EFFICIENCY)
        self.assertIn("networkPerDateMax",EFFICIENCY)
        self.assertIn("supersededAborts",EFFICIENCY)
        self.assertNotIn("originalFetch = window.fetch.bind(window)",EFFICIENCY)

    def test_enrichment_firewall_keeps_expensive_work_out_of_first_paint(self):
        self.assertIn("Enrichment Firewall",BROKER)
        self.assertIn("deferred-abort",BROKER)
        self.assertIn("deferred-release",BROKER)
        self.assertIn("ON_DEMAND",BROKER)
        self.assertIn("IDLE_ENRICHMENT",BROKER)
        self.assertNotIn("fetch(`/api/history/discovery",DATE_COORD)

    def test_operator_stack_is_lazy_not_normal_big_board_startup(self):
        self.assertIn(f"architecture/operator-module-loader.js?v={VERSION}",INDEX)
        self.assertNotIn(f'<script src="architecture/competition-builder.js?v={VERSION}"></script>',INDEX)
        self.assertNotIn(f'<script src="architecture/competition-builder-v4611.js?v={VERSION}"></script>',INDEX)
        self.assertNotIn(f'<script src="architecture/competition-builder-v4612.js?v={VERSION}"></script>',INDEX)
        self.assertNotIn(f'<script src="architecture/competition-builder-v4613.js?v={VERSION}"></script>',INDEX)
        self.assertIn("window.SBB_OPERATOR_MODULES",OPERATOR_LOADER)
        self.assertNotIn("new MutationObserver",OPERATOR_LOADER)

    def test_day_state_shell_transition_bypasses_legacy_media_barrier(self):
        self.assertIn("dayStateFirstPaint",HIST_MEDIA)
        self.assertIn("__sbbOriginal=original.setDate",HIST_MEDIA)
        self.assertIn("unwrapSetter",DATE_COORD)

    def test_special_event_history_is_prewarmer_enrolled(self):
        self.assertIn("HISTORICAL_COMPLETE_SECONDS",DAY_BACKEND)
        self.assertIn('if typ == "SPECIAL_EVENT"',DAY_BACKEND)
        self.assertIn("prewarm_queued",DAY_BACKEND)
        self.assertIn("v4.7.5 fairness",DAY_BACKEND)

    def test_verify_script_has_no_literal_escaped_command_joins(self):
        self.assertIsNone(re.search(r'\\n(?:python3|python|node|bash)',VERIFY))

    def test_active_foundation_checker_contracts_remain_blocking(self):
        # These commands are explicitly required by current release checkers.
        # Future verification cleanup may not move them into the advisory archive.
        required=(
            "python3 tools/check_foundation_certification.py",
            "python3 tools/check_ultimate_playback.py",
            "python3 -m unittest tests.test_v446_historical_media_quarantine",
            "node tests/test_certification_error_evidence.js",
            "node tests/test_tier1_restoration_semantics.js",
            "node tests/test_v440_playback_readiness.js",
            "node tests/test_v441_playback_terminal.js",
            "node tests/test_v441_readiness_hydration.js",
            "node tests/test_v442_dev_mode.js",
            "node tests/test_v443_playback_endurance.js",
            "node tests/test_v443_playback_endurance_runtime.js",
            "node tests/test_v444_playback_recovery_runtime.js",
            "node tests/test_v445_duplicate_candidate_runtime.js",
            "node tests/test_v446_stale_media_runtime.js",
            "node tests/test_v447_poisoned_player_containment_runtime.js",
            "node tests/test_v473_efficiency_runtime.js",
            "node tests/test_v474_efficiency_remediation_runtime.js",
            "node tests/test_v475_enrichment_firewall_runtime.js",
        )
        for command in required:
            self.assertIn(command,VERIFY)

    def test_legacy_archive_is_advisory_not_release_blocking(self):
        self.assertIn("[legacy-advisory]",VERIFY)
        self.assertIn("does not block deployment",VERIFY)


if __name__=="__main__":
    unittest.main()

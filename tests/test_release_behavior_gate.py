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
FUTURE_DATES=(ROOT/"architecture"/"future-date-navigation.js").read_text(encoding="utf-8")
RENDER_PIPELINE=(ROOT/"architecture"/"render-pipeline.js").read_text(encoding="utf-8")
CARD_CACHE=(ROOT/"architecture"/"card-build-cache.js").read_text(encoding="utf-8")
NAVIGATION_UI=(ROOT/"architecture"/"navigation-ui.js").read_text(encoding="utf-8")
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

    def test_future_scheduled_dates_are_browsable(self):
        self.assertIn("window.SBB_FUTURE_DATES",FUTURE_DATES)
        self.assertIn("picker.removeAttribute('max')",FUTURE_DATES)
        self.assertIn("setFutureShell",FUTURE_DATES)
        self.assertIn("Future scheduled dates are valid Big Board dates",DATE_COORD)
        self.assertNotIn("if(d>today())d=today()",DATE_COORD)

    def test_render_pipeline_coalesces_immediate_duplicate_ribbon_renders(self):
        self.assertIn("window.SBB_RENDER_PIPELINE",RENDER_PIPELINE)
        self.assertIn("same-frame",RENDER_PIPELINE)
        self.assertIn("durationMs",RENDER_PIPELINE)
        self.assertIn("transition owns exactly one first-paint ribbon commit",DATE_COORD)

    def test_efficiency_request_attribution_is_fixed_at_network_start(self):
        self.assertIn("__SBB_EFFICIENCY_RUN_ID",BROKER)
        self.assertIn("runId:String(d.runId",EFFICIENCY)
        self.assertIn("RENDER_P95=",EFFICIENCY)
        self.assertIn("DAY_APPLY_P95=",EFFICIENCY)

    def test_early_launch_bridge_exists_before_app_handler(self):
        self.assertIn("__SBB_LAUNCH_CONTROL_PARSED_AT=performance.now()",INDEX)
        self.assertIn("__SBB_PENDING_LAUNCH",INDEX)
        self.assertIn("launchHandlerReadyMs",EFFICIENCY)

    def test_date_transition_has_one_generation_owned_first_paint_commit(self):
        self.assertIn("beginGeneration",RENDER_PIPELINE)
        self.assertIn("commitGeneration",RENDER_PIPELINE)
        self.assertIn("generation-hold",RENDER_PIPELINE)
        self.assertIn("SBB_RENDER_PIPELINE?.beginGeneration",DATE_COORD)
        self.assertIn("SBB_RENDER_PIPELINE?.commitGeneration",DATE_COORD)

    def test_ribbon_cards_are_batched_off_dom_before_commit(self):
        self.assertIn("document.createDocumentFragment()",RENDER_PIPELINE)
        self.assertIn("fragmentCommits",RENDER_PIPELINE)
        self.assertIn("buildMs",RENDER_PIPELINE)
        self.assertIn("commitMs",RENDER_PIPELINE)

    def test_efficiency_certifies_first_usable_paint_not_background_settle(self):
        self.assertIn("function ribbonFirstUsable",EFFICIENCY)
        self.assertIn("function ribbonFullySettled",EFFICIENCY)
        self.assertIn("FULL_SETTLE_TIMEOUTS=",EFFICIENCY)
        self.assertIn("CARD_BUILD_P95=",EFFICIENCY)
        self.assertIn("DOM_COMMIT_P95=",EFFICIENCY)
        self.assertIn("BROWSER_PAINT_P95=",EFFICIENCY)

    def test_future_catalog_schedule_is_part_of_day_state_projection(self):
        self.assertIn("def _merge_future_catalog_rows",DAY_BACKEND)
        self.assertIn("projectionDiagnostics",DAY_BACKEND)
        self.assertIn("FUTURE_CATALOG_REBUILT",DAY_BACKEND)
        self.assertIn("canonical_future > projected_games",DAY_BACKEND)

    def test_card_helpers_are_cached_only_for_one_render(self):
        self.assertIn("window.SBB_CARD_BUILD_CACHE",CARD_CACHE)
        self.assertIn("WeakMap",CARD_CACHE)
        self.assertIn("beginRender",CARD_CACHE)
        self.assertIn("endRender",CARD_CACHE)
        self.assertIn("SBB_CARD_BUILD_CACHE?.beginRender",RENDER_PIPELINE)
        self.assertIn("SBB_CARD_BUILD_CACHE?.endRender",RENDER_PIPELINE)

    def test_memory_certification_uses_post_restore_window(self):
        self.assertIn("sampleHeapWindow",EFFICIENCY)
        self.assertIn("Heap retained (stabilized)",EFFICIENCY)
        self.assertIn("MEMORY_WINDOW_SPREAD=",EFFICIENCY)
        self.assertIn("CARD_CACHE_HITS=",EFFICIENCY)

    def test_special_events_live_only_in_special_events_menu(self):
        self.assertIn("function normalizedType",REG_UI)
        self.assertIn("eventIcon",REG_UI)
        self.assertIn("sbb-special-main-row-suppressed",REG_UI)
        self.assertIn("#sbbSpecialEventsMenu",NAVIGATION_UI)
        self.assertIn("window.SBB_FRONTEND_REGISTRY?.select",NAVIGATION_UI)

    def test_date_picker_is_custom_themed_and_anchored(self):
        self.assertIn("sbb-date-popover",NAVIGATION_UI)
        self.assertIn("sbb-calendar-grid",NAVIGATION_UI)
        self.assertIn("position:fixed",NAVIGATION_UI)
        self.assertIn("scoreDatePicker",NAVIGATION_UI)
        self.assertIn("topDateSelectBtn,#scoreDayIndicator",NAVIGATION_UI)

    def test_auto_efficiency_sweeps_arrows_and_random_history(self):
        self.assertIn("runHistoricalNavigationSweep",EFFICIENCY)
        self.assertIn("historicalArrowStep",EFFICIENCY)
        self.assertIn("historicalCalendarJump",EFFICIENCY)
        self.assertIn("randomHistoricalDates",EFFICIENCY)
        self.assertIn("thanksgiving",EFFICIENCY)
        self.assertIn("History nav p95",EFFICIENCY)

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
            "node tests/test_v476_render_pipeline_runtime.js",
            "node tests/test_v477_first_paint_render_consolidation_runtime.js",
            "node tests/test_v478_future_projection_card_cache_runtime.js",
            "node tests/test_v479_navigation_history_runtime.js",
            "python3 -m unittest tests.test_v478_future_projection",
        )
        for command in required:
            self.assertIn(command,VERIFY)

    def test_legacy_archive_is_advisory_not_release_blocking(self):
        self.assertIn("[legacy-advisory]",VERIFY)
        self.assertIn("does not block deployment",VERIFY)


if __name__=="__main__":
    unittest.main()

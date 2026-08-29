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

    def test_day_state_http_reads_do_not_build_on_request_thread(self):
        serve=DAY_BACKEND[DAY_BACKEND.index("def serve_day_state"):DAY_BACKEND.index("def engine()")]
        self.assertGreaterEqual(serve.count("allow_build=False"),2)
        self.assertIn("COLD_WARMING",serve)
        self.assertIn("STALE_REFRESHING",serve)

    def test_browser_day_state_has_bounded_fallback(self):
        self.assertIn("AbortController",DAY_UI)
        self.assertIn("pending",DAY_UI)
        self.assertIn("fallback(date)",DAY_UI)

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

    def test_verify_script_has_no_literal_escaped_command_joins(self):
        self.assertIsNone(re.search(r'\\n(?:python3|python|node|bash)',VERIFY))

    def test_legacy_archive_is_advisory_not_release_blocking(self):
        self.assertIn("[legacy-advisory]",VERIFY)
        self.assertIn("does not block deployment",VERIFY)


if __name__=="__main__":
    unittest.main()

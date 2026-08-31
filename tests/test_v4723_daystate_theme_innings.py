import ast
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class V4723HotfixTests(unittest.TestCase):
    def test_runtime_python_compiles_and_repairs_all_date_cardinality(self):
        src=(ROOT/"sbb/runtime_path_repair_v4720.py").read_text(encoding="utf-8")
        ast.parse(src)
        self.assertIn("def _repair_day_state_catalog_projection",src)
        self.assertIn("v4723ReadBoundaryCatalogRepair",src)
        self.assertIn('daymod.DayStateEngine.get = _day_state_get',src)
        self.assertIn('"scope": "ALL_DATES"',src)

    def test_game_center_has_play_by_play_innings_fallback(self):
        src=(ROOT/"architecture/game-center-multisport-view.js").read_text(encoding="utf-8")
        self.assertIn("function timelineInnings(gc)",src)
        self.assertIn("function baseballInnings(gc)",src)
        self.assertIn("RECONCILED FROM PLAY-BY-PLAY",src)
        self.assertIn("baseballLinescoreFallback:'PLAY_BY_PLAY_RECONCILIATION'",src)
        self.assertIn("if(baseballEvent(gc))return baseballCard(gc);",src)

    def test_light_mode_is_static_css_owned_not_mutation_observer_owned(self):
        src=(ROOT/"index.html").read_text(encoding="utf-8")
        self.assertIn("CSS_ONLY_NO_MUTATION_OBSERVER",src)
        self.assertNotIn("new MutationObserver(scheduleRetint)",src)
        self.assertNotIn("function retintDarkSurfaces()",src)
        self.assertIn("#scoreFilters > .sbb-active-event-filter",src)
        self.assertIn("html[data-sbb-theme=\"light\"] body #sbbSpecialEventsMenu",src)

    def test_balanced_background_has_general_gap_lane_and_stale_audit_rebase(self):
        src=(ROOT/"sbb/runtime_path_repair_v4720.py").read_text(encoding="utf-8")
        self.assertIn("def _install_background_progress_policy",src)
        self.assertIn("idx not in {1,4,5}",src)
        self.assertIn("def _restart_stale_database_audit",src)
        self.assertIn("release_rebuild_pending_events",src)
        self.assertIn("def _llws_periodic_recovery",src)

if __name__=="__main__":
    unittest.main()

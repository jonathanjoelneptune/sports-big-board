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

    def test_light_mode_has_dynamic_dark_surface_cleanup(self):
        src=(ROOT/"index.html").read_text(encoding="utf-8")
        self.assertIn('data-sbb-light-auto="1"',src)
        self.assertIn("function retintDarkSurfaces()",src)
        self.assertIn("function darkSurface(el)",src)
        self.assertIn("attributeFilter:['class','style']",src)
        self.assertIn(".coverage-pipeline",src)
        self.assertIn(".sport-feed-diagnostics",src)

if __name__=="__main__":
    unittest.main()

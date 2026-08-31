import ast
import re
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=(ROOT/"sbb"/"runtime_path_repair_v4720.py").read_text(encoding="utf-8")
INDEX=(ROOT/"index.html").read_text(encoding="utf-8")
GC=(ROOT/"architecture"/"game-center-multisport-view.js").read_text(encoding="utf-8")


class V4722LlwsThemeWinProbTests(unittest.TestCase):
    def test_runtime_parses_and_contains_exact_llws_playlist_manifest(self):
        tree=ast.parse(RUNTIME)
        manifest=None
        for node in tree.body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="LLWS_ESPN_2026_GAME_MANIFEST" for t in node.targets):
                manifest=ast.literal_eval(node.value)
                break
        self.assertIsNotNone(manifest)
        self.assertEqual(len(manifest),35)
        titles=[row[2] for row in manifest]
        self.assertTrue(all("Little League World Series" in title for title in titles))
        self.assertTrue(all("Region Championship" not in title for title in titles))
        self.assertIn("Curaçao vs. Nevada Championship Highlights | Little League World Series",titles)
        self.assertIn("A WALK-OFF WIN 🔥 Ohio vs. Japan | Full Game Highlights | Little League World Series",titles)
        self.assertIn("Canada vs. South Korea | Full Game Highlights | Little League World Series",titles)

    def test_llws_alias_bridge_covers_actual_ribbon_location_forms(self):
        self.assertIn('"JPN":"Japan"',RUNTIME)
        self.assertIn('"CUW":"Curaçao"',RUNTIME)
        self.assertIn("TRAILING_US_STATE_CODE",RUNTIME)
        self.assertIn("TRAILING_COUNTRY_CODE",RUNTIME)
        self.assertIn("_install_llws_trailing_code_alias_bridge()",RUNTIME)
        self.assertIn("_seed_llws_espn_playlist_manifest(server)",RUNTIME)

    def test_light_mode_is_persistent_and_global(self):
        self.assertIn('id="themeToggleBtn"',INDEX)
        self.assertIn("dataset.sbbTheme",INDEX)
        self.assertIn("localStorage.setItem(KEY,theme)",INDEX)
        self.assertIn('html[data-sbb-theme="light"]',INDEX)
        self.assertIn("--sbb-light-red:#c73f3a",INDEX)
        self.assertIn("--sbb-light-blue:#246fae",INDEX)
        self.assertIn("sbb:themechange",INDEX)

    def test_win_probability_uses_graph_not_table(self):
        self.assertIn('class="gc-win-chart"',GC)
        self.assertIn('<polyline class="gc-win-line gc-win-away"',GC)
        self.assertIn('<polyline class="gc-win-line gc-win-home"',GC)
        self.assertIn('aria-label="Win probability graph',GC)
        self.assertNotIn("gc-win-prob-table",GC)


if __name__=="__main__":
    unittest.main()

import ast
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/"sbb"/"day_state.py").read_text(encoding="utf-8")


class V478FutureProjectionTests(unittest.TestCase):
    def test_day_state_source_parses(self):
        ast.parse(SOURCE)

    def test_future_catalog_rows_are_merged_before_plans(self):
        merge=SOURCE.index("score_rows, projection_diagnostics = _merge_future_catalog_rows")
        plans=SOURCE.index("plans = plans_fn(day, score_rows)")
        self.assertLess(merge,plans)

    def test_future_incomplete_snapshot_has_narrow_repair(self):
        self.assertIn("canonical_future > projected_games",SOURCE)
        self.assertIn('"state":"FUTURE_CATALOG_REBUILT"',SOURCE)
        self.assertIn("if day > self.today()",SOURCE)

    def test_future_projection_does_not_replace_normal_history(self):
        self.assertIn('if not diagnostics["future"]:',SOURCE)
        self.assertIn('return normalized, diagnostics',SOURCE)


if __name__=="__main__":
    unittest.main()

import ast
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/"sbb"/"day_state.py").read_text(encoding="utf-8")
MERGE_SOURCE=SOURCE[
    SOURCE.index("def _merge_future_catalog_rows"):
    SOURCE.index("\n\nclass DayStateStore")
]


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

    def test_catalog_projection_repairs_all_dates_without_replacing_primary_rows(self):
        # v4.7.20+ correctness contract:
        # history_catalog_event is canonical for event existence on historical and
        # future dates. The merge may fill a missing event identity on any date,
        # but existing provider/history-day rows remain primary and are never
        # overwritten by the catalog fallback.
        self.assertIn('"catalogMergeScope": "ALL_DATES"',MERGE_SOURCE)
        self.assertNotIn('if not diagnostics["future"]:',MERGE_SOURCE)
        self.assertIn(
            'existing[league] = {_event_identity(row) for row in rows if _event_identity(row)}',
            MERGE_SOURCE,
        )
        self.assertIn(
            'if identity and identity in existing.setdefault(league, set()):',
            MERGE_SOURCE,
        )
        self.assertIn('normalized.setdefault(league, []).append(event)',MERGE_SOURCE)
        self.assertIn('return normalized, diagnostics',MERGE_SOURCE)


if __name__=="__main__":
    unittest.main()

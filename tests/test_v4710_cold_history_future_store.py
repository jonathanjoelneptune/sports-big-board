import ast
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DAY=(ROOT/"sbb"/"day_state.py").read_text(encoding="utf-8")
STORE=(ROOT/"architecture"/"score-date-store.js").read_text(encoding="utf-8")
COORD=(ROOT/"architecture"/"date-transition-coordinator.js").read_text(encoding="utf-8")


class V4710ColdHistoryFutureStoreTests(unittest.TestCase):
    def test_day_state_source_parses(self):
        ast.parse(DAY)

    def test_thin_snapshot_has_no_media_plan_builder(self):
        start=DAY.index("def _build_thin_catalog_snapshot")
        end=DAY.index("def _cold_historical_thin",start)
        block=DAY[start:end]
        self.assertIn('"eventPlans":{}',block)
        self.assertNotIn("_history_day_ribbon_plans",block)
        self.assertNotIn("plans_fn",block)

    def test_cold_past_thin_happens_before_focus_queue(self):
        thin=DAY.index("payload = self._cold_historical_thin(day)")
        focus=DAY.index("self.focus(day)",thin)
        self.assertLess(thin,focus)

    def test_score_store_preserves_future_dates(self):
        self.assertIn("return raw;",STORE)
        self.assertNotIn("return raw>localDateISO(0)?localDateISO(0):raw",STORE)

    def test_date_coordinator_has_no_history_ribbon_first_paint(self):
        self.assertNotIn("legacyRibbonFallback",COORD)
        self.assertNotIn("COLD_CANONICAL_RIBBON",COORD)


if __name__=="__main__":
    unittest.main()

import ast
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DAY=(ROOT/"sbb"/"day_state.py").read_text(encoding="utf-8")
EFF=(ROOT/"architecture"/"efficiency-certification.js").read_text(encoding="utf-8")
INDEX=(ROOT/"architecture"/"score-card-availability-index.js").read_text(encoding="utf-8")

class V4711ThinProbeAvailabilityIndexTests(unittest.TestCase):
    def test_day_state_source_parses(self):
        ast.parse(DAY)
    def test_thin_probe_has_dedicated_route_and_minimal_payload(self):
        self.assertIn('def serve_thin_probe',DAY)
        self.assertIn('parsed.path == "/api/day-state/thin"',DAY)
        start=DAY.index('def serve_thin_probe'); end=DAY.index('def serve_day_state',start)
        block=DAY[start:end]
        self.assertIn('_catalog_score_rows_for_day',block)
        self.assertNotIn('_history_day_ribbon_plans',block)
        self.assertNotIn('self.store.put',block)
        self.assertNotIn('self.focus(',block)
    def test_probe_report_exposes_server_error_details(self):
        self.assertIn('/api/day-state/thin?date=',EFF)
        self.assertIn('http=${x.httpStatus',EFF)
        self.assertIn('error=${x.error',EFF)
        self.assertIn('message=${x.message',EFF)
    def test_availability_index_keeps_unknown_fallback(self):
        self.assertIn('stableKey',INDEX)
        self.assertIn('originalPlayable(match)',INDEX)
        self.assertIn("kind:'verified'",INDEX)
        self.assertIn("kind:'scheduled'",INDEX)
        self.assertIn("kind:'thin-score-only'",INDEX)
if __name__=="__main__": unittest.main()

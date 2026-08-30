import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
INDEX=(ROOT/"index.html").read_text(encoding="utf-8")
EFF=(ROOT/"architecture"/"efficiency-certification.js").read_text(encoding="utf-8")
AVAIL=(ROOT/"architecture"/"score-card-availability-index.js").read_text(encoding="utf-8")
RENDER=(ROOT/"architecture"/"render-pipeline.js").read_text(encoding="utf-8")
NATIVE=(ROOT/"architecture"/"native-transport.js").read_text(encoding="utf-8")


class V4712DayStateRenderModelTests(unittest.TestCase):
    def test_native_transport_precedes_request_broker(self):
        native=INDEX.index("architecture/native-transport.js")
        broker=INDEX.index("architecture/request-broker.js")
        self.assertLess(native,broker)
        self.assertIn("capturedFetch",NATIVE)

    def test_thin_probe_uses_native_api_aware_transport(self):
        self.assertIn("window.SBB_NATIVE_TRANSPORT?.fetch",EFF)
        self.assertIn("window.SBB_NATIVE_TRANSPORT?.url?.(path)",EFF)
        probe=EFF[EFF.index("async function probeColdThinHistory"):EFF.index("function candidateFilters")]
        self.assertNotIn("await fetch(",probe)

    def test_day_state_event_plans_are_primary_media_fast_path(self):
        self.assertIn("canonical Day State eventPlans",AVAIL)
        self.assertIn("catalogPlanForScoreGame",AVAIL)
        self.assertIn("payload?.eventPlans",AVAIL)
        self.assertIn("plan?.playable",AVAIL)
        self.assertIn("kind:'day-state-plan'",AVAIL)
        self.assertIn("originalPlayable(match)",AVAIL)

    def test_long_tasks_are_correlated_to_render_intervals(self):
        self.assertIn("perfStartedAt",RENDER)
        self.assertIn("perfFinishedAt",RENDER)
        self.assertIn("function attributeLongTask",EFF)
        self.assertIn("'LONGEST TASKS'",EFF)
        self.assertIn("availabilityFallbacks",EFF)


if __name__=="__main__":
    unittest.main()

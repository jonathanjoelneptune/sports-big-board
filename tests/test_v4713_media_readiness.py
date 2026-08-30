import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EFF=(ROOT/"architecture"/"efficiency-certification.js").read_text(encoding="utf-8")
AVAIL=(ROOT/"architecture"/"score-card-availability-index.js").read_text(encoding="utf-8")
RENDER=(ROOT/"architecture"/"render-pipeline.js").read_text(encoding="utf-8")
class V4713MediaReadinessTests(unittest.TestCase):
    def test_media_readiness_is_separate_from_first_paint(self):
        self.assertIn("function waitForMediaReadiness",EFF)
        self.assertIn("mediaReadyMs",EFF)
        self.assertIn("mediaKnownGames",EFF)
        self.assertIn("mediaReadyGames",EFF)
        self.assertIn("'MEDIA READINESS'",EFF)
    def test_only_known_database_media_is_required(self):
        self.assertIn("knownDatabaseMedia:true",AVAIL)
        self.assertIn("knownMediaGames",AVAIL)
        self.assertIn("readyKnownMediaKeys",AVAIL)
        self.assertIn("NO_KNOWN_DATABASE_MEDIA",EFF)
    def test_render_reports_consumed_known_media(self):
        self.assertIn("availabilityKnownMediaGames",RENDER)
        self.assertIn("availabilityMediaReadyGames",RENDER)
        self.assertIn("availabilityMediaReadyComplete",RENDER)
    def test_native_thin_probe_avoids_custom_header_preflight(self):
        start=EFF.index("async function probeColdThinHistory")
        end=EFF.index("function candidateFilters",start)
        block=EFF[start:end]
        self.assertIn("credentials:'omit'",block)
        self.assertNotIn("X-SBB-Efficiency-Run",block)
if __name__=="__main__":unittest.main()

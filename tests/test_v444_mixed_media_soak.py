import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TERM=(ROOT/'architecture'/'playback-terminal.js').read_text(encoding='utf-8')
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
VERIFY=(ROOT/'VERIFY.sh').read_text(encoding='utf-8')
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
MANIFEST=(ROOT/'release-manifest.json').read_text(encoding='utf-8')

class V444MixedMediaSoak(unittest.TestCase):
    def test_release(self):
        self.assertEqual(VERSION,'4.4.4')
        self.assertIn('Sports Big Board — v4.4.4',INDEX)
        self.assertIn('START 60M',INDEX)
    def test_sixty_minute_mixed_phases(self):
        self.assertIn("label:'WARMUP',durationMs:10*60_000",TERM)
        self.assertIn("label:'MIXED SOAK',durationMs:30*60_000",TERM)
        self.assertIn("label:'MIXED HAMMER',durationMs:20*60_000",TERM)
        self.assertIn('MIN_SUCCESSFUL_STARTS=150',TERM)
        self.assertIn('MIN_TRANSITIONS=149',TERM)
    def test_color_sport_date_and_transport_diversity(self):
        self.assertIn("QUALITY_ROTATION=Object.freeze(['GREEN','PURPLE','BLUE'])",TERM)
        self.assertIn('MIN_SPORTS=3',TERM)
        self.assertIn('MIN_DATES=3',TERM)
        self.assertIn('MIN_DATE_CHANGES=10',TERM)
        self.assertIn('MIN_TRANSPORTS=2',TERM)
        self.assertIn("querySelectorAll?.('#scoreCells .score-card.has-highlights')",TERM)
        self.assertIn("highlight-recap",TERM)
        self.assertIn("highlight-extended",TERM)
        self.assertIn("highlight-blue",TERM)
        self.assertIn('switchStressDate',TERM)
        self.assertIn('setScoreDate',TERM)
    def test_no_repeat_and_recovery_chain(self):
        self.assertIn('seenMediaKeys',TERM)
        self.assertIn('REPEATED_MEDIA',TERM)
        self.assertIn('retryAttempts',TERM)
        self.assertIn('retrySuccesses',TERM)
        self.assertIn('fallbacks',TERM)
        self.assertIn('ASSET_BAD',TERM)
        self.assertIn('restoreMediaKey',TERM)
        self.assertIn('forcePlaybackEngineReset',TERM)
        self.assertIn('unrecoveredBlanks',TERM)
    def test_verify_executes_runtime_recovery(self):
        self.assertIn('node tests/test_v444_playback_recovery_runtime.js',VERIFY)
    def test_atomic_release_manifest_gate(self):
        self.assertIn('\"release\": \"4.4.4\"',MANIFEST)
        self.assertIn('release-manifest.json',MANIFEST)
        self.assertIn('tools/check_release_manifest.py',MANIFEST)
        self.assertIn('python3 tools/check_release_manifest.py',VERIFY)

if __name__=='__main__': unittest.main()

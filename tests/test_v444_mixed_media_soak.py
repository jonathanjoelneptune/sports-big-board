import re
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TERM=(ROOT/'architecture'/'playback-terminal.js').read_text(encoding='utf-8')
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
VERIFY=(ROOT/'VERIFY.sh').read_text(encoding='utf-8')
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()

def value(name):
    m=re.search(rf'const {re.escape(name)}=(\d+)',TERM)
    return int(m.group(1)) if m else -1

class V444MixedMediaSoak(unittest.TestCase):
    def test_release_baseline_or_newer(self):
        self.assertGreaterEqual(tuple(map(int,VERSION.split('.'))),(4,4,4))
        self.assertIn(f'Sports Big Board — v{VERSION}',INDEX)
        self.assertIn('START 60M',INDEX)
    def test_sixty_minute_mixed_phases(self):
        self.assertIn("label:'WARMUP',durationMs:10*60_000",TERM)
        self.assertIn("label:'MIXED SOAK',durationMs:30*60_000",TERM)
        self.assertIn("label:'MIXED HAMMER',durationMs:20*60_000",TERM)
        self.assertGreaterEqual(value('MIN_SUCCESSFUL_STARTS'),150)
        self.assertGreaterEqual(value('MIN_TRANSITIONS'),149)
    def test_color_sport_date_and_transport_diversity(self):
        self.assertIn("QUALITY_ROTATION=Object.freeze(['GREEN','PURPLE','BLUE'])",TERM)
        self.assertGreaterEqual(value('MIN_SPORTS'),3)
        self.assertGreaterEqual(value('MIN_DATES'),3)
        self.assertGreaterEqual(value('MIN_DATE_CHANGES'),10)
        self.assertGreaterEqual(value('MIN_TRANSPORTS'),2)
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
        self.assertIn('markRuntimeMediaFailed',TERM)
        self.assertIn('unrecoveredBlanks',TERM)
    def test_verify_executes_runtime_recovery(self):
        self.assertIn('node tests/test_v444_playback_recovery_runtime.js',VERIFY)

if __name__=='__main__': unittest.main()

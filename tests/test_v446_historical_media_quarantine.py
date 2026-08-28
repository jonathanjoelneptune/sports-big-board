import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TERM=(ROOT/'architecture'/'playback-terminal.js').read_text(encoding='utf-8')
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
VERIFY=(ROOT/'VERIFY.sh').read_text(encoding='utf-8')
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()

class V446HistoricalMediaQuarantine(unittest.TestCase):
    def test_release(self):
        self.assertGreaterEqual(tuple(map(int,VERSION.split('.'))),(4,4,6))
        self.assertIn(f'Sports Big Board — v{VERSION}',INDEX)
        self.assertIn('START 30M RECOVERY',INDEX)
    def test_targeted_recovery_profile_exists_without_replacing_full_certification(self):
        for token in ("label:'RECOVERY SOAK',durationMs:15*60_000","label:'RECOVERY HAMMER',durationMs:15*60_000","RECOVERY_TOTAL_MS","profile:'full'","preferNFL:true","startRecovery"):
            self.assertIn(token,TERM)
        self.assertIn('START 60M',INDEX)
    def test_stale_media_is_quarantined_not_treated_as_system_failure(self):
        for token in ('STALE_MEDIA','staleMedia','quarantineStaleMedia','markRuntimeMediaFailed',"HTTP 410 stale historical media",'providerFailure:false','tryScoreMediaFallback','quarantinedMediaKeys','QUARANTINED_MEDIA_RESELECTED'):
            self.assertIn(token,TERM)
        self.assertIn("if(failures===1)",TERM)
        self.assertIn("restoreMediaKey",TERM)
        self.assertIn("endurance.noFrameStreak=0",TERM)
    def test_find_recap_and_missing_media_are_nonblocking(self):
        for token in ('NO_MEDIA_SKIP','noMediaSkips','noteNoMediaCards','FIND RECAP / no playable asset'):
            self.assertIn(token,TERM)
    def test_report_separates_catalog_quality_from_player_failure(self):
        for token in ('STALE_MEDIA=','NO_MEDIA_SKIP=','FALLBACK_OK=','QUARANTINE_RESELECT=','RAW_NOFRAME='):
            self.assertIn(token,TERM)
    def test_verify_executes_v446_guards(self):
        self.assertIn('python3 -m unittest tests.test_v446_historical_media_quarantine',VERIFY)
        self.assertIn('node tests/test_v446_stale_media_runtime.js',VERIFY)

if __name__=='__main__': unittest.main()

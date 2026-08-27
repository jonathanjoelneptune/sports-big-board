import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'app.js').read_text(encoding='utf-8')
TERM=(ROOT/'architecture'/'playback-terminal.js').read_text(encoding='utf-8')
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
CORE=(ROOT/'core-model.js').read_text(encoding='utf-8')

class V443PlaybackEndurance(unittest.TestCase):
    def test_semantic_recap_completion_prevents_same_game_alternate(self):
        block=APP[APP.index('function advanceAfterCompletedItem'):APP.index('function advance(direction=1)')]
        self.assertIn('!isFullRecapCandidate(finished)',block)
        self.assertNotIn('!finished?.overview',block)
    def test_transient_failures_do_not_permanently_poison_assets(self):
        block=APP[APP.index('function markRuntimeMediaFailed'):APP.index('function mediaMatchesScoreGame')]
        self.assertIn('playbackFailureIsAssetSpecific(reason)',block)
        self.assertIn('noteTransientPlaybackFailure(item,reason)',block)
        self.assertIn('RUNTIME_UNPLAYABLE_MEDIA.add(key)',block)
    def test_engine_circuit_breaker_and_zero_extra_decoders(self):
        self.assertIn('PLAYBACK_ENGINE_FAILURE_THRESHOLD=3',APP)
        self.assertIn('function resetPlaybackEngine',APP)
        prepared=APP[APP.index('function scorePreparedLimit'):APP.index('function scoreServerWarmLimit')]
        self.assertIn('return 0;',prepared)
    def test_recent_final_refill_is_three_days(self):
        self.assertIn('RECENT_HISTORY_AUTOFILL_DAYS=3',APP)
        self.assertIn('scheduleRecentHistoricalRecapFill(date)',APP)
    def test_terminal_endurance_phases_and_failure_guards(self):
        self.assertIn("label:'WARMUP',durationMs:5*60_000",TERM)
        self.assertIn("label:'SOAK',durationMs:15*60_000",TERM)
        self.assertIn("label:'HAMMER',durationMs:10*60_000",TERM)
        self.assertIn('DUPLICATE_GAME_RECAP',TERM)
        self.assertIn('UNRECOVERABLE_NO_FIRST_FRAME',TERM)
        self.assertIn('chaosDisruptStandby',TERM)
    def test_release_version_and_controls(self):
        self.assertEqual((ROOT/'VERSION').read_text().strip(),'4.4.3')
        self.assertIn('playbackEnduranceStart',INDEX)
        self.assertIn('playbackEnduranceStop',INDEX)
        self.assertIn('app.js?v=4.4.3',INDEX)
        self.assertIn("version:'4.4.3'",CORE)

if __name__=='__main__': unittest.main()

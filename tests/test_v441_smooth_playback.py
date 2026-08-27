import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'app.js').read_text(encoding='utf-8'); READY=(ROOT/'architecture/playback-readiness.js').read_text(encoding='utf-8'); INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
class V441SmoothPlaybackContracts(unittest.TestCase):
    def test_active_stream_has_priority_over_speculative_warmers(self):
        self.assertIn('const SCORE_MEDIA_PRIME_MAX_ACTIVE = 1;',APP);self.assertIn('STANDBY_ACTIVE_RUNWAY_SECONDS=5',APP);self.assertIn('backgroundWarmAllowed()',APP);self.assertIn('cancelPreparedWarmersForPlaybackPressure',APP)
    def test_automatic_transition_never_cold_promotes_unready_media(self):
        block=APP[APP.index('function performSwapWhenReady'):APP.index('function doSwap')]
        self.assertIn('STANDBY_TRANSITION_MAX_WAIT_MS',block);self.assertIn('PREPARING VERIFIED VIDEO',block);self.assertNotIn('bounded cold fallback',block);self.assertNotIn('PlaybackController.tuneProgramIndex(chosen',block)
    def test_durable_readiness_is_hydrated_into_browser(self):
        for token in ('hydrateFromServer','playbackReadiness','serverUpdatedAt','reliability_score'):
            self.assertIn(token,READY)
    def test_dev_terminal_is_below_player(self):
        self.assertIn('id="playbackTerminal"',INDEX);self.assertIn('architecture/playback-terminal.js?v=4.4.1',INDEX);self.assertLess(INDEX.index('id="stage"'),INDEX.index('id="playbackTerminal"'));self.assertLess(INDEX.index('id="playbackTerminal"'),INDEX.index('lower-third player-footer'))
if __name__=='__main__':unittest.main()

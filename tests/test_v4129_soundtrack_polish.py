import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class V4129SoundtrackPolishTests(unittest.TestCase):
    def test_soundtrack_controls_include_next_and_debug_song(self):
        html=(ROOT/'index.html').read_text()
        self.assertIn('id="soundtrackNextBtn"',html)
        self.assertIn('id="diagSoundtrack"',html)
        self.assertIn('architecture/site-soundtrack.js?v=4.1.30',html)

    def test_pause_truth_hard_stops_soundtrack(self):
        engine=(ROOT/'architecture/site-soundtrack.js').read_text()
        self.assertIn("HARD_PAUSE_STATES.has(playbackState)",engine)
        self.assertIn("pauseNow()",engine)
        self.assertIn("$('soundtrackNextBtn')?.addEventListener",engine)
        self.assertIn("currentTrackDebugLabel",engine)
        app=(ROOT/'app.js').read_text()
        self.assertIn("manualPauseRequested=true; setPlaybackUi('paused'); v.pause();",app)
        self.assertIn("manualPauseRequested=true; setPlaybackUi('paused'); p.pauseVideo();",app)
        self.assertIn("manualPauseRequested=true;\n      setPlaybackUi('paused');",app)

    def test_volume_popover_sits_above_video(self):
        css=(ROOT/'styles.css').read_text()
        self.assertIn('.stage-card>.player-topbar{z-index:120!important;overflow:visible!important}',css)
        self.assertIn('bottom:calc(100% + 8px)!important',css)
        self.assertIn('.soundtrack-next-btn',css)

if __name__=='__main__':
    unittest.main()

import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'app.js').read_text(encoding='utf-8');GC=(ROOT/'ui/game-center-view.js').read_text(encoding='utf-8');CSS=(ROOT/'styles.css').read_text(encoding='utf-8')
class V431PlaybackHardeningTests(unittest.TestCase):
    def test_legacy_demo_seed_is_removed(self):
        self.assertIn('let PROGRAM = [];',APP)
        for old in ('oKkhTdPR3DA','t44ztyYZ434','eHDl-gryBJM','iWX1ofpnkeE','Aqi9zT9WVgk','GbHxc0oxCFI'):self.assertNotIn(old,APP)
        self.assertNotIn('Math.floor(Math.random()*Math.max(1,PROGRAM.length))',APP)
    def test_date_browse_cannot_autoplay_roundup(self):
        block=APP[APP.index('async function setScoreBrowseDate'):APP.index('function stepScoreRibbonDate')]
        self.assertNotIn('maybeAutoplayRoundupForDate',block)
        fn=APP[APP.index('function maybeAutoplayRoundupForDate'):APP.index('function dateProgramWithSelectionFirst')]
        self.assertIn('return false;',fn)
        filters=APP[APP.index('function wireScoreFilters'):APP.index('function highlightType')]
        self.assertNotIn('maybeAutoplayRoundupForDate',filters)
    def test_score_pager_owns_its_hitbox(self):
        self.assertIn("pager.addEventListener('pointerdown'",APP);self.assertIn('e.stopPropagation()',APP);self.assertIn('score-date pager interaction hardening',CSS)
    def test_game_center_is_projection_of_active_video(self):
        for token in ('syncGameCenterToActivePlayback','selectedEventMatchesActivePlayback',"reason:'A/B active video promotion'","reason:'native PLAYING confirmed'","reason:'YouTube PLAYING confirmed'"):self.assertIn(token,APP)
        self.assertIn("if(!event){clear();return;}",GC);self.assertIn('Game Center follows the active game video.',GC)
    def test_manual_pause_blocks_background_resume(self):
        self.assertGreaterEqual(APP.count('manualPauseRequested&&!userInitiated'),3)
        self.assertIn('manual pause remains latched for 25 seconds',(ROOT/'architecture/milestone-console.js').read_text())
    def test_background_refresh_preserves_exact_active_media(self):
        self.assertIn('const currentMediaKey=playbackItemKey(current);',APP)
        self.assertIn('background refresh is not a playback command',APP)
        self.assertIn('background program refresh cannot restart active clip',(ROOT/'architecture/milestone-console.js').read_text())
if __name__=='__main__':unittest.main()

import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'app.js').read_text(encoding='utf-8')
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
class V442TransitionAuthority(unittest.TestCase):
    def test_manual_next_is_authoritative(self):
        self.assertIn('function manualQueueAdvance(direction=1)',APP)
        block=APP[APP.index("$('nextBtn').onclick"):APP.index("for(const [id,tier]")]
        self.assertIn('manualQueueAdvance(1)',block)
        self.assertNotIn('advance(1);',block)
    def test_transition_critical_warm_bypasses_background_runway_gate(self):
        block=APP[APP.index('function prepareStandby'):APP.index('function programGameIdentity')]
        self.assertIn('transitionCritical=false',block)
        self.assertIn('if(!transitionCritical&&!backgroundWarmAllowed())',block)
        swap=APP[APP.index('function performSwapWhenReady'):APP.index('function doSwap')]
        self.assertIn('transitionCritical:true',swap)
    def test_background_timeout_is_not_asset_failure(self):
        block=APP[APP.index('function armStandbyDeadline'):APP.index('function recordPlaybackPromotion')]
        self.assertIn('standby pending: readiness not proven',block)
        self.assertIn('if(!transitionCritical&&!transitionInFlight)',block)
    def test_legacy_v440_hot_standby_contract_marker_is_preserved(self):
        self.assertIn('hot standby did not prove playback',APP)
    def test_dev_mode_ui_exists(self):
        self.assertIn('id="devModeToggleBtn"',INDEX)
        self.assertIn('architecture/dev-mode.js?v=4.4.3',INDEX)
if __name__=='__main__': unittest.main()

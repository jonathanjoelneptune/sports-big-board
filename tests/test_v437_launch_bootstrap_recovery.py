import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'app.js').read_text(encoding='utf-8')

class V437LaunchBootstrapRecoveryTests(unittest.TestCase):
    def test_launch_always_enters_canonical_playback_controller(self):
        block=APP[APP.index('function startSportsBigBoardExperience()'):APP.index('function wireLaunchScreen()')]
        self.assertIn("PlaybackController.tuneProgramIndex(currentIndex,{userInitiated:true,reason:'launch screen play'})",block)
        self.assertNotIn('if(initialized || playerReady[activeSlot]',block)

    def test_cold_youtube_launch_has_bounded_player_readiness(self):
        start=APP[APP.index('function startAssignedPlayback'):APP.index('function reconcileActiveSlot')]
        self.assertIn('ensurePlaybackSessionTracksAssignment(slot,item,{reason,userInitiated})',start)
        self.assertIn('waitForYouTubeSlotReady(slot,item,expectedEpoch,12000)',start)

    def test_launch_session_is_created_before_iframe_wait(self):
        controller=APP[APP.index('const PlaybackController='):APP.index('window.SBB_PLAYBACK_CONTROLLER=PlaybackController')]
        self.assertLess(controller.index('SBB_PLAYBACK_SESSION?.select?.'),controller.index('startAssignedPlayback(targetSlot,item'))

    def test_unattended_readiness_failure_can_fail_over(self):
        failure=APP[APP.index('function handlePlaybackFailure'):APP.index('function retryActivePlaybackFromGesture')]
        for token in ('if(!userInitiated){','nextVisibleQueueIndex()',"reason:'automatic playback failure recovery'",'AUTO_MEDIA_FAILURE_SKIP'):
            self.assertIn(token,failure)

if __name__=='__main__': unittest.main()

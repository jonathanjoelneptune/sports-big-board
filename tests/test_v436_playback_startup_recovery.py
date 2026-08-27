import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class V436StartupRecoveryTests(unittest.TestCase):
    def test_provider_neutral_startup_watchdog_exists(self):
        app=(ROOT/'app.js').read_text(encoding='utf-8')
        for token in (
            'const PLAYBACK_STARTUP_RECOVERY_MS=10000',
            'function armPlaybackStartupRecovery(slot,item,epoch)',
            'PLAYBACK_STARTUP_RECOVERY',
            'Playback startup did not reach first frame within ${PLAYBACK_STARTUP_RECOVERY_MS} ms',
            'ensurePlaybackSessionTracksAssignment(slot,item',
        ):
            self.assertIn(token,app)

    def test_startup_watchdog_uses_assignment_identity_and_cannot_restart_same_clip(self):
        app=(ROOT/'app.js').read_text(encoding='utf-8')
        block=app[app.index('function armPlaybackStartupRecovery'):app.index('function armPlaybackBufferRecovery')]
        for token in (
            'selection!==playbackSelectionToken','slot!==activeSlot','!slotClaimIsCurrent(slot,epoch,item)',
            "String(current.mediaKey||'')!==key",'current.firstFrameAt','handlePlaybackFailure(slot,new Error',
        ):
            self.assertIn(token,block)
        self.assertNotIn('startAssignedPlayback(',block)
        self.assertNotIn('playVideo()',block)
        self.assertNotIn('loadVideoById',block)

    def test_controller_exact_media_retry_does_not_compete_with_generic_watchdog(self):
        app=(ROOT/'app.js').read_text(encoding='utf-8')
        controller=app[app.index('const PlaybackController='):app.index('window.SBB_PLAYBACK_CONTROLLER=PlaybackController')]
        self.assertGreaterEqual(controller.count('startupWatchdog:false'),2)

    def test_starting_session_gets_media_identity_before_provider_first_frame(self):
        app=(ROOT/'app.js').read_text(encoding='utf-8')
        start=app[app.index('function startAssignedPlayback'):app.index('function reconcileActiveSlot')]
        self.assertIn('ensurePlaybackSessionTracksAssignment(slot,item,{reason,userInitiated})',start)
        helper=app[app.index('function ensurePlaybackSessionTracksAssignment'):app.index('function armPlaybackStartupRecovery')]
        self.assertIn('SBB_PLAYBACK_SESSION?.select?.(descriptor)',helper)
        self.assertIn('SBB_PLAYBACK_SESSION?.assign?.(descriptor)',helper)

    def test_tier1_observation_waits_for_recovery_instead_of_duplicate_start_failure(self):
        js=(ROOT/'architecture'/'milestone-console.js').read_text(encoding='utf-8')
        self.assertIn('const mediaKey=p.mediaKey||h.currentMediaKey()',js)
        self.assertIn("label:'bounded buffering recovery'",js)
        self.assertIn('startup/buffering did not recover within 20000 ms',js)

    def test_confirmed_playing_clears_startup_watchdog(self):
        app=(ROOT/'app.js').read_text(encoding='utf-8')
        yt=app[app.index("if(slot === activeSlot && state === YT.PlayerState.PLAYING)"):app.index("if(slot === activeSlot && (state === YT.PlayerState.PAUSED")]
        self.assertIn('clearPlaybackStartupRecovery()',yt)
        first=app[app.index('function waitForFirstPlayback'):app.index('let playbackRecovery = null')]
        self.assertIn('clearPlaybackStartupRecovery()',first)

if __name__=='__main__':
    unittest.main()

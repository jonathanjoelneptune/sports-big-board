import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'app.js').read_text(encoding='utf-8')
MILESTONE=(ROOT/'architecture'/'milestone-console.js').read_text(encoding='utf-8')
CERT=(ROOT/'architecture'/'foundation-certification.js').read_text(encoding='utf-8')
MANIFEST=(ROOT/'foundation-certification.json').read_text(encoding='utf-8')


class V4311StartupSoakRecoveryTests(unittest.TestCase):
    def test_native_play_promise_cannot_block_first_frame_observation(self):
        self.assertIn('const NATIVE_PLAY_REQUEST_ACK_MS=250',APP)
        native=APP[APP.index("native(slot){ return {"):APP.index("context(slot){ return {")]
        self.assertIn('Promise.race([',native)
        self.assertIn('NATIVE_PLAY_REQUEST_ACK_MS',native)
        self.assertIn("play() pending; controller startup deadline active",native)
        self.assertNotIn("if(p?.then) return p.then",native)

    def test_existing_assignment_and_first_frame_recovery_remain_bounded(self):
        self.assertIn('const PLAYBACK_STARTUP_RECOVERY_MS=10000',APP)
        controller=APP[APP.index('const PlaybackController='):APP.index('window.SBB_PLAYBACK_CONTROLLER=PlaybackController')]
        self.assertIn('waitForFirstPlayback(targetSlot,{timeoutMs:12000',controller)
        self.assertIn("handlePlaybackFailure(targetSlot,new Error('Selected media did not start'),userInitiated)",controller)

    def test_soak_buffering_clock_tracks_one_assignment_even_during_transition(self):
        self.assertIn("const identity=`${selection}|${key}`",MILESTONE)
        self.assertIn('bufferingIdentity!==identity',MILESTONE)
        self.assertIn('longestBufferingMs=Math.max(longestBufferingMs,bufferingMs)',MILESTONE)
        block=MILESTONE[MILESTONE.index("if(state==='buffering')"):MILESTONE.index('const failureCount=',MILESTONE.index("if(state==='buffering')"))]
        self.assertNotIn('!ctx.transitionInFlight',block)

    def test_soak_transition_timeout_gets_bounded_recovery_window(self):
        self.assertIn('transitionTimeoutRecoveries',MILESTONE)
        self.assertIn("label:'soak transition timeout recovery'",MILESTONE)
        self.assertIn('const transitionRecoveryMs=20000',MILESTONE)
        self.assertIn('playback did not recover within ${transitionRecoveryMs} ms',MILESTONE)
        self.assertIn('transitionTimeoutRecoveries++;moved=true',MILESTONE)

    def test_tier2_allows_recovered_timeout_but_not_unrecovered_timeout(self):
        self.assertIn('transitionTimeoutRecoveries===transitionTimeouts',CERT)
        self.assertIn('recovered within 20s',CERT)

    def test_manifest_documents_startup_and_transition_recovery(self):
        self.assertIn('Native video play-request acknowledgment is bounded',MANIFEST)
        self.assertIn('Timed-out game-transition calls are evidence and must recover within 20 seconds',MANIFEST)
        self.assertIn('transitionRecoveryMs',MANIFEST)


if __name__=='__main__':
    unittest.main()

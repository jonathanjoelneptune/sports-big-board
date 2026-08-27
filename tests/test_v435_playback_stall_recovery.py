import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'app.js').read_text(encoding='utf-8')
MILESTONE = (ROOT / 'architecture' / 'milestone-console.js').read_text(encoding='utf-8')


class V435PlaybackStallRecoveryTests(unittest.TestCase):
    def test_post_first_frame_buffering_has_bounded_runtime_watchdog(self):
        self.assertIn('const PLAYBACK_BUFFER_STALL_RECOVERY_MS=8000', APP)
        self.assertIn('if(!item||!snap.firstFrameAt) return;', APP)
        self.assertIn("String(current.state||'')!=='buffering'", APP)
        self.assertIn('PLAYBACK_STALL_RECOVERY', APP)
        self.assertIn('Sustained playback buffering > ${PLAYBACK_BUFFER_STALL_RECOVERY_MS} ms', APP)

    def test_stall_recovery_uses_failure_controller_instead_of_restarting_same_clip(self):
        watchdog = APP[APP.index('function armPlaybackBufferRecovery()'):APP.index('function clearPlaybackRecovery()')]
        self.assertIn('handlePlaybackFailure(slot,new Error(', watchdog)
        self.assertNotIn('startAssignedPlayback(', watchdog)
        self.assertNotIn('restart:true', watchdog)
        unattended = APP[APP.index('// v4.3.6 unattended playback recovery'):APP.index("setPlaybackUi('ready');", APP.index('// v4.3.6 unattended playback recovery'))]
        self.assertIn("reason:'automatic playback failure recovery'", unattended)
        self.assertIn('AUTO_MEDIA_FAILURE_SKIP', unattended)

    def test_tier1_verifies_bounded_recovery_not_perfect_network(self):
        self.assertIn("timeoutMs:20000,label:'bounded buffering recovery'", MILESTONE)
        self.assertIn('recoveredByFailover:', MILESTONE)
        self.assertIn('buffering did not recover within 20000 ms', MILESTONE)
        self.assertNotIn("label:'sustained buffering recovery'", MILESTONE)

    def test_release_gate_persists_stall_recovery_contract(self):
        manifest = (ROOT / 'foundation-certification.json').read_text(encoding='utf-8')
        checker = (ROOT / 'tools' / 'check_foundation_certification.py').read_text(encoding='utf-8')
        self.assertIn('Post-first-frame playback buffering self-recovers', manifest)
        self.assertIn('PLAYBACK_BUFFER_STALL_RECOVERY_MS=8000', checker)
        self.assertIn("timeoutMs:20000,label:'bounded buffering recovery'", checker)


if __name__ == '__main__':
    unittest.main()

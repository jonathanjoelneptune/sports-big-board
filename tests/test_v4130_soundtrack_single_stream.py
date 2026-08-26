import json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class V4132SoundtrackClipScopedTests(unittest.TestCase):
    def test_exactly_one_audio_and_clip_scoped_contract(self):
        src=(ROOT/'architecture/site-soundtrack.js').read_text()
        self.assertEqual(src.count('new Audio()'),1)
        self.assertIn('startExperience',src)
        self.assertIn('syncClip',src)
        self.assertIn("reason:'video-change'",src)
        self.assertIn("advanceTrack('song-ended')",src)
        self.assertIn('experienceStarted&&enabled',src)
        self.assertNotIn('preloadAudio',src)
        for forbidden in ('beginCrossfade','finalizeCrossfade','crossfadeRaf','crossfading','primeNextTrack'):
            self.assertNotIn(forbidden,src)

    def test_manifest_declares_clip_scoped_behavior(self):
        data=json.loads((ROOT/'assets/soundtrack/manifest.json').read_text())
        defs=data['playbackDefaults']
        self.assertTrue(defs['singleActiveAudioStream'])
        self.assertFalse(defs['preloadNextTrack'])
        self.assertFalse(defs['persistentAcrossVideoChanges'])
        self.assertTrue(defs['newSongOnClipChange'])
        self.assertTrue(defs['continueSongsDuringLongClip'])
        self.assertTrue(defs['enabledOnExperienceStart'])

    def test_app_passes_clip_identity_and_launches_soundtrack_explicitly(self):
        app=(ROOT/'app.js').read_text()
        self.assertIn('function soundtrackPlaybackClipKey()',app)
        self.assertIn('SBB_SOUNDTRACK?.setPlaybackState?.(mode,soundtrackPlaybackClipKey())',app)
        self.assertIn('SBB_SOUNDTRACK?.startExperience?.(soundtrackPlaybackClipKey())',app)
        self.assertIn('SBB_SOUNDTRACK?.pauseForSearch?.()',app)
        self.assertIn('SBB_SOUNDTRACK?.resumeFromSearch?.()',app)

    def test_prelaunch_html_state_is_truthfully_off(self):
        html=(ROOT/'index.html').read_text()
        self.assertIn('id="soundtrackToggle"',html)
        self.assertIn('aria-pressed="false"',html)
        self.assertIn('id="soundtrackNextBtn"',html)
        self.assertIn('id="diagSoundtrack"',html)
        self.assertIn('architecture/site-soundtrack.js?v=4.2.0',html)

if __name__=='__main__': unittest.main()

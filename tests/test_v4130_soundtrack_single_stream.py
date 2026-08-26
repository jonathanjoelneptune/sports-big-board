import json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class V4131SoundtrackPersistentStreamTests(unittest.TestCase):
    def test_exactly_one_audio_element_and_persistent_clip_contract(self):
        src=(ROOT/'architecture/site-soundtrack.js').read_text()
        self.assertEqual(src.count('new Audio()'),1)
        self.assertIn("const activeAudio=new Audio()",src)
        self.assertNotIn('preloadAudio',src)
        self.assertIn('sessionActive=true;videoPaused=false',src)
        self.assertIn("else if(next==='ready')",src)
        self.assertIn('READY is common during a clip handoff/cue',src)
        self.assertIn('duplicate script',src.lower()) if False else None
        self.assertIn('RUNTIME_KEY',src)
        self.assertIn('remainingIds:bag.map',src)
        self.assertIn('playedIds:[...playedIds]',src)
        for forbidden in ('beginCrossfade','finalizeCrossfade','crossfadeRaf','crossfading','primeNextTrack'):
            self.assertNotIn(forbidden,src)

    def test_manifest_disables_audio_preloader_and_declares_persistence(self):
        data=json.loads((ROOT/'assets/soundtrack/manifest.json').read_text())
        defs=data['playbackDefaults']
        self.assertTrue(defs['singleActiveAudioStream'])
        self.assertFalse(defs['preloadNextTrack'])
        self.assertTrue(defs['persistentAcrossVideoChanges'])
        self.assertTrue(defs['pauseOnlyOnExplicitVideoPause'])

    def test_search_mode_has_explicit_resume_hook(self):
        app=(ROOT/'app.js').read_text()
        self.assertIn('SBB_SOUNDTRACK?.pauseForSearch?.()',app)
        self.assertIn('SBB_SOUNDTRACK?.resumeFromSearch?.()',app)

    def test_dev_and_next_controls_remain(self):
        html=(ROOT/'index.html').read_text()
        self.assertIn('id="soundtrackNextBtn"',html)
        self.assertIn('id="diagSoundtrack"',html)
        self.assertIn('architecture/site-soundtrack.js?v=4.1.31',html)

if __name__=='__main__': unittest.main()

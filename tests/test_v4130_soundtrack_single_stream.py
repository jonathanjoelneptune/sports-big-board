import json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class V4130SoundtrackSingleStreamTests(unittest.TestCase):
    def test_crossfade_removed_and_single_stream_contract_present(self):
        src=(ROOT/'architecture/site-soundtrack.js').read_text()
        self.assertIn("const activeAudio=new Audio()",src)
        self.assertIn("const preloadAudio=new Audio()",src)
        self.assertIn("preloadAudio.addEventListener?.('play'",src)
        self.assertIn("hardStopActive({reset:true",src)
        self.assertIn("remainingIds:bag.map",src)
        self.assertIn("playedIds:[...playedIds]",src)
        self.assertIn("ev.target.closest?.('#soundtrackControls')",src)
        for forbidden in ('beginCrossfade','finalizeCrossfade','finishCrossfadeForPause','crossfadeRaf','crossfading'):
            self.assertNotIn(forbidden,src)

    def test_manifest_declares_single_active_stream_without_crossfade(self):
        data=json.loads((ROOT/'assets/soundtrack/manifest.json').read_text())
        defs=data['playbackDefaults']
        self.assertTrue(defs['singleActiveAudioStream'])
        self.assertTrue(defs['preloadNextTrack'])
        self.assertNotIn('crossfadeSeconds',defs)
        self.assertEqual(data['version'],2)

    def test_dev_and_next_controls_remain(self):
        html=(ROOT/'index.html').read_text()
        self.assertIn('id="soundtrackNextBtn"',html)
        self.assertIn('id="diagSoundtrack"',html)
        self.assertIn('architecture/site-soundtrack.js?v=4.1.30',html)

if __name__=='__main__': unittest.main()

import json, os, subprocess, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class V4128SoundtrackTests(unittest.TestCase):
    def test_manifest_is_unique_and_long_rotation(self):
        data=json.loads((ROOT/'assets/soundtrack/manifest.json').read_text())
        tracks=data.get('tracks') or []
        ids=[x.get('id') for x in tracks]
        files=[x.get('file') for x in tracks]
        self.assertEqual(len(tracks),113)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(len(files),len(set(files)))
        self.assertGreater(data.get('totalDurationSeconds',0),3*60*60)
        self.assertTrue(data.get('playbackDefaults',{}).get('repeatOnlyAfterBagExhausted'))

    def test_browser_engine_is_site_level_and_persistent(self):
        src=(ROOT/'architecture/site-soundtrack.js').read_text()
        for token in (
            'weightedShuffle', 'rebuildCycle', 'localStorage',
            'setPlaybackState', 'highlightDuckFactor', 'pauseForSearch', 'resumeFromSearch',
            'assets/soundtrack/manifest.json', 'soundtrackBase'
        ):
            self.assertIn(token,src)
        app=(ROOT/'app.js').read_text()
        self.assertIn('SBB_SOUNDTRACK?.setPlaybackState?.(mode)',app)
        self.assertIn('SBB_SOUNDTRACK?.pauseForSearch?.()',app)
        self.assertIn('SBB_SOUNDTRACK?.resumeFromSearch?.()',app)
        html=(ROOT/'index.html').read_text()
        self.assertIn('id="soundtrackToggle"',html)
        self.assertIn('id="soundtrackVolume"',html)
        self.assertIn('architecture/site-soundtrack.js',html)

    def test_pages_ship_manifest_but_not_audio(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'pages'
            env=dict(os.environ,GCP_PROJECT_ID='sportsbigboard')
            subprocess.run(['python3',str(ROOT/'cloud/github-pages/build_pages.py'),'https://example.invalid',str(out)],check=True,env=env,capture_output=True,text=True)
            config=(out/'config.js').read_text()
            self.assertIn('https://example.invalid/api/soundtrack',config)
            self.assertIn("soundtrackTransport:'private-gcs'",config)
            self.assertTrue((out/'assets/soundtrack/manifest.json').exists())
            self.assertFalse((out/'assets/soundtrack/tracks').exists())

    def test_cloud_uploader_accepts_split_zips_and_validates_hashes(self):
        src=(ROOT/'cloud/gcp/UPLOAD-SOUNDTRACK.sh').read_text()
        self.assertIn('Sports-Big-Board-Soundtrack-Pack-*.zip',src)
        self.assertIn('sha256',src)
        self.assertIn('gcloud storage rsync',src)
        self.assertIn('${PROJECT_ID}-soundtrack',src)
        self.assertIn('roles/storage.objectViewer',src)
        self.assertIn('roles/iam.serviceAccountTokenCreator',src)
        self.assertNotIn('--member=allUsers',src)
        self.assertNotIn('public-access-prevention=unspecified',src)

    def test_private_gcs_backend_prefers_signed_redirect_with_proxy_fallback(self):
        src=(ROOT/'server.py').read_text()
        for token in ('/api/soundtrack/tracks/', '_soundtrack_signed_url', ':signBlob', 'SIGNED-GCS', 'PRIVATE-GCS-PROXY', 'SOUNDTRACK_ALLOWED_FILES'):
            self.assertIn(token,src)
        self.assertIn('storage.googleapis.com/download/storage/v1/b/',src)

if __name__=='__main__':
    unittest.main()

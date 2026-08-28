import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sbb.media_intelligence import MediaIntelligenceStore, MusicDetector, MusicResult, MUSIC_SCAN_VERSION

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
INIT=(ROOT/'sbb'/'__init__.py').read_text(encoding='utf-8')
WORKER=(ROOT/'sbb'/'media_intelligence.py').read_text(encoding='utf-8')
DEPLOY=(ROOT/'cloud'/'gcp'/'DEPLOY-FROM-GITHUB.sh').read_text(encoding='utf-8')
INSTALL=(ROOT/'cloud'/'vm'/'INSTALL-STAGE1.sh').read_text(encoding='utf-8')


def make_db(path):
    conn=sqlite3.connect(path)
    conn.execute('''CREATE TABLE history_source_media (
      asset_key TEXT PRIMARY KEY,provider TEXT DEFAULT '',provider_media_id TEXT DEFAULT '',canonical_url TEXT DEFAULT '',title TEXT DEFAULT '',
      duration_seconds REAL DEFAULT 0,published_at TEXT DEFAULT '',validation_state TEXT DEFAULT 'VERIFIED',runtime_state TEXT DEFAULT 'UNKNOWN',
      asset_json TEXT DEFAULT '{}',last_seen_at REAL DEFAULT 0,updated_at REAL DEFAULT 0)''')
    conn.commit();conn.close()


class V450MediaIntelligence(unittest.TestCase):
    def test_release_and_browser_authority(self):
        self.assertGreaterEqual(tuple(map(int,VERSION.split('.'))),(4,5,0))
        self.assertIn(f'architecture/media-intelligence.js?v={VERSION}',INDEX)
        self.assertLess(INDEX.index(f'architecture/site-soundtrack.js?v={VERSION}'),INDEX.index(f'architecture/media-intelligence.js?v={VERSION}'))
        self.assertLess(INDEX.index(f'architecture/media-intelligence.js?v={VERSION}'),INDEX.index(f'app.js?v={VERSION}'))

    def test_worker_auto_installs_and_deploy_provisions_audio_tools(self):
        self.assertIn('schedule_media_intelligence_install()',INIT)
        for token in ('history_media_intelligence','musicStatus','musicConflict','MUSIC_SCAN_VERSION','claim_next','MediaIntelligenceWorker'):
            self.assertIn(token,WORKER)
        for script in (DEPLOY,INSTALL):
            self.assertIn('ffmpeg',script)
            self.assertIn('yt-dlp',script)

    def test_existing_and_future_assets_are_automatically_queued(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'history.sqlite3';make_db(db)
            conn=sqlite3.connect(db)
            conn.execute("INSERT INTO history_source_media(asset_key,provider,provider_media_id,title,validation_state,runtime_state,asset_json,last_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         ('youtube:a','youtube','a','Existing clip','VERIFIED','UNKNOWN',json.dumps({'youtubeId':'a'}),20,20))
            conn.commit();conn.close()
            store=MediaIntelligenceStore(db)
            first=store.claim_next('test')
            self.assertEqual(first['asset_key'],'youtube:a')
            store.complete('youtube:a',MusicResult('NO_MUSIC',.91,.03,False,12.0,{'test':True}))
            conn=sqlite3.connect(db);conn.row_factory=sqlite3.Row
            row=conn.execute("SELECT music_status,music_conflict,scan_version FROM history_media_intelligence WHERE asset_key='youtube:a'").fetchone()
            asset=json.loads(conn.execute("SELECT asset_json FROM history_source_media WHERE asset_key='youtube:a'").fetchone()[0])
            self.assertEqual(row['music_status'],'NO_MUSIC');self.assertEqual(row['music_conflict'],0);self.assertEqual(row['scan_version'],MUSIC_SCAN_VERSION)
            self.assertEqual(asset['musicStatus'],'NO_MUSIC');self.assertFalse(asset['musicConflict'])
            # Simulate a clip discovered after the worker/schema already exists.
            conn.execute("INSERT INTO history_source_media(asset_key,provider,provider_media_id,title,validation_state,runtime_state,asset_json,last_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         ('direct:new','direct','new','Newly discovered clip','VERIFIED','UNKNOWN',json.dumps({'mediaUrl':'https://example.invalid/new.mp4'}),30,30))
            conn.commit();conn.close()
            future=store.claim_next('test')
            self.assertEqual(future['asset_key'],'direct:new','newly discovered assets must enter music queue without provider-specific wiring')

    def test_conservative_music_classification(self):
        no_music=MusicDetector.classify_features([{'activeFrames':20,'tonalFrames':0,'musicRatio':0,'consecutiveTonal':0}],8)
        has_music=MusicDetector.classify_features([{'activeFrames':20,'tonalFrames':14,'musicRatio':.70,'consecutiveTonal':7}],8)
        unknown=MusicDetector.classify_features([{'activeFrames':20,'tonalFrames':4,'musicRatio':.20,'consecutiveTonal':2}],8)
        self.assertEqual(no_music.status,'NO_MUSIC');self.assertFalse(no_music.conflict)
        self.assertEqual(has_music.status,'HAS_MUSIC');self.assertTrue(has_music.conflict)
        self.assertEqual(unknown.status,'UNKNOWN');self.assertTrue(unknown.conflict,'ambiguous media must conservatively mute site music')

if __name__=='__main__': unittest.main()

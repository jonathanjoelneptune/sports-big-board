import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sbb.media_intelligence import MediaIntelligenceStore, MusicResult, MUSIC_SCAN_VERSION

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
INIT=(ROOT/'sbb'/'__init__.py').read_text(encoding='utf-8')
CONTROL=(ROOT/'sbb'/'media_intelligence_control.py').read_text(encoding='utf-8')
CONSOLE=(ROOT/'architecture'/'media-intelligence-console.js').read_text(encoding='utf-8')


def make_db(path):
    conn=sqlite3.connect(path)
    conn.execute('''CREATE TABLE history_source_media (
      asset_key TEXT PRIMARY KEY,provider TEXT DEFAULT '',provider_media_id TEXT DEFAULT '',canonical_url TEXT DEFAULT '',title TEXT DEFAULT '',
      duration_seconds REAL DEFAULT 0,published_at TEXT DEFAULT '',validation_state TEXT DEFAULT 'VERIFIED',runtime_state TEXT DEFAULT 'UNKNOWN',
      asset_json TEXT DEFAULT '{}',last_seen_at REAL DEFAULT 0,updated_at REAL DEFAULT 0)''')
    conn.commit();conn.close()


class V452MediaIntelligenceVisibility(unittest.TestCase):
    def test_release_loads_operator_console_after_media_intelligence(self):
        self.assertGreaterEqual(tuple(map(int,VERSION.split('.'))),(4,5,2))
        base=f'architecture/media-intelligence.js?v={VERSION}'
        console=f'architecture/media-intelligence-console.js?v={VERSION}'
        self.assertIn(base,INDEX);self.assertIn(console,INDEX)
        self.assertLess(INDEX.index(base),INDEX.index(console))

    def test_operator_api_is_installed_without_server_py_fork(self):
        self.assertIn('schedule_media_intelligence_control_install',INIT)
        for token in ('/api/media-intelligence/status','/api/media-intelligence/assets','/api/media-intelligence/asset','/api/media-intelligence/scan','original_get','original_post'):
            self.assertIn(token,CONTROL)

    def test_priority_scan_beats_backfill_and_results_are_queryable(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'history.sqlite3';make_db(db)
            conn=sqlite3.connect(db)
            rows=[
              ('direct:old','direct','old','https://example.invalid/old.mp4','Old clip','VERIFIED','UNKNOWN',{'mediaUrl':'https://example.invalid/old.mp4'},10,10),
              ('direct:current','direct','current','https://example.invalid/current.mp4','Current clip','VERIFIED','UNKNOWN',{'mediaUrl':'https://example.invalid/current.mp4','league':'MLB','date':'2026-08-27'},20,20),
            ]
            for key,provider,pid,url,title,validation,runtime,asset,last,updated in rows:
                conn.execute("INSERT INTO history_source_media(asset_key,provider,provider_media_id,canonical_url,title,validation_state,runtime_state,asset_json,last_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (key,provider,pid,url,title,validation,runtime,json.dumps(asset),last,updated))
            conn.commit();conn.close()
            store=MediaIntelligenceStore(db)
            queued=store.request_scan('direct:current',priority=1000,reason='test-current')
            self.assertEqual(queued['music_status'],'PENDING');self.assertEqual(queued['scan_priority'],1000)
            claimed=store.claim_next('worker')
            self.assertEqual(claimed['asset_key'],'direct:current','SCAN CURRENT must outrank ordinary backfill')
            store.complete('direct:current',MusicResult('HAS_MUSIC',.96,.71,True,24.0,{'test':True}))
            known=store.list_assets('HAS_MUSIC',5)
            self.assertEqual(known[0]['asset_key'],'direct:current')
            self.assertEqual(known[0]['music_status'],'HAS_MUSIC')
            self.assertEqual(known[0]['scan_version'],MUSIC_SCAN_VERSION)
            self.assertEqual(known[0]['league'],'MLB')
            self.assertEqual(known[0]['date'],'2026-08-27')
            val=store.validation_set(3)
            self.assertEqual(val['hasMusic'][0]['asset_key'],'direct:current')

    def test_console_exposes_current_scan_and_known_reference_sets(self):
        for token in ('SCAN CURRENT','KNOWN HAS MUSIC','KNOWN NO MUSIC','/api/media-intelligence/status','/api/media-intelligence/scan','musicStatus','musicConfidence','musicRatio'):
            self.assertIn(token,CONSOLE)
        self.assertNotIn('MutationObserver',CONSOLE)

if __name__=='__main__': unittest.main()

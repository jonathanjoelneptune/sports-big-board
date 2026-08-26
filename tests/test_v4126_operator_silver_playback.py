import json, tempfile, threading, time, unittest
from contextlib import closing
from pathlib import Path

from sbb.history_repository import HistoryRepository

class V4126RepositoryTests(unittest.TestCase):
    def make_repo(self):
        td=tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        return HistoryRepository(Path(td.name)/'history.sqlite3')

    def test_roundup_uses_normalized_verified_runtime_truth(self):
        repo=self.make_repo()
        # Build a Silver collection directly to isolate read semantics.
        now=time.time(); asset={'youtubeId':'silver123','title':'Daily Recap','mediaScope':'DAY_LEAGUE','scope':'DAY_LEAGUE','externalUrl':'https://www.youtube.com/watch?v=silver123'}
        with repo._lock, closing(repo._connect()) as c:
            repo._upsert_source_media_conn(c,asset,league='MLB',date='2026-08-22')
            key=repo.asset_key_for(asset)
            c.execute("UPDATE history_source_media SET validation_state='VERIFIED',runtime_state='UNKNOWN',asset_json=? WHERE asset_key=?",(json.dumps({**asset,'verifiedPlayable':False}),key))
            c.execute("INSERT INTO history_collection(collection_key,scope,league,period_key,collection_kind,title,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",('day:MLB:2026-08-22','DAY_LEAGUE','MLB','2026-08-22','ROUNDUP','Daily','{}',now,now))
            c.execute("INSERT INTO history_collection_media(collection_key,asset_key,association_confidence,association_method,association_evidence,classifier_version,rank_hint,first_associated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",('day:MLB:2026-08-22',key,1.0,'test','test',1,10,now,now)); c.commit()
        rows=repo.roundup_media('2026-08-22','MLB')
        self.assertEqual(len(rows),1); self.assertTrue(rows[0]['verifiedPlayable'])

    def test_default_audit_is_sql_paged(self):
        repo=self.make_repo()
        for i in range(12): repo.put_scores('2026-08-%02d'%(10+i),'MLB',[{'id':str(i),'completed':True,'awayTeam':{'name':'A'},'homeTeam':{'name':'B'}}])
        out=repo.audit_catalog(limit=3,offset=3,current_discovery_version=15)
        self.assertEqual(out['queryMode'],'SQL_PAGE'); self.assertEqual(len(out['rows']),3); self.assertGreaterEqual(out['total'],12)

    def test_read_only_silver_lookup_does_not_wait_for_writer_python_lock(self):
        repo=self.make_repo(); done=[]
        def reader(): repo.roundup_media('2026-08-22','MLB'); done.append(time.time())
        with repo._lock:
            t=threading.Thread(target=reader); start=time.time(); t.start(); t.join(.75)
            self.assertTrue(done, 'roundup_media should use independent WAL reader')
            self.assertLess(done[0]-start,.75)

class V4126SourceGuards(unittest.TestCase):
    def test_server_has_cached_operator_snapshot_and_chunk_diagnostics(self):
        src=Path('server.py').read_text()
        self.assertIn('history_operator_snapshot_worker',src)
        self.assertIn("operator_snapshot=_history_operator_snapshot()",src)
        self.assertIn('MEDIA_FILE_CACHE_CHUNK_BYTES',src)
        self.assertIn('/api/media/diagnostics',src)
        self.assertIn("'HYBRID_CHUNK'",src)
    def test_browser_reports_first_frame_path(self):
        src=Path('app.js').read_text()
        self.assertIn('reportNativePlaybackPath',src)
        self.assertIn('PLAYBACK_FIRST_FRAME',src)
        self.assertIn('BROWSER_HOT',src)

if __name__=='__main__': unittest.main()

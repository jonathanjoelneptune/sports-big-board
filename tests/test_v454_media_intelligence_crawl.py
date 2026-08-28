import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from sbb.media_intelligence import MediaIntelligenceStore, MusicResult, MUSIC_SCAN_VERSION

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
WORKER=(ROOT/'sbb'/'media_intelligence.py').read_text(encoding='utf-8')
CONSOLE=(ROOT/'architecture'/'media-intelligence-console.js').read_text(encoding='utf-8')
TERMINAL=(ROOT/'architecture'/'playback-terminal.js').read_text(encoding='utf-8')


def make_db(path):
    conn=sqlite3.connect(path)
    conn.execute("""CREATE TABLE history_source_media (
      asset_key TEXT PRIMARY KEY,provider TEXT DEFAULT '',provider_media_id TEXT DEFAULT '',canonical_url TEXT DEFAULT '',title TEXT DEFAULT '',
      duration_seconds REAL DEFAULT 0,published_at TEXT DEFAULT '',validation_state TEXT DEFAULT 'VERIFIED',runtime_state TEXT DEFAULT 'UNKNOWN',
      asset_json TEXT DEFAULT '{}',last_seen_at REAL DEFAULT 0,updated_at REAL DEFAULT 0)""")
    conn.commit();conn.close()


def add_asset(path,key,title,last_seen=0,runtime='UNKNOWN'):
    conn=sqlite3.connect(path)
    conn.execute("""INSERT INTO history_source_media
      (asset_key,provider,provider_media_id,canonical_url,title,validation_state,runtime_state,asset_json,last_seen_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (key,'direct',key,f'https://example.invalid/{key}.mp4',title,'VERIFIED',runtime,
       json.dumps({'mediaUrl':f'https://example.invalid/{key}.mp4'}),last_seen,last_seen))
    conn.commit();conn.close()


class V454MediaIntelligenceCrawlHardening(unittest.TestCase):
    def test_release_floor_and_console_scroll_contract(self):
        self.assertGreaterEqual(tuple(map(int,VERSION.split('.'))),(4,5,4))
        for token in ('PROCESSED','CLASSIFIED','PENDING FRESH','SCAN FAILURES','failureReasons','attemptedAt','FAILURE TYPE'):
            self.assertIn(token,CONSOLE)
        self.assertIn('.milestone-console-shell{max-height:calc(100dvh - 24px)!important;overflow-y:auto!important',CONSOLE)
        self.assertIn('musicFailureKind',TERMINAL)

    def test_fresh_backlog_wins_over_due_failed_retry(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'history.sqlite3';make_db(db)
            add_asset(db,'direct:failed','Previously failed recent asset',last_seen=9999,runtime='PLAYED')
            store=MediaIntelligenceStore(db)
            first=store.claim_next('test')
            self.assertEqual(first['asset_key'],'direct:failed')
            store.fail('direct:failed',RuntimeError('ffmpeg decode failed'))
            conn=sqlite3.connect(db)
            conn.execute("UPDATE history_media_intelligence SET next_retry_at=0 WHERE asset_key='direct:failed'")
            conn.commit();conn.close()
            add_asset(db,'direct:fresh','Never scanned older asset',last_seen=1,runtime='UNKNOWN')
            next_row=store.claim_next('test2')
            self.assertEqual(next_row['asset_key'],'direct:fresh','never-scanned backlog must run before ordinary failed retries')

    def test_failed_attempt_accounting_is_not_fake_classification(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'history.sqlite3';make_db(db);add_asset(db,'direct:a','Failure sample',last_seen=10)
            store=MediaIntelligenceStore(db)
            self.assertEqual(store.claim_next('test')['asset_key'],'direct:a')
            retry=store.fail('direct:a',RuntimeError('yt-dlp audio URL failed: unavailable'))
            row=store.asset('direct:a');snap=store.snapshot()
            self.assertEqual(row['music_status'],'SCAN_FAILED')
            self.assertEqual(row['failure_kind'],'YOUTUBE_RESOLVE')
            self.assertGreater(row['attempted_at'],0)
            self.assertEqual(row['scanned_at'],0,'failure attempt is not a successful music classification')
            self.assertGreater(retry-time.time(),20*3600,'YouTube failures should not hot-loop every few minutes')
            self.assertEqual(snap['processed'],1)
            self.assertEqual(snap['classified'],0)
            self.assertEqual(snap['failed'],1)
            self.assertEqual(snap['failureReasons'].get('YOUTUBE_RESOLVE'),1)
            self.assertGreater(snap['lastProcessedAt'],0)

    def test_background_trickle_keeps_playback_priority_as_hard_fence(self):
        for token in (
            'MUSIC_FOREGROUND_TRICKLE_SECONDS',
            'reason == "playback-priority"',
            'reason == "active-media"',
            'foreground_trickle = True',
            'priority >= 900',
            'fresh unprocessed assets',
        ):
            self.assertIn(token,WORKER)


if __name__=='__main__': unittest.main()

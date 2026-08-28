import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sbb.media_intelligence import MediaIntelligenceStore, MusicDetector

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
WORKER=(ROOT/'sbb'/'media_intelligence.py').read_text(encoding='utf-8')
CONSOLE=(ROOT/'architecture'/'media-intelligence-console.js').read_text(encoding='utf-8')
DEPLOY=(ROOT/'cloud'/'gcp'/'DEPLOY-FROM-GITHUB.sh').read_text(encoding='utf-8')
INSTALL=(ROOT/'cloud'/'vm'/'INSTALL-STAGE1.sh').read_text(encoding='utf-8')


def make_db(path):
    conn=sqlite3.connect(path)
    conn.execute('''CREATE TABLE history_source_media (
      asset_key TEXT PRIMARY KEY,provider TEXT DEFAULT '',provider_media_id TEXT DEFAULT '',canonical_url TEXT DEFAULT '',title TEXT DEFAULT '',
      duration_seconds REAL DEFAULT 0,published_at TEXT DEFAULT '',validation_state TEXT DEFAULT 'VERIFIED',runtime_state TEXT DEFAULT 'UNKNOWN',
      asset_json TEXT DEFAULT '{}',last_seen_at REAL DEFAULT 0,updated_at REAL DEFAULT 0)''')
    conn.commit();conn.close()


class Proc:
    def __init__(self, rc=0, stdout='', stderr=''):
        self.returncode=rc;self.stdout=stdout;self.stderr=stderr


class V455YoutubeMediaIntelligence(unittest.TestCase):
    def test_release_and_runtime_dependency_contract(self):
        self.assertGreaterEqual(tuple(map(int,VERSION.split('.'))),(4,5,5))
        for token in ('--js-runtimes','inventory-fallback','youtubeAudioFormatCount','FORMAT_UNAVAILABLE'):
            self.assertIn(token,WORKER)
        for script in (DEPLOY,INSTALL):
            self.assertIn('yt-dlp/yt-dlp/releases/latest/download/yt-dlp',script)
            self.assertIn('denoland/deno/releases/latest/download/deno-',script)
            self.assertIn('/usr/local/bin/yt-dlp',script)
            self.assertIn('/usr/local/bin/deno',script)
        self.assertIn('deno=',CONSOLE)
        self.assertIn('ytDlpVersion',CONSOLE)

    def test_requested_format_failure_uses_inventory_audio_fallback(self):
        detector=MusicDetector(ffmpeg='/fake/ffmpeg',ytdlp='/fake/yt-dlp',deno='/fake/deno')
        inventory={
            'formats':[
                {'format_id':'sb0','url':'https://example.invalid/storyboard','acodec':'none','vcodec':'images','protocol':'https'},
                {'format_id':'18','url':'https://example.invalid/progressive.mp4','acodec':'mp4a.40.2','vcodec':'avc1','protocol':'https','abr':96,'asr':44100},
                {'format_id':'140','url':'https://example.invalid/audio.m4a','acodec':'mp4a.40.2','vcodec':'none','protocol':'https','abr':129,'asr':44100},
            ]
        }
        calls=[]
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if '-g' in cmd:
                return Proc(1,'','ERROR: [youtube] abc: Requested format is not available. Use --list-formats for a list of available formats')
            if '--dump-single-json' in cmd:
                return Proc(0,json.dumps(inventory),'')
            raise AssertionError(cmd)
        with mock.patch('sbb.media_intelligence.subprocess.run',side_effect=fake_run):
            url=detector._resolve_youtube_audio_url('abc')
        self.assertEqual(url,'https://example.invalid/audio.m4a')
        self.assertEqual(detector._last_source_details['youtubeResolver'],'inventory-fallback')
        self.assertEqual(detector._last_source_details['youtubeFormatId'],'140')
        self.assertTrue(all('--js-runtimes' in cmd for cmd in calls))
        self.assertTrue(all('deno:/fake/deno' in cmd for cmd in calls))
        self.assertTrue(any('-f' in cmd and 'all' in cmd for cmd in calls))

    def test_format_unavailable_failure_is_distinct_and_reopened_once(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'history.sqlite3';make_db(db)
            conn=sqlite3.connect(db)
            conn.execute("INSERT INTO history_source_media(asset_key,provider,provider_media_id,title,validation_state,runtime_state,asset_json,last_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         ('youtube:abc','youtube','abc','YouTube clip','VERIFIED','UNKNOWN',json.dumps({'youtubeId':'abc'}),1,1))
            conn.commit();conn.close()
            store=MediaIntelligenceStore(db)
            self.assertEqual(store.claim_next('test')['asset_key'],'youtube:abc')
            store.fail('youtube:abc',RuntimeError('yt-dlp audio URL failed: ERROR: [youtube] abc: Requested format is not available. Use --list-formats'))
            row=store.asset('youtube:abc')
            self.assertEqual(row['failure_kind'],'FORMAT_UNAVAILABLE')
            # Simulate the v4.5.4 persisted failure before the v4.5.5 schema startup repair.
            conn=sqlite3.connect(db)
            conn.execute("UPDATE history_media_intelligence SET failure_kind='YOUTUBE_RESOLVE',scan_attempts=6,next_retry_at=9999999999,scan_request_reason='' WHERE asset_key='youtube:abc'")
            conn.commit();conn.close()
            MediaIntelligenceStore(db)
            conn=sqlite3.connect(db);conn.row_factory=sqlite3.Row
            repaired=conn.execute("SELECT failure_kind,scan_attempts,next_retry_at,scan_request_reason FROM history_media_intelligence WHERE asset_key='youtube:abc'").fetchone()
            conn.close()
            self.assertEqual(repaired['failure_kind'],'FORMAT_UNAVAILABLE')
            self.assertEqual(repaired['scan_attempts'],0)
            self.assertEqual(repaired['next_retry_at'],0)
            self.assertEqual(repaired['scan_request_reason'],'v4.5.5-youtube-repair')


if __name__=='__main__': unittest.main()

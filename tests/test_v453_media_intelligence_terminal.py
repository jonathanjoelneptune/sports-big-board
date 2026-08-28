import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import sbb.media_intelligence_control as CONTROL_MODULE

from sbb.media_intelligence import MediaIntelligenceStore

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
INDEX=(ROOT/'index.html').read_text(encoding='utf-8')
TERMINAL=(ROOT/'architecture'/'playback-terminal.js').read_text(encoding='utf-8')
CONSOLE=(ROOT/'architecture'/'media-intelligence-console.js').read_text(encoding='utf-8')
CONTROL=(ROOT/'sbb'/'media_intelligence_control.py').read_text(encoding='utf-8')
WORKER=(ROOT/'sbb'/'media_intelligence.py').read_text(encoding='utf-8')


def make_db(path):
    conn=sqlite3.connect(path)
    conn.execute("""CREATE TABLE history_source_media (
      asset_key TEXT PRIMARY KEY,provider TEXT DEFAULT '',provider_media_id TEXT DEFAULT '',canonical_url TEXT DEFAULT '',title TEXT DEFAULT '',
      duration_seconds REAL DEFAULT 0,published_at TEXT DEFAULT '',validation_state TEXT DEFAULT 'VERIFIED',runtime_state TEXT DEFAULT 'UNKNOWN',
      asset_json TEXT DEFAULT '{}',last_seen_at REAL DEFAULT 0,updated_at REAL DEFAULT 0)""")
    conn.commit();conn.close()


class V453MediaIntelligenceTerminal(unittest.TestCase):
    def test_release_and_terminal_columns(self):
        self.assertGreaterEqual(tuple(map(int,VERSION.split('.'))),(4,5,3))
        for label in ('MUSIC','CONF','MUSIC%','SCAN','SITE MUSIC'):
            self.assertIn(f'<span>{label}</span>',INDEX)
        self.assertIn(f'architecture/playback-terminal.js?v={VERSION}',INDEX)
        for token in ('playback-terminal-auto','MCONF=','MRATIO=','MSCAN=','SITE_MUSIC=','enrichMediaIntel(row,{autoQueue:true})'):
            self.assertIn(token,TERMINAL)

    def test_console_uses_deployment_aware_api_path(self):
        self.assertIn('window.SBB_API?.url?.(path)||path',CONSOLE)
        self.assertIn('/api/media-intelligence/status',CONSOLE)

    def test_control_installer_has_no_startup_deadline_and_supports_explicit_priority(self):
        self.assertIn('def _find_server_context()',CONTROL)
        self.assertIn('while not _INSTALLED:',CONTROL)
        self.assertNotIn('deadline=time.time()+90',CONTROL)
        self.assertIn("body.get('priority')",CONTROL)
        self.assertIn("'routeVersion':'1.1'",CONTROL)

    def test_http_control_wrapper_returns_status_200(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'history.sqlite3';make_db(db)
            class Handler:
                def __init__(self):
                    self.path='/api/media-intelligence/status';self.headers={};self.response=None
                def do_GET(self):
                    self.response=({'fallback':True},599);return self.response
                def do_POST(self):
                    self.response=({'fallback':True},599);return self.response
            def send_json(handler,payload,status=200,*_args,**_kwargs):
                handler.response=(payload,status);return handler.response
            main=SimpleNamespace()
            repo=SimpleNamespace(path=db)
            CONTROL_MODULE._install_routes('fake-sbb-server',main,Handler,repo,send_json)
            h=Handler();h.do_GET()
            self.assertEqual(h.response[1],200)
            self.assertTrue(h.response[0]['controlInstalled'])
            self.assertEqual(h.response[0]['routeVersion'],'1.1')

    def test_auto_priority_is_lower_than_manual_and_database_backfill_remains_complete(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'history.sqlite3';make_db(db)
            conn=sqlite3.connect(db)
            for key,last in [('direct:one',10),('direct:two',20)]:
                url=f'https://example.invalid/{key.split(":")[-1]}.mp4'
                conn.execute("INSERT INTO history_source_media(asset_key,provider,provider_media_id,canonical_url,title,validation_state,runtime_state,asset_json,last_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (key,'direct',key,url,key,'VERIFIED','UNKNOWN',json.dumps({'mediaUrl':url}),last,last))
            conn.commit();conn.close()
            store=MediaIntelligenceStore(db)
            snap=store.snapshot()
            self.assertEqual(snap['total'],2)
            self.assertEqual(snap['pending'],2)
            store.request_scan('direct:one',priority=250,reason='playback-terminal-auto')
            store.request_scan('direct:two',priority=1000,reason='operator-current')
            self.assertEqual(store.priority_request_level(),1000)
            claimed=store.claim_next('test')
            self.assertEqual(claimed['asset_key'],'direct:two')
            self.assertIn('priority_request_level() >= 900',WORKER)


if __name__=='__main__': unittest.main()

import importlib.util
import json
import pathlib
import sqlite3
import sys
import tempfile
import threading
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CoreCorrectnessRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: v for k, v in list(sys.modules.items()) if k == 'sbb' or k.startswith('sbb.')}
        for k in list(sys.modules):
            if k == 'sbb' or k.startswith('sbb.'):
                sys.modules.pop(k, None)
        pkg = types.ModuleType('sbb')
        pkg.__path__ = [str(ROOT / 'sbb')]
        sys.modules['sbb'] = pkg

    def tearDown(self):
        for k in list(sys.modules):
            if k == 'sbb' or k.startswith('sbb.'):
                sys.modules.pop(k, None)
        sys.modules.update(self.saved)

    def test_historical_empty_score_cache_is_filled_from_canonical_catalog(self):
        registry = types.ModuleType('sbb.competition_registry')
        sys.modules['sbb.competition_registry'] = registry
        mod = load_module('sbb.day_state', ROOT / 'sbb/day_state.py')

        class Repo:
            def catalog_events(self, date_from='', date_to='', limit=0):
                self.args = (date_from, date_to, limit)
                return [{
                    'league': 'MLB', 'eventId': 'historic-1',
                    'event': {'eventId': 'historic-1', 'date': '2026-05-13', 'status': 'FINAL',
                              'awayScore': 2, 'homeScore': 4},
                }]
        server = types.SimpleNamespace(HISTORY_REPOSITORY=Repo())
        rows, diag = mod._merge_future_catalog_rows(server, '2026-05-13', {}, '2026-08-30')
        self.assertEqual(len(rows['MLB']), 1)
        self.assertEqual(rows['MLB'][0]['eventId'], 'historic-1')
        self.assertEqual(diag['catalogMergeScope'], 'ALL_DATES')
        self.assertEqual(diag['catalogAdded'], 1)
        self.assertFalse(diag['future'])

    def test_cfb_game_center_runtime_adds_support_and_indexes_canonical_events(self):
        cfb = types.ModuleType('sbb.cfb_ranked')
        cfb._load_state = lambda: {'weeks': {'1': {'events': [{
            'eventId': '401752001', 'espnEventId': '401752001', 'date': '2026-08-29',
            'awayTeam': {'name': 'San Jose State'}, 'homeTeam': {'name': 'USC'},
        }]}}}
        sys.modules['sbb.cfb_ranked'] = cfb
        mod = load_module('sbb.game_center_runtime_v4721', ROOT / 'sbb/game_center_runtime_v4721.py')

        class Server:
            GAME_CENTER_SUPPORTED = {'MLB', 'NFL'}
            GAME_CENTER_EVENT_INDEX_LOCK = threading.RLock()
            GAME_CENTER_EVENT_INDEX = {}
            MILESTONE_CONSOLE = types.SimpleNamespace(record=lambda *a, **k: None)
            @staticmethod
            def _index_game_center_events(comp, rows, day, provider='official'):
                converted = []
                for event in rows:
                    converted.append({'competition': comp, 'providerEventId': event['eventId'],
                                      'date': day, 'awayTeam': event.get('awayTeam') or {},
                                      'homeTeam': event.get('homeTeam') or {}, 'provider': provider})
                Server.GAME_CENTER_EVENT_INDEX[(comp, day)] = converted
                return converted
            @staticmethod
            def _game_center_index_rows(comp, day, allow_fetch=False):
                return list(Server.GAME_CENTER_EVENT_INDEX.get((comp, day)) or [])
        server = Server()
        self.assertTrue(mod._patch_server(server))
        self.assertIn('CFB', server.GAME_CENTER_SUPPORTED)
        rows = server._game_center_index_rows('CFB', '2026-08-29', allow_fetch=True)
        self.assertEqual(rows[0]['providerEventId'], '401752001')
        self.assertEqual(rows[0]['provider'], 'official')

    def test_llws_inventory_includes_demoted_or_quarantined_prior_llws_assets(self):
        hist = types.ModuleType('sbb.history_repository')
        class HistoryRepository:
            def event_media(self,*a,**k): return []
            def ribbon_media_for_date(self,*a,**k): return {}
            def roundup_media(self,*a,**k): return []
            def repair_event_associations(self,*a,**k): return {}
            def repair_collection_associations(self,*a,**k): return {}
            def repair_relationships(self,*a,**k): return {'ok':True}
        hist.HistoryRepository = HistoryRepository
        sys.modules['sbb.history_repository'] = hist
        mod = load_module('sbb.database_authority', ROOT / 'sbb/database_authority.py')

        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / 'db.sqlite3'
            conn = sqlite3.connect(path)
            conn.executescript('''
                CREATE TABLE history_source_media(asset_key TEXT PRIMARY KEY,provider TEXT,provider_media_id TEXT,canonical_url TEXT,
                  channel_name TEXT,scope TEXT,runtime_state TEXT,asset_json TEXT,updated_at REAL);
                CREATE TABLE history_event_media(canonical_event_key TEXT,asset_key TEXT,association_state TEXT);
                CREATE TABLE history_catalog_event(canonical_event_key TEXT PRIMARY KEY,league TEXT);
            ''')
            payload = json.dumps({'youtubeId':'llws-old','title':'Ohio vs Alabama | Little League World Series','mediaScope':'OTHER'})
            conn.execute("INSERT INTO history_source_media VALUES(?,?,?,?,?,?,?,?,?)",
                         ('yt:llws-old','YOUTUBE','llws-old','https://youtu.be/llws-old','Little League','OTHER','UNKNOWN',payload,1))
            conn.execute("INSERT INTO history_catalog_event VALUES('LLWS2026:g1','LLWS2026')")
            conn.execute("INSERT INTO history_event_media VALUES('LLWS2026:g1','yt:llws-old','QUARANTINED')")
            conn.commit(); conn.close()

            class Repo:
                def _read_connect(self):
                    c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
                @staticmethod
                def _hydrate_asset(row):
                    item=json.loads(row['asset_json']);item['assetKey']=row['asset_key'];return item
            items = mod._llws_source_inventory(Repo())
            self.assertEqual(len(items),1)
            self.assertEqual(items[0]['assetKey'],'yt:llws-old')
            self.assertEqual(items[0]['competitionId'],'LLWS2026')

    def test_game_center_persistent_summary_has_real_tab_anchor(self):
        html = (ROOT / 'index.html').read_text(encoding='utf-8')
        view = (ROOT / 'architecture/game-center-multisport-view.js').read_text(encoding='utf-8')
        self.assertIn('id="gcSections" class="gc-section-tabs"', html)
        self.assertIn("document.getElementById('gcSections')", view)
        self.assertIn('function baseballCard(gc)', view)
        self.assertIn('function periodCard(gc)', view)


if __name__ == '__main__':
    unittest.main()

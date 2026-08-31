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


class DummyThread:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
    def start(self):
        return None


class V4721DatabaseAuthorityTests(unittest.TestCase):
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

    def _load_authority_with_stub(self):
        hist = types.ModuleType('sbb.history_repository')

        class HistoryRepository:
            destructive_calls = 0

            def event_media(self, date, league, event_id, include_failed=True):
                return [
                    {'youtubeId': 'abc12345', 'validationState': 'CANDIDATE', 'runtimeCatalogState': 'UNKNOWN', 'verifiedPlayable': False},
                    {'youtubeId': 'failed123', 'validationState': 'VERIFIED', 'runtimeCatalogState': 'FAILED', 'verifiedPlayable': True},
                ]

            def ribbon_media_for_date(self, date, leagues=None, include_failed=False):
                return {'NFL:1': [{'youtubeId': 'ribbon123', 'validationState': 'CANDIDATE', 'runtimeCatalogState': 'UNKNOWN', 'verifiedPlayable': False}]}

            def roundup_media(self, date, league=None):
                return [{'youtubeId': 'silver123', 'validationState': 'CANDIDATE', 'runtimeCatalogState': 'UNKNOWN', 'verifiedPlayable': False}]

            def repair_event_associations(self, matcher_version=None, force=False):
                type(self).destructive_calls += 1
                return {'mutated': True, 'family': 'event'}

            def repair_collection_associations(self, classifier_version=None, force=False):
                type(self).destructive_calls += 1
                return {'mutated': True, 'family': 'collection'}

            def repair_relationships(self, force=False, force_event=False, force_collection=False):
                type(self).destructive_calls += 1
                if force:
                    self.repair_event_associations(force=True)
                    self.repair_collection_associations(force=True)
                return {'ok': True, 'mutated': True}

            def association_integrity_summary(self):
                return {'assignedLinks': 10}

            def catalog_integrity(self):
                return {'collectionLinks': 3, 'lowConfidenceAssigned': 2}

        hist.HistoryRepository = HistoryRepository
        sys.modules['sbb.history_repository'] = hist
        mod = load_module('sbb.database_authority', ROOT / 'sbb/database_authority.py')
        mod.threading.Thread = DummyThread
        mod.install()
        return mod, HistoryRepository

    def test_assigned_event_relationship_restores_candidate_playability_but_not_failed(self):
        mod, HistoryRepository = self._load_authority_with_stub()
        rows = HistoryRepository().event_media('2026-08-01', 'NFL', '1')
        self.assertTrue(rows[0]['verifiedPlayable'])
        self.assertEqual(rows[0]['databaseAuthority'], 'EVENT_MEDIA_ASSIGNED')
        self.assertFalse(rows[1]['verifiedPlayable'])

        ribbon = HistoryRepository().ribbon_media_for_date('2026-08-01')
        self.assertTrue(ribbon['NFL:1'][0]['verifiedPlayable'])
        self.assertEqual(ribbon['NFL:1'][0]['databaseAuthority'], 'EVENT_MEDIA_ASSIGNED')

    def test_collection_relationship_restores_candidate_silver_playability(self):
        mod, HistoryRepository = self._load_authority_with_stub()
        rows = HistoryRepository().roundup_media('2026-08-01', 'NFL')
        self.assertTrue(rows[0]['verifiedPlayable'])
        self.assertEqual(rows[0]['databaseAuthority'], 'COLLECTION_MEDIA_ASSIGNED')

    def test_startup_family_force_flags_are_audit_only(self):
        mod, HistoryRepository = self._load_authority_with_stub()
        repo = HistoryRepository()
        result = repo.repair_relationships(force_event=True, force_collection=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['mode'], 'AUDIT_ONLY_DATABASE_AUTHORITY')
        self.assertTrue(result['startupMutationBlocked'])
        self.assertEqual(HistoryRepository.destructive_calls, 0)

    def test_explicit_global_force_preserves_manual_maintenance_path(self):
        mod, HistoryRepository = self._load_authority_with_stub()
        HistoryRepository.destructive_calls = 0
        result = HistoryRepository().repair_relationships(force=True)
        self.assertTrue(result['ok'])
        self.assertGreaterEqual(HistoryRepository.destructive_calls, 3)

    def test_one_time_recovery_restores_exact_event_and_silver_edges(self):
        hist = types.ModuleType('sbb.history_repository')

        class FakeRepo:
            def __init__(self, path):
                self.path = path
                self._lock = threading.RLock()
            def _connect(self):
                conn = sqlite3.connect(self.path)
                conn.row_factory = sqlite3.Row
                return conn
            def _read_connect(self):
                return self._connect()
            @staticmethod
            def _dump_obj(value):
                return json.dumps(value, separators=(',', ':'))
            @staticmethod
            def _collection_key(scope, league, period, kind):
                return f'{scope}:{league}:{period}:{kind}'
            @staticmethod
            def asset_key_for(item):
                yid = str((item or {}).get('youtubeId') or '')
                mapping = {'archive12345':'s2','silver12345':'s1','event12345':'a1','eventarchive':'a2'}
                return mapping.get(yid, '')
            def catalog_meta(self, key, default=''):
                with self._connect() as conn:
                    row = conn.execute('SELECT value FROM history_catalog_meta WHERE key=?', (key,)).fetchone()
                return row['value'] if row else default
            # Required class methods for install capture; unused in this recovery test.
            def event_media(self, *args, **kwargs): return []
            def ribbon_media_for_date(self, *args, **kwargs): return {}
            def roundup_media(self, *args, **kwargs): return []
            def repair_event_associations(self, *args, **kwargs): return {}
            def repair_collection_associations(self, *args, **kwargs): return {}
            def repair_relationships(self, *args, **kwargs): return {'ok': True}

        hist.HistoryRepository = FakeRepo
        sys.modules['sbb.history_repository'] = hist
        mod = load_module('sbb.database_authority', ROOT / 'sbb/database_authority.py')

        with tempfile.TemporaryDirectory() as td:
            repo = FakeRepo(str(pathlib.Path(td) / 'history.sqlite3'))
            with repo._connect() as conn:
                conn.executescript('''
                    CREATE TABLE history_catalog_meta(key TEXT PRIMARY KEY,value TEXT,updated_at REAL);
                    CREATE TABLE history_catalog_event(canonical_event_key TEXT PRIMARY KEY,league TEXT,event_id TEXT,event_date TEXT);
                    CREATE TABLE history_source_media(
                      asset_key TEXT PRIMARY KEY,provider TEXT,provider_media_id TEXT,canonical_url TEXT,
                      scope TEXT,scope_confidence REAL,scope_reason TEXT,catalog_state TEXT,quarantine_reason TEXT,
                      validation_state TEXT,runtime_state TEXT,asset_json TEXT,updated_at REAL);
                    CREATE TABLE history_event_media(
                      canonical_event_key TEXT,asset_key TEXT,association_state TEXT,association_confidence REAL,
                      association_method TEXT,association_evidence TEXT,matcher_version INTEGER,updated_at REAL,
                      PRIMARY KEY(canonical_event_key,asset_key));
                    CREATE TABLE history_collection(
                      collection_key TEXT PRIMARY KEY,scope TEXT,league TEXT,period_key TEXT,collection_kind TEXT,title TEXT,
                      metadata_json TEXT,created_at REAL,updated_at REAL);
                    CREATE TABLE history_collection_media(
                      collection_key TEXT,asset_key TEXT,association_confidence REAL,association_method TEXT,
                      association_evidence TEXT,classifier_version INTEGER,rank_hint INTEGER,first_associated_at REAL,updated_at REAL,
                      PRIMARY KEY(collection_key,asset_key));
                    CREATE TABLE history_assignment_review(
                      asset_key TEXT,proposed_event_key TEXT,state TEXT,updated_at REAL);
                    CREATE TABLE history_day(date TEXT,league TEXT,media_json TEXT);
                ''')
                conn.execute("INSERT INTO history_catalog_event VALUES('NFL:E1','NFL','E1','2026-08-01')")
                event_json = json.dumps({
                    'youtubeId': 'event12345', 'canonicalEventKey': 'NFL:E1', 'eventId': 'E1',
                    'associationConfidence': 0.99, 'associationMethod': 'PROVIDER_EVENT_ID',
                    'mediaScope': 'GAME',
                }, separators=(',', ':'))
                conn.execute("INSERT INTO history_source_media VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ('a1','YOUTUBE','event12345','https://youtu.be/event12345','GAME',0.99,'old','QUARANTINED','UNPROVEN_GAME_ASSOCIATION','CANDIDATE','UNKNOWN',event_json,0))
                conn.execute("INSERT INTO history_event_media VALUES(?,?,?,?,?,?,?,?)",
                    ('NFL:E1','a1','QUARANTINED',0.0,'UNPROVEN_GAME_ASSOCIATION','generic repair rejected',4716,0))

                # Same regression, but current SOURCE_MEDIA has lost its original
                # association fields; history_day still proves the exact event.
                conn.execute("INSERT INTO history_catalog_event VALUES('NFL:E2','NFL','E2','2026-08-01')")
                stripped_event = json.dumps({'youtubeId':'eventarchive','title':'Archived recap'}, separators=(',', ':'))
                conn.execute("INSERT INTO history_source_media VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ('a2','YOUTUBE','eventarchive','https://youtu.be/eventarchive','OTHER',0.1,'reclassified','QUARANTINED','UNPROVEN_GAME_ASSOCIATION','CANDIDATE','UNKNOWN',stripped_event,0))
                conn.execute("INSERT INTO history_event_media VALUES(?,?,?,?,?,?,?,?)",
                    ('NFL:E2','a2','QUARANTINED',0.0,'UNPROVEN_GAME_ASSOCIATION','generic repair rejected',4716,0))

                silver_json = json.dumps({
                    'youtubeId': 'silver12345', 'competitionId': 'NFL', 'collectionTier': 'silver',
                    'displayTier': 'silver', 'collectionPeriodKey': '2026-08-01',
                    'collectionKind': 'DAILY_RECAP', 'collectionPromotionApproved': True,
                }, separators=(',', ':'))
                conn.execute("INSERT INTO history_source_media VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ('s1','YOUTUBE','silver12345','https://youtu.be/silver12345','OTHER',0.7,'old','UNASSIGNED','','CANDIDATE','UNKNOWN',silver_json,0))

                # Reproduce the more destructive case: the source row survived but its
                # collection metadata was overwritten. The compatibility day JSON still
                # retains the old Silver association evidence.
                archive_source = json.dumps({'youtubeId': 'archive12345', 'competitionId': 'NFL'}, separators=(',', ':'))
                conn.execute("INSERT INTO history_source_media VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ('s2','YOUTUBE','archive12345','https://youtu.be/archive12345','OTHER',0.2,'reclassified','UNASSIGNED','','CANDIDATE','UNKNOWN',archive_source,0))
                archive_item = {
                    'youtubeId': 'archive12345', 'competitionId': 'NFL', 'collectionTier': 'silver',
                    'collectionPeriodKey': '2026-08-01', 'collectionKind': 'DAILY_RECAP',
                    'mediaScope': 'DAY_LEAGUE', 'collectionPromotionApproved': True,
                }
                archived_event = {
                    'youtubeId':'eventarchive','competitionId':'NFL','canonicalEventKey':'NFL:E2',
                    'associationConfidence':0.99,'associationMethod':'PROVIDER_EVENT_ID','mediaScope':'GAME',
                }
                conn.execute("INSERT INTO history_day VALUES(?,?,?)",
                    ('2026-08-01','NFL',json.dumps([archive_item, archived_event], separators=(',', ':'))))
                conn.commit()

            result = mod.recover(repo, force=True)
            self.assertEqual(result['event']['restored'], 2)
            self.assertEqual(result['event']['archiveRestored'], 1)
            self.assertEqual(result['silver']['restored'], 2)
            self.assertEqual(result['silver']['archiveRestored'], 1)
            with repo._connect() as conn:
                event_states = [r[0] for r in conn.execute("SELECT association_state FROM history_event_media WHERE asset_key IN ('a1','a2') ORDER BY asset_key").fetchall()]
                silver_edges = conn.execute("SELECT COUNT(*) FROM history_collection_media WHERE asset_key IN ('s1','s2')").fetchone()[0]
                marker = conn.execute("SELECT value FROM history_catalog_meta WHERE key='database_authority_recovery_version'").fetchone()[0]
            self.assertEqual(event_states, ['ASSIGNED','ASSIGNED'])
            self.assertEqual(silver_edges, 2)
            self.assertEqual(marker, '4721')


class V4721GameCenterCoverageTests(unittest.TestCase):
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

    def _load_game_center_module(self):
        gc = types.ModuleType('sbb.game_center')
        gc.normalize_espn_summary = lambda payload, competition, event_id: {}
        gc.fetch_espn_game_center = lambda *a, **k: None
        gc._safe = lambda v: '' if v is None else v
        gc._espn_status_parts = lambda payload: ({}, {}, {}, '', '', '', 0)
        gc._espn_flat_plays = lambda payload: []
        def coverage(data):
            return {'complete': True, 'final': True, 'live': False, 'scheduled': False, 'missing': [], 'richness': 10}
        gc.game_center_coverage = coverage
        gc._apply_coverage_fields = lambda out: out
        sys.modules['sbb.game_center'] = gc
        return load_module('sbb.game_center_multisport', ROOT / 'sbb/game_center_multisport.py')

    def test_completed_period_sports_require_linescore_periods(self):
        mod = self._load_game_center_module()
        for competition in ('NFL', 'CFB', 'NBA', 'NHL'):
            out = mod.game_center_coverage({'competitionId': competition, 'scoreboard': {}})
            self.assertFalse(out['complete'], competition)
            self.assertIn('linescore', out['missing'], competition)
            self.assertEqual(out['periods'], 0)

            out = mod.game_center_coverage({'competitionId': competition, 'scoreboard': {'periods': [{'num': 1, 'away': 7, 'home': 3}]}})
            self.assertTrue(out['complete'], competition)
            self.assertEqual(out['periods'], 1)


if __name__ == '__main__':
    unittest.main()

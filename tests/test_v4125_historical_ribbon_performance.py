import inspect
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from sbb.history_repository import HistoryRepository


class V4125HistoricalRibbonPerformanceTests(unittest.TestCase):
    def _repo_with_two_games(self, td):
        repo=HistoryRepository(Path(td)/'history.sqlite3')
        fixtures=[
            ('g1','green','Toronto Blue Jays','TOR','New York Yankees','NYY',210),
            ('g2','blue','New York Mets','NYM','Chicago White Sox','CHW',90),
        ]
        rows=[]
        for idx,(event_id,tier,away_name,away_abbr,home_name,home_abbr,duration) in enumerate(fixtures,1):
            row={
                'id':event_id,'eventId':event_id,'status':'Final','date':'2026-08-22',
                'awayTeam':{'displayName':away_name,'abbreviation':away_abbr},
                'homeTeam':{'displayName':home_name,'abbreviation':home_abbr},
            }
            rows.append(row)
            repo.put_scores('2026-08-22','MLB',rows)
            repo.put_event_media('2026-08-22','MLB',event_id,[{
                'id':f'm{idx}','eventId':event_id,'matchId':event_id,'gameDate':'2026-08-22',
                'away':away_name,'home':home_name,
                'title':f'{away_name} vs. {home_name}: Official Game Highlights',
                'youtubeId':f'abcdefghij{idx}','provider':'YOUTUBE','verifiedPlayable':True,
                'validationState':'VERIFIED','durationSeconds':duration,
                'duration':duration,'recapTier':tier,
                'mediaScope':'GAME','scope':'GAME',
            }])
        repo.put_scores('2026-08-22','MLB',rows)
        return repo

    def test_release_boundary_advances_to_4125(self):
        root=Path(__file__).resolve().parents[1]
        index=(root/'index.html').read_text(encoding='utf-8')
        self.assertEqual(server.APP_VERSION,'4.1.29')
        self.assertIn('app.js?v=4.1.29',index)
        self.assertIn('styles.css?v=4.1.29',index)
        self.assertNotIn('app.js?v=4.1.24',index)

    def test_score_rows_do_not_hydrate_catalog_media(self):
        with tempfile.TemporaryDirectory() as td:
            repo=self._repo_with_two_games(td)
            def forbidden(*_args,**_kwargs):
                raise AssertionError('score ribbon attempted full catalog media hydration')
            repo._catalog_media_for_league=forbidden
            with patch.object(server,'HISTORY_REPOSITORY',repo):
                rows=server._history_day_score_rows('2026-08-22')
            self.assertEqual(len(rows['MLB']),2)

    def test_compact_plan_uses_one_bulk_media_read_not_event_n_plus_one(self):
        with tempfile.TemporaryDirectory() as td:
            repo=self._repo_with_two_games(td)
            calls={'bulk':0}
            original=repo.ribbon_media_for_date
            def bulk(*args,**kwargs):
                calls['bulk']+=1
                return original(*args,**kwargs)
            repo.ribbon_media_for_date=bulk
            def forbidden(*_args,**_kwargs):
                raise AssertionError('N+1 event_media lookup used by ribbon')
            repo.event_media=forbidden
            with patch.object(server,'HISTORY_REPOSITORY',repo):
                rows=server._history_day_score_rows('2026-08-22')
                plans=server._history_day_ribbon_plans('2026-08-22',rows)
            self.assertEqual(calls['bulk'],1)
            self.assertEqual(plans['MLB:g1']['catalogPlayableCount'],1)
            self.assertEqual(plans['MLB:g1']['catalogTier'],'GREEN')
            self.assertEqual(plans['MLB:g2']['catalogPlayableCount'],1)
            self.assertIn(plans['MLB:g2']['catalogTier'],{'GOLD','GREEN','EXTENDED','BLUE'})

    def test_latency_sensitive_reads_do_not_wait_on_repository_write_lock(self):
        with tempfile.TemporaryDirectory() as td:
            repo=self._repo_with_two_games(td)
            result={}
            repo._lock.acquire()
            try:
                t=threading.Thread(target=lambda: result.setdefault('rows',repo.get_league('2026-08-22','MLB',prefer_catalog=False)['scores']))
                t.start(); t.join(0.75)
                self.assertFalse(t.is_alive(),'read path is still serialized by the process-wide RLock')
            finally:
                repo._lock.release()
                if 't' in locals(): t.join(2)
            self.assertEqual(len(result.get('rows') or []),2)

    def test_wal_is_initialized_once_not_negotiated_per_connection(self):
        connect_source=inspect.getsource(HistoryRepository._connect)
        init_source=inspect.getsource(HistoryRepository._init_db)
        self.assertNotIn('conn.execute("PRAGMA journal_mode=WAL")',connect_source)
        self.assertIn('conn.execute("PRAGMA journal_mode=WAL")',init_source)
        self.assertIn('query_only=ON',inspect.getsource(HistoryRepository._read_connect))

    def test_frontend_merges_exact_catalog_media_even_when_manifest_is_empty(self):
        root=Path(__file__).resolve().parents[1]
        app=(root/'app.js').read_text(encoding='utf-8')
        block=app[app.index('function scoreCardPlayableItems'):app.index('function scoreCardPlaybackSelection')]
        self.assertIn('[...manifestPlayable,...discovered]',block)
        self.assertIn('__sbbCatalogExact',block)
        self.assertNotIn('?.playable?.(match)||discovered',block)

    def test_ribbon_contract_exposes_server_timing_and_catalog_diagnostics(self):
        root=Path(__file__).resolve().parents[1]
        backend=(root/'server.py').read_text(encoding='utf-8')
        app=(root/'app.js').read_text(encoding='utf-8')
        self.assertIn("'catalogPlayableCount':len(playable)",backend)
        self.assertIn("'catalogTier':tier",backend)
        self.assertIn("'scoresMs'",backend)
        self.assertIn("'mediaMs'",backend)
        self.assertIn("'totalMs'",backend)
        self.assertIn("'Server-Timing'",backend)
        self.assertIn('historical ribbon timing',app)


if __name__ == '__main__':
    unittest.main()

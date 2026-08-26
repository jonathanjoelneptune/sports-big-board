import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from sbb.history_repository import HistoryRepository


ROOT=Path(__file__).resolve().parents[1]
RELEASE_VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()


class V4124HistoricalRibbonTests(unittest.TestCase):
    def test_release_boundary_and_static_cache_buster_advance(self):
        root=Path(__file__).resolve().parents[1]
        index=(root/'index.html').read_text(encoding='utf-8')
        self.assertEqual(server.APP_VERSION,RELEASE_VERSION)
        self.assertIn(f'app.js?v={RELEASE_VERSION}',index)
        self.assertIn(f'styles.css?v={RELEASE_VERSION}',index)
        self.assertNotIn('app.js?v=4.1.23',index)

    def test_persisted_seed_marker_is_authoritative_after_restart(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3')
            repo.set_catalog_meta('historical_seed_floor_date',server.HISTORY_BACKFILL_FLOOR_DATE)
            repo.set_catalog_meta('historical_seed_complete','1')
            repo.set_catalog_meta('historical_seed_completed_at','1')
            old=dict(server.HISTORY_BACKFILL_STATE)
            try:
                server.HISTORY_BACKFILL_STATE.update(seedComplete=False)
                with patch.object(server,'HISTORY_REPOSITORY',repo), patch.object(server,'_client_date_iso',return_value='2026-08-25'):
                    self.assertTrue(server._history_day_score_inventory_complete('2026-08-22'))
            finally:
                server.HISTORY_BACKFILL_STATE.clear(); server.HISTORY_BACKFILL_STATE.update(old)

    def test_ribbon_rows_come_directly_from_persisted_score_catalog(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3')
            row={
                'id':'401816643','status':'Final','date':'2026-08-22',
                'awayTeam':{'displayName':'Toronto Blue Jays','abbreviation':'TOR'},
                'homeTeam':{'displayName':'New York Yankees','abbreviation':'NYY'},
                'awayScore':3,'homeScore':8,
            }
            repo.put_scores('2026-08-22','MLB',[row])
            with patch.object(server,'HISTORY_REPOSITORY',repo):
                rows=server._history_day_score_rows('2026-08-22')
            self.assertEqual(len(rows['MLB']),1)
            self.assertEqual(rows['MLB'][0]['id'],'401816643')
            self.assertEqual(rows['MLB'][0]['awayTeam']['abbreviation'],'TOR')
            self.assertEqual(rows['MLB'][0]['homeTeam']['abbreviation'],'NYY')

    def test_compact_ribbon_plan_contains_exact_playable_media(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3')
            row={
                'id':'g1','status':'Final','date':'2026-08-22',
                'awayTeam':{'displayName':'Toronto Blue Jays','abbreviation':'TOR'},
                'homeTeam':{'displayName':'New York Yankees','abbreviation':'NYY'},
            }
            repo.put_scores('2026-08-22','MLB',[row])
            media={
                'id':'m1','eventId':'g1','matchId':'g1','gameDate':'2026-08-22',
                'away':'Toronto Blue Jays','home':'New York Yankees',
                'title':'BLUE JAYS vs. YANKEES: Official Full Game Highlights',
                'youtubeId':'abcdefghijk','provider':'YOUTUBE','verifiedPlayable':True,
                'validationState':'VERIFIED','durationSeconds':816,'duration':816,
                'recapTier':'extended','mediaScope':'GAME','scope':'GAME',
            }
            repo.put_event_media('2026-08-22','MLB','g1',[media])
            with patch.object(server,'HISTORY_REPOSITORY',repo):
                rows=server._history_day_score_rows('2026-08-22')
                plans=server._history_day_ribbon_plans('2026-08-22',rows)
            self.assertIn('MLB:g1',plans)
            self.assertEqual(plans['MLB:g1']['event']['id'],'g1')
            self.assertTrue(plans['MLB:g1']['playable'])
            self.assertEqual(plans['MLB:g1']['primary']['youtubeId'],'abcdefghijk')
            self.assertEqual(plans['MLB:g1']['media'],[])

    def test_frontend_uses_compact_ribbon_before_full_history_payload(self):
        root=Path(__file__).resolve().parents[1]
        app=(root/'app.js').read_text(encoding='utf-8')
        backend=(root/'server.py').read_text(encoding='utf-8')
        self.assertIn('parsed.path == "/api/history/ribbon"',backend)
        self.assertIn("'scoreRowsByLeague':score_rows",backend)
        self.assertIn('async function hydrateHistoricalRibbonFromCatalog',app)
        self.assertIn('/api/history/ribbon?date=',app)
        self.assertIn('apiJsonTimed(`/api/history/ribbon?date=',app)
        self.assertIn('6500',app)
        self.assertIn("source:'CATALOG_RIBBON'",app)
        self.assertIn("hydrateScoreDateFromHistory(date,{scores:false})",app)
        self.assertIn('Historical catalog unavailable — tap the date to retry',app)

    def test_today_key_info_paints_cache_before_forced_refresh(self):
        root=Path(__file__).resolve().parents[1]
        app=(root/'app.js').read_text(encoding='utf-8')
        browse=app[app.index('async function setScoreBrowseDate'):app.index('function stepScoreRibbonDate')]
        cached=browse.index('refreshKeyInformation(false,false)')
        forced=browse.index('refreshKeyInformation(false,true)')
        self.assertLess(cached,forced)
        self.assertIn('lastKeyInfoRefresh=0',browse)


if __name__ == '__main__':
    unittest.main()

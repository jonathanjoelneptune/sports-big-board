import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sbb.competition_builder as cb

ROOT=Path(__file__).resolve().parents[1]

class _Repo:
    def __init__(self): self.events=[]
    def upsert_event(self,date,league,event_id,event): self.events.append((date,league,event_id,event))

class _Server:
    OPENAI_MODEL='gpt-5-mini'
    def __init__(self):
        self.HISTORY_LEAGUES=('MLB','NFL','NBA','NHL','EPL','MLS')
        self.HISTORY_REPOSITORY=_Repo()
    def _operator_media_playlists_load(self): return []
    def _operator_media_playlists_save(self,rows): return rows
    def _operator_media_playlist_crawl_async(self,*a,**k): return None
    def _operator_media_playlist_normalize(self,raw,existing=None): return {**(existing or {}),**raw,'id':'test-playlist'}
    def _youtube_playlist_id(self,value): return ''

class V461CompetitionBuilderHardeningTests(unittest.TestCase):
    def test_keyboard_inputs_do_not_reach_playback_shortcuts(self):
        src=(ROOT/'architecture/competition-builder.js').read_text(encoding='utf-8')
        self.assertIn("matches?.('input,textarea,select')",src)
        self.assertIn('ev.stopPropagation()',src)
        self.assertIn('CREATED SITE-WIDE ✓',src)
        self.assertIn('Server read-back verification failed',src)
        self.assertIn('lastCatalogAt>5000',src)

    def test_save_is_durable_and_revisioned(self):
        server=_Server()
        with tempfile.TemporaryDirectory() as td:
            old_store,old_rev=cb._STORE,cb._CATALOG_REVISION
            try:
                cb._STORE=Path(td)/'custom-competitions.json';cb._CATALOG_REVISION=0
                saved=cb.save_competition({
                    'id':'TEST26','name':'Test Competition','shortName':'TEST','type':'LEAGUE',
                    'sportId':'football','startDate':'2026-08-01','endDate':'2026-09-01',
                    'mediaSources':{},'crawlEnabled':True,'backgroundDiscovery':True
                },[{'eventId':'1','date':'2026-08-28','away':'A','home':'B','status':'FINAL'}],server)
                self.assertEqual(saved['id'],'TEST26')
                self.assertTrue(cb._STORE.exists())
                first=cb._store_revision();self.assertGreater(first,0)
                persisted=cb._find('TEST26');self.assertIsNotNone(persisted)
                self.assertEqual(len(persisted['events']),1)
                self.assertIn('TEST26',server.HISTORY_LEAGUES)
            finally:
                cb._STORE,cb._CATALOG_REVISION=old_store,old_rev

    def test_discovery_falls_back_to_official_page(self):
        server=_Server()
        result={'sourceUrls':['https://official.test/schedule'],'sourceLabel':'Official','events':[
            {'eventId':'g1','date':'2026-06-11','scheduledAt':'2026-06-11T12:00:00','away':'A','home':'B','awayScore':1,'homeScore':0,'status':'FINAL','round':'Group A','stage':'Group','venue':'Stadium','broadcast':'TV','sourceUrl':'https://official.test/g1'}
        ]}
        calls=[]
        def request(_server,_model,_prompt,_schema,_name,use_web=True,**kwargs):
            calls.append(use_web)
            if use_web: raise RuntimeError('web search unavailable')
            return result
        with patch.object(cb,'_discovery_plan',return_value={'expectedEventCount':1,'sourceUrls':['https://official.test/schedule'],'sourceLabel':'Official','notes':''}), \
             patch.object(cb,'_date_windows',return_value=[('2026-06-11','2026-06-11')]), \
             patch.object(cb,'_openai_json_request',side_effect=request), \
             patch.object(cb,'_official_page_text',return_value='Official schedule page content '+('x'*500)):
            out=cb.discover_schedule(server,{
                'id':'WC2026','name':'2026 FIFA World Cup','type':'SPECIAL_EVENT','sportId':'football',
                'startDate':'2026-06-11','endDate':'2026-07-19','scheduleSourceUrl':'https://official.test/schedule'
            })
        self.assertEqual(calls,[True,False])
        self.assertTrue(out['complete'])
        self.assertEqual(out['discoveredEventCount'],1)
        self.assertEqual(len(out['events']),1)
        self.assertEqual(out['windowReports'][0]['mode'],'OFFICIAL_PAGE')

    def test_custom_competition_reports_crawl_enrollment(self):
        server=_Server();server.HISTORY_LEAGUES=server.HISTORY_LEAGUES+('CUP26',)
        server._operator_media_playlists_load=lambda:[{'id':'p1','league':'CUP26','playlistId':'PL1','objective':'quick','enabled':True}]
        comp={'id':'CUP26','backgroundDiscovery':True,'crawlEnabled':True}
        snap=cb._crawl_enrollment(server,comp)
        self.assertTrue(snap['historyLeague'])
        self.assertTrue(snap['backgroundDiscovery'])
        self.assertTrue(snap['crawlEnabled'])
        self.assertEqual(len(snap['operatorPlaylists']),1)
        src=(ROOT/'sbb/competition_builder.py').read_text(encoding='utf-8')
        self.assertIn('sbb-custom-competition-crawl',src)
        self.assertIn('SBB_CUSTOM_COMPETITION_CRAWL_INTERVAL',src)

if __name__=='__main__': unittest.main()

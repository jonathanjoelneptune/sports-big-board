import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import sbb.competition_builder as cb

ROOT=Path(__file__).resolve().parents[1]

class _Repo:
    def __init__(self,path):
        self.path=str(path);self._lock=threading.RLock()
        c=self._connect()
        c.executescript("""
        CREATE TABLE history_catalog_event(canonical_event_key TEXT PRIMARY KEY, league TEXT);
        CREATE TABLE history_event_media(canonical_event_key TEXT, asset_key TEXT);
        CREATE TABLE history_discovery_attempt(canonical_event_key TEXT);
        CREATE TABLE history_source_enrichment(canonical_event_key TEXT);
        CREATE TABLE history_media_segment(canonical_event_key TEXT);
        CREATE TABLE history_collection(collection_key TEXT PRIMARY KEY, league TEXT);
        CREATE TABLE history_collection_media(collection_key TEXT);
        CREATE TABLE history_assignment_review(league TEXT);
        CREATE TABLE history_day(league TEXT);
        """)
        c.commit();c.close()
    def _connect(self):
        c=sqlite3.connect(self.path)
        c.execute("PRAGMA foreign_keys=ON")
        return c
    def upsert_event(self,date,league,event_id,event):
        c=self._connect()
        c.execute("INSERT OR REPLACE INTO history_catalog_event(canonical_event_key,league) VALUES(?,?)",(f"{league}:{event_id}",league))
        c.execute("INSERT INTO history_day(league) VALUES(?)",(league,))
        c.commit();c.close()

class _Server:
    def __init__(self,path):
        self.HISTORY_REPOSITORY=_Repo(path)
        self.HISTORY_LEAGUES=('MLB','NFL','NBA','NHL','EPL','MLS')
        self.playlists=[]
    def _operator_media_playlists_load(self):return list(self.playlists)
    def _operator_media_playlists_save(self,rows):self.playlists=list(rows);return rows
    def _operator_media_playlist_crawl_async(self,*a,**k):return None
    def _operator_media_playlist_normalize(self,raw,existing=None):return {**(existing or {}),**raw,'id':'p1'}
    def _youtube_playlist_id(self,value):return ''

class V462CompetitionBuilderResearchDeleteTests(unittest.TestCase):
    def test_world_cup_uses_bounded_windows(self):
        windows=cb._date_windows('2026-06-11','2026-07-19')
        self.assertGreater(len(windows),1)
        self.assertEqual(windows[0][0],'2026-06-11')
        self.assertEqual(windows[-1][1],'2026-07-19')
        self.assertLessEqual(len(windows),8)

    def test_discovery_aggregates_multiple_windows_to_completeness(self):
        class Server: OPENAI_MODEL='gpt-5-mini'
        def req(_server,_model,prompt,_schema,_name,use_web=True,**kwargs):
            if '2026-06-11 and 2026-06-17' in prompt:
                rows=[
                    {'eventId':'1','date':'2026-06-11','scheduledAt':'','away':'A','home':'B','awayScore':1,'homeScore':0,'status':'FINAL','round':'Group','stage':'Group','venue':'V1','broadcast':'','sourceUrl':'u1'},
                    {'eventId':'2','date':'2026-06-12','scheduledAt':'','away':'C','home':'D','awayScore':2,'homeScore':1,'status':'FINAL','round':'Group','stage':'Group','venue':'V2','broadcast':'','sourceUrl':'u2'}]
            else:
                rows=[
                    {'eventId':'3','date':'2026-06-18','scheduledAt':'','away':'E','home':'F','awayScore':0,'homeScore':0,'status':'FINAL','round':'Group','stage':'Group','venue':'V3','broadcast':'','sourceUrl':'u3'},
                    {'eventId':'4','date':'2026-06-19','scheduledAt':'','away':'G','home':'H','awayScore':3,'homeScore':2,'status':'FINAL','round':'Group','stage':'Group','venue':'V4','broadcast':'','sourceUrl':'u4'}]
            return {'sourceUrls':['https://official.test'],'sourceLabel':'Official','events':rows}
        with patch.object(cb,'_discovery_plan',return_value={'expectedEventCount':4,'sourceUrls':['https://official.test'],'sourceLabel':'Official','notes':''}), \
             patch.object(cb,'_date_windows',return_value=[('2026-06-11','2026-06-17'),('2026-06-18','2026-06-24')]), \
             patch.object(cb,'_official_page_text',return_value=''), \
             patch.object(cb,'_openai_json_request',side_effect=req):
            out=cb.discover_schedule(Server(),{'id':'CUP26','name':'Cup','type':'SPECIAL_EVENT','sportId':'football','startDate':'2026-06-11','endDate':'2026-06-24','expectedEventCount':4})
        self.assertTrue(out['complete'])
        self.assertEqual(out['discoveredEventCount'],4)
        self.assertEqual(len(out['windowReports']),2)

    def test_merge_deduplicates_same_event(self):
        rows=[
            {'eventId':'73','date':'2026-06-28','away':'A','home':'B','status':'FINAL','awayScore':'','homeScore':''},
            {'eventId':'73','date':'2026-06-28','away':'A','home':'B','status':'FINAL','awayScore':1,'homeScore':0},
        ]
        merged=cb._merge_discovered_events(rows)
        self.assertEqual(len(merged),1)
        self.assertEqual(merged[0]['awayScore'],1)

    def test_zero_and_partial_schedule_cannot_activate(self):
        with tempfile.TemporaryDirectory() as td:
            old_store,old_rev=cb._STORE,cb._CATALOG_REVISION
            cb._STORE=Path(td)/'custom.json';cb._CATALOG_REVISION=0
            try:
                raw={'id':'WC2026','name':'World Cup','type':'SPECIAL_EVENT','sportId':'football','startDate':'2026-06-11','endDate':'2026-07-19','expectedEventCount':104}
                with self.assertRaisesRegex(ValueError,'zero schedule events'):
                    cb.save_competition(raw,[],None)
                one=[{'eventId':'1','date':'2026-06-11','away':'A','home':'B','status':'FINAL'}]
                with self.assertRaisesRegex(ValueError,'1/104'):
                    cb.save_competition(raw,one,None)
            finally:
                cb._STORE,cb._CATALOG_REVISION=old_store,old_rev

    def test_delete_is_site_wide_and_purges_custom_history(self):
        with tempfile.TemporaryDirectory() as td:
            old_store,old_rev=cb._STORE,cb._CATALOG_REVISION
            cb._STORE=Path(td)/'custom.json';cb._CATALOG_REVISION=0
            server=_Server(Path(td)/'history.db')
            try:
                saved=cb.save_competition(
                    {'id':'TEST26','name':'Test','type':'SPECIAL_EVENT','sportId':'football','startDate':'2026-08-01','endDate':'2026-08-30'},
                    [{'eventId':'g1','date':'2026-08-20','away':'A','home':'B','status':'FINAL'}],server)
                self.assertIsNotNone(cb._find('TEST26'))
                self.assertIn('TEST26',server.HISTORY_LEAGUES)
                server.playlists=[{'id':'p1','league':'TEST26'},{'id':'keep','league':'NFL'}]
                result=cb.delete_competition(server,'TEST26',purge=True)
                self.assertIsNone(cb._find('TEST26'))
                self.assertNotIn('TEST26',server.HISTORY_LEAGUES)
                self.assertEqual([x['id'] for x in server.playlists],['keep'])
                c=server.HISTORY_REPOSITORY._connect()
                self.assertEqual(c.execute("SELECT COUNT(*) FROM history_catalog_event WHERE league='TEST26'").fetchone()[0],0)
                self.assertEqual(c.execute("SELECT COUNT(*) FROM history_day WHERE league='TEST26'").fetchone()[0],0)
                c.close()
                self.assertTrue(result['purged'])
            finally:
                cb._STORE,cb._CATALOG_REVISION=old_store,old_rev

    def test_frontend_has_delete_and_completeness_guards(self):
        src=(ROOT/'architecture/competition-builder.js').read_text(encoding='utf-8')
        for token in ('CONFIRM DELETE','expectedEventCount','PARTIAL SCHEDULE — NOT READY TO CREATE',"cbExpectedEvents').value='104'","cbExpectedEvents').value='38'",'.sbb-builder-actions .hidden'):
            self.assertIn(token,src)

if __name__=='__main__':unittest.main()

import tempfile
import unittest
from pathlib import Path

import sbb.competition_builder as cb

ROOT=Path(__file__).resolve().parents[1]

class _PlaylistServer:
    def __init__(self):
        self.rows=[];self.saved=False;self.crawled=[]
    def _operator_media_playlists_load(self):return list(self.rows)
    def _operator_media_playlists_save(self,rows):self.rows=list(rows);self.saved=True;return rows
    def _operator_media_playlist_normalize(self,raw,existing=None):return {**(existing or {}),**raw,'id':'playlist-1','stats':(existing or {}).get('stats',{})}
    def _operator_media_playlist_crawl_async(self,pid,force=False):
        if not self.saved:raise AssertionError('crawl started before playlist registration was saved')
        self.crawled.append((pid,force))
    def _youtube_playlist_id(self,url):return 'PLTEST'

class V464CustomRuntimeBridgeTests(unittest.TestCase):
    def test_world_cup_auto_artwork_uses_country_flags(self):
        comp=cb.normalize_definition({'id':'WC2026','name':'2026 FIFA World Cup','type':'SPECIAL_EVENT','sportId':'football','startDate':'2026-06-11','endDate':'2026-07-19'})
        self.assertEqual(comp['effectiveLogoStrategy'],'COUNTRY_FLAGS')
        ev=cb.normalize_event(comp,{'eventId':'g1','date':'2026-06-12','away':'Mexico','home':'United States','status':'FINAL'},0)
        self.assertEqual(ev['awayTeam']['countryCode'],'MX')
        self.assertEqual(ev['homeTeam']['countryCode'],'US')
        self.assertIn('flagcdn.com/w80/mx.png',ev['awayTeam']['logo'])
        self.assertIn('flagcdn.com/w80/us.png',ev['homeTeam']['logo'])

    def test_operator_playlist_is_saved_before_async_crawl(self):
        server=_PlaylistServer()
        comp=cb.normalize_definition({'id':'CUP26','name':'Cup','type':'SPECIAL_EVENT','sportId':'football','startDate':'2026-06-01','endDate':'2026-06-30','mediaSources':{'green':['https://www.youtube.com/playlist?list=PLTEST']}})
        ids=cb._register_media_sources(server,comp,force_crawl=True)
        self.assertTrue(server.saved)
        self.assertEqual(ids,['playlist-1'])
        self.assertEqual(server.crawled,[('playlist-1',True)])

    def test_frontend_rebuilds_verified_media_index_after_custom_hydration(self):
        src=(ROOT/'architecture/competition-builder.js').read_text(encoding='utf-8')
        self.assertIn("rebuildVerifiedMediaIndex(SCORE_DATE_STORE?.allMedia?.(date)||media)",src)
        self.assertIn("SCORE_DATE_STORE?.setMedia?.(date,c.id,media)",src)
        self.assertIn("console.info('[SBB custom] hydrated'",src)

    def test_special_event_dropdown_is_portaled_out_of_overflowing_filter_row(self):
        src=(ROOT/'architecture/competition-builder.js').read_text(encoding='utf-8')
        self.assertIn("document.body.appendChild(menu)",src)
        self.assertIn("position:fixed;z-index:20050",src)
        self.assertIn("placeSpecialMenu()",src)
        self.assertIn("c.mainRow===true&&mainRowEligible(c)",src)

    def test_custom_media_endpoint_forces_canonical_event_identity_and_can_repair(self):
        src=(ROOT/'sbb/competition_builder.py').read_text(encoding='utf-8')
        for token in ('scoreEventId','canonicalEventId','_repair_event_media','_league_source_media','/api/competition-builder/health','force_crawl=True'):
            self.assertIn(token,src)
        self.assertIn('x.update({"league":cid',src)

    def test_wizard_exposes_participant_artwork_and_repair_media(self):
        src=(ROOT/'architecture/competition-builder.js').read_text(encoding='utf-8')
        for token in ('PARTICIPANT ARTWORK','COUNTRY FLAGS','TEAM / CLUB LOGOS','cbLogoStrategy',"$('cbLogoStrategy').value='COUNTRY_FLAGS'",'REPAIR MEDIA'):
            self.assertIn(token,src)

if __name__=='__main__':unittest.main()

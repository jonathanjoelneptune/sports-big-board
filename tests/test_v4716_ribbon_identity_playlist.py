import unittest
import sys
import types
from pathlib import Path

# The downloadable release bundle contains only changed repo files. Provide tiny
# import-time stubs for unchanged package modules so this focused gate also runs
# against the bundle by itself; the full repository uses the real modules.
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
registry=types.ModuleType('sbb.competition_registry')
registry.revision=lambda:1
registry.catalog=lambda:[]
registry.register=lambda *a,**k:None
registry.COMPETITIONS={}
sys.modules.setdefault('sbb.competition_registry',registry)
builder=types.ModuleType('sbb.competition_builder')
builder._find=lambda *a,**k:None
builder.save_competition=lambda *a,**k:None
sys.modules.setdefault('sbb.competition_builder',builder)

from sbb import day_state
from sbb import cfb_ranked
from sbb import operator_playlist_contract


class FakePlanServer:
    def _history_media_match_evidence(self,item,event):
        title=str(item.get('title') or '')
        assigned='August 29' in title
        return ({'mediaScope':'GAME'}, {'associationState':'ASSIGNED' if assigned else 'QUARANTINED','associationMethod':'DATE_MISMATCH' if not assigned else 'EXACT_TEAM_PAIR_TITLE'})


class FakePlaylistServer:
    def __init__(self):
        self.HISTORY_LEAGUES=('MLB','CFB')
        self.rows=[{
            'id':'playlist-cfb','league':'CFB','playlistId':'PLPydJJjt7Pb4',
            'url':'https://www.youtube.com/playlist?list=PLPydJJjt7Pb4',
            'title':'Full Game Highlights | 2026-27','seasonStart':2026,'seasonEnd':2026,
            'objective':'extended','priority':'PRIMARY','trust':'OPERATOR_TRUSTED',
            'enabled':True,'autoRecrawl':True,'recrawlMinutes':60,'stats':{},'lastCrawlAt':1,
        }]
        self.saved=0;self.crawled=[]

    def _operator_media_playlist_normalize(self,raw,existing=None):
        existing=dict(existing or {});raw=dict(raw or {})
        return {**existing,
            'id':existing.get('id') or 'playlist-cfb','league':raw.get('league') or existing.get('league'),
            'playlistId':raw.get('playlistId') or existing.get('playlistId'),'url':raw.get('url') or existing.get('url'),
            'title':raw.get('title') or existing.get('title') or 'Full Game Highlights | 2026-27',
            'seasonStart':int(raw.get('seasonStart') or existing.get('seasonStart') or 0),
            'seasonEnd':int(raw.get('seasonEnd') or existing.get('seasonEnd') or 0),
            'objective':raw.get('objective') or existing.get('objective'),'priority':raw.get('priority') or existing.get('priority'),
            'trust':raw.get('trust') or existing.get('trust'),'enabled':True,'autoRecrawl':True,
            'recrawlMinutes':int(raw.get('recrawlMinutes') or 60),'channelId':'','channelTitle':'ESPN College Football',
            'stats':existing.get('stats') or {},'lastCrawlAt':existing.get('lastCrawlAt') or 0,
        }

    def _operator_playlist_to_curated(self,row):
        return {'playlistId':row.get('playlistId'),'includeAllItems':True,'sourceLabel':row.get('title'),'objective':row.get('objective')}

    def _curated_playlist_items(self,league,playlist,force=False):
        return [
            {'youtubeId':'good','title':'USC vs SJSU: Full Game Highlights (August 29) | 2026 College Football'},
            {'youtubeId':'noise','title':'USC vs SJSU Postgame Interview'},
        ]

    def _operator_media_playlists_load(self):return [dict(x) for x in self.rows]
    def _operator_media_playlists_save(self,rows):self.rows=[dict(x) for x in rows];self.saved+=1
    def _operator_media_playlist_crawl_async(self,playlist_id,force=True):self.crawled.append((playlist_id,bool(force)))
    def _youtube_playlist_id(self,value):
        return 'PLPydJJjt7Pb4' if 'PLPydJJjt7Pb4' in str(value or '') else ''


class V4716RibbonIdentityPlaylistTests(unittest.TestCase):
    def test_day_state_revalidates_stale_event_media(self):
        plans={'MLB:game-2':{
            'date':'2026-08-29','league':'MLB','eventId':'game-2',
            'event':{'id':'game-2','date':'2026-08-29','competitionId':'MLB','away':'ARI','home':'SF'},
            'media':[{'id':'bad','title':'D-BACKS vs. GIANTS: Official Full Game Highlights (August 28) | 2026 MLB Season'},
                     {'id':'good','title':'D-BACKS vs. GIANTS: Official Full Game Highlights (August 29) | 2026 MLB Season'}],
            'playable':[{'id':'bad','title':'D-BACKS vs. GIANTS: Official Full Game Highlights (August 28) | 2026 MLB Season'},
                        {'id':'good','title':'D-BACKS vs. GIANTS: Official Full Game Highlights (August 29) | 2026 MLB Season'}],
            'primary':{'id':'bad'}
        }}
        safe,stats=day_state._sanitize_event_plans(FakePlanServer(),plans)
        self.assertEqual([x['id'] for x in safe['MLB:game-2']['playable']],['good'])
        self.assertEqual(safe['MLB:game-2']['primary']['id'],'good')
        self.assertEqual(stats['rejected'],2)
        self.assertGreaterEqual(stats['checked'],4)

    def test_same_physical_media_cannot_own_two_doubleheader_events_without_provider_identity(self):
        item={'youtubeId':'same-video','title':'ARI vs SF Full Game Highlights (August 29)'}
        plans={
            'MLB:g1':{'date':'2026-08-29','league':'MLB','eventId':'g1','event':{'id':'g1','date':'2026-08-29','competitionId':'MLB','away':'ARI','home':'SF'},'media':[dict(item)],'playable':[dict(item)]},
            'MLB:g2':{'date':'2026-08-29','league':'MLB','eventId':'g2','event':{'id':'g2','date':'2026-08-29','competitionId':'MLB','away':'ARI','home':'SF'},'media':[dict(item)],'playable':[dict(item)]},
        }
        safe,stats=day_state._sanitize_event_plans(FakePlanServer(),plans)
        self.assertEqual(safe['MLB:g1']['playable'],[])
        self.assertEqual(safe['MLB:g2']['playable'],[])
        self.assertEqual(stats['ambiguousAssets'],1)
        self.assertEqual(stats['ambiguousRejected'],4)

    def test_cfb_playlist_contract_is_enforced_end_to_end(self):
        source=cfb_ranked._definition(1)['mediaSources']['purple'][0]
        self.assertEqual(source['url'],'https://www.youtube.com/playlist?list=PLPydJJjt7Pb4')
        self.assertEqual(source['titleIncludePhrase'],'full game highlights')
        self.assertEqual(source['sourceType'],'espn-college-football-full-game-highlights')

        server=FakePlaylistServer()
        report=operator_playlist_contract.ensure_competition_sources(server,cfb_ranked._definition(1),force=True)
        self.assertTrue(report['ok'])
        self.assertEqual(report['seasonStart'],2026)
        self.assertEqual(report['seasonEnd'],2027)
        row=server.rows[0]
        self.assertEqual(row['seasonEnd'],2027)
        self.assertEqual(row['titleIncludePhrase'],'full game highlights')
        self.assertEqual(row['sourceLabel'],'ESPN College Football — Full Game Highlights | 2026-27')
        self.assertFalse(row['includeAllItems'])

        cfg=server._operator_playlist_to_curated(row)
        items=server._curated_playlist_items('CFB',cfg,force=True)
        self.assertEqual([x['youtubeId'] for x in items],['good'])
        self.assertEqual(items[0]['sourceType'],'espn-college-football-full-game-highlights')
        self.assertTrue(server.crawled)


if __name__=='__main__':
    unittest.main()

import threading
import time
import unittest
import tempfile
import io
from urllib.error import HTTPError
from pathlib import Path
from unittest.mock import patch
import server
from sbb.competition_registry import enabled_ids
from sbb.media_classifier import tier
from sbb.game_center import normalize_mlb_feed, fetch_mlb_game_center, normalize_espn_summary, fetch_espn_game_center, normalize_highlightly_game_center, game_center_coverage, merge_game_centers
from sbb.media_work_scheduler import MediaWorkScheduler
from sbb.editorial_registry import catalog as editorial_catalog
from sbb.game_center_repository import GameCenterRepository
from sbb.history_repository import HistoryRepository
from sbb.youtube_gateway import YouTubeGateway

class ArchitectureTests(unittest.TestCase):
    def test_enabled_competitions(self):
        self.assertEqual(enabled_ids(),["MLB","NFL","NBA","NHL","EPL","MLS"])

    def test_media_classifier(self):
        self.assertEqual(tier({"overview":True,"title":"Official Full Game Highlights","durationSeconds":720,"source":"MLB"}),"extended")
        self.assertEqual(tier({"overview":True,"title":"Game Recap","durationSeconds":210,"source":"MLB"}),"green")
        self.assertEqual(tier({"overview":True,"title":"Postgame Recap and Analysis","durationSeconds":240,"source":"ESPN"}),"gold")
        self.assertEqual(tier({"programType":"reel","title":"Walk-off homer","durationSeconds":45,"source":"MLB"}),"blue")

    def test_mlb_game_center_contract(self):
        feed={
            "gameData":{"status":{"abstractGameState":"Final","detailedState":"Final"},"teams":{"away":{"id":1,"name":"Boston Red Sox","abbreviation":"BOS"},"home":{"id":2,"name":"San Diego Padres","abbreviation":"SD"}},"venue":{"name":"Petco Park"},"datetime":{"dateTime":"2026-08-10T20:00:00Z"}},
            "liveData":{
                "linescore":{"currentInning":9,"currentInningOrdinal":"9th","teams":{"away":{"runs":2,"hits":5,"errors":0},"home":{"runs":6,"hits":9,"errors":1}},"innings":[{"num":1,"ordinalNum":"1st","away":{"runs":0},"home":{"runs":0}},{"num":3,"ordinalNum":"3rd","away":{"runs":0},"home":{"runs":2}}]},
                "boxscore":{"teams":{"away":{"teamStats":{"batting":{"baseOnBalls":2,"strikeOuts":8,"leftOnBase":5,"homeRuns":0}},"batters":[10],"pitchers":[],"players":{"ID10":{"person":{"fullName":"Roman Anthony"},"position":{"abbreviation":"LF"},"stats":{"batting":{"atBats":3,"runs":0,"hits":1,"rbi":0,"baseOnBalls":1,"strikeOuts":1,"homeRuns":0}}}}},"home":{"teamStats":{"batting":{"baseOnBalls":4,"strikeOuts":6,"leftOnBase":7,"homeRuns":1}},"batters":[],"pitchers":[],"players":{}}}},
                "plays":{"scoringPlays":[0],"allPlays":[{"playId":"p1","about":{"inning":3,"halfInning":"bottom","isScoringPlay":True},"result":{"description":"Luis Arraez doubles. Two runs score.","awayScore":0,"homeScore":2},"matchup":{"batter":{"fullName":"Luis Arraez"}}}]}
            }
        }
        data=normalize_mlb_feed(feed,777777)
        self.assertEqual(data["event"]["competitionId"],"MLB")
        self.assertEqual(data["scoreboard"]["home"]["score"],6)
        self.assertEqual(data["scoreboard"]["venue"],"Petco Park")
        self.assertEqual(len(data["scoringPlays"]),1)
        self.assertEqual(data["playerStatSections"][0]["rows"][0][0],"Roman Anthony")


    def test_mlb_game_center_fetch_uses_v11_live_feed(self):
        calls=[]
        feed={
            "gameData":{"status":{"abstractGameState":"Final"},"teams":{"away":{"name":"A"},"home":{"name":"H"}},"datetime":{}},
            "liveData":{"linescore":{"teams":{"away":{},"home":{}},"innings":[]},"boxscore":{"teams":{"away":{},"home":{}}},"plays":{"allPlays":[],"scoringPlays":[]}}
        }
        def fake_fetch(url,timeout=0):
            calls.append(url)
            return feed
        data=fetch_mlb_game_center(824155,fake_fetch,"https://statsapi.mlb.com/api/v1")
        self.assertTrue(calls[0].startswith("https://statsapi.mlb.com/api/v1.1/game/824155/feed/live"))
        self.assertEqual(data["eventId"],"824155")

    def test_mlb_game_center_falls_back_to_v1_components(self):
        calls=[]
        def fake_fetch(url,timeout=0):
            calls.append(url)
            if "/api/v1.1/" in url:
                raise RuntimeError("feed unavailable")
            if url.endswith("/boxscore"):
                return {"teams":{"away":{"team":{"id":1,"name":"Away Club","abbreviation":"AWY"},"teamStats":{},"batters":[],"pitchers":[],"players":{}},"home":{"team":{"id":2,"name":"Home Club","abbreviation":"HME"},"teamStats":{},"batters":[],"pitchers":[],"players":{}}}}
            if url.endswith("/linescore"):
                return {"teams":{"away":{"runs":1,"hits":3,"errors":0},"home":{"runs":2,"hits":4,"errors":0}},"innings":[]}
            if url.endswith("/playByPlay"):
                return {"allPlays":[],"scoringPlays":[]}
            if "/schedule?" in url:
                return {"dates":[{"games":[{"gameDate":"2026-08-20T23:00:00Z","status":{"abstractGameState":"Final","detailedState":"Final"},"venue":{"name":"Test Park"},"teams":{}}]}]}
            raise AssertionError(url)
        data=fetch_mlb_game_center(824155,fake_fetch,"https://statsapi.mlb.com/api/v1")
        self.assertEqual(data["scoreboard"]["home"]["score"],2)
        self.assertEqual(data["scoreboard"]["venue"],"Test Park")
        self.assertTrue(any("/boxscore" in x for x in calls))


    def test_nfl_historical_score_inventory_is_scoped_by_espn_authority(self):
        payload={"data":[
            {"id":"hl-wrong-day","date":"2026-08-21T23:00:00Z","awayTeam":{"abbreviation":"NYJ"},"homeTeam":{"abbreviation":"PIT"},"status":"Scheduled"},
            {"id":"hl-raiders-texans","date":"2026-08-21T00:00:00Z","awayTeam":{"abbreviation":"LV"},"homeTeam":{"abbreviation":"HOU"},"status":"Final"}
        ]}
        authority=[
            {"id":"401873286","eventId":"401873286","date":"2026-08-21T00:00:00Z","awayTeam":{"abbreviation":"LV"},"homeTeam":{"abbreviation":"HOU"},"status":"Final","score":{"away":22,"home":20}}
        ]
        with patch.object(server,'_espn_live_authority',return_value=authority):
            result=server._reconcile_scoreboard_authority(payload,'nfl','2026-08-20','America/New_York',-240)
        rows=result['data']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['id'],'hl-raiders-texans')
        self.assertEqual(rows[0]['espnEventId'],'401873286')
        self.assertEqual(rows[0]['__sbbScoreAuthority'],'ESPN')

    def test_media_scheduler_prioritizes_waiting_work(self):
        scheduler=MediaWorkScheduler(workers=1,name="test-sbb")
        gate=threading.Event(); order=[]
        first=scheduler.submit("block",1000,lambda:(gate.wait(1),order.append("block")))
        # Allow the only worker to enter the blocker, then enqueue low before high.
        time.sleep(.05)
        low=scheduler.submit("low",100,lambda:order.append("low"))
        high=scheduler.submit("high",800,lambda:order.append("high"))
        gate.set(); first.result(2); high.result(2); low.result(2)
        self.assertEqual(order,["block","high","low"])

    def test_league_editorial_series_registry(self):
        rows={x["id"]:x for x in editorial_catalog()}
        self.assertEqual(rows["MLB_TOP_PLAYS_DAILY"]["cadence"],"daily")
        self.assertEqual(rows["NBA_TOP_PLAYS_NIGHTLY"]["cadence"],"nightly")
        self.assertEqual(rows["NFL_TOP_PLAYS_WEEKLY"]["cadence"],"weekly")
        self.assertTrue(all(x["scope"]=="league" for x in rows.values()))


    def test_game_center_repository_persists_across_process_restart(self):
        sample={"competitionId":"MLB","event":{"status":"Final","competitionId":"MLB"},"scoreboard":{"status":"Final","away":{"team":{"name":"Away Club","abbreviation":"AWY"},"score":1},"home":{"team":{"name":"Home Club","abbreviation":"HME"},"score":2}},"live":False,"eventId":"824155"}
        with tempfile.TemporaryDirectory() as td, patch.object(server,'fetch_mlb_game_center',return_value=sample) as fetcher:
            db=Path(td)/'game-centers.sqlite3'
            with patch.object(server,'GAME_CENTER_REPOSITORY',GameCenterRepository(db)):
                data,state=server._game_center_get('MLB','824155')
                self.assertEqual(data['eventId'],'824155'); self.assertEqual(state,'MISS')
                self.assertEqual(fetcher.call_count,1)
            with patch.object(server,'GAME_CENTER_REPOSITORY',GameCenterRepository(db)):
                data,state=server._game_center_get('MLB','824155')
                self.assertEqual(state,'REPO-HIT')
                self.assertEqual(fetcher.call_count,1)

    def test_game_center_async_open_never_blocks_on_provider_miss(self):
        class FakeFuture: pass
        calls=[]
        with tempfile.TemporaryDirectory() as td, patch.object(server,'GAME_CENTER_REPOSITORY',GameCenterRepository(Path(td)/'gc.sqlite3')), patch.object(server,'schedule_game_center_prepare',side_effect=lambda c,e,p,hints=None: calls.append((c,e,p,hints)) or FakeFuture()), patch.object(server,'fetch_mlb_game_center') as fetcher:
            data,state,pending,resolved=server._game_center_open('MLB','824155')
            self.assertIsNone(data); self.assertEqual(state,'PENDING'); self.assertTrue(pending); self.assertEqual(resolved,'824155')
            self.assertEqual(fetcher.call_count,0)
            self.assertEqual(calls[0][0:2],('MLB','824155'))
            self.assertEqual(calls[0][2],server.MEDIA_PRIORITY['TOUCH_INTENT'])

    def test_espn_nfl_game_center_normalizes_team_player_and_play_data(self):
        payload={
          "header":{"competitions":[{"date":"2026-08-20T20:00:00Z","status":{"type":{"state":"post","completed":True,"shortDetail":"Final"},"period":4},"venue":{"fullName":"Test Stadium"},"competitors":[{"homeAway":"away","score":"17","team":{"id":"1","displayName":"Away Club","abbreviation":"AWY"}},{"homeAway":"home","score":"24","team":{"id":"2","displayName":"Home Club","abbreviation":"HME"}}]}]},
          "boxscore":{"teams":[{"team":{"id":"1","displayName":"Away Club","abbreviation":"AWY"},"statistics":[{"name":"totalYards","label":"Total Yards","displayValue":"311"}]},{"team":{"id":"2","displayName":"Home Club","abbreviation":"HME"},"statistics":[{"name":"totalYards","label":"Total Yards","displayValue":"402"}]}],"players":[{"team":{"id":"2","displayName":"Home Club"},"statistics":[{"name":"passing","labels":["C/ATT","YDS","TD"],"athletes":[{"athlete":{"displayName":"QB One"},"stats":["20/30","255","2"]}]}]}]},
          "plays":[{"id":"p1","text":"Touchdown pass","period":{"number":2},"clock":{"displayValue":"4:12"},"scoringPlay":True,"awayScore":7,"homeScore":14}]
        }
        data=normalize_espn_summary(payload,'NFL','401')
        self.assertEqual(data['scoreboard']['home']['score'],'24')
        self.assertEqual(data['teamStats'][0]['home'],'402')
        self.assertEqual(data['playerStatSections'][0]['rows'][0][0],'QB One')
        self.assertEqual(data['scoringPlays'][0]['description'],'Touchdown pass')

    def test_espn_soccer_game_center_normalizes_stats_and_key_events(self):
        payload={
          "header":{"competitions":[{"date":"2026-08-20T01:00:00Z","status":{"type":{"state":"post","completed":True,"shortDetail":"Final"}},"competitors":[{"homeAway":"away","score":"1","team":{"id":"10","displayName":"San Jose Earthquakes","abbreviation":"SJ"}},{"homeAway":"home","score":"2","team":{"id":"11","displayName":"LA Galaxy","abbreviation":"LA"}}]}]},
          "boxscore":{"teams":[{"team":{"id":"10","displayName":"San Jose Earthquakes"},"statistics":[{"name":"possessionPct","label":"Possession","displayValue":"48%"}]},{"team":{"id":"11","displayName":"LA Galaxy"},"statistics":[{"name":"possessionPct","label":"Possession","displayValue":"52%"}]}]},
          "keyEvents":[{"id":"g1","text":"Goal - LA Galaxy","type":{"text":"Goal"},"scoringPlay":True}]
        }
        data=normalize_espn_summary(payload,'MLS','999')
        self.assertEqual(data['teamStats'][0]['away'],'48%')
        self.assertEqual(data['teamStats'][0]['home'],'52%')
        self.assertTrue(data['scoringPlays'][0]['isScoring'])

    def test_espn_game_center_fetch_uses_summary_endpoint(self):
        calls=[]
        payload={"header":{"competitions":[{"status":{"type":{"state":"pre","shortDetail":"Scheduled"}},"competitors":[]}]}}
        def fake_fetch(url,timeout=0): calls.append(url); return payload
        fetch_espn_game_center('NFL','401',fake_fetch,'https://site.api.espn.com/apis/site/v2/sports')
        self.assertIn('/football/nfl/summary?event=401',calls[0])

    def test_nba_and_nhl_share_the_generic_espn_game_center_adapter(self):
        calls=[]
        payload={"header":{"competitions":[{"status":{"type":{"state":"pre","shortDetail":"Scheduled"}},"competitors":[]}]}}
        def fake_fetch(url,timeout=0): calls.append(url); return payload
        nba=fetch_espn_game_center('NBA','nba-1',fake_fetch,'https://site.api.espn.com/apis/site/v2/sports')
        nhl=fetch_espn_game_center('NHL','nhl-1',fake_fetch,'https://site.api.espn.com/apis/site/v2/sports')
        self.assertIn('/basketball/nba/summary?event=nba-1',calls[0])
        self.assertIn('/hockey/nhl/summary?event=nhl-1',calls[1])
        self.assertEqual(nba['event']['sportId'],'basketball')
        self.assertEqual(nhl['event']['sportId'],'ice-hockey')

    def test_coverage_pass_inventories_today_and_yesterday_for_all_supported_adapters(self):
        calls=[]
        def fake_sched(date): calls.append(('schedule',date)); return ([{'gamePk':1}],1,0)
        def fake_mlb(games,date,today=False): calls.append(('MLB',date,today)); return {'queued':len(games)}
        def fake_espn(comp,date,today=False): calls.append((comp,date,today)); return {'queued':1}
        with patch.object(server,'_schedule_game_counts',side_effect=fake_sched), \
             patch.object(server,'prewarm_game_centers_for_games',side_effect=fake_mlb), \
             patch.object(server,'prewarm_espn_game_centers',side_effect=fake_espn), \
             patch.object(server,'_prewarm_highlightly_call',return_value={'data':[]}):
            result=server._game_center_coverage_pass('2026-08-21','2026-08-20')
        self.assertIn(('MLB','2026-08-21',True),calls)
        self.assertIn(('MLB','2026-08-20',False),calls)
        for comp in ('NFL','NBA','NHL','MLS','EPL'):
            self.assertIn((comp,'2026-08-21',True),calls)
            self.assertIn((comp,'2026-08-20',False),calls)
        self.assertEqual(result['MLB:2026-08-21:official']['queued'],1)
        self.assertEqual(result['MLB:2026-08-20:official']['queued'],1)
        self.assertIn('MLB:2026-08-21:highlightly',result)
        self.assertIn('MLB:2026-08-20:highlightly',result)

    def test_highlightly_game_center_normalizes_same_score_provider_id(self):
        from sbb.game_center import normalize_highlightly_game_center
        match={'id':991,'date':'2026-08-21T00:00:00Z','awayTeam':{'id':1,'name':'Away Club','abbreviation':'AWY'},'homeTeam':{'id':2,'name':'Home Club','abbreviation':'HME'},'state':{'report':'Finished','score':{'current':'5 - 2'}},'plays':[{'description':'Home Club scores','isScoring':True}]}
        stats=[{'team':match['awayTeam'],'statistics':[{'name':'Total Hits','value':5}]},{'team':match['homeTeam'],'statistics':[{'name':'Total Hits','value':9}]}]
        box=[{'team':match['awayTeam'],'boxScores':[{'player':{'name':'A Player'},'statistics':[{'name':'Total At-Bats','group':'Batting','value':4}]}]},{'team':match['homeTeam'],'boxScores':[{'player':{'name':'H Player'},'statistics':[{'name':'Total At-Bats','group':'Batting','value':3}]}]}]
        gc=normalize_highlightly_game_center(match,'MLB','991',stats,box)
        self.assertEqual(gc['eventId'],'991')
        self.assertEqual(gc['scoreboard']['away']['team']['name'],'Away Club')
        self.assertTrue(gc['teamStats'])
        self.assertTrue(gc['playerStatSections'])
        self.assertTrue(gc['scoringPlays'])

    def test_all_known_mlb_game_centers_are_queued_for_server_prewarm(self):
        games=[
            {"gamePk":824155,"status":{"abstractGameState":"Live"}},
            {"gamePk":824156,"status":{"abstractGameState":"Final"}},
            {"gamePk":824157,"status":{"abstractGameState":"Preview"}},
        ]
        calls=[]
        class FakeScheduler:
            def submit(self,key,priority,fn,*args,**kwargs): calls.append((key,priority,args)); return object()
        with patch.object(server,'GAME_CENTER_WORK_SCHEDULER',FakeScheduler()):
            result=server.prewarm_game_centers_for_games(games,'2026-08-20',True)
        self.assertEqual(result['queued'],3)
        self.assertEqual({x[0] for x in calls},{'game-center:MLB:2026-08-20::::824155','game-center:MLB:2026-08-20::::824156','game-center:MLB:2026-08-20::::824157'})
        self.assertGreater(calls[0][1],calls[2][1])

    def test_mlb_provider_id_resolves_to_gamepk_by_team_and_date(self):
        date="2026-08-20"
        games=[{"gamePk":999001,"gameDate":"2026-08-20T23:10:00Z","teams":{"away":{"team":{"name":"San Diego Padres","abbreviation":"SD"}},"home":{"team":{"name":"New York Mets","abbreviation":"NYM"}}}}]
        with tempfile.TemporaryDirectory() as td, patch.object(server,'GAME_CENTER_REPOSITORY',GameCenterRepository(Path(td)/'gc.sqlite3')):
            server._index_game_center_events('MLB',games,date)
            resolved=server._resolve_game_center_event_id("MLB","123456789",{"date":date,"away":"SD","home":"NYM"},allow_fetch=False)
            self.assertEqual(resolved,"999001")
        with server.GAME_CENTER_EVENT_INDEX_LOCK:
            server.GAME_CENTER_EVENT_INDEX.pop(('MLB',date),None)


    def test_wrong_provider_id_cannot_override_team_fingerprint(self):
        date='2026-08-20'
        games=[
          {"gamePk":910001,"gameDate":"2026-08-20T18:00:00Z","teams":{"away":{"team":{"name":"Chicago White Sox","abbreviation":"CHW"}},"home":{"team":{"name":"Chicago Cubs","abbreviation":"CHC"}}}},
          {"gamePk":910002,"gameDate":"2026-08-20T23:00:00Z","teams":{"away":{"team":{"name":"Toronto Blue Jays","abbreviation":"TOR"}},"home":{"team":{"name":"Tampa Bay Rays","abbreviation":"TB"}}}},
        ]
        rows=server._index_game_center_events('MLB',games,date)
        chosen=server._gc_pick_index_match(rows,'910001',{'date':date,'away':'TOR','home':'TB'})
        self.assertEqual(chosen['providerEventId'],'910002')
        with server.GAME_CENTER_EVENT_INDEX_LOCK:
            server.GAME_CENTER_EVENT_INDEX.pop(('MLB',date),None)

    def test_poisoned_alias_is_revalidated_against_team_fingerprint(self):
        date='2026-08-20'
        games=[
          {"gamePk":920001,"gameDate":"2026-08-20T18:00:00Z","teams":{"away":{"team":{"name":"Chicago White Sox","abbreviation":"CHW"}},"home":{"team":{"name":"Chicago Cubs","abbreviation":"CHC"}}}},
          {"gamePk":920002,"gameDate":"2026-08-20T23:00:00Z","teams":{"away":{"team":{"name":"Toronto Blue Jays","abbreviation":"TOR"}},"home":{"team":{"name":"Tampa Bay Rays","abbreviation":"TB"}}}},
        ]
        def payload(pk,away,home):
            return {"competitionId":"MLB","eventId":str(pk),"event":{"status":"Final","competitionId":"MLB"},"scoreboard":{"status":"Final","away":{"team":{"name":away,"abbreviation":away},"score":1},"home":{"team":{"name":home,"abbreviation":home},"score":2}},"live":False}
        with tempfile.TemporaryDirectory() as td, patch.object(server,'GAME_CENTER_REPOSITORY',GameCenterRepository(Path(td)/'gc.sqlite3')):
            server._index_game_center_events('MLB',games,date)
            server.GAME_CENTER_REPOSITORY.put_alias('MLB','score-alias','920001',date,'CHW','CHC')
            server._game_center_store('MLB','920001',payload('920001','CHW','CHC'))
            resolved=server._resolve_game_center_event_id('MLB','score-alias',{'date':date,'away':'TOR','home':'TB'},allow_fetch=False)
            self.assertEqual(resolved,'920002')
        with server.GAME_CENTER_EVENT_INDEX_LOCK:
            server.GAME_CENTER_EVENT_INDEX.pop(('MLB',date),None)

    def test_unknown_placeholder_game_center_is_invalid(self):
        bad={"competitionId":"MLB","scoreboard":{"away":{"team":{"name":"Unknown"}},"home":{"team":{"name":"Unknown"}}}}
        self.assertFalse(server._game_center_payload_valid(bad,'MLB'))

    def test_sequential_score_aliases_resolve_to_distinct_mlb_game_centers(self):
        date='2026-08-20'
        games=[
          {"gamePk":900001,"gameDate":"2026-08-20T18:00:00Z","teams":{"away":{"team":{"name":"Chicago White Sox","abbreviation":"CHW"}},"home":{"team":{"name":"Chicago Cubs","abbreviation":"CHC"}}}},
          {"gamePk":900002,"gameDate":"2026-08-20T23:00:00Z","teams":{"away":{"team":{"name":"Toronto Blue Jays","abbreviation":"TOR"}},"home":{"team":{"name":"Tampa Bay Rays","abbreviation":"TB"}}}},
        ]
        def payload(pk,away,home):
            team_stats=[{"label":label,"away":i+1,"home":i+2} for i,label in enumerate(("Hits","Walks","Strikeouts","Errors"))]
            player_rows=[[f"Player {i}",i%3] for i in range(8)]
            timeline=[{"id":f"p{i}","description":f"Play {i}"} for i in range(5)]
            return {"competitionId":"MLB","eventId":str(pk),"event":{"status":"Final","competitionId":"MLB"},"scoreboard":{"status":"Final","away":{"team":{"name":away,"abbreviation":({"Chicago White Sox":"CHW","Toronto Blue Jays":"TOR"}.get(away,""))},"score":1},"home":{"team":{"name":home,"abbreviation":({"Chicago Cubs":"CHC","Tampa Bay Rays":"TB"}.get(home,""))},"score":2},"innings":[{"num":1,"away":0,"home":0},{"num":2,"away":1,"home":0},{"num":3,"away":0,"home":2}]},"teamStats":team_stats,"playerStatSections":[{"title":"Batting","columns":["Player","H"],"rows":player_rows}],"timeline":timeline,"scoringPlays":[{"id":"p2","description":"Run scores"}],"live":False}
        with tempfile.TemporaryDirectory() as td, patch.object(server,'GAME_CENTER_REPOSITORY',GameCenterRepository(Path(td)/'gc.sqlite3')):
            server._index_game_center_events('MLB',games,date)
            with patch.object(server,'fetch_mlb_game_center',side_effect=lambda pk,*a: payload(pk,'Chicago White Sox','Chicago Cubs') if str(pk)=='900001' else payload(pk,'Toronto Blue Jays','Tampa Bay Rays')):
                server._game_center_prepare_job('MLB','hl-111',{'date':date,'away':'CHW','home':'CHC'})
                server._game_center_prepare_job('MLB','hl-222',{'date':date,'away':'TOR','home':'TB'})
            first=server._game_center_open('MLB','hl-111',hints={'date':date,'away':'CHW','home':'CHC'})
            second=server._game_center_open('MLB','hl-222',hints={'date':date,'away':'TOR','home':'TB'})
            self.assertFalse(first[2]); self.assertEqual(first[3],'900001'); self.assertEqual(first[0]['eventId'],'900001')
            self.assertFalse(second[2]); self.assertEqual(second[3],'900002'); self.assertEqual(second[0]['eventId'],'900002')

    def test_espn_score_alias_resolves_by_team_pair(self):
        date='2026-08-20'; rows=[{"id":"401999001","date":"2026-08-20T20:00:00Z","awayTeam":{"name":"Las Vegas Raiders","abbreviation":"LV"},"homeTeam":{"name":"Houston Texans","abbreviation":"HOU"}}]
        with tempfile.TemporaryDirectory() as td, patch.object(server,'GAME_CENTER_REPOSITORY',GameCenterRepository(Path(td)/'gc.sqlite3')):
            server._index_game_center_events('NFL',rows,date)
            self.assertEqual(server._resolve_game_center_event_id('NFL','highlightly-77',{'date':date,'away':'LV','home':'HOU'},False),'401999001')

    def test_invalid_unknown_game_center_cache_is_purged(self):
        bad={"competitionId":"MLB","eventId":"123","event":{"status":"Final"},"scoreboard":{"status":"Final","away":{"team":{}},"home":{"team":{}}},"live":False}
        with tempfile.TemporaryDirectory() as td:
            repo=GameCenterRepository(Path(td)/'gc.sqlite3'); repo.put('MLB','123',bad,time.time()+100)
            with patch.object(server,'GAME_CENTER_REPOSITORY',repo):
                self.assertIsNone(server._game_center_cached_record('MLB','123'))
                self.assertIsNone(repo.get('MLB','123'))

    def test_highlightly_mlb_box_score_direct_team_shape_is_parsed(self):
        match={
            "id":77123,"date":"2026-08-20T18:00:00Z","status":"Final",
            "awayTeam":{"id":1,"name":"Atlanta Braves","abbreviation":"ATL"},
            "homeTeam":{"id":2,"name":"Chicago White Sox","abbreviation":"CHW"},
            "state":{"report":"Final","score":{"awayTeam":[0,1,0,0,0,1,0,0,0],"homeTeam":[0,0,0,0,0,0,0,0,0]}}
        }
        stats=[
            {"team":{"id":1,"name":"Atlanta Braves","statistics":[{"name":"Hits","value":8},{"name":"Walks","value":3},{"name":"Strikeouts","value":7},{"name":"Errors","value":0}]}},
            {"team":{"id":2,"name":"Chicago White Sox","statistics":[{"name":"Hits","value":5},{"name":"Walks","value":2},{"name":"Strikeouts","value":9},{"name":"Errors","value":1}]}}
        ]
        # Highlightly MLB box-score rows identify the TEAM at the row root rather
        # than under row.team. Home/away order must not matter.
        box=[
            {"id":2,"name":"Chicago White Sox","boxScores":[
                {"name":"Home A","statistics":[{"group":"Batting","name":"At Bats","value":4},{"group":"Batting","name":"Hits","value":1}]},
                {"name":"Home B","statistics":[{"group":"Batting","name":"At Bats","value":4},{"group":"Batting","name":"Hits","value":1}]},
                {"name":"Home C","statistics":[{"group":"Batting","name":"At Bats","value":4},{"group":"Batting","name":"Hits","value":1}]},
                {"name":"Home D","statistics":[{"group":"Batting","name":"At Bats","value":4},{"group":"Batting","name":"Hits","value":1}]}
            ]},
            {"id":1,"name":"Atlanta Braves","boxScores":[
                {"name":"Away A","statistics":[{"group":"Batting","name":"At Bats","value":4},{"group":"Batting","name":"Hits","value":2}]},
                {"name":"Away B","statistics":[{"group":"Batting","name":"At Bats","value":4},{"group":"Batting","name":"Hits","value":1}]},
                {"name":"Away C","statistics":[{"group":"Batting","name":"At Bats","value":4},{"group":"Batting","name":"Hits","value":1}]},
                {"name":"Away D","statistics":[{"group":"Batting","name":"At Bats","value":4},{"group":"Batting","name":"Hits","value":1}]}
            ]}
        ]
        data=normalize_highlightly_game_center(match,'MLB','77123',stats,box)
        titles=[x['title'] for x in data['playerStatSections']]
        self.assertTrue(any('Atlanta Braves' in x for x in titles))
        self.assertTrue(any('Chicago White Sox' in x for x in titles))
        self.assertEqual(len(data['scoreboard']['innings']),9)
        self.assertGreaterEqual(len(data['teamStats']),4)
        self.assertGreaterEqual(data['coverage']['playerRows'],8)

    def test_final_mlb_requires_expected_game_center_categories(self):
        thin={
            "competitionId":"MLB","event":{"status":"Final","competitionId":"MLB"},
            "scoreboard":{"status":"Final","away":{"team":{"name":"ATL"},"score":2},"home":{"team":{"name":"CHW"},"score":0},
                          "innings":[{"num":1},{"num":2},{"num":3}]},
            "teamStats":[{"label":"Runs","away":2,"home":0},{"label":"Hits","away":8,"home":5},{"label":"Errors","away":0,"home":1},{"label":"Walks","away":3,"home":2}],
            "playerStatSections":[],"timeline":[],"scoringPlays":[]
        }
        cov=game_center_coverage(thin)
        self.assertFalse(cov['complete'])
        self.assertIn('playerStats',cov['missing'])
        self.assertIn('playByPlay',cov['missing'])
        self.assertIn('scoringPlays',cov['missing'])

    def test_merge_game_centers_recalculates_completion(self):
        thin={"competitionId":"MLB","event":{"status":"Final","competitionId":"MLB"},"scoreboard":{"status":"Final","away":{"team":{"name":"ATL"},"score":2},"home":{"team":{"name":"CHW"},"score":0}},"teamStats":[],"playerStatSections":[],"timeline":[],"scoringPlays":[]}
        rich={"competitionId":"MLB","event":{"status":"Final","competitionId":"MLB"},"scoreboard":{"status":"Final","away":{"team":{"name":"ATL"},"score":2},"home":{"team":{"name":"CHW"},"score":0},"innings":[{"num":1},{"num":2},{"num":3}]},"teamStats":[{"label":"Runs","away":2,"home":0},{"label":"Hits","away":8,"home":5},{"label":"Errors","away":0,"home":1},{"label":"Walks","away":3,"home":2}],"playerStatSections":[{"title":"ATL Batting","columns":["Player"],"rows":[[f'A{i}'] for i in range(4)]},{"title":"CHW Batting","columns":["Player"],"rows":[[f'H{i}'] for i in range(4)]}],"timeline":[{"id":str(i),"description":f'Play {i}'} for i in range(5)],"scoringPlays":[{"id":"s","description":"Run scores"}]}
        merged=merge_game_centers(thin,rich)
        self.assertTrue(merged['coverage']['complete'])
        self.assertFalse(merged['partial'])


    def test_partial_highlightly_final_is_enriched_with_official_provider(self):
        thin={"competitionId":"MLB","eventId":"77123","event":{"status":"Final","competitionId":"MLB"},"scoreboard":{"status":"Final","away":{"team":{"name":"Atlanta Braves","abbreviation":"ATL"},"score":2},"home":{"team":{"name":"Chicago White Sox","abbreviation":"CHW"},"score":0}},"teamStats":[],"playerStatSections":[],"timeline":[],"scoringPlays":[],"source":"Highlightly match detail","live":False}
        rich={"competitionId":"MLB","eventId":"930001","event":{"status":"Final","competitionId":"MLB"},"scoreboard":{"status":"Final","away":{"team":{"name":"Atlanta Braves","abbreviation":"ATL"},"score":2},"home":{"team":{"name":"Chicago White Sox","abbreviation":"CHW"},"score":0},"innings":[{"num":1},{"num":2},{"num":3}]},"teamStats":[{"label":"Runs","away":2,"home":0},{"label":"Hits","away":8,"home":5},{"label":"Errors","away":0,"home":1},{"label":"Walks","away":3,"home":2}],"playerStatSections":[{"title":"ATL Batting","columns":["Player"],"rows":[[f'A{i}'] for i in range(4)]},{"title":"CHW Batting","columns":["Player"],"rows":[[f'H{i}'] for i in range(4)]}],"timeline":[{"id":str(i),"description":f'Play {i}'} for i in range(5)],"scoringPlays":[{"id":"score","description":"Run scores"}],"source":"MLB Stats API live feed","live":False}
        hints={"date":"2026-08-20","away":"ATL","home":"CHW","provider":"highlightly"}
        with patch.object(server,'_highlightly_game_center',return_value=thin), \
             patch.object(server,'_resolve_game_center_event_id',return_value='930001'), \
             patch.object(server,'_game_center_refresh',return_value=rich), \
             patch.object(server,'_game_center_cached_record',return_value=None), \
             patch.object(server,'_game_center_store') as store, \
             patch.object(server.GAME_CENTER_REPOSITORY,'put_alias'):
            server._game_center_prepare_job('MLB','77123',hints)
        stored=store.call_args.args[2]
        self.assertTrue(game_center_coverage(stored)['complete'])
        self.assertGreaterEqual(len(stored.get('scoringPlays') or []),1)

    def test_highlightly_coverage_prejoins_score_alias_to_official_event(self):
        date='2026-08-20'
        official=[{"gamePk":930001,"gameDate":"2026-08-20T18:00:00Z","teams":{"away":{"team":{"name":"Atlanta Braves","abbreviation":"ATL"}},"home":{"team":{"name":"Chicago White Sox","abbreviation":"CHW"}}}}]
        highlightly=[{"id":77123,"date":"2026-08-20T18:00:00Z","awayTeam":{"name":"Atlanta Braves","abbreviation":"ATL"},"homeTeam":{"name":"Chicago White Sox","abbreviation":"CHW"},"state":{"report":"Final"}}]
        with server.GAME_CENTER_EVENT_INDEX_LOCK:
            server.GAME_CENTER_EVENT_INDEX.pop(('MLB',date),None)
        server._index_game_center_events('MLB',official,date,'official')
        with patch.object(server.GAME_CENTER_REPOSITORY,'put_alias') as alias, patch.object(server,'schedule_game_center_prepare',return_value='job') as schedule:
            result=server.prewarm_game_centers_for_events('MLB',highlightly,date,False,'highlightly')
        alias.assert_called()
        self.assertEqual(alias.call_args.args[1],'77123')
        self.assertEqual(alias.call_args.args[2],'930001')
        self.assertEqual(schedule.call_args.args[1],'930001')
        self.assertEqual(result['queued'],1)
        with server.GAME_CENTER_EVENT_INDEX_LOCK:
            server.GAME_CENTER_EVENT_INDEX.pop(('MLB',date),None)


    def test_game_center_provider_indexes_preserve_official_and_highlightly(self):
        date='2026-08-20'
        official=[{"gamePk":930001,"gameDate":"2026-08-20T18:00:00Z","teams":{"away":{"team":{"name":"Atlanta Braves","abbreviation":"ATL"}},"home":{"team":{"name":"Chicago White Sox","abbreviation":"CHW"}}}}]
        highlightly=[{"id":77123,"date":"2026-08-20T18:00:00Z","awayTeam":{"name":"Atlanta Braves","abbreviation":"ATL"},"homeTeam":{"name":"Chicago White Sox","abbreviation":"CHW"}}]
        with server.GAME_CENTER_EVENT_INDEX_LOCK:
            server.GAME_CENTER_EVENT_INDEX.pop(('MLB',date),None)
        server._index_game_center_events('MLB',official,date,'official')
        server._index_game_center_events('MLB',highlightly,date,'highlightly')
        with server.GAME_CENTER_EVENT_INDEX_LOCK:
            rows=list(server.GAME_CENTER_EVENT_INDEX.get(('MLB',date)) or [])
        self.assertEqual(len(rows),2)
        self.assertEqual({r['provider'] for r in rows},{'official','highlightly'})
        resolved=server._resolve_game_center_event_id('MLB','77123',{'date':date,'away':'ATL','home':'CHW','provider':'highlightly'},False)
        self.assertEqual(resolved,'930001')
        with server.GAME_CENTER_EVENT_INDEX_LOCK:
            server.GAME_CENTER_EVENT_INDEX.pop(('MLB',date),None)

    def test_partial_final_game_center_is_not_long_term_cached(self):
        partial={"competitionId":"MLB","eventId":"1","event":{"status":"Final","competitionId":"MLB"},"scoreboard":{"status":"Final","away":{"team":{"name":"Away","abbreviation":"AWY"},"score":2},"home":{"team":{"name":"Home","abbreviation":"HME"},"score":3}},"teamStats":[],"playerStatSections":[],"timeline":[],"scoringPlays":[],"live":False}
        self.assertTrue(server._game_center_needs_enrichment(partial,'MLB'))
        self.assertEqual(server._game_center_ttl(partial),90)

    def test_game_center_merge_prefers_richer_fallback_sections(self):
        primary={"competitionId":"MLB","eventId":"hl-1","event":{"status":"Final","competitionId":"MLB"},"scoreboard":{"status":"Final","away":{"team":{"name":"Away","abbreviation":"AWY"},"score":2},"home":{"team":{"name":"Home","abbreviation":"HME"},"score":3}},"teamStats":[],"playerStatSections":[],"timeline":[],"scoringPlays":[],"source":"Highlightly match detail","live":False}
        secondary={"competitionId":"MLB","eventId":"930001","event":{"status":"Final","competitionId":"MLB"},"scoreboard":{"status":"Final","away":{"team":{"name":"Away","abbreviation":"AWY"},"score":2},"home":{"team":{"name":"Home","abbreviation":"HME"},"score":3},"innings":[{"num":1,"away":0,"home":1},{"num":2,"away":1,"home":0},{"num":3,"away":1,"home":2}]},"teamStats":[{"label":"Hits","away":5,"home":8},{"label":"Runs","away":2,"home":3},{"label":"Errors","away":0,"home":0},{"label":"Walks","away":3,"home":4}],"playerStatSections":[{"title":"Away Batting","columns":["Player","H"],"rows":[["A",1],["B",1],["C",1],["D",1]]},{"title":"Home Batting","columns":["Player","H"],"rows":[["E",1],["F",1],["G",1],["H",1]]}],"timeline":[{"id":str(i),"description":f"Play {i}"} for i in range(6)],"scoringPlays":[{"id":"score1","description":"A scores"}],"source":"MLB Stats API live feed","live":False}
        merged=server._game_center_merge(primary,secondary)
        self.assertEqual(merged['teamStats'][0]['label'],'Hits')
        self.assertEqual(len(merged['playerStatSections']),2)
        self.assertEqual(len(merged['timeline']),6)
        self.assertEqual(merged['quality']['level'],'rich')
        self.assertFalse(merged['partial'])

    def test_highlightly_only_index_fetches_official_inventory_before_resolution(self):
        date='2026-08-20'
        highlightly=[{"id":77222,"date":"2026-08-20T18:00:00Z","awayTeam":{"name":"Atlanta Braves","abbreviation":"ATL"},"homeTeam":{"name":"Chicago White Sox","abbreviation":"CHW"}}]
        official=[{"gamePk":940001,"gameDate":"2026-08-20T18:00:00Z","teams":{"away":{"team":{"name":"Atlanta Braves","abbreviation":"ATL"}},"home":{"team":{"name":"Chicago White Sox","abbreviation":"CHW"}}}}]
        with server.GAME_CENTER_EVENT_INDEX_LOCK:
            server.GAME_CENTER_EVENT_INDEX.pop(('MLB',date),None)
        server._index_game_center_events('MLB',highlightly,date,'highlightly')
        with patch.object(server,'_schedule_game_counts',return_value=(official,1,0)):
            rows=server._game_center_index_rows('MLB',date,allow_fetch=True)
        self.assertEqual({r['provider'] for r in rows},{'official','highlightly'})
        chosen=server._gc_pick_index_match(rows,'77222',{'date':date,'away':'ATL','home':'CHW'})
        self.assertEqual(chosen['providerEventId'],'940001')
        with server.GAME_CENTER_EVENT_INDEX_LOCK:
            server.GAME_CENTER_EVENT_INDEX.pop(('MLB',date),None)


    def test_youtube_region_restrictions_are_part_of_playable_truth(self):
        self.assertFalse(server._youtube_video_available_in_us({
            'status': {'embeddable': True, 'privacyStatus': 'public'},
            'contentDetails': {'regionRestriction': {'blocked': ['US','CA']}}
        }))
        self.assertFalse(server._youtube_video_available_in_us({
            'status': {'embeddable': True, 'privacyStatus': 'public'},
            'contentDetails': {'regionRestriction': {'allowed': ['GB','CA']}}
        }))
        self.assertTrue(server._youtube_video_available_in_us({
            'status': {'embeddable': True, 'privacyStatus': 'public'},
            'contentDetails': {'regionRestriction': {'allowed': ['US','CA']}}
        }))
        self.assertTrue(server._youtube_video_available_in_us({
            'status': {'embeddable': True, 'privacyStatus': 'public'},
            'contentDetails': {}
        }))


    def test_youtube_web_search_parser_extracts_video_renderer_without_data_api(self):
        payload='<html><script>{"videoRenderer":{"videoId":"P55rMeZkNwQ","title":{"runs":[{"text":"SPURS at THUNDER | FULL GAME HIGHLIGHTS | December 25, 2025"}]},"ownerText":{"runs":[{"text":"NBA"}]},"lengthText":{"simpleText":"9:44"},"thumbnail":{"thumbnails":[{"url":"https://img.test/a.jpg"}]}}}</script></html>'
        class Resp:
            status=200
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,*args): return payload.encode()
        with patch.object(server,'urlopen',return_value=Resp()):
            rows=server._youtube_html_video_renderers('Spurs Thunder NBA highlights',max_results=5)
        self.assertEqual(rows[0]['videoId'],'P55rMeZkNwQ')
        self.assertEqual(rows[0]['channelTitle'],'NBA')
        self.assertEqual(rows[0]['durationSeconds'],584)

    def test_historical_youtube_web_oembed_is_metadata_only_until_positive_validation(self):
        rows=[{'videoId':'P55rMeZkNwQ','title':'SPURS at THUNDER | FULL GAME HIGHLIGHTS | December 25, 2025','channelTitle':'NBA','durationSeconds':584,'description':'','thumbnail':'','publishedText':''}]
        with patch.object(server,'_youtube_html_video_renderers',return_value=rows), \
             patch.object(server,'read_youtube_key',return_value=None), \
             patch.object(server,'_youtube_oembed_probe',return_value={'author_name':'NBA','title':rows[0]['title']}):
            out=server._historical_youtube_web_results('NBA','2025-12-25','San Antonio Spurs','Oklahoma City Thunder')
        self.assertTrue(out)
        self.assertFalse(out[0]['verifiedPlayable'])
        self.assertFalse(out[0]['embedValidated'])
        self.assertTrue(out[0]['externalOnly'])
        self.assertEqual(out[0]['validationState'],'CANDIDATE')
        self.assertEqual(out[0]['embedValidation'],'oembed-metadata-only')
        self.assertEqual(out[0]['provider'],'YOUTUBE')

    def test_historical_youtube_uses_one_unit_video_list_for_embed_truth_when_key_exists(self):
        rows=[{'videoId':'P55rMeZkNwQ','title':'SPURS at THUNDER | FULL GAME HIGHLIGHTS | December 25, 2025','channelTitle':'NBA','durationSeconds':584,'description':'','thumbnail':'','publishedText':''}]
        detail={'id':'P55rMeZkNwQ','snippet':{'title':rows[0]['title'],'channelTitle':'NBA'},'contentDetails':{'duration':'PT9M44S'},'status':{'embeddable':True,'privacyStatus':'public'}}
        calls=[]
        def fake_api(url,timeout=10):
            calls.append(url)
            self.assertIn('/videos?',url)
            self.assertNotIn('/search?',url)
            return {'items':[detail]}
        with patch.object(server,'_youtube_html_video_renderers',return_value=rows), \
             patch.object(server,'read_youtube_key',return_value='fake-key'), \
             patch.object(server,'youtube_fetch_json',side_effect=fake_api), \
             patch.object(server,'_youtube_oembed_probe',side_effect=AssertionError('videos.list validation should be authoritative when available')):
            out=server._historical_youtube_web_results('NBA','2025-12-25','San Antonio Spurs','Oklahoma City Thunder')
        self.assertEqual(len(calls),1)
        self.assertTrue(out[0]['verifiedPlayable'])
        self.assertEqual(out[0]['embedValidation'],'videos.list')
        self.assertEqual(out[0]['durationSeconds'],584)


    def test_youtube_search_cooldown_does_not_disable_history_index_or_validation(self):
        gateway=YouTubeGateway()
        body=io.BytesIO(b'{"error":{"errors":[{"reason":"quotaExceeded"}],"message":"search quota exhausted"}}')
        exc=HTTPError('https://www.googleapis.com/youtube/v3/search',429,'Too Many Requests',{},body)
        limited=gateway._mark_http_failure('search',exc)
        self.assertIsNotNone(limited)
        self.assertFalse(gateway.operation_available('search'))
        self.assertTrue(gateway.operation_available('activities'))
        self.assertTrue(gateway.operation_available('videos'))
        status=gateway.status()
        self.assertGreater(status['search']['cooldownSeconds'],0)
        self.assertEqual(status['activities']['cooldownSeconds'],0)
        self.assertEqual(status['videos']['cooldownSeconds'],0)

    def test_historical_score_inventory_is_cached_once_and_shared_with_media_discovery(self):
        row={'id':'evt-score','espnEventId':'evt-score','completed':True,'awayTeam':{'name':'Away'},'homeTeam':{'name':'Home'}}
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3')
            with patch.object(server,'HISTORY_REPOSITORY',repo), patch.object(server,'_espn_scoreboard',return_value=[row]) as espn:
                first=server._history_get_league_scores('2025-12-25','NBA','America/Chicago',-360)
                second=server._history_get_league_scores('2025-12-25','NBA','America/Chicago',-360)
        self.assertEqual(first[0],[row])
        self.assertFalse(first[2])
        self.assertTrue(second[2])
        self.assertEqual(second[1],'HISTORY_DB')
        self.assertEqual(espn.call_count,1)

    def test_official_uploads_playlist_finds_historical_green_without_search_list(self):
        calls=[]
        def fake_fetch(url,timeout=0):
            calls.append(url)
            if '/channels?' in url:
                return {'items':[{'contentDetails':{'relatedPlaylists':{'uploads':'UPLOADS1'}}}]}
            if '/playlistItems?' in url:
                return {'items':[{'contentDetails':{'videoId':'abcdefghijk'},'snippet':{'resourceId':{'videoId':'abcdefghijk'}}}]}
            if '/videos?' in url:
                return {'items':[{'id':'abcdefghijk','snippet':{'title':'Cleveland Cavaliers vs New York Knicks Full Game Highlights','description':'Christmas Day recap','channelTitle':'NBA','publishedAt':'2025-12-26T03:00:00Z','thumbnails':{}},'contentDetails':{'duration':'PT3M30S'},'status':{'embeddable':True,'privacyStatus':'public'}}]}
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as td, patch.object(server,'YOUTUBE_CACHE_DIR',Path(td)), patch.object(server,'read_youtube_key',return_value='key'), patch.object(server,'youtube_fetch_json',side_effect=fake_fetch):
            out=server._official_youtube_history_upload_results('NBA','2025-12-25','Cleveland Cavaliers','New York Knicks')
        self.assertTrue(any(x.get('recapTier')=='green' for x in out))
        self.assertTrue(any('/playlistItems?' in x for x in calls))
        self.assertFalse(any('/search?' in x for x in calls))

    def test_official_activity_catalog_finds_historical_video_without_search_list(self):
        activity={"items":[
            {"snippet":{"type":"upload"},"contentDetails":{"upload":{"videoId":"P55rMeZkNwQ"}}},
        ]}
        details={"items":[{
            "id":"P55rMeZkNwQ",
            "snippet":{"title":"SPURS at THUNDER | FULL GAME HIGHLIGHTS | December 25, 2025","description":"San Antonio Spurs and Oklahoma City Thunder","channelTitle":"NBA","publishedAt":"2025-12-25T23:00:00Z","thumbnails":{}},
            "contentDetails":{"duration":"PT9M44S"},"status":{"embeddable":True,"privacyStatus":"public"}
        }]}
        calls=[]
        def fake_fetch(url,timeout=0):
            calls.append(url)
            if '/activities?' in url: return activity
            if '/videos?' in url: return details
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as td, \
             patch.object(server,'read_youtube_key',return_value='yt-key'), \
             patch.object(server,'_official_youtube_activity_cache_path',return_value=Path(td)/'activity.json'), \
             patch.object(server,'youtube_fetch_json',side_effect=fake_fetch):
            out=server._official_youtube_history_activity_results('NBA','2025-12-25','San Antonio Spurs','Oklahoma City Thunder')
        self.assertTrue(out)
        self.assertEqual(out[0]['youtubeId'],'P55rMeZkNwQ')
        self.assertTrue(out[0]['verifiedPlayable'])
        self.assertTrue(any('/activities?' in x for x in calls))
        self.assertTrue(any('/videos?' in x for x in calls))
        self.assertFalse(any('/search?' in x for x in calls))

    def test_official_day_search_rescue_is_shared_by_all_games_on_date(self):
        search={"items":[
            {"id":{"videoId":"spurs123"}},
            {"id":{"videoId":"mavs123"}},
        ]}
        details={"items":[
            {"id":"spurs123","snippet":{"title":"SPURS at THUNDER | FULL GAME HIGHLIGHTS | December 25, 2025","description":"San Antonio Spurs and Oklahoma City Thunder","channelTitle":"NBA","publishedAt":"2025-12-25T20:00:00Z","thumbnails":{}},"contentDetails":{"duration":"PT9M44S"},"status":{"embeddable":True,"privacyStatus":"public"}},
            {"id":"mavs123","snippet":{"title":"MAVERICKS at WARRIORS | FULL GAME HIGHLIGHTS | December 25, 2025","description":"Dallas Mavericks and Golden State Warriors","channelTitle":"NBA","publishedAt":"2025-12-25T23:00:00Z","thumbnails":{}},"contentDetails":{"duration":"PT10M10S"},"status":{"embeddable":True,"privacyStatus":"public"}},
        ]}
        calls=[]
        def fake_fetch(url,timeout=0):
            calls.append(url)
            if '/search?' in url: return search
            if '/videos?' in url: return details
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as td, \
             patch.object(server,'read_youtube_key',return_value='yt-key'), \
             patch.object(server,'_history_youtube_budget_take',return_value={'remaining':50}), \
             patch.object(server,'_official_youtube_day_search_cache_path',return_value=Path(td)/'day.json'), \
             patch.object(server,'youtube_fetch_json',side_effect=fake_fetch):
            one=server._official_youtube_history_day_search_results('NBA','2025-12-25','San Antonio Spurs','Oklahoma City Thunder')
            two=server._official_youtube_history_day_search_results('NBA','2025-12-25','Dallas Mavericks','Golden State Warriors')
        self.assertEqual(one[0]['youtubeId'],'spurs123')
        self.assertEqual(two[0]['youtubeId'],'mavs123')
        self.assertEqual(sum('/search?' in x for x in calls),1)
        self.assertEqual(sum('/videos?' in x for x in calls),1)

    def test_official_channel_historical_rescue_finds_nba_quick_and_extended(self):
        search_payload={"items":[{"id":{"videoId":"quick123"}},{"id":{"videoId":"ext123"}}]}
        details_payload={"items":[
            {"id":"quick123","snippet":{"title":"CAVALIERS at KNICKS | FULL GAME HIGHLIGHTS | December 25, 2025","description":"Cleveland Cavaliers and New York Knicks Christmas Day highlights","channelTitle":"NBA","publishedAt":"2025-12-25T20:00:00Z","thumbnails":{}},"contentDetails":{"duration":"PT3M28S"},"status":{"embeddable":True,"privacyStatus":"public"}},
            {"id":"ext123","snippet":{"title":"EXTENDED: CAVALIERS at KNICKS | FULL GAME HIGHLIGHTS | December 25, 2025","description":"Cleveland Cavaliers and New York Knicks Christmas Day highlights","channelTitle":"NBA","publishedAt":"2025-12-25T21:00:00Z","thumbnails":{}},"contentDetails":{"duration":"PT14M12S"},"status":{"embeddable":True,"privacyStatus":"public"}},
        ]}
        def fake_fetch(url,timeout=0):
            if '/search?' in url: return search_payload
            if '/videos?' in url: return details_payload
            raise AssertionError(url)
        with patch.object(server,'read_youtube_key',return_value='yt-key'), \
             patch.object(server,'youtube_fetch_json',side_effect=fake_fetch), \
             patch.object(server,'_history_youtube_budget_take',return_value={'remaining':71}):
            out=server._official_youtube_history_api_results('NBA','2025-12-25','Cleveland Cavaliers','New York Knicks')
        self.assertEqual({x.get('youtubeId') for x in out},{'quick123','ext123'})
        self.assertTrue(all(x.get('verifiedPlayable') and x.get('embedValidated') for x in out))
        self.assertIn('green',{x.get('recapTier') for x in out})
        self.assertIn('extended',{x.get('recapTier') for x in out})

    def test_historical_generic_discovery_uses_official_channel_rescue_when_free_lane_is_empty(self):
        playable={'id':'official-rescue','youtubeId':'MEp3ymMFxsE','title':'CAVALIERS at KNICKS | FULL GAME HIGHLIGHTS | December 25, 2025','source':'NBA','sourceLabel':'NBA','provider':'YOUTUBE','durationSeconds':208,'overview':True,'verifiedPlayable':True,'embedValidated':True,'externalOnly':False}
        with patch.object(server,'_official_youtube_history_upload_results',return_value=[]), \
             patch.object(server,'_official_youtube_history_activity_results',return_value=[]), \
             patch.object(server,'_historical_youtube_web_results',return_value=[]), \
             patch.object(server,'_historical_search_engine_youtube_results',return_value=[]), \
             patch.object(server,'_official_youtube_history_api_results',return_value=[playable]) as rescue, \
             patch.object(server,'_espn_search_video_results',return_value=[]):
            out=server.generic_rapid_team_videos('NBA','2025-12-25','Cleveland Cavaliers','New York Knicks',force_refresh=True,allow_youtube=True)
        rescue.assert_called_once()
        self.assertTrue(any(x.get('youtubeId')=='MEp3ymMFxsE' and x.get('verifiedPlayable') for x in out))

    def test_historical_generic_discovery_does_not_spend_youtube_search_api_quota(self):
        playable={'id':'yt-web','youtubeId':'P6e9d5jOwX8','title':'MAVERICKS at WARRIORS | FULL GAME HIGHLIGHTS | December 25, 2025','source':'NBA','sourceLabel':'NBA','provider':'YOUTUBE','durationSeconds':600,'overview':True,'verifiedPlayable':True,'embedValidated':True,'externalOnly':False}
        with patch.object(server,'_official_youtube_history_upload_results',return_value=[]), \
             patch.object(server,'_official_youtube_history_activity_results',return_value=[]), \
             patch.object(server,'_historical_youtube_web_results',return_value=[playable]), \
             patch.object(server,'_espn_search_video_results',return_value=[]), \
             patch.object(server,'youtube_fetch_json',side_effect=AssertionError('search API should not run for history')):
            out=server.generic_rapid_team_videos('NBA','2025-12-25','Dallas Mavericks','Golden State Warriors',force_refresh=True,allow_youtube=True)
        self.assertTrue(any(x.get('youtubeId')=='P6e9d5jOwX8' and x.get('verifiedPlayable') for x in out))

    def test_history_repository_new_media_upgrades_same_youtube_identity(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3')
            repo.put_media('2025-12-25','NBA',[{'id':'old-feed','youtubeId':'P55rMeZkNwQ','verifiedPlayable':False,'externalOnly':True}],merge=True)
            repo.put_media('2025-12-25','NBA',[{'id':'new-index','youtubeId':'P55rMeZkNwQ','verifiedPlayable':True,'externalOnly':False,'embedValidated':True}],merge=True)
            media=repo.get_league('2025-12-25','NBA')['media']
        self.assertEqual(len(media),1)
        self.assertTrue(media[0]['verifiedPlayable'])
        self.assertFalse(media[0]['externalOnly'])
        self.assertTrue(media[0]['embedValidated'])

    def test_historical_public_index_lane_stays_candidate_without_videos_list_validation(self):
        indexed=[{'videoId':'P55rMeZkNwQ','url':'https://www.youtube.com/watch?v=P55rMeZkNwQ','title':'SPURS at THUNDER | FULL GAME HIGHLIGHTS | December 25, 2025','description':'','engine':'bing-rss'}]
        with patch.object(server,'_search_engine_youtube_links',return_value=indexed), \
             patch.object(server,'read_youtube_key',return_value=None), \
             patch.object(server,'_youtube_oembed_probe',return_value={'author_name':'NBA','title':indexed[0]['title'],'thumbnail_url':'https://img.test/x.jpg'}):
            out=server._historical_search_engine_youtube_results('NBA','2025-12-25','San Antonio Spurs','Oklahoma City Thunder')
        self.assertTrue(out)
        self.assertEqual(out[0]['youtubeId'],'P55rMeZkNwQ')
        self.assertFalse(out[0]['verifiedPlayable'])
        self.assertTrue(out[0]['externalOnly'])
        self.assertEqual(out[0]['validationState'],'CANDIDATE')
        self.assertEqual(out[0]['embedValidation'],'oembed-metadata-only+public-search-index')


    def test_history_repository_persists_runtime_playback_failure(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'history.sqlite3'; repo=HistoryRepository(path)
            event={'id':'evt','espnEventId':'evt','completed':True,'awayTeam':{'name':'Away'},'homeTeam':{'name':'Home'}}
            repo.put_scores('2025-12-25','NBA',[event])
            media={'id':'yt-row','youtubeId':'P55rMeZkNwQ','scoreEventId':'evt','matchId':'evt','verifiedPlayable':True,'validationState':'VERIFIED','historyVerifiedAt':time.time()}
            repo.put_event_media('2025-12-25','NBA','evt',[media])
            self.assertTrue(repo.record_runtime('2025-12-25','NBA','evt','yt:P55rMeZkNwQ',success=False,reason='YouTube 150'))
            reopened=HistoryRepository(path)
            rows=reopened.event_media('2025-12-25','NBA','evt',include_failed=True)
        self.assertEqual(rows[0]['runtimeCatalogState'],'FAILED')
        self.assertFalse(rows[0]['verifiedPlayable'])
        self.assertIn('150',rows[0]['runtimeFailureReason'])

    def test_history_repository_persists_discovery_progress(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3')
            repo.put_scores('2025-12-25','NFL',[])
            repo.put_discovery('2025-12-25','NFL',{'deepSearchedEventIds':['a'],'deepComplete':False})
            repo.put_discovery('2025-12-25','NFL',{'deepSearchedEventIds':['b'],'deepComplete':True})
            reopened=HistoryRepository(Path(td)/'history.sqlite3')
            state=reopened.get_league('2025-12-25','NFL')
            self.assertGreater(state['scoresSavedAt'],0)
            self.assertEqual(state['discovery']['deepSearchedEventIds'],['a','b'])
            self.assertTrue(state['discovery']['deepComplete'])

    def test_historical_media_is_bound_to_score_event_and_tiered(self):
        row={'id':'401999001','espnEventId':'401999001','completed':True,
             'awayTeam':{'name':'Dallas Cowboys','abbreviation':'DAL'},
             'homeTeam':{'name':'Washington Commanders','abbreviation':'WSH'}}
        media=[{'id':'quick','youtubeId':'yt-quick','title':'Cowboys vs Commanders Game Recap','durationSeconds':210,'overview':True,'verifiedPlayable':True},
               {'id':'extended','youtubeId':'yt-ext','title':'Cowboys vs Commanders Full Game Highlights','durationSeconds':900,'overview':True,'verifiedPlayable':True}]
        out=server._history_decorate_event_media('NFL','2025-12-25',row,media)
        self.assertEqual({x['matchId'] for x in out},{'401999001'})
        self.assertEqual({x['scoreEventId'] for x in out},{'401999001'})
        self.assertEqual({x['gameDate'] for x in out},{'2025-12-25'})
        self.assertIn('green',{x['recapTier'] for x in out})
        self.assertIn('extended',{x['recapTier'] for x in out})

    def test_full_historical_discovery_persists_multiple_media_types(self):
        row={'id':'nba-xmas-1','espnEventId':'nba-xmas-1','completed':True,
             'awayTeam':{'name':'Cleveland Cavaliers','abbreviation':'CLE'},
             'homeTeam':{'name':'New York Knicks','abbreviation':'NY'}}
        score_rows={lg:[] for lg in server.HISTORY_LEAGUES}; score_rows['NBA']=[row]
        no_quota=[{'id':'quick','youtubeId':'q','title':'Cavaliers vs Knicks Game Recap','durationSeconds':205,'overview':True,'verifiedPlayable':True}]
        deep=[
            {'id':'ext','youtubeId':'e','title':'Cavaliers vs Knicks Full Game Highlights','durationSeconds':900,'overview':True,'verifiedPlayable':True},
            {'id':'talk','youtubeId':'g','title':'Cavaliers vs Knicks Postgame Recap and Analysis','durationSeconds':240,'overview':True,'verifiedPlayable':True,'source':'ESPN'},
            {'id':'clip','youtubeId':'b','title':'Top dunk from Cavaliers vs Knicks','durationSeconds':42,'programType':'reel','verifiedPlayable':True},
        ]
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3')
            date='2025-12-25'
            for lg in server.HISTORY_LEAGUES: repo.put_scores(date,lg,score_rows.get(lg) or [])
            server.HISTORY_DISCOVERY_STATE.pop(date,None)
            with patch.object(server,'HISTORY_REPOSITORY',repo), \
                 patch.object(server,'_history_ensure_scores',return_value=(score_rows,[])), \
                 patch.object(server,'normalized_stats_highlights',return_value=[]), \
                 patch.object(server,'normalized_rapid_highlights',return_value=[]), \
                 patch.object(server,'_history_event_media_no_quota',return_value=no_quota), \
                 patch.object(server,'_official_youtube_history_upload_results',return_value=[]), \
                 patch.object(server,'_official_youtube_history_activity_results',return_value=deep), \
                 patch.object(server,'_official_youtube_history_day_search_results',return_value=[]), \
                 patch.object(server,'_historical_youtube_web_results',return_value=[]), \
                 patch.object(server,'_historical_search_engine_youtube_results',return_value=[]):
                state=server._history_discover_day(date,deep=True)
                saved=repo.get_league(date,'NBA')
            tiers={x.get('recapTier') for x in saved['media']}
            self.assertTrue({'green','extended','gold','blue'}.issubset(tiers))
            self.assertTrue(all(x.get('matchId')=='nba-xmas-1' for x in saved['media']))
            self.assertEqual(state['inventory']['leagues']['NBA']['playableGames'],1)
            self.assertTrue(saved['discovery']['deepComplete'])
            server.HISTORY_DISCOVERY_STATE.pop(date,None)


    def test_historical_discovery_upgrades_blue_without_short_circuiting_better_tiers(self):
        row={'id':'nba-upgrade-1','espnEventId':'nba-upgrade-1','completed':True,
             'awayTeam':{'name':'Brooklyn Nets','abbreviation':'BKN'},
             'homeTeam':{'name':'Los Angeles Lakers','abbreviation':'LAL'}}
        blue={'id':'blue','youtubeId':'blue-id','title':'Top plays Nets vs Lakers','durationSeconds':55,'programType':'reel','verifiedPlayable':True}
        green={'id':'green','youtubeId':'green-id','title':'Nets vs Lakers Game Recap','durationSeconds':210,'overview':True,'verifiedPlayable':True}
        extended={'id':'ext','youtubeId':'ext-id','title':'Nets vs Lakers Extended Highlights','durationSeconds':780,'overview':True,'verifiedPlayable':True}
        gold={'id':'gold','youtubeId':'gold-id','title':'Nets vs Lakers Postgame Recap and Analysis','durationSeconds':240,'overview':True,'verifiedPlayable':True,'source':'ESPN'}
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3'); date='2026-03-27'
            for lg in server.HISTORY_LEAGUES: repo.put_scores(date,lg,[row] if lg=='NBA' else [])
            repo.put_event_media(date,'NBA','nba-upgrade-1',server._history_decorate_event_media('NBA',date,row,[blue]))
            repo.set_event_discovery(date,'NBA','nba-upgrade-1','VERIFIED_PARTIAL',
                {'discoveryVersion':server.HISTORY_DISCOVERY_VERSION,'freeLaneComplete':True,'searchRescueAttempted':False,'catalogComplete':False},
                retry_at=time.time()+6*60*60,success=True)
            with patch.object(server,'HISTORY_REPOSITORY',repo), \
                 patch.object(server,'_history_event_media_no_quota',return_value=[blue]), \
                 patch.object(server,'_official_youtube_history_upload_results',return_value=[]), \
                 patch.object(server,'_official_youtube_history_activity_results',return_value=[green]), \
                 patch.object(server,'_official_youtube_history_day_search_results',return_value=[extended,gold]), \
                 patch.object(server,'_historical_youtube_web_results',return_value=[]), \
                 patch.object(server,'_historical_search_engine_youtube_results',return_value=[]):
                result=server._history_discover_event(date,'NBA',row,allow_search_rescue=True)
                plan=server._history_playback_plan(date,'NBA','nba-upgrade-1')
                saved=repo.get_event(date,'NBA','nba-upgrade-1')
            self.assertFalse(result.get('cached'))
            self.assertEqual(result['state'],'VERIFIED')
            self.assertTrue(result['catalogComplete'])
            self.assertTrue({'gold','green','extended','blue'}.issubset(set(result['tiersFound'])))
            self.assertEqual(plan['primary']['recapTier'],'gold')
            self.assertEqual(saved['discovery']['bestTier'],'gold')
            self.assertTrue(saved['discovery']['catalogComplete'])

    def test_catalog_complete_blue_remains_quality_upgrade_pending(self):
        row={'id':'nba-blue-closed','espnEventId':'nba-blue-closed','completed':True,
             'awayTeam':{'name':'Away Club'},'homeTeam':{'name':'Home Club'}}
        blue={'id':'blue','youtubeId':'blue-only-id','title':'Top plays Away Club vs Home Club','durationSeconds':50,'programType':'reel','verifiedPlayable':True}
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3'); date='2025-12-20'
            repo.put_scores(date,'NBA',[row])
            with patch.object(server,'HISTORY_REPOSITORY',repo), \
                 patch.object(server,'_history_event_media_no_quota',return_value=[blue]), \
                 patch.object(server,'_official_youtube_history_upload_results',return_value=[]), \
                 patch.object(server,'_official_youtube_history_activity_results',return_value=[]), \
                 patch.object(server,'_official_youtube_history_day_search_results',return_value=[]), \
                 patch.object(server,'_historical_youtube_web_results',return_value=[]), \
                 patch.object(server,'_historical_search_engine_youtube_results',return_value=[]):
                before=time.time()
                result=server._history_discover_event(date,'NBA',row,allow_search_rescue=True)
                saved=repo.get_event(date,'NBA','nba-blue-closed')
                inv=server._history_inventory(date)
            self.assertEqual(result['state'],'VERIFIED_UPGRADE_PENDING')
            self.assertTrue(result['catalogComplete'])
            self.assertFalse(result['qualityComplete'])
            self.assertTrue(result['upgradeEligible'])
            self.assertEqual(result['bestTier'],'blue')
            self.assertGreater(result['nextRetryAt'],before)
            self.assertFalse(saved['discovery']['qualityComplete'])
            self.assertEqual(saved['discovery']['missingBetterTiers'],['gold','green','extended'])
            self.assertEqual(inv['qualityCompleteGames'],0)
            self.assertEqual(inv['upgradeEligibleGames'],1)
            self.assertTrue(inv['needsUpgrade'])

    def test_history_audit_groups_media_by_game_and_tier(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            event={"scoreEventId":"evt1","awayTeam":{"name":"Away Club"},"homeTeam":{"name":"Home Club"},"completed":True}
            repo.put_scores("2025-12-26","NBA",[event])
            repo.put_event_media("2025-12-26","NBA","evt1",[
                {"id":"green1","scoreEventId":"evt1","recapTier":"green","title":"Full Game Highlights","youtubeId":"abcdefghijk","verifiedPlayable":True,"validationState":"VERIFIED","historyVerifiedAt":100},
                {"id":"blue1","scoreEventId":"evt1","recapTier":"blue","title":"Top Play","youtubeId":"lmnopqrstuv","verifiedPlayable":True,"validationState":"VERIFIED","historyVerifiedAt":90},
            ])
            repo.set_event_discovery("2025-12-26","NBA","evt1","VERIFIED_UPGRADE_PENDING",{"discoveryVersion":9,"bestTier":"green","qualityComplete":False,"upgradeEligible":True},retry_at=200)
            data=repo.audit_catalog(date_from="2025-12-26",date_to="2025-12-26",league="NBA")
            self.assertEqual(data["total"],1)
            row=data["rows"][0]
            self.assertEqual(row["game"],"Away Club @ Home Club")
            self.assertEqual(row["bestTier"],"green")
            self.assertEqual(len(row["tiers"]["green"]),1)
            self.assertEqual(len(row["tiers"]["blue"]),1)
            self.assertEqual(data["summary"]["tiers"]["green"],1)
            self.assertEqual(data["summary"]["upgradePendingGames"],1)

    def test_history_audit_projects_unknown_with_known_green_as_pending_index_and_upgradeable(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            event={"scoreEventId":"evt-stale-green","awayTeam":{"name":"Away"},"homeTeam":{"name":"Home"},"completed":True}
            repo.put_scores("2025-12-25","NBA",[event])
            repo.put_event_media("2025-12-25","NBA","evt-stale-green",[
                {"id":"green1","scoreEventId":"evt-stale-green","recapTier":"green","title":"Full Game Highlights","youtubeId":"abcdefghijk","verifiedPlayable":True,"validationState":"VERIFIED","historyVerifiedAt":100}
            ])
            data=repo.audit_catalog(date_from="2025-12-25",date_to="2025-12-25",current_discovery_version=9)
            row=data["rows"][0]
            self.assertEqual(row["discoveryState"],"UNKNOWN")
            self.assertEqual(row["effectiveStatus"],"PENDING_INDEX")
            self.assertTrue(row["discoveryPending"])
            self.assertTrue(row["upgradeEligible"])
            self.assertEqual(row["bestTier"],"green")
            self.assertEqual(data["summary"]["effectiveStatuses"]["PENDING_INDEX"],1)
            self.assertEqual(data["summary"]["upgradePendingGames"],1)

    def test_history_audit_projects_unknown_without_media_as_pending_index_not_false_complete(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            repo.put_scores("2025-12-24","NFL",[{"scoreEventId":"evt-empty","awayTeam":{"name":"Away"},"homeTeam":{"name":"Home"},"completed":True}])
            data=repo.audit_catalog(current_discovery_version=9)
            row=data["rows"][0]
            self.assertEqual(row["effectiveStatus"],"PENDING_INDEX")
            self.assertTrue(row["discoveryPending"])
            self.assertFalse(row["upgradeEligible"])
            self.assertEqual(data["summary"]["noVerifiedMediaGames"],1)

    def test_history_audit_actual_gold_overrides_stale_unknown_bookkeeping(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            event={"scoreEventId":"evt-gold","awayTeam":{"name":"Away"},"homeTeam":{"name":"Home"},"completed":True}
            repo.put_scores("2025-12-23","NBA",[event])
            repo.put_event_media("2025-12-23","NBA","evt-gold",[
                {"id":"gold1","scoreEventId":"evt-gold","recapTier":"gold","title":"Postgame Recap","youtubeId":"abcdefghijk","verifiedPlayable":True,"validationState":"VERIFIED","historyVerifiedAt":100}
            ])
            row=repo.audit_catalog(current_discovery_version=9)["rows"][0]
            self.assertEqual(row["effectiveStatus"],"QUALITY_COMPLETE")
            self.assertTrue(row["qualityComplete"])
            self.assertFalse(row["upgradeEligible"])

    def test_history_audit_export_preserves_raw_state_and_adds_projected_status(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            repo.put_scores("2025-12-22","NBA",[{"scoreEventId":"evt-export","awayTeam":{"name":"Away"},"homeTeam":{"name":"Home"},"completed":True}])
            rows=repo.audit_export_rows(current_discovery_version=9)
            self.assertEqual(rows[0]["Audit Status"],"PENDING INDEX")
            self.assertEqual(rows[0]["Discovery State"],"UNKNOWN")
            self.assertTrue(rows[0]["Discovery Pending"])
            self.assertEqual(rows[0]["Current Discovery Version"],9)

    def test_discovery_version_10_soft_reindex_ignores_old_closed_retry(self):
        row={'id':'nba-old-v7','espnEventId':'nba-old-v7','completed':True,
             'awayTeam':{'name':'Away Club'},'homeTeam':{'name':'Home Club'}}
        blue={'id':'old-blue','youtubeId':'old-blue-id','title':'Top plays Away Club vs Home Club','durationSeconds':45,'programType':'reel','verifiedPlayable':True}
        gold={'id':'new-gold','youtubeId':'new-gold-id','title':'Away Club vs Home Club Postgame Recap and Analysis','durationSeconds':240,'overview':True,'verifiedPlayable':True,'source':'ESPN'}
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3'); date='2025-12-19'
            repo.put_scores(date,'NBA',[row])
            repo.put_event_media(date,'NBA','nba-old-v7',server._history_decorate_event_media('NBA',date,row,[blue]))
            repo.set_event_discovery(date,'NBA','nba-old-v7','VERIFIED',
                {'discoveryVersion':7,'freeLaneComplete':True,'searchRescueAttempted':True,'catalogComplete':True},
                retry_at=time.time()+7*24*60*60,success=True)
            with patch.object(server,'HISTORY_REPOSITORY',repo), \
                 patch.object(server,'_history_event_media_no_quota',return_value=[gold]), \
                 patch.object(server,'_official_youtube_history_upload_results',return_value=[]), \
                 patch.object(server,'_official_youtube_history_activity_results',return_value=[]), \
                 patch.object(server,'_official_youtube_history_day_search_results',return_value=[]), \
                 patch.object(server,'_historical_youtube_web_results',return_value=[]), \
                 patch.object(server,'_historical_search_engine_youtube_results',return_value=[]):
                result=server._history_discover_event(date,'NBA',row,allow_search_rescue=True)
                saved=repo.get_event(date,'NBA','nba-old-v7')
            self.assertFalse(result.get('cached'))
            self.assertEqual(result['state'],'VERIFIED')
            self.assertEqual(result['bestTier'],'gold')
            self.assertTrue(result['qualityComplete'])
            self.assertEqual(saved['discovery']['discoveryVersion'],10)
            self.assertTrue(saved['discovery']['qualityComplete'])

    def test_quality_upgrade_due_respects_persistent_retry_window(self):
        row={'id':'nba-retry','espnEventId':'nba-retry','completed':True,
             'awayTeam':{'name':'Away Club'},'homeTeam':{'name':'Home Club'}}
        blue={'id':'retry-blue','youtubeId':'retry-blue-id','title':'Top plays Away Club vs Home Club','durationSeconds':45,'programType':'reel','verifiedPlayable':True}
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3'); date='2025-12-18'
            repo.put_scores(date,'NBA',[row])
            repo.put_event_media(date,'NBA','nba-retry',server._history_decorate_event_media('NBA',date,row,[blue]))
            details={'discoveryVersion':server.HISTORY_DISCOVERY_VERSION,'freeLaneComplete':True,'searchRescueAttempted':True,
                     'catalogComplete':True,'qualityComplete':False,'upgradeEligible':True,'bestTier':'blue'}
            repo.set_event_discovery(date,'NBA','nba-retry','VERIFIED_UPGRADE_PENDING',details,retry_at=time.time()+3600,success=True)
            with patch.object(server,'HISTORY_REPOSITORY',repo):
                future=server._history_inventory(date)
            self.assertTrue(future['needsUpgrade'])
            self.assertFalse(future['upgradeDue'])
            repo.set_event_discovery(date,'NBA','nba-retry','VERIFIED_UPGRADE_PENDING',details,retry_at=time.time()-1,success=True)
            with patch.object(server,'HISTORY_REPOSITORY',repo):
                due=server._history_inventory(date)
            self.assertTrue(due['needsUpgrade'])
            self.assertTrue(due['upgradeDue'])
            self.assertEqual(due['upgradeDueGames'],1)

    def test_background_playable_event_remains_partial_until_foreground_search_lane_runs(self):
        row={'id':'nba-bg-1','espnEventId':'nba-bg-1','completed':True,
             'awayTeam':{'name':'Away Club'},'homeTeam':{'name':'Home Club'}}
        blue={'id':'blue','youtubeId':'blue-only','title':'Top plays Away Club vs Home Club','durationSeconds':50,'programType':'reel','verifiedPlayable':True}
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3'); date='2026-03-26'
            repo.put_scores(date,'NBA',[row])
            with patch.object(server,'HISTORY_REPOSITORY',repo), \
                 patch.object(server,'_history_event_media_no_quota',return_value=[blue]), \
                 patch.object(server,'_official_youtube_history_upload_results',return_value=[]), \
                 patch.object(server,'_official_youtube_history_activity_results',return_value=[]), \
                 patch.object(server,'_historical_youtube_web_results',return_value=[]), \
                 patch.object(server,'_historical_search_engine_youtube_results',return_value=[]):
                result=server._history_discover_event(date,'NBA',row,allow_search_rescue=False)
                inv=server._history_inventory(date)
            self.assertEqual(result['state'],'VERIFIED_PARTIAL')
            self.assertFalse(result['catalogComplete'])
            self.assertTrue(inv['leagues']['NBA']['deepComplete'])
            self.assertFalse(inv['leagues']['NBA']['catalogComplete'])
            self.assertTrue(inv['needsUpgrade'])

    def test_christmas_day_catalog_can_cover_all_nfl_and_nba_games(self):
        def score(event_id,away,home):
            return {'id':event_id,'espnEventId':event_id,'completed':True,
                    'awayTeam':{'name':away},'homeTeam':{'name':home},'state':{'status':'Final'}}
        score_rows={lg:[] for lg in server.HISTORY_LEAGUES}
        score_rows['NFL']=[
            score('nfl1','Dallas Cowboys','Washington Commanders'),
            score('nfl2','Detroit Lions','Minnesota Vikings'),
            score('nfl3','Denver Broncos','Kansas City Chiefs'),
        ]
        score_rows['NBA']=[
            score('nba1','Cleveland Cavaliers','New York Knicks'),
            score('nba2','San Antonio Spurs','Oklahoma City Thunder'),
            score('nba3','Dallas Mavericks','Golden State Warriors'),
            score('nba4','Houston Rockets','Los Angeles Lakers'),
            score('nba5','Boston Celtics','Philadelphia 76ers'),
        ]
        def activity(league,date,away,home,max_items=24,force=False):
            slug=(away.split()[-1]+'-'+home.split()[-1]).lower()
            return [{'id':f'{league}-{slug}','youtubeId':('x'+str(abs(hash((league,away,home)))))[:11].ljust(11,'0'),
                     'title':f'{away} vs {home} Full Game Highlights','durationSeconds':240,'overview':True,
                     'verifiedPlayable':True,'embedValidated':True,'validationState':'VERIFIED','provider':'YOUTUBE','source':league}]
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3'); date='2025-12-25'
            for lg in server.HISTORY_LEAGUES: repo.put_scores(date,lg,score_rows[lg])
            server.HISTORY_DISCOVERY_STATE.pop(date,None)
            with patch.object(server,'HISTORY_REPOSITORY',repo), \
                 patch.object(server,'_history_ensure_scores',return_value=(score_rows,[])), \
                 patch.object(server,'_history_event_media_no_quota',return_value=[]), \
                 patch.object(server,'_official_youtube_history_upload_results',return_value=[]), \
                 patch.object(server,'_official_youtube_history_activity_results',side_effect=activity), \
                 patch.object(server,'_official_youtube_history_day_search_results',return_value=[]), \
                 patch.object(server,'_historical_youtube_web_results',return_value=[]), \
                 patch.object(server,'_historical_search_engine_youtube_results',return_value=[]):
                state=server._history_discover_day(date,deep=True)
        inv=state['inventory']
        self.assertEqual(inv['completedGames'],8)
        self.assertEqual(inv['playableGames'],8)
        self.assertEqual(inv['leagues']['NFL']['playableGames'],3)
        self.assertEqual(inv['leagues']['NBA']['playableGames'],5)
        self.assertEqual(inv['candidateMedia'],0)
        server.HISTORY_DISCOVERY_STATE.pop(date,None)

    def test_v281_historical_discovery_markers_are_rebuilt_after_upgrade(self):
        row={'id':'old-evt','completed':True,'awayTeam':{'name':'Away Club'},'homeTeam':{'name':'Home Club'}}
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/'history.sqlite3')
            date='2025-12-24'
            for lg in server.HISTORY_LEAGUES: repo.put_scores(date,lg,[row] if lg=='NBA' else [])
            # Simulate the old release falsely marking a date/game complete.
            repo.put_discovery(date,'NBA',{'deepSearchedEventIds':['old-evt'],'deepComplete':True})
            with patch.object(server,'HISTORY_REPOSITORY',repo):
                inv=server._history_inventory(date)
            self.assertEqual(inv['leagues']['NBA']['searchedGames'],0)
            self.assertFalse(inv['leagues']['NBA']['deepComplete'])

    def test_stale_native_historical_media_requests_refresh_without_discarding_durable_youtube(self):
        row={'id':'evt1','completed':True,'awayTeam':{'name':'Away Club'},'homeTeam':{'name':'Home Club'}}
        stale=time.time()-7*60*60
        direct={'id':'native','matchId':'evt1','mediaUrl':'https://example.test/signed.mp4','verifiedPlayable':True}
        durable={'id':'yt','matchId':'evt1','youtubeId':'durable','verifiedPlayable':True}
        self.assertTrue(server._history_event_needs_native_refresh({'mediaSavedAt':stale,'media':[direct]},row))
        self.assertFalse(server._history_event_needs_native_refresh({'mediaSavedAt':stale,'media':[direct,durable]},row))

    def test_openai_json_parser_recovers_fenced_structured_output(self):
        parsed=server._openai_json_object('```json\n{"items":[{"id":"1"}]}\n```')
        self.assertEqual(parsed['items'][0]['id'],'1')

    def test_espn_postgame_analysis_is_gold_commentary_not_blue_reel(self):
        item={"title":"Did Man United look better without Fernandes in win vs Newcastle?","source":"ESPN FC","durationSeconds":90,"programType":"reel","overview":False}
        self.assertEqual(tier(item),"gold")


if __name__=='__main__': unittest.main()

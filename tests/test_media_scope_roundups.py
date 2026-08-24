import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from sbb.history_repository import HistoryRepository
from sbb.history_rebuild import HistoryCatalogRebuilder
from sbb.media_scope import annotate, GAME, DAY_LEAGUE, WEEK_LEAGUE, ROUND_LEAGUE, OTHER
from sbb.youtube_gateway import YouTubeRateLimited


class MediaScopeRoundupTests(unittest.TestCase):
    def test_scope_separates_nightly_roundup_from_game_highlights(self):
        nightly=annotate({"title":"NBA's Nightly Recap | January 28, 2026","durationSeconds":1538,"provider":"YOUTUBE",
                          "channelId":"UCWJ2lWNubArHWmf3FIHbfcQ","publishedAt":"2026-01-28T08:00:00Z"},
                         league="NBA",date="2026-01-26",away="Los Angeles Lakers",home="Chicago Bulls")
        game=annotate({"title":"LAKERS at BULLS | FULL GAME HIGHLIGHTS | January 26, 2026","durationSeconds":995,"provider":"YOUTUBE"},
                      league="NBA",date="2026-01-26",away="Los Angeles Lakers",home="Chicago Bulls")
        wrong=annotate({"title":"WARRIORS at TIMBERWOLVES | FULL GAME HIGHLIGHTS | January 26, 2026","durationSeconds":900,"provider":"YOUTUBE"},
                       league="NBA",date="2026-01-26",away="Los Angeles Lakers",home="Chicago Bulls")
        self.assertEqual(nightly["mediaScope"],DAY_LEAGUE)
        self.assertEqual(nightly["collectionTier"],"silver")
        self.assertEqual(nightly["collectionPeriodKey"],"2026-01-28")
        self.assertEqual(game["mediaScope"],GAME)
        self.assertEqual(wrong["mediaScope"],OTHER)

    def test_cross_event_association_keeps_only_target_game_and_routes_roundup(self):
        target={"id":"761743","espnEventId":"761743","completed":True,
                "awayTeam":{"name":"Seattle Sounders FC"},"homeTeam":{"name":"FC Cincinnati"}}
        rows=[
            {"id":"wrong","youtubeId":"wrong-video","title":"LAFC vs. Portland Timbers | Full Match Highlights","durationSeconds":624,"verifiedPlayable":True},
            {"id":"right","youtubeId":"right-video","title":"FC Cincinnati vs. Seattle Sounders FC | Full Match Highlights","durationSeconds":632,"verifiedPlayable":True},
            {"id":"roundup","youtubeId":"roundup-video","title":"MLS Daily Recap | August 23, 2026","durationSeconds":1200,"verifiedPlayable":True,
             "provider":"YOUTUBE","channelId":"UCSZbXT5TLLW_i-5W8FZpFsg","publishedAt":"2026-08-23T23:00:00Z"},
        ]
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            repo.put_scores("2026-08-23","MLS",[target])
            with patch.object(server,"HISTORY_REPOSITORY",repo):
                out=server._history_decorate_event_media("MLS","2026-08-23",target,rows)
            self.assertEqual([x["youtubeId"] for x in out],["right-video"])
            self.assertEqual(out[0]["scoreEventId"],"761743")
            roundups=repo.roundup_media("2026-08-23","MLS")
            self.assertEqual([x["youtubeId"] for x in roundups],["roundup-video"])
            self.assertEqual(roundups[0]["displayTier"],"silver")

    def test_v4_rebuild_distrusts_legacy_wrong_event_stamp(self):
        event={"scoreEventId":"761743","awayTeam":{"name":"Seattle Sounders FC"},"homeTeam":{"name":"FC Cincinnati"},"completed":True}
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/"v3.sqlite3"; output=Path(td)/"v4.sqlite3"; now=time.time()
            conn=sqlite3.connect(source)
            conn.execute("CREATE TABLE history_day(date TEXT,league TEXT,scores_json TEXT,media_json TEXT,discovery_json TEXT,scores_saved_at REAL,media_saved_at REAL,discovery_saved_at REAL,PRIMARY KEY(date,league))")
            conn.execute("CREATE TABLE history_event(date TEXT,league TEXT,event_id TEXT,event_json TEXT,discovery_state TEXT,discovery_json TEXT,last_discovery_at REAL,last_success_at REAL,next_retry_at REAL,last_error TEXT,updated_at REAL,PRIMARY KEY(date,league,event_id))")
            conn.execute("CREATE TABLE history_media_asset(date TEXT,league TEXT,event_id TEXT,asset_key TEXT,asset_json TEXT,validation_state TEXT,verified_at REAL,runtime_state TEXT,runtime_success_at REAL,runtime_failure_at REAL,runtime_failure_reason TEXT,last_seen_at REAL,updated_at REAL,PRIMARY KEY(date,league,event_id,asset_key))")
            conn.execute("INSERT INTO history_day VALUES(?,?,?,?,?,?,?,?)",("2026-08-23","MLS",json.dumps([event]),"[]","{}",now,now,now))
            conn.execute("INSERT INTO history_event VALUES(?,?,?,?,?,?,?,?,?,?,?)",("2026-08-23","MLS","761743",json.dumps(event),"VERIFIED","{}",now,now,0,"",now))
            legacy=[
                ("yt:daily",{"id":"daily","youtubeId":"daily","matchId":"761743","scoreEventId":"761743","title":"MLS Daily Recap | August 23, 2026","durationSeconds":1200,"verifiedPlayable":True,"recapTier":"green",
                             "provider":"YOUTUBE","channelId":"UCSZbXT5TLLW_i-5W8FZpFsg","publishedAt":"2026-08-23T23:00:00Z"}),
                ("yt:wrong",{"id":"wrong","youtubeId":"wrong","matchId":"761743","scoreEventId":"761743","title":"LAFC vs Portland Timbers | Full Match Highlights","durationSeconds":624,"verifiedPlayable":True,"recapTier":"extended"}),
                ("yt:right",{"id":"right","youtubeId":"right","matchId":"761743","scoreEventId":"761743","title":"FC Cincinnati vs Seattle Sounders FC | Full Match Highlights","durationSeconds":632,"verifiedPlayable":True,"recapTier":"extended"}),
            ]
            for key,item in legacy:
                conn.execute("INSERT INTO history_media_asset VALUES(?,?,?,?,?,'VERIFIED',?,'UNKNOWN',0,0,'',?,?)",("2026-08-23","MLS","761743",key,json.dumps(item),now,now,now))
            conn.commit(); conn.close()
            result=HistoryCatalogRebuilder(source,output).rebuild()
            self.assertTrue(result["passed"])
            repo=HistoryRepository(output)
            self.assertEqual([x.get("youtubeId") for x in repo.event_media("2026-08-23","MLS","761743")],["right"])
            self.assertEqual(repo.roundup_media("2026-08-23","MLS")[0]["youtubeId"],"daily")
            conn=sqlite3.connect(output)
            state=conn.execute("SELECT catalog_state FROM history_source_media WHERE asset_key='yt:wrong'").fetchone()[0]
            conn.close(); self.assertEqual(state,"QUARANTINED")

    def test_weekly_silver_uses_league_season_week_not_calendar_week(self):
        nba=annotate({"youtubeId":"week24","title":"The TOP Plays of Week 24 | 2025-26 NBA Season","provider":"YOUTUBE",
                      "channelId":"UCWJ2lWNubArHWmf3FIHbfcQ","publishedAt":"2026-04-03T12:00:00Z"},league="NBA",date="2026-04-03")
        nfl=annotate({"youtubeId":"week18","title":"Every Touchdown from Week 18 | 2025 NFL Season","provider":"YOUTUBE",
                      "channelId":"UCDVYQ4Zhbm3S2dlz7P1GBDg","publishedAt":"2026-01-03T12:00:00Z"},league="NFL",date="2026-01-03")
        self.assertEqual(nba.get("collectionPeriodKey"),"2025-26:W24")
        self.assertEqual(nba.get("collectionSeasonId"),"2025-26"); self.assertEqual(nba.get("collectionSeasonWeek"),24)
        self.assertEqual(nfl.get("collectionPeriodKey"),"2025:W18")

    def test_player_week_clip_and_unproven_channel_do_not_become_silver(self):
        player=annotate({"youtubeId":"player","title":"Stetson Bennett's best plays from 2-TD game vs. Saints | Preseason Week 2",
                         "provider":"YOUTUBE","channelId":"UCDVYQ4Zhbm3S2dlz7P1GBDg","publishedAt":"2026-08-21T12:00:00Z"},league="NFL",date="2026-08-23")
        unofficial=annotate({"youtubeId":"fake","title":"NBA's Nightly Recap | August 23, 2026","provider":"YOUTUBE",
                             "channelId":"small-town-shop","channelName":"Small Town Hoops Official","publishedAt":"2026-08-23T23:00:00Z"},league="NBA",date="2026-08-23")
        self.assertNotEqual(player.get("collectionTier"),"silver")
        self.assertNotEqual(unofficial.get("collectionTier"),"silver")
        self.assertEqual(unofficial.get("sourceAuthority"),"UNKNOWN")

    def test_daily_period_comes_from_content_not_backfill_encounter_date(self):
        item=annotate({"youtubeId":"allgames","title":"Highlights from ALL GAMES on 8/21","provider":"YOUTUBE",
                       "channelId":"UCoLrcjPV5PbUrUyXq5mjc_A","publishedAt":"2026-08-22T05:00:00Z"},league="MLB",date="2026-08-23")
        self.assertEqual(item.get("collectionPeriodKey"),"2026-08-21")


    def test_v418_soccer_roundups_use_matchweek_matchday_identity(self):
        mls=annotate({"title":"Every goal from Matchday 21!","officialLeagueSource":True,"sourceType":"official-mls-matchday-roundup",
                      "publishedAt":"2026-06-20T12:00:00Z"},league="MLS",date="2026-06-20")
        epl=annotate({"title":"BEST GOALS of Matchweek 38","officialLeagueSource":True,"sourceType":"official-premierleague-roundup",
                      "publishedAt":"2026-05-24T12:00:00Z"},league="EPL",date="2026-05-24")
        self.assertEqual(mls.get("mediaScope"),ROUND_LEAGUE)
        self.assertEqual(mls.get("collectionPeriodKey"),"2026:MD21")
        self.assertEqual(mls.get("collectionKind"),"SCORING_ROUNDUP")
        self.assertEqual(mls.get("collectionRoundType"),"MATCHDAY")
        self.assertEqual(epl.get("mediaScope"),ROUND_LEAGUE)
        self.assertEqual(epl.get("collectionPeriodKey"),"2025-26:MW38")
        self.assertEqual(epl.get("collectionKind"),"TOP_PLAYS")
        self.assertEqual(epl.get("collectionRoundType"),"MATCHWEEK")

    def test_v418_nhl_top_goals_week_is_weekly_silver(self):
        nhl=annotate({"title":"Top Goals from Week 24 of the 2025-26 NHL Season","officialLeagueSource":True,
                      "sourceType":"official-nhl-weekly-roundup","publishedAt":"2026-04-05T12:00:00Z"},
                     league="NHL",date="2026-04-05")
        self.assertEqual(nhl.get("mediaScope"),WEEK_LEAGUE)
        self.assertEqual(nhl.get("collectionPeriodKey"),"2025-26:W24")
        self.assertEqual(nhl.get("collectionKind"),"TOP_PLAYS")
        self.assertEqual(nhl.get("collectionTier"),"silver")

    def test_existing_green_candidate_promotes_before_new_discovery(self):
        row={"id":"mlb-score-id","espnEventId":"mlb-score-id","completed":True,
             "awayTeam":{"name":"Colorado Rockies"},"homeTeam":{"name":"Arizona Diamondbacks"}}
        candidate={"id":"mlb-candidate","scoreEventId":"mlb-score-id","mediaUrl":"https://example.test/recap.mp4",
                   "title":"Rockies vs Diamondbacks Game Recap","durationSeconds":180,"overview":True,
                   "verifiedPlayable":False,"validationState":"CANDIDATE","source":"MLB Stats API","sourceType":"mlb-game-content"}
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3"); date="2026-08-10"
            repo.put_scores(date,"MLB",[row]); repo.put_event_media(date,"MLB","mlb-score-id",[candidate])
            def promoted(item,timeout=6):
                out=dict(item); out.update(verifiedPlayable=True,validationState="VERIFIED",nativeValidated=True,nativeValidation="test",historyVerifiedAt=time.time()); return out
            bomb=lambda *a,**k: (_ for _ in ()).throw(AssertionError("new discovery should not run before candidate promotion"))
            with patch.object(server,"HISTORY_REPOSITORY",repo), patch.object(server,"_history_validate_native_asset",side_effect=promoted), \
                 patch.object(server,"_history_event_media_no_quota",side_effect=bomb):
                result=server._history_discover_event(date,"MLB",row,allow_search_rescue=True)
            self.assertTrue(result.get("candidatePromoted"))
            self.assertEqual(result["bestTier"],"green")
            self.assertEqual(repo.event_media(date,"MLB","mlb-score-id")[0]["validationState"],"VERIFIED")

    def test_canonical_queue_dedupes_adjacent_date_alias_and_obeys_current_generation_cooldown(self):
        event={"scoreEventId":"same-event","awayTeam":{"name":"Away"},"homeTeam":{"name":"Home"},"completed":True}
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"history.sqlite3"; repo=HistoryRepository(path)
            repo.put_scores("2026-08-22","NBA",[event]); repo.put_scores("2026-08-23","NBA",[event])
            repo.set_event_discovery("2026-08-23","NBA","same-event","SEARCHED_EMPTY",{"discoveryVersion":11},retry_at=0)
            # Same-generation retries honor cooldown. A new discovery generation
            # deliberately bypasses that old cooldown and still returns only one
            # canonical LEAGUE:EventID row despite the adjacent-date alias.
            self.assertEqual(repo.green_gap_events(current_discovery_version=11,now=time.time(),recent_cooldown=7200,archive_cooldown=86400),[])
            due=repo.green_gap_events(current_discovery_version=12,now=time.time(),recent_cooldown=7200,archive_cooldown=86400)
            self.assertEqual(len(due),1)
            self.assertEqual(due[0]["canonicalEventKey"],"NBA:same-event")

    def test_search_quota_reserves_recent_bucket_when_archive_is_exhausted(self):
        with tempfile.TemporaryDirectory() as td:
            budget=Path(td)/"budget.json"
            with patch.object(server,"HISTORY_YOUTUBE_BUDGET_FILE",budget), patch.object(server,"HISTORY_YOUTUBE_SEARCH_BUDGET",10):
                limits=server._history_youtube_budget_limits(); self.assertEqual(limits,{"recent":4,"empty":3,"blue":2,"archive":1})
                server._history_youtube_budget_take("archive")
                with self.assertRaises(YouTubeRateLimited): server._history_youtube_budget_take("archive")
                server._history_youtube_budget_take("recent")
                status=server._history_youtube_budget_status()
                self.assertEqual(status["usedByBucket"]["archive"],1)
                self.assertEqual(status["usedByBucket"]["recent"],1)
                self.assertEqual(status["remainingByBucket"]["recent"],3)


if __name__ == '__main__':
    unittest.main()

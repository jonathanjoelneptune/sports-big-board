import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from sbb.history_repository import HistoryRepository
from sbb.media_scope import annotate, GAME, DAY_LEAGUE, OTHER
from sbb.youtube_gateway import YouTubeRateLimited


class MediaScopeRoundupTests(unittest.TestCase):
    def test_scope_separates_nightly_roundup_from_game_highlights(self):
        nightly=annotate({"title":"NBA's Nightly Recap | January 28, 2026","durationSeconds":1538,"provider":"YOUTUBE"},
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
            {"id":"roundup","youtubeId":"roundup-video","title":"MLS Daily Recap | August 23, 2026","durationSeconds":1200,"verifiedPlayable":True},
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

    def test_soft_migration_distrusts_legacy_wrong_event_stamp(self):
        event={"scoreEventId":"761743","awayTeam":{"name":"Seattle Sounders FC"},"homeTeam":{"name":"FC Cincinnati"},"completed":True}
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"history.sqlite3"; repo=HistoryRepository(path)
            repo.put_scores("2026-08-23","MLS",[event])
            now=time.time()
            legacy=[
                ("yt:daily",{"id":"daily","youtubeId":"daily","matchId":"761743","scoreEventId":"761743","title":"MLS Daily Recap | August 23, 2026","durationSeconds":1200,"verifiedPlayable":True,"recapTier":"green"}),
                ("yt:wrong",{"id":"wrong","youtubeId":"wrong","matchId":"761743","scoreEventId":"761743","title":"LAFC vs Portland Timbers | Full Match Highlights","durationSeconds":624,"verifiedPlayable":True,"recapTier":"extended"}),
                ("yt:right",{"id":"right","youtubeId":"right","matchId":"761743","scoreEventId":"761743","title":"FC Cincinnati vs Seattle Sounders FC | Full Match Highlights","durationSeconds":632,"verifiedPlayable":True,"recapTier":"extended"}),
            ]
            conn=sqlite3.connect(path)
            for key,item in legacy:
                conn.execute("INSERT INTO history_media_asset(date,league,event_id,asset_key,asset_json,validation_state,verified_at,last_seen_at,updated_at) VALUES(?,?,?,?,?,'VERIFIED',?,?,?)",
                             ("2026-08-23","MLS","761743",key,json.dumps(item),now,now,now))
            conn.commit(); conn.close()
            result=repo.reclassify_media_scopes()
            self.assertGreaterEqual(result["movedToCollections"],1)
            game_ids=[x.get("youtubeId") for x in repo.event_media("2026-08-23","MLS","761743")]
            self.assertEqual(game_ids,["right"])
            self.assertEqual(repo.roundup_media("2026-08-23","MLS")[0]["youtubeId"],"daily")
            # Unrelated game is quarantined rather than counted as target coverage.
            conn=sqlite3.connect(path)
            scope=json.loads(conn.execute("SELECT asset_json FROM history_media_asset WHERE asset_key='yt:wrong'").fetchone()[0])["mediaScope"]
            conn.close(); self.assertEqual(scope,OTHER)

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

    def test_canonical_queue_dedupes_adjacent_date_alias_and_obeys_cooldown(self):
        event={"scoreEventId":"same-event","awayTeam":{"name":"Away"},"homeTeam":{"name":"Home"},"completed":True}
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"history.sqlite3"; repo=HistoryRepository(path)
            repo.put_scores("2026-08-22","NBA",[event]); repo.put_scores("2026-08-23","NBA",[event])
            repo.set_event_discovery("2026-08-23","NBA","same-event","SEARCHED_EMPTY",{"discoveryVersion":11},retry_at=0)
            # A version bump alone cannot immediately requeue a game just searched.
            self.assertEqual(repo.green_gap_events(current_discovery_version=12,now=time.time(),recent_cooldown=7200,archive_cooldown=86400),[])
            conn=sqlite3.connect(path); conn.execute("UPDATE history_event SET last_discovery_at=? WHERE league='NBA' AND event_id='same-event'",(time.time()-90000,)); conn.commit(); conn.close()
            due=repo.green_gap_events(current_discovery_version=12,now=time.time(),recent_cooldown=0,archive_cooldown=0)
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

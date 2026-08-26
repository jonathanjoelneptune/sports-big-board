import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from sbb.history_repository import HistoryRepository


class V4123CatalogFirstTests(unittest.TestCase):
    def test_release_boundary_preserves_discovery_and_rule_versions(self):
        self.assertEqual(server.APP_VERSION, "4.2.2")
        self.assertEqual(server.HISTORY_DISCOVERY_VERSION, 15)
        self.assertEqual(server.HISTORY_RULE_CATCHUP_VERSION, 10)
        self.assertEqual(server.HISTORY_RULE_COLLECTION_CATCHUP_VERSION, 8)

    def test_schedule_sync_refreshes_yesterday_today_and_future_with_force(self):
        calls=[]
        def fake(date,league,tz,offset,force=False):
            calls.append((date,league,force))
            return ([{"id":f"{league}-{date}","status":"Scheduled"}],"TEST",False,"")
        state=dict(server.HISTORY_SCHEDULE_SYNC_STATE)
        try:
            server.HISTORY_SCHEDULE_SYNC_STATE.update(lastFullRun=0)
            with patch.object(server,"_history_schedule_sync_today",return_value="2026-08-25"), patch.object(server,"_history_get_league_scores",side_effect=fake):
                out=server._history_schedule_sync_once(full=True)
            dates=sorted({x[0] for x in calls})
            self.assertEqual(dates[0],"2026-08-24")
            self.assertEqual(dates[-1],"2026-09-08")
            self.assertIn("2026-08-25",dates)
            self.assertEqual(len(calls),16*len(server.HISTORY_LEAGUES))
            self.assertTrue(all(x[2] for x in calls))
            self.assertEqual(out["today"],"2026-08-25")
        finally:
            server.HISTORY_SCHEDULE_SYNC_STATE.clear(); server.HISTORY_SCHEDULE_SYNC_STATE.update(state)

    def test_operator_playlist_crawl_hydrates_orphan_then_assigns_canonical_event(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            event={"id":"n1","competitionId":"NHL","status":"Final","awayTeam":{"displayName":"Vegas Golden Knights"},"homeTeam":{"displayName":"Carolina Hurricanes"}}
            repo.put_scores("2026-06-14","NHL",[event])
            operator={"id":"op1","playlistId":"PLTEST123456789","url":"https://www.youtube.com/playlist?list=PLTEST123456789","league":"NHL","title":"Test NHL","seasonStart":2026,"seasonEnd":2026,"objective":"extended","priority":"PRIMARY","trust":"OPERATOR_TRUSTED","enabled":True,"autoRecrawl":False,"recrawlMinutes":60,"channelId":"","channelTitle":"NHL","createdAt":1,"updatedAt":1,"stats":{}}
            item={"id":"x","youtubeId":"abcdefghijk","eventId":"abcdefghijk","title":"Hurricanes vs. Golden Knights | NHL Playoff Highlights | Game 6 | June 14, 2026","description":"Carolina Hurricanes vs. Vegas Golden Knights Game 6 highlights","durationSeconds":752,"duration":752,"publishedAt":"2026-06-14T23:00:00Z","provider":"YOUTUBE","verifiedPlayable":True,"embedValidated":True,"validationState":"VERIFIED","recapTier":"extended","mediaObjective":"EXTENDED","source":"NHL","sourceLabel":"NHL","sourceType":"operator-youtube-game-playlist","officialPlaylistId":"PLTEST123456789","officialPlaylistTitle":"Test NHL","externalUrl":"https://www.youtube.com/watch?v=abcdefghijk"}
            state_file=Path(td)/"operator-media-playlists.json"
            with patch.object(server,"HISTORY_REPOSITORY",repo), patch.object(server,"OPERATOR_MEDIA_PLAYLISTS_FILE",state_file), patch.object(server,"_curated_playlist_items",return_value=[item]):
                server._operator_media_playlists_save([operator])
                result=server._operator_media_playlist_crawl("op1",force=True)
            self.assertEqual(result["stats"]["assets"],1)
            self.assertEqual(result["stats"]["assigned"],1)
            self.assertEqual(result["stats"]["orphaned"],0)
            media=repo.event_media("2026-06-14","NHL","n1",include_failed=True)
            self.assertEqual(len(media),1)
            self.assertEqual(media[0]["youtubeId"],"abcdefghijk")
            self.assertEqual(media[0]["canonicalEventKey"],"NHL:n1")

    def test_repository_exposes_catalog_events_and_playlist_asset_stats(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            repo.put_scores("2026-08-25","EPL",[{"id":"e1","status":"Scheduled","awayTeam":{"displayName":"Chelsea"},"homeTeam":{"displayName":"Fulham"}}])
            events=repo.catalog_events(league="EPL",date_from="2026-08-25",date_to="2026-08-25")
            self.assertEqual(len(events),1)
            self.assertEqual(events[0]["canonicalEventKey"],"EPL:e1")
            self.assertEqual(repo.playlist_asset_stats("not-present"),{"assets":0,"assigned":0,"orphaned":0,"quarantined":0})

    def test_frontend_is_catalog_first_and_playlist_manager_is_interactive(self):
        root=Path(__file__).resolve().parents[1]
        app=(root/"app.js").read_text(encoding="utf-8")
        index=(root/"index.html").read_text(encoding="utf-8")
        ui=(root/"ui"/"history-audit.js").read_text(encoding="utf-8")
        backend=(root/"server.py").read_text(encoding="utf-8")
        self.assertIn("const CATALOG_EVENT_PLANS=new Map()",app)
        self.assertIn("function catalogPlanForScoreGame",app)
        self.assertIn("CATALOG_EVENT_PLANS.get(`${lg}:${id}`)",app)
        self.assertIn("__sbbCatalogExact:true",app)
        self.assertIn("x?.__sbbCatalogExact===true||mediaMatchesScoreGame",app)
        self.assertIn("eventPlans",backend)
        self.assertIn("catalogFirst",backend)
        browse=app[app.index("async function setScoreBrowseDate"):app.index("function stepScoreRibbonDate",app.index("async function setScoreBrowseDate"))]
        self.assertNotIn("startHistoricalDateDiscovery(date)",browse)
        self.assertIn("refreshHistoricalDiscoverySnapshot(date,{hydrate:false})",browse)
        self.assertIn("historyMediaPlaylistForm",index)
        self.assertIn("historyScheduleSyncNow",index)
        self.assertIn("ADD & CRAWL PLAYLIST",index)
        self.assertIn("savePlaylistForm",ui)
        self.assertIn("data-playlist-action=\"crawl\"",ui)
        self.assertIn("/api/history/media-sources",ui)
        self.assertIn("history_media_playlist_crawler_worker",backend)
        self.assertIn("history_schedule_sync_worker",backend)
        self.assertIn("sbb-history-schedule-sync",backend)
        self.assertIn("sbb-media-playlist-crawler",backend)

    def test_historical_ribbon_uses_catalog_events_without_waiting_on_score_providers(self):
        root=Path(__file__).resolve().parents[1]
        app=(root/"app.js").read_text(encoding="utf-8")
        backend=(root/"server.py").read_text(encoding="utf-8")
        self.assertIn("scoreInventoryComplete",backend)
        self.assertIn("catalogEventCount",backend)
        self.assertIn("const catalogRowsByLeague=new Map()",app)
        self.assertIn("storeScoreDateLeague(lg,date,rows)",app)
        self.assertIn("hydrateHistoricalRibbonFromCatalog",app)
        self.assertIn("if(ribbon.scoreInventoryComplete)",app)
        self.assertIn("source:'CATALOG_RIBBON'",app)

    def test_key_info_today_has_rolling_recent_fallback(self):
        root=Path(__file__).resolve().parents[1]
        app=(root/"app.js").read_text(encoding="utf-8")
        self.assertIn("rolling 36-hour window",app)
        self.assertIn("scoreBrowseDate!==localDateISO(0)",app)
        self.assertIn("refreshKeyInformation(false,true).catch(()=>{})",app)

    def test_android_history_audit_uses_outer_vertical_scroll_container(self):
        root=Path(__file__).resolve().parents[1]
        css=(root/"styles.css").read_text(encoding="utf-8")
        marker="/* v4.2.2 Android/mobile Historical Database Audit scroll repair."
        self.assertIn(marker,css)
        mobile=css[css.index(marker):]
        self.assertIn("height:100dvh",mobile)
        self.assertIn("overflow-y:auto",mobile)
        self.assertIn("-webkit-overflow-scrolling:touch",mobile)
        self.assertIn("touch-action:pan-y",mobile)
        self.assertIn(".history-audit-table thead{position:static}",mobile)
        self.assertIn("overflow-y:visible",mobile)


if __name__ == "__main__":
    unittest.main()

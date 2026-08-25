import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from sbb.history_repository import HistoryRepository


class V4121ParallelRecoveryTests(unittest.TestCase):
    def test_worker_pool_roles_and_provider_limits(self):
        self.assertEqual(server.HISTORY_GREEN_WORKERS, 5)
        self.assertEqual(server._history_worker_role(1), {"kind":"affinity","league":"NFL","label":"NFL"})
        self.assertEqual(server._history_worker_role(2)["league"], "MLS")
        self.assertEqual(server._history_worker_role(3)["league"], "EPL")
        self.assertEqual(server._history_worker_role(4)["label"], "FLOAT-NHL")
        self.assertEqual(server._history_worker_role(5)["label"], "FLOAT-GENERIC")
        # v4.1.29 intentionally scales scheduling without scaling provider semaphores.
        self.assertEqual(server.HISTORY_PROVIDER_LIMITS.get("youtube"), 2)
        self.assertEqual(server.HISTORY_PROVIDER_LIMITS.get("web"), 2)
        self.assertEqual(server.HISTORY_PROVIDER_LIMITS.get("native"), 3)

    def test_gap_opportunity_prefers_uncovered_and_nhl(self):
        today="2026-08-24"
        uncovered_nhl={"league":"NHL","date":"2026-08-20","verifiedCount":0,"bestTier":"none"}
        old_purple={"league":"MLB","date":"2025-09-01","verifiedCount":1,"bestTier":"extended"}
        uncovered_mlb={"league":"MLB","date":"2026-08-20","verifiedCount":0,"bestTier":"none"}
        self.assertGreater(server._history_gap_opportunity_score(uncovered_nhl,today), server._history_gap_opportunity_score(old_purple,today))
        self.assertGreater(server._history_gap_opportunity_score(uncovered_nhl,today), server._history_gap_opportunity_score(uncovered_mlb,today))

    def test_source_reopen_preview_and_apply_preserve_media(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            date="2026-08-20"; league="NFL"; event_id="evt1"
            event={"id":event_id,"status":"Final","awayTeam":{"name":"Away"},"homeTeam":{"name":"Home"}}
            repo.upsert_event(date,league,event_id,event)
            source=server.HISTORY_OFFICIAL_CATCHUP_SOURCES[league][0]
            repo.mark_source_enrichment(league,event_id,source["key"],source["version"],"COMPLETE",accepted_count=0)
            media={"youtubeId":"abcdefghijk","title":"Away vs Home Highlights","provider":"YOUTUBE","verifiedPlayable":True,"validationState":"VERIFIED","recapTier":"extended","mediaScope":"GAME","scope":"GAME"}
            repo.put_media(date,league,[media],merge=True)
            with patch.object(server,"HISTORY_REPOSITORY",repo), patch.object(server,"_client_date_iso",return_value="2026-08-24"):
                preview=server._history_recovery_preview({"action":"source_reopen","league":"NFL","sourceKey":source["key"],"startDate":"2026-08-24","direction":"newest"})
                self.assertTrue(preview["ok"])
                self.assertEqual(preview["result"]["records"],1)
                self.assertEqual(preview["result"]["newlyEligible"],1)
                applied=server._history_recovery_apply({"action":"source_reopen","league":"NFL","sourceKey":source["key"],"startDate":"2026-08-24","direction":"newest","confirmToken":preview["confirmToken"]})
                self.assertTrue(applied["result"]["mediaPreserved"])
                self.assertEqual(applied["result"]["deleted"],1)
                after=repo.source_enrichment_reset_preview(server.HISTORY_OFFICIAL_CATCHUP_SOURCES,league="NFL",source_key=source["key"],date_from=server.HISTORY_OFFICIAL_CATCHUP_FLOOR_DATE,date_to="2026-08-24")
                self.assertEqual(after["records"],0)
                self.assertTrue(any(x.get("youtubeId")=="abcdefghijk" for x in repo.get_league(date,league,prefer_catalog=False).get("media",[])))

    def test_cursor_restart_does_not_reopen_source_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            repo.upsert_event("2026-08-20","EPL","e1",{"id":"e1","status":"Final"})
            source=server.HISTORY_OFFICIAL_CATCHUP_SOURCES["EPL"][0]
            repo.mark_source_enrichment("EPL","e1",source["key"],source["version"],"COMPLETE")
            with patch.object(server,"HISTORY_REPOSITORY",repo), patch.object(server,"_client_date_iso",return_value="2026-08-24"):
                preview=server._history_recovery_preview({"action":"cursor_restart","league":"EPL","startDate":"TODAY","direction":"newest"})
                self.assertTrue(preview["result"]["sourceLedgerPreserved"])
                self.assertEqual(preview["result"]["newlyEligible"],0)
                server._history_recovery_apply({"action":"cursor_restart","league":"EPL","startDate":"TODAY","direction":"newest","confirmToken":preview["confirmToken"]})
                still=repo.source_enrichment_reset_preview(server.HISTORY_OFFICIAL_CATCHUP_SOURCES,league="EPL",source_key=source["key"],date_from=server.HISTORY_OFFICIAL_CATCHUP_FLOOR_DATE,date_to="2026-08-24")
                self.assertEqual(still["records"],1)
                self.assertEqual(repo.catalog_meta(server._history_cursor_meta_key("EPL","upper")),"TODAY")

    def test_database_audit_restart_is_local_and_persistent(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            repo.upsert_event("2026-08-20","NHL","n1",{"id":"n1","status":"Final"})
            with patch.object(server,"HISTORY_REPOSITORY",repo), patch.object(server,"_client_date_iso",return_value="2026-08-24"):
                preview=server._history_recovery_preview({"action":"database_audit_restart"})
                self.assertTrue(preview["result"]["localAuditOnly"])
                applied=server._history_recovery_apply({"action":"database_audit_restart","confirmToken":preview["confirmToken"]})
                self.assertTrue(applied["result"]["mediaPreserved"])
                self.assertEqual(repo.catalog_meta("database_audit_cursor"),"0")
                self.assertEqual(repo.catalog_meta("database_audit_complete"),"0")

    def test_silver_identity_audit_one_youtube_id_one_asset(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            item={"youtubeId":"silver12345x","title":"Every Goal from Matchweek 1 | 2026-27 Premier League Season","description":"Premier League Matchweek 1 goals","provider":"YOUTUBE","channelId":server.EPL_YOUTUBE_PL_CHANNEL_ID,"channelTitle":"Premier League","officialLeagueSource":True,"verifiedPlayable":True,"validationState":"VERIFIED","collectionRoundNumber":1,"collectionRoundType":"MATCHWEEK","programType":"roundup","publishedAt":"2026-08-18T12:00:00Z"}
            first=repo.put_collection_media("ROUND_LEAGUE","EPL","2026-27:MW1",[item],collection_kind="SCORING_ROUNDUP",return_stats=True)
            second=repo.put_collection_media("ROUND_LEAGUE","EPL","2026-27:MW1",[item],collection_kind="SCORING_ROUNDUP",return_stats=True)
            audit=repo.silver_identity_audit(league="EPL")
            self.assertEqual(first["newUniqueAssets"],1)
            self.assertEqual(second["existingAssetsReused"],1)
            self.assertEqual(audit["youtubeIds"],1)
            self.assertEqual(audit["uniqueAssets"],1)
            self.assertEqual(audit["duplicateYoutubeIdentities"],0)


    def test_operator_controls_and_reporting_contract(self):
        root=Path(__file__).resolve().parents[1]
        index=(root/"index.html").read_text(encoding="utf-8")
        audit=(root/"ui"/"history-audit.js").read_text(encoding="utf-8")
        backend=(root/"server.py").read_text(encoding="utf-8")
        for token in ("historyRecoveryAction","historyRecoveryLeague","historyRecoveryPreview","historyRecoveryApply"):
            self.assertIn(token,index)
        for token in ("[WORKER UTILIZATION]","[CATCH-UP POSITION]","[SCHEDULER]","[EVERY GOAL IDENTITY]","source-complete","INDEX PASS PENDING"):
            self.assertIn(token,audit)
        self.assertIn('/api/history/admin/recovery/preview',backend)
        self.assertIn('/api/history/admin/recovery/apply',backend)
        self.assertIn('sbb-history-database-audit',backend)



if __name__ == "__main__":
    unittest.main()

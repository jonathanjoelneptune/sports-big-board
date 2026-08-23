import json
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from sbb.catalog_contract import CATALOG_SCHEMA_VERSION, MEDIA_CLASSIFIER_VERSION, EVENT_MATCHER_VERSION
from sbb.history_repository import HistoryRepository

ROOT=Path(__file__).resolve().parents[1]


class HistoryV4BaselineTests(unittest.TestCase):
    def test_normalized_source_event_and_classifier_evidence_are_separate(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/"history.sqlite3"; repo=HistoryRepository(db)
            event={"scoreEventId":"401810516","awayTeam":{"name":"Los Angeles Lakers"},"homeTeam":{"name":"Chicago Bulls"},"completed":True,"completedAt":"2026-01-27T03:12:00Z"}
            repo.put_scores("2026-01-26","NBA",[event])
            accepted=repo.put_event_media("2026-01-26","NBA","401810516",[{"youtubeId":"GDLPuIBAXkE","title":"LAKERS at BULLS | FULL GAME HIGHLIGHTS | January 26, 2026","durationSeconds":995,"verifiedPlayable":True,"recapTier":"extended","provider":"YOUTUBE"}])
            self.assertEqual(accepted,1)
            conn=sqlite3.connect(db); conn.row_factory=sqlite3.Row
            src=conn.execute("SELECT * FROM history_source_media").fetchone(); link=conn.execute("SELECT * FROM history_event_media").fetchone(); ev=conn.execute("SELECT * FROM history_catalog_event").fetchone()
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM history_source_media").fetchone()[0],1)
            self.assertEqual(src["asset_key"],"yt:GDLPuIBAXkE")
            self.assertEqual(src["scope"],"GAME"); self.assertGreaterEqual(src["scope_confidence"],0.9)
            self.assertTrue(src["scope_reason"]); self.assertTrue(src["intent_reason"]); self.assertGreater(src["intent_confidence"],0)
            self.assertEqual(src["classifier_version"],MEDIA_CLASSIFIER_VERSION)
            self.assertEqual(link["association_state"],"ASSIGNED"); self.assertGreaterEqual(link["association_confidence"],0.9)
            self.assertIn(link["association_method"],{"EXACT_TEAM_PAIR_TITLE","PROVIDER_EVENT_ID"}); self.assertEqual(link["matcher_version"],EVENT_MATCHER_VERSION)
            self.assertGreater(ev["final_at"],0); conn.close()

    def test_silver_collection_has_independent_evidence_and_never_game_link(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/"history.sqlite3"; repo=HistoryRepository(db)
            event={"scoreEventId":"401810516","awayTeam":{"name":"Los Angeles Lakers"},"homeTeam":{"name":"Chicago Bulls"},"completed":True}
            repo.put_scores("2026-01-26","NBA",[event])
            nightly={"youtubeId":"nightly12345","title":"NBA's Nightly Recap | January 26, 2026","durationSeconds":1253,"verifiedPlayable":True,"provider":"YOUTUBE"}
            self.assertEqual(repo.put_event_media("2026-01-26","NBA","401810516",[nightly]),0)
            self.assertEqual(repo.put_collection_media("DAY_LEAGUE","NBA","2026-01-26",[nightly],collection_kind="DAILY_RECAP"),1)
            integrity=repo.catalog_integrity(); self.assertEqual(integrity["silverGameLeaks"],0); self.assertEqual(integrity["collectionGameLeaks"],0)
            rows=repo.collection_audit(league="NBA",period_key="2026-01-26")["rows"]
            self.assertEqual(len(rows),1); self.assertGreaterEqual(rows[0]["associationConfidence"],0.8); self.assertTrue(rows[0]["associationEvidence"])
            self.assertEqual(repo.event_media("2026-01-26","NBA","401810516"),[])

    def test_source_identity_does_not_collapse_multiple_clips_using_same_generic_id(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            rows=[
                {"id":"same-game-id","title":"First scoring play","provider":"ESPN","externalUrl":"https://espn.test/game/1"},
                {"id":"same-game-id","title":"Second scoring play","provider":"ESPN","externalUrl":"https://espn.test/game/1"},
            ]
            repo.put_source_media(rows,league="NFL",date="2026-08-23")
            self.assertEqual(repo.catalog_integrity()["sourceAssets"],2)
            # A direct media URL is the stronger identity and dedupes independently of title.
            direct1={"id":"a","title":"A","provider":"MLB","mediaUrl":"https://cdn.test/clip.mp4"}
            direct2={"id":"b","title":"B","provider":"MLB","mediaUrl":"https://cdn.test/clip.mp4"}
            repo.put_source_media([direct1,direct2],league="MLB",date="2026-08-23")
            self.assertEqual(repo.catalog_integrity()["sourceAssets"],3)

    def test_ledgers_segments_and_review_queue_are_durable(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/"history.sqlite3"; repo=HistoryRepository(db)
            event={"scoreEventId":"evt1","awayTeam":{"name":"Away Club"},"homeTeam":{"name":"Home Club"},"completed":True}
            repo.put_scores("2026-08-20","NBA",[event])
            game={"youtubeId":"abcdefghijk","title":"Away Club vs Home Club Full Game Highlights","verifiedPlayable":True,"recapTier":"extended"}
            repo.put_event_media("2026-08-20","NBA","evt1",[game]); asset=repo.event_media("2026-08-20","NBA","evt1")[0]["assetKey"]
            repo.record_discovery_attempt("NBA","evt1",source="youtube-official-uploads",discovery_version=13,query_type="PROVIDER_LANE",result_count=3,accepted_count=1,best_before="blue",best_after="extended",quota_cost=0)
            repo.record_verification(asset,"EMBED","VERIFIED",reason="test")
            seg=repo.add_segment(asset,league="NBA",event_id="evt1",start_seconds=45,end_seconds=210,title="Game segment",confidence=.98,evidence="chapter")
            self.assertTrue(seg)
            self.assertEqual(repo.discovery_attempts(league="NBA",event_id="evt1")["rows"][0]["bestAfter"],"extended")
            self.assertEqual(repo.catalog_integrity()["verificationRecords"],1); self.assertEqual(repo.catalog_integrity()["segments"],1)
            wrong={"youtubeId":"wrongwrong11","title":"Completely Different Teams Full Game Highlights","verifiedPlayable":True}
            repo.put_event_media("2026-08-20","NBA","evt1",[wrong])
            review=repo.assignment_reviews(state="QUARANTINED"); self.assertGreaterEqual(review["total"],1); self.assertEqual(review["rows"][0]["state"],"QUARANTINED")

    def test_preflight_recognizes_fresh_v4_without_mutating_or_rebuilding(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td); db=state/"cache"/"history.sqlite3"; db.parent.mkdir(parents=True)
            repo=HistoryRepository(db); repo.put_scores("2026-01-01","NBA",[])
            proc=subprocess.run(["python3",str(ROOT/"tools/ensure_history_v4.py"),"--state-dir",str(state)],capture_output=True,text=True,check=True)
            data=json.loads(proc.stdout.strip()); self.assertEqual(data["action"],"V4_ALREADY_READY"); self.assertEqual(data["before"]["catalogSchemaVersion"],CATALOG_SCHEMA_VERSION)
            self.assertFalse(list((state/"backups").glob("history-pre-v4-*.sqlite3")))

    def test_preflight_rebuilds_legacy_into_second_catalog_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td); db=state/"cache"/"history.sqlite3"; db.parent.mkdir(parents=True); now=time.time()
            event={"scoreEventId":"evt1","awayTeam":{"name":"Away Club"},"homeTeam":{"name":"Home Club"},"completed":True}
            conn=sqlite3.connect(db)
            conn.execute("CREATE TABLE history_day(date TEXT,league TEXT,scores_json TEXT,media_json TEXT,discovery_json TEXT,scores_saved_at REAL,media_saved_at REAL,discovery_saved_at REAL,PRIMARY KEY(date,league))")
            conn.execute("CREATE TABLE history_event(date TEXT,league TEXT,event_id TEXT,event_json TEXT,discovery_state TEXT,discovery_json TEXT,last_discovery_at REAL,last_success_at REAL,next_retry_at REAL,last_error TEXT,updated_at REAL,PRIMARY KEY(date,league,event_id))")
            conn.execute("CREATE TABLE history_media_asset(date TEXT,league TEXT,event_id TEXT,asset_key TEXT,asset_json TEXT,validation_state TEXT,verified_at REAL,runtime_state TEXT,runtime_success_at REAL,runtime_failure_at REAL,runtime_failure_reason TEXT,last_seen_at REAL,updated_at REAL,PRIMARY KEY(date,league,event_id,asset_key))")
            conn.execute("INSERT INTO history_day VALUES(?,?,?,?,?,?,?,?)",("2026-08-20","NBA",json.dumps([event]),"[]","{}",now,now,now))
            conn.execute("INSERT INTO history_event VALUES(?,?,?,?,?,?,?,?,?,?,?)",("2026-08-20","NBA","evt1",json.dumps(event),"VERIFIED","{}",now,now,0,"",now))
            item={"youtubeId":"abcdefghijk","scoreEventId":"evt1","title":"Away Club vs Home Club Full Game Highlights","verifiedPlayable":True,"recapTier":"extended"}
            conn.execute("INSERT INTO history_media_asset VALUES(?,?,?,?,?,'VERIFIED',?,'UNKNOWN',0,0,'',?,?)",("2026-08-20","NBA","evt1","yt:abcdefghijk",json.dumps(item),now,now,now)); conn.commit(); conn.close()
            proc=subprocess.run(["python3",str(ROOT/"tools/ensure_history_v4.py"),"--state-dir",str(state)],capture_output=True,text=True,check=True)
            data=json.loads(proc.stdout.strip()); self.assertEqual(data["action"],"REBUILT"); self.assertTrue(data["rebuild"]["passed"])
            self.assertTrue(Path(data["rollbackBackup"]).exists()); self.assertTrue(Path(data["reconciliationReport"]).exists())
            repo=HistoryRepository(db); self.assertEqual(repo.catalog_integrity()["schemaVersion"],4); self.assertEqual(len(repo.event_media("2026-08-20","NBA","evt1")),1)

    def test_rebuild_conflict_resolution_quarantines_cross_event_asset_before_hard_audit(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td); source=state/"legacy.sqlite3"; output=state/"v4.sqlite3"; now=time.time()
            e1={"scoreEventId":"evt1","awayTeam":{"name":"Away One"},"homeTeam":{"name":"Home One"},"completed":True}
            e2={"scoreEventId":"evt2","awayTeam":{"name":"Away Two"},"homeTeam":{"name":"Home Two"},"completed":True}
            conn=sqlite3.connect(source)
            conn.execute("CREATE TABLE history_day(date TEXT,league TEXT,scores_json TEXT,media_json TEXT,discovery_json TEXT,scores_saved_at REAL,media_saved_at REAL,discovery_saved_at REAL,PRIMARY KEY(date,league))")
            conn.execute("CREATE TABLE history_event(date TEXT,league TEXT,event_id TEXT,event_json TEXT,discovery_state TEXT,discovery_json TEXT,last_discovery_at REAL,last_success_at REAL,next_retry_at REAL,last_error TEXT,updated_at REAL,PRIMARY KEY(date,league,event_id))")
            conn.execute("CREATE TABLE history_media_asset(date TEXT,league TEXT,event_id TEXT,asset_key TEXT,asset_json TEXT,validation_state TEXT,verified_at REAL,runtime_state TEXT,runtime_success_at REAL,runtime_failure_at REAL,runtime_failure_reason TEXT,last_seen_at REAL,updated_at REAL,PRIMARY KEY(date,league,event_id,asset_key))")
            conn.execute("INSERT INTO history_day VALUES(?,?,?,?,?,?,?,?)",("2026-08-20","NBA",json.dumps([e1,e2]),"[]","{}",now,now,now))
            for eid,event in (("evt1",e1),("evt2",e2)):
                conn.execute("INSERT INTO history_event VALUES(?,?,?,?,?,?,?,?,?,?,?)",("2026-08-20","NBA",eid,json.dumps(event),"VERIFIED","{}",now,now,0,"",now))
            # Same source asset is stamped into two games, reproducing the legacy contamination class.
            item={"youtubeId":"abcdefghijk","title":"Generic Full Game Highlights","verifiedPlayable":True,"mediaScope":"GAME"}
            for eid in ("evt1","evt2"):
                stamped=dict(item,sourceType="espn-event-video",scoreEventId=eid)
                conn.execute("INSERT INTO history_media_asset VALUES(?,?,?,?,?,'VERIFIED',?,'UNKNOWN',0,0,'',?,?)",("2026-08-20","NBA",eid,"yt:abcdefghijk",json.dumps(stamped),now,now,now))
            conn.commit(); conn.close()
            from sbb.history_rebuild import HistoryCatalogRebuilder
            report=HistoryCatalogRebuilder(source,output).rebuild(force=True)
            self.assertTrue(report["passed"],report)
            self.assertEqual(report["integrity"]["crossEventAssignedAssets"],0)
            self.assertGreaterEqual(report["conflictResolution"]["crossEventAssetsQuarantined"],1)
            repo=HistoryRepository(output)
            self.assertGreaterEqual(repo.assignment_reviews(reason="CROSS_EVENT_CONFLICT")["total"],1)

    def test_launch_and_cloud_paths_enforce_v4_preflight(self):
        for path in (ROOT/"start.sh",ROOT/"START-ANDROID.sh",ROOT/"START SPORTS BIG BOARD.bat",ROOT/"cloud/vm/INSTALL-STAGE1.sh",ROOT/"cloud/gcp/DEPLOY-FROM-GITHUB.sh"):
            self.assertIn("ensure_history_v4.py",path.read_text())
        deploy=(ROOT/"cloud/gcp/DEPLOY-FROM-GITHUB.sh").read_text()
        self.assertIn("MIGRATION_BACKUP",deploy); self.assertIn("Restored pre-v4 history catalog",deploy)


if __name__=='__main__': unittest.main()

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
            nightly={"youtubeId":"nightly12345","title":"NBA's Nightly Recap | January 26, 2026","durationSeconds":1253,"verifiedPlayable":True,"provider":"YOUTUBE",
                     "channelId":"UCWJ2lWNubArHWmf3FIHbfcQ","publishedAt":"2026-01-26T23:30:00Z"}
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


    def test_reindex_reset_is_not_recorded_as_a_discovery_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/"history.sqlite3"; repo=HistoryRepository(db)
            event={"scoreEventId":"evt1","awayTeam":{"name":"Away Club"},"homeTeam":{"name":"Home Club"},"completed":True}
            details={"catalogSchemaVersion":4,"discoveryVersion":0,"rebuildImportedAt":time.time(),"rebuildState":"PENDING_CURRENT_DISCOVERY"}
            repo.upsert_event("2026-08-20","NBA","evt1",event)
            repo.reset_event_for_reindex("2026-08-20","NBA","evt1",details)
            row=repo.get_event("2026-08-20","NBA","evt1")
            self.assertEqual(row["lastDiscoveryAt"],0)
            self.assertEqual(row["nextRetryAt"],0)
            self.assertEqual(row["discovery"]["discoveryVersion"],0)

    def test_stale_discovery_generation_bypasses_retry_cooldown(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            event={"scoreEventId":"evt1","awayTeam":{"name":"Away Club"},"homeTeam":{"name":"Home Club"},"completed":True}
            repo.upsert_event("2026-08-20","NBA","evt1",event)
            # A real v12 attempt happened moments ago. Discovery v15 must still
            # be allowed immediately because generation changes invalidate the
            # old cooldown.
            repo.set_event_discovery("2026-08-20","NBA","evt1","SEARCHED_EMPTY",{"discoveryVersion":12},retry_at=time.time()+86400)
            rows=repo.green_gap_events(current_discovery_version=13,now=time.time())
            self.assertEqual([r["eventId"] for r in rows],["evt1"])
            summary=repo.green_gap_summary(current_discovery_version=13,now=time.time())
            self.assertEqual(summary["due"],1)
            self.assertEqual(summary["unindexed"],1)
            self.assertNotIn("noMedia",summary)
            self.assertEqual(summary["unindexedOrEmpty"],1)

    def test_current_discovery_generation_still_respects_cooldown(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            event={"scoreEventId":"evt1","awayTeam":{"name":"Away Club"},"homeTeam":{"name":"Home Club"},"completed":True}
            repo.upsert_event("2026-08-20","NBA","evt1",event)
            repo.set_event_discovery("2026-08-20","NBA","evt1","SEARCHED_EMPTY",{"discoveryVersion":13},retry_at=0)
            self.assertEqual(repo.green_gap_events(current_discovery_version=13,now=time.time()),[])
            self.assertEqual(repo.green_gap_summary(current_discovery_version=13,now=time.time())["due"],0)

    def test_startup_release_repairs_v400_artificial_rebuild_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            event={"scoreEventId":"evt1","awayTeam":{"name":"Away Club"},"homeTeam":{"name":"Home Club"},"completed":True}
            repo.upsert_event("2026-08-20","NBA","evt1",event)
            details={"catalogSchemaVersion":4,"discoveryVersion":0,"rebuildImportedAt":time.time(),"rebuildState":"PENDING_CURRENT_DISCOVERY"}
            repo.set_event_discovery("2026-08-20","NBA","evt1","UNKNOWN",details,retry_at=time.time()+86400)
            self.assertGreater(repo.get_event("2026-08-20","NBA","evt1")["lastDiscoveryAt"],0)
            self.assertEqual(repo.release_rebuild_pending_events(13),1)
            row=repo.get_event("2026-08-20","NBA","evt1")
            self.assertEqual(row["lastDiscoveryAt"],0); self.assertEqual(row["nextRetryAt"],0)
            self.assertEqual(repo.release_rebuild_pending_events(13),0)

    def test_preflight_recognizes_fresh_v4_without_mutating_or_rebuilding(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td); db=state/"cache"/"history.sqlite3"; db.parent.mkdir(parents=True)
            repo=HistoryRepository(db); repo.put_scores("2026-01-01","NBA",[])
            proc=subprocess.run(["python3",str(ROOT/"tools/ensure_history_v4.py"),"--state-dir",str(state)],capture_output=True,text=True,check=True)
            data=json.loads(proc.stdout.strip()); self.assertEqual(data["action"],"V4_ALREADY_READY"); self.assertEqual(data["before"]["catalogSchemaVersion"],CATALOG_SCHEMA_VERSION)
            self.assertFalse(list((state/"backups").glob("history-pre-v4-*.sqlite3")))

    def test_preflight_preserves_discovery_progress_for_repairable_relationship_drift(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td); db=state/"cache"/"history.sqlite3"; db.parent.mkdir(parents=True)
            repo=HistoryRepository(db)
            e1={"scoreEventId":"evt1","awayTeam":{"name":"Alpha Bears"},"homeTeam":{"name":"Beta Hawks"},"completed":True}
            e2={"scoreEventId":"evt2","awayTeam":{"name":"Gamma Cats"},"homeTeam":{"name":"Delta Wolves"},"completed":True}
            repo.put_scores("2026-08-20","NBA",[e1,e2])
            retry=time.time()+7200
            repo.set_event_discovery("2026-08-20","NBA","evt1","VERIFIED_PARTIAL",{"discoveryVersion":13,"catalogComplete":True,"qualityComplete":False},retry_at=retry,success=True)
            repo.record_discovery_attempt("NBA","evt1",source="official-native",discovery_version=13,query_type="PROVIDER_LANE",result_count=3,accepted_count=1,best_before="blue",best_after="extended")
            media={"youtubeId":"sharedasset1","title":"Alpha Bears vs Beta Hawks Game Highlights","verifiedPlayable":True,"provider":"YOUTUBE","mediaScope":"GAME","recapTier":"extended"}
            repo.put_source_media([media],league="NBA",date="2026-08-20",away="Alpha Bears",home="Beta Hawks")
            conn=sqlite3.connect(db)
            asset=conn.execute("SELECT asset_key FROM history_source_media LIMIT 1").fetchone()[0]
            now=time.time()
            for key in ("NBA:evt1","NBA:evt2"):
                conn.execute("INSERT INTO history_event_media(canonical_event_key,asset_key,association_state,association_confidence,association_method,association_evidence,matcher_version,first_associated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(key,asset,"ASSIGNED",1.0,"LEGACY_STAMP","legacy",4,now,now))
            conn.execute("UPDATE history_catalog_meta SET value='4' WHERE key='event_association_repair_version'")
            day_progress={"deepComplete":True,"deepGames":1,"discoveryVersion":13,"lastEventId":"evt1"}
            conn.execute("UPDATE history_day SET discovery_json=?,discovery_saved_at=? WHERE date='2026-08-20' AND league='NBA'",(json.dumps(day_progress),now))
            before_event=conn.execute("SELECT discovery_state,discovery_json,last_discovery_at,last_success_at,next_retry_at,last_error FROM history_catalog_event WHERE canonical_event_key='NBA:evt1'").fetchone()
            before_attempts=conn.execute("SELECT COUNT(*) FROM history_discovery_attempt").fetchone()[0]
            before_day=conn.execute("SELECT discovery_json,discovery_saved_at FROM history_day WHERE date='2026-08-20' AND league='NBA'").fetchone()
            conn.commit(); conn.close()

            proc=subprocess.run(["python3",str(ROOT/"tools/ensure_history_v4.py"),"--state-dir",str(state)],capture_output=True,text=True,check=True)
            data=json.loads(proc.stdout.strip())
            self.assertEqual(data["action"],"V4_ALREADY_READY")
            self.assertTrue(data["repairRequired"],data)
            self.assertEqual(data["before"]["reason"],"V4_READY")
            self.assertTrue(Path(data["rollbackBackup"]).exists())
            self.assertFalse(list((state/"backups").glob("history-pre-v4-*.sqlite3")))

            conn=sqlite3.connect(db)
            after_event=conn.execute("SELECT discovery_state,discovery_json,last_discovery_at,last_success_at,next_retry_at,last_error FROM history_catalog_event WHERE canonical_event_key='NBA:evt1'").fetchone()
            after_attempts=conn.execute("SELECT COUNT(*) FROM history_discovery_attempt").fetchone()[0]
            after_day=conn.execute("SELECT discovery_json,discovery_saved_at FROM history_day WHERE date='2026-08-20' AND league='NBA'").fetchone()
            conn.close()
            self.assertEqual(before_event,after_event)
            self.assertEqual(before_attempts,after_attempts)
            self.assertEqual(before_day,after_day)

            repaired=HistoryRepository(db).repair_relationships(force=True)
            self.assertTrue(repaired["ok"],repaired)
            conn=sqlite3.connect(db)
            final_event=conn.execute("SELECT discovery_state,discovery_json,last_discovery_at,last_success_at,next_retry_at,last_error FROM history_catalog_event WHERE canonical_event_key='NBA:evt1'").fetchone()
            final_attempts=conn.execute("SELECT COUNT(*) FROM history_discovery_attempt").fetchone()[0]
            final_day=conn.execute("SELECT discovery_json,discovery_saved_at FROM history_day WHERE date='2026-08-20' AND league='NBA'").fetchone()
            conn.close()
            self.assertEqual(before_event,final_event)
            self.assertEqual(before_attempts,final_attempts)
            self.assertEqual(before_day,final_day)

    def test_preflight_check_only_reports_repairable_drift_without_backup_or_failure(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td); db=state/"cache"/"history.sqlite3"; db.parent.mkdir(parents=True)
            repo=HistoryRepository(db)
            repo.put_scores("2026-08-20","NBA",[{"scoreEventId":"evt1","awayTeam":{"name":"Away"},"homeTeam":{"name":"Home"}}])
            repo.set_catalog_meta("event_association_repair_version",EVENT_MATCHER_VERSION-1)
            proc=subprocess.run(["python3",str(ROOT/"tools/ensure_history_v4.py"),"--state-dir",str(state),"--check-only"],capture_output=True,text=True,check=True)
            data=json.loads(proc.stdout.strip())
            self.assertTrue(data["ok"]); self.assertTrue(data["structuralOk"]); self.assertTrue(data["repairRequired"])
            self.assertFalse(list((state/"backups").glob("*.sqlite3")))

    def test_preflight_recovers_partial_v4_shell_using_preserved_legacy_rows(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td); db=state/"cache"/"history.sqlite3"; db.parent.mkdir(parents=True); now=time.time()
            event={"scoreEventId":"evt1","awayTeam":{"name":"Away Club"},"homeTeam":{"name":"Home Club"},"completed":True}
            conn=sqlite3.connect(db)
            conn.execute("CREATE TABLE history_day(date TEXT,league TEXT,scores_json TEXT,media_json TEXT,discovery_json TEXT,scores_saved_at REAL,media_saved_at REAL,discovery_saved_at REAL,PRIMARY KEY(date,league))")
            conn.execute("CREATE TABLE history_event(date TEXT,league TEXT,event_id TEXT,event_json TEXT,discovery_state TEXT,discovery_json TEXT,last_discovery_at REAL,last_success_at REAL,next_retry_at REAL,last_error TEXT,updated_at REAL,PRIMARY KEY(date,league,event_id))")
            conn.execute("CREATE TABLE history_media_asset(date TEXT,league TEXT,event_id TEXT,asset_key TEXT,asset_json TEXT,validation_state TEXT,verified_at REAL,runtime_state TEXT,runtime_success_at REAL,runtime_failure_at REAL,runtime_failure_reason TEXT,last_seen_at REAL,updated_at REAL,PRIMARY KEY(date,league,event_id,asset_key))")
            item={"youtubeId":"abcdefghijk","scoreEventId":"evt1","title":"Away Club vs Home Club Full Game Highlights","verifiedPlayable":True,"recapTier":"extended"}
            conn.execute("INSERT INTO history_day VALUES(?,?,?,?,?,?,?,?)",("2026-08-20","NBA",json.dumps([event]),json.dumps([item]),"{}",now,now,now))
            conn.execute("INSERT INTO history_event VALUES(?,?,?,?,?,?,?,?,?,?,?)",("2026-08-20","NBA","evt1",json.dumps(event),"VERIFIED","{}",now,now,0,"",now))
            conn.execute("INSERT INTO history_media_asset VALUES(?,?,?,?,?,'VERIFIED',?,'UNKNOWN',0,0,'',?,?)",("2026-08-20","NBA","evt1","yt:abcdefghijk",json.dumps(item),now,now,now)); conn.commit(); conn.close()
            # Reproduce the failed-transition state from production: additive v4
            # schema/meta exists, but normalized source assets were never built.
            repo=HistoryRepository(db)
            self.assertEqual(repo.catalog_integrity()["sourceAssets"],0)
            proc=subprocess.run(["python3",str(ROOT/"tools/ensure_history_v4.py"),"--state-dir",str(state)],capture_output=True,text=True,check=True)
            data=json.loads(proc.stdout.strip())
            self.assertEqual(data["action"],"REBUILT")
            self.assertIn(data["before"]["reason"],{"V4_STRUCTURAL_INVALID_WITH_LEGACY"})
            self.assertTrue(data["rebuild"]["passed"],data)
            rebuilt=HistoryRepository(db)
            self.assertGreaterEqual(rebuilt.catalog_integrity()["sourceAssets"],1)
            self.assertEqual(len(rebuilt.event_media("2026-08-20","NBA","evt1")),1)

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
            migrated=repo.get_event("2026-08-20","NBA","evt1"); self.assertEqual(migrated["lastDiscoveryAt"],0); self.assertEqual(migrated["nextRetryAt"],0)

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
            repo=HistoryRepository(output)
            integrity=repo.association_integrity_summary()
            self.assertEqual(integrity["crossEventAssets"],0)
            self.assertGreaterEqual(integrity["quarantinedLinks"],1)

    def test_launch_and_cloud_paths_enforce_v4_preflight(self):
        for path in (ROOT/"start.sh",ROOT/"START-ANDROID.sh",ROOT/"START SPORTS BIG BOARD.bat",ROOT/"cloud/vm/INSTALL-STAGE1.sh",ROOT/"cloud/gcp/DEPLOY-FROM-GITHUB.sh"):
            self.assertIn("ensure_history_v4.py",path.read_text())
        deploy=(ROOT/"cloud/gcp/DEPLOY-FROM-GITHUB.sh").read_text()
        self.assertIn("MIGRATION_BACKUP",deploy); self.assertIn("Restored pre-deploy history catalog",deploy)



    def test_v410_durable_event_lease_prevents_duplicate_worker_claims(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            event={"scoreEventId":"evt-lease","awayTeam":{"name":"Away Club"},"homeTeam":{"name":"Home Club"},"completed":True}
            repo.upsert_event("2026-08-20","NBA","evt-lease",event)
            key=repo.canonical_event_key("NBA","evt-lease"); now=time.time()
            self.assertTrue(repo.claim_event(key,"green-gap-1",lease_seconds=300,now=now))
            self.assertFalse(repo.claim_event(key,"green-gap-2",lease_seconds=300,now=now+1))
            self.assertEqual(repo.green_gap_events(current_discovery_version=13,now=now+2),[])
            summary=repo.green_gap_summary(current_discovery_version=13,now=now+2)
            self.assertEqual(summary["claimed"],1); self.assertEqual(summary["availableDue"],0)
            claims=repo.active_event_claims(now=now+2); self.assertEqual(claims[0]["owner"],"green-gap-1")
            self.assertTrue(repo.release_event_claim(key,"green-gap-1"))
            self.assertTrue(repo.claim_event(key,"green-gap-2",lease_seconds=300,now=now+3))

    def test_v410_expired_event_lease_is_recoverable_after_worker_crash(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            event={"scoreEventId":"evt-expire","awayTeam":{"name":"Away"},"homeTeam":{"name":"Home"},"completed":True}
            repo.upsert_event("2026-08-19","NFL","evt-expire",event); key=repo.canonical_event_key("NFL","evt-expire"); now=time.time()
            self.assertTrue(repo.claim_event(key,"dead-worker",lease_seconds=30,now=now))
            self.assertTrue(repo.claim_event(key,"replacement-worker",lease_seconds=30,now=now+31))
            self.assertEqual(repo.active_event_claims(now=now+31)[0]["owner"],"replacement-worker")

    def test_v419_source_enrichment_is_versioned_and_newest_first(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            sources={"NFL":[{"key":"nfl-game-highlights","version":1}],"NHL":[{"key":"nhl-official-video","version":1}]}
            recent={"scoreEventId":"nfl-new","awayTeam":{"name":"Jets"},"homeTeam":{"name":"Steelers"},"completed":True}
            older={"scoreEventId":"nhl-old","awayTeam":{"name":"Bruins"},"homeTeam":{"name":"Rangers"},"completed":True}
            repo.put_scores("2026-08-20","NFL",[recent]); repo.put_scores("2025-11-01","NHL",[older])
            rows=repo.source_enrichment_events(sources,floor_date="2025-08-01",today="2026-08-24",now=time.time(),limit=10)
            self.assertEqual(rows[0]["eventId"],"nfl-new"); self.assertEqual(rows[0]["pendingSources"][0]["key"],"nfl-game-highlights")
            repo.mark_source_enrichment("NFL","nfl-new","nfl-game-highlights",1,"COMPLETE",best_before="none",best_after="none")
            rows=repo.source_enrichment_events(sources,floor_date="2025-08-01",today="2026-08-24",now=time.time(),limit=10)
            self.assertEqual([r["eventId"] for r in rows],["nhl-old"])
            # Bumping only one provider version reopens only that provider/event.
            sources["NFL"][0]["version"]=2
            rows=repo.source_enrichment_events(sources,floor_date="2025-08-01",today="2026-08-24",now=time.time(),limit=10)
            self.assertEqual(rows[0]["eventId"],"nfl-new"); self.assertEqual(rows[0]["pendingSources"][0]["version"],2)

    def test_v4110_nfl_green_without_purple_remains_extended_catchup_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            sources={"NFL":[{"key":"nfl-game-highlights","version":2,"objective":"quick"},{"key":"nfl-extended-highlights","version":1,"objective":"extended"}]}
            event={"scoreEventId":"nfl-objectives","awayTeam":{"name":"Las Vegas Raiders"},"homeTeam":{"name":"Houston Texans"},"completed":True}
            repo.put_scores("2026-08-20","NFL",[event])
            green={"youtubeId":"nflquick123","scoreEventId":"nfl-objectives","title":"Las Vegas Raiders vs Houston Texans Game Highlights","durationSeconds":180,"overview":True,"programType":"recap","mediaObjective":"QUICK","verifiedPlayable":True,"validationState":"VERIFIED","historyVerifiedAt":time.time(),"embedValidated":True,"sourceType":"official-nfl-game-highlights","source":"NFL.com"}
            repo.put_event_media("2026-08-20","NFL","nfl-objectives",[green])
            rows=repo.source_enrichment_events(sources,floor_date="2025-08-01",today="2026-08-24",now=time.time(),limit=10)
            self.assertEqual(len(rows),1); self.assertTrue(rows[0]["hasGreen"]); self.assertFalse(rows[0]["hasExtended"])
            self.assertEqual([x["key"] for x in rows[0]["pendingSources"]],["nfl-extended-highlights"])
            objectives=repo.media_objective_summary()
            self.assertEqual(objectives["nflQuickGames"],1); self.assertEqual(objectives["nflExtendedGames"],0); self.assertEqual(objectives["nflGreenWithoutPurple"],1)

    def test_v4111_mls_green_without_extended_remains_rule_catchup_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            sources={"MLS":[{"key":"mls-match-snapshot","version":1,"objective":"quick"},{"key":"mls-match-highlights","version":1,"objective":"extended"}]}
            event={"scoreEventId":"mls-objectives","awayTeam":{"name":"San Diego FC"},"homeTeam":{"name":"Minnesota United FC"},"completed":True}
            repo.put_scores("2026-08-20","MLS",[event])
            green={"youtubeId":"mlssnap123","scoreEventId":"mls-objectives","title":"Match Snapshot: San Diego FC vs Minnesota United FC","durationSeconds":60,"overview":True,"programType":"recap","mediaObjective":"QUICK","recapTier":"green","verifiedPlayable":True,"validationState":"VERIFIED","historyVerifiedAt":time.time(),"embedValidated":True,"sourceType":"official-mls-match-snapshot","source":"MLSsoccer.com"}
            repo.put_event_media("2026-08-20","MLS","mls-objectives",[green])
            rows=repo.source_enrichment_events(sources,floor_date="2025-08-01",today="2026-08-24",now=time.time(),limit=10)
            self.assertEqual(len(rows),1); self.assertTrue(rows[0]["hasGreen"]); self.assertFalse(rows[0]["hasExtended"])
            self.assertEqual([x["key"] for x in rows[0]["pendingSources"]],["mls-match-highlights"])

    def test_v4111_epl_green_without_extended_remains_rule_catchup_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            sources={"EPL":[{"key":"premierleague-official","version":3,"objective":"quick"},{"key":"nbc-epl-extended","version":2,"objective":"extended"}]}
            event={"scoreEventId":"epl-objectives","awayTeam":{"name":"Arsenal"},"homeTeam":{"name":"Liverpool"},"completed":True}
            repo.put_scores("2026-08-20","EPL",[event])
            green={"youtubeId":"eplquick123","scoreEventId":"epl-objectives","title":"Arsenal v Liverpool Match Highlights","durationSeconds":240,"overview":True,"programType":"recap","mediaObjective":"QUICK","recapTier":"green","verifiedPlayable":True,"validationState":"VERIFIED","historyVerifiedAt":time.time(),"embedValidated":True,"sourceType":"official-premierleague-match-highlights","source":"PremierLeague.com"}
            repo.put_event_media("2026-08-20","EPL","epl-objectives",[green])
            rows=repo.source_enrichment_events(sources,floor_date="2025-08-01",today="2026-08-24",now=time.time(),limit=10)
            self.assertEqual(len(rows),1); self.assertEqual([x["key"] for x in rows[0]["pendingSources"]],["nbc-epl-extended"])

    def test_v419_source_enrichment_summary_counts_coverage_and_quality_upgrades(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            sources={"EPL":[{"key":"premierleague-official","version":1},{"key":"nbc-epl-extended","version":1}]}
            event={"scoreEventId":"epl1","awayTeam":{"name":"Away FC"},"homeTeam":{"name":"Home FC"},"completed":True}
            repo.put_scores("2026-08-10","EPL",[event])
            repo.mark_source_enrichment("EPL","epl1","premierleague-official",1,"COMPLETE",best_before="none",best_after="none")
            repo.mark_source_enrichment("EPL","epl1","nbc-epl-extended",1,"COMPLETE",accepted_count=1,best_before="none",best_after="extended",coverage_upgraded=True)
            summary=repo.source_enrichment_summary(sources,floor_date="2025-08-01",today="2026-08-24")
            self.assertEqual(summary["leagues"]["EPL"]["checked"],1); self.assertEqual(summary["remaining"],0)
            self.assertEqual(summary["coverageUpgrades"],1); self.assertEqual(summary["qualityUpgrades"],0)

    def test_v410_silver_summary_exposes_daily_and_weekly_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            repo.put_collection_media("DAY_LEAGUE","NBA","2026-08-20",[{"youtubeId":"daily1234567","title":"NBA Nightly Recap August 20 2026","verifiedPlayable":True,"provider":"YOUTUBE",
                "channelId":"UCWJ2lWNubArHWmf3FIHbfcQ","publishedAt":"2026-08-20T23:00:00Z"}],collection_kind="DAILY_RECAP")
            repo.put_collection_media("WEEK_LEAGUE","NFL","2026-W34",[{"youtubeId":"weekly123456","title":"Every Touchdown from Week 18 | 2025 NFL Season","verifiedPlayable":True,"provider":"YOUTUBE",
                "channelId":"UCDVYQ4Zhbm3S2dlz7P1GBDg","publishedAt":"2026-01-03T23:00:00Z"}],collection_kind="WEEKLY_RECAP")
            summary=repo.silver_summary()
            self.assertEqual(summary["dayCollections"],1); self.assertEqual(summary["weekCollections"],1)
            self.assertEqual(summary["dayAssets"],1); self.assertEqual(summary["weekAssets"],1); self.assertEqual(summary["totalAssets"],2)


    def test_purple_is_coverage_complete_but_remains_quality_upgrade_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            event={"scoreEventId":"soccer-purple","awayTeam":{"name":"Away FC"},"homeTeam":{"name":"Home FC"},"completed":True}
            repo.put_scores("2026-04-18","EPL",[event])
            purple={"youtubeId":"purple12345","title":"Away FC vs Home FC Extended Highlights","durationSeconds":780,"verifiedPlayable":True,"recapTier":"extended","provider":"YOUTUBE"}
            self.assertEqual(repo.put_event_media("2026-04-18","EPL","soccer-purple",[purple]),1)
            repo.set_event_discovery("2026-04-18","EPL","soccer-purple","VERIFIED",{"discoveryVersion":13,"coverageComplete":True,"upgradeEligible":True},retry_at=0)
            summary=repo.green_gap_summary(current_discovery_version=13,now=time.time()+90000,recent_cooldown=1,archive_cooldown=1,recent_cutoff="2026-08-01")
            self.assertEqual(summary["gaps"],0)
            self.assertEqual(summary["coverageComplete"],1)
            self.assertEqual(summary["purpleOnly"],1)
            self.assertEqual(summary["qualityUpgradeDue"],1)
            audit_payload=repo.audit_catalog(league="EPL",current_discovery_version=13)
            audit=audit_payload["rows"][0]
            self.assertEqual(audit["catalogCoverageStatus"],"COVERAGE_COMPLETE")
            self.assertTrue(audit["coverageComplete"]); self.assertTrue(audit["upgradeEligible"])
            self.assertEqual(audit["qualityGapStatus"],"OPTIONAL_QUALITY_UPGRADE")
            self.assertEqual(audit_payload["summary"]["coverageCompleteGames"],1)
            self.assertEqual(audit_payload["summary"]["coverageCompleteByLeague"]["EPL"],{"games":1,"coverageCompleteGames":1})
            # Green-gap scheduling itself is intentionally unchanged: Purple can still
            # be revisited later for a preferred Green/Gold upgrade.
            due=repo.green_gap_events(current_discovery_version=13,now=time.time()+90000,recent_cooldown=1,archive_cooldown=1,recent_cutoff="2026-08-01")
            self.assertEqual(len(due),1); self.assertEqual(due[0]["bestTier"],"extended")

    def test_blue_remains_incomplete_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            event={"scoreEventId":"blue-only","awayTeam":{"name":"Away"},"homeTeam":{"name":"Home"},"completed":True}
            repo.put_scores("2026-04-18","NBA",[event])
            blue={"youtubeId":"blue123456","title":"Away vs Home Game Highlights","durationSeconds":80,"verifiedPlayable":True,"recapTier":"blue","provider":"YOUTUBE"}
            repo.put_event_media("2026-04-18","NBA","blue-only",[blue])
            repo.set_event_discovery("2026-04-18","NBA","blue-only","VERIFIED",{"discoveryVersion":13},retry_at=0)
            summary=repo.green_gap_summary(current_discovery_version=13,now=time.time()+90000,recent_cooldown=1,archive_cooldown=1,recent_cutoff="2026-08-01")
            self.assertEqual(summary["gaps"],1); self.assertEqual(summary["blueOnly"],1); self.assertEqual(summary["coverageComplete"],0)
            audit=repo.audit_catalog(league="NBA",current_discovery_version=13)["rows"][0]
            self.assertEqual(audit["catalogCoverageStatus"],"PLAYABLE_PARTIAL")
            self.assertEqual(audit["qualityGapStatus"],"REQUIRED_COVERAGE_UPGRADE")




    def test_v412_rule_catchup_worker_affinity_prefers_assigned_league(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            sources={
                "NFL":[{"key":"nfl-public-video-quick","version":1,"objective":"quick"}],
                "MLS":[{"key":"mls-match-snapshot","version":2,"objective":"quick"}],
                "EPL":[{"key":"premierleague-official","version":4,"objective":"quick"}],
            }
            for league,event_id in (("NFL","nfl-aff"),("MLS","mls-aff"),("EPL","epl-aff")):
                repo.put_scores("2026-08-20",league,[{"scoreEventId":event_id,"awayTeam":{"name":"Away Club"},"homeTeam":{"name":"Home Club"},"completed":True}])
            rows=repo.source_enrichment_events(sources,floor_date="2025-08-01",today="2026-08-24",now=time.time(),preferred_league="MLS",limit=10)
            self.assertEqual(rows[0]["league"],"MLS")
            self.assertEqual(rows[0]["eventId"],"mls-aff")

    def test_v412_silver_rule_replay_telemetry_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            item={"youtubeId":"daily412xyz","title":"NBA Nightly Recap August 20 2026","verifiedPlayable":True,"provider":"YOUTUBE",
                  "channelId":"UCWJ2lWNubArHWmf3FIHbfcQ","publishedAt":"2026-08-20T23:00:00Z"}
            first=repo.put_collection_media("DAY_LEAGUE","NBA","2026-08-20",[item],collection_kind="DAILY_RECAP",return_stats=True)
            second=repo.put_collection_media("DAY_LEAGUE","NBA","2026-08-20",[item],collection_kind="DAILY_RECAP",return_stats=True)
            self.assertEqual(first["newUniqueAssets"],1); self.assertEqual(first["newCollectionLinks"],1)
            self.assertEqual(second["newUniqueAssets"],0); self.assertEqual(second["existingAssetsReused"],1)
            self.assertEqual(second["newCollectionLinks"],0); self.assertEqual(second["duplicateLinksSuppressed"],1)


class EventAssociationV402Tests(unittest.TestCase):
    def test_matcher_rejects_wrong_matchup_even_with_copied_event_id(self):
        from sbb.event_matcher import match_event
        from sbb.media_scope import annotate
        event={"id":"761748","espnEventId":"761748","awayTeam":{"name":"Philadelphia Union"},"homeTeam":{"name":"Austin FC"}}
        item=annotate({"espnEventId":"761748","scoreEventId":"761748","title":"New York City FC vs. Philadelphia Union - Game Highlights","sourceType":"espn-event-video","provider":"ESPN"},league="MLS",date="2026-08-22",away="Philadelphia Union",home="Austin FC")
        ev=match_event(item,event,league="MLS",date="2026-08-22")
        self.assertNotEqual(ev["associationState"],"ASSIGNED")
        self.assertEqual(ev["associationMethod"],"TITLE_TEAM_PAIR_CONFLICT")

    def test_mlb_explicit_date_disambiguates_consecutive_series_games(self):
        from sbb.event_matcher import match_event
        from sbb.media_scope import annotate
        event={"id":"401816625","awayTeam":{"name":"San Francisco Giants"},"homeTeam":{"name":"Boston Red Sox"}}
        wrong=annotate({"scoreEventId":"401816625","title":"GIANTS vs. RED SOX: Official Full Game Highlights (August 21) | 2026 MLB Season","provider":"YOUTUBE"},league="MLB",date="2026-08-22",away="San Francisco Giants",home="Boston Red Sox")
        ev=match_event(wrong,event,league="MLB",date="2026-08-22")
        self.assertEqual(ev["associationMethod"],"DATE_MISMATCH")
        self.assertNotEqual(ev["associationState"],"ASSIGNED")

    def test_nfl_old_season_club_recap_is_rejected(self):
        from sbb.event_matcher import match_event
        from sbb.media_scope import annotate
        event={"id":"401873296","awayTeam":{"name":"Kansas City Chiefs"},"homeTeam":{"name":"Tampa Bay Buccaneers"}}
        old=annotate({"scoreEventId":"401873296","title":"Chiefs vs. Buccaneers Week 4 Recap | Chiefs Rewind Oct 03, 2022","sourceType":"official-nfl-club-site","provider":"NFL_CLUB"},league="NFL",date="2026-08-22",away="Kansas City Chiefs",home="Tampa Bay Buccaneers")
        ev=match_event(old,event,league="NFL",date="2026-08-22")
        self.assertEqual(ev["associationMethod"],"SEASON_MISMATCH")
        self.assertNotEqual(ev["associationState"],"ASSIGNED")

    def test_repository_enforces_one_asset_one_game(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            e1={"id":"a","awayTeam":{"name":"Alpha Bears"},"homeTeam":{"name":"Beta Hawks"}}
            e2={"id":"b","awayTeam":{"name":"Alpha Bears"},"homeTeam":{"name":"Beta Hawks"}}
            repo.put_scores("2026-08-20","NBA",[e1]); repo.put_scores("2026-08-21","NBA",[e2])
            media={"youtubeId":"same","title":"Alpha Bears vs Beta Hawks Game Highlights","verifiedPlayable":True,"recapTier":"green","provider":"YOUTUBE"}
            self.assertEqual(repo.put_event_media("2026-08-20","NBA","a",[media]),1)
            self.assertEqual(repo.put_event_media("2026-08-21","NBA","b",[media]),0)
            self.assertEqual(repo.event_media("2026-08-20","NBA","a"),[])
            self.assertEqual(repo.event_media("2026-08-21","NBA","b"),[])
            self.assertEqual(repo.association_integrity_summary()["crossEventAssets"],0)

    def test_repair_quarantines_existing_bad_links_without_deleting_source(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            event={"id":"761748","espnEventId":"761748","awayTeam":{"name":"Philadelphia Union"},"homeTeam":{"name":"Austin FC"}}
            repo.put_scores("2026-08-22","MLS",[event])
            # Simulate a pre-v4.1.12 assigned row by directly inserting source/link.
            wrong={"youtubeId":"wrong-espn-like","espnEventId":"761748","scoreEventId":"761748","title":"New York City FC vs. Philadelphia Union - Game Highlights","provider":"ESPN","sourceType":"espn-event-video","verifiedPlayable":False,"recapTier":"green"}
            repo.put_source_media([wrong],league="MLS",date="2026-08-22")
            import sqlite3 as _sqlite3, time as _time, json as _json
            con=_sqlite3.connect(Path(td)/"history.sqlite3")
            key=con.execute("SELECT asset_key FROM history_source_media LIMIT 1").fetchone()[0]
            con.execute("INSERT INTO history_event_media(canonical_event_key,asset_key,association_state,association_confidence,association_method,association_evidence,matcher_version,first_associated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",("MLS:761748",key,"ASSIGNED",1.0,"PROVIDER_EVENT_ID","legacy",4,_time.time(),_time.time()))
            con.commit(); con.close()
            report=repo.repair_event_associations(force=True)
            self.assertGreaterEqual(report["quarantinedLinks"],1)
            self.assertEqual(repo.event_media("2026-08-22","MLS","761748"),[])
            con=_sqlite3.connect(Path(td)/"history.sqlite3")
            self.assertIsNotNone(con.execute("SELECT 1 FROM history_source_media WHERE asset_key=?",(key,)).fetchone()); con.close()

if __name__=='__main__': unittest.main()

if __name__=='__main__': unittest.main()

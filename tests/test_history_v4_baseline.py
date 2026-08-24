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
            # A real v12 attempt happened moments ago. Discovery v13 must still
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


if __name__=='__main__': unittest.main()

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
            # Simulate a pre-v4.0.4 assigned row by directly inserting source/link.
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

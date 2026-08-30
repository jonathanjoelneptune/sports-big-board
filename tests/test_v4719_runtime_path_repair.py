import json
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

# Importing sbb installs the production wrapper order, including v4.7.19 LAST.
from sbb.history_repository import HistoryRepository
from sbb.runtime_path_repair_v4719 import restore_special_event_links, restore_silver_collection_links


class V4719RuntimePathRepairTests(unittest.TestCase):
    def make_repo(self):
        td=tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        return HistoryRepository(Path(td.name)/"history.sqlite3")

    def test_legacy_silver_explicit_playable_proof_survives_candidate_normalization(self):
        repo=self.make_repo(); now=time.time(); date="2026-05-13"
        asset={
            "title":"MLB Daily Recap","provider":"YOUTUBE",
            "externalUrl":"https://www.youtube.com/watch?v=silver123",
            "verifiedPlayable":True,"embedValidated":True,
            "mediaScope":"DAY_LEAGUE","collectionTier":"silver",
            "collectionPeriodKey":date,"collectionKind":"DAILY_RECAP",
        }
        with repo._lock, closing(repo._connect()) as conn:
            key=repo._upsert_source_media_conn(conn,asset,league="MLB",date=date,catalog_state="ASSIGNED")
            # Reproduce a pre-normalization Silver row: explicit old playback proof,
            # but the normalized validation column never got promoted to VERIFIED.
            conn.execute("UPDATE history_source_media SET validation_state='CANDIDATE',runtime_state='UNKNOWN',asset_json=? WHERE asset_key=?",(json.dumps(asset),key))
            ckey=f"DAY_LEAGUE:MLB:{date}:DAILY_RECAP"
            conn.execute("INSERT INTO history_collection(collection_key,scope,league,period_key,collection_kind,title,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (ckey,"DAY_LEAGUE","MLB",date,"DAILY_RECAP","Daily Recap","{}",now,now))
            conn.execute("INSERT INTO history_collection_media(collection_key,asset_key,association_confidence,association_method,association_evidence,classifier_version,rank_hint,first_associated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (ckey,key,1.0,"legacy","legacy",1,10,now,now))
            conn.commit()
        rows=repo.roundup_media(date,"MLB")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].get("youtubeId"),"silver123")
        self.assertTrue(rows[0].get("verifiedPlayable"))
        self.assertTrue(rows[0].get("legacyDatabasePlayable"))

    def test_missing_legacy_silver_collection_edge_is_recreated(self):
        repo=self.make_repo(); now=time.time(); date="2026-05-13"
        item={"title":"MLB Daily Recap","provider":"YOUTUBE","youtubeId":"silver-edge",
              "verifiedPlayable":True,"validationState":"VERIFIED","mediaScope":"DAY_LEAGUE",
              "collectionTier":"silver","displayTier":"silver","collectionPromotionApproved":True,
              "collectionPeriodKey":date,"collectionKind":"DAILY_RECAP","league":"MLB"}
        with repo._lock, closing(repo._connect()) as conn:
            key=repo._upsert_source_media_conn(conn,item,league="MLB",date=date,catalog_state="ASSIGNED")
            conn.execute("UPDATE history_source_media SET scope='DAY_LEAGUE',validation_state='VERIFIED',runtime_state='UNKNOWN',asset_json=? WHERE asset_key=?",(json.dumps(item),key));conn.commit()
        self.assertEqual(repo.roundup_media(date,"MLB"),[])
        result=restore_silver_collection_links(repo)
        self.assertEqual(result["restored"],1)
        rows=repo.roundup_media(date,"MLB")
        self.assertEqual(len(rows),1);self.assertEqual(rows[0].get("youtubeId"),"silver-edge");self.assertTrue(rows[0].get("verifiedPlayable"))

    def test_quarantined_llws_special_proof_is_restored_even_after_scope_demoted_to_other(self):
        repo=self.make_repo(); date="2026-08-25"; league="LLWS2026"; eid="g1"; now=time.time()
        event={"eventId":eid,"id":eid,"date":date,"competitionId":league,
               "awayTeam":{"name":"West Side LL"},"homeTeam":{"name":"Phenix City Youth Baseball LL"}}
        repo.upsert_event(date,league,eid,event)
        item={
            "youtubeId":"llws-proof-video","title":"Ohio vs Alabama | Full Game Highlights | Little League World Series",
            "verifiedPlayable":True,"validationState":"VERIFIED","mediaScope":"GAME",
            "canonicalEventKey":f"{league}:{eid}","associationMethod":"SPECIAL_EVENT_TITLE_ALIAS_PAIR",
            "associationConfidence":0.995,
        }
        with repo._lock, closing(repo._connect()) as conn:
            key=repo._upsert_source_media_conn(conn,item,league=league,date=date,catalog_state="QUARANTINED",quarantine_reason="TITLE_TEAM_PAIR_CONFLICT")
            # Reproduce the destructive generic-repair result that made the live
            # LLWS ribbon say FIND: link quarantined and normalized scope OTHER.
            conn.execute("UPDATE history_source_media SET scope='OTHER',catalog_state='QUARANTINED',quarantine_reason='TITLE_TEAM_PAIR_CONFLICT',asset_json=? WHERE asset_key=?",(json.dumps(item),key))
            conn.execute("INSERT INTO history_event_media(canonical_event_key,asset_key,association_state,association_confidence,association_method,association_evidence,matcher_version,first_associated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (f"{league}:{eid}",key,"QUARANTINED",0.0,"SPECIAL_EVENT_TITLE_ALIAS_PAIR","persisted special proof",4616,now,now))
            conn.commit()
        result=restore_special_event_links(repo)
        status=repo.event_media_link_status(league,eid,key)
        self.assertEqual(result["restored"],1)
        self.assertEqual(result["scopeRecovered"],1)
        self.assertEqual(status["associationState"],"ASSIGNED")
        media=repo.event_media(date,league,eid,include_failed=False)
        self.assertEqual(len(media),1)
        self.assertEqual(media[0]["mediaScope"],"GAME")
        self.assertTrue(media[0]["verifiedPlayable"])

    def test_collection_scope_special_asset_is_not_resurrected_as_game(self):
        repo=self.make_repo(); date="2026-08-25"; league="LLWS2026"; eid="g1"; now=time.time()
        repo.upsert_event(date,league,eid,{"eventId":eid,"date":date,"competitionId":league})
        item={"youtubeId":"silver-not-game","title":"Daily Recap","verifiedPlayable":True,
              "canonicalEventKey":f"{league}:{eid}","associationMethod":"SPECIAL_EVENT_TITLE_ALIAS_PAIR","mediaScope":"DAY_LEAGUE"}
        with repo._lock, closing(repo._connect()) as conn:
            key=repo._upsert_source_media_conn(conn,item,league=league,date=date,catalog_state="QUARANTINED")
            conn.execute("UPDATE history_source_media SET scope='DAY_LEAGUE',asset_json=? WHERE asset_key=?",(json.dumps(item),key))
            conn.execute("INSERT INTO history_event_media(canonical_event_key,asset_key,association_state,association_confidence,association_method,association_evidence,matcher_version,first_associated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (f"{league}:{eid}",key,"QUARANTINED",0.0,"SPECIAL_EVENT_TITLE_ALIAS_PAIR","old proof",4616,now,now))
            conn.commit()
        result=restore_special_event_links(repo)
        self.assertEqual(result["restored"],0)
        self.assertEqual(result["scopeRejected"],1)

    def test_runtime_module_owns_cfb_day_state_invalidation(self):
        src=(Path(__file__).resolve().parents[1]/"sbb/runtime_path_repair_v4719.py").read_text(encoding="utf-8")
        self.assertIn("_ORIGINAL_CFB_PERSIST",src)
        self.assertIn("_invalidate_day_state([date])",src)
        self.assertIn("-tDiPDHU2fs",src)
        self.assertIn("scan_recent_missing",src)


if __name__=="__main__":
    unittest.main()

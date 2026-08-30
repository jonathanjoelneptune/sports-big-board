import json
import tempfile
import time
import unittest
from pathlib import Path

from sbb import day_state
from sbb.cfb_trusted_youtube import KNOWN_MEDIA_HINTS, _cache_fresh, trusted_results
from sbb.history_repository import HistoryRepository


class _RejectingMatcherServer:
    @staticmethod
    def _history_media_match_evidence(item, event):
        return ({**item, "mediaScope": "OTHER"}, {"associationState": "QUARANTINED"})


class _HintServer:
    @staticmethod
    def read_youtube_key():
        return ""

    @staticmethod
    def _youtube_match_strength(title, desc, away, home):
        text=f"{title} {desc}".lower()
        return 2 if ("usc" in text and ("san jose state" in text or "sjsu" in text)) else 0


class V4718RegressionRecoveryTests(unittest.TestCase):
    def test_special_event_proven_relationship_survives_generic_read_guard(self):
        plans={
            "LLWS2026:g1":{
                "league":"LLWS2026","date":"2026-08-25","event":{
                    "eventId":"g1","date":"2026-08-25","competitionId":"LLWS2026"
                },
                "playable":[{
                    "youtubeId":"llws-proof-video","verifiedPlayable":True,"mediaScope":"GAME",
                    "canonicalEventKey":"LLWS2026:g1",
                    "associationMethod":"SPECIAL_EVENT_TITLE_ALIAS_PAIR",
                }],
                "media":[],
            }
        }
        out,stats=day_state._sanitize_event_plans(_RejectingMatcherServer(),plans)
        self.assertEqual(len(out["LLWS2026:g1"]["playable"]),1)
        self.assertEqual(stats["specialProofAccepted"],1)
        self.assertEqual(stats["rejected"],0)

    def test_ordinary_stale_relationship_still_fails_closed(self):
        plans={"MLB:g1":{"league":"MLB","date":"2026-08-25","event":{"eventId":"g1"},
            "playable":[{"youtubeId":"bad","verifiedPlayable":True,"mediaScope":"GAME","canonicalEventKey":"MLB:g1","associationMethod":"TITLE_TEAM_PAIR"}],"media":[]}}
        out,stats=day_state._sanitize_event_plans(_RejectingMatcherServer(),plans)
        self.assertEqual(out["MLB:g1"]["playable"],[])
        self.assertEqual(stats["rejected"],1)

    def test_silver_youtube_external_url_recovers_playable_transport(self):
        with tempfile.TemporaryDirectory() as td:
            repo=HistoryRepository(Path(td)/"history.sqlite3")
            now=time.time()
            asset={"title":"Daily Recap","externalUrl":"https://www.youtube.com/watch?v=silver123",
                   "mediaScope":"DAY_LEAGUE","collectionTier":"silver","collectionPeriodKey":"2026-05-13"}
            with repo._lock, repo._connect() as conn:
                key=repo._upsert_source_media_conn(conn,asset,league="MLB",date="2026-05-13")
                conn.execute("UPDATE history_source_media SET provider='YOUTUBE',validation_state='VERIFIED',runtime_state='UNKNOWN',asset_json=? WHERE asset_key=?",
                             (json.dumps(asset),key))
                conn.execute("INSERT INTO history_collection(collection_key,scope,league,period_key,collection_kind,title,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                             ("DAY_LEAGUE:MLB:2026-05-13:DAILY_RECAP","DAY_LEAGUE","MLB","2026-05-13","DAILY_RECAP","Daily Recap","{}",now,now))
                conn.execute("INSERT INTO history_collection_media(collection_key,asset_key,association_confidence,association_method,association_evidence,classifier_version,rank_hint,first_associated_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                             ("DAY_LEAGUE:MLB:2026-05-13:DAILY_RECAP",key,1.0,"test","test",1,10,now,now))
                conn.commit()
            rows=repo.roundup_media("2026-05-13","MLB")
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0].get("youtubeId"),"silver123")
            self.assertTrue(rows[0].get("verifiedPlayable"))
            self.assertTrue(rows[0].get("databaseVerifiedPlayable"))

    def test_known_usc_hint_works_without_youtube_search_quota(self):
        self.assertTrue(any(x.get("youtubeId")=="-tDiPDHU2fs" for x in KNOWN_MEDIA_HINTS))
        rows=trusted_results(_HintServer(),"2026-08-29","San Jose State Spartans","USC Trojans")
        self.assertEqual(rows[0]["youtubeId"],"-tDiPDHU2fs")
        self.assertEqual(rows[0]["recapTier"],"extended")

    def test_empty_and_recent_cfb_day_catalogs_do_not_get_month_long_ttl(self):
        from sbb import cfb_trusted_youtube as cfb
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"cache.json"
            path.write_text(json.dumps({"savedAt":time.time()-cfb.EMPTY_CATALOG_TTL_SECONDS-1,"data":[]}),encoding="utf-8")
            self.assertFalse(_cache_fresh(path,time.strftime("%Y-%m-%d")))


if __name__=="__main__":
    unittest.main()

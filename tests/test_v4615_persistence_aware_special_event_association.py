import tempfile
import unittest
from pathlib import Path

from sbb.event_matcher import match_event
from sbb.history_repository import HistoryRepository
import sbb.competition_builder_v4615 as v4615

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
INDEX=(ROOT/"index.html").read_text(encoding="utf-8")
BACKEND=(ROOT/"sbb"/"competition_builder_v4615.py").read_text(encoding="utf-8")
INIT=(ROOT/"sbb"/"__init__.py").read_text(encoding="utf-8")
CERT=(ROOT/"foundation-certification.json").read_text(encoding="utf-8")


class V4615PersistenceAwareSpecialEventAssociationTests(unittest.TestCase):
    def event(self,event_id="g1"):
        return {
            "eventId":event_id,
            "id":event_id,
            "date":"2026-08-25",
            "awayTeam":{
                "name":"West Side LL",
                "displayName":"West Side LL",
                "group":"Great Lakes Region",
                "abbreviation":"GL",
                "aliases":["Hamilton, Ohio","Hamilton, OH","Great Lakes Region"],
            },
            "homeTeam":{
                "name":"Phenix City Youth Baseball LL",
                "displayName":"Phenix City Youth Baseball LL",
                "group":"Southeast Region",
                "abbreviation":"SE",
                "aliases":["Phenix City, Alabama","Phenix City, AL","Southeast Region"],
            },
        }

    def proof_item(self,event_id="g1",canonical_key="LLWS2026:g1"):
        proof={
            "schema":1,
            "producer":"SBB_SPECIAL_EVENT_MATCHER",
            "proofVersion":"4.6.15",
            "associationState":"ASSIGNED",
            "associationMethod":"SPECIAL_EVENT_TITLE_ALIAS_PAIR",
            "associationConfidence":0.995,
            "associationResolution":"UNIQUE_PAIR",
            "league":"LLWS2026",
            "eventId":event_id,
            "canonicalEventKey":canonical_key,
            "titleAlias1":"Ohio",
            "titleAlias1Source":"LOCATION_TAIL",
            "titleAlias2":"Alabama",
            "titleAlias2Source":"LOCATION_TAIL",
            "titlePairOrder":"NORMAL",
            "titlePairScore":200,
            "titleFingerprint":v4615._title_fingerprint(
                "Ohio vs Alabama | Full Game Highlights | Little League World Series"
            ),
        }
        return {
            "youtubeId":"proof-video-1",
            "title":"Ohio vs Alabama | Full Game Highlights | Little League World Series",
            "verifiedPlayable":True,
            "mediaScope":"GAME",
            "recapTier":"extended",
            "league":"LLWS2026",
            "competitionId":"LLWS2026",
            "eventId":event_id,
            "matchId":event_id,
            "scoreEventId":event_id,
            "canonicalEventId":event_id,
            "canonicalEventKey":canonical_key,
            "date":"2026-08-25",
            "officialPlaylistId":"PLJBIB5zsrIC8",
            "sbbPreprovenAssociation":proof,
        }

    def repo(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo=HistoryRepository(Path(tmp.name)/"history.sqlite")
        event=self.event()
        repo.upsert_event("2026-08-25","LLWS2026","g1",event)
        return repo

    def test_legacy_matcher_rejects_geographic_title_against_club_names(self):
        ev=self.event()
        raw=self.proof_item()
        legacy=dict(raw)
        legacy.pop("sbbPreprovenAssociation",None)
        evidence=match_event(legacy,ev,league="LLWS2026",date="2026-08-25")
        self.assertEqual(evidence["associationState"],"QUARANTINED")
        self.assertEqual(evidence["associationMethod"],"TITLE_TEAM_PAIR_CONFLICT")

    def test_trusted_special_event_proof_persists_as_assigned(self):
        repo=self.repo()
        added=v4615._put_event_media_v4615(
            repo,"2026-08-25","LLWS2026","g1",[self.proof_item()]
        )
        self.assertEqual(added,1)
        asset_key=repo.asset_key_for(self.proof_item())
        status=repo.event_media_link_status("LLWS2026","g1",asset_key)
        self.assertEqual(status["associationState"],"ASSIGNED")
        self.assertEqual(status["associationMethod"],"SPECIAL_EVENT_TITLE_ALIAS_PAIR")
        self.assertEqual(status["quarantineReason"],"")

    def test_existing_title_team_pair_quarantine_is_released_after_exact_reproof(self):
        repo=self.repo()
        ordinary=self.proof_item()
        ordinary.pop("sbbPreprovenAssociation",None)
        ordinary.pop("associationMethod",None)
        ordinary.pop("associationConfidence",None)
        self.assertEqual(
            v4615._ORIGINAL_PUT_EVENT_MEDIA(
                repo,"2026-08-25","LLWS2026","g1",[ordinary]
            ),
            0,
        )
        asset_key=repo.asset_key_for(ordinary)
        before=repo.event_media_link_status("LLWS2026","g1",asset_key)
        self.assertEqual(before["associationState"],"QUARANTINED")
        self.assertEqual(before["associationMethod"],"TITLE_TEAM_PAIR_CONFLICT")

        added=v4615._put_event_media_v4615(
            repo,"2026-08-25","LLWS2026","g1",[self.proof_item()]
        )
        self.assertEqual(added,1)
        after=repo.event_media_link_status("LLWS2026","g1",asset_key)
        self.assertEqual(after["associationState"],"ASSIGNED")
        self.assertEqual(after["quarantineReason"],"")

    def test_mismatched_canonical_key_cannot_bypass_legacy_matcher(self):
        repo=self.repo()
        raw=self.proof_item(canonical_key="LLWS2026:WRONG")
        raw["canonicalEventKey"]="LLWS2026:WRONG"
        added=v4615._put_event_media_v4615(
            repo,"2026-08-25","LLWS2026","g1",[raw]
        )
        self.assertEqual(added,0)
        asset_key=repo.asset_key_for(raw)
        status=repo.event_media_link_status("LLWS2026","g1",asset_key)
        self.assertEqual(status["associationState"],"QUARANTINED")

    def test_proven_asset_cannot_steal_an_existing_different_assignment(self):
        repo=self.repo()
        event2=self.event("g2")
        repo.upsert_event("2026-08-25","LLWS2026","g2",event2)

        # Strong provider-id assignment to g2 exists first.
        existing=self.proof_item("g2","LLWS2026:g2")
        existing.pop("sbbPreprovenAssociation",None)
        existing["eventId"]="g2"
        existing["matchId"]="g2"
        existing["scoreEventId"]="g2"
        existing["canonicalEventId"]="g2"
        existing["espnEventId"]="g2"
        existing["youtubeId"]="shared-video"
        # This first link must be independently valid under the legacy matcher.
        existing["title"]="West Side LL vs Phenix City Youth Baseball LL | Full Game Highlights"
        event2["espnEventId"]="g2"
        repo.upsert_event("2026-08-25","LLWS2026","g2",event2)
        self.assertEqual(
            v4615._ORIGINAL_PUT_EVENT_MEDIA(
                repo,"2026-08-25","LLWS2026","g2",[existing]
            ),
            1,
        )

        candidate=self.proof_item()
        candidate["youtubeId"]="shared-video"
        candidate["sbbPreprovenAssociation"]["titleFingerprint"]=v4615._title_fingerprint(candidate["title"])
        added=v4615._put_event_media_v4615(
            repo,"2026-08-25","LLWS2026","g1",[candidate]
        )
        self.assertEqual(added,0)
        asset_key=repo.asset_key_for(candidate)
        target=repo.event_media_link_status("LLWS2026","g1",asset_key)
        existing_status=repo.event_media_link_status("LLWS2026","g2",asset_key)
        self.assertEqual(target["associationState"],"QUARANTINED")
        self.assertEqual(existing_status["associationState"],"ASSIGNED")

    def test_relationship_repair_restores_still_valid_preproven_link(self):
        repo=self.repo()
        raw=self.proof_item()
        self.assertEqual(
            v4615._put_event_media_v4615(
                repo,"2026-08-25","LLWS2026","g1",[raw]
            ),
            1,
        )
        result=v4615._repair_event_associations_v4615(repo,force=True)
        asset_key=repo.asset_key_for(raw)
        status=repo.event_media_link_status("LLWS2026","g1",asset_key)
        self.assertEqual(status["associationState"],"ASSIGNED")
        self.assertGreaterEqual(result["preprovenChecked"],1)

    def test_release_contract(self):
        self.assertIn(f"Sports Big Board — v{VERSION}",INDEX)
        self.assertIn("competition_builder_v4615",INIT)
        self.assertIn("_install_competition_builder_v4615()",INIT)
        self.assertIn("sbbPreprovenAssociation",BACKEND)
        self.assertIn("SBB_SPECIAL_EVENT_MATCHER",BACKEND)
        self.assertIn("Persistence accepts a deterministic special-event proof",CERT)


if __name__=="__main__":
    unittest.main()

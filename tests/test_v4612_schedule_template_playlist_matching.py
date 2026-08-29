import unittest
from pathlib import Path

import sbb.competition_builder as base
import sbb.competition_builder_v4612 as v4612

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
INDEX=(ROOT/"index.html").read_text(encoding="utf-8")
UI=(ROOT/"architecture"/"competition-builder-v4612.js").read_text(encoding="utf-8")
BACKEND=(ROOT/"sbb"/"competition_builder_v4612.py").read_text(encoding="utf-8")
INIT=(ROOT/"sbb"/"__init__.py").read_text(encoding="utf-8")
CERT=(ROOT/"foundation-certification.json").read_text(encoding="utf-8")


class V4612ScheduleTemplatePlaylistMatchingTests(unittest.TestCase):
    def test_generic_schedule_template_copy_contract(self):
        self.assertIn(f"architecture/competition-builder-v4612.js?v={VERSION}",INDEX)
        self.assertIn("COPY TEMPLATE JSON",UI)
        self.assertIn("GENERIC_SCHEDULE_TEMPLATE",UI)
        self.assertIn("providerEventId",UI)
        self.assertIn("espnEventId",UI)
        self.assertIn("aliases",UI)
        self.assertIn("group",UI)
        self.assertIn("gameNumber",UI)
        self.assertIn("sourceUrl",UI)
        self.assertNotIn('"eventId": "SPORTS_BIG_BOARD',UI)

    def test_playlist_title_rule_fields_are_reusable(self):
        self.assertIn("cbGreenRequiredTitlePhrases",UI)
        self.assertIn("cbPurpleRequiredTitlePhrases",UI)
        self.assertIn("cbBlueRequiredTitlePhrases",UI)
        self.assertIn("historyMediaPlaylistRequiredTitlePhrases",UI)
        self.assertIn("historyMediaPlaylistExcludedTitlePhrases",UI)
        self.assertIn("/api/competition-builder/media-rules",UI)
        self.assertIn("Full Game Highlights",UI)

    def test_title_rules_accept_full_game_and_reject_nonmatching_clips(self):
        comp={"mediaSources":{"green":[{
            "url":"https://www.youtube.com/playlist?list=PLTEST123456",
            "requiredTitlePhrases":["Full Game Highlights"],
            "excludedTitlePhrases":["Top Plays"],
        }]}}
        ok,_=v4612._title_rule_allows(comp,{"title":"Team A vs Team B | Full Game Highlights"})
        self.assertTrue(ok)
        ok,detail=v4612._title_rule_allows(comp,{"title":"Team A vs Team B | Top Plays"})
        self.assertFalse(ok)
        self.assertIn(detail["reason"],{"EXCLUDED_TITLE_PHRASE","REQUIRED_TITLE_PHRASE_MISSING"})

    def test_participant_aliases_include_group_and_media_names(self):
        names=v4612._participant_aliases({
            "name":"South Carolina","displayName":"South Carolina","group":"Southeast",
            "abbreviation":"SC","aliases":["South Carolina Little League","Southeast"]
        })
        self.assertIn("South Carolina",names)
        self.assertIn("Southeast",names)
        self.assertIn("SC",names)
        self.assertIn("South Carolina Little League",names)

    def test_imported_participant_objects_preserve_alias_metadata(self):
        comp=base.normalize_definition({
            "id":"GENERIC26","name":"Generic Event","type":"SPECIAL_EVENT","sportId":"baseball",
            "startDate":"2026-08-01","endDate":"2026-08-02"
        })
        event=base.normalize_event(comp,{
            "date":"2026-08-01","scheduledAt":"2026-08-01T13:00:00-04:00",
            "away":{"name":"State A","group":"Region A","aliases":["Region A","Team Alpha"]},
            "home":{"name":"State B","group":"Region B","aliases":["Region B","Team Beta"]},
            "status":"FINAL","awayScore":5,"homeScore":3,
            "providerEventId":"provider-123","gameNumber":1,"city":"Example City","country":"USA"
        })
        self.assertEqual(event["awayTeam"]["group"],"Region A")
        self.assertIn("Team Alpha",event["awayTeam"]["aliases"])
        self.assertEqual(event["providerEventId"],"provider-123")
        self.assertEqual(event["gameNumber"],1)
        self.assertEqual(event["city"],"Example City")

    def test_backend_installs_persistent_media_rule_and_alias_matcher(self):
        self.assertIn("competition_builder_v4612",INIT)
        self.assertIn("_install_competition_builder_v4612()",INIT)
        self.assertIn("def _wrap_server_matcher",BACKEND)
        self.assertIn("PLAYLIST_TITLE_RULE",BACKEND)
        self.assertIn("participantAliasMatch",BACKEND)
        self.assertIn("def _update_media_rules",BACKEND)
        self.assertIn("force_crawl=True",BACKEND)

    def test_certification_carries_v4612_contract(self):
        self.assertIn("COPY TEMPLATE JSON",CERT)
        self.assertIn("required/excluded playlist title phrases",CERT)
        self.assertIn("participant aliases",CERT)


if __name__=="__main__":
    unittest.main()

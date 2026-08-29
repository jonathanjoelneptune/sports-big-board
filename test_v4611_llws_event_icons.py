import unittest
from pathlib import Path

import sbb.competition_builder as base
import sbb.competition_builder_v467 as v467

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")
UI = (ROOT / "architecture" / "competition-builder-v4611.js").read_text(encoding="utf-8")
BUILDER = (ROOT / "architecture" / "competition-builder.js").read_text(encoding="utf-8")
CERT = (ROOT / "foundation-certification.json").read_text(encoding="utf-8")


class _Server:
    ESPN_SITE_API = "https://site.api.espn.com/apis/site/v2/sports"
    def __init__(self, payload):
        self.payload = payload
        self.urls = []
    def _espn_fetch_json(self, url, timeout=10):
        self.urls.append(url)
        return self.payload


class V4611LLWSEventIconTests(unittest.TestCase):
    def test_event_icon_selector_and_dropdown_contract(self):
        self.assertIn(f"architecture/competition-builder-v4611.js?v={VERSION}", INDEX)
        self.assertIn("cbEventIcon", UI)
        self.assertIn("EVENT ICON", UI)
        self.assertIn("⚾", UI)
        self.assertIn("⚽", UI)
        self.assertIn("🏆", UI)
        self.assertIn("eventIcon", UI)
        self.assertIn("sbb-special-event-icon", UI)
        self.assertIn("competitionMap", UI)

    def test_llws_template_is_complete_and_provider_ready(self):
        self.assertIn("kind === 'LLWS'", UI)
        self.assertIn("LLWS2026", BUILDER)
        self.assertIn("2026 Little League Baseball World Series", BUILDER)
        self.assertIn("2026-08-19", BUILDER)
        self.assertIn("2026-08-30", BUILDER)
        self.assertIn("cbExpectedEvents').value='38'", BUILDER)
        self.assertIn("littleleague.org/world-series/2026/llbws", BUILDER)
        self.assertIn("providerLeagueSlug = clean(d.providerLeagueSlug) || 'llb'", UI)
        self.assertIn("gameCenterProfile = clean(d.gameCenterProfile) || 'baseball'", UI)

    def test_event_icon_survives_backend_definition_normalization(self):
        row = base.normalize_definition({
            "id":"LLWS2026","name":"2026 Little League Baseball World Series","shortName":"LLWS",
            "type":"SPECIAL_EVENT","sportId":"baseball","startDate":"2026-08-19","endDate":"2026-08-30",
            "eventIcon":"⚾","expectedEventCount":38,
        })
        self.assertEqual(row["eventIcon"], "⚾")

    def test_llws_espn_provider_mapping(self):
        comp={"id":"LLWS2026","name":"2026 Little League Baseball World Series","shortName":"LLWS","sportId":"baseball"}
        self.assertEqual(v467._espn_provider_for_comp(comp), ("baseball","llb","baseball"))
        self.assertEqual(v467._espn_slug_for_comp(comp), "llb")
        self.assertEqual(v467._espn_sport_for_comp(comp), "baseball")

    def test_llws_scoreboard_uses_baseball_llb_and_realized_teams(self):
        payload={"events":[{
            "id":"401999999","date":"2026-08-24T17:00:00Z",
            "competitions":[{
                "competitors":[
                    {"homeAway":"away","score":"3","team":{"displayName":"Canada Region"}},
                    {"homeAway":"home","score":"2","team":{"displayName":"Panama Region"}},
                ],
                "status":{"type":{"completed":True,"state":"post","shortDetail":"Final"}},
                "venue":{"fullName":"Volunteer Stadium"},
            }]
        }]}
        server=_Server(payload)
        comp={"id":"LLWS2026","name":"2026 Little League Baseball World Series","shortName":"LLWS","sportId":"baseball"}
        rows=v467._espn_scoreboard_rows(server,comp,"2026-08-24","2026-08-24")
        self.assertEqual(len(rows),1)
        self.assertIn("/baseball/llb/scoreboard",server.urls[0])
        self.assertEqual(rows[0]["away"],"Canada Region")
        self.assertEqual(rows[0]["home"],"Panama Region")
        self.assertEqual(rows[0]["status"],"FINAL")
        self.assertEqual(rows[0]["providerSport"],"baseball")

    def test_llws_game_center_uses_standard_baseball_shape(self):
        payload={
            "header":{"competitions":[{
                "date":"2026-08-24T17:00:00Z",
                "status":{"type":{"completed":True,"state":"post","shortDetail":"Final"}},
                "venue":{"fullName":"Volunteer Stadium"},
                "competitors":[
                    {"homeAway":"away","score":"3","team":{"id":"1","displayName":"Canada Region","abbreviation":"CAN"},"linescores":[{"value":1},{"value":0},{"value":2}]},
                    {"homeAway":"home","score":"2","team":{"id":"2","displayName":"Panama Region","abbreviation":"PAN"},"linescores":[{"value":0},{"value":2},{"value":0}]},
                ]
            }]},
            "boxscore":{"teams":[
                {"team":{"id":"1","displayName":"Canada Region"},"statistics":[{"name":"hits","label":"Hits","displayValue":"7"}]},
                {"team":{"id":"2","displayName":"Panama Region"},"statistics":[{"name":"hits","label":"Hits","displayValue":"5"}]},
            ]},
            "plays":[{"id":"p1","period":{"number":1},"text":"Canada scored","scoringPlay":True,"awayScore":1,"homeScore":0}],
        }
        server=_Server(payload)
        comp={"id":"LLWS2026","name":"2026 Little League Baseball World Series","shortName":"LLWS","sportId":"baseball"}
        event={"eventId":"canonical-24","espnEventId":"401999999","date":"2026-08-24","awayTeam":{"name":"Canada Region"},"homeTeam":{"name":"Panama Region"},"status":"FINAL"}
        data=v467.provider_game_center(server,comp,event)
        self.assertIn("/baseball/llb/summary?event=401999999",server.urls[0])
        self.assertEqual(data["competitionId"],"LLWS2026")
        self.assertEqual(data["eventId"],"canonical-24")
        self.assertEqual(data["event"]["sportId"],"baseball")
        self.assertEqual(data["event"]["eventKind"],"game")
        self.assertEqual(len(data["scoreboard"]["innings"]),3)
        self.assertGreaterEqual(len(data["teamStats"]),1)
        self.assertGreaterEqual(len(data["scoringPlays"]),1)

    def test_certification_carries_llws_and_icon_reuse_contract(self):
        self.assertIn("Event Icon selector beside Sport", CERT)
        self.assertIn("ESPN league slug llb", CERT)
        self.assertIn("standard baseball Game Center structure", CERT)
        self.assertIn("historical database-first hydration", CERT)


if __name__ == "__main__":
    unittest.main()

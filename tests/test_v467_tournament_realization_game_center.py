import unittest
from unittest.mock import patch

import sbb.competition_builder as cb
import sbb.competition_builder_v467 as v467


class _Server:
    ESPN_SITE_API = "https://site.api.espn.com/apis/site/v2/sports"

    def __init__(self, payload):
        self.payload = payload

    def _espn_fetch_json(self, url, timeout=10):
        if "summary?event=" in url:
            return self.payload
        return {"events": []}


def _comp():
    return {
        "id": "WC2026",
        "name": "2026 FIFA World Cup",
        "shortName": "WORLD CUP",
        "type": "SPECIAL_EVENT",
        "sportId": "football",
        "startDate": "2026-06-11",
        "endDate": "2026-07-19",
        "logoStrategy": "COUNTRY_FLAGS",
        "events": [],
    }


class V467TournamentRealizationGameCenterTests(unittest.TestCase):
    def test_world_cup_uses_espn_fifa_world(self):
        self.assertEqual(v467._espn_slug_for_comp(_comp()), "fifa.world")

    def test_future_placeholder_is_refreshable_without_being_guessed(self):
        event = {
            "date": "2026-07-10",
            "away": "Winner Match 95",
            "home": "Winner Match 96",
            "status": "SCHEDULED",
        }
        self.assertTrue(v467._needs_realized_refresh(event, today="2026-07-01"))

    def test_realized_match_replaces_bracket_but_preserves_canonical_id(self):
        comp = _comp()
        comp["events"] = [cb.normalize_event(comp, {
            "eventId": "canonical-slot-95",
            "date": "2026-07-10",
            "scheduledAt": "2026-07-10T19:00:00Z",
            "away": "Winner Match 95",
            "home": "Winner Match 96",
            "status": "SCHEDULED",
            "venue": "Test Stadium",
            "round": "Quarterfinal",
        }, 0)]
        realized = [{
            "eventId": "760999",
            "providerEventId": "760999",
            "espnEventId": "760999",
            "date": "2026-07-10",
            "scheduledAt": "2026-07-10T19:00:00Z",
            "away": "Spain",
            "home": "Argentina",
            "awayScore": "1",
            "homeScore": "2",
            "status": "FINAL",
            "venue": "Test Stadium",
            "round": "Quarterfinal",
            "stage": "Quarterfinal",
            "sourceUrl": "https://www.espn.com/",
        }]
        updated, changed, matched = v467._merge_realized_results(comp, realized, {"canonical-slot-95"})
        self.assertEqual(changed, 1)
        self.assertEqual(matched, ["canonical-slot-95"])
        self.assertEqual(updated[0]["eventId"], "canonical-slot-95")
        self.assertEqual(updated[0]["espnEventId"], "760999")
        self.assertEqual(updated[0]["awayTeam"]["name"], "Spain")
        self.assertEqual(updated[0]["homeTeam"]["name"], "Argentina")
        self.assertEqual(updated[0]["awayScore"], "1")
        self.assertEqual(updated[0]["homeScore"], "2")

    def test_world_cup_game_center_uses_standard_soccer_sections(self):
        payload = {
            "header": {
                "competitions": [{
                    "date": "2026-06-12T19:00:00Z",
                    "status": {"type": {"state": "post", "completed": True, "shortDetail": "FT"}},
                    "venue": {"fullName": "Test Stadium"},
                    "competitors": [
                        {"homeAway": "away", "score": "2", "team": {"id": "1", "displayName": "Spain", "abbreviation": "ESP"}},
                        {"homeAway": "home", "score": "1", "team": {"id": "2", "displayName": "Argentina", "abbreviation": "ARG"}},
                    ],
                }]
            },
            "boxscore": {
                "teams": [
                    {"team": {"id": "1", "displayName": "Spain", "abbreviation": "ESP"},
                     "statistics": [
                         {"name": "possessionPct", "label": "Possession", "displayValue": "56%"},
                         {"name": "shots", "label": "Shots", "displayValue": "14"},
                         {"name": "shotsOnTarget", "label": "Shots on Goal", "displayValue": "6"},
                     ]},
                    {"team": {"id": "2", "displayName": "Argentina", "abbreviation": "ARG"},
                     "statistics": [
                         {"name": "possessionPct", "label": "Possession", "displayValue": "44%"},
                         {"name": "shots", "label": "Shots", "displayValue": "10"},
                         {"name": "shotsOnTarget", "label": "Shots on Goal", "displayValue": "4"},
                     ]},
                ]
            },
            "rosters": [
                {"team": {"id": "1", "displayName": "Spain", "abbreviation": "ESP"},
                 "roster": [{"athlete": {"displayName": "Player A", "position": {"abbreviation": "F"}}, "starter": True}]},
                {"team": {"id": "2", "displayName": "Argentina", "abbreviation": "ARG"},
                 "roster": [{"athlete": {"displayName": "Player B", "position": {"abbreviation": "F"}}, "starter": True}]},
            ],
            "keyEvents": [
                {"id": "k1", "period": {"number": 1}, "clock": {"displayValue": "12'"}, "text": "Spain goal", "type": {"text": "Goal"}},
                {"id": "k2", "period": {"number": 1}, "clock": {"displayValue": "28'"}, "text": "Argentina yellow card", "type": {"text": "Yellow Card"}},
                {"id": "k3", "period": {"number": 2}, "clock": {"displayValue": "70'"}, "text": "Spain substitution", "type": {"text": "Substitution"}},
            ],
        }
        comp = _comp()
        event = cb.normalize_event(comp, {
            "eventId": "canonical-1",
            "espnEventId": "760414",
            "date": "2026-06-12",
            "away": "Spain",
            "home": "Argentina",
            "awayScore": "2",
            "homeScore": "1",
            "status": "FINAL",
        }, 0)
        data = v467.soccer_game_center(_Server(payload), comp, event)
        self.assertEqual(data["competitionId"], "WC2026")
        self.assertEqual(data["eventId"], "canonical-1")
        self.assertEqual(data["providerEventId"], "760414")
        self.assertGreaterEqual(len(data["teamStats"]), 3)
        self.assertGreaterEqual(len(data["playerStatSections"]), 2)
        self.assertGreaterEqual(len(data["timeline"]), 3)
        self.assertGreaterEqual(len(data["scoringPlays"]), 1)
        self.assertTrue(data["coverage"]["complete"])
        self.assertEqual(data["event"]["sportId"], "football")

    def test_discovery_prompt_requires_actual_past_teams_and_resolved_future_teams(self):
        draft = _comp()
        text = v467._window_prompt_v467(draft, "2026-06-11", "2026-06-18", [], 104)
        self.assertIn("ACTUAL teams/countries", text)
        self.assertIn("future match", text)
        self.assertIn("genuinely unresolved", text)


if __name__ == "__main__":
    unittest.main()

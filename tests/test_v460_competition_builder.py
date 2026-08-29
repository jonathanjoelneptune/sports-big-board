import json
import unittest
from pathlib import Path
from sbb.competition_builder import lifecycle,main_row,normalize_definition,normalize_event,parse_schedule_text,generic_game_center

ROOT=Path(__file__).resolve().parents[1]

class V460CompetitionBuilderTests(unittest.TestCase):
    def test_special_event_lifecycle_and_selector_placement(self):
        base={"id":"EVENT26","name":"Event 2026","type":"SPECIAL_EVENT","sportId":"football","startDate":"2026-08-19","endDate":"2026-08-30"}
        c=normalize_definition(base)
        self.assertEqual(lifecycle(c,"2026-08-28"),"ACTIVE")
        self.assertTrue(main_row(c,"2026-08-28"))
        self.assertEqual(lifecycle(c,"2026-09-01"),"COMPLETED")
        self.assertFalse(main_row(c,"2026-09-01"))
        league=normalize_definition({**base,"id":"NEWLEAGUE","type":"LEAGUE"})
        self.assertTrue(main_row(league,"2026-09-01"))

    def test_schedule_normalizes_for_score_ribbon_and_game_center(self):
        c=normalize_definition({"id":"LLWS2026","name":"2026 LLWS","type":"SPECIAL_EVENT","sportId":"baseball","startDate":"2026-08-19","endDate":"2026-08-30"})
        e=normalize_event(c,{"eventId":"35","date":"2026-08-29","away":"Curaçao Region","home":"Japan Region","awayScore":"","homeScore":"","status":"SCHEDULED","round":"International Championship"},0)
        self.assertEqual(e["competitionId"],"LLWS2026")
        self.assertEqual(e["participants"][0]["side"],"away")
        gc=generic_game_center(c,e)
        self.assertEqual(gc["competitionId"],"LLWS2026")
        self.assertEqual(gc["scoreboard"]["away"]["team"]["name"],"Curaçao Region")
        self.assertTrue(gc["coverage"]["scoreboard"])

    def test_json_and_csv_schedule_input(self):
        self.assertEqual(len(parse_schedule_text('[{"date":"2026-01-01","away":"A","home":"B"}]')),1)
        csv_text="date,away,home,status\n2026-01-01,A,B,FINAL\n"
        self.assertEqual(parse_schedule_text(csv_text)[0]["away"],"A")

    def test_frontend_contracts_are_present(self):
        src=(ROOT/"architecture/competition-builder.js").read_text(encoding="utf-8")
        # Runtime Competition Builder capabilities belong to the module.
        for token in ("ADD LEAGUE","ADD SPECIAL EVENT","mainRowEligible","/api/competition-builder","/api/competition-builder/media","SCORE_DATE_STORE?.setMedia","2026 WORLD CUP TEMPLATE","2026 LLWS TEMPLATE"):
            self.assertIn(token,src)

        # v4.6.3 made Special Events a permanent application-owned header control.
        # The builder now populates that stable control instead of manufacturing
        # the entire dropdown at runtime.
        index=(ROOT/"index.html").read_text(encoding="utf-8")
        self.assertIn("SPECIAL EVENTS ▾",index)
        self.assertIn('id="sbbSpecialEventsWrap"',index)
        self.assertIn('id="sbbSpecialEventsBtn"',index)
        self.assertIn('id="sbbSpecialEventsMenu"',index)
        self.assertIn("sbbSpecialEventsWrap",src)
        self.assertIn("menu.innerHTML=''",src)

        version=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
        self.assertIn(f"architecture/competition-builder.js?v={version}",index)
        self.assertLess(index.index(f"app.js?v={version}"),index.index(f"competition-builder.js?v={version}"))

    def test_backend_openai_and_game_center_contracts(self):
        src=(ROOT/"sbb/competition_builder.py").read_text(encoding="utf-8")
        for token in ('web_search','/api/events/([^/]+)/([^/]+)/game-center','_operator_media_playlist_normalize','HISTORY_REPOSITORY.upsert_event','AUTO_DISCOVER','_generic_youtube_gap_search'):
            self.assertIn(token,src)

if __name__=="__main__":
    unittest.main()

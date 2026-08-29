import unittest
import sbb.competition_builder_v467 as v467

class _Server:
    ESPN_SITE_API="https://site.api.espn.com/apis/site/v2/sports"
    def __init__(self,payload): self.payload=payload
    def _espn_fetch_json(self,url,timeout=10): return self.payload

class V469WorldCupRibbonPlaybackTests(unittest.TestCase):
    def test_ft_is_normalized_to_final_for_ribbon_playback(self):
        row=v467._normalize_completed_soccer_event({
            "eventId":"wc-slot","date":"2026-07-15",
            "awayScore":"2","homeScore":"1","status":"FT"
        },today="2026-08-29")
        self.assertEqual(row["status"],"FINAL")
        self.assertEqual(row["state"],"FINAL")
        self.assertEqual(row["providerStatus"],"FT")
        self.assertTrue(row["providerCompleted"])

    def test_stale_past_scheduled_result_is_normalized_to_final(self):
        row=v467._normalize_completed_soccer_event({
            "date":"2026-07-15","awayScore":"2","homeScore":"1","status":"SCHEDULED"
        },today="2026-08-29")
        self.assertEqual(row["status"],"FINAL")

    def test_live_or_today_match_is_not_forced_final(self):
        row=v467._normalize_completed_soccer_event({
            "date":"2026-08-29","awayScore":"1","homeScore":"1","status":"IN PROGRESS"
        },today="2026-08-29")
        self.assertEqual(row["status"],"IN PROGRESS")
        self.assertFalse(row.get("providerCompleted",False))

    def test_completed_espn_soccer_row_uses_canonical_final_status(self):
        payload={"events":[{
            "id":"401999","date":"2026-07-15T20:00:00Z",
            "competitions":[{
                "competitors":[
                    {"homeAway":"away","score":"2","team":{"displayName":"Argentina"}},
                    {"homeAway":"home","score":"1","team":{"displayName":"England"}}
                ],
                "status":{"type":{"completed":True,"state":"post","shortDetail":"FT"}}
            }]
        }]}
        comp={"id":"WC2026","name":"2026 FIFA World Cup","sportId":"football"}
        rows=v467._espn_scoreboard_rows(_Server(payload),comp,"2026-07-15","2026-07-15")
        self.assertEqual(rows[0]["status"],"FINAL")
        self.assertEqual(rows[0]["providerStatus"],"FT")
        self.assertTrue(rows[0]["providerCompleted"])

    def test_stale_completed_rows_are_revisited(self):
        base={"date":"2026-07-15","awayScore":"2","homeScore":"1","away":"Argentina","home":"England"}
        self.assertTrue(v467._needs_realized_refresh({**base,"status":"FT"},today="2026-08-29"))
        self.assertTrue(v467._needs_realized_refresh({**base,"status":"SCHEDULED"},today="2026-08-29"))
        self.assertFalse(v467._needs_realized_refresh({**base,"status":"FINAL"},today="2026-08-29"))

if __name__=="__main__":
    unittest.main()

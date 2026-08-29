import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")
FRONTEND = (ROOT / "architecture" / "historical-media-v4610.js").read_text(encoding="utf-8")
BACKEND = (ROOT / "sbb" / "historical_media_v4610.py").read_text(encoding="utf-8")
INIT = (ROOT / "sbb" / "__init__.py").read_text(encoding="utf-8")
CERT = (ROOT / "foundation-certification.json").read_text(encoding="utf-8")

class V4610HistoricalMediaAssociationTests(unittest.TestCase):
    def test_database_first_browser_barrier(self):
        self.assertIn("architecture/historical-media-v4610.js?v=4.6.10", INDEX)
        self.assertIn("checking database media associations before search", FRONTEND)
        self.assertIn("await hydrateHistoricalRibbonFromCatalog(date)", FRONTEND)
        self.assertIn("state.deferredFill.add(date)", FRONTEND)
        self.assertIn("await barrier.promise", FRONTEND)
        self.assertIn("DB ASSOCIATION", FRONTEND)

    def test_backend_alias_and_date_repair_contract(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS history_event_alias", BACKEND)
        self.assertIn('"DATE_TEAMS_TIME"', BACKEND)
        self.assertIn("def repair_date_associations", BACKEND)
        self.assertIn("s.scope='GAME'", BACKEND)
        self.assertIn("match_event(working, event, league=league, date=target)", BACKEND)
        self.assertIn("result[alias_key] = result[canonical_key]", BACKEND)

    def test_service_is_installed_in_normal_sbb_boot(self):
        self.assertIn("historical_media_v4610", INIT)
        self.assertIn("_install_historical_media_v4610()", INIT)

    def test_schedule_alias_preserves_canonical_event_in_real_repository(self):
        from sbb.history_repository import HistoryRepository
        with tempfile.TemporaryDirectory() as tmp:
            repo=HistoryRepository(Path(tmp)/"history.sqlite3")
            date="2026-06-13"
            first={"id":"mlb-old-id","eventId":"mlb-old-id","date":date+"T19:10:00Z","awayTeam":{"name":"New York Yankees"},"homeTeam":{"name":"Boston Red Sox"},"status":"FINAL"}
            changed={"id":"provider-new-id","eventId":"provider-new-id","date":date+"T19:10:00Z","awayTeam":{"name":"New York Yankees"},"homeTeam":{"name":"Boston Red Sox"},"status":"FINAL"}
            repo.put_scores(date,"MLB",[first]);repo.put_scores(date,"MLB",[changed])
            resolved=repo.get_event(date,"MLB","provider-new-id")
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved["canonicalEventKey"],"MLB:mlb-old-id")

    def test_certification_carries_historical_hardening(self):
        self.assertIn("Historical score-ribbon dates remain database-first", CERT)
        self.assertIn("Schedule/provider event-id changes", CERT)
        self.assertIn("Historical date switching is generation-safe", CERT)

if __name__ == "__main__": unittest.main()

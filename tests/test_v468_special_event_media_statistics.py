import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")
AUDIT = (ROOT / "ui" / "history-audit-v468.js").read_text(encoding="utf-8")
TOURNAMENT = (ROOT / "sbb" / "competition_builder_v467.py").read_text(encoding="utf-8")
CERT = (ROOT / "foundation-certification.json").read_text(encoding="utf-8")


class V468SpecialEventMediaStatisticsTests(unittest.TestCase):
    def test_statistics_tab_is_a_first_class_audit_surface(self):
        self.assertIn('id="historyAuditTabStatistics"', INDEX)
        self.assertIn('id="historyStatisticsPane"', INDEX)
        self.assertIn('id="historyStatisticsBody"', INDEX)
        self.assertIn(f'ui/history-audit-v468.js?v={VERSION}', INDEX)
        self.assertIn("loadStatistics", AUDIT)
        self.assertIn("coverageCompleteGames", AUDIT)
        self.assertIn("noVerifiedMediaGames", AUDIT)

    def test_dynamic_competition_selectors_include_special_events(self):
        self.assertIn("/api/competition-builder/catalog", AUDIT)
        self.assertIn("historyMediaSourcesLeague", AUDIT)
        self.assertIn("historyMediaPlaylistLeague", AUDIT)
        self.assertIn("historyAuditLeague", AUDIT)
        self.assertIn("historySilverLeague", AUDIT)
        self.assertIn("historyRecoveryLeague", AUDIT)
        self.assertNotIn("const leagueOrder=['MLB','NFL','NBA','NHL','EPL','MLS']", AUDIT)

    def test_per_competition_reprocess_reopens_and_recrawls_media(self):
        self.assertIn("data-v468-reprocess", AUDIT)
        self.assertIn("action:'source_reopen'", AUDIT)
        self.assertIn("/api/history/admin/recovery/preview", AUDIT)
        self.assertIn("/api/history/admin/recovery/apply", AUDIT)
        self.assertIn("action:'crawl'", AUDIT)
        self.assertIn("/api/competition-builder/health?id=", AUDIT)
        self.assertIn("Existing discovered media will be preserved", AUDIT)

    def test_realized_tournament_identity_triggers_playlist_recrawl(self):
        self.assertIn("if changed:", TOURNAMENT)
        self.assertIn("base._register_media_sources(server, current, force_crawl=True)", TOURNAMENT)
        self.assertIn("Winner Match/TBA identities", TOURNAMENT)

    def test_certification_keeps_v468_operator_contract(self):
        self.assertIn("History Audit exposes a Statistics tab", CERT)
        self.assertIn("Special-event media reprocessing force-crawls every enabled operator playlist", CERT)
        self.assertIn("registered competition playlists are force-crawled again automatically", CERT)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path
from sbb.nfl_weekly_playlists import weekly_title_info,is_weekly_recap_title
from sbb.media_classifier import tier

class V448NFLWeeklyPlaylistTests(unittest.TestCase):
    def test_frontend_reconciles_recent_purple_only_nfl_before_click(self):
        root=Path(__file__).resolve().parents[1]
        js=(root/'architecture'/'nfl-recap-reconciliation.js').read_text(encoding='utf-8')
        self.assertIn("rapidHistoricalGameMedia(match,{force:true})",js)
        self.assertIn("!ts.has('green')",js)
        self.assertIn("ts.has('extended')||ts.has('blue')",js)
        self.assertIn("renderScoresFromMatchesCombined(false)",js)
    def test_preseason_current_shape(self):
        x=weekly_title_info("2026 Preseason Week 3 Game Recaps")
        self.assertEqual((x["year"],x["phase"],x["week"]),(2026,"preseason",3))
    def test_future_preseason_shape(self):
        x=weekly_title_info("2026 Preseason Week 4 Game Recaps")
        self.assertEqual((x["year"],x["phase"],x["week"]),(2026,"preseason",4))
    def test_regular_season_shapes(self):
        for title in ("2026 Season Week 1 Game Recaps","2026 Regular Season Week 12 Game Recaps","Week 8 - 2026 Season Game Recaps"):
            self.assertTrue(is_weekly_recap_title(title),title)
            self.assertIsNotNone(weekly_title_info(title),title)
    def test_server_classifier_uses_physical_duration_before_objective(self):
        self.assertEqual(tier({"overview":True,"programType":"recap","title":"Game Highlights","durationSeconds":600,"mediaObjective":"QUICK"}),"extended")
        self.assertEqual(tier({"overview":True,"programType":"recap","title":"Game Recap","durationSeconds":210,"mediaObjective":"EXTENDED"}),"green")
    def test_current_week_playlist_items_bypass_archive_cache(self):
        root=Path(__file__).resolve().parents[1]
        src=(root/'sbb'/'nfl_weekly_playlists.py').read_text(encoding='utf-8')
        self.assertIn('PLAYLIST_ITEMS_REFRESH_SECONDS = 10 * 60',src)
        self.assertIn('original_items(playlist,force=use_force)',src)
        self.assertIn('refresh_weekly=',src)
    def test_non_recap_playlist_rejected(self):
        self.assertFalse(is_weekly_recap_title("2026 Week 3 Top Plays"))
        self.assertFalse(is_weekly_recap_title("NFL Mic'd Up Week 3"))
if __name__=="__main__":unittest.main()

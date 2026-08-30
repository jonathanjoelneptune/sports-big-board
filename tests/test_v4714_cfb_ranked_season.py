import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'sbb'/'cfb_ranked.py').read_text(encoding='utf-8')
CORE=(ROOT/'core-model.js').read_text(encoding='utf-8')
DAY=(ROOT/'sbb'/'day_state.py').read_text(encoding='utf-8')

class V4714CfbRankedSeasonTests(unittest.TestCase):
    def test_cfb_is_first_class_persistent_league(self):
        self.assertIn("CFB:{id:'CFB'",CORE)
        self.assertIn("scoreProvider:'cfb-ranked'",CORE)
        self.assertIn("seasonId:'CFB2026'",CORE)
        self.assertIn("rankingSnapshotPolicy:'IMMUTABLE_WEEKLY'",CORE)
    def test_weekly_membership_rule_is_ranked_either_participant(self):
        self.assertIn("if not away_rank and not home_rank:continue",SRC)
        self.assertIn("selectionRule':'AP_TOP_25_EITHER_PARTICIPANT'",SRC)
        self.assertIn("ranked-v-ranked matchup is one event",SRC)
    def test_archived_rank_snapshot_is_immutable(self):
        self.assertIn("Immutable weekly archive",SRC)
        self.assertIn("parsed=existing",SRC)
        self.assertIn("rankingFrozen':True",SRC)
        self.assertIn("rankingSnapshotId':f'{SEASON_ID}:AP:{week}'",SRC)
    def test_future_weeks_are_not_projected_using_old_rankings(self):
        self.assertIn("never project a future week's games from the previous week's rankings",SRC)
        self.assertIn("materialize a week only after its AP snapshot is known",SRC)
    def test_playlist_is_purple_extended_source(self):
        self.assertIn("PLPydJJjt7Pb4",SRC)
        self.assertIn("'purple':[{",SRC)
        self.assertIn("titleIncludePhrase':'full game highlights'",SRC)
    def test_day_state_installs_service(self):
        self.assertIn("from . import cfb_ranked as _cfb_ranked",DAY)
        self.assertIn("_cfb_ranked.install()",DAY)

if __name__=='__main__':unittest.main()

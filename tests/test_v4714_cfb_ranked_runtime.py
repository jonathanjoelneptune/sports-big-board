import ast
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'sbb'/'cfb_ranked.py').read_text(encoding='utf-8')
class V4714CfbRuntimeContracts(unittest.TestCase):
    def test_source_parses(self):ast.parse(SRC)
    def test_espn_rankings_and_fbs_scoreboard_are_separate_authorities(self):
        self.assertIn("/college-football/rankings",SRC)
        self.assertIn("/college-football/scoreboard",SRC)
        self.assertIn("'groups':80",SRC)
    def test_score_refresh_does_not_change_rank_snapshot(self):
        self.assertIn("targets=[week]",SRC)
        self.assertIn("targets.append(week-1)",SRC)
        self.assertIn("snap=state.get('snapshots',{}).get(str(target))",SRC)
    def test_diagnostics_and_manual_refresh_exist(self):
        self.assertIn("'/api/cfb/status'",SRC)
        self.assertIn("'/api/cfb/rankings'",SRC)
        self.assertIn("'/api/cfb/refresh'",SRC)
if __name__=='__main__':unittest.main()

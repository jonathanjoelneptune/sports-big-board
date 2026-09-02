from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class V5119ArchitectureTests(unittest.TestCase):
    def text(self,rel): return (ROOT/rel).read_text(encoding='utf-8')

    def test_release_identity(self):
        self.assertEqual(self.text('VERSION').strip(),'5.1.19')
        self.assertIn('Sports Big Board — v5.1.19',self.text('index.html'))
        self.assertIn("version:'5.1.19'",self.text('core-model.js'))

    def test_one_frontend_tennis_authority(self):
        index=self.text('index.html')
        self.assertEqual(index.count('architecture/tennis-presentation.js?v=5.1.19'),1)
        self.assertNotIn('tennis-presentation-v5117.js?v=',index)
        self.assertNotIn('tennis-presentation-v5118.js?v=',index)
        tennis=self.text('architecture/tennis-presentation.js')
        for forbidden in ('fetch(','.setMatches(','setInterval('): self.assertNotIn(forbidden,tennis)
        self.assertIn("['round','rnd','main draw']",tennis)
        self.assertIn('.score-team-abbr',tennis)
        self.assertIn('compactName(full,rankOf(team))',tennis)

    def test_v5118_competing_date_paths_retired(self):
        index=self.text('index.html')
        self.assertNotIn('score-date-stability-v5118.js?v=',index)
        self.assertNotIn('day-state-browser-cache-v5118.js?v=',index)
        init=self.text('sbb/__init__.py')
        self.assertNotIn('_install_day_state_fast_path_v5118',init)
        fast=self.text('sbb/day_state_fast_path_v5118.py')
        self.assertNotIn('/api/day-state/fast',fast)
        self.assertIn('return False',fast)

    def test_score_store_owns_non_regression_directly(self):
        src=self.text('architecture/score-date-store.js')
        self.assertIn("version:'1.1'",src)
        self.assertIn("architectureVersion:'1.3-v5119'",src)
        self.assertIn('meta.scoreOnly===true',src)
        self.assertIn('meta.thin===true',src)
        self.assertIn('blockedEmptyReplacements',src)
        self.assertIn('mergeRows(prior,next)',src)
        self.assertNotIn('localStorage',src)

    def test_tennis_backend_is_selected_match_only(self):
        src=self.text('sbb/tennis_game_center.py')
        self.assertIn('competition_registry as registry',src)
        self.assertIn('TENNIS_CANONICAL',src)
        self.assertIn('"providerFetches":False',src)
        self.assertIn('"warming":False',src)
        self.assertNotIn('_warm_competition_date',src)
        self.assertNotIn('_active_tennis_prewarm_worker',src)
        self.assertEqual(src.count('\ndef install():'),1)
        self.assertEqual(src.count('\ndef peek_tennis_game_center('),1)

    def test_retired_frontend_files_are_inert(self):
        for rel in ('architecture/score-date-stability-v5118.js','architecture/day-state-browser-cache-v5118.js','architecture/tennis-presentation-v5118.js','architecture/tennis-presentation-v5117.js'):
            src=self.text(rel)
            for forbidden in ('fetch(','.setMatches(','setInterval('): self.assertNotIn(forbidden,src,rel)

if __name__=='__main__': unittest.main()

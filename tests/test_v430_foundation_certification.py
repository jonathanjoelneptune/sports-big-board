import json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
class V431FoundationCertificationTests(unittest.TestCase):
    def test_release_identity_and_three_tier_manifest(self):
        self.assertEqual(VERSION,'4.3.1')
        m=json.loads((ROOT/'foundation-certification.json').read_text())
        self.assertEqual(m['schemaVersion'],2);self.assertEqual(m['release'],VERSION);self.assertTrue(m['allThreeTiersRequired'])
        self.assertGreaterEqual(m['tiers']['tier2']['minimumDurationMs'],900000)
        for tier in ('tier1','tier2','tier3'): self.assertTrue(m['tiers'][tier]['required'])
    def test_index_wires_certification_before_soundtrack_and_app(self):
        html=(ROOT/'index.html').read_text();chain=[f'architecture/milestone-console.js?v={VERSION}',f'architecture/foundation-certification.js?v={VERSION}',f'architecture/site-soundtrack.js?v={VERSION}',f'app.js?v={VERSION}'];pos=[html.index(x) for x in chain];self.assertEqual(pos,sorted(pos))
    def test_full_certification_requires_all_three_tiers(self):
        js=(ROOT/'architecture/foundation-certification.js').read_text()
        for token in ('runTier1','runTier2','runTier3','runFull','runSoakTest','runChaosTest','allThreeRequired:true',"status:all&&recovered?'FOUNDATION_CERTIFIED':'IN_PROGRESS'"): self.assertIn(token,js)
    def test_milestone_exposes_three_tier_runtime(self):
        js=(ROOT/'architecture/milestone-console.js').read_text()
        for token in ("version:'1.3'",'runStressTest','runSoakTest','runChaosTest','regression-hardening'): self.assertIn(token,js)
    def test_static_verification_enforces_contract(self):
        verify=(ROOT/'VERIFY.sh').read_text();self.assertIn('tools/check_foundation_certification.py',verify)
if __name__=='__main__':unittest.main()

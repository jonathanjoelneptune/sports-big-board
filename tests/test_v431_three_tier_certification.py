import json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class V431ThreeTierCertificationTests(unittest.TestCase):
    def test_three_tiers_are_blocking(self):
        m=json.loads((ROOT/'foundation-certification.json').read_text())
        self.assertTrue(m['allThreeTiersRequired']);self.assertEqual(set(m['tiers']),{'tier1','tier2','tier3'})
        self.assertGreaterEqual(m['tiers']['tier2']['minimumDurationMs'],15*60*1000)
    def test_tier1_has_reported_bug_regressions(self):
        req=' '.join(json.loads((ROOT/'foundation-certification.json').read_text())['tiers']['tier1']['reportedRegressionRequirements']).lower()
        for term in ('game center','restart','manual pause','roundup','demo'):self.assertIn(term,req)
    def test_tier2_and_tier3_runners_exist(self):
        js=(ROOT/'architecture/milestone-console.js').read_text()
        for token in ('async function runSoakTest','async function runChaosTest','same-media restart detected','aborted request storm','standby disruption','resource-mode turbulence'):self.assertIn(token,js)
    def test_only_all_three_plus_recovery_can_certify(self):
        js=(ROOT/'architecture/foundation-certification.js').read_text()
        self.assertIn("const tiers=[tierEvidence.tier1,tierEvidence.tier2,tierEvidence.tier3]",js)
        self.assertIn("all&&recovered?'FOUNDATION_CERTIFIED':'IN_PROGRESS'",js)
if __name__=='__main__':unittest.main()

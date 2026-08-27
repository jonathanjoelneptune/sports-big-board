import json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CERT=(ROOT/'architecture/foundation-certification.js').read_text(encoding='utf-8')
MILESTONE=(ROOT/'architecture/milestone-console.js').read_text(encoding='utf-8')
class V438CertificationErrorEvidenceTests(unittest.TestCase):
    def test_error_evidence_is_exported_not_just_counted(self):
        for token in ('collectErrorEvidence','actionableErrors','recoveredAdvisories','diagnosticMismatch','problems:snap?.problems','recentErrors:errors.recentErrors','browser:errors.browser'):
            self.assertIn(token,CERT)
    def test_count_only_error_cannot_independently_fail_tier(self):
        self.assertIn("errors.actionableErrors.length===0",CERT)
        self.assertIn('count-only error cannot block without an exported record',CERT)
    def test_recovered_media_advisory_requires_recovery_proof(self):
        self.assertIn('transientMediaInterruption',CERT);self.assertIn('laterPlaybackRecovery',CERT)
        self.assertIn("String(latest?.state||'')!=='playing'",CERT)
        self.assertIn("String(step?.status)==='PASS'",CERT)
    def test_browser_identity_is_captured_with_errors(self):
        for token in ('function browserRuntime()','browser:browserRuntime()','normalizedLevel===\'ERROR\'','userAgent','browserBrands','platform'):
            self.assertIn(token,MILESTONE)
        self.assertIn("version:'1.3'",MILESTONE)
    def test_verify_executes_behavioral_error_evidence_test(self):
        verify=(ROOT/'VERIFY.sh').read_text(encoding='utf-8')
        self.assertIn('node tests/test_certification_error_evidence.js',verify)
    def test_manifest_documents_error_evidence_contract(self):
        m=json.loads((ROOT/'foundation-certification.json').read_text())
        self.assertEqual(m['release'],(ROOT/'VERSION').read_text().strip())
        text=' '.join(m['tiers']['tier1']['reportedRegressionRequirements'])
        self.assertIn('exported',text);self.assertIn('count-only',text);self.assertIn('RECOVERED_ADVISORY',text)
if __name__=='__main__': unittest.main()

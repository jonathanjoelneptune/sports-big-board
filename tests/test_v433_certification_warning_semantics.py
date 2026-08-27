import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CERT=(ROOT/'architecture'/'foundation-certification.js').read_text(encoding='utf-8')
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()


class V433CertificationWarningSemanticsTests(unittest.TestCase):
    def test_release_retains_v433_warning_semantics_or_newer(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split('.'))), (4,3,3))

    def test_tier3_allows_advisory_warn_without_allowing_fail(self):
        self.assertIn("allowWarnings=false", CERT)
        self.assertIn("new Set(['PASS','WARN'])", CERT)
        self.assertIn("runStatus==='PASS'||(allowWarnings&&runStatus==='WARN')", CERT)
        self.assertIn("tierRunEvidence('tier3','Tier 3 chaos',run,0,{allowWarnings:true})", CERT)
        self.assertIn("tierRunEvidence('tier2','Tier 2 soak',run,SOAK_MS-2000)", CERT)

    def test_tier3_certificate_surfaces_warnings_instead_of_hiding_them(self):
        self.assertIn("`${id}-warnings`", CERT)
        self.assertIn("advisory warnings", CERT)
        self.assertIn("warningCount:warnings.length", CERT)
        self.assertIn("no failed evidence", CERT)


if __name__=='__main__':
    unittest.main()

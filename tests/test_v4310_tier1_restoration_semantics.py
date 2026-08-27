from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
MILESTONE=(ROOT/'architecture/milestone-console.js').read_text(encoding='utf-8')
CERT=(ROOT/'architecture/foundation-certification.js').read_text(encoding='utf-8')
MANIFEST=(ROOT/'foundation-certification.json').read_text(encoding='utf-8')

class Tier1RestorationSemanticsTests(unittest.TestCase):
    def test_exact_restore_failures_are_advisories_not_automatic_stress_failure(self):
        self.assertIn("stressRun.restoration=[]", MILESTONE)
        self.assertIn("status:'ADVISORY'", MILESTONE)
        self.assertIn("post('stress-restore','WARN'", MILESTONE)
        self.assertNotIn("restoreFailed||statuses.includes('FAIL')", MILESTONE)
        self.assertNotIn("if(restoreFailed&&stressRun.status!=='FAIL')", MILESTONE)

    def test_final_health_not_exact_snapshot_controls_restore_failure(self):
        for token in (
            "stressRun.restorationHealth={ok:healthProblems.length===0",
            "resource mode ${postRestoreMode||'unknown'} != ${original.resourceMode}",
            "playback invariant ${postRestorePlayback.invariant}",
            "soundtrack audioElementCount=${postRestoreSoundtrack.audioElementCount}",
            "started board has no selected media",
            "Game Center does not match active game media after cleanup",
            "post-test restoration left application unhealthy",
        ):
            self.assertIn(token, MILESTONE)
        self.assertIn("stressRun.status=healthProblems.length||statuses.includes('FAIL')?'FAIL'", MILESTONE)

    def test_tier1_uses_evidence_and_post_restore_health(self):
        self.assertIn("const evidenceStressOk=steps.length>0&&bad.length===0&&proceduresOk&&restoreHealth?.ok===true", CERT)
        self.assertIn("gate('post-test-health','Post-test application health'", CERT)
        self.assertIn("gate('restore-advisories','Exact pre-test state restoration',true", CERT)
        self.assertIn("PASS by evidence", CERT)

    def test_manifest_documents_nonblocking_exact_restore(self):
        self.assertIn('Post-test exact-state restoration is advisory unless final application health is bad', MANIFEST)

if __name__=='__main__':
    unittest.main()

"""R19 known-candidate repair regression guards."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
AUDIT=(ROOT/'media_audit_service.py').read_text(encoding='utf-8')
UI=(ROOT/'ui/media-audit-v550.js').read_text(encoding='utf-8')

class R19KnownCandidateRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.block=AUDIT[AUDIT.index('def _repair_by_discovery'):AUDIT.index('@staticmethod',AUDIT.index('def _repair_by_discovery'))]

    def test_known_candidates_are_recertified_before_new_discovery(self):
        self.assertLess(self.block.index('_eligible_known_candidates(before,target,tested)'),self.block.index('_deep_catalog_candidates'))
        self.assertIn("phase='RECERTIFY_KNOWN_CANDIDATE'",self.block)
        self.assertIn("target=='PREFERRED'",AUDIT[AUDIT.index('def _eligible_known_candidates'):AUDIT.index('def _probe',AUDIT.index('def _eligible_known_candidates'))])

    def test_one_repair_attempt_does_not_reprobe_same_transport(self):
        cert=AUDIT[AUDIT.index('def _certify_candidates'):AUDIT.index('def _recertify_existing')]
        self.assertIn('if key and key in tested: continue',cert)
        self.assertIn('tested.add(key)',cert)

    def test_changed_known_transport_can_be_retried_once(self):
        self.assertIn('new_sig!=old_sig and key in tested',self.block)
        self.assertIn('tested.discard(key)',self.block)
        self.assertIn('knownTransportRefreshes',self.block)

    def test_r19_requeues_prior_waiting_jobs_once(self):
        self.assertIn('R19_KNOWN_CANDIDATE_RECERTIFICATION',AUDIT)
        self.assertIn('R19 known-candidate recertification strategy upgrade: immediate one-time retry',AUDIT)

    def test_operator_telemetry_exposes_eligible_known(self):
        self.assertIn('sourceEligibleKnown',UI)
        self.assertIn('eligible known',UI)

if __name__=='__main__':
    unittest.main()

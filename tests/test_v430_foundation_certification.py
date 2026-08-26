import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()

REQUIRED_PROCEDURES = [
    'release-handshake', 'playback-cycle', 'historical-read', 'operator-load',
    'resource-modes', 'game-center', 'soundtrack', 'ui-responsiveness',
]
REQUIRED_GATES = [
    'release-handshake', 'stress-suite', 'procedure-suite', 'step-debt',
    'platform-checks', 'clean-window-errors', 'playback-invariant', 'worker-health',
    'state-restore', 'legacy-read-isolation',
]


class V430FoundationCertificationTests(unittest.TestCase):
    def test_release_identity_and_manifest_scope(self):
        self.assertEqual(VERSION, '4.3.0')
        manifest = json.loads((ROOT / 'foundation-certification.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['release'], VERSION)
        self.assertEqual(manifest['certifiesBaseline'], '4.2.2')
        self.assertEqual(manifest['requiredProcedures'], REQUIRED_PROCEDURES)
        self.assertEqual(manifest['blockingGates'], REQUIRED_GATES)
        self.assertFalse(manifest['durableCatalogMutation'])
        self.assertFalse(manifest['requiresCatalogRebuild'])
        self.assertFalse(manifest['requiresSoundtrackUpload'])

    def test_index_wires_certification_between_milestone_and_runtime(self):
        html = (ROOT / 'index.html').read_text(encoding='utf-8')
        milestone = f'architecture/milestone-console.js?v={VERSION}'
        cert = f'architecture/foundation-certification.js?v={VERSION}'
        soundtrack = f'architecture/site-soundtrack.js?v={VERSION}'
        app = f'app.js?v={VERSION}'
        self.assertLess(html.index(milestone), html.index(cert))
        self.assertLess(html.index(cert), html.index(soundtrack))
        self.assertLess(html.index(soundtrack), html.index(app))
        for token in ('Foundation Certification Console', 'OPEN 4.3 CERTIFICATION CONSOLE', '4.3 Foundation Certification Console'):
            self.assertIn(token, html)

    def test_certification_starts_a_clean_window_before_running_existing_stress(self):
        js = (ROOT / 'architecture' / 'foundation-certification.js').read_text(encoding='utf-8')
        self.assertIn('await M.reset()', js)
        self.assertIn('await M.runStressTest()', js)
        self.assertLess(js.index('await M.reset()'), js.index('await M.runStressTest()'))
        self.assertIn('M.procedureResults', js)
        self.assertIn("snap?.api?.['/api/history/day']", js)
        self.assertIn('cleanWindow:true', js)
        self.assertIn("status:ok?'CERTIFIED':'NOT_CERTIFIED'", js)

    def test_certification_runtime_keeps_exact_procedure_and_gate_contracts(self):
        js = (ROOT / 'architecture' / 'foundation-certification.js').read_text(encoding='utf-8')
        for procedure in REQUIRED_PROCEDURES:
            self.assertIn(procedure, js)
        for gate in REQUIRED_GATES:
            self.assertIn(f"gate('{gate}'", js)

    def test_milestone_console_exposes_only_needed_certification_hooks(self):
        js = (ROOT / 'architecture' / 'milestone-console.js').read_text(encoding='utf-8')
        self.assertIn("version:'1.2'", js)
        self.assertIn('refresh,reset,text:textSnapshot', js)
        self.assertIn('get procedureResults(){return safe(procedureResults);}', js)
        self.assertIn('runStressTest', js)
        self.assertIn('runProcedure', js)

    def test_static_verification_enforces_certification_contract(self):
        verify = (ROOT / 'VERIFY.sh').read_text(encoding='utf-8')
        release_checker = (ROOT / 'tools' / 'check_release_version.py').read_text(encoding='utf-8')
        foundation_checker = (ROOT / 'tools' / 'check_foundation_certification.py').read_text(encoding='utf-8')
        self.assertIn('tools/check_release_version.py', verify)
        self.assertIn('tools/check_foundation_certification.py', verify)
        self.assertIn('architecture/foundation-certification.js', release_checker)
        for token in ('production-smoke:', 'deployment-watchdog.yml', 'test_v422_final_hardening.py'):
            self.assertIn(token, foundation_checker)

    def test_v422_final_hardening_guards_remain_part_of_certification(self):
        src = (ROOT / 'tests' / 'test_v422_final_hardening.py').read_text(encoding='utf-8')
        for token in (
            'test_collection_media_cannot_become_selected_game',
            'test_full_cache_worker_has_hard_yield_path',
            'test_browser_history_hydration_no_longer_calls_legacy_day_aggregate',
        ):
            self.assertIn(token, src)


if __name__ == '__main__':
    unittest.main()

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class V434DeployRehearsalTests(unittest.TestCase):
    def test_verify_runs_deploy_rehearsal_before_runtime_suites(self):
        verify = (ROOT / 'VERIFY.sh').read_text(encoding='utf-8')
        token = 'python3 tools/check_deploy_rehearsal.py'
        self.assertIn(token, verify)
        self.assertLess(verify.index(token), verify.index('node --check config.js'))
        self.assertLess(verify.index(token), verify.index("python -m unittest discover"))

    def test_deploy_rehearsal_scans_exact_source_contracts_and_workflow(self):
        src = (ROOT / 'tools' / 'check_deploy_rehearsal.py').read_text(encoding='utf-8')
        for token in ('static_source_contract_scan', 'assertIn', 'assertNotIn',
                      'overlay_manifest_check', 'workflow_chain_check',
                      'run: bash VERIFY.sh', 'Verify deployed frontend/backend handshake'):
            self.assertIn(token, src)

    def test_deploy_rehearsal_resolves_reused_aliases_lexically(self):
        src = (ROOT / 'tools' / 'check_deploy_rehearsal.py').read_text(encoding='utf-8')
        self.assertIn('def scope_resolution_self_check()', src)
        self.assertIn('def static_source_contract_scan(root: Path = ROOT)', src)
        self.assertIn('scope_resolution_self_check()\n    workflow_chain_check()', src)
        self.assertIn('Each test method/function gets its own lexical local binding table', src)

    def test_score_playback_failure_marks_runtime_truth_at_boundary_without_double_mark(self):
        app = (ROOT / 'app.js').read_text(encoding='utf-8')
        failure = app[app.index('function handlePlaybackFailure'):app.index('function retryActivePlaybackFromGesture')]
        block = failure[failure.index("if(userPlaybackSession?.source==='score')"):
                        failure.index('if(!userInitiated){')]
        self.assertIn("markRuntimeMediaFailed(failed,err?.message||'score playback failed')", block)
        self.assertIn("runtimeFailureAlreadyMarked:true", block)
        fallback = app[app.index('function tryScoreMediaFallback'):
                       app.index('function finalizeScorePlaybackUnavailable')]
        self.assertIn('runtimeFailureAlreadyMarked=false', fallback)
        self.assertIn('if(!runtimeFailureAlreadyMarked) markRuntimeMediaFailed(failedItem,reason)', fallback)


if __name__ == '__main__':
    unittest.main()

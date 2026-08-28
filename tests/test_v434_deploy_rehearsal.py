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

    def test_deploy_rehearsal_preserves_source_and_workflow_guards(self):
        src = (ROOT / 'tools' / 'check_deploy_rehearsal.py').read_text(encoding='utf-8')
        # Test stable capabilities, not private implementation layout. The deploy
        # checker may be refactored without requiring historical tests to be edited.
        for token in (
            'static_source_contract_scan',
            'workflow_chain_check',
            'assertIn',
            'assertNotIn',
            'run: bash VERIFY.sh',
            'Verify deployed frontend/backend handshake',
        ):
            self.assertIn(token, src)

    def test_changed_files_bookkeeping_is_not_a_deploy_contract(self):
        src = (ROOT / 'tools' / 'check_deploy_rehearsal.py').read_text(encoding='utf-8')
        manifest_gate = (ROOT / 'tools' / 'check_release_manifest.py').read_text(encoding='utf-8')
        release_manifest = (ROOT / 'release-manifest.json').read_text(encoding='utf-8')
        version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
        self.assertIn('CHANGED-FILES ignored', src)
        self.assertIn('CHANGED-FILES-vX.X.X.txt files are intentionally ignored', manifest_gate)
        self.assertNotIn(f'CHANGED-FILES-v{version}.txt', release_manifest)

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

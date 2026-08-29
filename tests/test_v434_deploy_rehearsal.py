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

    def test_deploy_rehearsal_preserves_structural_and_workflow_guards(self):
        src = (ROOT / 'tools' / 'check_deploy_rehearsal.py').read_text(encoding='utf-8')

        # v4.7.0: deploy rehearsal is a STRUCTURAL preflight. Exact source-string
        # scanning was intentionally removed because the real regression suites
        # below VERIFY.sh are the behavioral authority.
        for token in (
            'workflow_chain_check',
            'test_syntax_check',
            'unittest_discovery_contract_check',
            'run: bash VERIFY.sh',
            'Verify deployed frontend/backend handshake',
        ):
            self.assertIn(token, src)

        # Do not resurrect the obsolete implementation-string scanner.
        self.assertNotIn('def _assertion_problem', src)
        self.assertNotIn('def static_source_contract_scan', src)

    def test_changed_files_bookkeeping_is_not_a_deploy_contract(self):
        manifest_gate = (ROOT / 'tools' / 'check_release_manifest.py').read_text(encoding='utf-8')
        release_manifest = (ROOT / 'release-manifest.json').read_text(encoding='utf-8')
        version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()

        # The release manifest checker remains the authority for this behavior.
        # check_deploy_rehearsal.py no longer needs a magic comment/string solely
        # to satisfy this historical test.
        self.assertIn(
            'CHANGED-FILES-vX.X.X.txt files are intentionally ignored',
            manifest_gate,
        )
        self.assertNotIn(f'CHANGED-FILES-v{version}.txt', release_manifest)

    def test_score_playback_failure_marks_runtime_truth_at_boundary_without_double_mark(self):
        app = (ROOT / 'app.js').read_text(encoding='utf-8')
        failure = app[
            app.index('function handlePlaybackFailure'):
            app.index('function retryActivePlaybackFromGesture')
        ]
        block = failure[
            failure.index("if(userPlaybackSession?.source==='score')"):
            failure.index('if(!userInitiated){')
        ]
        self.assertIn(
            "markRuntimeMediaFailed(failed,err?.message||'score playback failed')",
            block,
        )
        self.assertIn("runtimeFailureAlreadyMarked:true", block)

        fallback = app[
            app.index('function tryScoreMediaFallback'):
            app.index('function finalizeScorePlaybackUnavailable')
        ]
        self.assertIn('runtimeFailureAlreadyMarked=false', fallback)
        self.assertIn(
            'if(!runtimeFailureAlreadyMarked) markRuntimeMediaFailed(failedItem,reason)',
            fallback,
        )


if __name__ == '__main__':
    unittest.main()

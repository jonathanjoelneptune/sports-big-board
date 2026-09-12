#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
workflow = (ROOT / '.github' / 'workflows' / 'deploy-pages.yml').read_text(encoding='utf-8')
verifier = (ROOT / 'tools' / 'verify_frontend.py').read_text(encoding='utf-8')

for token in [
    "Classify deployment scope and prepare frontend",
    "fetch-depth: 1",
    "Fetch prior commit for classification",
    "git fetch --no-tags --depth=1 origin \"$BEFORE_SHA\"",
    "steps.scope.outputs.frontend_only == 'true'",
    "Run focused frontend verification",
    "python3 tools/verify_frontend.py",
    "Verify existing backend for frontend-only deploy",
    "Build static frontend for fast path",
    "Upload Pages artifact for fast path",
    "Verify full release",
    "needs.classify.outputs.backend_required == 'true'",
    "Run full Sports Big Board verification",
    "run: bash VERIFY.sh",
    "Build GitHub Pages frontend after backend deploy",
    "needs.classify.outputs.frontend_only == 'true' && needs.classify.result == 'success'",
]:
    assert token in workflow, token

# The frontend path must not pay for a full-history clone or a separate verify job.
assert 'fetch-depth: 0' not in workflow
assert workflow.count('Run focused frontend verification') == 1
assert workflow.count('Verify existing backend for frontend-only deploy') == 1
assert workflow.count('Build static frontend for fast path') == 1

# Full verification remains isolated to backend-required changes.
verify_section = workflow.split('\n  verify:\n', 1)[1].split('\n  backend:\n', 1)[0]
assert "if: ${{ needs.classify.outputs.backend_required == 'true' }}" in verify_section
assert 'Run focused frontend verification' not in verify_section
assert 'bash VERIFY.sh' in verify_section

# The backend Pages builder must only run after a successful backend deployment.
pages_build_section = workflow.split('\n  pages-build:\n', 1)[1].split('\n  pages-deploy:\n', 1)[0]
assert "needs.classify.outputs.backend_required == 'true'" in pages_build_section
assert "needs.backend.result == 'success'" in pages_build_section
assert 'Verify existing backend for frontend-only deploy' not in pages_build_section

for token in [
    'build_pages.py',
    'node',
    '--check',
    'validate_local_references',
    'backend/runtime files leaked into live Pages surfaces',
    'focused frontend verification complete',
]:
    assert token in verifier, token

# Frontend-only verification itself must not invoke backend/release deployment work.
assert 'VERIFY.sh' not in verifier
assert 'DEPLOY-FROM-GITHUB.sh' not in verifier

print('PASS: collapsed focused frontend verification lane contract')

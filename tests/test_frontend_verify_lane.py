#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
workflow = (ROOT / '.github' / 'workflows' / 'deploy-pages.yml').read_text(encoding='utf-8')
verifier = (ROOT / 'tools' / 'verify_frontend.py').read_text(encoding='utf-8')

for token in [
    "Run full Sports Big Board verification",
    "needs.classify.outputs.backend_required == 'true'",
    "Run focused frontend verification",
    "needs.classify.outputs.frontend_only == 'true'",
    "python3 tools/verify_frontend.py",
    "python3 tests/test_frontend_verify_lane.py",
]:
    assert token in workflow, token

for token in [
    'build_pages.py',
    'node',
    '--check',
    'validate_local_references',
    'backend/runtime files leaked into live Pages surfaces',
    'focused frontend verification complete',
]:
    assert token in verifier, token

# Frontend-only verification must not invoke the full backend/release preflight.
assert 'VERIFY.sh' not in verifier
assert 'DEPLOY-FROM-GITHUB.sh' not in verifier

print('PASS: focused frontend verification lane contract')

#!/usr/bin/env python3
from pathlib import Path
import importlib.util

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('scope',ROOT/'tools'/'classify_deploy_scope.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

frontend=[
    'index.html','app.js','styles.css','backend.html','media-audit.html',
    'media-audit-probe.html','canonical-shadow.html','core-model.js','api-runtime.js',
    'ui/league-view-v538.js','ui/league-view-v538.css',
    'architecture/milestone-console.js','cloud/github-pages/build_pages.py',
    # Actions-owned Sports Ticker sidecar code/regressions do not run on the VM.
    'tools/refresh_sports_ticker_current.py','tools/refresh_sports_ticker_a415.py',
    'tests/test_sports_ticker_current.py','tests/test_a415_editor_fallback.py',
    '.github/workflows/sports-ticker-refresh.yml',
    '.github/workflows/sports-ticker-scheduler-v2.yml',
    # Deployment-control files change routing/verification, not application runtime.
    'tools/classify_deploy_scope.py','tests/test_deploy_scope_classifier.py',
    '.github/workflows/deploy-pages.yml',
]
for path in frontend:
    assert mod.is_frontend_only_path(path),path

backend=[
    'VERSION','architecture/VERSION','server.py','media_audit_service.py',
    'sbb/history_repository.py','assets/soundtrack/manifest.json',
    'cloud/gcp/DEPLOY-FROM-GITHUB.sh','cloud/vm/INSTALL-MEDIA-AUDIT.sh',
    'tools/ensure_history_v4.py','requirements.txt','unknown/new-runtime-file.py',
]
for path in backend:
    assert not mod.is_frontend_only_path(path),path

needed,front,back=mod.classify(['app.js','ui/example.js'])
assert needed is False and len(front)==2 and not back
needed,front,back=mod.classify(['tools/refresh_sports_ticker_a415.py','tests/test_a415_editor_fallback.py'])
assert needed is False and len(front)==2 and not back
needed,front,back=mod.classify(['.github/workflows/deploy-pages.yml','tools/classify_deploy_scope.py'])
assert needed is False and len(front)==2 and not back
needed,front,back=mod.classify(['app.js','server.py'])
assert needed is True and 'server.py' in back
print('PASS: conservative frontend-only + sidecar/control-plane deployment classifier')

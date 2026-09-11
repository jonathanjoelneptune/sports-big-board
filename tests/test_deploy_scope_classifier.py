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
]
for path in frontend:
    assert mod.is_frontend_only_path(path),path

backend=[
    'VERSION','architecture/VERSION','server.py','media_audit_service.py',
    'sbb/history_repository.py','assets/soundtrack/manifest.json',
    'cloud/gcp/DEPLOY-FROM-GITHUB.sh','cloud/vm/INSTALL-MEDIA-AUDIT.sh',
    'tools/ensure_history_v4.py','requirements.txt','.github/workflows/deploy-pages.yml',
    'unknown/new-runtime-file.py',
]
for path in backend:
    assert not mod.is_frontend_only_path(path),path

needed,front,back=mod.classify(['app.js','ui/example.js'])
assert needed is False and len(front)==2 and not back
needed,front,back=mod.classify(['app.js','server.py'])
assert needed is True and 'server.py' in back
print('PASS: conservative frontend-only deployment classifier')

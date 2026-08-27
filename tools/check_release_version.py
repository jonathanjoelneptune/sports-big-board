#!/usr/bin/env python3
"""Fail CI when a release is assembled from mixed frontend/backend generations."""
from pathlib import Path
import re, sys
root=Path(__file__).resolve().parents[1]
version=(root/'VERSION').read_text(encoding='utf-8').strip()
errors=[]
if not re.fullmatch(r'\d+\.\d+\.\d+',version): errors.append(f'VERSION is not semantic: {version!r}')
index=(root/'index.html').read_text(encoding='utf-8')
required=['styles.css','config.js','api-runtime.js','core-model.js','architecture/playback-session.js','architecture/milestone-console.js','architecture/foundation-certification.js','architecture/site-soundtrack.js','app.js']
for asset in required:
    token=f'{asset}?v={version}'
    if token not in index: errors.append(f'index missing current cache generation: {token}')
# Every cache-busted local JS/CSS asset in index must exist and use exactly VERSION.
asset_refs=re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index)
seen_assets=set()
for asset,found in asset_refs:
    if found!=version: errors.append(f'stale cache generation {found} on {asset}; expected {version}')
    if not (root/asset).is_file(): errors.append(f'index references missing local asset: {asset}')
    if asset in seen_assets: errors.append(f'index loads local asset more than once: {asset}')
    seen_assets.add(asset)
core=(root/'core-model.js').read_text(encoding='utf-8')
if f"version:'{version}'" not in core: errors.append('core-model version does not match VERSION')
app=(root/'app.js').read_text(encoding='utf-8')
if f"version:String(DOMAIN_MODEL?.version||'{version}')" not in app: errors.append('app architecture version/fallback does not match VERSION')
history_ui=(root/'ui'/'history-audit.js').read_text(encoding='utf-8')
# History Audit is loaded after core-model.js and must derive release identity from
# the canonical core model. Do not duplicate a semantic version fallback here;
# that created repeated release-only CI failures when the file was omitted from a bump.
history_version_contract="const FRONTEND_VERSION=String(window.SBB_CORE?.version||'UNKNOWN')"
if history_version_contract not in history_ui:
    errors.append('history audit must derive frontend version from SBB_CORE without a hard-coded release fallback')
if re.search(r"FRONTEND_VERSION\s*=.*?['\"]\d+\.\d+\.\d+['\"]",history_ui):
    errors.append('history audit contains a hard-coded semantic version fallback')
try:
    if index.index('core-model.js') > index.index('ui/history-audit.js'):
        errors.append('history audit loads before core-model.js; dynamic release identity would be unavailable')
except ValueError:
    errors.append('index is missing core-model.js or ui/history-audit.js')
milestone=(root/'architecture'/'milestone-console.js').read_text(encoding='utf-8')
if f"window.SBB_CORE?.version||'{version}'" not in milestone: errors.append('milestone console fallback version does not match VERSION')
cert=(root/'architecture'/'foundation-certification.js').read_text(encoding='utf-8')
if f"window.SBB_CORE?.version||'{version}'" not in cert: errors.append('foundation certification fallback version does not match VERSION')
server=(root/'server.py').read_text(encoding='utf-8')
if 'APP_VERSION = (ROOT / "VERSION").read_text' not in server: errors.append('server APP_VERSION is not derived from VERSION')
verify=(root/'VERIFY.sh').read_text(encoding='utf-8')
if 'tools/check_release_version.py' not in verify: errors.append('VERIFY.sh does not enforce release version check')
if 'tools/check_foundation_certification.py' not in verify: errors.append('VERIFY.sh does not enforce foundation certification check')
if errors:
    print('RELEASE VERSION CHECK FAILED')
    for e in errors: print(' -',e)
    raise SystemExit(1)
print(f'PASS: release version handshake inputs are synchronized at {version}')

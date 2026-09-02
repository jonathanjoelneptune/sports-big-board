#!/usr/bin/env python3
"""Fail CI when Sports Big Board is assembled from mixed release generations.

Deployment release identity is independent of component/module versions. VERSION,
architecture/VERSION, index metadata/cache generation, frontend handshake callers,
and backend APP_VERSION must all agree on the one deployment release.
"""
from pathlib import Path
import re

root=Path(__file__).resolve().parents[1]
version=(root/'VERSION').read_text(encoding='utf-8').strip()
errors=[]

def text(path):
    p=root/path
    if not p.is_file():
        errors.append(f'missing release-integrity file: {path}')
        return ''
    return p.read_text(encoding='utf-8')

if not re.fullmatch(r'\d+\.\d+\.\d+',version):
    errors.append(f'VERSION is not semantic: {version!r}')

architecture_version=text(Path('architecture')/'VERSION').strip()
if architecture_version!=version:
    errors.append(f'architecture/VERSION={architecture_version!r}; expected {version!r}')

index=text(Path('index.html'))
if f'<title>Sports Big Board — v{version}</title>' not in index:
    errors.append('index title does not match VERSION')
if f'<meta name="sbb-release-version" content="{version}"' not in index:
    errors.append('index canonical sbb-release-version meta does not match VERSION')
if 'window.SBB_RELEASE_VERSION=version' not in index or 'window.SBB_RELEASE=Object.freeze' not in index:
    errors.append('index does not establish the canonical frontend release authority')
if 'sbbLegacyCoreReleaseProjection' not in index:
    errors.append('index is missing the compatibility projection for legacy release consumers')

asset_refs=re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index)
for asset,found in asset_refs:
    if found!=version:
        errors.append(f'stale cache generation {found} on {asset}; expected {version}')

settings=text(Path('ui')/'settings-view.js')
if re.search(r"(?:SBB_RELEASE_VERSION\s*=|SBB_CORE\s*=).*?['\"]\d+\.\d+\.\d+['\"]",settings,re.S):
    errors.append('settings-view contains a hard-coded deployment release assignment')
if 'window.SBB_RELEASE_VERSION=' in settings:
    errors.append('settings-view must never assign SBB_RELEASE_VERSION')
if 'window.SBB_CORE=Object.freeze' in settings:
    errors.append('settings-view must never rewrite SBB_CORE release metadata')
if 'window.SBB_RELEASE?.version||window.SBB_RELEASE_VERSION' not in settings:
    errors.append('settings-view does not read canonical release identity')
if '/api/release-identity?frontendVersion=' not in settings:
    errors.append('settings-view does not report canonical frontend identity to backend')

# The tuner must be directly available in Settings. Dev Mode still unlocks the
# remaining diagnostic utilities, but ticker tuning is an operator setting.
if 'class="settings-card sports-ticker-dev-card"' not in index:
    errors.append('Sports Ticker tuning card is not statically present in Settings')
if 'sports-ticker-dev-card sbb-dev-global-card' in index or 'sports-ticker-dev-card" data-sbb-dev-only' in index:
    errors.append('Sports Ticker tuning card is still hidden behind a Dev-only gate')

ticker=text(Path('architecture')/'key-info-current-v520.js')
if ".sports-ticker-dev-card{display:block!important}" not in ticker:
    errors.append('Sports Ticker runtime does not force its tuning utility visible')
if "card.className='settings-card sports-ticker-dev-card'" not in ticker:
    errors.append('runtime Sports Ticker utility injection is still Dev-gated')

release_backend=text(Path('sbb')/'release_identity_v523.py')
if 'VERSION = (ROOT / "VERSION").read_text' not in release_backend:
    errors.append('backend release-identity module is not derived from repository VERSION')
if re.search(r'^VERSION\s*=\s*["\']\d+\.\d+\.\d+["\']',release_backend,re.M):
    errors.append('backend release-identity module contains a hard-coded semantic release')

server=text(Path('server.py'))
if 'APP_VERSION = (ROOT / "VERSION").read_text' not in server:
    errors.append('server APP_VERSION is not derived from VERSION')

verify=text(Path('VERIFY.sh'))
if 'tools/check_release_version.py' not in verify:
    errors.append('VERIFY.sh does not execute the release-integrity checker')
if re.search(r'^exit\s+0\s*$',verify,re.M):
    errors.append('VERIFY.sh contains an unconditional successful exit')

# Release projection must exist after core-model is loaded and before consumers
# such as Settings and History Audit initialize.
try:
    core_pos=index.index(f'<script src="core-model.js?v={version}"')
    projection_pos=index.index('<script id="sbbLegacyCoreReleaseProjection"')
    settings_pos=index.index(f'<script src="ui/settings-view.js?v={version}"')
    history_pos=index.index(f'<script src="ui/history-audit.js?v={version}"')
    if not (core_pos < projection_pos < settings_pos < history_pos):
        errors.append('release authority/projection load order is unsafe')
except ValueError:
    errors.append('index is missing core/release/settings/history release surfaces')

if errors:
    print('RELEASE INTEGRITY CHECK FAILED')
    for error in errors:
        print(' -',error)
    raise SystemExit(1)
print(f'PASS: frontend + backend + database-audit release inputs are synchronized at {version}')

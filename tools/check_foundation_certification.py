#!/usr/bin/env python3
"""Static release gate for Sports Big Board v4.3 Foundation Certification."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
errors=[]

def require(condition,message):
    if not condition: errors.append(message)

def text(path):
    p=ROOT/path
    if not p.is_file():
        errors.append(f'missing certification file: {path}')
        return ''
    return p.read_text(encoding='utf-8')

version=text('VERSION').strip()
try:
    manifest=json.loads(text('foundation-certification.json') or '{}')
except json.JSONDecodeError as exc:
    errors.append(f'foundation-certification.json is invalid JSON: {exc}')
    manifest={}

required_procedures=[
    'release-handshake','playback-cycle','historical-read','operator-load',
    'resource-modes','game-center','soundtrack','ui-responsiveness'
]
required_gates=[
    'release-handshake','stress-suite','procedure-suite','step-debt',
    'platform-checks','clean-window-errors','playback-invariant','worker-health',
    'state-restore','legacy-read-isolation'
]

require(version=='4.3.0',f'Foundation Certification build must be VERSION 4.3.0, found {version!r}')
require(manifest.get('release')==version,'certification manifest release does not match VERSION')
require(manifest.get('certifiesBaseline')=='4.2.2','certification baseline must be v4.2.2 final hardening')
require(manifest.get('requiredProcedures')==required_procedures,'manifest procedure order/scope changed')
require(manifest.get('blockingGates')==required_gates,'manifest blocking gate set changed')
require(manifest.get('durableCatalogMutation') is False,'certification must not mutate the durable catalog')
require(manifest.get('requiresCatalogRebuild') is False,'certification must not require a catalog rebuild')
require(manifest.get('requiresSoundtrackUpload') is False,'certification must not require soundtrack re-upload')

html=text('index.html')
cert=text('architecture/foundation-certification.js')
milestone=text('architecture/milestone-console.js')
verify=text('VERIFY.sh')
workflow=text('.github/workflows/deploy-pages.yml')
watchdog=text('.github/workflows/deployment-watchdog.yml')
hardening=text('tests/test_v422_final_hardening.py')

m='architecture/milestone-console.js?v=4.3.0'
f='architecture/foundation-certification.js?v=4.3.0'
s='architecture/site-soundtrack.js?v=4.3.0'
a='app.js?v=4.3.0'
for token in (m,f,s,a,'Foundation Certification Console','RUN DEV STRESS TEST'):
    require(token in html,f'index missing certification/release token: {token}')
if all(token in html for token in (m,f,s,a)):
    require(html.index(m)<html.index(f)<html.index(s)<html.index(a),'foundation certification must load after milestone and before soundtrack/app')

for token in (
    "const REQUIRED_PROCEDURES=['release-handshake','playback-cycle','historical-read','operator-load','resource-modes','game-center','soundtrack','ui-responsiveness']",
    'await M.reset()','await M.runStressTest()','M.procedureResults',"snap?.api?.['/api/history/day']",
    "status:ok?'CERTIFIED':'NOT_CERTIFIED'",'cleanWindow:true','FOUNDATION CERTIFIED'
):
    require(token in cert,f'certification runtime missing invariant: {token}')
if 'await M.reset()' in cert and 'await M.runStressTest()' in cert:
    require(cert.index('await M.reset()')<cert.index('await M.runStressTest()'),'certification must reset observation window before stress execution')

for token in ("version:'1.2'",'refresh,reset,text:textSnapshot','get procedureResults(){return safe(procedureResults);}'):
    require(token in milestone,f'milestone console does not expose certification API: {token}')

require('tools/check_foundation_certification.py' in verify,'VERIFY.sh does not enforce Foundation Certification contract')
for token in ('production-smoke:','Verify deployed frontend/backend handshake','/api/milestone/console?frontendVersion=$EXPECTED_VERSION'):
    require(token in workflow,f'deployment release gate missing: {token}')
for token in ("cron: '*/15 * * * *'",'Detect repository/deployment drift'):
    require(token in watchdog,f'deployment watchdog missing: {token}')
for token in ('test_collection_media_cannot_become_selected_game','test_full_cache_worker_has_hard_yield_path','test_browser_history_hydration_no_longer_calls_legacy_day_aggregate'):
    require(token in hardening,f'v4.2.2 hardening regression contract missing: {token}')

if errors:
    print('FOUNDATION CERTIFICATION CHECK FAILED')
    for error in errors: print(' -',error)
    raise SystemExit(1)
print(f'PASS: Sports Big Board v{version} Foundation Certification contract is internally consistent')

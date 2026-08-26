#!/usr/bin/env python3
"""Static release gate for Sports Big Board v4.3.3 three-tier Foundation Certification."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
errors=[]
def require(cond,msg):
    if not cond: errors.append(msg)
def text(path):
    p=ROOT/path
    if not p.is_file(): errors.append(f'missing certification file: {path}'); return ''
    return p.read_text(encoding='utf-8')
version=text('VERSION').strip()
try: manifest=json.loads(text('foundation-certification.json') or '{}')
except Exception as exc: errors.append(f'invalid foundation-certification.json: {exc}');manifest={}
require(version=='4.3.3',f'expected VERSION 4.3.3, found {version!r}')
require(manifest.get('release')==version,'manifest release mismatch')
require(manifest.get('schemaVersion')==2,'three-tier manifest schema must be 2')
require(manifest.get('allThreeTiersRequired') is True,'all three tiers must be required')
for tier in ('tier1','tier2','tier3'): require(manifest.get('tiers',{}).get(tier,{}).get('required') is True,f'{tier} must be required')
require(manifest.get('tiers',{}).get('tier2',{}).get('minimumDurationMs',0)>=900000,'Tier 2 soak must be at least 15 minutes')
require(manifest.get('durableCatalogMutation') is False,'certification may not mutate durable catalog')
html=text('index.html');cert=text('architecture/foundation-certification.js');milestone=text('architecture/milestone-console.js');app=text('app.js');gc=text('ui/game-center-view.js');styles=text('styles.css');verify=text('VERIFY.sh');linescore=text('architecture/game-center-linescore.js');scheduler=text('sbb/media_work_scheduler.py')
chain=[f'architecture/milestone-console.js?v={version}',f'architecture/foundation-certification.js?v={version}',f'architecture/site-soundtrack.js?v={version}',f'app.js?v={version}']
for token in chain: require(token in html,f'index missing {token}')
if all(x in html for x in chain): require([html.index(x) for x in chain]==sorted(html.index(x) for x in chain),'certification/runtime load order invalid')
for token in ('RUN TIER 1','RUN TIER 2 • 15 MIN','RUN TIER 3','RUN FULL CERTIFICATION','FOUNDATION_CERTIFIED','allThreeRequired:true','await M.runSoakTest','await M.runChaosTest'):
    require(token in cert,f'certification runtime missing {token}')
for token in ("allowWarnings=false","new Set(['PASS','WARN'])","tierRunEvidence('tier3','Tier 3 chaos',run,0,{allowWarnings:true})",'advisory warnings','warningCount:warnings.length'):
    require(token in cert,f'certification warning semantics missing {token}')
for token in ("version:'1.3'",'runSoakTest','runChaosTest','regression-hardening','manual pause remains latched for 25 seconds','background program refresh cannot restart active clip'):
    require(token in milestone,f'milestone runtime missing {token}')
for token in ('let PROGRAM = [];','function maybeAutoplayRoundupForDate(){','return false;','selectedEventMatchesActivePlayback','syncGameCenterToActivePlayback','demoSeedCount:()=>0','roundupAutoplayEnabled:()=>false','manualPauseRequested&&!userInitiated'):
    require(token in app,f'playback hardening missing {token}')
for token in ("function clear(message='Game Center follows the active game video.')","if(!event){clear();return;}","version:'1.6'"):
    require(token in gc,f'Game Center hardening missing {token}')
for token in ('SBB_GAME_CENTER_LINESCORE','const missing=total-known'):
    require(token in linescore,f'extra-inning linescore hardening missing {token}')
for token in ('circuitRejected','game-center:','rate-limit'):
    require(token in scheduler,f'Game Center rate-limit circuit missing {token}')
require(f'architecture/game-center-linescore.js?v={version}' in html,'index missing Game Center linescore reconciler')
require('score-date pager interaction hardening' in styles,'score pager hitbox hardening missing')
require('tools/check_foundation_certification.py' in verify,'VERIFY.sh does not enforce certification checker')
if errors:
    print('FOUNDATION CERTIFICATION CHECK FAILED')
    for e in errors: print(' -',e)
    raise SystemExit(1)
print(f'PASS: Sports Big Board v{version} three-tier Foundation Certification contract is internally consistent')

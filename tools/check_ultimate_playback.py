#!/usr/bin/env python3
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
errors=[]
def need(cond,msg):
    if not cond: errors.append(msg)
def text(p):
    q=ROOT/p
    if not q.is_file(): errors.append(f"missing {p}"); return ""
    return q.read_text(encoding='utf-8')
version=text('VERSION').strip(); app=text('app.js'); index=text('index.html')
readiness=text('architecture/playback-readiness.js'); session=text('architecture/playback-session.js'); backend=text('sbb/playback_readiness.py'); resolver=text('architecture/media-resolver.js'); manifest=text('architecture/media-manifest.js'); scheduler=text('sbb/media_work_scheduler.py'); verify=text('VERIFY.sh')
try: version_tuple=tuple(int(x) for x in version.split('.'))
except Exception: version_tuple=(0,)
need(version_tuple>=(4,4,1),f'expected v4.4.1 or newer, found {version}')
need(f'architecture/playback-readiness.js?v={version}' in index,'playback readiness module not loaded with current cache generation')
t=f'architecture/playback-transports.js?v={version}';r=f'architecture/playback-readiness.js?v={version}';m=f'architecture/media-manifest.js?v={version}'
need(index.find(t) < index.find(r) < index.find(m),'readiness load order must be transports -> readiness -> manifest')
for token in ('PLAYBACK_READY','QUARANTINED','noteHotReady','noteWarmFailure','networkSuspect','rankBonus'):
    need(token in readiness,f'frontend readiness missing {token}')
need("provider:''" in session and 'provider:String(meta.provider||state.provider' in session,'canonical playback session does not preserve provider identity')
need('provider:s.provider' in readiness,'frontend readiness does not learn provider from canonical playback session')
for token in ('STANDBY_WARM_TIMEOUT_MS=8000','STANDBY_MIN_PROGRESS_SECONDS=0.45','standbyWarmFailed','noteHotStandbyReady','preflightUpcomingProgram','hotStandbyHitRate','A/B promotion lost hot-ready claim'):
    need(token in app,f'hot standby integration missing {token}')
need("window.SBB_PLAYBACK_READINESS?.eligible?.(item)!==false" in app,'runtime usability does not enforce quarantine')
need('window.SBB_PLAYBACK_READINESS?.rankBonus?.(asset)' in resolver,'resolver does not include playback reliability')
need('window.SBB_PLAYBACK_READINESS?.eligible?.(a)!==false' in manifest,'manifest does not exclude quarantined playback')
for token in ('playback_asset_health','reliability_score','quarantined_until','competition_id','hot-ready','schedule_milestone_hook_install'):
    need(token in backend,f'backend readiness persistence missing {token}')
need('_install_playback_readiness()' in scheduler,'server import path does not schedule readiness persistence hook')
need('node tests/test_v440_playback_readiness.js' in verify,'VERIFY.sh does not execute v4.4.0 browser readiness test')

for token in ('hydrateFromServer','hydrate(payload.records','serverUpdatedAt'):
    need(token in readiness,f'v4.4.1 durable readiness hydration missing {token}')
for token in ('SCORE_MEDIA_PRIME_MAX_ACTIVE = 1','STANDBY_ACTIVE_RUNWAY_SECONDS=5','backgroundWarmAllowed','updatePlaybackWarmPressure','STANDBY_TRANSITION_MAX_WAIT_MS=24000','never intentionally puts an unproven automatic candidate on air'):
    need(token in app,f'v4.4.1 on-air bandwidth protection missing {token}')
terminal=text('architecture/playback-terminal.js');terminal_css=text('ui/playback-terminal.css')
for token in ('bufferTimeMs','playTimeMs','SBB_PLAYBACK_TERMINAL','playbackTerminalSummary'):
    need(token in terminal,f'playback terminal missing {token}')
need('architecture/playback-terminal.js?v='+version in index,'playback terminal not loaded with current cache generation')
need('playbackReadiness' in backend and 'total_stall_ms' in backend and 'MilestoneConsole.snapshot = wrapped_snapshot' in backend,'server readiness hydration surface/stall totals missing')
need('node tests/test_v441_playback_terminal.js' in verify,'VERIFY.sh does not execute v4.4.1 playback terminal test')
need('node tests/test_v441_readiness_hydration.js' in verify,'VERIFY.sh does not execute v4.4.1 readiness hydration test')
need('_bootstrap_from_history_catalog' in backend,'v4.4.1 readiness database does not seed from existing runtime catalog truth')
need("tests/test_v441_smooth_playback.py" in verify or "unittest discover" in verify,'VERIFY.sh does not cover v4.4.1 smooth-playback contracts')
if errors:
    print('ULTIMATE PLAYBACK CHECK FAILED')
    for e in errors: print(' -',e)
    raise SystemExit(1)
print('PASS: v4.4.1 Ultimate Playback smoothness contract is internally consistent')

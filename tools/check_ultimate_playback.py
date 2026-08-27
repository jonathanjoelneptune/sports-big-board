#!/usr/bin/env python3
from pathlib import Path
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
need(version_tuple>=(4,4,2),f'expected v4.4.2 or newer, found {version}')
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
terminal=text('architecture/playback-terminal.js')
for token in ('bufferTimeMs','playTimeMs','SBB_PLAYBACK_TERMINAL','playbackTerminalSummary'):
    need(token in terminal,f'playback terminal missing {token}')
need('architecture/playback-terminal.js?v='+version in index,'playback terminal not loaded with current cache generation')
need('playbackReadiness' in backend and 'total_stall_ms' in backend and 'MilestoneConsole.snapshot = wrapped_snapshot' in backend,'server readiness hydration surface/stall totals missing')
need('node tests/test_v441_playback_terminal.js' in verify,'VERIFY.sh does not execute v4.4.1 playback terminal test')
need('node tests/test_v441_readiness_hydration.js' in verify,'VERIFY.sh does not execute v4.4.1 readiness hydration test')
need('_bootstrap_from_history_catalog' in backend,'v4.4.1 readiness database does not seed from existing runtime catalog truth')
need("tests/test_v441_smooth_playback.py" in verify or "unittest discover" in verify,'VERIFY.sh does not cover v4.4.1 smooth-playback contracts')
devmode=text('architecture/dev-mode.js')
for token in ('resetForLoad','SBB_DEV_MODE','sbb:dev-mode'):
    need(token in devmode,f'v4.4.2 dev-mode authority missing {token}')
need('id="devModeToggleBtn"' in index,'v4.4.2 settings Dev Mode toggle missing')
need('manualQueueAdvance' in app and "reason:direction<0?'manual previous button':'manual next button'" in app,'v4.4.2 manual Next/Prev authority missing')
need('transitionCritical=false' in app and 'transition-critical standby' in app and 'standby pending: readiness not proven' in app,'v4.4.2 transition-critical readiness distinction missing')
need('node tests/test_v442_dev_mode.js' in verify,'VERIFY.sh does not execute v4.4.2 Dev Mode test')
# v4.4.3 playback resilience baseline retained by v4.4.4.
for token in ('PLAYBACK_ENGINE_FAILURE_THRESHOLD=3','TRANSIENT_UNPLAYABLE_MEDIA=new Map()','function resetPlaybackEngine','RECENT_HISTORY_AUTOFILL_DAYS=3','currentIsFullRecap:()=>isFullRecapCandidate'):
    need(token in app,f'v4.4.3 playback hardening missing {token}')
completion=app[app.find('function advanceAfterCompletedItem'):app.find('function advance(direction=1)')]
need('!isFullRecapCandidate(finished)' in completion,'v4.4.3 recap completion does not use semantic recap classification')
need('!finished?.overview' not in completion,'v4.4.3 recap completion still depends on raw overview flag')
for token in ('DUPLICATE_GAME_RECAP','UNRECOVERABLE_NO_FIRST_FRAME','chaosDisruptStandby','markRuntimeMediaFailed'):
    need(token in terminal,f'v4.4.3+ resilience guard missing {token}')
need('node tests/test_v443_playback_endurance.js' in verify,'VERIFY.sh does not execute v4.4.3 endurance baseline test')
need('node tests/test_v443_playback_endurance_runtime.js' in verify,'VERIFY.sh does not execute v4.4.3 endurance runtime test')
# v4.4.4 mixed-media endurance + playback recovery baseline retained.
for token in ("label:'WARMUP',durationMs:10*60_000","label:'MIXED SOAK',durationMs:30*60_000","label:'MIXED HAMMER',durationMs:20*60_000",'MIN_SUCCESSFUL_STARTS=150','MIN_TRANSITIONS=149',"QUALITY_ROTATION=Object.freeze(['GREEN','PURPLE','BLUE'])",'MIN_SPORTS=3','MIN_TRANSPORTS=2','seenMediaKeys','switchStressDate','retryAttempts','fallbacks','ASSET_BAD','REPEATED_MEDIA','unrecoveredBlanks'):
    need(token in terminal,f'v4.4.4 mixed-media endurance baseline missing {token}')
import re
def numeric_const(name):
    m=re.search(rf'const {re.escape(name)}=(\d+)',terminal);return int(m.group(1)) if m else -1
need(numeric_const('MIN_DATES')>=3,'v4.4.4 date diversity floor regressed below 3')
need(numeric_const('MIN_DATE_CHANGES')>=10,'v4.4.4 date-change floor regressed below 10')
need("querySelectorAll?.('#scoreCells .score-card.has-highlights')" in terminal,'v4.4.4 endurance does not drive playable score-ribbon cards')
need('node tests/test_v444_playback_recovery_runtime.js' in verify,'VERIFY.sh does not execute v4.4.4 recovery runtime test')
# v4.4.5 random-archive stress + duplicate-candidate rejection.
for token in ('ARCHIVE_LOOKBACK_DAYS=365','ARCHIVE_MIN_JUMP_DAYS=45','LONG_DATE_JUMP_DAYS=45','MIN_DATES=10','MIN_DATE_CHANGES=12','MIN_MONTHS=6','MIN_DATE_SPAN_DAYS=180','MIN_LONG_DATE_JUMPS=8','SPORT_IDS','randomArchiveTarget','waitForRibbonCandidate','shouldRandomArchiveJump','cardMediaKey','scoreCardAvailability','playbackItemKey','duplicateCandidateRejects','preflightDuplicateSkips','rejectDuplicateStressCandidate','queueDuplicateCandidateReplacement','stressDriven',"filter(r=>r.enduranceRunId===s.runId)"):
    need(token in terminal,f'v4.4.5 random-archive endurance missing {token}')
need('python3 tools/check_release_manifest.py' in verify,'VERIFY.sh does not execute atomic release manifest gate first')
need('node tests/test_v445_duplicate_candidate_runtime.js' in verify,'VERIFY.sh does not execute v4.4.5 duplicate-candidate runtime test')
# v4.4.6 historical-media quarantine + graceful recovery.
for token in ('RECOVERY_PHASES','RECOVERY_TOTAL_MS',"profile:'full'",'preferNFL:true','startRecovery','STALE_MEDIA','NO_MEDIA_SKIP','staleMedia','noMediaSkips','fallbackSuccesses','quarantineReselections','quarantineStaleMedia','markRuntimeMediaFailed','tryScoreMediaFallback','QUARANTINED_MEDIA_RESELECTED',"HTTP 410 stale historical media",'providerFailure:false'):
    need(token in terminal,f'v4.4.6 historical-media recovery missing {token}')
need('node tests/test_v446_stale_media_runtime.js' in verify,'VERIFY.sh does not execute v4.4.6 stale-media runtime test')
need('python3 -m unittest tests.test_v446_historical_media_quarantine' in verify,'VERIFY.sh does not execute v4.4.6 static recovery contract')
if errors:
    print('ULTIMATE PLAYBACK CHECK FAILED')
    for e in errors: print(' -',e)
    raise SystemExit(1)
print(f'PASS: v{version} Ultimate Playback random-archive + historical-media quarantine/recovery contract is internally consistent')

#!/usr/bin/env python3
"""Static invariants for splash-screen first-program preload + v5.4.3 progress UI."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
index=(ROOT/'index.html').read_text(encoding='utf-8')
module=(ROOT/'architecture'/'splash-preload-v5212.js').read_text(encoding='utf-8')

checks={
    'module version': f"const VERSION='{VERSION}'" in module,
    'YouTube SDK network preload': '<link rel="preload" href="https://www.youtube.com/iframe_api" as="script" fetchpriority="high">' in index,
    'splash progress bar': 'id="launchWarmProgress"' in index and 'role="progressbar"' in index and 'id="launchWarmProgressFill"' in index,
    'splash progress percentage': 'id="launchWarmProgressPct"' in index and 'PROGRESS_FLOOR' in module and 'aria-valuenow' in module,
    'accessible hidden warm status retained': 'id="launchWarmStatus"' in index and '>Loading…</div>' in index,
    'old visible loading sentence retired': 'Loading scores and first video' not in index,
    'module loaded after app': index.index(f'app.js?v={VERSION}') < index.index(f'architecture/splash-preload-v5212.js?v={VERSION}'),
    'module loaded before post-app ticker': index.index(f'architecture/splash-preload-v5212.js?v={VERSION}') < index.index(f'architecture/key-info-current-v520.js?v={VERSION}'),
    'existing data bootstrap reinforced': "typeof safeStartLiveData==='function'" in module,
    'exact selected program reused': "typeof clip==='function'" in module and 'SBB_V5_LEGACY_CLIP' in module,
    'existing assignment respected': 'assignmentMatches' in module and 'slotAssignment' in module,
    'canonical Hot Standby preparation': 'prepareStandby' in module and 'transitionCritical:true' in module and 'videoReady' in module and 'HOT_STANDBY' in module,
    'safe YouTube cue fallback': 'cueVideoById' in module,
    'native preload auto': "v.preload='auto'" in module and "v.setAttribute('preload','auto')" in module,
    'native remains muted': 'v.muted=true' in module,
    'launch state stops warmer': 'experienceStarted()' in module and "stop('launch-click')" in module,
    'diagnostic surface': 'SBB_SPLASH_PRELOAD' in module and 'snapshot:' in module,
}
forbidden={
    'prelaunch YouTube load/start': '.loadVideoById(' in module or '.playVideo(' in module,
    'prelaunch native play': bool(re.search(r'\bv\.play\s*\(',module)),
}
failed=[name for name,ok in checks.items() if not ok]
failed += [name for name,bad in forbidden.items() if bad]
if failed:
    print(f'FAIL v{VERSION} splash preload invariants')
    for name in failed: print(' -',name)
    raise SystemExit(1)
print(f'PASS v{VERSION} splash progress + safe exact-first-video preload without bypassing launch gesture')

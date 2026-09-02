#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
parts=tuple(int(x) for x in VERSION.split('.'))
assert parts >= (5,2,10), VERSION

index=(ROOT/'index.html').read_text()
assert f'ui/player-visibility.js?v={VERSION}' in index
assert f'architecture/scroll-motion-smoothness-v5210.js?v={VERSION}' in index
assert index.index(f'ui/player-visibility.js?v={VERSION}') < index.index(f'architecture/scroll-motion-smoothness-v5210.js?v={VERSION}') < index.index(f'ui/settings-view.js?v={VERSION}')

visibility=(ROOT/'ui'/'player-visibility.js').read_text()
assert "version:'1.7'" in visibility
assert "if(!canUseSticky()){diag.scrollNoops++;return;}" in visibility
assert 'function bindLockGestures()' in visibility
assert 'function unbindLockGestures()' in visibility
assert "stage.style.setProperty('transform',`translate3d(" in visibility
assert "window.addEventListener('scroll',onRootScroll,{passive:true})" in visibility
# Non-passive listeners may exist only as lock-state helpers, not in init.
init=visibility.split('function init(){',1)[1].split('}',1)[0]
assert "addEventListener('wheel',onUpperWheel" not in init
assert "addEventListener('touchmove',onUpperTouchMove" not in init

motion=(ROOT/'architecture'/'scroll-motion-smoothness-v5210.js').read_text()
assert f"const VERSION='{VERSION}'" in motion
for token in [
    'content-visibility:auto',
    'contain-intrinsic-size:166px 76px',
    'sbb-paint-suspended',
    'sbb-scroll-active',
    'RUN MOTION TEST',
    'samplePhase',
    'SCORE RIBBON',
    'VERTICAL PAGE',
    'SPORTS TICKER',
    'PerformanceObserver',
    'longtask',
    'SBB_SCROLL_MOTION',
]:
    assert token in motion, token

# Browser-level score virtualization keeps every event/scroll coordinate while
# allowing Chromium to skip offscreen card rendering.
assert '.score-ribbon>.score-cells>.score-card' in motion
assert 'content-visibility:auto' in motion

# Ticker remains compositor-owned and date-independent from the prior releases.
ticker=(ROOT/'architecture'/'key-info-current-v520.js').read_text()
assert "engine:'COMPOSITOR_WAAPI_LOOP'" in ticker
assert 'mainThreadPerFrame:false' in ticker
assert 'forcedLayoutReadsPerFrame:0' in ticker

print(f'PASS v5.2.10+ conditional scrolling + compositor motion + score virtualization + motion certification at v{VERSION}')

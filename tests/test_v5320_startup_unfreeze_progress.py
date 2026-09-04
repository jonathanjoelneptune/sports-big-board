#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
assert VERSION=='5.4.6',VERSION
index=(ROOT/'index.html').read_text()
score=(ROOT/'ui'/'game-center-score-authority-v5319.js').read_text()
bumper=(ROOT/'architecture'/'playback-transition-bumper-v5319.js').read_text()
bumper_css=(ROOT/'ui'/'playback-transition-bumper-v5319.css').read_text()
splash=(ROOT/'architecture'/'splash-preload-v5212.js').read_text()

# Prior-release startup freeze prevention: neither new authority layer may watch the
# same DOM it also mutates. Their ownership is data/session-event based instead.
assert 'new MutationObserver' not in score
assert 'observer.observe' not in score
assert '__sbbScoreAuthorityV5320' in score
assert 'correctedPayload' in score
assert 'window.SBB_GAME_CENTER=Object.freeze' in score
assert 'new MutationObserver' not in bumper
assert 'observer.observe' not in bumper
assert 'data-sbb-transition-bumper' in bumper_css
assert "document.documentElement.dataset.sbbTransitionBumper" in bumper
assert '[60,180,420,900,1800]' in bumper

# Splash loading copy is now a real progress bar rather than visible status text.
assert 'id="launchWarmProgress"' in index
assert 'role="progressbar"' in index
assert 'id="launchWarmProgressFill"' in index
assert 'id="launchWarmProgressPct"' in index
assert 'Loading scores and first video' not in index
assert 'PROGRESS_FLOOR' in splash
assert 'aria-valuenow' in splash
assert 'progressValue' in splash
assert "READY:100" in splash

# Release cache identity remains atomic.
for asset in ['ui/game-center-score-authority-v5319.js','architecture/playback-transition-bumper-v5319.js','ui/playback-transition-bumper-v5319.css','architecture/splash-preload-v5212.js']:
    assert f'{asset}?v={VERSION}' in index,asset

print(f'PASS v{VERSION} startup unfreeze + observer-free authorities + launch progress bar')

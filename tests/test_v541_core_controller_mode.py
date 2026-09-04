#!/usr/bin/env python3
"""Evergreen compatibility regression for v5.4.1 Core Controller Mode."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
parts=tuple(int(x) for x in VERSION.split('.'))
assert parts >= (5,4,1), VERSION
index=(ROOT/'index.html').read_text(encoding='utf-8')
module=(ROOT/'architecture'/'controller-mode-v542.js').read_text(encoding='utf-8')
readiness=(ROOT/'architecture'/'controller-readiness-v540.js').read_text(encoding='utf-8')
css=(ROOT/'ui'/'controller-mode-v542.css').read_text(encoding='utf-8')

assert f'ui/controller-mode-v542.css?v={VERSION}' in index
assert f'architecture/controller-mode-v542.js?v={VERSION}' in index
assert index.index(f'architecture/controller-readiness-v540.js?v={VERSION}') < index.index(f'architecture/controller-mode-v542.js?v={VERSION}')
assert f"const VERSION='{VERSION}'" in module

for token in [
    'navigator.getGamepads',"window.addEventListener('gamepadconnected'", "window.addEventListener('gamepaddisconnected'",
    "ownerApi()?.claim?.('controller'", 'waitingForNeutral', 'controllerNeutral', 'controllerEverActive',
    "preference!=='disabled'", "localStorage.setItem(PREF_KEY,preference)", "document.visibilityState==='hidden'",
    'A:0','B:1','X:2','Y:3','LB:4','RB:5','MENU:9','UP:12','DOWN:13','LEFT:14','RIGHT:15',
    'function processDirection(gamepad,now)', 'nav()?.activate?.()', 'nav()?.back?.()', 'playPause()', 'toggleGameCenterLeagueView()', 'toggleInfoDrawerVisibility()',
    'transport(-1)', 'transport(1)', 'function processRightStick(gamepad,dt)', 'requestAnimationFrame(poll)', 'scheduleDiscovery()'
]:
    assert token in module, token
assert 'setInterval(' not in module
assert 'new MutationObserver' not in module

for token in ['id="controllerSettingsCard"','id="controllerModeSelect"','<option value="automatic">Automatic</option>','<option value="disabled">Disabled</option>','id="controllerStatusValue"','id="controllerStatusHint"']:
    assert token in index, token
for token in ['sbb-controller-help','sbb-controller-help-grid','data-sbb-controller-active','prefers-reduced-motion','[data-sbb-controller-focus="1"]']:
    assert token in css or token in module, token

for forbidden in ['navigator.getGamepads','gamepadconnected','gamepaddisconnected']:
    assert forbidden not in readiness, forbidden
for token in ['SBB_SEMANTIC_NAVIGATION','SBB_INTERACTION_REGIONS','SBB_INPUT_OWNERSHIP']:
    assert token in readiness, token

print(f'PASS v{VERSION} preserves v5.4.1 core controller behavior')

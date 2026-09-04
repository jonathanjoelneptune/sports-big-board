#!/usr/bin/env python3
"""Static invariants for Sports Big Board v5.4.2 controller radials/live input."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
parts=tuple(int(x) for x in VERSION.split('.'))
assert parts >= (5,4,2), VERSION
index=(ROOT/'index.html').read_text(encoding='utf-8')
module=(ROOT/'architecture'/'controller-mode-v542.js').read_text(encoding='utf-8')
css=(ROOT/'ui'/'controller-mode-v542.css').read_text(encoding='utf-8')
region_map=(ROOT/f'CONTROLLER-REGION-MAP-v{VERSION}.md').read_text(encoding='utf-8')

assert f'ui/controller-mode-v542.css?v={VERSION}' in index
assert f'architecture/controller-mode-v542.js?v={VERSION}' in index
assert f"const VERSION='{VERSION}'" in module
assert "mode:'RADIALS_POINTER_AUTOMATIC_GAMEPAD'" in module

# Header diagnostics distinguishes browser visibility from actual live input.
for token in ['id="controllerLiveIndicator"','controller-live-indicator','🎮 WAIT']:
    assert token in index or token in css, token
for token in ['gamepadApiAvailable','indicatorState()','🎮 NO API','🎮 READY','🎮 LIVE','lastRawInputAt','rawInputs','activeMapping']:
    assert token in module, token

# Robust controller discovery and non-standard XInput support.
for token in [
    'DISCOVERY_MS=650','window.addEventListener(\'focus\',onWindowFocus)',"document.addEventListener('pointerdown',onPointerWake",
    'triggerValue(gamepad,side)','Some non-standard XInput wrappers expose triggers as axes resting at -1',
    "activeMapping!=='standard'", '(gamepad?.axes?.length||0)>=8', 'NEUTRAL_DEADZONE=.28', 'processRawActivity(gamepad)'
]:
    assert token in module, token

# RT league wheel and LT date/scope wheel.
for token in [
    "openRadial('league')","openRadial('date')",'function leagueOptions()','function dateScopeOptions()',
    "['ALL','ALL']","['MLB','MLB']","['NCAAF','NCAAF']","['SPECIAL','SPECIAL EVENTS']",
    "value:'TODAY'","value:'YESTERDAY'","value:'PREV'","value:'NEXT'","value:'DATE'","value:'BROWSE'","value:'RETURN'",
    'processRadial(gamepad)','MOVE RIGHT STICK • RELEASE TRIGGER','RADIAL_DEADZONE=.38'
]:
    assert token in module, token
for token in ['.sbb-controller-radial','.sbb-controller-radial-wheel','.sbb-controller-radial-item.selected']:
    assert token in css, token

# R3 pointer fallback uses left stick for cursor, A to click and right stick to scroll.
for token in [
    'if(index===BUTTON.RS){setPointerMode(!pointerMode);return;}','document.elementFromPoint(pointerX,pointerY)',
    'function movePointer(gamepad,dt)','function pointerClick()','function pointerScroll(gamepad,dt)',
    'POINTER_SPEED=760','POINTER_DEADZONE=.16','dispatchEvent(new MouseEvent'
]:
    assert token in module, token
for token in ['.sbb-controller-pointer','data-sbb-controller-pointer']:
    assert token in css or token in module, token

# No main-thread busy loops or mutation feedback observers.
assert 'setInterval(' not in module
assert 'new MutationObserver' not in module
assert 'requestAnimationFrame(poll)' in module

# Updated help and documentation surface the new controls.
for token in ['Leagues','Date / Scope','Pointer']:
    assert token in module, token
for token in ['RT — League radial','LT — Date / scope radial','R3 — Pointer fallback','Header live-input indicator']:
    assert token in region_map, token

print(f'PASS v{VERSION} controller live indicator + robust input + RT/LT radials + R3 pointer fallback')

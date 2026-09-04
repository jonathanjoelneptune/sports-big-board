#!/usr/bin/env python3
"""Static invariants for Sports Big Board v5.4.1 Core Controller Mode."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
index=(ROOT/'index.html').read_text(encoding='utf-8')
module=(ROOT/'architecture'/'controller-mode-v541.js').read_text(encoding='utf-8')
readiness=(ROOT/'architecture'/'controller-readiness-v540.js').read_text(encoding='utf-8')
css=(ROOT/'ui'/'controller-mode-v541.css').read_text(encoding='utf-8')
region_map=(ROOT/f'CONTROLLER-REGION-MAP-v{VERSION}.md').read_text(encoding='utf-8')

assert VERSION=='5.4.1', VERSION
assert f'ui/controller-mode-v541.css?v={VERSION}' in index
assert f'architecture/controller-mode-v541.js?v={VERSION}' in index
assert index.index(f'architecture/controller-readiness-v540.js?v={VERSION}') < index.index(f'architecture/controller-mode-v541.js?v={VERSION}')
assert f"const VERSION='{VERSION}'" in module
assert "mode:'CORE_AUTOMATIC_GAMEPAD'" in module

# Automatic controller detection/input ownership. Controller mode is activated by
# meaningful gamepad input, not by a separate site button.
for token in [
    'navigator.getGamepads',"window.addEventListener('gamepadconnected'", "window.addEventListener('gamepaddisconnected'",
    "ownerApi()?.claim?.('controller'", "ownerApi()?.subscribe?.(onOwnerChange)", 'waitingForNeutral', 'controllerNeutral', 'controllerEverActive',
    "preference!=='disabled'", "localStorage.setItem(PREF_KEY,preference)", "document.visibilityState==='hidden'"
]:
    assert token in module, token
assert 'setInterval(' not in module
assert 'new MutationObserver' not in module

# Standard controller mapping required for the first playable controller release.
for token in [
    'A:0','B:1','X:2','Y:3','LB:4','RB:5','LT:6','RT:7','MENU:9','UP:12','DOWN:13','LEFT:14','RIGHT:15',
    'DEADZONE=.22','REPEAT_DELAY_MS=360','REPEAT_MS=118','directionFrom(gamepad)', 'function processDirection(gamepad,now)',
    'nav()?.activate?.()', 'nav()?.back?.()', 'playAll()', 'cycleDrawer()', 'transport(-1)', 'transport(1)'
]:
    assert token in module, token

# Right stick scrolls the currently focused scrollable region. No analog cursor or
# mouse emulation belongs in v5.4.1; that fallback is intentionally deferred.
for token in ['function processRightStick(gamepad,dt)','scrollableAncestor(focus,\'y\')','scrollableAncestor(focus,\'x\')']:
    assert token in module, token
for forbidden in ['dispatchEvent(new MouseEvent','document.elementFromPoint','pointer cursor','radial-menu','RADIAL_']:
    assert forbidden not in module, forbidden

# LT/RT and stick-clicks are reserved for v5.4.2 rather than silently acquiring a
# conflicting action in this foundational controller release.
assert 'LT/RT and stick clicks are intentionally reserved for v5.4.2' in module
assert 'Reserved for v5.4.2 radial menus' in region_map

# Settings expose only Automatic/Disabled; automatic is the normal path.
for token in ['id="controllerSettingsCard"','id="controllerModeSelect"','<option value="automatic">Automatic</option>','<option value="disabled">Disabled</option>','id="controllerStatusValue"','id="controllerStatusHint"']:
    assert token in index, token

# The controller legend is compact and not interactive, so it cannot become a new
# unmapped focus target. Team-theme focus remains in the v5.4.0 semantic layer.
for token in ['sbb-controller-help','sbb-controller-help-grid','data-sbb-controller-active','prefers-reduced-motion']:
    assert token in css or token in module, token
assert '<button' not in module.split('function renderHelp',1)[1].split('function showHelp',1)[0]
assert '[data-sbb-controller-focus="1"]' in css

# Form controls remain usable: left/right adjusts sliders/selects instead of
# forcing focus away. Text entry stays focusable for keyboard/pointer takeover.
for token in ['adjustForm(direction)',"clean(el.type).toLowerCase()==='range'", "el.tagName==='SELECT'", "dispatchEvent(new Event('input'", "dispatchEvent(new Event('change'"]:
    assert token in module, token

# Controller discovery sleeps when no pad is present and rAF polling is used only
# while an active connected gamepad exists. This prevents a site-wide busy loop.
for token in ['DISCOVERY_MS=800','scheduleDiscovery()','requestAnimationFrame(poll)','cancelAnimationFrame(pollRaf)','if(!enabled()||!connected||pollRaf']:
    assert token in module, token

# Readiness remains the single semantic map and does not acquire Gamepad code.
for forbidden in ['navigator.getGamepads','gamepadconnected','gamepaddisconnected']:
    assert forbidden not in readiness, forbidden
for token in ['SBB_SEMANTIC_NAVIGATION','SBB_INTERACTION_REGIONS','SBB_INPUT_OWNERSHIP']:
    assert token in readiness, token

print(f'PASS v{VERSION} core controller mode: automatic takeover + semantic navigation + A/B/X/Y + LB/RB + safe scrolling')

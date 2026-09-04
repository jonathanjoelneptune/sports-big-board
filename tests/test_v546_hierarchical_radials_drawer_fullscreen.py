#!/usr/bin/env python3
"""v5.4.9 hierarchical controller radials, Game Center recovery, and fullscreen repair."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
assert VERSION=='5.4.9', VERSION
index=(ROOT/'index.html').read_text(encoding='utf-8')
core=(ROOT/'architecture'/'controller-mode-v542.js').read_text(encoding='utf-8')
fs=(ROOT/'ui'/'fullscreen-controller-v545.js').read_text(encoding='utf-8')
map_txt=(ROOT/'CONTROLLER-REGION-MAP-v5.4.9.md').read_text(encoding='utf-8')
verify=(ROOT/'VERIFY.sh').read_text(encoding='utf-8')

# Atomic frontend cache generation still advances together.
for asset in ['architecture/controller-mode-v542.js','ui/fullscreen-controller-v545.js']:
    assert f'{asset}?v={VERSION}' in index, asset
assert f"const VERSION='{VERSION}'" in core
assert f"const VERSION='{VERSION}'" in fs

# v5.4.9 remaps drawer/view ownership without regressing the hierarchical radial foundation.
assert '<b>${g.y}</b> Game Center / League View' in core
assert '<b>L3</b> Open / Close Drawer' in core
assert 'function toggleGameCenterLeagueView()' in core
assert 'if(index===BUTTON.Y){toggleGameCenterLeagueView();return;}' in core
assert 'function toggleInfoDrawerVisibility()' in core
assert 'if(index===BUTTON.LS){toggleInfoDrawerVisibility();return;}' in core
assert 'cycleDrawer()' not in core
for token in [
    "window.SBB_VIEWING_WORKSPACE?.setCollapsed",
    "window.SBB_INFO_DRAWER?.open?.(tab)",
    "active==='game-center'?'up-next':'game-center'",
    "return setDrawerCollapsed(true)",
]:
    assert token in core, token

# RT now forms a hierarchy: league -> scope, Special Events -> event -> scope.
assert "queueRadial('league-scope',{league:value,label,parent:'league'})" in core
assert "type==='league-scope'" in core
assert 'function leagueScopeOptions(context={})' in core
for token in ["value:'TODAY'","value:'ALL'","value:'BROWSE'"]:
    assert token in core, token
assert "label:browseLabel(league)" in core
assert "return playerBrowseLeague(league)?'PLAYER BROWSE':'TEAM BROWSE';" in core

# Special Events comes from the existing live menu/registry, not a second hard-coded list.
assert 'function specialEventNodes()' in core
assert "#sbbSpecialEventsMenu [data-special-competition]" in core
assert 'function openSpecialEventRadial()' in core
assert "openRadial('special-league'" in core
assert "queueRadial('special-scope'" in core
assert 'function specialScopeOptions(context={})' in core
assert "browseApi()?.enterSpecialContext?.(league,label)" in core

# LT Date/Scope also exposes contextual team/player browsing.
assert 'function dateScopeOptions(){const league=contextualLeague();return [' in core
assert "{value:'BROWSE',label:browseLabel(league)" in core

# Top-left app fullscreen stays in the trusted click turn and targets document root.
assert "function appTarget(){return document.documentElement;}" in fs
assert "requestFullscreen(appTarget(),{navigationUI:true})" in fs
assert "button.addEventListener('click',onClick,true)" in fs
assert "bindButton(APP_BUTTON);bindButton(VIDEO_BUTTON);" in fs
# Controller fullscreen retains explicit local bridge fallbacks.
assert "nativeCommand('app-fullscreen')" in fs
assert "nativeCommand('video-fullscreen')" in fs
assert "function fullscreenCommand(kind)" in core
assert "window.SBB_CONTROLLER_NATIVE_BRIDGE?.sendCommand?.(command)" in core

for token in [
    'Y / Triangle — toggle Game Center ↔ League View',
    'Hierarchical RT league radial',
    'SPECIAL EVENTS',
    'PLAYER BROWSE',
    'Fullscreen reliability',
]:
    assert token in map_txt, token
assert 'tests/test_v546_hierarchical_radials_drawer_fullscreen.py' in verify

print('PASS v5.4.9 hierarchical league/Special Event browse radials + Y view toggle + L3 drawer + fullscreen repair')

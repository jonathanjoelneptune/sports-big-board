#!/usr/bin/env python3
"""v5.4.8 controller polish: transport toggle, view/drawer mapping, browse parity, dense logos, fullscreen exit."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION=(ROOT/'VERSION').read_text().strip()
assert VERSION=='5.4.8',VERSION
index=(ROOT/'index.html').read_text()
core=(ROOT/'architecture'/'controller-mode-v542.js').read_text()
browse=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
fs=(ROOT/'ui'/'fullscreen-controller-v545.js').read_text()
css=(ROOT/'ui'/'controller-mode-v542.css').read_text()
fs_css=(ROOT/'ui'/'fullscreen-controller-v545.css').read_text()
verify=(ROOT/'VERIFY.sh').read_text()
map_txt=(ROOT/'CONTROLLER-REGION-MAP-v5.4.8.md').read_text()

for asset in ['architecture/controller-mode-v542.js','ui/fullscreen-controller-v545.js','ui/controller-mode-v542.css','ui/fullscreen-controller-v545.css']:
    assert f'{asset}?v={VERSION}' in index,asset
assert f"const VERSION='{VERSION}'" in core and f"const VERSION='{VERSION}'" in fs

# X/Square uses the canonical transport authority even when the on-screen button is hidden.
assert "const btn=document.getElementById('playBtn');" in core
assert 'if(btn){try{btn.click();return true;}' in core
assert "clickVisible('#playBtn')" not in core
assert 'if(index===BUTTON.X){playPause();return;}' in core
assert 'p.pauseVideo?.()' in core and 'p.playVideo?.()' in core

# Y toggles the two viewing modes; L3 independently owns drawer visibility.
assert '<b>${g.y}</b> Game Center / League View' in core
assert '<b>L3</b> Open / Close Drawer' in core
assert 'function toggleGameCenterLeagueView()' in core
assert "return openDrawerTab(active==='game-center'?'up-next':'game-center');" in core
assert 'if(index===BUTTON.Y){toggleGameCenterLeagueView();return;}' in core
assert 'function toggleInfoDrawerVisibility()' in core
assert 'if(index===BUTTON.LS){toggleInfoDrawerVisibility();return;}' in core

# Team/player radial is dense and logo-first.
assert 'const ENTITY_RADIAL_PAGE_SIZE=16' in core
assert 'controllerEntityEntries' in core
assert 'logo:clean(entry.logo)' in core
assert 'class="sbb-controller-entity-mark"' in core and '<img src="${esc(item.logo)}"' in core
assert 'data-radial-type="entity-browse"' not in core  # assigned dynamically, not duplicated markup
assert '.sbb-controller-radial[data-radial-type="entity-browse"]' in css
assert 'width:58px' in css and 'height:58px' in css

# Controller team selection binds league/special-event context, then calls the same historical entity authority as top Browse.
assert 'function controllerSelectEntityContext(league' in browse
assert 'function controllerBrowseEntity(league,entity' in browse
assert 'controllerSelectEntityContext(selected,{special,label});' in browse
assert 'return activateHistorical({entity:name});' in browse
assert 'controllerEntityEntries:league=>controllerEntityEntriesForLeague(league)' in browse
assert 'controllerBrowseEntity:(league,entity,options={})=>controllerBrowseEntity(league,entity,options)' in browse
assert 'api?.controllerBrowseEntity' in core

# Video fullscreen owns the stage-card so the radial stays available to exit.
assert "return document.querySelector('.stage-card')||$('stage')||activePlayerLayer();" in fs
assert "label:fs.videoFullscreen?'EXIT VIDEO FULLSCREEN':'VIDEO FULLSCREEN'" in core
assert 'function radialHost()' in core
assert "fs.matches?.('.stage-card,#stage')" in core
assert '.stage-card:fullscreen' in fs_css
assert '.stage-card:fullscreen #sbbControllerRadial' in fs_css
assert 'videoFullscreen' in fs

assert 'tests/test_v548_controller_polish.py' in verify
for token in ['X / Square — Play / Pause','Y / Triangle — toggle Game Center ↔ League View','L3 / Left Stick Click','16','logo','EXIT VIDEO FULLSCREEN']:
    assert token in map_txt,token
print('PASS v5.4.8 X play/pause + Y view toggle + L3 drawer + dense logo browse + team parity + fullscreen exit')

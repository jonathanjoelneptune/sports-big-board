#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
css=(ROOT/'ui'/'viewing-workspace-v5218.css').read_text()
js=(ROOT/'ui'/'viewing-workspace-v5218.js').read_text()

assert version=='5.3.9', version
assert f'ui/viewing-workspace-v5218.css?v={version}' in index
assert f'<script src="ui/viewing-workspace-v5218.js?v={version}"></script>' in index
assert index.index(f'ui/harmonized-controls-drawer-v5217.css?v={version}') < index.index(f'ui/viewing-workspace-v5218.css?v={version}') < index.index('</head>')
assert index.index(f'<script src="ui/harmonized-controls-drawer-v5217.js?v={version}"></script>') < index.index(f'<script src="ui/viewing-workspace-v5218.js?v={version}"></script>')

# Collapsing must free the real stage column, not merely hide drawer contents.
for token in [
    'body.sbb-game-center-side.sbb-drawer-collapsed .stage-card{',
    'grid-template-columns:minmax(0,1fr) var(--sbb-drawer-collapsed-width)!important',
    '--sbb-drawer-collapsed-width:36px',
    '#drawerCollapseToggle{',
    'body.sbb-drawer-collapsed #infoDrawer .info-drawer-head,',
]:
    assert token in css, token

# Game Center is hero -> full-width tabs -> one scrollable pane, with Coming Up
# outside that scroll context and locked to the bottom of the right workspace.
for token in [
    '#gameCenterPane{',
    'grid-template-rows:minmax(0,1fr) auto!important',
    '#gameCenterPane #gameCenterContent{',
    'grid-template-rows:auto auto minmax(0,1fr)!important',
    '#gameCenterPane #gcSections{',
    'grid-template-columns:repeat(4,minmax(0,1fr))!important',
    '#gameCenterPane .gc-section{',
    'overflow-y:auto!important',
    '#gameCenterPane .next-up-dock{',
]:
    assert token in css, token

# Persistent line score is no longer above every tab. It is mirrored into Overview.
assert '#gcPersistentSummary{display:none!important}' in css
assert '#gcOverviewBroadcastSummary{' in css
for token in [
    'renderOverviewEnhancements()',
    'SBB_GAME_CENTER_MULTISPORT_VIEW',
    "line=line.replace(/>LINESCORE(?=<|\\s)/,'>LINE SCORE')",
    "overview.insertAdjacentElement('afterbegin',host)",
]:
    assert token in js, token

# PREV / NEXT are plain centered text buttons. The footer is intentionally gone.
assert "prev.textContent='PREV'" in js
assert "next.textContent='NEXT'" in js
assert '#prevBtn::before,#prevBtn::after,#nextBtn::before,#nextBtn::after{content:none!important;display:none!important}' in css
assert '.player-footer,.lower-third.player-footer{display:none!important}' in css

# Grid resize gets announced after collapse so iframe/native/player observers can react.
assert "window.dispatchEvent(new Event('resize'))" in js
assert 'SBB_VIEW_PREFS?.refresh?.()' in js

for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==version, f'{asset}: {found} != {version}'

print('PASS v5.3.9 Game Center workspace reflow + real drawer collapse + Overview-only line score')

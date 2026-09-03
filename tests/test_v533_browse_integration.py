#!/usr/bin/env python3
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
js=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
assert version=='5.3.10',version
assert f'ui/browse-curated-programming-v537.css?v={version}' in index
assert f'<script src="ui/browse-curated-programming-v537.js?v={version}"></script>' in index

# Browse is visually and structurally attached to the selected league.
for token in [
    '#scoreFilters button[data-score-filter]:has(+ #sbbBrowseSubnav:not(.hidden)){',
    'border-radius:9px 0 0 9px!important',
    'border-radius:0 9px 9px 0',
    'active.insertAdjacentElement(\'afterend\',subnav)',
    "browseWord=state.entityType==='player'?'PLAYER BROWSE':'TEAM BROWSE'",
]:
    assert token in (css+js),token
assert 'id="sbbBrowseExit"' not in js

# Fullscreen menu must remain inside the fullscreenable app shell and reposition.
for token in [
    "(document.getElementById('app-shell')||document.body).appendChild(pop)",
    'function ensurePopoverHost()',
    "document.addEventListener('fullscreenchange'",
    "document.addEventListener('webkitfullscreenchange'",
    ':fullscreen .sbb-browse-popover',
]:
    assert token in (js+css),token

# Curated row exists only in a real curated mode and has one explicit EXIT action.
for token in [
    "const active=state.mode!=='daily'",
    'ribbon.hidden=!active',
    '>Exit Event</button>',
    "ribbon.hidden=true;ribbon.classList.add('hidden')",
]:
    assert token in js,token
assert '‹ DAY' not in js

# Cards are more readable and still mean start-here-and-play-older.
for token in [
    'font:790 11.4px/1.18 system-ui,sans-serif',
    'font:850 9.4px/1 system-ui,sans-serif',
    'function playFrom(index){const games=state.games.slice(index)',
    'function playAll(){return playGames(state.games',
]:
    assert token in (css+js),token

# Unsupported curated competitions cannot leak a stale Game Center from the last sport.
for token in [
    'function syncCuratedGameCenterContext(item)',
    "window.SBB_SELECTED_EVENT?.clear?.({reason:'curated competition has no Game Center'",
    "body?.classList.toggle('sbb-curated-no-game-center',unsupported)",
    'body.sbb-curated-no-game-center #gameCenterContent{display:none!important}',
    'syncCuratedGameCenterContext(state.queueItems[bounded])',
]:
    assert token in (js+css),token

# No continuous work introduced.
for forbidden in ['setInterval(', 'requestAnimationFrame(loop', 'data-curation-select', '+ QUEUE']:
    assert forbidden not in js,forbidden
for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==version,f'{asset}: {found} != {version}'
print('PASS v5.3.10 fullscreen-safe attached Browse, explicit EXIT, larger cards, and curated Game Center context sync')

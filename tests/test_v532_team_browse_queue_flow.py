#!/usr/bin/env python3
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
css=(ROOT/'ui'/'browse-curated-programming-v537.css').read_text()
js=(ROOT/'ui'/'browse-curated-programming-v537.js').read_text()
upnext=(ROOT/'ui'/'up-next-experience-v5217.js').read_text()
assert version=='5.4.2',version
for surface in [f'ui/browse-curated-programming-v537.css?v={version}',f'<script src="ui/browse-curated-programming-v537.js?v={version}"></script>']:
    assert surface in index,surface
# Team/Player Browse is a visual child of the active league, not a free-floating nav item.
for token in ['#sbbBrowseSubnav{','#scoreFilters button[data-score-filter]:has(+ #sbbBrowseSubnav:not(.hidden)){','sbb-browse-subnav-enter','@keyframes sbb-browse-subnav-in']:
    assert token in css,token
for token in [
    "subnav.id='sbbBrowseSubnav'", "active.insertAdjacentElement('afterend',subnav)",
    "browseWord=state.entityType==='player'?'PLAYER BROWSE':'TEAM BROWSE'",
]: assert token in js,token
# Popover close must be unambiguous even if the legacy .hidden rule loses source-order precedence.
for token in ['.sbb-browse-popover.hidden,.sbb-browse-popover[hidden]{display:none!important}', ".sbb-browse-popover .hidden{display:none!important}"]:
    assert token in css,token
for token in [
    'pop.hidden=!state.open', "pop.setAttribute('aria-hidden',state.open?'false':'true')",
    "event.target.closest('#sbbBrowseClose')", 'setOpen(false);\n    state.mode=\'history\'',
]: assert token in js,token
# Curated cards are now direct chronological queue starters; no per-card + QUEUE affordance remains.
assert 'data-curation-select' not in js
assert '+ QUEUE' not in js
assert '.sbb-curation-select{' not in css
assert 'function playFrom(index){const games=state.games.slice(index)' in js
assert 'function playAll(){return playGames(state.games' in js
assert "$('sbbFocusPlayAll')?.addEventListener('click',playAll)" in js
# Timeline and Up Next titles make the selected team/player explicit.
for token in ['function entityMatchupLabel(', 'return `${e} at ${h', 'return `${e} vs ${a', 'const queueTitle=entityMatchupLabel(away,home)']:
    assert token in js,token
assert "const curated=String(item?.queueTitle||'').trim();if(curated)return curated;" in upnext
assert 'title:queueTitle,queueTitle,sourceTitle,mediaTitle:sourceTitle' in js
# Static asset generation remains atomic.
for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==version,f'{asset}: {found} != {version}'
print('PASS v5.4.2 league-attached Browse submenu, reliable close, automatic chronological queue, and explicit matchup queue titles')

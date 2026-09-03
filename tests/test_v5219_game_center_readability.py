#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
css=(ROOT/'ui'/'game-center-readability-v5219.css').read_text()
js=(ROOT/'ui'/'game-center-readability-v5219.js').read_text()
upnext=(ROOT/'ui'/'up-next-experience-v5217.js').read_text()

assert version=='5.3.6', version
assert f'ui/game-center-readability-v5219.css?v={version}' in index
assert f'<script src="ui/game-center-readability-v5219.js?v={version}"></script>' in index
assert index.index(f'ui/viewing-workspace-v5218.css?v={version}') < index.index(f'ui/game-center-readability-v5219.css?v={version}') < index.index('</head>')
assert index.index(f'<script src="ui/viewing-workspace-v5218.js?v={version}"></script>') < index.index(f'<script src="ui/game-center-readability-v5219.js?v={version}"></script>')

# The active pane, not a child table or the whole drawer, owns vertical scrolling.
for token in [
    '#gameCenterPane #gameCenterContent>[data-gc-pane]:not(.hidden){',
    'overflow-y:auto!important',
    'scrollbar-gutter:stable!important',
    '#gameCenterPane .gc-table-scroll{',
    'overflow-y:visible!important',
    '#gameCenterPane>.next-up-dock{',
    'align-self:end!important',
]:
    assert token in css, token

# Readability and strong selected-state treatment.
for token in [
    '#gameCenterPane #gcSections .gc-section-tab.active,',
    'background:linear-gradient(180deg,#163d58 0%,#102d42 100%)!important',
    '#gameCenterPane .gc-player-team-tab{',
    'min-height:48px!important',
    '#gameCenterPane .gc-player-table th,',
    'font-size:11px!important',
    '#gameCenterPane .gc-play-row strong{font-size:11.5px!important',
]:
    assert token in css, token

# DOM post-processing keeps provider data intact while making labels readable.
for token in [
    'STAT_ABBR', 'polishSectionTabs()', 'polishPlayerTeams()',
    'abbreviatePlayerHeaders()', "btn.textContent='KEY PLAYS'",
    "span.textContent=label", "th.dataset.sbbStatFull=original",
    "btn.setAttribute('aria-selected',active?'true':'false')",
]:
    assert token in js, token

# Up Next is sourced from the canonical queue, not the current rendered row.
for token in [
    'canonicalProgramEntries(wanted=3)', 'visibleQueueEntries(wanted)',
    "state.source='visibleQueueEntries'", 'tuneEntry(entry)',
    'canonicalProgramEntries(3)',
]:
    assert token in upnext, token

# No provider-data truncation or artificial row caps are added by this release.
for forbidden in ['slice(0,3)', 'tbody tr:nth-child(n+4)', 'display:none!important/* rows */']:
    assert forbidden not in css+js, forbidden

for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==version, f'{asset}: {found} != {version}'

print('PASS v5.3.6 Game Center full-content scroll + readable stats + canonical Coming Up queue')

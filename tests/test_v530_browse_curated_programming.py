#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
css=(ROOT/'ui'/'browse-curated-programming-v535.css').read_text()
js=(ROOT/'ui'/'browse-curated-programming-v535.js').read_text()

assert version=='5.3.5', version
assert f'ui/browse-curated-programming-v535.css?v={version}' in index
assert f'<script src="ui/browse-curated-programming-v535.js?v={version}"></script>' in index

for token in [
    '#sbbBrowseBtn{', '.sbb-browse-popover{', '.sbb-curation-ribbon{',
    'body.sbb-curation-active .score-ribbon{display:none!important}',
    '.sbb-curation-card{', '#sbbCurationPlay{', '#sbbBrowseSubnav{',
]:
    assert token in css, token

for token in [
    "const VERSION='5.3.5'",
    'SBB_CURATED_BROWSE',
    "FAVORITES_KEY='sbb.curation.favorites.v1'",
    '/api/history/audit?',
    'MAX_AUDIT_ROWS=1000',
    "'ALL HIGHLIGHTS'",
    "'RANKED TODAY'",
    "'SEEDED TODAY'",
    'fetchAuditRows(state.league,state.entity,MAX_AUDIT_ROWS)',
    'String(b.date).localeCompare(String(a.date))',
    'scoreCardPlayableItems(match)',
    'scoreCardPlaybackSelection(match,candidates)',
    'PROGRAM=[...state.queueItems]',
    'GENERAL_PROGRAM=[...state.queueItems]',
    'tuneProgramIndexV5(bounded',
    'window.SBB_SCORE_INTERRUPT_QUEUE?.clear?.',
    'function playAll()',
    'state.games.slice(index)',
    'toggleFavorite',
    'patchRenderQueue()',
]:
    assert token in js, token

for forbidden in ['new MutationObserver', 'setInterval(', 'requestAnimationFrame(loop']:
    assert forbidden not in js, forbidden

# Every static asset in index must use the deployment generation.
for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==version, f'{asset}: {found} != {version}'

print('PASS v5.3.5 Browse + Curated Programming core: league facets, entity history, favorites, and chronological Play All queue')

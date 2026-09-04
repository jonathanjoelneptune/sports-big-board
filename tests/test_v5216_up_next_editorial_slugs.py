#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
css=(ROOT/'ui'/'editorial-slugs-up-next-v5216.css').read_text()
js=(ROOT/'ui'/'up-next-experience-v5217.js').read_text()

assert version=='5.4.2', version
assert f'ui/editorial-slugs-up-next-v5216.css?v={version}' in index
assert f'<script src="ui/up-next-experience-v5217.js?v={version}"></script>' in index
assert index.index(f'ui/premium-now-watching-v5215.css?v={version}') < index.index(f'ui/editorial-slugs-up-next-v5216.css?v={version}') < index.index('</head>')
assert index.index(f'app.js?v={version}') < index.index(f'architecture/key-info-current-v520.js?v={version}') < index.index(f'ui/up-next-experience-v5217.js?v={version}')

# Editorial slugs are centered, squared-off broadcast labels, not rounded SaaS pills.
for token in [
    '.key-info-item .key-info-type{',
    'display:inline-flex!important', 'align-items:center!important',
    'justify-content:center!important', 'height:18px!important',
    'border-radius:2px!important',
    'box-shadow:inset 3px 0 0 var(--sbb-slug-accent)!important',
    'ui-monospace'
]:
    assert token in css, token
assert 'border-radius:999px!important' not in css.split('Sports Ticker editorial slugs',1)[1].split('Persistent Coming Up dock',1)[0]

# Up Next is visible inside Game Center through a compact persistent shelf and the
# full tab uses a visual two-column card grid rather than dense diagnostic rows.
for token in [
    '.next-up-dock{', '.next-up-dock-grid{', '.next-up-dock-card{',
    '#upNextPane .queue-list{', 'grid-template-columns:repeat(2,minmax(0,1fr))!important',
    '#upNextPane .queue-thumb-wrap{', 'aspect-ratio:16/9!important',
    '#upNextPane .queue-meta-diagnostic{display:none!important}',
    '#upNextPane .queue-copy>strong{'
]:
    assert token in css, token

# Integration now prefers the canonical visibleQueueEntries() API so the shelf
# cannot mistake the current row for the next program. DOM rows remain fallback.
for token in [
    'sourceRows()', 'canonicalProgramEntries(wanted=3)', 'visibleQueueEntries(wanted)',
    'renderDock()', 'patchRenderQueue()', 'canonicalNextRow()', 'repairNextButton()',
    'row.click()', 'nextVisibleQueueIndex()', 'tuneEntry(entry)',
    "reason:'manual next control v5.4.2 fallback'"
]:
    assert token in js, token
for forbidden in ['let PROGRAM', 'const PROGRAM', 'setInterval(', 'new MutationObserver']:
    assert forbidden not in js, forbidden

# The repaired top NEXT button uses the same canonical visible-queue entry as the
# shelf; DOM row and nextVisibleQueueIndex remain bounded fallbacks.
assert "btn.onclick=()=>{" in js
assert 'const entry=canonicalProgramEntries(1)[0];' in js
assert 'if(entry&&tuneEntry(entry))return;' in js
assert 'const row=canonicalNextRow();' in js

# Atomic cache generation remains required across the whole release.
for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==version, f'{asset}: {found} != {version}'

print('PASS v5.4.2 editorial slugs + integrated Up Next + NEXT transport repair')

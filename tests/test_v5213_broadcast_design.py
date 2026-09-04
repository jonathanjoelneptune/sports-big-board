#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
css=(ROOT/'ui'/'broadcast-design-v5213.css').read_text()

assert version=='5.4.5', version
assert f'ui/broadcast-design-v5213.css?v={version}' in index
assert index.index('styles.css?v='+version) < index.index('ui/broadcast-design-v5213.css?v='+version) < index.index('</head>')

required=[
  '--sbb-surface:', '--sbb-line:', '--sbb-radius-lg:', '--sbb-shadow-1:',
  '.top-nav-header{', '.score-filters{', '.key-info-ribbon{', '.score-ribbon{',
  '.stage-card{', '.player-topbar{', '.transport-btn,', '.info-drawer{',
  '.gc-hero{', '.gc-section-tabs{', '.settings-card{',
  '.diagnostics-off .sport-feed-diagnostics', 'scrollbar-width:thin',
  '@media (prefers-reduced-motion:reduce)'
]
for token in required:
    assert token in css, f'missing broadcast design contract: {token}'

# v5.4.5 is presentation-only. Do not introduce script behavior or expensive
# glass/blur effects that can regress the v5.2.10 motion work.
for forbidden in ['<script', 'backdrop-filter', 'filter:blur(', 'animation:']:
    assert forbidden not in css, f'performance/behavior regression in design CSS: {forbidden}'

# The base behavior surfaces remain in the HTML; this release only restyles them.
for id_ in ['scoreCells','keyInfoTrack','stage','infoDrawer','gameCenterContent','settingsPane']:
    assert f'id="{id_}"' in index, f'missing stable UI surface: {id_}'

# Release labels and every cache-busted asset advance atomically.
assert f'<meta name="sbb-release-version" content="{version}"' in index
assert f'<title>Sports Big Board — v{version}</title>' in index
for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==version, f'{asset} cache version {found} != {version}'

print('PASS v5.4.5 broadcast design system presentation invariants')

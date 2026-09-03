#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
css=(ROOT/'ui'/'premium-masthead-v5214.css').read_text()

assert version=='5.3.5', version
assert f'<title>Sports Big Board — v{version}</title>' in index
assert 'const tabTitle=`Sports Big Board — v${version}`' in index
assert "window.addEventListener('pageshow',syncTabTitle)" in index
assert f'ui/premium-masthead-v5214.css?v={version}' in index
assert index.index('ui/broadcast-design-v5213.css?v='+version) < index.index('ui/premium-masthead-v5214.css?v='+version) < index.index('</head>')

required=[
  '.top-nav-header{', '.top-date-controls{', '.score-filters{',
  '.score-filters > button.active::after,', '.key-info-ribbon{',
  '.key-info-label::before{', '.sbb-sports-ticker-conveyor .key-info-item{',
  '.score-ribbon{', '.score-day-arrow{', '.score-cell{',
  '.score-cell.now-watching,', '.score-team-score{', '.highlight-type-label{',
  '@media (max-width:1100px)', '@media (max-width:760px)',
  '@media (prefers-reduced-motion:reduce)'
]
for token in required:
    assert token in css, f'missing premium masthead contract: {token}'

# This pass must remain presentation-only and must not trade polish for motion cost.
for forbidden in ['<script', 'backdrop-filter', 'filter:blur(', 'animation:', 'scroll-snap-type:']:
    assert forbidden not in css, f'performance/behavior regression: {forbidden}'

# The three stable top surfaces remain the same DOM owners.
for id_ in ['scoreFilters','keyInfoTrack','scoreCells','scoreDayIndicator']:
    assert f'id="{id_}"' in index, f'missing stable masthead surface: {id_}'

# Every cache-busted release asset must remain atomic.
for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==version, f'{asset} cache version {found} != {version}'

print('PASS v5.3.5 premium masthead + ticker + score ribbon presentation invariants')

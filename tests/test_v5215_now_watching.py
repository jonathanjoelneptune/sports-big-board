from pathlib import Path

root=Path(__file__).resolve().parents[1]
version=(root/'VERSION').read_text().strip()
index=(root/'index.html').read_text()
css=(root/'ui'/'premium-now-watching-v5215.css').read_text()

assert version=='5.3.0', version
assert f'ui/premium-now-watching-v5215.css?v={version}' in index
assert index.index(f'ui/premium-masthead-v5214.css?v={version}') < index.index(f'ui/premium-now-watching-v5215.css?v={version}') < index.index('</head>')

required=[
    '.now-playing-copy::before{',
    '.transport-play.primary{',
    'body.sbb-info-open.diagnostics-off .layout{',
    '.gc-hero{',
    '.gc-team-score{',
    '.gc-section-tabs{',
    '.gc-play-row.scoring{',
    '.game-center-empty{',
    '@media (max-width:760px)',
    '@media (prefers-reduced-motion:reduce)'
]
for token in required:
    assert token in css, token

for forbidden in ['backdrop-filter','filter:blur(','animation:','scroll-snap-type:']:
    assert forbidden not in css, forbidden

# Presentation-only contract: no script/module is introduced for this pass.
assert 'premium-now-watching-v5215.js' not in index
assert '<script' not in css.lower()

# Stable functional anchors remain present and unchanged in identity.
for anchor in ['id="currentTitle"','id="playBtn"','id="stage"','id="gameCenterContent"','id="gcSections"','id="infoDrawer"']:
    assert anchor in index, anchor

print('PASS v5.3.0 premium Now Watching presentation invariants')

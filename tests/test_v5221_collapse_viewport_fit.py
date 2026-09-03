#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
css=(ROOT/'ui'/'collapse-viewport-fit-v5221.css').read_text()
js=(ROOT/'ui'/'collapse-viewport-fit-v5221.js').read_text()

assert version=='5.3.20', version
assert f'ui/collapse-viewport-fit-v5221.css?v={version}' in index
assert f'<script src="ui/collapse-viewport-fit-v5221.js?v={version}"></script>' in index

for token in [
    'grid-template-columns:minmax(0,1fr) 0!important',
    'max-width:0!important',
    'top:50%!important',
    'transform:translateY(-50%)!important',
    '--sbb-collapsed-stage-height',
    'aspect-ratio:auto!important',
]:
    assert token in css, token

for token in [
    "const VERSION='5.3.20'",
    'stage.getBoundingClientRect().top',
    'viewportHeight()-top-bottomGap',
    "body.style.setProperty('--sbb-collapsed-stage-height'",
    "window.addEventListener('sbb:workspace-resize'",
    'window.visualViewport?.addEventListener',
    'SBB_COLLAPSE_VIEWPORT_FIT',
]:
    assert token in js, token

for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==version, f'{asset}: {found} != {version}'

print('PASS v5.3.20 zero-width drawer collapse + centered handle + viewport-fit player')

#!/usr/bin/env python3
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
css=(ROOT/'ui'/'browse-curated-programming-v531.css').read_text()
js=(ROOT/'ui'/'browse-curated-programming-v531.js').read_text()
fit_css=(ROOT/'ui'/'workspace-viewport-fit-v531.css').read_text()
fit_js=(ROOT/'ui'/'workspace-viewport-fit-v531.js').read_text()
assert version=='5.3.1',version
for surface in [
    f'ui/browse-curated-programming-v531.css?v={version}',
    f'ui/workspace-viewport-fit-v531.css?v={version}',
    f'<script src="ui/browse-curated-programming-v531.js?v={version}"></script>',
    f'<script src="ui/workspace-viewport-fit-v531.js?v={version}"></script>',
]: assert surface in index,surface
for token in [
    '#sbbBrowseExit{','.sbb-browse-suggestions{min-height:0;overflow-y:auto',
    '.sbb-curation-card-shell{','.sbb-curation-date-pill{','.sbb-curation-result{',
    '.sbb-curation-media-tier.tier-green{','.sbb-curation-media-tier.tier-extended{',
    '.sbb-curation-select{',
]: assert token in css,token
for token in [
    "const VERSION='5.3.1'",'placeBrowseControls()','positionPopover()','primeEntityCatalog()',
    "exit.textContent='EXIT BROWSE ×'", "browseWord=state.entityType==='player'?'PLAYER BROWSE':'TEAM BROWSE'",
    "fetch(apiUrl(`/api/history/scores?${p.toString()}`)", 'IntersectionObserver',
    "state.games.slice(index)", "'✓ QUEUED':'+ QUEUE'", 'sbb-curation-date-pill',
    'sbb-curation-media-tier', "window.dispatchEvent(new CustomEvent('sbb:browse-layout'",
]: assert token in js,token
for token in ['--sbb-workspace-stage-height','body.sbb-game-center-side .stage-card>.stage{','aspect-ratio:auto!important']:
    assert token in fit_css,token
for token in ["const VERSION='5.3.1'","body.classList.contains('sbb-game-center-side')",'viewportHeight()-top-bottomGap',"sbb:browse-layout",'SBB_WORKSPACE_VIEWPORT_FIT']:
    assert token in fit_js,token
for forbidden in ['new MutationObserver','setInterval(','requestAnimationFrame(loop']:
    assert forbidden not in js,forbidden
for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==version,f'{asset}: {found} != {version}'
print('PASS v5.3.1 contextual Browse, date-headed scored timeline, explicit queue affordance, and open/closed viewport fit')

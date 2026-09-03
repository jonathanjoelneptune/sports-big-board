#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
version=(ROOT/'VERSION').read_text().strip()
index=(ROOT/'index.html').read_text()
css=(ROOT/'ui'/'harmonized-controls-drawer-v5217.css').read_text()
js=(ROOT/'ui'/'harmonized-controls-drawer-v5217.js').read_text()
upnext=(ROOT/'ui'/'up-next-experience-v5217.js').read_text()

assert version=='5.3.11', version
assert f'ui/harmonized-controls-drawer-v5217.css?v={version}' in index
assert f'<script src="ui/harmonized-controls-drawer-v5217.js?v={version}"></script>' in index
assert f'<script src="ui/up-next-experience-v5217.js?v={version}"></script>' in index

for token in [
    '.player-footer .utility-controls{display:none!important}',
    '#drawerCollapseToggle{',
    'body.sbb-drawer-collapsed #infoDrawer{',
    '#gameCenterPane .next-up-dock{',
    '.sbb-sports-ticker-conveyor .key-info-item .key-info-type{',
    '#nextBtn::after{content:none!important;display:none!important}',
    '.transport .transport-btn .transport-label{',
]:
    assert token in css, token

for token in [
    'setTransportLabels()',
    'ensureDrawerToggle()',
    "STORAGE_KEY='sbb.drawer.collapsed.v1'",
    "prev.innerHTML='<span class=\"transport-label\"",
    "next.innerHTML='<span class=\"transport-label\"",
    "document.body.classList.toggle('sbb-drawer-collapsed'",
]:
    assert token in js, token

for token in [
    "if(window.SBB_UP_NEXT_EXPERIENCE?.version==='5.3.11') return;",
    "const pane=$('gameCenterPane');",
    'if(dock.parentElement!==pane) pane.appendChild(dock);',
    "reason:'manual next control v5.3.11 fallback'",
]:
    assert token in upnext, token

for asset,found in re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))\?v=([^"]+)"',index):
    assert found==version, f'{asset}: {found} != {version}'

print('PASS v5.3.11 drawer polish, harmonized controls, bottom-docked Coming Up, and collapsible drawer')

from pathlib import Path
root=Path(__file__).resolve().parents[1]
version=(root/'VERSION').read_text().strip()
assert version=='5.5.0',version
html=(root/'media-audit.html').read_text()
js=(root/'ui/media-audit-v550.js').read_text()
css=(root/'ui/media-audit-v550.css').read_text()
index=(root/'index.html').read_text()
pages_builder=(root/'cloud/github-pages/build_pages.py').read_text()

for token in ['MEDIA HEALTH AUDIT','AUDIT EVERYTHING','RETEST FAILED','AUDIT STALE','REHYDRATION JSON','FAILURES CSV','youtubeProbe','directProbe']:
    assert token in html,token
for token in ['/api/history/audit','/api/history/event/media','/api/history/media/runtime','PLAYING_TIME_ADVANCED','REPEATED_','NO_MEDIA','UNPLAYABLE','DEGRADED','FRESH_MS','STALE_MS','localStorage','runAudit','resumeRun','sports-big-board-media-rehydration']:
    assert token in js,token

assert 'href="media-audit.html"' in index
assert "const VERSION='5.5.0'" in js
assert 'ui/media-audit-v550.css?v=5.5.0' in html

# R6 preferred-package audit policy: audit through today only, certify one Green/Purple,
# rediscover preferred media before falling back to a bounded Blue reel.
for token in [
    "const PREFERRED_TIERS=Object.freeze(['green','extended'])",
    'const BLUE_FALLBACK_TARGET=3',
    "const AUDIT_POLICY='R6_PREFERRED_PACKAGE'",
    'g.date<=today',
    "'/api/history/event/discover'",
    'forcing targeted rediscovery before Blue fallback',
    "PREFERRED PACKAGE",
    "Blue skipped",
    'NON_VIDEO_MEDIA_URL',
    "if(t==='blue'&&anyPreferredPass(assets))",
    'bluePasses>=BLUE_FALLBACK_TARGET',
]:
    assert token in js,token
assert "if(anyPreferredPass(assets))return {state:'HEALTHY'" in js

# Deployment contract: creating the page in the repository is not enough.
# GitHub Pages must copy it into .pages-dist or the operator link will 404.
assert "'media-audit.html'" in pages_builder, 'media-audit.html missing from GitHub Pages artifact builder'
assert "Media Health Audit -> media-audit.html" in pages_builder

print('PASS v5.5.0 Media Audit R6 preferred-package policy + today cap + targeted rediscovery + Pages publication')

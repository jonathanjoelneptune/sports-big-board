from pathlib import Path
root=Path(__file__).resolve().parents[1]
version=(root/'VERSION').read_text().strip()
assert version=='5.5.0',version
html=(root/'media-audit.html').read_text()
js=(root/'ui/media-audit-v550.js').read_text()
css=(root/'ui/media-audit-v550.css').read_text()
index=(root/'index.html').read_text()
pages_builder=(root/'cloud/github-pages/build_pages.py').read_text()

for token in ['MEDIA HEALTH AUDIT','AUDIT EVERYTHING','RETEST FAILED','AUDIT STALE','RESET AUDIT','START AUDIT FROM','auditStartDate','auditReset','REHYDRATION JSON','FAILURES CSV','youtubeProbe','directProbe']:
    assert token in html,token
for token in ['/api/history/audit','/api/history/event/media','/api/history/media/runtime','PLAYING_TIME_ADVANCED','REPEATED_','NO_MEDIA','UNPLAYABLE','DEGRADED','FRESH_MS','STALE_MS','localStorage','runAudit','resumeRun','sports-big-board-media-rehydration']:
    assert token in js,token

assert 'href="media-audit.html"' in index
assert "const VERSION='5.5.0'" in js
assert 'ui/media-audit-v550.css?v=5.5.0' in html

# R7 audit policy: preferred-package logic remains, but queue eligibility is now
# final-state authoritative with a selectable newest audit date and one-click reset.
for token in [
    "const PREFERRED_TIERS=Object.freeze(['green','extended'])",
    'const BLUE_FALLBACK_TARGET=3',
    "const AUDIT_POLICY='R7_FINAL_ONLY_RESET_START_DATE'",
    'function finalInfo(row,event)',
    'type.completed===true',
    'finalAt>0||completed||statusFinal',
    "return {state:'WAITING_FINAL'",
    'function latestFinalDate()',
    'function selectedAuditStartDate()',
    'g.isFinal&&g.date<=startDate',
    'filter(g=>g&&g.isFinal&&g.date<=startDate)',
    'No FINAL games found on or before',
    'function resetAudit()',
    "localStorage.removeItem(STORE);localStorage.removeItem(RUN_STORE)",
    "'/api/history/event/discover'",
    'forcing targeted rediscovery before Blue fallback',
    "PREFERRED PACKAGE",
    "Blue skipped",
    'NON_VIDEO_MEDIA_URL',
    "if(t==='blue'&&anyPreferredPass(assets))",
    'bluePasses>=BLUE_FALLBACK_TARGET',
    'state.games.filter(g=>g.isFinal).map',
]:
    assert token in js,token
assert "if(anyPreferredPass(assets))return {state:'HEALTHY'" in js
assert '<option value="WAITING_FINAL">WAITING FINAL</option>' in html
assert 'class="danger">RESET AUDIT</button>' in html
assert 'type="date"' in html

# Deployment contract: creating the page in the repository is not enough.
# GitHub Pages must copy it into .pages-dist or the operator link will 404.
assert "'media-audit.html'" in pages_builder, 'media-audit.html missing from GitHub Pages artifact builder'
assert "Media Health Audit -> media-audit.html" in pages_builder

print('PASS v5.5.0 Media Audit R7 final-only queue + start date + reset + preferred-package policy + Pages publication')

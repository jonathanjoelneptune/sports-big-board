from pathlib import Path
root=Path(__file__).resolve().parents[1]
version=(root/'VERSION').read_text().strip()
assert version=='5.5.0',version
html=(root/'media-audit.html').read_text()
js=(root/'ui/media-audit-v550.js').read_text()
css=(root/'ui/media-audit-v550.css').read_text()
index=(root/'index.html').read_text()
for token in ['MEDIA HEALTH AUDIT','AUDIT EVERYTHING','RETEST FAILED','AUDIT STALE','REHYDRATION JSON','FAILURES CSV','youtubeProbe','directProbe']:
    assert token in html,token
for token in ['/api/history/audit','/api/history/event/media','/api/history/media/runtime','PLAYING_TIME_ADVANCED','REPEATED_','NO_MEDIA','UNPLAYABLE','DEGRADED','FRESH_MS','STALE_MS','localStorage','runAudit','resumeRun','sports-big-board-media-rehydration']:
    assert token in js,token
assert 'href="media-audit.html"' in index
assert "const VERSION='5.5.0'" in js
assert 'ui/media-audit-v550.css?v=5.5.0' in html
print('PASS v5.5.0 exhaustive Media Health Audit + persistent runtime certification + rehydration manifest')

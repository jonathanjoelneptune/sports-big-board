from pathlib import Path
root=Path(__file__).resolve().parents[1]
version=(root/'VERSION').read_text().strip()
assert version=='5.5.0',version
html=(root/'media-audit.html').read_text()
js=(root/'ui/media-audit-v550.js').read_text()
css=(root/'ui/media-audit-v550.css').read_text()
index=(root/'index.html').read_text()
service=(root/'media_audit_service.py').read_text()
probe=(root/'media-audit-probe.html').read_text()
installer=(root/'cloud/vm/INSTALL-MEDIA-AUDIT.sh').read_text()
deploy=(root/'cloud/gcp/DEPLOY-FROM-GITHUB.sh').read_text()
pages=(root/'cloud/github-pages/build_pages.py').read_text()

for token in ['MEDIA HEALTH AUDIT','AUDIT EVERYTHING','RETEST FAILED','AUDIT STALE','RESET AUDIT','FULL RECERTIFY','START AUDIT FROM','REHYDRATION JSON','FAILURES CSV','CANONICAL SERVER WORKER']:
    assert token in html,token
assert 'youtubeProbe' not in html
assert 'directProbe' not in html
assert 'youtube.com/iframe_api' not in html
assert 'ui/media-audit-v550.js?v=5.5.0-r9' in html
assert 'href="media-audit.html"' in index

# Browser is a console only. All control and inventory authority routes to the backend service.
for token in ['/api/media-audit','/start','/pause','/resume','/stop','/reset','/inventory','/event?event=','/rehydration.json','/failures.csv','Canonical audit results are stored in SQLite']:
    assert token in js,token
for forbidden in ['localStorage','YT.Player','directProbe','youtubeProbe','/api/history/media/runtime']:
    assert forbidden not in js,forbidden

# Canonical server-owned audit contract.
for token in [
    'AUDIT_GENERATION = "R9"',
    'history_media_audit_run',
    'history_media_audit_queue',
    'history_media_audit_asset_result',
    'history_media_canonical_package',
    'CANONICAL_BROWSER',
    'CANONICAL_MEDIA_AUDIT',
    'MEDIA_AUDIT_FAILED',
    'MEDIA_AUDIT_SUPERSEDED',
    'MEDIA_AUDIT_BLUE_SUPPRESSED',
    'BLUE_FALLBACK_TARGET',
    'TARGETED_REHYDRATION',
    '/api/history/event/discover',
    'WAITING_DISCOVERY_PRIORITY',
    'Never jump ahead of a lower ordinal non-terminal item.',
    'ORDER BY ordinal ASC LIMIT 1',
    'events.sort',
    'scheduledKey',
    'queueOrdinal',
    'WAITING_PROBE_INFRASTRUCTURE',
    'event_date DESC',
    'if not selected["green"] or not selected["extended"]',
    'if not preferred:',
    'len(selected["blue"]) >= BLUE_FALLBACK_TARGET',
    'association_state=\'ASSIGNED\'',
    'state = QUARANTINED',
    'browserOwned',
]:
    assert token in service,token

# Special Events/tennis cannot be starved by the old HISTORY_LEAGUES API gate: queue comes from the normalized catalog directly.
assert 'SELECT canonical_event_key,league,event_id,event_date,event_json,final_at FROM history_catalog_event' in service
assert 'HISTORY_LEAGUES' not in service

# Controlled production-origin browser probe proves real playback advancement.
for token in ['window.SBB_MEDIA_PROBE','PLAYING_TIME_ADVANCED','YOUTUBE_EMBED_DISABLED','YOUTUBE_UNAVAILABLE','DIRECT_MEDIA_ERROR_','currentTimeDelta','youtube-nocookie.com','location.origin']:
    assert token in probe,token

# VM deployment owns Chrome/Selenium and a persistent systemd worker.
assert 'QUEUE #' in js
assert 'SBB_MEDIA_AUDIT_TIMEZONE' in service

for token in ['google-chrome-stable','selenium==4.27.1','sports-big-board-media-audit.service','127.0.0.1:8091','handle_path /api/media-audit/*','media_audit_service.py','Canonical audit service is healthy']:
    assert token.lower() in installer.lower(),token
for token in ['INSTALL-MEDIA-AUDIT.sh','sports-big-board-media-audit','/api/media-audit/status','canonical Media Audit API is public and server-owned']:
    assert token in deploy,token

# GitHub Pages publishes the operator console and the exact-origin probe page.
assert "'media-audit.html'" in pages
assert "'media-audit-probe.html'" in pages
assert 'Canonical Media Probe -> media-audit-probe.html' in pages

print('PASS v5.5.0 R9 canonical backend-owned Media Health Audit + deterministic all-competition queue + canonical playback package')

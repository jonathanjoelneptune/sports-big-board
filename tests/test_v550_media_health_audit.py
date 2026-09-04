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

for token in ['MEDIA HEALTH AUDIT','AUDIT EVERYTHING','RETEST FAILED','AUDIT STALE','RESET AUDIT','FULL RECERTIFY','START AUDIT FROM','REHYDRATION JSON','FAILURES CSV','CANONICAL AUDIT DIAGNOSTICS']:
    assert token in html,token
assert 'youtubeProbe' not in html
assert 'directProbe' not in html
assert 'youtube.com/iframe_api' not in html
assert 'ui/media-audit-v550.js?v=5.5.0-r11p' in html
assert 'href="media-audit.html"' in index

# Browser is a console only. All control and inventory authority routes to the backend service.
for token in ['/api/media-audit','/start','/pause','/resume','/stop','/reset','/inventory','/event?event=','/rehydration.json','/failures.csv']:
    assert token in js,token
for forbidden in ['localStorage','YT.Player','directProbe','youtubeProbe','/api/history/media/runtime']:
    assert forbidden not in js,forbidden

# Canonical server-owned audit contract.
for token in [
    'AUDIT_GENERATION = "R11"',
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
    'events.sort',
    'scheduledKey',
    'queueOrdinal',
    'WAITING_PROBE_INFRASTRUCTURE',
    'event_date DESC',
    'if not selected["green"] and not selected["extended"]',
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

# R10/R11: production playback parity, DB-lock recovery, diagnostics, and hard run replacement.
for token in [
    'WAITING_DATABASE_LOCK',
    '_is_db_locked',
    'recover_exception_failures',
    'RECOVERED_EXCEPTION_RETRY',
    'WORKER_EXCEPTION_RETRIES',
    'DB_LOCK_RETRY_SECONDS',
    '/api/history/event/media?',
    '_load_assets_with_production_parity',
    'productionPlayableCount',
    'DISCOVERY_PASSES',
    'Only rehydrate when no preferred recap candidate survives canonical playback',
    'recoveredExceptionFailures',
]:
    assert token in service,token
for token in [
    'diagDbState','diagDbOp','diagDbRetries','diagParity','diagCandidates',
    'diagCandidate','diagAsset','diagProbe','diagDiscovery','diagWaiting',
    'diagProgressAge','diagTrace','SERVER TRACE','DATABASE + PRODUCTION PARITY'
]:
    assert token in html or token in js,token
assert "const GENERATION='R11-PARALLEL'" in js
assert 'localStorage' not in js

# R11: reset/start/stop retire the worker itself and stale run work cannot persist.
for token in [
    'WORKER_CONTROL_LOCK',
    '_retire_worker',
    '_spawn_worker',
    'RUN_REPLACED',
    'current_after_probe',
    'current_after_request',
    'DISCOVERY_HTTP_TIMEOUT_SECONDS',
    'Canonical audit worker retired',
    'new audit run requested',
    'idle after reset',
]:
    assert token in service,token
assert 'current = self.store.run_snapshot(int(run["id"]))' in service
assert 'current = self.store.active_run()' not in service[service.index('def _discover_preferred'):service.index('def audit_event')]
assert "if(!confirm('RESET AUDIT will stop the current server worker" in js
assert "if(!recertify)return command('/reset'" not in js

# R11 startup-lock repair: the audit service must not initialize the main HistoryRepository
# during service startup, and existing audit schemas must use a read-first/no-write path.
for token in [
    'AUDIT_SCHEMA_TABLES',
    'def _schema_ready(self):',
    'def _ensure_schema(self):',
    "SELECT name FROM sqlite_master WHERE type='table'",
    'SQLite busy during audit schema startup; retrying',
]:
    assert token in service,token
assert 'self.repo = HistoryRepository' not in service
assert 'HistoryRepository(self.db_path)' not in service


# R11 bounded-rehydration repair: non-priority discovery failures must return to
# the outer pass loop instead of sleeping forever inside pass 1.
disc=service[service.index('def _discover_preferred'):service.index('def audit_event')]
for token in [
    'Discovery transport timed out; continuing bounded rehydration',
    'advancing bounded retry',
    'DISCOVERY_TRANSPORT_',
]:
    assert token in disc,token
assert 'except (URLError, TimeoutError) as exc:' in disc
# Priority mode is intentionally allowed to wait on the same ordinal, but generic
# transport/HTTP failures are bounded by DISCOVERY_PASSES.
transport_block=disc[disc.index('except (URLError, TimeoutError) as exc:'):]
assert 'time.sleep(DISCOVERY_RETRY_SECONDS)' not in transport_block


# R11 parallel audit lanes + bounded discovery timeout repair.
for token in [
    'AUDIT_WORKER_COUNT', 'SBB_MEDIA_AUDIT_WORKERS', 'DISCOVERY_CONCURRENCY',
    'DISCOVERY_SEMAPHORE', 'worker_lane', 'commit_turn_ready', 'WAITING_COMMIT_ORDER',
    'Parallel workers claim adjacent PENDING ordinals in deterministic order.',
    '_spawn_workers', '_retire_workers', '_worker_status_payload', '"workers": worker_rows',
]:
    assert token in service,token
assert "state='PENDING' ORDER BY ordinal ASC LIMIT 1" in service
assert 'Earlier queue ordinal is still being certified' in service
assert 'Targeted discovery pass {pass_number}/{DISCOVERY_PASSES} transport failure; advancing bounded retry' in service
for token in ['PARALLEL WORKER LANES','diagWorkers']:
    assert token in html or token in js,token

print('PASS v5.5.0 R11 canonical Media Health Audit + 3-lane parallel probing + ordered canonical commits + bounded rehydration + reset/startup-lock/parity diagnostics')

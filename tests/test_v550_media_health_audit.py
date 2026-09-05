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
assert 'ui/media-audit-v550.js?v=5.5.0-r16' in html
assert 'ui/media-audit-v550.css?v=5.5.0-r16' in html
assert 'href="media-audit.html"' in index

# Browser is a console only. All control and inventory authority routes to the backend service.
for token in ['/api/media-audit','/start','/pause','/resume','/stop','/reset','/inventory','/event?event=','/rehydration.json','/failures.csv']:
    assert token in js,token
for forbidden in ['localStorage','YT.Player','directProbe','youtubeProbe','/api/history/media/runtime']:
    assert forbidden not in js,forbidden

# Canonical server-owned audit contract.
for token in [
    'AUDIT_GENERATION = "R16-AUDIT-REPAIR-SEPARATION"',
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
    '/api/history/event/discover',
    'WAITING_DISCOVERY_PRIORITY',
    'events.sort',
    'scheduledKey',
    'queueOrdinal',
    'event_date DESC',
    'if not preferred:',
    'len(selected["blue"]) >= BLUE_FALLBACK_TARGET',
    'association_state=\'ASSIGNED\'',
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
    'recoveredExceptionFailures',
]:
    assert token in service,token
for token in [
    'diagDbState','diagDbOp','diagDbRetries','diagParity','diagCandidates',
    'diagCandidate','diagAsset','diagProbe','diagDiscovery','diagWaiting',
    'diagProgressAge','diagTrace','SERVER TRACE','DATABASE + PRODUCTION PARITY'
]:
    assert token in html or token in js,token
assert "const GENERATION='R16-AUDIT-REPAIR-SEPARATION'" in js
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



# R11 serialized audit DB writer: browser results are retained while SQLite is busy.
for token in [
    'class SerializedAuditDbWriter',
    'canonical-media-audit-db-writer',
    'self.jobs = queue.Queue',
    'Preserve this exact queued result and retry the database write.',
    'PROBE_COMPLETE_WAITING_DB',
    'CANONICAL_PACKAGE_WAITING_DB',
    'pendingDbWrite',
    'DB_WRITE_QUEUE_MAX',
    'DB_WRITER = SerializedAuditDbWriter(STORE)',
    '"dbWriter": DB_WRITER.snapshot()',
]:
    assert token in service,token
probe_block=service[service.index('def _probe_candidate'):service.index('def _select_one')]
assert 'self.store.record_probe' not in probe_block
assert '"record_probe"' in probe_block
assert 'waiting for serialized DB writer' in probe_block
worker_block=service[service.index('class CanonicalAuditWorker'):service.index('STORE = AuditStore')]
for forbidden in [
    'self.store.record_probe(', 'self.store.queue_phase(', 'self.store.canonicalize(',
    'self.store.finish_queue_item(', 'self.store.requeue_item(', 'self.store.next_queue_item(',
    'self.store.complete_run_if_done(',
]:
    assert forbidden not in worker_block,forbidden
for token in ['DB WRITER','SAVE QUEUED','status.dbWriter']:
    assert token in js,token


# R11 playable-evidence protection: transient headless failures cannot revoke a
# recent real-browser PLAYED success or falsely quarantine its event association.
for token in [
    'PLAYABLE_EVIDENCE_FRESH_SECONDS',
    'TRANSIENT_MEDIA_FAILURE_REASONS',
    'def _transient_media_failure_reason',
    'def _recent_playable',
    'retainedPriorSuccess',
    'effectiveRuntimeState',
    'RECENT_PLAYBACK_RETAINED',
    'recover_transient_playable_quarantines',
    'MEDIA_AUDIT_RETAINED_PLAYABLE',
    'RECOVERED_PLAYABLE_EVIDENCE',
    '"recoveredPlayableEvidence": PLAYABLE_RECOVERY',
]:
    assert token in service,token
record_block=service[service.index('def record_probe'):service.index('def canonicalize')]
for token in ['probe_state = "PLAYED"', '"HARD_FAILED"', '"INFRA_ERROR"', '"INCONCLUSIVE"', 'Only definitive hard evidence can', 'effective_state = prior_runtime']:
    assert token in record_block,token
assert 'elif hard_failure:' in record_block
assert 'runtime_failure_at=CASE WHEN ? THEN ? ELSE runtime_failure_at END' in record_block
select_block=service[service.index('def _select_one'):service.index('@staticmethod',service.index('def _select_one'))]
assert 'RECENT_PLAYBACK_RETAINED' in select_block
assert '_transient_media_failure_reason(result.get("reason"))' in select_block
for token in ['recent-playable asset','false-unplayable game','playableRecovery']:
    assert token in js,token


# R12 failure-hardening: audit infrastructure/soft negatives are non-destructive.
for token in [
    'CHROMEDRIVER_READ_TIMEOUT', 'SELENIUM_TIMEOUT', 'INFRA_RETRIES',
    'def _infra_result_from_exception', 'def _infra_failure_reason',
    'DEFERRED_INFRA', 'def defer_queue_item', '"DEFERRED"',
    'SOFT_RETRY_FRESH_BROWSER', 'recreating Chrome before independent retry',
    '"INCONCLUSIVE"', 'Independent soft-negative probes remain inconclusive',
    'MEDIA_AUDIT_FALLBACK_AVAILABLE', 'MEDIA_AUDIT_ALTERNATE_AVAILABLE',
    'recover_healthy_audit_alternatives', 'preferenceSeparatedFromValidity',
    'class AuditStatusCache', 'memory-only', 'statusCacheAgeSeconds',
    'SQL-filtered/paginated operator inventory', 'LIMIT ? OFFSET ?',
    'ENDPOINT_UNSUPPORTED_SPECIAL_EVENT', 'DISCOVERY_ENDPOINT_UNSUPPORTED_SPECIAL_EVENT',
]:
    assert token in service,token

# Chrome creation itself must be protected; _ensure cannot sit outside the try.
probe_class=service[service.index('class BrowserProbe'):service.index('class AuditRunReplaced')]
probe_fn=probe_class[probe_class.index('def probe'): ]
assert probe_fn.index('try:') < probe_fn.index('driver = self._ensure()')
assert '_infra_result_from_exception(exc)' in probe_fn

# Infrastructure evidence is persisted but cannot become global media failure.
assert 'infra_failure = bool(result.get("infra")) or _infra_failure_reason(reason)' in record_block
assert 'elif hard_failure:' in record_block
assert 'effective_state = prior_runtime' in record_block

# Only hard-failed alternatives may be quarantined; nonpreferred healthy media remain ASSIGNED.
canon=service[service.index('def canonicalize'):service.index('def inventory')]
assert 'hard_failed = meta["runtime"] == "FAILED" and _hard_media_failure_reason' in canon
assert 'state = ASSIGNED' in canon
assert 'MEDIA_AUDIT_FALLBACK_AVAILABLE' in canon
assert 'MEDIA_AUDIT_ALTERNATE_AVAILABLE' in canon

# Deferred infrastructure is terminal for queue ordering so later ordinals can commit.
assert "state NOT IN ('DONE','FAILED','SKIPPED','DEFERRED')" in service
assert "state IN ('DONE','FAILED','SKIPPED','DEFERRED')" in service

# Operator status and inventory failure domains are split.
for token in ['metricInconclusive','diagHeartbeat','diagInventoryState','diagStatusCacheAge','INCONCLUSIVE']:
    assert token in html or token in js,token
for token in ['statusFailures','inventoryError','Inventory refresh delayed','Heartbeat failed','STATUS DELAYED','document.hidden']:
    assert token in js,token
status_fn=js[js.index('async function refreshStatus'):js.index('async function command')]
assert 'await refreshInventory()' not in status_fn
assert 'refreshInventory();' in status_fn

# Special-event legacy endpoint rejection is compatibility telemetry, not media failure.
assert 'SPECIAL EVENT ENDPOINT UNSUPPORTED • normalized catalog authoritative' in js

assert '.health.INCONCLUSIVE' in css
assert 'repeat(11,minmax(108px,1fr))' in css

# R12 recovery repairs old false-negative packages and exposes inconclusive/deferred work.
for token in ['preservedRecentPlayable','removedFalsePackages','RECOVERED_NONHARD_FAILURE','RECERTIFICATION_REQUIRED']:
    assert token in service or token in js,token
assert "q.health='INCONCLUSIVE' OR q.state='DEFERRED'" in service


# R11 deployment quiescence/readiness contract: the canonical audit service shares
# SQLite with the main backend and must not remain active through catalog preflight.
deploy=(root/'cloud/gcp/DEPLOY-FROM-GITHUB.sh').read_text()
stop_audit='systemctl stop sports-big-board-media-audit >/dev/null 2>&1 || true'
stop_backend='systemctl stop sports-big-board >/dev/null 2>&1 || true'
assert stop_audit in deploy, 'deployment must stop canonical audit before backend/catalog restart'
assert deploy.index(stop_audit) < deploy.index(stop_backend, deploy.index(stop_audit)), 'audit service must stop before main backend'
assert 'LOCAL_HEALTH_ATTEMPTS="${SBB_LOCAL_HEALTH_ATTEMPTS:-180}"' in deploy, 'cold-start health window must be bounded and configurable at 180 attempts'
assert deploy.index('systemctl restart sports-big-board') < deploy.index('Installing canonical Media Health Audit service'), 'main backend must be healthy before audit service restart'


# R16 audit/repair separation: audit certifies existing media only; Repair Engine owns discovery.
assert 'R16-AUDIT-REPAIR-SEPARATION' in service
for token in [
    'history_media_repair_queue','history_media_repair_candidate','class MediaRepairEngine',
    'canonical-media-repair-engine','REPAIR_ENABLED','REPAIR_DISCOVERY_PASSES','REPAIR_CERT_ATTEMPTS',
    'def seed_repair_queue','def claim_repair_job','def mark_repair_discovered',
    'MEDIA_REPAIR_DISCOVERED','MEDIA_REPAIR_CERTIFIED','MEDIA_REPAIR_FAILED',
    'promote_repaired_candidate','canonicalWriteBack','SBB_MULTI_PROVIDER_DISCOVERY',
    'repairMode','searchDepth','exhaustive','targetTier',
    'repairSummary','"repair": {**','/repairs',
]:
    assert token in service,token

# Repair first reuses the existing Sports Big Board multi-provider discovery authority,
# then has a quota-bounded direct YouTube fallback for gaps/special events.
for token in ['YouTubeGateway','YOUTUBE_API_KEY','REPAIR_YOUTUBE_FALLBACK','REPAIR_YOUTUBE_QUERY_LIMIT',
              'def _youtube_fallback_candidates','Direct YouTube repair fallback','ingest_repair_youtube_candidates',
              'publishedAfter','publishedBefore','MEDIA_REPAIR_DISCOVERED']:
    assert token in service,token

audit_block=service[service.index('def audit_event'):service.index('class MediaRepairEngine')]
assert '_discover_preferred(' not in audit_block
assert 'TARGETED_REHYDRATION' not in audit_block
assert 'certification-only policy' in audit_block
assert 'finish_queue_item() then' in audit_block

# Audit completion automatically synchronizes repair work; HEALTHY closes it.
finish_block=service[service.index('def finish_queue_item'):service.index('def complete_run_if_done')]
assert '_sync_repair_job_conn' in finish_block
assert '"INCONCLUSIVE"' in finish_block
sync_block=service[service.index('def _sync_repair_job_conn'):service.index('def seed_repair_queue')]
for token in ['CLOSED_HEALTHY','PENDING','SEARCHING','CERTIFYING']:
    assert token in sync_block,token
for token in ['NO_MEDIA','UNPLAYABLE','DEGRADED','INCONCLUSIVE','PREFERRED','RECERTIFY']:
    assert token in service,token

# Newly discovered repair media is hidden until certified, then promoted into the shared canonical package.
mark_block=service[service.index('def mark_repair_discovered'):service.index('def record_repair_candidate')]
assert "association_state='UNVERIFIED'" in mark_block
assert "association_method='MEDIA_REPAIR_DISCOVERED'" in mark_block
promote_block=service[service.index('def promote_repaired_candidate'):service.index('def _eligible_events')]
for token in ["runtime_state", "!='PLAYED'", "association_state='ASSIGNED'", "association_method='MEDIA_REPAIR_CERTIFIED'",
              'history_media_canonical_package','history_media_audit_queue','HEALTHY','DEGRADED']:
    assert token in promote_block,token

# Repair writes share the one serialized DB writer rather than introducing another SQLite writer lane.
repair_class=service[service.index('class MediaRepairEngine'):service.index('class AuditStatusCache')]
assert 'self.db_writer.submit' in repair_class
assert 'lane=99' in repair_class
for forbidden in ['self.store.promote_repaired_candidate(', 'self.store.record_repair_candidate(', 'self.store.claim_repair_job(', 'self.store.seed_repair_queue(']:
    assert forbidden not in repair_class,forbidden

# Operator console exposes the synchronized repair engine.
for token in ['REPAIR QUEUE','REPAIRED','MEDIA REPAIR ENGINE','repairState','repairQueue','repairGame','repairTarget','repairPhase','repairTotals']:
    assert token in html or token in js,token
assert "AUDIT DISCOVERY DISABLED • Repair Engine owns discovery" in js
assert '/repairs' in service

print('PASS v5.5.0 R16 certification-only audit + synchronized Media Repair Engine + canonical repair write-back')


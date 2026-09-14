#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
service=(ROOT/'media_audit_service.py').read_text(encoding='utf-8')
ui=(ROOT/'ui'/'media-audit-v550.js').read_text(encoding='utf-8')
materializer=(ROOT/'tools'/'apply_v6116_release.py').read_text(encoding='utf-8')
verify=(ROOT/'VERIFY.sh').read_text(encoding='utf-8')

for token in (
    'REPAIR_SALVAGE_CANDIDATE_LIMIT',
    'REPAIR_SALVAGE_STALE_SECONDS',
    'R21_KNOWN_CANDIDATE_SALVAGE',
    'def refresh_repair_known_transport(self, event_key, assets):',
    'def _repair_plan_snapshot(self, job):',
    'def _merge_salvage_transport(self, known_assets, plan_assets):',
    'def _salvage_classification(self, asset, now=None):',
    'def _salvage_known_candidates(self, job, assets, target, tested):',
    "'KNOWN_TRANSPORT_REFRESH'",
    "'KNOWN_CANDIDATE_SALVAGE'",
    "phase='SALVAGE_KNOWN_CANDIDATE'",
    "self.stats['salvageTransportRefreshes']",
    "self.stats['salvageTransportRecovered']",
    "self.stats['salvageTransportPersisted']",
    "self.stats['salvageCandidatesSelected']",
    "self.stats['salvageCertified']",
    "self.stats['salvagePromotions']",
    "self.stats['salvageClosedHealthy']",
    "if (runtime=='FAILED' or assoc=='QUARANTINED') and _hard_media_failure_reason(failure):",
):
    assert token in service, token

# Salvage runs before any fresh discovery consumes provider/search budget.
repair=service.split('    def _repair_by_discovery(self, job):',1)[1].split('    @staticmethod\n    def _retry_at',1)[0]
assert repair.index('_salvage_known_candidates') < repair.index('_deep_catalog_candidates') < repair.index('_discover_once')
assert "if promoted and promoted.get('health')=='HEALTHY': return promoted" in repair

# Production plan is read-only transport recovery, not fresh discovery.
snapshot=service.split('    def _repair_plan_snapshot(self, job):',1)[1].split('    @staticmethod\n    def _salvage_identity',1)[0]
assert '/api/history/event/media?' in snapshot
assert '/api/history/event/discover' not in snapshot
assert 'timeout=min(15,DISCOVERY_HTTP_TIMEOUT_SECONDS)' in snapshot

# Exact assetKey first, then conservative provider/media-id identity fallback.
merge=service.split('    def _merge_salvage_transport(self, known_assets, plan_assets):',1)[1].split('    def _salvage_classification',1)[0]
assert 'by_key' in merge and 'by_identity' in merge
assert 'fresh=by_key.get(key)' in merge
assert "asset['_salvageTransportRefreshed']=True" in merge
assert 'transportRecovered' in merge and 'transportChanged' in merge

# Fresh transport is durably persisted before a probe can promote the asset.
store_refresh=service.split('    def refresh_repair_known_transport(self, event_key, assets):',1)[1].split('    def record_repair_source_attempt',1)[0]
assert 'UPDATE history_source_media SET provider=?' in store_refresh
assert "item['url']=url; item['externalUrl']=url; item['mediaUrl']=url" in store_refresh
assert 'runtime_state' not in store_refresh.lower()
salvage=service.split('    def _salvage_known_candidates(self, job, assets, target, tested):',1)[1].split('    def _eligible_known_candidates',1)[0]
assert salvage.index('persist salvage transport refresh') < salvage.index('_certify_candidates')
assert 'refresh_repair_known_transport' in salvage

# Hard failures remain terminal; soft/transient/stale states are salvageable.
classification=service.split('    def _salvage_classification(self, asset, now=None):',1)[1].split('    def _salvage_known_candidates',1)[0]
for token in ('RECENT_PLAYED','STALE_PLAYED','TRANSIENT_FAILURE','INFRA_FAILURE','STALE_NONHARD_FAILURE','UNVERIFIED_KNOWN'):
    assert token in classification

# Deployment must not wake every cooling repair job. R21 appears in the repair
# strategy, never as a seed-time mass-requeue marker.
seed=service.split('    def seed_repair_queue(self):',1)[1].split('    def repair_liveness',1)[0]
assert "NOT LIKE '%R21_KNOWN_CANDIDATE_SALVAGE%'" not in seed
assert 'R21 known-candidate salvage strategy upgrade: immediate one-time retry' not in seed
assert 'R21_KNOWN_CANDIDATE_SALVAGE' in repair

# Operator telemetry exposes the lane; overcomplete copy also receives raw stats.
for token in ('transport refreshes','persisted','salvage selected','salvage certified','salvage closed'):
    assert token in ui, token

# Historical release replay must restore this lane at v6.1.16.
assert '"tools/patch_media_repair_salvage_v6116.py"' in materializer
assert '"tests/test_media_repair_salvage_v6116.py"' in materializer
assert 'patch_media_repair_salvage_v6116.py' in materializer
assert 'tests/test_media_repair_salvage_v6116.py' in verify
assert 'tools/patch_media_repair_salvage_v6116.py' in verify

print('PASS v6.1.16 durable Known Candidate Salvage / Revalidation lane contract')

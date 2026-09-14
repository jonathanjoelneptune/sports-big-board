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
    'def _repair_plan_snapshot(self, job):',
    'def _merge_salvage_transport(self, known_assets, plan_assets):',
    'def _salvage_classification(self, asset, now=None):',
    'def _salvage_known_candidates(self, job, assets, target, tested):',
    "'KNOWN_TRANSPORT_REFRESH'",
    "'KNOWN_CANDIDATE_SALVAGE'",
    "phase='SALVAGE_KNOWN_CANDIDATE'",
    "self.stats['salvageTransportRefreshes']",
    "self.stats['salvageTransportRecovered']",
    "self.stats['salvageCandidatesSelected']",
    "self.stats['salvageCertified']",
    "self.stats['salvagePromotions']",
    "self.stats['salvageClosedHealthy']",
    "if (runtime=='FAILED' or assoc=='QUARANTINED') and _hard_media_failure_reason(failure):",
):
    assert token in service, token

# Salvage must happen before local/fresh discovery consumes provider or search budget.
repair=service.split('    def _repair_by_discovery(self, job):',1)[1].split('    @staticmethod\n    def _retry_at',1)[0]
assert repair.index('_salvage_known_candidates') < repair.index('_deep_catalog_candidates') < repair.index('_discover_once')
assert "if promoted and promoted.get('health')=='HEALTHY': return promoted" in repair

# Production media-plan refresh is a read-only transport source, not fresh discovery.
snapshot=service.split('    def _repair_plan_snapshot(self, job):',1)[1].split('    @staticmethod\n    def _salvage_identity',1)[0]
assert "/api/history/event/media?" in snapshot
assert "/api/history/event/discover" not in snapshot
assert "timeout=min(15,DISCOVERY_HTTP_TIMEOUT_SECONDS)" in snapshot

# Conservative refresh identity: exact key first, provider/media id only as fallback.
merge=service.split('    def _merge_salvage_transport(self, known_assets, plan_assets):',1)[1].split('    def _salvage_classification',1)[0]
assert 'by_key' in merge and 'by_identity' in merge
assert "fresh=by_key.get(key)" in merge
assert 'transportRecovered' in merge and 'transportChanged' in merge

# Hard failures remain terminal; soft/transient/stale states are explicitly ranked.
classification=service.split('    def _salvage_classification(self, asset, now=None):',1)[1].split('    def _salvage_known_candidates',1)[0]
for token in ('RECENT_PLAYED','TRANSIENT_FAILURE','INFRA_FAILURE','STALE_NONHARD_FAILURE','UNVERIFIED_KNOWN'):
    assert token in classification

# R21 rollout must preserve existing cooldowns. Historical materializers may name
# their own older one-time migration differently, but R21 itself may not introduce
# a seed-time WHERE/details marker that wakes every WAITING_RETRY job.
seed=service.split('    def seed_repair_queue(self):',1)[1].split('    def repair_liveness',1)[0]
assert "NOT LIKE '%R21_KNOWN_CANDIDATE_SALVAGE%'" not in seed
assert "R21 known-candidate salvage strategy upgrade: immediate one-time retry" not in seed
assert 'R21_KNOWN_CANDIDATE_SALVAGE' in repair

# Operator telemetry and overcomplete copy raw JSON will expose salvage yield.
for token in ('salvage selected','salvage certified','salvage closed'):
    assert token in ui, token

# Release replay must restore the lane after historical v6.1.15 materialization.
assert '"tools/patch_media_repair_salvage_v6116.py"' in materializer
assert '"tests/test_media_repair_salvage_v6116.py"' in materializer
assert 'patch_media_repair_salvage_v6116.py' in materializer
assert 'tests/test_media_repair_salvage_v6116.py' in verify

print('PASS v6.1.16 Known Candidate Salvage / Revalidation lane contract')

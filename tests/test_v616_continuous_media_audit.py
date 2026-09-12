#!/usr/bin/env python3
from __future__ import annotations

from datetime import timezone
from pathlib import Path

from sbb.media_audit_continuous import DiscoveryCircuitBreaker, RollingAuditCoordinator

ROOT = Path(__file__).resolve().parents[1]
service = (ROOT / "media_audit_service.py").read_text(encoding="utf-8")
materializer = (ROOT / "tools" / "apply_v616_release.py").read_text(encoding="utf-8")

# Release contract: v6.1.3 safe mode is deliberately superseded only after the
# shared discovery circuit and rolling coordinator are present.
for token in [
    'SBB_MEDIA_REPAIR_ENABLED", "1"',
    'SBB_MEDIA_REPAIR_WORKERS", "2"',
    'SBB_MEDIA_REPAIR_DISCOVERY_FAILURE_THRESHOLD", "3"',
    'SBB_MEDIA_REPAIR_DISCOVERY_CIRCUIT_SECONDS", "900"',
    'SBB_MEDIA_AUDIT_ROLLING_ENABLED", "1"',
    'SBB_MEDIA_AUDIT_ROLLING_INTERVAL_SECONDS", "120"',
    'SBB_MEDIA_AUDIT_ROLLING_BATCH_SIZE", "250"',
    'SBB_MEDIA_AUDIT_ROLLING_CUTOFF_DAYS", "1"',
    'R21-CONTINUOUS-ROLLING-REPAIR',
    'R21_CONTINUOUS_REPAIR',
    'def rolling_backlog_count(',
    'def start_run(self, mode="ALL", start_date="", max_games=0):',
    'MediaRepairEngine(STORE, DB_WRITER, worker_index=i, seed_owner=(i == 1))',
    'REPAIR_DISCOVERY_CIRCUIT.before_request()',
    'with REPAIR_EXTERNAL_SEMAPHORE:',
    'RollingAuditCoordinator(',
    '"workers": [w.snapshot() for w in REPAIR_ENGINES]',
    '"rolling": ROLLING_COORDINATOR.snapshot()',
]:
    assert token in service, token

# Keep canonical audit probing conservative while accelerating the independent
# repair queue. Expensive provider discovery remains globally serialized.
assert 'SBB_MEDIA_AUDIT_WORKERS", "1"' in service
assert 'SBB_MEDIA_AUDIT_DISCOVERY_CONCURRENCY", "1"' in service
assert 'REPAIR_EXTERNAL_CONCURRENCY = max(1, min(2' in service

# Retry cadence is intentionally much more active than the old 6h/24h/7d ladder.
assert 'str(15 * 60)' in service
assert 'str(2 * 3600)' in service
assert 'str(24 * 3600)' in service
assert 'SBB_MEDIA_REPAIR_SEED_SECONDS", "300"' in service

# Circuit breaker opens after repeated shared upstream failures and recovers after
# cooldown or any successful discovery request.
now = [1000.0]
cb = DiscoveryCircuitBreaker(threshold=3, cooldown_seconds=60, clock=lambda: now[0])
assert cb.before_request()["allowed"] is True
cb.failure("HTTP_503")
cb.failure("HTTP_503")
assert cb.before_request()["allowed"] is True
cb.failure("DISCOVERY_TRANSPORT_TIMEOUT")
gate = cb.before_request()
assert gate["allowed"] is False
assert gate["retryAt"] == 1060.0
assert cb.snapshot()["totalOpened"] == 1
now[0] = 1061.0
assert cb.before_request()["allowed"] is True
cb.failure("HTTP_503")
cb.success()
assert cb.snapshot()["state"] == "CLOSED"
assert cb.snapshot()["consecutiveFailures"] == 0


class FakeStore:
    def __init__(self):
        self.active = None
        self.backlog = 17

    def active_run(self):
        return self.active

    def rolling_backlog_count(self, cutoff, fresh_seconds):
        assert cutoff == "2026-09-10"
        assert fresh_seconds == 30 * 86400
        return self.backlog


store = FakeStore()
started = []

def start_batch(cutoff, batch):
    started.append((cutoff, batch))
    store.active = {"id": 44, "state": "RUNNING", "total_games": min(store.backlog, batch)}
    return dict(store.active)

coord = RollingAuditCoordinator(
    store,
    start_batch,
    timezone=timezone.utc,
    interval_seconds=120,
    batch_size=250,
    cutoff_days=1,
    fresh_seconds=30 * 86400,
)
# Freeze date computation for deterministic unit coverage of yesterday-first logic.
coord.cutoff_date = lambda: "2026-09-10"
state = coord.run_once()
assert started == [("2026-09-10", 250)]
assert state["state"] == "RUNNING_BATCH"
assert state["backlog"] == 17
assert state["lastRunGames"] == 17

# An active rolling/manual run is never replaced by the coordinator.
state = coord.run_once()
assert state["state"] == "WAITING_ACTIVE_RUN"
assert started == [("2026-09-10", 250)]

# No missing/stale work means caught up rather than generating empty runs.
store.active = {"id": 44, "state": "COMPLETE", "total_games": 17}
store.backlog = 0
state = coord.run_once()
assert state["state"] == "CAUGHT_UP"
assert started == [("2026-09-10", 250)]

for token in [
    'run_base(root)',
    'patch_media_audit(root)',
    'REPAIR_WORKER_COUNT',
    'ROLLING_AUDIT_BATCH_SIZE',
    'R21_CONTINUOUS_REPAIR',
]:
    assert token in materializer, token

print("PASS: v6.1.6 continuous Media Audit + accelerated Repair contract")

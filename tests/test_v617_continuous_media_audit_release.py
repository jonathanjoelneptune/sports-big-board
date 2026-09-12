#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "6.1.7"
service = (ROOT / "media_audit_service.py").read_text(encoding="utf-8")
legacy = (ROOT / "tests" / "test_v550_media_health_audit.py").read_text(encoding="utf-8")

for token in [
    'AUDIT_GENERATION = "R21-CONTINUOUS-ROLLING-REPAIR"',
    'SBB_MEDIA_REPAIR_ENABLED", "1"',
    'SBB_MEDIA_REPAIR_WORKERS", "2"',
    'SBB_MEDIA_AUDIT_WORKERS", "1"',
    'SBB_MEDIA_AUDIT_DISCOVERY_CONCURRENCY", "1"',
    'SBB_MEDIA_AUDIT_ROLLING_INTERVAL_SECONDS", "300"',
    'SBB_MEDIA_AUDIT_ROLLING_BATCH_SIZE", "250"',
    'STORE.start_run("ROLLING", cutoff_date, max_games=batch_size)',
    'REPAIR_DISCOVERY_CIRCUIT.before_request()',
    'REPAIR_EXTERNAL_SEMAPHORE',
    'R21_CONTINUOUS_REPAIR',
]:
    assert token in service, token

assert 'AUDIT_GENERATION = "R21-CONTINUOUS-ROLLING-REPAIR"' in legacy
assert "assert 'R21-CONTINUOUS-ROLLING-REPAIR' in service" in legacy
assert "'R21_CONTINUOUS_REPAIR','history_media_repair_source_attempt'" in legacy

print("PASS: v6.1.7 R21 continuous Media Audit release contract")

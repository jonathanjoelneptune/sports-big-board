#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = (root / "VERSION").read_text(encoding="utf-8").strip()
service = (root / "media_audit_service.py").read_text(encoding="utf-8")
yieldmod = (root / "sbb" / "media_repair_yield_v6116.py").read_text(encoding="utf-8")
resolver = (root / "sbb" / "media_team_sources_v6116.py").read_text(encoding="utf-8")
seed = (root / "sbb" / "media_team_seed_v6116.py").read_text(encoding="utf-8")
js = (root / "ui" / "media-audit-v550.js").read_text(encoding="utf-8")
verify = (root / "VERIFY.sh").read_text(encoding="utf-8")

assert version == "6.1.16", version
assert "_install_media_repair_yield_v6116(globals())" in service
assert "REPAIR_DISCOVERY_SETTLE_SECONDS and not result.get('skipped')" in service

for token in (
    "history_media_repair_rejection_memory",
    "history_media_repair_strategy_activation",
    "R25_REPAIR_YIELD",
    "rejectionMemorySkips", "rejectionMemoryWrites",
    "operation_available(\"search\")",
    "GATEWAY_COOLDOWN_SKIPPED",
    "LOCAL_DISCOVERY_CIRCUIT_OPEN",
    "stageSkipsQuota", "stageSkipsCircuit",
):
    assert token in yieldmod, token

for token in (
    "MANUAL_AUTHORITATIVE_SEED",
    "Manual authoritative team-video seed available",
    "seedEntries", "seededTeams",
):
    assert token in resolver, token
assert "TEAM_VIDEO_SEEDS" in seed and "SEED_COUNTS" in seed

for token in ("remembered rejects skipped", "quota-stage skips", "circuit-stage skips", "manual seeds active"):
    assert token in js, token

for command in (
    "python3 -m py_compile sbb/media_team_seed_v6116.py sbb/media_team_sources_v6116.py sbb/media_repair_yield_v6116.py",
    "python3 tests/test_v6116_team_seed_directory.py",
    "python3 tests/test_v6116_media_repair_yield_release.py",
):
    assert command in verify, command

print("PASS v6.1.16 R25 Media Repair yield release contract")

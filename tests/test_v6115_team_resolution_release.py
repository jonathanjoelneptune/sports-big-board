#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = (root / "VERSION").read_text(encoding="utf-8").strip()
service = (root / "media_audit_service.py").read_text(encoding="utf-8")
helper = (root / "sbb" / "media_team_sources_v6115.py").read_text(encoding="utf-8")
html = (root / "media-audit.html").read_text(encoding="utf-8")
js = (root / "ui" / "media-audit-v550.js").read_text(encoding="utf-8")
verify = (root / "VERIFY.sh").read_text(encoding="utf-8")

expected_version = ".".join(("6", "1", "15"))
assert version == expected_version, version
assert "from sbb.media_team_sources_v6115 import TeamSourceRegistry" in service
assert "R24-CONTINUOUS-TEAM-RESOLUTION" in service
assert "R24_TEAM_RESOLUTION_CONTROL_LOOP" in service
assert "TEAM_RESOLUTION_TICK_SECONDS" in service
assert "TEAM_RESOLUTION_BATCH" in service
assert "def requeue_repairs_for_team(" in service
assert "on_team_resolved=self._on_team_source_resolved" in service
assert "def _on_team_source_resolved(" in service
assert "self.team_sources.resolve_due(" in service
assert "teamResolutionQueueAttempts" in service
assert "teamResolutionUpgrades" in service
assert "teamResolutionRequeues" in service
assert "teamUnresolvedObserved" in service

# The background identity resolver is owned by the seed worker and remains under
# the existing serialized external-source semaphore. It must execute before the
# next repair-job claim so the engine can make progress even when all games cool down.
run_start = service.index("    def run(self):", service.index("class MediaRepairEngine"))
run_end = service.index("\n\nclass AuditStatusCache", run_start)
run_body = service[run_start:run_end]
assert "if self.seed_owner and _now()-self.last_team_resolution_at>=TEAM_RESOLUTION_TICK_SECONDS:" in run_body
assert "with REPAIR_EXTERNAL_SEMAPHORE:" in run_body
assert run_body.index("self.team_sources.resolve_due(") < run_body.index("claim next repair job")

# The sidecar resolver owns explicit persistent statuses/cooldowns and records
# every repair wakeup caused by an improved team source graph.
for token in (
    "CREATE TABLE IF NOT EXISTS team_resolution_queue",
    "NO_DIRECTORY_MATCH", "LEAGUE_PAGE_FOUND", "OFFICIAL_SITE_FOUND", "YOUTUBE_FOUND",
    "next_retry_at", "total_requeued_jobs", "def resolve_due(",
    "repairJobsRequeuedByResolution", "recentUnresolvedTeams",
):
    assert token in helper, token

# The operator page must make the source graph visible rather than forcing log inspection.
for token in ("repairTeamSources", "repairTeamResolution", "repairTeamStates"):
    assert token in html, token
    assert token in js, token
assert "resolvedTeams" in js and "unresolvedTeams" in js and "dueUnresolvedTeams" in js
assert "repairJobsRequeuedByResolution" in js

assert "python3 -m py_compile sbb/media_team_sources_v6115.py" in verify
assert "python3 tests/test_v6115_team_resolution_queue.py" in verify
assert "python3 tests/test_v6115_team_resolution_release.py" in verify

print("PASS v6.1.15 team-resolution control-loop release contract")

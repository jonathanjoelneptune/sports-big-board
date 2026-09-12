#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
service = (root / "media_audit_service.py").read_text(encoding="utf-8")
helper = (root / "sbb" / "media_team_sources_v6112.py").read_text(encoding="utf-8")
verify = (root / "VERIFY.sh").read_text(encoding="utf-8")

assert 'from sbb.media_team_sources_v6112 import TeamSourceRegistry' in service
assert 'media-team-sources.sqlite' in service
assert 'R22-CONTINUOUS-TEAM-SOURCES' in service
assert 'R22_TEAM_SOURCE_REGISTRY' in service
assert "OFFICIAL_TEAM_SOURCES" in service
assert "TEAM_SOURCE_REGISTRY" in service
assert "teamSources" in service
assert "teamSourceCandidates" in service

# Assert execution order inside the repair ladder itself. Stage labels are emitted
# inside helper methods, so use the actual calls made by _repair_by_discovery().
repair_start = service.index("    def _repair_by_discovery(self, job):")
repair_end = service.index("    @staticmethod\n    def _retry_at(job):", repair_start)
repair = service[repair_start:repair_end]
league_stage = repair.index("result=self._discover_once(job,1)")
global_yt_stage = repair.index("indexed=self._youtube_index_candidates(job,known)")
team_stage = repair.index("OFFICIAL_TEAM_SOURCES")
generic_stage = repair.index("yt=self._youtube_fallback_candidates(job)")
assert league_stage < global_yt_stage < team_stage < generic_stage, (
    league_stage, global_yt_stage, team_stage, generic_stage
)

assert 'CREATE TABLE IF NOT EXISTS team_source (' in helper
assert 'CREATE TABLE IF NOT EXISTS team_source_video (' in helper
assert 'VERIFIED_SOCIAL_LINK' in helper
assert 'TRUSTED_INDEX_NAME_MATCH' in helper
assert 'OFFICIAL_TEAM_WEB' in helper
assert 'OFFICIAL_TEAM_YOUTUBE' in helper
assert 'candidates_from_registry' in helper
assert '.88' in helper
assert 'search.list' in helper  # documentation explicitly states this lane avoids it

assert 'python3 -m py_compile sbb/media_team_sources_v6112.py' in verify
assert 'python3 tests/test_v6112_team_source_registry.py' in verify
assert 'python3 tests/test_v6112_team_source_release.py' in verify

print("PASS v6.1.12 official team-source repair ladder contract")

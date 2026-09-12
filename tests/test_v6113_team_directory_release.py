#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = (root / "VERSION").read_text(encoding="utf-8").strip()
service = (root / "media_audit_service.py").read_text(encoding="utf-8")
helper = (root / "sbb" / "media_team_sources_v6113.py").read_text(encoding="utf-8")
verify = (root / "VERIFY.sh").read_text(encoding="utf-8")

assert version == "6.1.13", version
assert "from sbb.media_team_sources_v6113 import TeamSourceRegistry" in service
assert "R23-CONTINUOUS-TEAM-DIRECTORY" in service
assert "R23_TEAM_DIRECTORY_RESOLUTION" in service
assert "OFFICIAL_TEAM_SOURCES" in service
assert "TEAM_SOURCE_REGISTRY" in service
assert "teamDirectoryFetches" in service
assert "teamDirectoryCacheHits" in service
assert "teamDirectoryErrors" in service
assert "teamLeaguePagesResolved" in service
assert "teamOfficialSitesResolved" in service

repair_start = service.index("    def _repair_by_discovery(self, job):")
repair_end = service.index("    @staticmethod\n    def _retry_at(job):", repair_start)
repair = service[repair_start:repair_end]
league_stage = repair.index("result=self._discover_once(job,1)")
global_yt_stage = repair.index("indexed=self._youtube_index_candidates(job,known)")
team_stage = repair.index("OFFICIAL_TEAM_SOURCES")
generic_stage = repair.index("yt=self._youtube_fallback_candidates(job)")
assert league_stage < global_yt_stage < team_stage < generic_stage

for token in [
    "LEAGUE_DIRECTORY_URLS",
    "league_directory_link",
    "league_directory_state",
    "OFFICIAL_LEAGUE_TEAM_PAGE",
    "VERIFIED_LEAGUE_REFERRAL",
    "VERIFIED_DIRECTORY_TEAM_PAGE",
    "directoryFetches",
    "directoryCacheHits",
    "leaguePagesResolved",
    "leagueReferredOfficialSites",
]:
    assert token in helper, token

# R23 must not reuse the v6.1.12 guessed template table.
candidate_start = helper.index("    def _candidate_web_urls(self, entity: dict)")
candidate_end = helper.index("    def _identity_score", candidate_start)
candidate_body = helper[candidate_start:candidate_end]
assert "LEAGUE_WEB_TEMPLATES" not in candidate_body
assert "metadataUrls" in candidate_body

assert "https://www.mlssoccer.com/clubs/" in helper
assert "https://www.premierleague.com/en/clubs" in helper
assert "https://www.nfl.com/teams/" in helper
assert "https://www.mlb.com/team" in helper

assert "python3 -m py_compile sbb/media_team_sources_v6113.py" in verify
assert "python3 tests/test_v6113_team_directory_resolution.py" in verify
assert "python3 tests/test_v6113_team_directory_release.py" in verify

print("PASS v6.1.13 authoritative team-directory release contract")

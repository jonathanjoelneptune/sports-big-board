#!/usr/bin/env python3
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from sbb.media_team_sources_v6115 import TeamSourceRegistry


class FakeStore:
    pass


with tempfile.TemporaryDirectory() as td:
    callbacks = []

    def on_resolved(entity, resolution):
        callbacks.append((entity["entityKey"], resolution["previousStatus"], resolution["status"]))
        return 4 if resolution["status"] == "OFFICIAL_SITE_FOUND" else 2

    registry = TeamSourceRegistry(
        FakeStore(), Path(td) / "team-sources.sqlite",
        on_team_resolved=on_resolved,
        unresolved_retry_seconds=600,
        error_retry_seconds=300,
    )
    entity = {
        "entityKey": "MLS:ORL", "league": "MLS", "side": "home",
        "teamId": "ORL", "teamName": "Orlando City SC", "slug": "orlando-city-sc",
        "nickname": "orlando", "raw": {}, "metadataUrls": [],
    }
    row = registry._ensure_resolution_row(entity)
    assert row["status"] == "UNRESOLVED"

    row = registry._update_resolution(entity, stats={"directoryLinks": 10}, attempted=True)
    assert row["status"] == "NO_DIRECTORY_MATCH"
    assert row["attempt_count"] == 1
    assert row["next_retry_at"] > 0
    assert not callbacks

    registry._upsert_source(
        entity, "OFFICIAL_TEAM_WEB", "https://orlandocitysc.com",
        url="https://orlandocitysc.com", trust_state="VERIFIED_LEAGUE_REFERRAL",
        evidence="fixture", checked=True, verified=True,
    )
    row = registry._update_resolution(entity, stats={}, attempted=False)
    assert row["status"] == "OFFICIAL_SITE_FOUND"
    assert row["last_requeued_jobs"] == 4
    assert row["total_requeued_jobs"] == 4
    assert callbacks[-1] == ("MLS:ORL", "NO_DIRECTORY_MATCH", "OFFICIAL_SITE_FOUND")

    registry._upsert_source(
        entity, "OFFICIAL_TEAM_YOUTUBE", "UCORLANDOFIXTURE12345678",
        url="https://youtube.com/@OrlandoCitySC", channel_id="UCORLANDOFIXTURE12345678",
        channel_name="Orlando City SC", trust_state="VERIFIED_AUTHORITATIVE_LINK",
        evidence="fixture", checked=True, verified=True,
    )
    row = registry._update_resolution(entity, stats={}, attempted=False)
    assert row["status"] == "YOUTUBE_FOUND"
    assert row["last_requeued_jobs"] == 2
    assert row["total_requeued_jobs"] == 6

    snap = registry.snapshot()
    assert snap["resolvedTeams"] == 1
    assert snap["unresolvedTeams"] == 0
    assert snap["repairJobsRequeuedByResolution"] == 6
    assert snap["resolutionStates"]["YOUTUBE_FOUND"] == 1

print("PASS v6.1.15 persistent team-resolution queue and upgrade callback")

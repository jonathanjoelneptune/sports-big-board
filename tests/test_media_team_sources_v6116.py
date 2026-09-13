#!/usr/bin/env python3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbb.media_team_sources_v6116 import TeamSourceRegistry


class FakeStore:
    def connect(self, timeout=3):
        raise RuntimeError("no catalog in identity-only test")


with tempfile.TemporaryDirectory() as td:
    registry = TeamSourceRegistry(FakeStore(), Path(td) / "team-sources.sqlite")

    def entity(name, *, raw=None):
        return {
            "entityKey": "NCAAF:test",
            "league": "NCAAF",
            "side": "home",
            "teamId": "test",
            "teamName": name,
            "slug": "test",
            "nickname": "test",
            "raw": raw or {},
            "metadataUrls": [],
        }

    assert registry._identity_score(entity("New Mexico State Aggies"), "New Mexico St", "/schools/new-mexico-st") >= 0.90
    assert registry._identity_score(entity("Hawai'i Rainbow Warriors"), "Hawaii", "/schools/hawaii") >= 0.90
    assert registry._identity_score(entity("Ohio State Buckeyes"), "Ohio State", "/schools/ohio-state") >= 0.90
    assert registry._identity_score(entity("Notre Dame Fighting Irish"), "Notre Dame", "/schools/notre-dame") >= 0.90

    rich = entity("New Mexico State Aggies", raw={"location":"New Mexico State","shortDisplayName":"New Mexico St"})
    assert registry._identity_score(rich, "New Mexico St Aggies") >= 0.95
    assert registry._identity_score(entity("Michigan Wolverines"), "Michigan State Spartans") < 0.90

    snap = registry.snapshot()
    assert snap["generation"] == "R25-TEAM-IDENTITY-ALIASES"
    assert snap["identityMatching"] == "PROVIDER_ALIASES+NCAAF_INSTITUTION_PREFIX"

print("PASS v6.1.16 Media Repair team identity aliases")

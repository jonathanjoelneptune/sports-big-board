#!/usr/bin/env python3
import sqlite3
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from sbb.media_team_seed_v6116 import TEAM_VIDEO_SEEDS, SEED_COUNTS
from sbb.media_team_sources_v6116 import TeamSourceRegistry

assert len(TEAM_VIDEO_SEEDS) == 218, len(TEAM_VIDEO_SEEDS)
assert SEED_COUNTS == {"NBA":26,"NFL":32,"MLB":30,"MLS":28,"EPL":18,"NCAAF":84}, SEED_COUNTS
for row in TEAM_VIDEO_SEEDS:
    assert row["url"].startswith(("http://", "https://")), row
    assert "utm_source=" not in row["url"], row
    assert row["role"] in {"VIDEO_INDEX", "TEAM_PAGE_WITH_VIDEO"}, row

class DummyStore:
    def __init__(self, path): self.path = path
    def connect(self, timeout=3):
        conn = sqlite3.connect(self.path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        return conn

with tempfile.TemporaryDirectory() as td:
    reg = TeamSourceRegistry(DummyStore(str(Path(td)/"history.sqlite")), Path(td)/"team.sqlite")

    def entity(league, name):
        return {"entityKey":f"{league}:{name}","league":league,"side":"home","teamId":"",
                "teamName":name,"slug":"","nickname":"","raw":{"displayName":name},"metadataUrls":[]}

    assert reg._seed_match(entity("NFL", "San Francisco 49ers"))["url"] == "https://www.49ers.com/video/highlights/"
    assert reg._seed_match(entity("NCAAF", "#21 Iowa Hawkeyes"))["team"] == "Iowa"
    assert reg._seed_match(entity("NCAAF", "Iowa State Cyclones"))["team"] == "Iowa State"
    assert reg._seed_match(entity("NCAAF", "Georgia Tech Yellow Jackets"))["team"] == "Georgia Tech"
    assert reg._seed_match(entity("MLS", "Red Bull New York"))["team"] == "New York Red Bulls"
    assert reg._seed_match(entity("NBA", "Brooklyn Nets")) is None
    assert reg._seed_match(entity("NFL", "Brooklyn Nets")) is None

    reg._consume_official_site = lambda *a, **k: {"pagesChecked":0,"officialSites":1,"youtubeChannels":0}
    e = entity("NFL", "Seattle Seahawks")
    result = reg._apply_seed(e, None, "")
    assert result["seedMatched"] is True
    with reg.connect() as conn:
        row = conn.execute("SELECT trust_state,url,verified_at FROM team_source WHERE entity_key=?", (e["entityKey"],)).fetchone()
    assert row and row["trust_state"] == "MANUAL_AUTHORITATIVE_SEED", row
    assert row["url"] == "https://www.seahawks.com/video/", row
    assert float(row["verified_at"] or 0) > 0

print("PASS v6.1.16 authoritative team video seed directory")

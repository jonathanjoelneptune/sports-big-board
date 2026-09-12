#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbb.media_team_sources_v6114 import TeamSourceRegistry


class FakeStore:
    def __init__(self, path: Path):
        self.db_path = str(path)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS history_media_repair_youtube_index(video_id TEXT PRIMARY KEY,channel_id TEXT,channel_name TEXT,title TEXT,description TEXT,published_at TEXT,playlist_id TEXT,indexed_at REAL,details_json TEXT)"
            )
            conn.commit()

    def connect(self, timeout=None):
        conn = sqlite3.connect(self.db_path, timeout=float(timeout or 5))
        conn.row_factory = sqlite3.Row
        return conn


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    registry = TeamSourceRegistry(FakeStore(root / "history.sqlite"), root / "team.sqlite")
    page = """
      <article class="club-card"><h3>Orlando City</h3>
        <a href="/clubs/orlando-city/">Details</a>
        <a href="https://www.orlandocitysc.com/">Club Site</a>
      </article>
      <article class="club-card"><h3>Atlanta United</h3>
        <a href="/clubs/atlanta-united/">Details</a>
        <a href="https://www.atlutd.com/">Club Site</a>
      </article>
    """
    links = registry._extract_links(page, "https://www.mlssoccer.com/clubs/")
    by_url = {row["url"]: row for row in links}
    assert "Atlanta United" not in by_url["https://www.orlandocitysc.com/"]["context"], by_url
    assert "Orlando City" not in by_url["https://www.atlutd.com/"]["context"], by_url
    assert "Orlando City" in by_url["https://www.orlandocitysc.com/"]["context"]
    assert "Atlanta United" in by_url["https://www.atlutd.com/"]["context"]

    orlando = {"teamName": "Orlando City SC", "raw": {"displayName": "Orlando City SC", "name": "Orlando City"}}
    atlanta = {"teamName": "Atlanta United FC", "raw": {"displayName": "Atlanta United FC", "name": "Atlanta United"}}
    assert registry._identity_score(orlando, by_url["https://www.orlandocitysc.com/"]["context"], "https://www.orlandocitysc.com/") >= .90
    assert registry._identity_score(atlanta, by_url["https://www.orlandocitysc.com/"]["context"], "https://www.orlandocitysc.com/") < .90

    json_page = """
      <script>
        {"href":"/en/clubs/11/everton/overview","name":"Everton"}
        {"href":"/en/clubs/94/brentford/overview","name":"Brentford"}
      </script>
    """
    links = registry._extract_links(json_page, "https://www.premierleague.com/en/clubs")
    by_url = {row["url"]: row for row in links}
    everton_url = "https://www.premierleague.com/en/clubs/11/everton/overview"
    brentford_url = "https://www.premierleague.com/en/clubs/94/brentford/overview"
    assert "Everton" in by_url[everton_url]["context"]
    assert "Brentford" not in by_url[everton_url]["context"]
    assert "Brentford" in by_url[brentford_url]["context"]
    assert "Everton" not in by_url[brentford_url]["context"]

    snap = registry.snapshot()
    assert snap["ownershipScoping"] == "SEMANTIC_CARD_OR_JSON_OBJECT"

print("PASS v6.1.14 team-directory ownership scoping")

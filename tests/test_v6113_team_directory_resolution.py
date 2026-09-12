#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbb.media_team_sources_v6113 import TeamSourceRegistry


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


class FakeYouTube:
    def fetch_json(self, url, timeout=10):
        return {"items": []}


class FixtureRegistry(TeamSourceRegistry):
    def __init__(self, *args, fixtures=None, **kwargs):
        self.fixtures = dict(fixtures or {})
        self.fetches = []
        super().__init__(*args, **kwargs)

    def _fetch_html(self, url):
        self.fetches.append(url)
        if url not in self.fixtures:
            raise RuntimeError("fixture missing: " + url)
        value = self.fixtures[url]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            return value
        return value, url

    def _resolve_channel(self, ref_url, youtube, api_key):
        low = ref_url.lower()
        if "orlandocitysc" in low:
            return "UC_ORLANDO_OFFICIAL_1234", "Orlando City SC"
        if "atlutd" in low:
            return "UC_ATLANTA_OFFICIAL_12345", "Atlanta United FC"
        if "everton" in low:
            return "UC_EVERTON_OFFICIAL_1234", "Everton"
        return "", ""

    def _index_channel(self, entity, source, youtube, api_key, stop_event=None):
        return 0


def mls_context():
    return {
        "league": "MLS",
        "event_date": "2026-09-10",
        "event": {
            "away": {
                "id": "ATL",
                "displayName": "Atlanta United FC",
                "name": "Atlanta United",
                "abbreviation": "ATL",
            },
            "home": {
                "id": "ORL",
                "displayName": "Orlando City SC",
                "name": "Orlando City",
                "abbreviation": "ORL",
            },
        },
    }


def epl_context():
    return {
        "league": "EPL",
        "event_date": "2026-09-10",
        "event": {
            "away": {"id": "BRE", "displayName": "Brentford", "abbreviation": "BRE"},
            "home": {"id": "EVE", "displayName": "Everton", "abbreviation": "EVE"},
        },
    }


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    store = FakeStore(root / "history.sqlite")
    youtube = FakeYouTube()

    mls_directory = """
    <html><body>
      <article class="club-card"><h3>Orlando City</h3>
        <a href="/clubs/orlando-city/">Details</a>
        <a href="https://www.orlandocitysc.com/">Club Site</a>
      </article>
      <div style="height:800px"></div>
      <article class="club-card"><h3>Atlanta United</h3>
        <a href="/clubs/atlanta-united/">Details</a>
        <a href="https://www.atlutd.com/">Club Site</a>
      </article>
    </body></html>
    """
    fixtures = {
        "https://www.mlssoccer.com/clubs/": (mls_directory, "https://www.mlssoccer.com/clubs/"),
        "https://www.mlssoccer.com/clubs/orlando-city/": (
            '<title>Orlando City | MLSsoccer.com</title><a href="https://www.orlandocitysc.com/">Club Site</a>',
            "https://www.mlssoccer.com/clubs/orlando-city/",
        ),
        "https://www.orlandocitysc.com/": (
            '<title>Orlando City SC</title><a href="https://www.youtube.com/@OrlandoCitySC">YouTube</a>',
            "https://www.orlandocitysc.com/",
        ),
        "https://www.mlssoccer.com/clubs/atlanta-united/": (
            '<title>Atlanta United | MLSsoccer.com</title><a href="https://www.atlutd.com/">Club Site</a>',
            "https://www.mlssoccer.com/clubs/atlanta-united/",
        ),
        "https://www.atlutd.com/": (
            '<title>Atlanta United FC</title><a href="https://www.youtube.com/@ATLUTD">YouTube</a>',
            "https://www.atlutd.com/",
        ),
    }
    registry = FixtureRegistry(
        store,
        root / "team-sources.sqlite",
        fixtures=fixtures,
        refresh_seconds=999999,
        directory_refresh_seconds=999999,
        index_refresh_seconds=999999,
    )

    entities = registry.entities(mls_context())
    orlando = entities[0]
    assert orlando["teamName"] == "Orlando City SC"

    # R23 no longer manufactures guessed league URLs.
    assert registry._candidate_web_urls(orlando) == []

    # Distinctive words such as City and United remain part of directory identity,
    # preventing the old stop-word collision class.
    city = {"teamName": "Manchester City", "raw": {"displayName": "Manchester City"}}
    assert registry._identity_score(city, "Manchester City") >= .95
    assert registry._identity_score(city, "Manchester United") < .90

    refresh = registry.refresh_event_sources(mls_context(), youtube, "fake-key")
    assert refresh["directoryFetches"] == 1, refresh
    assert refresh["directoryCacheHits"] >= 1, refresh
    assert refresh["leaguePagesResolved"] == 2, refresh
    assert refresh["officialSites"] == 2, refresh
    assert refresh["youtubeChannels"] >= 2, refresh
    assert refresh["verifiedWeb"] == 4, refresh

    snap = registry.snapshot()
    assert snap["generation"] == "R23-OFFICIAL-TEAM-DIRECTORY-SOURCES"
    assert snap["directoryLeagues"] == 1, snap
    assert snap["directoryLinks"] >= 4, snap
    assert snap["leagueTeamPages"] == 2, snap
    assert snap["leagueReferredOfficialSites"] == 2, snap
    assert snap["youtubeChannels"] == 2, snap

    # The directory page was fetched only once for both teams. Fresh resolved
    # identities prevent a second event refresh from re-hitting the web.
    before = list(registry.fetches)
    second = registry.refresh_event_sources(mls_context(), youtube, "fake-key")
    assert registry.fetches == before, (before, registry.fetches)
    assert second["directoryFetches"] == 0

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    store = FakeStore(root / "history.sqlite")
    youtube = FakeYouTube()
    epl_directory = """
      <script>
        {"href":"/en/clubs/11/everton/overview","name":"Everton"}
        {"href":"/en/clubs/94/brentford/overview","name":"Brentford"}
      </script>
    """
    fixtures = {
        "https://www.premierleague.com/en/clubs": (
            epl_directory,
            "https://www.premierleague.com/en/clubs",
        ),
        "https://www.premierleague.com/en/clubs/11/everton/overview": (
            '<title>Everton | Premier League</title><a aria-label="Official Website" href="https://www.evertonfc.com/">Official Website</a>',
            "https://www.premierleague.com/en/clubs/11/everton/overview",
        ),
        "https://www.evertonfc.com/": (
            '<title>Everton Football Club</title><a href="https://www.youtube.com/@Everton">YouTube</a>',
            "https://www.evertonfc.com/",
        ),
        "https://www.premierleague.com/en/clubs/94/brentford/overview": (
            '<title>Brentford | Premier League</title>',
            "https://www.premierleague.com/en/clubs/94/brentford/overview",
        ),
    }
    registry = FixtureRegistry(
        store,
        root / "team-sources.sqlite",
        fixtures=fixtures,
        refresh_seconds=999999,
        directory_refresh_seconds=999999,
        index_refresh_seconds=999999,
    )
    refresh = registry.refresh_event_sources(epl_context(), youtube, "fake-key")
    assert refresh["leaguePagesResolved"] == 2, refresh
    assert "https://www.premierleague.com/en/clubs/11/everton/overview" in registry.fetches
    assert not any("/clubs/everton/overview" in url for url in registry.fetches), registry.fetches
    assert refresh["officialSites"] >= 1, refresh
    assert registry.snapshot()["youtubeChannels"] >= 1

print("PASS v6.1.13 authoritative league-directory team source resolver")

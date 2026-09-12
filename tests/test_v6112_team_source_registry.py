#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbb.media_team_sources_v6112 import TeamSourceRegistry


class FakeStore:
    def __init__(self, path: Path):
        self.db_path = str(path)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS history_media_repair_youtube_index(video_id TEXT PRIMARY KEY,channel_id TEXT,channel_name TEXT,title TEXT,description TEXT,published_at TEXT,playlist_id TEXT,indexed_at REAL,details_json TEXT)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO history_media_repair_youtube_index VALUES(?,?,?,?,?,?,?,?,?)",
                ("known-video", "UC_PADRES_OFFICIAL_123456", "San Diego Padres", "Padres highlights", "", "2026-09-10T06:00:00Z", "uploads", 1, "{}"),
            )
            conn.commit()

    def connect(self, timeout=None):
        conn = sqlite3.connect(self.db_path, timeout=float(timeout or 5))
        conn.row_factory = sqlite3.Row
        return conn


def context():
    return {
        "league": "MLB",
        "event_date": "2026-09-10",
        "event": {
            "away": {"id": "19", "displayName": "Los Angeles Dodgers", "abbreviation": "LAD", "slug": "los-angeles-dodgers"},
            "home": {"id": "25", "displayName": "San Diego Padres", "abbreviation": "SD", "slug": "san-diego-padres"},
        },
    }


def match_candidate(ctx, title, description, published_at, strict_date=True):
    text = (str(title) + " " + str(description)).lower()
    return .96 if "padres" in text and "dodgers" in text else 0.0


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    store = FakeStore(root / "history.sqlite")
    registry = TeamSourceRegistry(store, root / "team-sources.sqlite", refresh_seconds=999999, index_refresh_seconds=999999)

    entities = registry.entities(context())
    assert [e["side"] for e in entities] == ["home", "away"]
    assert entities[0]["teamName"] == "San Diego Padres"
    urls = registry._candidate_web_urls(entities[0])
    assert any("mlb.com" in u and "padres" in u for u in urls), urls

    learned = registry._learn_trusted_index_channels(entities[0])
    assert learned == 1
    snap = registry.snapshot()
    assert snap["teams"] == 1
    assert snap["youtubeChannels"] == 1

    registry._upsert_videos(
        entities[0]["entityKey"],
        [
            {
                "videoId": "abcDEF12345",
                "channelId": "UC_PADRES_OFFICIAL_123456",
                "channelName": "San Diego Padres",
                "title": "Dodgers vs Padres Extended Highlights | September 10, 2026",
                "description": "Los Angeles Dodgers at San Diego Padres game recap",
                "publishedAt": "2026-09-11T05:00:00Z",
                "durationSeconds": 480,
                "playlistId": "uploads",
            },
            {
                "videoId": "wrongGame123",
                "channelId": "UC_PADRES_OFFICIAL_123456",
                "channelName": "San Diego Padres",
                "title": "Padres clubhouse interview",
                "description": "Postgame interview",
                "publishedAt": "2026-09-11T05:00:00Z",
                "durationSeconds": 120,
                "playlistId": "uploads",
            },
        ],
        "OFFICIAL_TEAM_YOUTUBE",
    )
    result = registry.candidates_from_registry(context(), set(), match_candidate, max_candidates=8)
    assert result["results"] == 2
    assert len(result["candidates"]) == 1, result
    cand = result["candidates"][0]
    assert cand["youtubeId"] == "abcDEF12345"
    assert cand["tier"] == "extended"
    assert cand["source"] == "OFFICIAL_TEAM_SOURCE"
    assert cand["teamName"] == "San Diego Padres"

    duplicate = registry.candidates_from_registry(context(), {"yt:abcDEF12345"}, match_candidate, max_candidates=8)
    assert not duplicate["candidates"]
    assert duplicate["duplicates"] >= 1

print("PASS v6.1.12 official team source registry")

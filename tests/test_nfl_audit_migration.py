import importlib.util
import json
import sqlite3
import tempfile
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "nfl_audit_migration_under_test", ROOT / "sbb" / "nfl_audit_migration.py"
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class FakeServer:
    HISTORY_OFFICIAL_CATCHUP_SOURCES = {
        "NFL": [
            {"key": "nfl-youtube-playlist-quick", "version": 2, "objective": "quick"},
            {"key": "nfl-youtube-playlist-extended", "version": 2, "objective": "extended"},
            {"key": "nfl-team-video-quick", "version": 1, "objective": "quick"},
        ],
        "NBA": [{"key": "nba-source", "version": 1, "objective": "quick"}],
    }


class FakeRepository:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _load_obj(value):
        return json.loads(value or "{}")

    @staticmethod
    def _dump_obj(value):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _seed_repository(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE history_catalog_event (
            canonical_event_key TEXT PRIMARY KEY,
            league TEXT NOT NULL
        );
        CREATE TABLE history_event_media (
            canonical_event_key TEXT NOT NULL,
            asset_key TEXT NOT NULL,
            association_state TEXT NOT NULL
        );
        CREATE TABLE history_source_media (
            asset_key TEXT PRIMARY KEY,
            asset_json TEXT NOT NULL,
            runtime_state TEXT NOT NULL,
            runtime_failure_at REAL NOT NULL DEFAULT 0,
            runtime_failure_reason TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL DEFAULT 0
        );
        """
    )
    conn.execute("INSERT INTO history_catalog_event VALUES('NFL:1','NFL')")
    conn.execute("INSERT INTO history_catalog_event VALUES('NFL:2','NFL')")
    conn.execute("INSERT INTO history_event_media VALUES('NFL:1','playlist-asset','ASSIGNED')")
    conn.execute("INSERT INTO history_event_media VALUES('NFL:2','team-asset','ASSIGNED')")
    conn.execute(
        "INSERT INTO history_source_media(asset_key,asset_json,runtime_state) VALUES(?,?,?)",
        (
            "playlist-asset",
            json.dumps(
                {
                    "league": "NFL",
                    "sourceType": "official-nfl-youtube-playlist",
                    "discoverySourceFamily": "nfl-youtube-playlist",
                    "recapTier": "green",
                    "verifiedPlayable": True,
                }
            ),
            "UNKNOWN",
        ),
    )
    conn.execute(
        "INSERT INTO history_source_media(asset_key,asset_json,runtime_state) VALUES(?,?,?)",
        (
            "team-asset",
            json.dumps(
                {
                    "league": "NFL",
                    "sourceType": "official-nfl-team-video",
                    "discoverySourceFamily": "nfl-team-video",
                    "recapTier": "extended",
                    "verifiedPlayable": True,
                }
            ),
            "PLAYED",
        ),
    )
    conn.commit()
    conn.close()


def test_active_nfl_audit_stack_has_no_playlist_and_is_version_two():
    rows = MOD.active_nfl_audit_sources()
    keys = [row["key"] for row in rows]
    assert keys == [
        "nfl-team-video-quick",
        "nfl-public-video-quick",
        "nfl-team-video-extended",
        "nfl-public-video-extended",
    ]
    assert all(row["version"] == 2 for row in rows)
    assert all("youtube-playlist" not in row["key"] for row in rows)


def test_configure_audit_sources_replaces_only_nfl_stack():
    server = FakeServer()
    original_nba = list(server.HISTORY_OFFICIAL_CATCHUP_SOURCES["NBA"])
    assert MOD.configure_audit_sources(server) is True
    assert server.HISTORY_OFFICIAL_CATCHUP_SOURCES["NFL"] == MOD.active_nfl_audit_sources()
    assert server.HISTORY_OFFICIAL_CATCHUP_SOURCES["NBA"] == original_nba


def test_retire_persisted_playlist_assets_marks_failed_but_preserves_rows():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
        _seed_repository(tmp.name)
        repo = FakeRepository(tmp.name)
        result = MOD.retire_persisted_playlist_assets(repo, now=1234.0)
        assert result == {"matched": 1, "retired": 1}

        conn = repo._connect()
        playlist = conn.execute("SELECT * FROM history_source_media WHERE asset_key='playlist-asset'").fetchone()
        team = conn.execute("SELECT * FROM history_source_media WHERE asset_key='team-asset'").fetchone()
        assert playlist is not None
        assert playlist["runtime_state"] == "FAILED"
        assert playlist["runtime_failure_reason"] == MOD._RETIRE_REASON
        item = json.loads(playlist["asset_json"])
        assert item["sourceRetired"] is True
        assert item["verifiedPlayable"] is False
        assert item["runtimeCatalogState"] == "FAILED"
        assert team["runtime_state"] == "PLAYED"
        conn.close()

        again = MOD.retire_persisted_playlist_assets(repo, now=5678.0)
        assert again == {"matched": 1, "retired": 0}


def test_source_retired_marker_remains_non_playable_after_rehydration():
    item = {
        "league": "NFL",
        "sourceRetired": True,
        "sourceRetiredReason": MOD._RETIRE_REASON,
        "discoverySourceFamily": "youtube",
        "sourceType": "generic-youtube",
    }

    def original(candidate, league, event_id, objective=""):
        return "PERSISTED_QUICK"

    assert MOD.persisted_disposition(item, "NFL", "1", "quick", original) == "PERSISTENCE_NON_PLAYABLE"
    assert MOD.persisted_disposition(item, "NBA", "1", "quick", original) == "PERSISTED_QUICK"

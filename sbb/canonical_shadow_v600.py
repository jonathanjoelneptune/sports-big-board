"""Sports Big Board v6.0 Canonical Slate shadow architecture.

This module is deliberately non-authoritative in v6.0.  It observes the existing
normalized history catalog and Day State read model, resolves durable SBB event
identities into a separate SQLite database, records schedule/score evidence, builds
versioned daily slates, and compares those slates against the production Day State
inventory.

Hard v6.0 safety boundary:
    * never mutates HISTORY_REPOSITORY
    * never mutates DayStateEngine snapshots
    * never changes /api/day-state or ribbon responses
    * never removes an event because a source stopped returning it
    * never claims CERTIFIED from legacy-derived evidence alone

Later releases can add authoritative and independent collectors through
CanonicalShadowEngine.observe_external_event() without replacing this schema.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

VERSION = "6.0.0-canonical-shadow-1"
SUPPORTED_LEAGUES = ("MLB", "NFL", "NBA", "NHL", "EPL", "MLS", "NCAAF")
LEAGUE_ALIASES = {
    "CFB": "NCAAF",
    "NCAAFOOTBALL": "NCAAF",
    "NCAA_FOOTBALL": "NCAAF",
    "COLLEGEFOOTBALL": "NCAAF",
}
ALL_EVENT_LEAGUES = frozenset(("MLB", "NFL", "NBA", "NHL", "EPL", "MLS"))
STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
DB_PATH = Path(os.environ.get("SBB_CANONICAL_DB_PATH") or (STATE_DIR / "canonical-shadow-v6.sqlite3")).expanduser()
LOOKBACK_DAYS = max(0, int(os.environ.get("SBB_CANONICAL_LOOKBACK_DAYS") or 7))
LOOKAHEAD_DAYS = max(0, int(os.environ.get("SBB_CANONICAL_LOOKAHEAD_DAYS") or 7))
HOT_SECONDS = max(15, int(os.environ.get("SBB_CANONICAL_HOT_SECONDS") or 60))
FULL_SECONDS = max(120, int(os.environ.get("SBB_CANONICAL_FULL_SECONDS") or 900))
HTTP_TIMEOUT = max(2, int(os.environ.get("SBB_CANONICAL_HTTP_TIMEOUT") or 8))
ESPN_SITE_API = str(os.environ.get("SBB_CANONICAL_ESPN_SITE_API") or "https://site.api.espn.com/apis/site/v2/sports").strip().rstrip("/")
ENABLED = str(os.environ.get("SBB_CANONICAL_SHADOW_ENABLED") or "1").strip().lower() not in {"0", "false", "no", "off"}
MODE = "shadow"

ESPN_DIRECT_COMPETITIONS = {
    "MLB": ("baseball", "mlb"),
    "NFL": ("football", "nfl"),
    "NBA": ("basketball", "nba"),
    "NHL": ("hockey", "nhl"),
    "EPL": ("soccer", "eng.1"),
    "MLS": ("soccer", "usa.1"),
    "NCAAF": ("football", "college-football"),
}
DISCOVERY_SOURCE_CLASSES = frozenset(("DIRECT", "AUTHORITATIVE", "INDEPENDENT"))

ET = ZoneInfo("America/New_York")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ENGINE = None


def _now() -> float:
    return time.time()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _load(value, fallback=None):
    try:
        return json.loads(value) if value else (fallback if fallback is not None else {})
    except Exception:
        return fallback if fallback is not None else {}


def _clean(value) -> str:
    return str(value or "").strip()


def _day(value) -> str:
    raw = _clean(value)[:10]
    return raw if _DATE_RE.fullmatch(raw) else ""


def _norm(value) -> str:
    value = _clean(value).lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", value)


def _team_obj(event, side):
    event = event or {}
    value = event.get(side)
    if not isinstance(value, dict):
        value = event.get(f"{side}Team")
    return value if isinstance(value, dict) else ({"name": value} if value else {})


def _team_name(event, side) -> str:
    team = _team_obj(event, side)
    return _clean(
        team.get("displayName") or team.get("name") or team.get("shortName")
        or team.get("abbreviation") or team.get("teamName")
    )


def _team_key(event, side) -> str:
    team = _team_obj(event, side)
    value = (
        team.get("id") or team.get("uid") or team.get("abbreviation")
        or team.get("displayName") or team.get("name") or team.get("shortName")
    )
    return _norm(value)


def _league(event, fallback="") -> str:
    event = event or {}
    raw = event.get("competitionId") or event.get("__sbbLeague") or event.get("league") or fallback
    if isinstance(raw, dict):
        raw = raw.get("id") or raw.get("abbreviation") or raw.get("name")
    value = _clean(raw).upper()
    return LEAGUE_ALIASES.get(value, value)


def _scheduled_at(event) -> str:
    event = event or {}
    for key in ("scheduledAt", "startTime", "startDate", "dateTime", "datetime", "date"):
        value = event.get(key)
        if isinstance(value, str) and ("T" in value or ":" in value):
            return value.strip()
    return ""


def _epoch(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = _clean(value)
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw).timestamp()
    except Exception:
        return None


def _event_sequence(event) -> str:
    event = event or {}
    for key in ("eventSequence", "gameNumber", "gameNo", "doubleheaderGame", "seriesGameNumber", "sequence"):
        value = event.get(key)
        if value not in (None, ""):
            return _clean(value)
    text = " ".join(_clean(event.get(k)) for k in ("name", "shortName", "description", "notes"))
    match = re.search(r"\bgame\s*([12])\b", text, re.I)
    return match.group(1) if match else ""


def _venue(event) -> str:
    value = (event or {}).get("venue")
    if isinstance(value, dict):
        return _clean(value.get("fullName") or value.get("name") or value.get("id"))
    return _clean(value)


def _status(event) -> str:
    raw = (event or {}).get("status")
    if isinstance(raw, dict):
        raw = raw.get("type") or raw.get("name") or raw.get("state") or raw.get("description")
        if isinstance(raw, dict):
            raw = raw.get("name") or raw.get("state") or raw.get("description")
    value = _clean(raw).upper()
    if any(x in value for x in ("FINAL", "COMPLETED", "FINISHED", "FT")):
        return "FINAL"
    if any(x in value for x in ("LIVE", "IN_PROGRESS", "IN PROGRESS", "HALFTIME", "QTR", "PERIOD")):
        return "LIVE"
    if "POSTPON" in value:
        return "POSTPONED"
    if "CANCEL" in value:
        return "CANCELLED"
    return "SCHEDULED"


def _score(event, side):
    event = event or {}
    for key in (f"{side}Score", f"{side}_score"):
        if event.get(key) not in (None, ""):
            return event.get(key)
    team = _team_obj(event, side)
    if team.get("score") not in (None, ""):
        return team.get("score")
    return None


def _period(event):
    event = event or {}
    for key in ("period", "quarter", "inning", "set", "segment"):
        value = event.get(key)
        if value not in (None, ""):
            return value
    status = event.get("status")
    if isinstance(status, dict):
        return status.get("period")
    return None


def _clock(event):
    event = event or {}
    for key in ("displayClock", "clock"):
        if event.get(key) not in (None, ""):
            return event.get(key)
    status = event.get("status")
    if isinstance(status, dict):
        return status.get("displayClock") or status.get("clock")
    return None


def _provider_ids(event, source=""):
    event = event or {}
    specs = (
        ("ESPN", "espnEventId", "ESPN_EVENT_ID"),
        ("MLB", "gamePk", "MLB_GAME_PK"),
        ("SCORE", "scoreEventId", "SCORE_EVENT_ID"),
        ("MATCH", "matchId", "MATCH_ID"),
        ("GAMECENTER", "gameCenterEventId", "GAME_CENTER_EVENT_ID"),
        ("LEGACY_CANONICAL", "canonicalEventId", "CANONICAL_EVENT_ID"),
        (_clean(source).upper() or "SOURCE", "eventId", "EVENT_ID"),
        (_clean(source).upper() or "SOURCE", "id", "ID"),
    )
    out = []
    seen = set()
    for provider, key, id_type in specs:
        value = event.get(key)
        if value in (None, ""):
            continue
        pair = (provider, str(value))
        if pair in seen:
            continue
        seen.add(pair)
        out.append((provider, str(value), id_type))
    return out


def _payload_hash(payload) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _event_day(event, fallback="") -> str:
    event = event or {}
    for key in ("__sbbDate", "gameDate", "slateDate", "eventDate"):
        value = _day(event.get(key))
        if value:
            return value
    raw = event.get("date")
    value = _day(raw)
    if value:
        return value
    return _day(fallback)


class CanonicalShadowStore:
    """Separate v6 SQLite authority candidate. Production never reads from it."""

    def __init__(self, path=DB_PATH):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self, readonly=False):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        if readonly:
            conn.execute("PRAGMA query_only=ON")
        return conn

    def _init_db(self):
        with self._lock, closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS canonical_event (
                    canonical_event_id TEXT PRIMARY KEY,
                    competition_id TEXT NOT NULL,
                    sport_id TEXT NOT NULL DEFAULT '',
                    slate_date TEXT NOT NULL,
                    away_key TEXT NOT NULL DEFAULT '', away_name TEXT NOT NULL DEFAULT '',
                    home_key TEXT NOT NULL DEFAULT '', home_name TEXT NOT NULL DEFAULT '',
                    scheduled_at TEXT NOT NULL DEFAULT '', event_sequence TEXT NOT NULL DEFAULT '',
                    venue TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'SCHEDULED',
                    identity_state TEXT NOT NULL DEFAULT 'RESOLVED',
                    inclusion_state TEXT NOT NULL DEFAULT 'UNKNOWN',
                    inclusion_reason TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    removal_state TEXT NOT NULL DEFAULT 'PRESENT',
                    first_source TEXT NOT NULL DEFAULT '', raw_json TEXT NOT NULL DEFAULT '{}',
                    first_seen_at REAL NOT NULL, last_seen_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cev_day_league ON canonical_event(slate_date,competition_id);
                CREATE INDEX IF NOT EXISTS idx_cev_pair ON canonical_event(slate_date,competition_id,away_key,home_key);
                CREATE INDEX IF NOT EXISTS idx_cev_inclusion ON canonical_event(slate_date,competition_id,inclusion_state);

                CREATE TABLE IF NOT EXISTS provider_event_mapping (
                    canonical_event_id TEXT NOT NULL,
                    provider TEXT NOT NULL, provider_event_id TEXT NOT NULL, id_type TEXT NOT NULL DEFAULT '',
                    first_seen_at REAL NOT NULL, last_seen_at REAL NOT NULL,
                    PRIMARY KEY(provider,provider_event_id),
                    FOREIGN KEY(canonical_event_id) REFERENCES canonical_event(canonical_event_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_provider_event ON provider_event_mapping(canonical_event_id);

                CREATE TABLE IF NOT EXISTS schedule_observation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_event_id TEXT NOT NULL,
                    source TEXT NOT NULL, source_class TEXT NOT NULL DEFAULT 'LEGACY',
                    observed_day TEXT NOT NULL, observed_at REAL NOT NULL, last_observed_at REAL NOT NULL,
                    observation_count INTEGER NOT NULL DEFAULT 1,
                    scheduled_at TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '',
                    payload_hash TEXT NOT NULL, raw_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(canonical_event_id,source,payload_hash),
                    FOREIGN KEY(canonical_event_id) REFERENCES canonical_event(canonical_event_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_sched_obs_event ON schedule_observation(canonical_event_id,last_observed_at);
                CREATE INDEX IF NOT EXISTS idx_sched_obs_source ON schedule_observation(source,observed_day);

                CREATE TABLE IF NOT EXISTS source_coverage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slate_date TEXT NOT NULL, competition_id TEXT NOT NULL,
                    source TEXT NOT NULL, source_class TEXT NOT NULL,
                    observed_at REAL NOT NULL, last_observed_at REAL NOT NULL,
                    observation_count INTEGER NOT NULL DEFAULT 1,
                    success INTEGER NOT NULL DEFAULT 1, result_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '', coverage_hash TEXT NOT NULL,
                    UNIQUE(slate_date,competition_id,source,coverage_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_source_coverage_day ON source_coverage(slate_date,competition_id,last_observed_at);

                CREATE TABLE IF NOT EXISTS score_observation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_event_id TEXT NOT NULL,
                    source TEXT NOT NULL, observed_at REAL NOT NULL, last_observed_at REAL NOT NULL,
                    observation_count INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT '', away_score TEXT, home_score TEXT,
                    period TEXT, clock TEXT, payload_hash TEXT NOT NULL,
                    UNIQUE(canonical_event_id,source,payload_hash),
                    FOREIGN KEY(canonical_event_id) REFERENCES canonical_event(canonical_event_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_score_obs_event ON score_observation(canonical_event_id,last_observed_at);

                CREATE TABLE IF NOT EXISTS daily_slate (
                    slate_id TEXT PRIMARY KEY,
                    slate_date TEXT NOT NULL, competition_id TEXT NOT NULL, version INTEGER NOT NULL,
                    certification_status TEXT NOT NULL, certification_reason TEXT NOT NULL DEFAULT '',
                    universe_count INTEGER NOT NULL DEFAULT 0, included_count INTEGER NOT NULL DEFAULT 0,
                    excluded_count INTEGER NOT NULL DEFAULT 0, unknown_count INTEGER NOT NULL DEFAULT 0,
                    unresolved_count INTEGER NOT NULL DEFAULT 0, conflict_count INTEGER NOT NULL DEFAULT 0,
                    source_class_count INTEGER NOT NULL DEFAULT 0, membership_hash TEXT NOT NULL,
                    baseline_kind TEXT NOT NULL DEFAULT 'RECONCILIATION', generated_at REAL NOT NULL,
                    UNIQUE(slate_date,competition_id,version)
                );
                CREATE INDEX IF NOT EXISTS idx_slate_day ON daily_slate(slate_date,competition_id,version);

                CREATE TABLE IF NOT EXISTS daily_slate_event (
                    slate_id TEXT NOT NULL, canonical_event_id TEXT NOT NULL,
                    inclusion_state TEXT NOT NULL, inclusion_reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '', scheduled_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(slate_id,canonical_event_id),
                    FOREIGN KEY(slate_id) REFERENCES daily_slate(slate_id) ON DELETE CASCADE,
                    FOREIGN KEY(canonical_event_id) REFERENCES canonical_event(canonical_event_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS slate_comparison (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slate_date TEXT NOT NULL, competition_id TEXT NOT NULL,
                    observed_at REAL NOT NULL, last_observed_at REAL NOT NULL,
                    observation_count INTEGER NOT NULL DEFAULT 1,
                    canonical_count INTEGER NOT NULL, legacy_count INTEGER NOT NULL,
                    matched_count INTEGER NOT NULL, canonical_only_count INTEGER NOT NULL,
                    legacy_only_count INTEGER NOT NULL, conflict_count INTEGER NOT NULL DEFAULT 0,
                    comparison_hash TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(slate_date,competition_id,comparison_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_compare_day ON slate_comparison(slate_date,competition_id,last_observed_at);

                CREATE TABLE IF NOT EXISTS shadow_run (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_kind TEXT NOT NULL, started_at REAL NOT NULL, completed_at REAL NOT NULL DEFAULT 0,
                    dates_from TEXT NOT NULL DEFAULT '', dates_to TEXT NOT NULL DEFAULT '',
                    direct_rows INTEGER NOT NULL DEFAULT 0, direct_errors INTEGER NOT NULL DEFAULT 0,
                    catalog_rows INTEGER NOT NULL DEFAULT 0, day_state_rows INTEGER NOT NULL DEFAULT 0,
                    events_touched INTEGER NOT NULL DEFAULT 0, slates_touched INTEGER NOT NULL DEFAULT 0,
                    comparisons_touched INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT ''
                );
            """)
            conn.commit()

    def begin_run(self, run_kind, day_from="", day_to=""):
        with self._lock, closing(self._connect()) as conn:
            cur = conn.execute(
                "INSERT INTO shadow_run(run_kind,started_at,dates_from,dates_to) VALUES(?,?,?,?)",
                (run_kind, _now(), day_from, day_to),
            )
            conn.commit()
            return int(cur.lastrowid)

    def finish_run(self, run_id, **stats):
        with self._lock, closing(self._connect()) as conn:
            conn.execute("""
                UPDATE shadow_run SET completed_at=?, direct_rows=?, direct_errors=?, catalog_rows=?, day_state_rows=?,
                    events_touched=?, slates_touched=?, comparisons_touched=?, error=? WHERE id=?
            """, (
                _now(), int(stats.get("direct_rows") or 0), int(stats.get("direct_errors") or 0),
                int(stats.get("catalog_rows") or 0), int(stats.get("day_state_rows") or 0),
                int(stats.get("events_touched") or 0), int(stats.get("slates_touched") or 0),
                int(stats.get("comparisons_touched") or 0), _clean(stats.get("error")), int(run_id),
            ))
            conn.commit()

    def mapping_lookup(self, provider_ids):
        provider_ids = list(provider_ids or [])
        if not provider_ids:
            return ""
        with closing(self._connect(readonly=True)) as conn:
            for provider, provider_event_id, _id_type in provider_ids:
                row = conn.execute(
                    "SELECT canonical_event_id FROM provider_event_mapping WHERE provider=? AND provider_event_id=?",
                    (provider, provider_event_id),
                ).fetchone()
                if row:
                    return str(row[0])
        return ""

    def pair_candidates(self, league, slate_date, away_key, home_key):
        if not league or not slate_date or not away_key or not home_key:
            return []
        with closing(self._connect(readonly=True)) as conn:
            rows = conn.execute("""
                SELECT * FROM canonical_event WHERE competition_id=? AND slate_date=?
                  AND away_key=? AND home_key=? AND active=1 ORDER BY first_seen_at
            """, (league, slate_date, away_key, home_key)).fetchall()
            return [dict(x) for x in rows]

    def mappings_for_event(self, canonical_event_id):
        with closing(self._connect(readonly=True)) as conn:
            rows = conn.execute(
                "SELECT provider,provider_event_id,id_type FROM provider_event_mapping WHERE canonical_event_id=?",
                (canonical_event_id,),
            ).fetchall()
            return [dict(x) for x in rows]

    def upsert_event(self, canonical_event_id, league, slate_date, event, source, identity_state, inclusion_state, inclusion_reason):
        now = _now()
        away_key, home_key = _team_key(event, "away"), _team_key(event, "home")
        away_name, home_name = _team_name(event, "away"), _team_name(event, "home")
        scheduled = _scheduled_at(event)
        sequence = _event_sequence(event)
        venue = _venue(event)
        status = _status(event)
        sport = _clean(event.get("sportId") or event.get("sport") or "")
        raw = _json(event)
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM canonical_event WHERE canonical_event_id=?", (canonical_event_id,)).fetchone()
            if row:
                # Absence never deletes.  New positive observations update mutable facts.
                old = dict(row)
                new_inclusion = inclusion_state
                new_reason = inclusion_reason
                if old.get("inclusion_state") == "INCLUDED" and inclusion_state != "INCLUDED":
                    new_inclusion = "INCLUDED"
                    new_reason = old.get("inclusion_reason") or inclusion_reason
                conn.execute("""
                    UPDATE canonical_event SET sport_id=COALESCE(NULLIF(?,''),sport_id),
                        away_key=COALESCE(NULLIF(?,''),away_key), away_name=COALESCE(NULLIF(?,''),away_name),
                        home_key=COALESCE(NULLIF(?,''),home_key), home_name=COALESCE(NULLIF(?,''),home_name),
                        scheduled_at=COALESCE(NULLIF(?,''),scheduled_at),
                        event_sequence=COALESCE(NULLIF(?,''),event_sequence), venue=COALESCE(NULLIF(?,''),venue),
                        status=?, identity_state=?, inclusion_state=?, inclusion_reason=?,
                        raw_json=?, last_seen_at=?, updated_at=? WHERE canonical_event_id=?
                """, (sport, away_key, away_name, home_key, home_name, scheduled, sequence, venue,
                      status, identity_state, new_inclusion, new_reason, raw, now, now, canonical_event_id))
            else:
                conn.execute("""
                    INSERT INTO canonical_event(
                        canonical_event_id,competition_id,sport_id,slate_date,away_key,away_name,home_key,home_name,
                        scheduled_at,event_sequence,venue,status,identity_state,inclusion_state,inclusion_reason,
                        first_source,raw_json,first_seen_at,last_seen_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (canonical_event_id, league, sport, slate_date, away_key, away_name, home_key, home_name,
                      scheduled, sequence, venue, status, identity_state, inclusion_state, inclusion_reason,
                      source, raw, now, now, now))
            conn.commit()

    def upsert_mappings(self, canonical_event_id, provider_ids):
        now = _now()
        with self._lock, closing(self._connect()) as conn:
            for provider, provider_event_id, id_type in provider_ids:
                existing = conn.execute(
                    "SELECT canonical_event_id FROM provider_event_mapping WHERE provider=? AND provider_event_id=?",
                    (provider, provider_event_id),
                ).fetchone()
                if existing and str(existing[0]) != canonical_event_id:
                    # Identity conflicts are evidence, not grounds to rewrite ownership.
                    continue
                conn.execute("""
                    INSERT INTO provider_event_mapping(canonical_event_id,provider,provider_event_id,id_type,first_seen_at,last_seen_at)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(provider,provider_event_id) DO UPDATE SET last_seen_at=excluded.last_seen_at
                """, (canonical_event_id, provider, provider_event_id, id_type, now, now))
            conn.commit()

    def record_schedule(self, canonical_event_id, source, source_class, slate_date, event):
        now = _now()
        payload = {
            "scheduledAt": _scheduled_at(event), "status": _status(event),
            "away": _team_name(event, "away"), "home": _team_name(event, "home"),
            "sequence": _event_sequence(event), "venue": _venue(event),
            "providerIds": [(a, b, c) for a, b, c in _provider_ids(event, source)],
        }
        digest = _payload_hash(payload)
        with self._lock, closing(self._connect()) as conn:
            conn.execute("""
                INSERT INTO schedule_observation(
                    canonical_event_id,source,source_class,observed_day,observed_at,last_observed_at,
                    scheduled_at,status,payload_hash,raw_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(canonical_event_id,source,payload_hash) DO UPDATE SET
                    last_observed_at=excluded.last_observed_at, observation_count=observation_count+1
            """, (canonical_event_id, source, source_class, slate_date, now, now,
                  payload["scheduledAt"], payload["status"], digest, _json(event)))
            conn.commit()

    def record_score(self, canonical_event_id, source, event):
        now = _now()
        payload = {
            "status": _status(event), "awayScore": _score(event, "away"), "homeScore": _score(event, "home"),
            "period": _period(event), "clock": _clock(event),
        }
        digest = _payload_hash(payload)
        with self._lock, closing(self._connect()) as conn:
            conn.execute("""
                INSERT INTO score_observation(
                    canonical_event_id,source,observed_at,last_observed_at,status,away_score,home_score,period,clock,payload_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(canonical_event_id,source,payload_hash) DO UPDATE SET
                    last_observed_at=excluded.last_observed_at, observation_count=observation_count+1
            """, (canonical_event_id, source, now, now, payload["status"],
                  None if payload["awayScore"] is None else str(payload["awayScore"]),
                  None if payload["homeScore"] is None else str(payload["homeScore"]),
                  None if payload["period"] is None else str(payload["period"]),
                  None if payload["clock"] is None else str(payload["clock"]), digest))
            conn.commit()

    def record_source_coverage(self, slate_date, league, source, source_class, success=True, result_count=0, error=""):
        payload = {
            "success": bool(success), "resultCount": int(result_count or 0),
            "error": _clean(error), "sourceClass": _clean(source_class).upper(),
        }
        digest = _payload_hash(payload)
        now = _now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute("""
                INSERT INTO source_coverage(
                    slate_date,competition_id,source,source_class,observed_at,last_observed_at,
                    success,result_count,error,coverage_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(slate_date,competition_id,source,coverage_hash) DO UPDATE SET
                    last_observed_at=excluded.last_observed_at, observation_count=observation_count+1
            """, (slate_date, league, source, _clean(source_class).upper(), now, now, int(bool(success)),
                  int(result_count or 0), _clean(error), digest))
            conn.commit()

    def coverage_classes(self, slate_date, league):
        with closing(self._connect(readonly=True)) as conn:
            rows = conn.execute("""
                SELECT DISTINCT source_class FROM source_coverage
                WHERE slate_date=? AND competition_id=? AND success=1
            """, (slate_date, league)).fetchall()
            return {str(x[0]).upper() for x in rows if x[0]}

    def events_for_day(self, slate_date, league=""):
        params = [slate_date]
        where = "slate_date=? AND active=1"
        if league:
            where += " AND competition_id=?"
            params.append(league)
        with closing(self._connect(readonly=True)) as conn:
            rows = conn.execute(f"SELECT * FROM canonical_event WHERE {where} ORDER BY competition_id,scheduled_at,canonical_event_id", params).fetchall()
            return [dict(x) for x in rows]

    def evidence_classes(self, event_id):
        with closing(self._connect(readonly=True)) as conn:
            rows = conn.execute(
                "SELECT DISTINCT source_class FROM schedule_observation WHERE canonical_event_id=?",
                (event_id,),
            ).fetchall()
            return {str(x[0]).upper() for x in rows if x[0]}

    def has_shadow_discovery_evidence(self, event_id):
        return bool(self.evidence_classes(event_id) & DISCOVERY_SOURCE_CLASSES)

    def compile_slate(self, slate_date, league, baseline_kind="RECONCILIATION", force_version=False):
        events = self.events_for_day(slate_date, league)
        included = [x for x in events if x["inclusion_state"] == "INCLUDED"]
        excluded = [x for x in events if x["inclusion_state"] == "EXCLUDED"]
        unknown = [x for x in events if x["inclusion_state"] not in {"INCLUDED", "EXCLUDED"}]
        unresolved = [x for x in events if x["identity_state"] != "RESOLVED"]

        classes = set()
        coverage_classes = self.coverage_classes(slate_date, league)
        classes.update(coverage_classes)
        # Coverage evidence proves that a source successfully checked the whole
        # league/date, including a legitimate zero-event answer. Event evidence
        # proves identity for the events that do exist. Both are required.
        independently_proven = {"AUTHORITATIVE", "INDEPENDENT"} <= coverage_classes
        for event in included:
            event_classes = self.evidence_classes(event["canonical_event_id"])
            classes.update(event_classes)
            if not ({"AUTHORITATIVE", "INDEPENDENT"} <= event_classes):
                independently_proven = False

        if unresolved:
            certification = "RECONCILING"
            reason = f"{len(unresolved)} identity conflict(s) require resolution"
        elif unknown:
            certification = "RECONCILING"
            reason = f"{len(unknown)} event(s) have unresolved SBB inclusion policy"
        elif independently_proven:
            certification = "CERTIFIED"
            reason = "Authoritative + independent date coverage is complete and every included event is independently proven"
        else:
            certification = "SHADOW_BASELINE"
            reason = "Legacy-derived evidence captured; independent certification evidence not yet complete"

        # A slate versions schedule/existence truth, while score_observation owns live
        # state.  LIVE/FINAL transitions therefore must not create a new slate
        # version every time a game advances.  Postponed/cancelled are schedule
        # material and intentionally remain in the membership hash.
        members = [{
            "id": x["canonical_event_id"], "include": x["inclusion_state"], "reason": x["inclusion_reason"],
            "scheduleStatus": x["status"] if x["status"] in {"POSTPONED", "CANCELLED"} else "ACTIVE",
            "scheduledAt": x["scheduled_at"],
        } for x in events]
        membership_hash = _payload_hash(members)
        with self._lock, closing(self._connect()) as conn:
            prior = conn.execute("""
                SELECT * FROM daily_slate WHERE slate_date=? AND competition_id=? ORDER BY version DESC LIMIT 1
            """, (slate_date, league)).fetchone()
            if prior and not force_version and str(prior["membership_hash"]) == membership_hash and str(prior["certification_status"]) == certification:
                return dict(prior), False
            version = int(prior["version"] if prior else 0) + 1
            slate_id = f"{slate_date}:{league}:v{version}"
            conn.execute("""
                INSERT INTO daily_slate(
                    slate_id,slate_date,competition_id,version,certification_status,certification_reason,
                    universe_count,included_count,excluded_count,unknown_count,unresolved_count,conflict_count,
                    source_class_count,membership_hash,baseline_kind,generated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (slate_id, slate_date, league, version, certification, reason, len(events), len(included),
                  len(excluded), len(unknown), len(unresolved), 0, len(classes), membership_hash, baseline_kind, _now()))
            conn.executemany("""
                INSERT INTO daily_slate_event(slate_id,canonical_event_id,inclusion_state,inclusion_reason,status,scheduled_at)
                VALUES(?,?,?,?,?,?)
            """, [(slate_id, x["canonical_event_id"], x["inclusion_state"], x["inclusion_reason"], x["status"], x["scheduled_at"]) for x in events])
            conn.commit()
            row = conn.execute("SELECT * FROM daily_slate WHERE slate_id=?", (slate_id,)).fetchone()
            return dict(row), True

    def record_comparison(self, slate_date, league, legacy_ids):
        # Compare the NEW shadow discovery path against production, not the safety
        # union. Legacy Day State observations are deliberately admitted to the DB
        # so v6.0 can never lose production knowledge, but counting those as
        # canonical discoveries would make a legacy-only miss mathematically
        # impossible to see.
        included_rows = [x for x in self.events_for_day(slate_date, league) if x["inclusion_state"] == "INCLUDED"]
        shadow_union = {x["canonical_event_id"] for x in included_rows}
        canonical = {x["canonical_event_id"] for x in included_rows if self.has_shadow_discovery_evidence(x["canonical_event_id"])}
        legacy = set(legacy_ids or [])
        matched = canonical & legacy
        canonical_only = sorted(canonical - legacy)
        legacy_only = sorted(legacy - canonical)
        details = {
            "canonicalOnly": canonical_only,
            "legacyOnly": legacy_only,
            "matched": len(matched),
            "shadowDiscoveryCount": len(canonical),
            "shadowSafetyUnionCount": len(shadow_union),
            "legacyFallbackOnly": sorted((legacy & shadow_union) - canonical),
        }
        digest = _payload_hash(details)
        now = _now()
        with self._lock, closing(self._connect()) as conn:
            conn.execute("""
                INSERT INTO slate_comparison(
                    slate_date,competition_id,observed_at,last_observed_at,canonical_count,legacy_count,
                    matched_count,canonical_only_count,legacy_only_count,conflict_count,comparison_hash,details_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(slate_date,competition_id,comparison_hash) DO UPDATE SET
                    last_observed_at=excluded.last_observed_at, observation_count=observation_count+1
            """, (slate_date, league, now, now, len(canonical), len(legacy), len(matched), len(canonical_only),
                  len(legacy_only), 0, digest, _json(details)))
            conn.commit()
        return details

    def has_daily_baseline(self, slate_date, league):
        with closing(self._connect(readonly=True)) as conn:
            row = conn.execute(
                """SELECT 1 FROM daily_slate WHERE slate_date=? AND competition_id=?
                   AND baseline_kind='DAILY_BASELINE_0200_ET' LIMIT 1""",
                (slate_date, league),
            ).fetchone()
            return bool(row)

    def latest_slates(self, slate_date, league=""):
        params = [slate_date]
        extra = ""
        if league:
            extra = " AND d.competition_id=?"
            params.append(league)
        with closing(self._connect(readonly=True)) as conn:
            rows = conn.execute(f"""
                SELECT d.* FROM daily_slate d JOIN (
                    SELECT slate_date,competition_id,MAX(version) version FROM daily_slate
                    WHERE slate_date=? GROUP BY slate_date,competition_id
                ) x ON x.slate_date=d.slate_date AND x.competition_id=d.competition_id AND x.version=d.version
                WHERE 1=1 {extra} ORDER BY d.competition_id
            """, params).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                evs = conn.execute("""
                    SELECT e.*, c.away_name,c.home_name,c.identity_state,c.first_seen_at,c.last_seen_at
                    FROM daily_slate_event e JOIN canonical_event c ON c.canonical_event_id=e.canonical_event_id
                    WHERE e.slate_id=? ORDER BY e.scheduled_at,e.canonical_event_id
                """, (item["slate_id"],)).fetchall()
                item["events"] = [dict(x) for x in evs]
                result.append(item)
            return result

    def latest_comparisons(self, slate_date, league=""):
        params = [slate_date]
        extra = ""
        if league:
            extra = " AND c.competition_id=?"
            params.append(league)
        with closing(self._connect(readonly=True)) as conn:
            rows = conn.execute(f"""
                SELECT c.* FROM slate_comparison c JOIN (
                    SELECT slate_date,competition_id,MAX(last_observed_at) last_at FROM slate_comparison
                    WHERE slate_date=? GROUP BY slate_date,competition_id
                ) x ON x.slate_date=c.slate_date AND x.competition_id=c.competition_id AND x.last_at=c.last_observed_at
                WHERE 1=1 {extra} ORDER BY c.competition_id
            """, params).fetchall()
            out = []
            for row in rows:
                item = dict(row)
                item["details"] = _load(item.pop("details_json", "{}"), {})
                out.append(item)
            return out

    def event_detail(self, event_id):
        with closing(self._connect(readonly=True)) as conn:
            row = conn.execute("SELECT * FROM canonical_event WHERE canonical_event_id=?", (event_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["raw"] = _load(item.pop("raw_json", "{}"), {})
            item["providerMappings"] = [dict(x) for x in conn.execute(
                "SELECT * FROM provider_event_mapping WHERE canonical_event_id=? ORDER BY provider", (event_id,)
            ).fetchall()]
            sched = [dict(x) for x in conn.execute(
                "SELECT * FROM schedule_observation WHERE canonical_event_id=? ORDER BY last_observed_at DESC LIMIT 100", (event_id,)
            ).fetchall()]
            for x in sched:
                x["raw"] = _load(x.pop("raw_json", "{}"), {})
            item["scheduleObservations"] = sched
            item["sourceCoverage"] = [dict(x) for x in conn.execute(
                "SELECT * FROM source_coverage WHERE slate_date=? AND competition_id=? ORDER BY last_observed_at DESC LIMIT 100",
                (item["slate_date"], item["competition_id"])
            ).fetchall()]
            item["scoreObservations"] = [dict(x) for x in conn.execute(
                "SELECT * FROM score_observation WHERE canonical_event_id=? ORDER BY last_observed_at DESC LIMIT 100", (event_id,)
            ).fetchall()]
            return item

    def health(self):
        with closing(self._connect(readonly=True)) as conn:
            def scalar(sql, params=()):
                row = conn.execute(sql, params).fetchone()
                return row[0] if row else 0
            last = conn.execute("SELECT * FROM shadow_run ORDER BY id DESC LIMIT 1").fetchone()
            statuses = conn.execute("""
                SELECT certification_status,COUNT(*) n FROM daily_slate d JOIN (
                    SELECT slate_date,competition_id,MAX(version) version FROM daily_slate GROUP BY slate_date,competition_id
                ) x ON x.slate_date=d.slate_date AND x.competition_id=d.competition_id AND x.version=d.version
                GROUP BY certification_status
            """).fetchall()
            return {
                "databasePath": self.path,
                "canonicalEvents": int(scalar("SELECT COUNT(*) FROM canonical_event")),
                "providerMappings": int(scalar("SELECT COUNT(*) FROM provider_event_mapping")),
                "scheduleObservations": int(scalar("SELECT COUNT(*) FROM schedule_observation")),
                "sourceCoverageRecords": int(scalar("SELECT COUNT(*) FROM source_coverage")),
                "scoreObservations": int(scalar("SELECT COUNT(*) FROM score_observation")),
                "slateVersions": int(scalar("SELECT COUNT(*) FROM daily_slate")),
                "comparisons": int(scalar("SELECT COUNT(*) FROM slate_comparison")),
                "latestCertification": {str(x[0]): int(x[1]) for x in statuses},
                "lastRun": dict(last) if last else None,
            }


class CanonicalIdentityResolver:
    """Conservative event resolver: strong IDs first, team/date evidence second."""

    def __init__(self, store):
        self.store = store

    def resolve(self, league, slate_date, event, source):
        provider_ids = _provider_ids(event, source)
        mapped = self.store.mapping_lookup(provider_ids)
        if mapped:
            return mapped, "RESOLVED", "PROVIDER_MAPPING"

        away_key, home_key = _team_key(event, "away"), _team_key(event, "home")
        sequence = _event_sequence(event)
        candidates = self.store.pair_candidates(league, slate_date, away_key, home_key)
        if not candidates:
            return self._new_id(), "RESOLVED", "NEW_EVENT"

        if sequence:
            matches = [x for x in candidates if _clean(x.get("event_sequence")) == sequence]
            if len(matches) == 1:
                return matches[0]["canonical_event_id"], "RESOLVED", "PAIR_SEQUENCE"
            if len(matches) > 1:
                return self._new_id(), "UNRESOLVED_PAIR_COLLISION", "AMBIGUOUS_SEQUENCE"
            known_sequences = [_clean(x.get("event_sequence")) for x in candidates]
            if known_sequences and all(x and x != sequence for x in known_sequences):
                return self._new_id(), "RESOLVED", "DISTINCT_SEQUENCE"

        incoming_map = {(a, b) for a, b, _ in provider_ids}
        incoming_by_provider = defaultdict(set)
        for provider, pid in incoming_map:
            incoming_by_provider[provider].add(pid)

        compatible = []
        incoming_time = _epoch(_scheduled_at(event))
        for candidate in candidates:
            existing_maps = self.store.mappings_for_event(candidate["canonical_event_id"])
            hard_conflict = False
            for mapping in existing_maps:
                provider = str(mapping["provider"])
                if provider in incoming_by_provider and str(mapping["provider_event_id"]) not in incoming_by_provider[provider]:
                    hard_conflict = True
                    break
            if hard_conflict:
                continue
            existing_time = _epoch(candidate.get("scheduled_at"))
            if incoming_time is not None and existing_time is not None and abs(incoming_time - existing_time) > 2 * 3600:
                # Same teams on the same day but materially different start times can
                # be a doubleheader.  Do not merge without stronger identity evidence.
                continue
            compatible.append(candidate)

        if len(compatible) == 1:
            return compatible[0]["canonical_event_id"], "RESOLVED", "PAIR_TIME"
        if len(candidates) == 1 and not compatible:
            return self._new_id(), "UNRESOLVED_PAIR_COLLISION", "POSSIBLE_DOUBLEHEADER"
        return self._new_id(), "UNRESOLVED_PAIR_COLLISION", "AMBIGUOUS_PAIR"

    @staticmethod
    def _new_id():
        return "cev_" + uuid.uuid4().hex[:24]


class CanonicalShadowEngine:
    def __init__(self, server, store=None):
        self.server = server
        self.store = store or CanonicalShadowStore()
        self.resolver = CanonicalIdentityResolver(self.store)
        self.running = True
        self.last_error = ""
        self.last_hot_at = 0.0
        self.last_full_at = 0.0
        self.baseline_dates = set()
        self.events_touched = 0
        self.comparisons_touched = 0
        self.last_source_errors = {}

    def today_et(self):
        return datetime.now(ET).date().isoformat()

    def _inclusion(self, league, source):
        if league in ALL_EVENT_LEAGUES:
            return "INCLUDED", "ALL_LEAGUE_EVENTS"
        if league == "NCAAF" and source == "DAY_STATE":
            return "INCLUDED", "LEGACY_BOARD_POLICY"
        if league == "NCAAF":
            return "UNKNOWN", "NCAAF_POLICY_PENDING"
        return "UNKNOWN", "UNSUPPORTED_POLICY"

    def observe_event(self, event, league, slate_date, source, source_class="LEGACY", inclusion_state=None, inclusion_reason=None):
        if not isinstance(event, dict):
            return ""
        league = _league(event, league)
        slate_date = _event_day(event, slate_date)
        if league not in SUPPORTED_LEAGUES or not slate_date:
            return ""
        if inclusion_state is None:
            inclusion_state, inclusion_reason = self._inclusion(league, source)
        event_id, identity_state, _method = self.resolver.resolve(league, slate_date, event, source)
        self.store.upsert_event(event_id, league, slate_date, event, source, identity_state, inclusion_state, inclusion_reason or "")
        provider_ids = _provider_ids(event, source)
        self.store.upsert_mappings(event_id, provider_ids)
        self.store.record_schedule(event_id, source, source_class, slate_date, event)
        self.store.record_score(event_id, source, event)
        self.events_touched += 1
        return event_id

    def observe_external_event(self, event, league, slate_date, source, source_class):
        """Stable extension point for v6.x independent collectors.

        source_class should be DIRECT for a separate fetch path, or AUTHORITATIVE /
        INDEPENDENT when the source is genuinely suitable for certification.
        """
        source_class = _clean(source_class).upper()
        if source_class not in {"AUTHORITATIVE", "INDEPENDENT", "DIRECT", "LEGACY"}:
            raise ValueError("source_class must be AUTHORITATIVE, INDEPENDENT, DIRECT, or LEGACY")
        return self.observe_event(event, league, slate_date, source, source_class)

    def observe_external_snapshot(self, events, league, slate_date, source, source_class, success=True, error=""):
        """Observe a complete provider response for one league/date.

        This is the preferred certification adapter API because it records both
        event evidence and source-level coverage, including successful zero rows.
        """
        rows = list(events or []) if success else []
        seen = []
        for event in rows:
            event_id = self.observe_external_event(event, league, slate_date, source, source_class)
            if event_id:
                seen.append(event_id)
        self.store.record_source_coverage(slate_date, _league({}, league), source, source_class, success, len(seen), error)
        return seen

    def _http_json(self, url, timeout=HTTP_TIMEOUT):
        req = Request(url, headers={"User-Agent": "SportsBigBoard/6.0 CanonicalShadow", "Accept": "application/json"})
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    @staticmethod
    def _espn_team(comp):
        team = comp.get("team") if isinstance(comp.get("team"), dict) else {}
        return {
            "id": _clean(team.get("id") or team.get("uid")),
            "name": _clean(team.get("name") or team.get("displayName") or team.get("shortDisplayName")),
            "displayName": _clean(team.get("displayName") or team.get("shortDisplayName") or team.get("name")),
            "abbreviation": _clean(team.get("abbreviation") or team.get("shortName")),
            "score": comp.get("score"),
        }

    def _espn_event(self, raw, league, slate_date):
        if not isinstance(raw, dict):
            return None
        comps = raw.get("competitions") or []
        game = comps[0] if comps and isinstance(comps[0], dict) else {}
        sides = {}
        for comp in game.get("competitors") or []:
            if not isinstance(comp, dict):
                continue
            side = _clean(comp.get("homeAway")).lower()
            if side in {"home", "away"}:
                sides[side] = comp
        if "home" not in sides or "away" not in sides:
            return None
        scheduled = _clean(raw.get("date") or game.get("date"))
        # ESPN's date filter occasionally returns boundary events around UTC. Keep
        # the SBB slate day explicit and reject a clearly different ET calendar day.
        ts = _epoch(scheduled)
        if ts is not None:
            event_day = datetime.fromtimestamp(ts, ET).date().isoformat()
            if event_day != slate_date:
                return None
        event = {
            "competitionId": league,
            "__sbbDate": slate_date,
            "espnEventId": _clean(raw.get("id")),
            "eventId": _clean(raw.get("id")),
            "scheduledAt": scheduled,
            "status": raw.get("status") or game.get("status") or "SCHEDULED",
            "away": self._espn_team(sides["away"]),
            "home": self._espn_team(sides["home"]),
            "awayScore": sides["away"].get("score"),
            "homeScore": sides["home"].get("score"),
            "venue": game.get("venue") or {},
            "name": _clean(raw.get("name") or raw.get("shortName")),
        }
        notes = game.get("notes") or []
        if notes:
            event["notes"] = " ".join(_clean(x.get("headline") if isinstance(x, dict) else x) for x in notes)
        if league == "NCAAF":
            ranks = []
            for side in ("away", "home"):
                rank = ((sides[side].get("curatedRank") or {}).get("current") if isinstance(sides[side].get("curatedRank"), dict) else None)
                try:
                    rank = int(rank)
                except Exception:
                    rank = 0
                if 1 <= rank <= 25:
                    ranks.append(rank)
            event["__sbbNcaafTop25"] = bool(ranks)
            event["__sbbNcaafRanks"] = ranks
        return event

    def ingest_direct_espn_range(self, day_from, day_to):
        touched = set()
        count = 0
        errors = {}
        start_token = day_from.replace("-", "")
        end_token = day_to.replace("-", "")
        dates = start_token if start_token == end_token else f"{start_token}-{end_token}"
        date_from_obj = date.fromisoformat(day_from)
        date_to_obj = date.fromisoformat(day_to)
        coverage_days = []
        cursor = date_from_obj
        while cursor <= date_to_obj:
            coverage_days.append(cursor.isoformat())
            cursor += timedelta(days=1)
        for league, (sport, competition) in ESPN_DIRECT_COMPETITIONS.items():
            params = {"dates": dates, "limit": 1000}
            if league == "NCAAF":
                params["groups"] = 80
            url = f"{ESPN_SITE_API}/{sport}/{competition}/scoreboard?{urlencode(params)}"
            try:
                payload = self._http_json(url)
                rows = payload.get("events") if isinstance(payload, dict) else []
                if not isinstance(rows, list):
                    raise RuntimeError("scoreboard response did not contain an events list")
                day_counts = defaultdict(int)
                for raw in rows:
                    if not isinstance(raw, dict):
                        continue
                    scheduled = _clean(raw.get("date") or ((raw.get("competitions") or [{}])[0] or {}).get("date"))
                    ts = _epoch(scheduled)
                    if ts is None:
                        continue
                    event_day = datetime.fromtimestamp(ts, ET).date().isoformat()
                    if event_day < day_from or event_day > day_to:
                        continue
                    event = self._espn_event(raw, league, event_day)
                    if not event:
                        continue
                    inclusion_state = None
                    inclusion_reason = None
                    if league == "NCAAF":
                        if event.get("__sbbNcaafTop25"):
                            inclusion_state, inclusion_reason = "INCLUDED", "DIRECT_ESPN_TOP25"
                        else:
                            inclusion_state, inclusion_reason = "UNKNOWN", "DIRECT_ESPN_TOP25_NOT_PROVEN"
                    event_id = self.observe_event(event, league, event_day, "ESPN_DIRECT", "DIRECT", inclusion_state, inclusion_reason)
                    if event_id:
                        count += 1
                        day_counts[event_day] += 1
                        touched.add((event_day, league))
                for coverage_day in coverage_days:
                    self.store.record_source_coverage(coverage_day, league, "ESPN_DIRECT", "DIRECT", True, day_counts.get(coverage_day, 0), "")
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                errors[league] = error
                for coverage_day in coverage_days:
                    self.store.record_source_coverage(coverage_day, league, "ESPN_DIRECT", "DIRECT", False, 0, error)
        self.last_source_errors = errors
        return count, touched, errors

    def ingest_direct_espn_day(self, day):
        return self.ingest_direct_espn_range(day, day)

    def _catalog_rows(self, day_from, day_to):
        repo = getattr(self.server, "HISTORY_REPOSITORY", None)
        if repo is None or not hasattr(repo, "catalog_events"):
            return []
        try:
            return list(repo.catalog_events(date_from=day_from, date_to=day_to, limit=100000) or [])
        except Exception:
            return []

    def _catalog_event(self, row):
        if not isinstance(row, dict):
            return {}, "", ""
        event = dict(row.get("event") or {})
        for key in ("eventId", "date", "gameDate", "scheduledAt", "status", "away", "home", "awayScore", "homeScore", "league"):
            if event.get(key) in (None, "") and row.get(key) not in (None, ""):
                event[key] = row.get(key)
        league = _league(event, row.get("league"))
        day = _day(row.get("eventDate") or row.get("event_date") or event.get("__sbbDate") or event.get("gameDate") or event.get("date"))
        if row.get("eventId") not in (None, "") and event.get("eventId") in (None, ""):
            event["eventId"] = row.get("eventId")
        return event, league, day

    def ingest_catalog_range(self, day_from, day_to):
        rows = self._catalog_rows(day_from, day_to)
        touched = set()
        for row in rows:
            event, league, day = self._catalog_event(row)
            if league not in SUPPORTED_LEAGUES or not day:
                continue
            self.observe_event(event, league, day, "HISTORY_CATALOG", "LEGACY")
            touched.add((day, league))
        return len(rows), touched

    def _day_state_snapshot(self, day):
        try:
            from . import day_state
            engine = day_state.engine()
            if engine is None:
                return None
            return engine.get(day, allow_build=False)
        except Exception:
            return None

    def ingest_day_state(self, day):
        snapshot = self._day_state_snapshot(day)
        if not snapshot:
            return 0, defaultdict(set), set(), False
        by_league = snapshot.get("scoreRowsByLeague") or {}
        legacy_ids = defaultdict(set)
        touched = set()
        count = 0
        for league, rows in by_league.items():
            league = _league({}, league)
            if league not in SUPPORTED_LEAGUES:
                continue
            for event in rows or []:
                if not isinstance(event, dict):
                    continue
                event_id = self.observe_event(event, league, day, "DAY_STATE", "LEGACY", "INCLUDED", "LEGACY_BOARD_POLICY")
                if event_id:
                    legacy_ids[league].add(event_id)
                    count += 1
                    touched.add((day, league))
        for league in SUPPORTED_LEAGUES:
            self.store.record_source_coverage(day, league, "DAY_STATE", "LEGACY", True, len(legacy_ids.get(league, set())), "")
        return count, legacy_ids, touched, True

    def _baseline_kind(self, slate_date, league):
        now_et = datetime.now(ET)
        key = (slate_date, league)
        if slate_date != now_et.date().isoformat() or now_et.hour < 2:
            return "RECONCILIATION"
        if key in self.baseline_dates:
            return "RECONCILIATION"
        # Persisted lookup prevents a service restart after 02:00 ET from creating
        # a second forced daily baseline for the same date/competition.
        if self.store.has_daily_baseline(slate_date, league):
            self.baseline_dates.add(key)
            return "RECONCILIATION"
        self.baseline_dates.add(key)
        return "DAILY_BASELINE_0200_ET"

    def _daily_baseline_due(self):
        now_et = datetime.now(ET)
        if now_et.hour < 2:
            return False
        today = now_et.date().isoformat()
        return any(not self.store.has_daily_baseline(today, league) for league in SUPPORTED_LEAGUES)

    def reconcile_day(self, day, include_catalog=True, include_direct=True):
        touched = set()
        catalog_rows = 0
        direct_rows = 0
        direct_errors = {}
        if include_direct:
            direct_rows, direct_touched, direct_errors = self.ingest_direct_espn_day(day)
            touched.update(direct_touched)
        if include_catalog:
            catalog_rows, catalog_touched = self.ingest_catalog_range(day, day)
            touched.update(catalog_touched)
        day_state_rows, legacy_ids, state_touched, snapshot_present = self.ingest_day_state(day)
        touched.update(state_touched)
        # A canonical date/league manifest must exist even when the answer is zero.
        for league in SUPPORTED_LEAGUES:
            touched.add((day, league))
        slates = 0
        comparisons = 0
        for slate_date, league in sorted(touched):
            baseline_kind = self._baseline_kind(slate_date, league)
            _slate, changed = self.store.compile_slate(
                slate_date, league, baseline_kind, force_version=baseline_kind.startswith("DAILY_BASELINE")
            )
            slates += int(bool(changed))
            if snapshot_present:
                self.store.record_comparison(slate_date, league, legacy_ids.get(league, set()))
                comparisons += 1
        self.comparisons_touched += comparisons
        return {"direct_rows": direct_rows, "direct_errors": direct_errors, "catalog_rows": catalog_rows, "day_state_rows": day_state_rows, "slates": slates, "comparisons": comparisons}

    def reconcile_horizon(self):
        today = datetime.now(ET).date()
        day_from = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
        day_to = (today + timedelta(days=LOOKAHEAD_DAYS)).isoformat()
        run_id = self.store.begin_run("FULL_HORIZON", day_from, day_to)
        before = self.events_touched
        stats = {"direct_rows": 0, "direct_errors": 0, "catalog_rows": 0, "day_state_rows": 0, "events_touched": 0, "slates_touched": 0, "comparisons_touched": 0, "error": ""}
        try:
            touched = set()
            direct_rows, direct_touched, direct_errors = self.ingest_direct_espn_range(day_from, day_to)
            stats["direct_rows"] = direct_rows
            stats["direct_errors"] = len(direct_errors)
            touched.update(direct_touched)
            catalog_rows, catalog_touched = self.ingest_catalog_range(day_from, day_to)
            touched.update(catalog_touched)
            stats["catalog_rows"] = catalog_rows
            legacy_by_key = {}
            for offset in range(-LOOKBACK_DAYS, LOOKAHEAD_DAYS + 1):
                day = (today + timedelta(days=offset)).isoformat()
                count, legacy_ids, state_touched, snapshot_present = self.ingest_day_state(day)
                stats["day_state_rows"] += count
                touched.update(state_touched)
                if snapshot_present:
                    for league in SUPPORTED_LEAGUES:
                        legacy_by_key[(day, league)] = legacy_ids.get(league, set())
            # Every supported competition gets an explicit date manifest, including
            # zero-event dates, so "no games" is distinguishable from "not checked."
            for offset in range(-LOOKBACK_DAYS, LOOKAHEAD_DAYS + 1):
                day = (today + timedelta(days=offset)).isoformat()
                for league in SUPPORTED_LEAGUES:
                    touched.add((day, league))
            for day, league in sorted(touched):
                baseline_kind = self._baseline_kind(day, league)
                _slate, changed = self.store.compile_slate(
                    day, league, baseline_kind, force_version=baseline_kind.startswith("DAILY_BASELINE")
                )
                stats["slates_touched"] += int(bool(changed))
                if (day, league) in legacy_by_key:
                    self.store.record_comparison(day, league, legacy_by_key[(day, league)])
                    stats["comparisons_touched"] += 1
            self.last_error = ""
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            stats["error"] = self.last_error
        finally:
            stats["events_touched"] = self.events_touched - before
            self.store.finish_run(run_id, **stats)
        return stats

    def hot_reconcile(self):
        day = self.today_et()
        run_id = self.store.begin_run("HOT_TODAY", day, day)
        before = self.events_touched
        stats = {"direct_rows": 0, "direct_errors": 0, "catalog_rows": 0, "day_state_rows": 0, "events_touched": 0, "slates_touched": 0, "comparisons_touched": 0, "error": ""}
        try:
            result = self.reconcile_day(day, include_catalog=True, include_direct=True)
            stats.update({
                "direct_rows": result["direct_rows"], "direct_errors": len(result["direct_errors"]),
                "catalog_rows": result["catalog_rows"], "day_state_rows": result["day_state_rows"],
                "slates_touched": result["slates"], "comparisons_touched": result["comparisons"],
            })
            self.last_error = ""
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            stats["error"] = self.last_error
        finally:
            stats["events_touched"] = self.events_touched - before
            self.store.finish_run(run_id, **stats)
        return stats

    def worker(self):
        # Let the existing production services finish startup first.
        time.sleep(4)
        while self.running:
            now = _now()
            try:
                # The 02:00 ET baseline is a semantic boundary, not merely another
                # 15-minute refresh.  If it is due, run the full horizon immediately.
                if self._daily_baseline_due() or not self.last_full_at or now - self.last_full_at >= FULL_SECONDS:
                    self.reconcile_horizon()
                    self.last_full_at = _now()
                    self.last_hot_at = self.last_full_at
                elif not self.last_hot_at or now - self.last_hot_at >= HOT_SECONDS:
                    self.hot_reconcile()
                    self.last_hot_at = _now()
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(1)

    def health(self):
        return {
            "ok": True, "version": VERSION, "enabled": ENABLED, "mode": MODE,
            "productionAuthority": False,
            "supportedLeagues": list(SUPPORTED_LEAGUES),
            "horizon": {"lookbackDays": LOOKBACK_DAYS, "lookaheadDays": LOOKAHEAD_DAYS},
            "cadence": {"hotSeconds": HOT_SECONDS, "fullSeconds": FULL_SECONDS, "dailyBaselineTimezone": "America/New_York", "dailyBaselineHour": 2},
            "lastError": self.last_error, "lastSourceErrors": self.last_source_errors, "lastHotAt": self.last_hot_at, "lastFullAt": self.last_full_at,
            "directDiscovery": {"provider": "ESPN_DIRECT", "sourceClass": "DIRECT", "certificationEligibleAlone": False},
            "safety": {
                "mutatesDayState": False, "mutatesHistoryRepository": False,
                "absenceDeletesEvents": False, "legacyEvidenceCanCertify": False,
            },
            "store": self.store.health(),
        }

    def api_slate(self, day, league=""):
        return {"ok": True, "version": VERSION, "mode": MODE, "date": day,
                "slates": self.store.latest_slates(day, league)}

    def api_compare(self, day, league=""):
        return {"ok": True, "version": VERSION, "mode": MODE, "date": day,
                "comparisons": self.store.latest_comparisons(day, league)}


def engine():
    return _ENGINE


def _install_into_server():
    global _ENGINE
    deadline = _now() + 120
    server = None
    while _now() < deadline:
        server = sys.modules.get("__main__")
        if server and all(hasattr(server, name) for name in ("Handler", "send_json", "HISTORY_REPOSITORY")):
            try:
                from . import day_state
                if day_state.engine() is not None:
                    break
            except Exception:
                pass
        time.sleep(0.2)
    if not server:
        return

    _ENGINE = CanonicalShadowEngine(server)
    server.CANONICAL_SHADOW_ENGINE = _ENGINE
    server.CANONICAL_SHADOW_STORE = _ENGINE.store
    try:
        server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update({
            "version": VERSION, "mode": MODE, "productionAuthority": False,
            "database": str(DB_PATH), "leagues": list(SUPPORTED_LEAGUES),
        })
    except Exception:
        pass

    Handler = server.Handler
    if not getattr(Handler, "__sbbCanonicalShadowV600", False):
        old_get = Handler.do_GET

        def do_GET(self):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            if parsed.path in {"/api/canonical/health", "/api/canonical/status"}:
                return server.send_json(self, _ENGINE.health(), 200, {"X-SBB-Canonical":"SHADOW"})
            if parsed.path == "/api/canonical/slate":
                day = _day((qs.get("date") or [""])[-1])
                league = _clean((qs.get("league") or [""])[-1]).upper()
                if not day:
                    return server.send_json(self, {"ok":False,"error":"DATE_REQUIRED"}, 400)
                if league and league not in SUPPORTED_LEAGUES:
                    return server.send_json(self, {"ok":False,"error":"UNSUPPORTED_LEAGUE"}, 400)
                return server.send_json(self, _ENGINE.api_slate(day, league), 200, {"X-SBB-Canonical":"SHADOW"})
            if parsed.path == "/api/canonical/compare":
                day = _day((qs.get("date") or [""])[-1])
                league = _clean((qs.get("league") or [""])[-1]).upper()
                if not day:
                    return server.send_json(self, {"ok":False,"error":"DATE_REQUIRED"}, 400)
                return server.send_json(self, _ENGINE.api_compare(day, league), 200, {"X-SBB-Canonical":"SHADOW"})
            if parsed.path == "/api/canonical/event":
                event_id = _clean((qs.get("id") or [""])[-1])
                if not event_id:
                    return server.send_json(self, {"ok":False,"error":"ID_REQUIRED"}, 400)
                payload = _ENGINE.store.event_detail(event_id)
                return server.send_json(self, {"ok": bool(payload), "event": payload}, 200 if payload else 404,
                                        {"X-SBB-Canonical":"SHADOW"})
            return old_get(self)

        Handler.do_GET = do_GET
        Handler.__sbbCanonicalShadowV600 = True

    threading.Thread(target=_ENGINE.worker, daemon=True, name="sbb-canonical-shadow-v600").start()


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED or not ENABLED:
            return
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-canonical-shadow-install-v600").start()

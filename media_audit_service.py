#!/usr/bin/env python3
"""Sports Big Board v5.5.0 R9 canonical media-health audit service.

The operator page is a control/status console only. Audit queue, browser playback
certification, canonical package selection, and remediation state live on the
Sports Big Board backend VM and persistent SQLite catalog.
"""
from __future__ import annotations

import csv
import io
import json
import os
import queue
import random
import re
import signal
import sqlite3
import threading
import time
import traceback
from contextlib import closing
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sbb.history_repository import HistoryRepository
from sbb.catalog_contract import VERIFICATION_VERSION
from sbb.event_matcher import team_name as catalog_team_name

APP_ROOT = Path(__file__).resolve().parent
APP_VERSION = (APP_ROOT / "VERSION").read_text(encoding="utf-8").strip()
AUDIT_GENERATION = "R12-FAILURE-HARDENING"
STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
DB_PATH = STATE_DIR / "cache" / "history.sqlite3"
HOST = os.environ.get("SBB_MEDIA_AUDIT_HOST", "127.0.0.1")
PORT = int(os.environ.get("SBB_MEDIA_AUDIT_PORT", "8091"))
MAIN_API = os.environ.get("SBB_MEDIA_AUDIT_MAIN_API", "http://127.0.0.1:8080").rstrip("/")
PROBE_URL = os.environ.get(
    "SBB_MEDIA_AUDIT_PROBE_URL",
    "https://jonathanjoelneptune.github.io/sports-big-board/media-audit-probe.html",
).strip()
FRESH_SECONDS = int(os.environ.get("SBB_MEDIA_AUDIT_FRESH_SECONDS", str(30 * 86400)))
SOFT_RETRIES = max(1, int(os.environ.get("SBB_MEDIA_AUDIT_SOFT_RETRIES", "2")))
BLUE_FALLBACK_TARGET = max(1, min(5, int(os.environ.get("SBB_MEDIA_AUDIT_BLUE_FALLBACK", "3"))))
DISCOVERY_RETRY_SECONDS = max(5, int(os.environ.get("SBB_MEDIA_AUDIT_DISCOVERY_RETRY_SECONDS", "20")))
DISCOVERY_PASSES = max(1, min(5, int(os.environ.get("SBB_MEDIA_AUDIT_DISCOVERY_PASSES", "3"))))
DISCOVERY_SETTLE_SECONDS = max(0.5, float(os.environ.get("SBB_MEDIA_AUDIT_DISCOVERY_SETTLE_SECONDS", "3")))
DB_BUSY_TIMEOUT_MS = max(1000, min(60000, int(os.environ.get("SBB_MEDIA_AUDIT_DB_BUSY_TIMEOUT_MS", "10000"))))
DB_LOCK_RETRY_SECONDS = max(1.0, float(os.environ.get("SBB_MEDIA_AUDIT_DB_LOCK_RETRY_SECONDS", "3")))
WORKER_EXCEPTION_RETRIES = max(1, min(10, int(os.environ.get("SBB_MEDIA_AUDIT_EXCEPTION_RETRIES", "3"))))
CONTROL_WORKER_JOIN_SECONDS = max(0.5, min(10.0, float(os.environ.get("SBB_MEDIA_AUDIT_CONTROL_JOIN_SECONDS", "2"))))
DISCOVERY_HTTP_TIMEOUT_SECONDS = max(5, min(60, int(os.environ.get("SBB_MEDIA_AUDIT_DISCOVERY_HTTP_TIMEOUT_SECONDS", "20"))))
AUDIT_WORKER_COUNT = max(1, min(4, int(os.environ.get("SBB_MEDIA_AUDIT_WORKERS", "3"))))
DISCOVERY_CONCURRENCY = max(1, min(2, int(os.environ.get("SBB_MEDIA_AUDIT_DISCOVERY_CONCURRENCY", "1"))))
DISCOVERY_SEMAPHORE = threading.Semaphore(DISCOVERY_CONCURRENCY)
DB_WRITE_QUEUE_MAX = max(32, min(4096, int(os.environ.get("SBB_MEDIA_AUDIT_DB_WRITE_QUEUE_MAX", "512"))))
INFRA_RETRIES = max(1, min(4, int(os.environ.get("SBB_MEDIA_AUDIT_INFRA_RETRIES", "2"))))
STATUS_CACHE_REFRESH_SECONDS = max(2.0, min(30.0, float(os.environ.get("SBB_MEDIA_AUDIT_STATUS_CACHE_SECONDS", "5"))))
PRODUCTION_ENDPOINT_CORE_LEAGUES = {"MLB", "NFL", "NBA", "NHL", "EPL", "MLS", "NCAAF"}
# Recent successful playback is durable evidence. Transient headless/browser
# failures remain audit evidence but cannot revoke/quarantine a recently PLAYED
# asset. Hard failures still revoke immediately.
PLAYABLE_EVIDENCE_FRESH_SECONDS = max(
    3600,
    int(os.environ.get("SBB_MEDIA_AUDIT_PLAYABLE_EVIDENCE_FRESH_SECONDS", str(FRESH_SECONDS)))
)
TRANSIENT_MEDIA_FAILURE_REASONS = {
    "YOUTUBE_START_TIMEOUT", "YOUTUBE_TIME_NOT_ADVANCING", "YOUTUBE_PLAY_CALL_FAILED",
    "YOUTUBE_PLAYER_CREATE_ERROR", "DIRECT_START_TIMEOUT", "DIRECT_TIME_NOT_ADVANCING",
    "DIRECT_PLAY_CALL_FAILED", "YOUTUBE_HTML5_ERROR",
}
HARD_MEDIA_FAILURE_REASONS = {
    "NON_VIDEO_MEDIA_URL", "MEDIA_URL_MISSING", "YOUTUBE_UNAVAILABLE",
    "YOUTUBE_EMBED_DISABLED", "YOUTUBE_INVALID_PARAMETER", "UNKNOWN_MEDIA_KIND",
    "DIRECT_MEDIA_ERROR_4",
}
AUDIT_TIMEZONE = os.environ.get("SBB_MEDIA_AUDIT_TIMEZONE", "America/Los_Angeles").strip() or "America/Los_Angeles"
try:
    AUDIT_TZ = ZoneInfo(AUDIT_TIMEZONE)
except Exception:
    AUDIT_TIMEZONE = "UTC"; AUDIT_TZ = timezone.utc

ASSIGNED = "ASSIGNED"
QUARANTINED = "QUARANTINED"
TERMINAL_QUEUE = {"DONE", "FAILED", "SKIPPED", "DEFERRED"}
INFRA_FAILURES = {
    "BROWSER_WORKER_ERROR", "CHROMEDRIVER_READ_TIMEOUT", "CHROMEDRIVER_CONNECTION_ERROR",
    "SELENIUM_TIMEOUT", "SELENIUM_SESSION_ERROR", "SELENIUM_WEBDRIVER_ERROR",
    "PROBE_PAGE_NOT_READY", "PROBE_EXCEPTION", "YOUTUBE_API_LOAD_ERROR",
    "YOUTUBE_API_LOAD_TIMEOUT", "INVALID_PROBE_RESULT", "EMPTY_PROBE_RESULT",
}
MANAGED_METHODS = {
    "CANONICAL_MEDIA_AUDIT",
    "MEDIA_AUDIT_FAILED",
    "MEDIA_AUDIT_SUPERSEDED",
    "MEDIA_AUDIT_BLUE_SUPPRESSED",
    "MEDIA_AUDIT_NON_CANONICAL",
    "MEDIA_AUDIT_RETAINED_PLAYABLE",
    "MEDIA_AUDIT_FALLBACK_AVAILABLE",
    "MEDIA_AUDIT_ALTERNATE_AVAILABLE",
}
IMAGE_RE = re.compile(r"\.(?:jpe?g|png|webp|gif|svg)(?:$|[?#])", re.I)
YOUTUBE_RE = re.compile(r"(?:youtu\.be/|youtube(?:-nocookie)?\.com/(?:watch\?v=|embed/|shorts/))([A-Za-z0-9_-]{6,20})", re.I)


def _now() -> float:
    return time.time()


def _today() -> str:
    return datetime.now(AUDIT_TZ).date().isoformat()


def _jloads(value, default=None):
    try:
        return json.loads(value or "")
    except Exception:
        return {} if default is None else default


def _jdumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _is_db_locked(exc) -> bool:
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    msg = str(exc or "").lower()
    return "database is locked" in msg or "database table is locked" in msg or "database is busy" in msg or "sqlite_busy" in msg


def _transient_media_failure_reason(reason: str) -> bool:
    reason = str(reason or "")
    if reason in TRANSIENT_MEDIA_FAILURE_REASONS:
        return True
    return reason.startswith(("REMOTE_", "NETWORK_", "HTTP_5"))


def _hard_media_failure_reason(reason: str) -> bool:
    reason = str(reason or "").upper()
    return reason in HARD_MEDIA_FAILURE_REASONS or reason.startswith("YOUTUBE_ERROR_100")


def _infra_failure_reason(reason: str) -> bool:
    reason = str(reason or "")
    return (
        reason in INFRA_FAILURES
        or reason.startswith("CHROMEDRIVER_")
        or reason.startswith("SELENIUM_")
        or reason.startswith("PROBE_INFRA_")
    )


def _infra_result_from_exception(exc) -> dict:
    name = type(exc).__name__
    message = f"{name}: {exc}"
    lower = message.lower()
    if name == "ReadTimeoutError" or ("localhost" in lower and "read timed out" in lower):
        reason = "CHROMEDRIVER_READ_TIMEOUT"
    elif "sessionnotcreated" in lower or name == "SessionNotCreatedException":
        reason = "SELENIUM_SESSION_ERROR"
    elif "timed out" in lower or name in {"TimeoutException", "TimeoutError"}:
        reason = "SELENIUM_TIMEOUT"
    elif "connection" in lower and ("chromedriver" in lower or "localhost" in lower):
        reason = "CHROMEDRIVER_CONNECTION_ERROR"
    elif "webdriver" in lower or name.endswith("WebDriverException"):
        reason = "SELENIUM_WEBDRIVER_ERROR"
    else:
        reason = "BROWSER_WORKER_ERROR"
    return {"ok": False, "hard": False, "infra": True, "reason": reason, "message": message, "startupMs": 0, "currentTimeDelta": 0}


def _special_event_league(league: str) -> bool:
    return str(league or "").upper() not in PRODUCTION_ENDPOINT_CORE_LEAGUES


def _recent_playable(asset: dict, now=None) -> bool:
    now = _now() if now is None else float(now)
    state = str((asset or {}).get("runtimeState") or "").upper()
    success_at = float((asset or {}).get("runtimeSuccessAt") or 0)
    return bool(
        state == "PLAYED"
        and success_at > 0
        and success_at >= now - PLAYABLE_EVIDENCE_FRESH_SECONDS
    )


def _event_final(event_date: str, final_at: float, event: dict) -> bool:
    if float(final_at or 0) > 0:
        return True
    status = event.get("status")
    status_obj = status if isinstance(status, dict) else {}
    tokens = [
        status if isinstance(status, str) else "",
        status_obj.get("type"), status_obj.get("name"), status_obj.get("state"),
        status_obj.get("description"), status_obj.get("detail"),
        event.get("state"), event.get("gameStatus"), event.get("statusText"),
    ]
    blob = " ".join(str(x or "") for x in tokens).upper()
    if any(x in blob for x in ("CANCEL", "POSTPON", "SUSPEND", "TBD")):
        return False
    if any(x in blob for x in ("FINAL", "COMPLETED", "COMPLETE", "ENDED", "FINISHED", "FT", "AET")):
        return True
    return str(event_date or "") < _today()


def _scheduled_key(event_date: str, event: dict) -> str:
    value=None
    for key in ("scheduledAt", "startTime", "startDate", "dateTime", "datetime", "timestamp", "gameDate"):
        if event.get(key) not in (None, ""):
            value=event.get(key); break
    if value in (None, ""):
        status = event.get("status") if isinstance(event.get("status"), dict) else {}
        for key in ("scheduledAt", "startTime"):
            if status.get(key) not in (None, ""):
                value=status.get(key); break
    try:
        if isinstance(value,(int,float)) or (isinstance(value,str) and re.fullmatch(r"\d+(?:\.\d+)?",value.strip())):
            epoch=float(value)
            if epoch>1e12: epoch/=1000.0
            return f"{epoch:020.3f}"
        raw=str(value or f"{event_date}T23:59:59").strip().replace('Z','+00:00')
        dt=datetime.fromisoformat(raw)
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return f"{dt.timestamp():020.3f}"
    except Exception:
        return f"{event_date.replace('-','')}999999999999"


def _team_name(event: dict, side: str) -> str:
    try:
        name=str(catalog_team_name(event,side) or '')
        if name: return name
    except Exception:
        pass
    raw = event.get(side)
    if isinstance(raw, dict):
        return str(raw.get("displayName") or raw.get("name") or raw.get("shortName") or raw.get("abbreviation") or "")
    competitors = event.get("competitors") or []
    if isinstance(competitors, list):
        for comp in competitors:
            if not isinstance(comp, dict):
                continue
            home_away = str(comp.get("homeAway") or comp.get("side") or "").lower()
            if home_away == side.lower():
                team = comp.get("team") if isinstance(comp.get("team"), dict) else comp
                return str(team.get("displayName") or team.get("name") or team.get("shortDisplayName") or team.get("abbreviation") or "")
    return ""


def _asset_url(item: dict, canonical_url: str = "") -> str:
    for key in ("mediaUrl", "externalUrl", "url", "videoUrl", "href"):
        value = item.get(key)
        if value:
            return str(value)
    return str(canonical_url or "")


def _youtube_id(item: dict, url: str) -> str:
    for key in ("youtubeId", "youtubeID", "videoId", "videoID"):
        value = item.get(key)
        if value:
            return str(value)
    match = YOUTUBE_RE.search(str(url or ""))
    return match.group(1) if match else ""


def _tier(item: dict) -> str:
    value = str(item.get("recapTier") or item.get("tier") or "blue").lower()
    if value == "purple":
        value = "extended"
    return value if value in {"gold", "green", "extended", "blue"} else "blue"


class AuditStore:
    AUDIT_SCHEMA_TABLES = {
        "history_media_audit_run",
        "history_media_audit_queue",
        "history_media_audit_asset_result",
        "history_media_canonical_package",
    }

    def __init__(self, db_path: Path):
        self.db_path = str(db_path)
        self.lock = threading.RLock()
        # Do not instantiate HistoryRepository here. Its constructor performs
        # catalog schema/meta writes, which are owned by the main Big Board
        # backend and can collide with that process during audit-service restart.
        # The audit service only needs HistoryRepository.asset_key_for(), which
        # is a static helper and does not require a repository instance.
        self._ensure_schema()

    def connect(self, timeout=None):
        wait_ms = DB_BUSY_TIMEOUT_MS if timeout is None else max(1000, int(float(timeout) * 1000))
        conn = sqlite3.connect(self.db_path, timeout=wait_ms / 1000.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={wait_ms}")
        return conn

    def _schema_ready(self):
        # Read-first startup: an established R9+ catalog already has these tables,
        # so a normal deploy/restart performs no SQLite write at service startup.
        with closing(self.connect(timeout=5)) as conn:
            placeholders=",".join("?" for _ in self.AUDIT_SCHEMA_TABLES)
            rows=conn.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({placeholders})",
                tuple(sorted(self.AUDIT_SCHEMA_TABLES)),
            ).fetchall()
        return {str(r[0]) for r in rows} == self.AUDIT_SCHEMA_TABLES

    def _ensure_schema(self):
        # Fresh installs still need the audit tables. Retry only that audit-owned
        # schema creation when the main backend temporarily owns SQLite's writer.
        deadline=time.time()+120.0
        while True:
            try:
                if self._schema_ready():
                    return
                self._init_schema()
                return
            except sqlite3.OperationalError as exc:
                if not _is_db_locked(exc) or time.time() >= deadline:
                    raise
                print(
                    f"[media-audit] SQLite busy during audit schema startup; retrying in {DB_LOCK_RETRY_SECONDS:g}s: {exc}",
                    flush=True,
                )
                time.sleep(DB_LOCK_RETRY_SECONDS)

    def _init_schema(self):
        with self.lock, closing(self.connect()) as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS history_media_audit_run (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              mode TEXT NOT NULL DEFAULT 'ALL', state TEXT NOT NULL DEFAULT 'IDLE',
              start_date TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL DEFAULT 0,
              updated_at REAL NOT NULL DEFAULT 0, completed_at REAL NOT NULL DEFAULT 0,
              total_games INTEGER NOT NULL DEFAULT 0, processed_games INTEGER NOT NULL DEFAULT 0,
              current_ordinal INTEGER NOT NULL DEFAULT 0, current_event_key TEXT NOT NULL DEFAULT '',
              current_phase TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '',
              worker_id TEXT NOT NULL DEFAULT '', generation TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS history_media_audit_queue (
              run_id INTEGER NOT NULL, ordinal INTEGER NOT NULL, canonical_event_key TEXT NOT NULL,
              event_date TEXT NOT NULL, scheduled_key TEXT NOT NULL DEFAULT '', league TEXT NOT NULL,
              event_id TEXT NOT NULL, game TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'PENDING',
              phase TEXT NOT NULL DEFAULT '', health TEXT NOT NULL DEFAULT 'UNTESTED',
              note TEXT NOT NULL DEFAULT '', started_at REAL NOT NULL DEFAULT 0, completed_at REAL NOT NULL DEFAULT 0,
              PRIMARY KEY(run_id, ordinal), UNIQUE(run_id, canonical_event_key),
              FOREIGN KEY(run_id) REFERENCES history_media_audit_run(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_media_audit_queue_state ON history_media_audit_queue(run_id,state,ordinal);
            CREATE TABLE IF NOT EXISTS history_media_audit_asset_result (
              id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, canonical_event_key TEXT NOT NULL,
              asset_key TEXT NOT NULL, tier TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 1,
              state TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', startup_ms REAL NOT NULL DEFAULT 0,
              current_time_delta REAL NOT NULL DEFAULT 0, browser TEXT NOT NULL DEFAULT '',
              probe_origin TEXT NOT NULL DEFAULT '', tested_at REAL NOT NULL DEFAULT 0,
              details_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_media_audit_asset_event ON history_media_audit_asset_result(canonical_event_key,tested_at);
            CREATE INDEX IF NOT EXISTS idx_media_audit_asset_asset ON history_media_audit_asset_result(asset_key,tested_at);
            CREATE TABLE IF NOT EXISTS history_media_canonical_package (
              canonical_event_key TEXT PRIMARY KEY, audit_run_id INTEGER NOT NULL DEFAULT 0,
              health TEXT NOT NULL DEFAULT 'UNTESTED', gold_asset_key TEXT NOT NULL DEFAULT '',
              green_asset_key TEXT NOT NULL DEFAULT '', purple_asset_key TEXT NOT NULL DEFAULT '',
              blue_asset_keys_json TEXT NOT NULL DEFAULT '[]', preferred_complete INTEGER NOT NULL DEFAULT 0,
              preferred_playable INTEGER NOT NULL DEFAULT 0, rehydration_state TEXT NOT NULL DEFAULT '',
              rehydration_reason TEXT NOT NULL DEFAULT '', certified_at REAL NOT NULL DEFAULT 0,
              worker_generation TEXT NOT NULL DEFAULT '', details_json TEXT NOT NULL DEFAULT '{}'
            );
            """)
            conn.commit()

    def _eligible_events(self, start_date: str):
        start_date = str(start_date or _today())[:10]
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT canonical_event_key,league,event_id,event_date,event_json,final_at FROM history_catalog_event WHERE event_date<=? ORDER BY event_date DESC,canonical_event_key",
                (start_date,),
            ).fetchall()
        events = []
        for row in rows:
            event = _jloads(row["event_json"], {})
            if not _event_final(row["event_date"], row["final_at"], event):
                continue
            away, home = _team_name(event, "away"), _team_name(event, "home")
            game = f"{away} @ {home}".strip(" @") or str(row["event_id"])
            events.append({
                "canonicalEventKey": row["canonical_event_key"], "league": row["league"],
                "eventId": row["event_id"], "date": row["event_date"], "event": event,
                "scheduledKey": _scheduled_key(row["event_date"], event), "game": game,
            })
        # Frozen deterministic order: newest date first; within each date actual scheduled time.
        events.sort(key=lambda x: (x["date"],), reverse=True)
        ordered = []
        by_date = {}
        for item in events:
            by_date.setdefault(item["date"], []).append(item)
        for date in sorted(by_date.keys(), reverse=True):
            ordered.extend(sorted(by_date[date], key=lambda x: (x["scheduledKey"], x["league"], x["eventId"], x["canonicalEventKey"])))
        return ordered

    def newest_eligible_date(self):
        today=_today()
        with closing(self.connect()) as conn:
            row=conn.execute("SELECT MAX(event_date) d FROM history_catalog_event WHERE event_date<=? AND (final_at>0 OR event_date<?)",(today,today)).fetchone()
        return str((row["d"] if row else "") or "")

    def active_run(self):
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM history_media_audit_run ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def exact_run_state(self, run_id: int):
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT state FROM history_media_audit_run WHERE id=?", (int(run_id),)).fetchone()
        return str(row["state"] or "") if row else ""

    def start_run(self, mode="ALL", start_date=""):
        mode = str(mode or "ALL").upper()
        if mode not in {"ALL", "FAILED", "STALE"}:
            mode = "ALL"
        start_date = str(start_date or self.newest_eligible_date() or _today())[:10]
        events = self._eligible_events(start_date)
        now = _now()
        with self.lock, closing(self.connect()) as conn:
            conn.execute("UPDATE history_media_audit_run SET state='STOPPED',updated_at=? WHERE state IN ('RUNNING','PAUSED')", (now,))
            cur = conn.execute(
                "INSERT INTO history_media_audit_run(mode,state,start_date,created_at,updated_at,total_games,worker_id,generation) VALUES(?,?,?,?,?,?,?,?)",
                (mode, "RUNNING", start_date, now, now, 0, f"canonical-audit-{os.getpid()}", AUDIT_GENERATION),
            )
            run_id = int(cur.lastrowid)
            ordinal = 0
            for event in events:
                if mode != "ALL":
                    pkg = conn.execute("SELECT health,certified_at FROM history_media_canonical_package WHERE canonical_event_key=?", (event["canonicalEventKey"],)).fetchone()
                    prior_q = conn.execute(
                        "SELECT health,state FROM history_media_audit_queue WHERE canonical_event_key=? ORDER BY run_id DESC LIMIT 1",
                        (event["canonicalEventKey"],),
                    ).fetchone()
                    prior_health = str(prior_q["health"] or "") if prior_q else ""
                    if mode == "FAILED" and (
                        (not pkg or str(pkg["health"]) not in {"DEGRADED", "UNPLAYABLE", "NO_MEDIA", "FAILED", "INCONCLUSIVE"})
                        and prior_health != "INCONCLUSIVE"
                    ):
                        continue
                    if mode == "STALE" and pkg and float(pkg["certified_at"] or 0) >= now - FRESH_SECONDS:
                        continue
                ordinal += 1
                conn.execute(
                    "INSERT INTO history_media_audit_queue(run_id,ordinal,canonical_event_key,event_date,scheduled_key,league,event_id,game,state) VALUES(?,?,?,?,?,?,?,?,?)",
                    (run_id, ordinal, event["canonicalEventKey"], event["date"], event["scheduledKey"], event["league"], event["eventId"], event["game"], "PENDING"),
                )
            conn.execute("UPDATE history_media_audit_run SET total_games=? WHERE id=?", (ordinal, run_id))
            conn.commit()
        return self.run_snapshot(run_id)

    def set_run_state(self, state: str):
        state = str(state or "").upper()
        if state not in {"RUNNING", "PAUSED", "STOPPED"}:
            raise ValueError("invalid run state")
        now = _now()
        with self.lock, closing(self.connect()) as conn:
            row = conn.execute("SELECT id FROM history_media_audit_run ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return None
            conn.execute("UPDATE history_media_audit_run SET state=?,updated_at=? WHERE id=?", (state, now, row["id"]))
            conn.commit()
            run_id = int(row["id"])
        return self.run_snapshot(run_id)

    def reset_run(self, recertify=False):
        with self.lock, closing(self.connect()) as conn:
            conn.execute("DELETE FROM history_media_audit_asset_result")
            conn.execute("DELETE FROM history_media_audit_queue")
            conn.execute("DELETE FROM history_media_audit_run")
            if recertify:
                # Keep source/history rows, but clear canonical package decisions and restore audit-managed links.
                conn.execute("DELETE FROM history_media_canonical_package")
                conn.execute(
                    "UPDATE history_event_media SET association_state='ASSIGNED',association_method='MEDIA_AUDIT_RESET',association_evidence='canonical audit reset' WHERE association_method IN (%s)" % ",".join("?" * len(MANAGED_METHODS)),
                    tuple(MANAGED_METHODS),
                )
            conn.commit()
        return {"ok": True, "recertify": bool(recertify)}

    def recover_transient_playable_quarantines(self):
        """Restore recent PLAYED assets falsely quarantined by transient audit failures."""
        now=_now()
        cutoff=now-PLAYABLE_EVIDENCE_FRESH_SECONDS
        restored=[]
        requeued=[]
        with self.lock, closing(self.connect(timeout=2)) as conn:
            rows=conn.execute(
                """SELECT s.asset_key,s.asset_json,s.runtime_success_at,s.runtime_failure_at,
                          s.runtime_failure_reason,em.canonical_event_key
                   FROM history_source_media s
                   JOIN history_event_media em ON em.asset_key=s.asset_key
                   WHERE s.runtime_state='FAILED'
                     AND s.runtime_success_at>=?
                     AND s.runtime_success_at>0
                     AND em.association_method='MEDIA_AUDIT_FAILED'""",
                (cutoff,),
            ).fetchall()
            affected=set()
            for row in rows:
                reason=str(row["runtime_failure_reason"] or "")
                if not _transient_media_failure_reason(reason):
                    continue
                item=_jloads(row["asset_json"],{})
                item["runtimeState"]="playing-confirmed"
                item["verifiedPlayable"]=True
                item["runtimeFailureReason"]=reason
                item["lastAuditTransientFailureReason"]=reason
                item["lastAuditTransientFailureAt"]=float(row["runtime_failure_at"] or now)
                conn.execute(
                    "UPDATE history_source_media SET asset_json=?,runtime_state='PLAYED',updated_at=? WHERE asset_key=?",
                    (_jdumps(item),now,row["asset_key"]),
                )
                conn.execute(
                    """UPDATE history_event_media
                       SET association_state='ASSIGNED',
                           association_method='MEDIA_AUDIT_RETAINED_PLAYABLE',
                           association_evidence=?,
                           updated_at=?
                       WHERE canonical_event_key=? AND asset_key=?""",
                    (
                        f"Recent PLAYED evidence retained after transient audit failure: {reason}",
                        now,row["canonical_event_key"],row["asset_key"],
                    ),
                )
                restored.append(str(row["asset_key"]))
                affected.add(str(row["canonical_event_key"]))

            run=conn.execute("SELECT id,state FROM history_media_audit_run ORDER BY id DESC LIMIT 1").fetchone()
            if run and str(run["state"] or "") in {"RUNNING","PAUSED"} and affected:
                run_id=int(run["id"])
                for event_key in sorted(affected):
                    q=conn.execute(
                        "SELECT ordinal,state,health FROM history_media_audit_queue WHERE run_id=? AND canonical_event_key=?",
                        (run_id,event_key),
                    ).fetchone()
                    if not q or str(q["state"] or "") not in {"DONE","FAILED","SKIPPED","DEFERRED"}:
                        continue
                    conn.execute(
                        """UPDATE history_media_audit_queue
                           SET state='PENDING',phase='RECOVERED_PLAYABLE_EVIDENCE',
                               health='UNTESTED',
                               note='Recent PLAYED evidence restored after transient audit failure',
                               started_at=0,completed_at=0
                           WHERE run_id=? AND ordinal=?""",
                        (run_id,q["ordinal"]),
                    )
                    conn.execute(
                        "DELETE FROM history_media_canonical_package WHERE canonical_event_key=? AND health IN ('UNPLAYABLE','NO_MEDIA','DEGRADED')",
                        (event_key,),
                    )
                    requeued.append(int(q["ordinal"]))
                processed=int(conn.execute(
                    "SELECT COUNT(*) FROM history_media_audit_queue WHERE run_id=? AND state IN ('DONE','FAILED','SKIPPED','DEFERRED')",
                    (run_id,),
                ).fetchone()[0] or 0)
                conn.execute(
                    "UPDATE history_media_audit_run SET processed_games=?,updated_at=?,current_phase='RECOVERED_PLAYABLE_EVIDENCE' WHERE id=?",
                    (processed,now,run_id),
                )
                if requeued:
                    self._sync_run_frontier_conn(conn,run_id,now)
            conn.commit()
        return {"restoredAssets":len(restored),"requeuedOrdinals":requeued}


    def recover_exception_failures(self):
        """Requeue R9/R10 worker exceptions without erasing real media outcomes.

        Normal audit outcomes are written as DONE with HEALTHY/DEGRADED/UNPLAYABLE/
        NO_MEDIA. A queue row in FAILED with no canonical package is therefore an
        infrastructure/worker exception and is safe to retry in deterministic order.
        """
        now = _now()
        with self.lock, closing(self.connect(timeout=2)) as conn:
            run = conn.execute(
                "SELECT * FROM history_media_audit_run ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not run or str(run["state"] or "") not in {"RUNNING", "PAUSED"}:
                return {"runId": int(run["id"]) if run else 0, "requeued": 0}
            run_id = int(run["id"])
            candidates = conn.execute(
                """SELECT q.ordinal,q.canonical_event_key
                   FROM history_media_audit_queue q
                   LEFT JOIN history_media_canonical_package p
                     ON p.canonical_event_key=q.canonical_event_key
                   WHERE q.run_id=? AND q.state='FAILED'
                     AND q.health IN ('FAILED','UNTESTED')
                     AND p.canonical_event_key IS NULL
                   ORDER BY q.ordinal""",
                (run_id,),
            ).fetchall()
            packaged = conn.execute(
                """SELECT q.ordinal,p.health
                   FROM history_media_audit_queue q
                   JOIN history_media_canonical_package p
                     ON p.canonical_event_key=q.canonical_event_key
                   WHERE q.run_id=? AND q.state='FAILED'
                     AND q.health IN ('FAILED','UNTESTED')
                   ORDER BY q.ordinal""",
                (run_id,),
            ).fetchall()
            for row in candidates:
                conn.execute(
                    """UPDATE history_media_audit_queue
                       SET state='PENDING',phase='RECOVERED_EXCEPTION_RETRY',
                           health='UNTESTED',
                           note='Recovered infrastructure/worker exception for canonical retry',
                           started_at=0,completed_at=0
                       WHERE run_id=? AND ordinal=?""",
                    (run_id, row["ordinal"]),
                )
            for row in packaged:
                conn.execute(
                    """UPDATE history_media_audit_queue
                       SET state='DONE',phase='COMPLETE',health=?,
                           note='Recovered post-canonicalization worker exception from persisted canonical package',
                           completed_at=CASE WHEN completed_at>0 THEN completed_at ELSE ? END
                       WHERE run_id=? AND ordinal=?""",
                    (row["health"], now, run_id, row["ordinal"]),
                )
            # Any ACTIVE row belongs to the old process instance. Make it resumable too.
            conn.execute(
                """UPDATE history_media_audit_queue
                   SET state='PENDING',phase='SERVICE_RESTART_RETRY',
                       note='Audit service restarted; deterministic retry'
                   WHERE run_id=? AND state='ACTIVE'""",
                (run_id,),
            )
            processed = int(conn.execute(
                "SELECT COUNT(*) FROM history_media_audit_queue WHERE run_id=? AND state IN ('DONE','FAILED','SKIPPED','DEFERRED')",
                (run_id,),
            ).fetchone()[0] or 0)
            conn.execute(
                """UPDATE history_media_audit_run
                   SET processed_games=?,current_ordinal=0,current_event_key='',
                       current_phase='RECOVERING_QUEUE',updated_at=?,last_error=''
                   WHERE id=?""",
                (processed, now, run_id),
            )
            conn.commit()
        return {"runId": run_id, "requeued": len(candidates), "recoveredPackages": len(packaged)}

    def run_snapshot(self, run_id=None):
        with closing(self.connect()) as conn:
            if run_id:
                run = conn.execute("SELECT * FROM history_media_audit_run WHERE id=?", (run_id,)).fetchone()
            else:
                run = conn.execute("SELECT * FROM history_media_audit_run ORDER BY id DESC LIMIT 1").fetchone()
            if not run:
                return None
            counts = {r["state"]: int(r["n"]) for r in conn.execute("SELECT state,COUNT(*) n FROM history_media_audit_queue WHERE run_id=? GROUP BY state", (run["id"],)).fetchall()}
            health = {r["health"]: int(r["n"]) for r in conn.execute("SELECT health,COUNT(*) n FROM history_media_audit_queue WHERE run_id=? GROUP BY health", (run["id"],)).fetchall()}
        data = dict(run)
        data["queueStates"] = counts
        data["healthCounts"] = health
        data["progressPct"] = round(100.0 * int(data.get("processed_games") or 0) / max(1, int(data.get("total_games") or 0)), 2)
        return data

    def _sync_run_frontier_conn(self, conn, run_id: int, now=None):
        now = _now() if now is None else now
        frontier = conn.execute(
            "SELECT ordinal,canonical_event_key,phase FROM history_media_audit_queue WHERE run_id=? AND state NOT IN ('DONE','FAILED','SKIPPED','DEFERRED') ORDER BY ordinal ASC LIMIT 1",
            (run_id,),
        ).fetchone()
        if frontier:
            conn.execute(
                "UPDATE history_media_audit_run SET current_ordinal=?,current_event_key=?,current_phase=?,updated_at=? WHERE id=?",
                (frontier["ordinal"], frontier["canonical_event_key"], frontier["phase"] or "PENDING", now, run_id),
            )
        else:
            conn.execute(
                "UPDATE history_media_audit_run SET current_ordinal=0,current_event_key='',current_phase='QUEUE_EMPTY',updated_at=? WHERE id=?",
                (now, run_id),
            )

    def next_queue_item(self, run_id: int, worker_lane: int = 1):
        with self.lock, closing(self.connect()) as conn:
            # Parallel workers claim adjacent PENDING ordinals in deterministic order.
            # They may probe concurrently, but canonical commit order is enforced later.
            row = conn.execute(
                "SELECT * FROM history_media_audit_queue WHERE run_id=? AND state='PENDING' ORDER BY ordinal ASC LIMIT 1",
                (run_id,),
            ).fetchone()
            if not row:
                return None
            now = _now()
            note = f"Claimed by audit lane {int(worker_lane)}"
            conn.execute(
                "UPDATE history_media_audit_queue SET state='ACTIVE',started_at=?,phase='STARTING',note=? WHERE run_id=? AND ordinal=? AND state='PENDING'",
                (now, note, run_id, row["ordinal"]),
            )
            if conn.total_changes <= 0:
                conn.rollback()
                return None
            self._sync_run_frontier_conn(conn, run_id, now)
            conn.commit()
            row = conn.execute("SELECT * FROM history_media_audit_queue WHERE run_id=? AND ordinal=?", (run_id, row["ordinal"])).fetchone()
            return dict(row) if row else None

    def requeue_item(self, run_id: int, ordinal: int, phase="RETRY_PENDING", note=""):
        now = _now()
        with self.lock, closing(self.connect()) as conn:
            conn.execute(
                "UPDATE history_media_audit_queue SET state='PENDING',phase=?,note=? WHERE run_id=? AND ordinal=? AND state='ACTIVE'",
                (phase, str(note or "")[:1000], run_id, ordinal),
            )
            self._sync_run_frontier_conn(conn, run_id, now)
            conn.commit()

    def commit_turn_ready(self, run_id: int, ordinal: int):
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) n FROM history_media_audit_queue WHERE run_id=? AND ordinal<? AND state NOT IN ('DONE','FAILED','SKIPPED','DEFERRED')",
                (run_id, ordinal),
            ).fetchone()
        return int(row["n"] or 0) == 0

    def queue_phase(self, run_id, ordinal, phase, note=""):
        now = _now()
        with self.lock, closing(self.connect()) as conn:
            conn.execute("UPDATE history_media_audit_queue SET phase=?,note=? WHERE run_id=? AND ordinal=?", (phase, str(note or "")[:1000], run_id, ordinal))
            self._sync_run_frontier_conn(conn, run_id, now)
            conn.commit()

    def finish_queue_item(self, run_id, ordinal, health, note="", failed=False):
        now = _now()
        state = "FAILED" if failed else "DONE"
        with self.lock, closing(self.connect()) as conn:
            conn.execute("UPDATE history_media_audit_queue SET state=?,phase='COMPLETE',health=?,note=?,completed_at=? WHERE run_id=? AND ordinal=?", (state, health, str(note or "")[:1000], now, run_id, ordinal))
            processed = int(conn.execute("SELECT COUNT(*) FROM history_media_audit_queue WHERE run_id=? AND state IN ('DONE','FAILED','SKIPPED','DEFERRED')", (run_id,)).fetchone()[0] or 0)
            conn.execute("UPDATE history_media_audit_run SET processed_games=?,updated_at=?,last_error=? WHERE id=?", (processed, now, str(note or "")[:1000] if failed else "", run_id))
            self._sync_run_frontier_conn(conn, run_id, now)
            conn.commit()

    def defer_queue_item(self, run_id, ordinal, note=""):
        """Terminally defer an audit item for infrastructure uncertainty without failing media."""
        now = _now()
        with self.lock, closing(self.connect()) as conn:
            conn.execute(
                "UPDATE history_media_audit_queue SET state='DEFERRED',phase='DEFERRED_INFRA',health='INCONCLUSIVE',note=?,completed_at=? WHERE run_id=? AND ordinal=?",
                (str(note or "")[:1000], now, run_id, ordinal),
            )
            processed = int(conn.execute(
                "SELECT COUNT(*) FROM history_media_audit_queue WHERE run_id=? AND state IN ('DONE','FAILED','SKIPPED','DEFERRED')",
                (run_id,),
            ).fetchone()[0] or 0)
            conn.execute(
                "UPDATE history_media_audit_run SET processed_games=?,updated_at=?,last_error='' WHERE id=?",
                (processed, now, run_id),
            )
            self._sync_run_frontier_conn(conn, run_id, now)
            conn.commit()

    def complete_run_if_done(self, run_id):
        with self.lock, closing(self.connect()) as conn:
            remaining = int(conn.execute("SELECT COUNT(*) FROM history_media_audit_queue WHERE run_id=? AND state NOT IN ('DONE','FAILED','SKIPPED','DEFERRED')", (run_id,)).fetchone()[0] or 0)
            if remaining:
                return False
            now = _now()
            conn.execute("UPDATE history_media_audit_run SET state='COMPLETE',completed_at=?,updated_at=?,current_event_key='',current_phase='COMPLETE' WHERE id=?", (now, now, run_id))
            conn.commit()
            return True

    def event_assets(self, canonical_event_key: str):
        with closing(self.connect()) as conn:
            rows = conn.execute(
                """SELECT em.association_state,em.association_method,em.association_evidence,em.association_confidence,em.matcher_version,
                          s.asset_key,s.provider,s.provider_media_id,s.canonical_url,s.title,s.duration_seconds,s.validation_state,
                          s.runtime_state,s.runtime_success_at,s.runtime_failure_at,s.runtime_failure_reason,s.asset_json,s.verified_at,s.updated_at
                   FROM history_event_media em JOIN history_source_media s ON s.asset_key=em.asset_key
                   WHERE em.canonical_event_key=? AND s.scope='GAME' AND (em.association_state='ASSIGNED' OR em.association_method LIKE 'MEDIA_AUDIT_%' OR em.association_method='CANONICAL_MEDIA_AUDIT')
                   ORDER BY s.verified_at DESC,s.updated_at DESC""",
                (canonical_event_key,),
            ).fetchall()
        out = []
        for row in rows:
            item = _jloads(row["asset_json"], {})
            url = _asset_url(item, row["canonical_url"])
            out.append({
                "assetKey": row["asset_key"], "provider": row["provider"], "providerMediaId": row["provider_media_id"],
                "title": row["title"], "durationSeconds": float(row["duration_seconds"] or 0),
                "validationState": row["validation_state"], "runtimeState": row["runtime_state"],
                "runtimeSuccessAt": float(row["runtime_success_at"] or 0), "runtimeFailureAt": float(row["runtime_failure_at"] or 0),
                "runtimeFailureReason": row["runtime_failure_reason"] or "", "associationState": row["association_state"],
                "associationMethod": row["association_method"] or "", "url": url, "youtubeId": _youtube_id(item, url),
                "tier": _tier(item), "item": item,
            })
        return out

    def record_probe(self, run_id, event_key, asset, attempt, result, browser=""):
        """Persist raw probe evidence without letting weak negatives poison runtime health."""
        now = _now()
        reason = str(result.get("reason") or ("PLAYING_TIME_ADVANCED" if result.get("ok") else "UNKNOWN"))[:500]
        hard_failure = bool(result.get("hard")) or _hard_media_failure_reason(reason)
        infra_failure = bool(result.get("infra")) or _infra_failure_reason(reason)
        soft_failure = bool(not result.get("ok") and not hard_failure and not infra_failure)
        probe_state = "PLAYED" if result.get("ok") else ("HARD_FAILED" if hard_failure else ("INFRA_ERROR" if infra_failure else "INCONCLUSIVE"))
        with self.lock, closing(self.connect()) as conn:
            src = conn.execute(
                "SELECT asset_json,runtime_state,runtime_success_at,runtime_failure_at,runtime_failure_reason FROM history_source_media WHERE asset_key=?",
                (asset["assetKey"],),
            ).fetchone()
            item = _jloads(src["asset_json"], {}) if src else {}
            prior_success_at = float(src["runtime_success_at"] or 0) if src else 0.0
            prior_runtime = str(src["runtime_state"] or "UNKNOWN").upper() if src else "UNKNOWN"
            recent_success = bool(
                prior_runtime == "PLAYED" and prior_success_at > 0
                and prior_success_at >= now - PLAYABLE_EVIDENCE_FRESH_SECONDS
            )
            retained_prior_success = bool(not result.get("ok") and not hard_failure and recent_success)

            # Positive evidence promotes to PLAYED. Only definitive hard evidence can
            # revoke global runtime health. Soft/infra evidence is audit-only.
            if result.get("ok"):
                effective_state = "PLAYED"
                item["runtimeState"] = "playing-confirmed"
                item["verifiedPlayable"] = True
                item.pop("runtimeFailureReason", None)
                item.pop("lastAuditTransientFailureReason", None)
                item.pop("lastAuditTransientFailureAt", None)
                item.pop("lastAuditInfraFailureReason", None)
                item.pop("lastAuditInfraFailureAt", None)
            elif hard_failure:
                effective_state = "FAILED"
                item["runtimeState"] = "failed"
                item["verifiedPlayable"] = False
                item["runtimeFailureReason"] = reason
            else:
                effective_state = prior_runtime if prior_runtime in {"PLAYED", "FAILED", "UNKNOWN"} else "UNKNOWN"
                if effective_state == "FAILED" and not _hard_media_failure_reason(str(src["runtime_failure_reason"] or "") if src else ""):
                    effective_state = "UNKNOWN"
                if retained_prior_success:
                    effective_state = "PLAYED"
                    item["runtimeState"] = "playing-confirmed"
                    item["verifiedPlayable"] = True
                if infra_failure:
                    item["lastAuditInfraFailureReason"] = reason
                    item["lastAuditInfraFailureAt"] = now
                else:
                    item["lastAuditTransientFailureReason"] = reason
                    item["lastAuditTransientFailureAt"] = now

            conn.execute(
                """UPDATE history_source_media
                   SET asset_json=?,
                       validation_state=CASE WHEN ? THEN 'VERIFIED' ELSE validation_state END,
                       verified_at=CASE WHEN ? THEN ? ELSE verified_at END,
                       runtime_state=?,
                       runtime_success_at=CASE WHEN ? THEN ? ELSE runtime_success_at END,
                       runtime_failure_at=CASE WHEN ? THEN ? ELSE runtime_failure_at END,
                       runtime_failure_reason=CASE WHEN ? THEN ? WHEN ? THEN '' ELSE runtime_failure_reason END,
                       updated_at=?
                   WHERE asset_key=?""",
                (
                    _jdumps(item),
                    1 if result.get("ok") else 0,
                    1 if result.get("ok") else 0, now,
                    effective_state,
                    1 if result.get("ok") else 0, now,
                    1 if hard_failure else 0, now,
                    1 if hard_failure else 0, reason,
                    1 if result.get("ok") else 0,
                    now, asset["assetKey"],
                ),
            )
            details = {
                "auditRunId": run_id, "generation": AUDIT_GENERATION, "browser": browser,
                "probeOrigin": PROBE_URL, "startupMs": result.get("startupMs"),
                "currentTimeDelta": result.get("currentTimeDelta"), "hard": hard_failure,
                "infra": infra_failure, "soft": soft_failure,
                "effectiveRuntimeState": effective_state,
                "retainedPriorSuccess": retained_prior_success,
                "priorRuntimeState": prior_runtime, "priorRuntimeSuccessAt": prior_success_at,
            }
            conn.execute(
                "INSERT INTO history_media_verification(asset_key,verification_type,state,reason,details_json,verified_at,verification_version) VALUES(?,?,?,?,?,?,?)",
                (asset["assetKey"], "CANONICAL_BROWSER", probe_state, reason, _jdumps(details), now, VERIFICATION_VERSION),
            )
            conn.execute(
                "INSERT INTO history_media_audit_asset_result(run_id,canonical_event_key,asset_key,tier,attempt,state,reason,startup_ms,current_time_delta,browser,probe_origin,tested_at,details_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, event_key, asset["assetKey"], asset["tier"], attempt, probe_state, reason,
                    float(result.get("startupMs") or 0), float(result.get("currentTimeDelta") or 0),
                    browser, PROBE_URL, now, _jdumps({**result, **details}),
                ),
            )
            conn.commit()
        return effective_state


    def canonicalize(self, run_id, queue_item, selections, health, rehydration_state="", rehydration_reason=""):
        """Publish package preference without treating healthy alternatives as invalid."""
        event_key = queue_item["canonical_event_key"]
        chosen = {k: (v or {}).get("assetKey", "") for k, v in selections.items() if k in {"gold", "green", "extended"}}
        blue_keys = [x["assetKey"] for x in selections.get("blue", [])]
        chosen_keys = {v for v in chosen.values() if v} | set(blue_keys)
        preferred = bool(chosen.get("green") or chosen.get("extended"))
        now = _now()
        with self.lock, closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT asset_key,association_state,association_method FROM history_event_media WHERE canonical_event_key=? AND (association_state='ASSIGNED' OR association_method LIKE 'MEDIA_AUDIT_%' OR association_method='CANONICAL_MEDIA_AUDIT')",
                (event_key,),
            ).fetchall()
            source = {}
            for r in conn.execute(
                "SELECT asset_key,asset_json,runtime_state,runtime_failure_reason,runtime_success_at FROM history_source_media WHERE asset_key IN (SELECT asset_key FROM history_event_media WHERE canonical_event_key=?)",
                (event_key,),
            ).fetchall():
                source[r["asset_key"]] = {
                    "tier": _tier(_jloads(r["asset_json"], {})),
                    "runtime": str(r["runtime_state"] or "UNKNOWN").upper(),
                    "failure": str(r["runtime_failure_reason"] or ""),
                    "successAt": float(r["runtime_success_at"] or 0),
                }
            for row in rows:
                asset_key = row["asset_key"]
                meta = source.get(asset_key, {"tier": "blue", "runtime": "UNKNOWN", "failure": "", "successAt": 0})
                tier = meta["tier"]
                hard_failed = meta["runtime"] == "FAILED" and _hard_media_failure_reason(meta["failure"])
                if hard_failed:
                    state, method, evidence = QUARANTINED, "MEDIA_AUDIT_FAILED", f"definitive hard playback failure in {AUDIT_GENERATION} run {run_id}: {meta['failure']}"
                elif asset_key in chosen_keys:
                    state, method, evidence = ASSIGNED, "CANONICAL_MEDIA_AUDIT", f"primary/default {tier} selected by {AUDIT_GENERATION} run {run_id}"
                else:
                    # Validity and package preference are independent. Healthy or
                    # unproven alternatives remain attached to the game so playback
                    # has immediate recovery options without rediscovery.
                    state = ASSIGNED
                    if meta["runtime"] == "PLAYED":
                        method = "MEDIA_AUDIT_FALLBACK_AVAILABLE"
                        evidence = f"playable {tier} retained as non-default fallback; canonical package preference stored separately"
                    else:
                        method = "MEDIA_AUDIT_ALTERNATE_AVAILABLE"
                        evidence = f"non-hard-failed {tier} retained as alternate; not selected in default canonical package"
                conn.execute(
                    "UPDATE history_event_media SET association_state=?,association_method=?,association_evidence=?,updated_at=? WHERE canonical_event_key=? AND asset_key=?",
                    (state, method, evidence, now, event_key, asset_key),
                )
            conn.execute(
                """INSERT INTO history_media_canonical_package(canonical_event_key,audit_run_id,health,gold_asset_key,green_asset_key,purple_asset_key,blue_asset_keys_json,preferred_complete,preferred_playable,rehydration_state,rehydration_reason,certified_at,worker_generation,details_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(canonical_event_key) DO UPDATE SET audit_run_id=excluded.audit_run_id,health=excluded.health,gold_asset_key=excluded.gold_asset_key,green_asset_key=excluded.green_asset_key,purple_asset_key=excluded.purple_asset_key,blue_asset_keys_json=excluded.blue_asset_keys_json,preferred_complete=excluded.preferred_complete,preferred_playable=excluded.preferred_playable,rehydration_state=excluded.rehydration_state,rehydration_reason=excluded.rehydration_reason,certified_at=excluded.certified_at,worker_generation=excluded.worker_generation,details_json=excluded.details_json""",
                (event_key, run_id, health, chosen.get("gold", ""), chosen.get("green", ""), chosen.get("extended", ""), _jdumps(blue_keys), 1 if chosen.get("green") and chosen.get("extended") else 0, 1 if preferred else 0, rehydration_state, rehydration_reason, now, AUDIT_GENERATION, _jdumps({"selections": {"gold": chosen.get("gold", ""), "green": chosen.get("green", ""), "purple": chosen.get("extended", ""), "blue": blue_keys}, "preferenceSeparatedFromValidity": True})),
            )
            conn.commit()
        return {"health": health, "preferredPlayable": preferred, "selected": chosen, "blue": blue_keys}

    def inventory(self, limit=100, offset=0, league="", health="", search=""):
        """SQL-filtered/paginated operator inventory; never load the full catalog into memory."""
        limit = max(1, min(500, int(limit or 100)))
        offset = max(0, int(offset or 0))
        league = str(league or "").upper()
        health = str(health or "").upper()
        search = str(search or "").strip().lower()
        today = _today()
        health_expr = """CASE
            WHEN q.health='INCONCLUSIVE' THEN 'INCONCLUSIVE'
            WHEN p.health IS NOT NULL AND p.health<>'' THEN p.health
            WHEN e.final_at>0 OR e.event_date<? THEN 'UNTESTED'
            ELSE 'WAITING_FINAL' END"""
        where = ["e.event_date<=?"]
        params = [today]
        if league:
            where.append("UPPER(e.league)=?"); params.append(league)
        if search:
            where.append("(LOWER(e.event_json) LIKE ? OR LOWER(e.league) LIKE ? OR LOWER(e.event_id) LIKE ?)")
            token = f"%{search}%"; params.extend([token, token, token])
        if health:
            where.append(f"({health_expr})=?"); params.extend([today, health])
        else:
            # health_expr still needs its date parameter in SELECT below
            pass
        where_sql = " AND ".join(where)
        select_health_params = [today]
        # Parameter order is SELECT expression first, then WHERE parameters. When the
        # health expression is repeated in WHERE it consumes one additional today.
        query_params = select_health_params + params
        count_params = list(params)
        latest_cte = "WITH latest_run AS (SELECT id FROM history_media_audit_run ORDER BY id DESC LIMIT 1)"
        joins = """
            FROM history_catalog_event e
            LEFT JOIN history_media_canonical_package p ON p.canonical_event_key=e.canonical_event_key
            LEFT JOIN latest_run lr ON 1=1
            LEFT JOIN history_media_audit_queue q ON q.run_id=lr.id AND q.canonical_event_key=e.canonical_event_key
        """
        with closing(self.connect()) as conn:
            count_sql = latest_cte + " SELECT COUNT(*) " + joins + " WHERE " + where_sql
            total = int(conn.execute(count_sql, tuple(count_params)).fetchone()[0] or 0)
            sql = latest_cte + f"""
                SELECT e.canonical_event_key,e.league,e.event_id,e.event_date,e.event_json,e.final_at,
                       p.certified_at,p.gold_asset_key,p.green_asset_key,p.purple_asset_key,p.blue_asset_keys_json,p.rehydration_state,
                       q.ordinal AS queue_ordinal,q.state AS queue_state,q.phase AS queue_phase,q.health AS queue_health,
                       {health_expr} AS row_health
                {joins}
                WHERE {where_sql}
                ORDER BY CASE WHEN q.ordinal IS NULL THEN 1 ELSE 0 END, q.ordinal ASC, e.event_date DESC, e.canonical_event_key ASC
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(sql, tuple(query_params + [limit, offset])).fetchall()
        out = []
        for row in rows:
            event = _jloads(row["event_json"], {})
            final = _event_final(row["event_date"], row["final_at"], event)
            away, home = _team_name(event, "away"), _team_name(event, "home")
            game = f"{away} @ {home}".strip(" @") or str(row["event_id"])
            row_health = str(row["row_health"] or ("UNTESTED" if final else "WAITING_FINAL"))
            if row_health == "WAITING_FINAL" and final:
                row_health = "UNTESTED"
            out.append({
                "canonicalEventKey": row["canonical_event_key"], "date": row["event_date"], "league": row["league"],
                "eventId": row["event_id"], "game": game, "final": final, "health": row_health,
                "certifiedAt": float(row["certified_at"] or 0), "gold": str(row["gold_asset_key"] or ""),
                "green": str(row["green_asset_key"] or ""), "purple": str(row["purple_asset_key"] or ""),
                "blueCount": len(_jloads(row["blue_asset_keys_json"], [])),
                "rehydrationState": str(row["rehydration_state"] or ""),
                "queueOrdinal": int(row["queue_ordinal"] or 0), "queueState": str(row["queue_state"] or ""),
                "queuePhase": str(row["queue_phase"] or ""),
            })
        return {"rows": out, "total": total, "limit": limit, "offset": offset}

    def event_detail(self, event_key):
        pkg = None
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM history_media_canonical_package WHERE canonical_event_key=?", (event_key,)).fetchone()
            pkg = dict(row) if row else None
            results = [dict(r) for r in conn.execute("SELECT * FROM history_media_audit_asset_result WHERE canonical_event_key=? ORDER BY tested_at DESC,id DESC LIMIT 100", (event_key,)).fetchall()]
        return {"package": pkg, "assets": self.event_assets(event_key), "results": results}

    def summary(self):
        now = _now()
        with closing(self.connect()) as conn:
            package_counts = {r["health"]: int(r["n"]) for r in conn.execute("SELECT health,COUNT(*) n FROM history_media_canonical_package GROUP BY health").fetchall()}
            certified = int(conn.execute("SELECT COUNT(*) FROM history_media_canonical_package WHERE certified_at>0").fetchone()[0] or 0)
            stale = int(conn.execute("SELECT COUNT(*) FROM history_media_canonical_package WHERE certified_at>0 AND certified_at<?", (now - FRESH_SECONDS,)).fetchone()[0] or 0)
            failed_assets = int(conn.execute("SELECT COUNT(*) FROM history_source_media WHERE runtime_state='FAILED'").fetchone()[0] or 0)
            played_assets = int(conn.execute("SELECT COUNT(*) FROM history_source_media WHERE runtime_state='PLAYED'").fetchone()[0] or 0)
            total_events = int(conn.execute("SELECT COUNT(*) FROM history_catalog_event WHERE event_date<=?", (_today(),)).fetchone()[0] or 0)
            latest = conn.execute("SELECT id FROM history_media_audit_run ORDER BY id DESC LIMIT 1").fetchone()
            inconclusive = 0
            deferred = 0
            if latest:
                inconclusive = int(conn.execute("SELECT COUNT(*) FROM history_media_audit_queue WHERE run_id=? AND health='INCONCLUSIVE'", (latest["id"],)).fetchone()[0] or 0)
                deferred = int(conn.execute("SELECT COUNT(*) FROM history_media_audit_queue WHERE run_id=? AND state='DEFERRED'", (latest["id"],)).fetchone()[0] or 0)
        return {"games": total_events, "certifiedGames": certified, "staleGames": stale, "health": package_counts, "playedAssets": played_assets, "failedAssets": failed_assets, "inconclusiveGames": inconclusive, "deferredInfraGames": deferred}

    def rehydration_manifest(self):
        """Export actionable repair work, including non-destructive inconclusive/deferred audit outcomes."""
        with closing(self.connect()) as conn:
            package_rows = conn.execute(
                """SELECT p.*,e.league,e.event_id,e.event_date,e.event_json
                   FROM history_media_canonical_package p
                   JOIN history_catalog_event e ON e.canonical_event_key=p.canonical_event_key
                   WHERE p.rehydration_state<>'' OR p.health IN ('UNPLAYABLE','NO_MEDIA','DEGRADED')
                   ORDER BY e.event_date DESC,e.league,e.event_id"""
            ).fetchall()
            latest = conn.execute("SELECT id FROM history_media_audit_run ORDER BY id DESC LIMIT 1").fetchone()
            queue_rows = []
            if latest:
                queue_rows = conn.execute(
                    """SELECT q.*,e.event_json
                       FROM history_media_audit_queue q
                       JOIN history_catalog_event e ON e.canonical_event_key=q.canonical_event_key
                       WHERE q.run_id=? AND (q.health='INCONCLUSIVE' OR q.state='DEFERRED')
                       ORDER BY q.event_date DESC,q.ordinal""",
                    (latest["id"],),
                ).fetchall()
        games = []
        seen = set()
        for row in package_rows:
            event = _jloads(row["event_json"], {})
            key = str(row["canonical_event_key"])
            seen.add(key)
            games.append({
                "date": row["event_date"], "league": row["league"], "eventId": row["event_id"], "canonicalEventKey": key,
                "game": f"{_team_name(event,'away')} @ {_team_name(event,'home')}".strip(" @"), "health": row["health"],
                "rehydrationState": row["rehydration_state"], "reason": row["rehydration_reason"],
                "canonicalGreen": row["green_asset_key"], "canonicalPurple": row["purple_asset_key"], "canonicalBlue": _jloads(row["blue_asset_keys_json"], []),
            })
        for row in queue_rows:
            key = str(row["canonical_event_key"])
            if key in seen:
                continue
            event = _jloads(row["event_json"], {})
            games.append({
                "date": row["event_date"], "league": row["league"], "eventId": row["event_id"], "canonicalEventKey": key,
                "game": str(row["game"] or f"{_team_name(event,'away')} @ {_team_name(event,'home')}".strip(" @")),
                "health": "INCONCLUSIVE", "rehydrationState": "RECERTIFICATION_REQUIRED",
                "reason": str(row["note"] or row["phase"] or "Audit evidence inconclusive"),
                "canonicalGreen": "", "canonicalPurple": "", "canonicalBlue": [],
            })
        return {"generatedAt": _now(), "generation": AUDIT_GENERATION, "games": games}

    def recover_healthy_audit_alternatives(self):
        """Undo old audit quarantine decisions that represented preference or soft/infra failure, not invalidity."""
        now = _now(); cutoff = now - PLAYABLE_EVIDENCE_FRESH_SECONDS
        restored = 0; reset_nonhard = 0; preserved_recent = 0
        affected = set(); requeued = []; removed_false_packages = 0
        with self.lock, closing(self.connect(timeout=2)) as conn:
            rows = conn.execute(
                """SELECT em.canonical_event_key,em.asset_key,em.association_method,
                          s.runtime_state,s.runtime_success_at,s.runtime_failure_reason
                   FROM history_event_media em JOIN history_source_media s ON s.asset_key=em.asset_key
                   WHERE em.association_state='QUARANTINED' AND em.association_method IN
                     ('MEDIA_AUDIT_SUPERSEDED','MEDIA_AUDIT_BLUE_SUPPRESSED','MEDIA_AUDIT_NON_CANONICAL','MEDIA_AUDIT_FAILED')"""
            ).fetchall()
            for row in rows:
                runtime_state = str(row["runtime_state"] or "").upper()
                reason = str(row["runtime_failure_reason"] or "")
                hard = runtime_state == "FAILED" and _hard_media_failure_reason(reason)
                if hard:
                    continue
                success_at = float(row["runtime_success_at"] or 0)
                # R11 could globally mark a soft/infra timeout as FAILED. Preserve
                # positive evidence when it exists; otherwise clear only the stale
                # negative authority back to UNKNOWN.
                if runtime_state == "FAILED":
                    if success_at > 0 and success_at >= cutoff:
                        conn.execute(
                            "UPDATE history_source_media SET runtime_state='PLAYED',runtime_failure_reason='',updated_at=? WHERE asset_key=?",
                            (now, row["asset_key"]),
                        )
                        runtime_state = "PLAYED"
                        preserved_recent += 1
                    else:
                        conn.execute(
                            "UPDATE history_source_media SET runtime_state='UNKNOWN',runtime_failure_reason='',updated_at=? WHERE asset_key=?",
                            (now, row["asset_key"]),
                        )
                        runtime_state = "UNKNOWN"
                    reset_nonhard += 1
                    affected.add(str(row["canonical_event_key"]))
                method = "MEDIA_AUDIT_FALLBACK_AVAILABLE" if runtime_state == "PLAYED" else "MEDIA_AUDIT_ALTERNATE_AVAILABLE"
                conn.execute(
                    "UPDATE history_event_media SET association_state='ASSIGNED',association_method=?,association_evidence=?,updated_at=? WHERE canonical_event_key=? AND asset_key=?",
                    (method, "Restored by R12: package preference/soft audit evidence no longer quarantines valid media", now, row["canonical_event_key"], row["asset_key"]),
                )
                restored += 1

            # A prior R11 UNPLAYABLE/NO_MEDIA package may have been caused solely by
            # soft/infra failures that R12 just stripped of negative authority. Remove
            # those false packages and requeue the same ordinal when a live run exists.
            false_package_events = set()
            for event_key in sorted(affected):
                pkg = conn.execute(
                    "SELECT health FROM history_media_canonical_package WHERE canonical_event_key=?",
                    (event_key,),
                ).fetchone()
                if pkg and str(pkg["health"] or "").upper() in {"UNPLAYABLE", "NO_MEDIA"}:
                    conn.execute("DELETE FROM history_media_canonical_package WHERE canonical_event_key=?", (event_key,))
                    false_package_events.add(event_key)
                    removed_false_packages += 1

            run = conn.execute("SELECT id,state FROM history_media_audit_run ORDER BY id DESC LIMIT 1").fetchone()
            if run and str(run["state"] or "") in {"RUNNING", "PAUSED"} and false_package_events:
                run_id = int(run["id"])
                for event_key in sorted(false_package_events):
                    q = conn.execute(
                        "SELECT ordinal,state FROM history_media_audit_queue WHERE run_id=? AND canonical_event_key=?",
                        (run_id, event_key),
                    ).fetchone()
                    if not q or str(q["state"] or "") not in {"DONE", "FAILED", "SKIPPED", "DEFERRED"}:
                        continue
                    conn.execute(
                        """UPDATE history_media_audit_queue
                           SET state='PENDING',phase='RECOVERED_NONHARD_FAILURE',health='UNTESTED',
                               note='R12 removed false hard-failure authority; clean recertification required',
                               started_at=0,completed_at=0
                           WHERE run_id=? AND ordinal=?""",
                        (run_id, q["ordinal"]),
                    )
                    requeued.append(int(q["ordinal"]))
                if requeued:
                    processed = int(conn.execute(
                        "SELECT COUNT(*) FROM history_media_audit_queue WHERE run_id=? AND state IN ('DONE','FAILED','SKIPPED','DEFERRED')",
                        (run_id,),
                    ).fetchone()[0] or 0)
                    conn.execute(
                        "UPDATE history_media_audit_run SET processed_games=?,updated_at=?,current_phase='RECOVERED_NONHARD_FAILURE' WHERE id=?",
                        (processed, now, run_id),
                    )
                    self._sync_run_frontier_conn(conn, run_id, now)
            conn.commit()
        return {
            "restoredAlternatives": restored,
            "resetNonHardFailures": reset_nonhard,
            "preservedRecentPlayable": preserved_recent,
            "removedFalsePackages": removed_false_packages,
            "requeuedOrdinals": requeued,
        }


class BrowserProbe:
    def __init__(self):
        self.driver = None
        self.lock = threading.RLock()
        self.browser = ""
        self.last_error = ""
        self.restart_count = 0

    def close(self):
        with self.lock:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None

    def restart(self):
        self.close()
        self.restart_count += 1

    def _ensure(self):
        with self.lock:
            if self.driver:
                return self.driver
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            options = Options()
            for arg in (
                "--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                "--mute-audio", "--autoplay-policy=no-user-gesture-required", "--window-size=1280,720",
                "--disable-background-networking", "--disable-component-update", "--disable-default-apps",
            ):
                options.add_argument(arg)
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(30)
            driver.set_script_timeout(30)
            caps = driver.capabilities or {}
            self.browser = f"Chrome {caps.get('browserVersion','?')} / chromedriver {((caps.get('chrome') or {}).get('chromedriverVersion') or '?').split(' ')[0]}"
            self.driver = driver
            self.last_error = ""
            return driver

    def probe(self, asset):
        url = str(asset.get("url") or "")
        youtube_id = str(asset.get("youtubeId") or "")
        if not youtube_id and IMAGE_RE.search(url):
            return {"ok": False, "hard": True, "infra": False, "reason": "NON_VIDEO_MEDIA_URL", "startupMs": 0, "currentTimeDelta": 0}
        if not youtube_id and not url:
            return {"ok": False, "hard": True, "infra": False, "reason": "MEDIA_URL_MISSING", "startupMs": 0, "currentTimeDelta": 0}
        payload = {"kind": "youtube" if youtube_id else "direct", "youtubeId": youtube_id, "url": url, "assetKey": asset.get("assetKey")}
        with self.lock:
            # Chrome/ChromeDriver creation is itself audit infrastructure. Keep it
            # inside the protected boundary so localhost ReadTimeoutError can never
            # escape as a media failure or terminal queue failure.
            try:
                driver = self._ensure()
                driver.get(PROBE_URL + ("?worker=" + AUDIT_GENERATION + "&t=" + str(int(_now()))))
                result = driver.execute_async_script(
                    """const input=arguments[0], done=arguments[arguments.length-1];
                    const finish=(v)=>done(v||{ok:false,reason:'EMPTY_PROBE_RESULT'});
                    if(!window.SBB_MEDIA_PROBE||!window.SBB_MEDIA_PROBE.probe){finish({ok:false,hard:false,infra:true,reason:'PROBE_PAGE_NOT_READY'});return;}
                    window.SBB_MEDIA_PROBE.probe(input).then(finish).catch(e=>finish({ok:false,hard:false,infra:true,reason:'PROBE_EXCEPTION',message:String(e&&e.message||e)}));""",
                    payload,
                )
                if not isinstance(result, dict):
                    return {"ok": False, "hard": False, "infra": True, "reason": "INVALID_PROBE_RESULT"}
                if _infra_failure_reason(result.get("reason")):
                    result["infra"] = True
                return result
            except Exception as exc:
                result = _infra_result_from_exception(exc)
                self.last_error = result.get("message") or result.get("reason")
                try:
                    if self.driver:
                        self.driver.quit()
                except Exception:
                    pass
                self.driver = None
                return result


class AuditRunReplaced(RuntimeError):
    """Raised when a queued DB write belongs to a stopped/replaced audit run."""


class SerializedAuditDbWriter(threading.Thread):
    """One SQLite writer for all audit lanes.

    Browser lanes may probe concurrently, but every audit-owned SQLite mutation is
    funneled through this queue. A transient SQLite writer lock therefore delays the
    commit without discarding the already-completed browser result or replaying media.
    """
    daemon = True

    def __init__(self, store: AuditStore):
        super().__init__(name="canonical-media-audit-db-writer")
        self.store = store
        self.jobs = queue.Queue(maxsize=DB_WRITE_QUEUE_MAX)
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.active = {}
        self.last_error = ""
        self.last_commit_at = 0.0
        self.lock_retries = 0
        self.completed_writes = 0

    def stop(self):
        self.stop_event.set()

    def snapshot(self):
        with self.lock:
            active = dict(self.active or {})
            return {
                "alive": self.is_alive(),
                "state": "LOCKED" if active.get("locked") else ("WRITING" if active else "IDLE"),
                "queueDepth": self.jobs.qsize(),
                "activeOperation": active.get("operation", ""),
                "activeRunId": int(active.get("runId") or 0),
                "activeOrdinal": int(active.get("ordinal") or 0),
                "activeEvent": active.get("eventKey", ""),
                "activeLane": int(active.get("lane") or 0),
                "lockRetries": int(self.lock_retries),
                "lastError": self.last_error,
                "lastCommitAt": self.last_commit_at,
                "completedWrites": int(self.completed_writes),
            }

    def submit(self, operation, method_name, *args, run_id=0, ordinal=0, event_key="", lane=0, **kwargs):
        if self.stop_event.is_set():
            raise AuditRunReplaced("DB_WRITER_STOPPED")
        job = {
            "operation": str(operation or method_name),
            "method": str(method_name),
            "args": args,
            "kwargs": kwargs,
            "runId": int(run_id or 0),
            "ordinal": int(ordinal or 0),
            "eventKey": str(event_key or ""),
            "lane": int(lane or 0),
            "done": threading.Event(),
            "result": None,
            "error": None,
            "queuedAt": _now(),
        }
        self.jobs.put(job)
        while not job["done"].wait(0.25):
            if self.stop_event.is_set():
                raise AuditRunReplaced("DB_WRITER_STOPPED")
        if job["error"] is not None:
            raise job["error"]
        return job["result"]

    def _run_is_current(self, run_id):
        if not run_id:
            return True
        state = self.store.exact_run_state(int(run_id))
        return bool(state and state != "STOPPED")

    def run(self):
        while not self.stop_event.is_set() or not self.jobs.empty():
            try:
                job = self.jobs.get(timeout=0.25)
            except queue.Empty:
                continue
            with self.lock:
                self.active = {
                    "operation": job["operation"], "runId": job["runId"],
                    "ordinal": job["ordinal"], "eventKey": job["eventKey"],
                    "lane": job["lane"], "locked": False,
                }
            try:
                while not self.stop_event.is_set():
                    try:
                        if job["runId"] and not self._run_is_current(job["runId"]):
                            raise AuditRunReplaced(
                                f"Run {job['runId']} was replaced before DB commit: {job['operation']}"
                            )
                        method = getattr(self.store, job["method"])
                        job["result"] = method(*job["args"], **job["kwargs"])
                        with self.lock:
                            self.last_error = ""
                            self.last_commit_at = _now()
                            self.completed_writes += 1
                            self.active["locked"] = False
                        break
                    except sqlite3.OperationalError as exc:
                        if not _is_db_locked(exc):
                            raise
                        with self.lock:
                            self.lock_retries += 1
                            self.last_error = f"{type(exc).__name__}: {exc}"
                            self.active["locked"] = True
                        # Preserve this exact queued result and retry the database write.
                        # Do not return control to the browser lane, so media is never
                        # replayed merely because SQLite's single writer is occupied.
                        time.sleep(DB_LOCK_RETRY_SECONDS)
                else:
                    raise AuditRunReplaced("DB_WRITER_STOPPED")
            except Exception as exc:
                job["error"] = exc
                with self.lock:
                    self.last_error = f"{type(exc).__name__}: {exc}"
            finally:
                with self.lock:
                    self.active = {}
                job["done"].set()
                self.jobs.task_done()


class CanonicalAuditWorker(threading.Thread):
    daemon = True

    def __init__(self, store: AuditStore, probe: BrowserProbe, db_writer: SerializedAuditDbWriter, worker_lane: int = 1):
        self.worker_lane = int(worker_lane)
        super().__init__(name=f"canonical-media-audit-{self.worker_lane}")
        self.store, self.probe, self.db_writer = store, probe, db_writer
        self.stop_event = threading.Event()
        self.current = {}
        self.last_error = ""
        self.exception_retries = {}
        self.diag_lock = threading.RLock()
        self.diagnostics = {
            "state": "IDLE",
            "phase": "IDLE",
            "phaseStartedAt": _now(),
            "lastProgressAt": _now(),
            "waitingReason": "",
            "dbState": "READY",
            "dbOperation": "",
            "dbLockRetries": 0,
            "lastDbLockAt": 0,
            "lastDbRecoveryAt": 0,
            "candidateTier": "",
            "candidateIndex": 0,
            "candidateCount": 0,
            "assetKey": "",
            "assetTitle": "",
            "assetProvider": "",
            "probeAttempt": 0,
            "probeMaxAttempts": SOFT_RETRIES,
            "lastProbeResult": "",
            "discoveryPass": 0,
            "discoveryMaxPasses": DISCOVERY_PASSES,
            "discoveryResult": "",
            "dbAssetCount": 0,
            "productionMediaCount": 0,
            "productionPlayableCount": 0,
            "productionPlanState": "",
            "lastOperation": "",
            "workerLane": self.worker_lane,
            "workerCount": AUDIT_WORKER_COUNT,
            "pendingDbWrite": "",
            "pendingDbWriteState": "",
        }
        self.trace = deque(maxlen=120)

    def stop(self):
        self.stop_event.set()
        self.probe.close()

    def _trace(self, level, message, **details):
        row = {"at": _now(), "level": str(level or "INFO").upper(), "message": str(message or "")[:1000]}
        if details:
            row["details"] = details
        with self.diag_lock:
            self.trace.append(row)

    def _diag(self, phase=None, progress=False, **patch):
        now = _now()
        with self.diag_lock:
            if phase is not None and str(phase) != str(self.diagnostics.get("phase") or ""):
                self.diagnostics["phase"] = str(phase)
                self.diagnostics["phaseStartedAt"] = now
            if progress:
                self.diagnostics["lastProgressAt"] = now
            for key, value in patch.items():
                self.diagnostics[key] = value

    def snapshot(self):
        with self.diag_lock:
            data = dict(self.diagnostics)
            data["trace"] = list(self.trace)[-80:]
        data["phaseAgeSeconds"] = max(0, round(_now() - float(data.get("phaseStartedAt") or _now()), 1))
        data["idleSinceProgressSeconds"] = max(0, round(_now() - float(data.get("lastProgressAt") or _now()), 1))
        return data

    def _db_op(self, operation):
        self._diag(dbOperation=operation, lastOperation=operation)

    def _db_recovered(self):
        snap = self.snapshot()
        if snap.get("dbState") == "LOCKED":
            if _is_db_locked(sqlite3.OperationalError(self.last_error)):
                self.last_error = ""
            self._diag(dbState="READY", waitingReason="", lastDbRecoveryAt=_now(), progress=True)
            self._trace("INFO", "SQLite write lock recovered; retrying same queue ordinal")
        else:
            self._diag(dbState="READY")

    def _reset_event_evidence(self):
        self.event_evidence = {"infra": [], "soft": [], "hard": [], "compatibility": []}

    def _note_event_evidence(self, kind, reason):
        if not hasattr(self, "event_evidence"):
            self._reset_event_evidence()
        bucket = self.event_evidence.setdefault(kind, [])
        reason = str(reason or "UNKNOWN")
        if reason not in bucket:
            bucket.append(reason)

    def _write(self, operation, method_name, *args, run_id=0, ordinal=0, event_key="", pending_phase="", pending_note="", **kwargs):
        previous_phase = self.snapshot().get("phase") or "RUNNING"
        self._db_op(operation)
        if pending_phase:
            self._diag(
                phase=pending_phase, dbState="QUEUED", pendingDbWrite=operation,
                pendingDbWriteState="QUEUED", waitingReason=pending_note or f"Waiting for serialized DB writer: {operation}"
            )
        try:
            value = self.db_writer.submit(
                operation, method_name, *args, run_id=run_id, ordinal=ordinal,
                event_key=event_key, lane=self.worker_lane, **kwargs
            )
            self._diag(
                dbState="READY", pendingDbWrite="", pendingDbWriteState="SAVED",
                waitingReason="", progress=True
            )
            if pending_phase:
                self._diag(phase=previous_phase)
            return value
        except AuditRunReplaced:
            self._diag(
                dbState="READY", pendingDbWrite="", pendingDbWriteState="DISCARDED",
                waitingReason="Audit run was stopped/replaced before queued DB commit"
            )
            raise

    def run(self):
        while not self.stop_event.is_set():
            try:
                self._db_op("read active run")
                run = self.store.active_run()
                self._db_recovered()
                if not run or run["state"] not in {"RUNNING", "PAUSED"}:
                    self._diag(state="IDLE" if not run else str(run["state"]), phase="IDLE" if not run else str(run["state"]), waitingReason="")
                    time.sleep(1.0)
                    continue
                if run["state"] == "PAUSED":
                    self._diag(state="PAUSED", phase="PAUSED", waitingReason="Operator paused canonical audit")
                    time.sleep(1.0)
                    continue

                self._db_op("claim next deterministic queue ordinal")
                item = self._write(
                    "claim next deterministic queue ordinal", "next_queue_item",
                    int(run["id"]), self.worker_lane, run_id=int(run["id"])
                )
                self._db_recovered()
                if not item:
                    self._db_op("complete run if queue empty")
                    self._write(
                        "complete run if queue empty", "complete_run_if_done", int(run["id"]),
                        run_id=int(run["id"])
                    )
                    self._diag(state="RUNNING", phase="QUEUE_EMPTY", progress=True)
                    time.sleep(1.0)
                    continue

                self.current = {
                    "runId": run["id"], "ordinal": item["ordinal"], "event": item["canonical_event_key"],
                    "game": item["game"], "phase": item["phase"], "league": item["league"], "eventId": item["event_id"],
                }
                self._diag(
                    state="RUNNING", phase=str(item.get("phase") or "STARTING"), progress=True,
                    waitingReason="", ordinal=int(item["ordinal"]), runId=int(run["id"]),
                    eventKey=item["canonical_event_key"], game=item["game"], league=item["league"],
                    candidateTier="", candidateIndex=0, candidateCount=0, assetKey="", assetTitle="", assetProvider="",
                    probeAttempt=0, lastProbeResult="", discoveryPass=0, discoveryResult="",
                )
                self._trace("INFO", f"Lane {self.worker_lane} • Queue #{item['ordinal']} started: {item['game']}", league=item["league"], event=item["canonical_event_key"], lane=self.worker_lane)

                try:
                    result = self.audit_event(run, item)
                    current_run = self.store.run_snapshot(int(run["id"]))
                    self._db_recovered()
                    if current_run and current_run.get("state") != "STOPPED":
                        self._db_op("finish queue item")
                        if result.get("deferred"):
                            self._write(
                                "defer infrastructure-inconclusive queue item", "defer_queue_item",
                                run["id"], item["ordinal"], result.get("note", ""),
                                run_id=int(run["id"]), ordinal=int(item["ordinal"]),
                                event_key=item["canonical_event_key"], pending_phase="WAITING_DB_COMMIT",
                                pending_note="Infrastructure-inconclusive result complete; waiting to save DEFERRED_INFRA state"
                            )
                        else:
                            self._write(
                                "finish queue item", "finish_queue_item",
                                run["id"], item["ordinal"], result.get("health", "FAILED"),
                                result.get("note", ""), failed=bool(result.get("failed")),
                                run_id=int(run["id"]), ordinal=int(item["ordinal"]),
                                event_key=item["canonical_event_key"], pending_phase="WAITING_DB_COMMIT",
                                pending_note="Audit result complete; waiting for serialized DB commit"
                            )
                        self._db_recovered()
                    self.exception_retries.pop(item["canonical_event_key"], None)
                    self._diag(progress=True, lastResult=result.get("note", ""), waitingReason="")
                    self._trace("INFO", f"Queue #{item['ordinal']} complete: {result.get('health','UNKNOWN')}", note=result.get("note", ""))
                except sqlite3.OperationalError as exc:
                    if not _is_db_locked(exc):
                        raise
                    msg = f"{type(exc).__name__}: {exc}"
                    self.last_error = msg
                    snap = self.snapshot()
                    retries = int(snap.get("dbLockRetries") or 0) + 1
                    self._diag(
                        state="RUNNING", phase="WAITING_DATABASE_LOCK", dbState="LOCKED",
                        dbLockRetries=retries, lastDbLockAt=_now(), waitingReason=msg,
                        lastProbeResult=msg,
                    )
                    self._trace(
                        "WARN", f"SQLite busy outside serialized audit writer on queue #{item['ordinal']}; ordinal returned to pending queue",
                        operation=snap.get("dbOperation") or "", retry=retries, event=item["canonical_event_key"], lane=self.worker_lane
                    )
                    try:
                        self._write(
                            "requeue after non-writer SQLite read contention", "requeue_item",
                            run["id"], item["ordinal"], "WAITING_DATABASE_LOCK", msg,
                            run_id=int(run["id"]), ordinal=int(item["ordinal"]),
                            event_key=item["canonical_event_key"]
                        )
                    except AuditRunReplaced:
                        pass
                    time.sleep(DB_LOCK_RETRY_SECONDS)
                    continue
                except AuditRunReplaced:
                    self._trace("INFO", f"Queue #{item['ordinal']} work discarded because run was stopped/replaced", lane=self.worker_lane)
                    continue
                except Exception as exc:
                    msg = f"{type(exc).__name__}: {exc}"
                    self.last_error = msg
                    key = item["canonical_event_key"]
                    attempt = int(self.exception_retries.get(key) or 0) + 1
                    self.exception_retries[key] = attempt
                    traceback.print_exc()
                    if attempt <= WORKER_EXCEPTION_RETRIES:
                        self._diag(
                            state="RUNNING", phase="RETRY_WORKER_EXCEPTION", waitingReason=msg,
                            exceptionRetry=attempt, exceptionRetryMax=WORKER_EXCEPTION_RETRIES,
                        )
                        self._trace(
                            "WARN", f"Worker exception on queue #{item['ordinal']}; retrying same ordinal",
                            error=msg, retry=attempt, maxRetries=WORKER_EXCEPTION_RETRIES
                        )
                        try:
                            self._write(
                                "persist worker exception retry phase", "queue_phase",
                                run["id"], item["ordinal"], "RETRY_WORKER_EXCEPTION",
                                f"{msg} • retry {attempt}/{WORKER_EXCEPTION_RETRIES}",
                                run_id=int(run["id"]), ordinal=int(item["ordinal"]),
                                event_key=item["canonical_event_key"]
                            )
                            self._write(
                                "requeue worker exception", "requeue_item",
                                run["id"], item["ordinal"], "RETRY_WORKER_EXCEPTION",
                                f"{msg} • retry {attempt}/{WORKER_EXCEPTION_RETRIES}",
                                run_id=int(run["id"]), ordinal=int(item["ordinal"]),
                                event_key=item["canonical_event_key"]
                            )
                            self._db_recovered()
                        except sqlite3.OperationalError as db_exc:
                            if _is_db_locked(db_exc):
                                self._diag(
                                    phase="WAITING_DATABASE_LOCK", dbState="LOCKED",
                                    dbLockRetries=int(self.snapshot().get("dbLockRetries") or 0)+1,
                                    lastDbLockAt=_now(), waitingReason=f"{type(db_exc).__name__}: {db_exc}"
                                )
                                try:
                                    self._write(
                                        "requeue worker exception after read contention", "requeue_item",
                                        run["id"], item["ordinal"], "RETRY_WORKER_EXCEPTION",
                                        f"{msg} • retry {attempt}/{WORKER_EXCEPTION_RETRIES}",
                                        run_id=int(run["id"]), ordinal=int(item["ordinal"]),
                                        event_key=item["canonical_event_key"]
                                    )
                                except AuditRunReplaced:
                                    pass
                            else:
                                raise
                        time.sleep(min(10.0, 1.5 * attempt))
                        continue

                    current_run = self.store.run_snapshot(int(run["id"]))
                    if current_run and current_run.get("state") != "STOPPED":
                        self._db_op("terminal worker exception after bounded retries")
                        self._write(
                            "defer terminal worker infrastructure exception", "defer_queue_item",
                            run["id"], item["ordinal"],
                            f"Audit infrastructure exception exhausted {WORKER_EXCEPTION_RETRIES} retries: {msg}",
                            run_id=int(run["id"]), ordinal=int(item["ordinal"]),
                            event_key=item["canonical_event_key"], pending_phase="WAITING_DB_COMMIT",
                            pending_note="Worker infrastructure exception exhausted; saving DEFERRED_INFRA without penalizing media"
                        )
                    self._trace("ERROR", f"Queue #{item['ordinal']} deferred after terminal worker infrastructure exception", error=msg)
                finally:
                    self.current = {}

                self._db_op("complete run if done")
                self._write(
                    "complete run if done", "complete_run_if_done", int(run["id"]),
                    run_id=int(run["id"])
                )
                self._db_recovered()
            except AuditRunReplaced:
                self._diag(state="IDLE", phase="RUN_REPLACED", waitingReason="Audit run was stopped/replaced")
                time.sleep(0.25)
                continue
            except sqlite3.OperationalError as exc:
                if _is_db_locked(exc):
                    msg = f"{type(exc).__name__}: {exc}"
                    self.last_error = msg
                    retries = int(self.snapshot().get("dbLockRetries") or 0) + 1
                    self._diag(
                        state="RUNNING", phase="WAITING_DATABASE_LOCK", dbState="LOCKED",
                        dbLockRetries=retries, lastDbLockAt=_now(), waitingReason=msg
                    )
                    self._trace("WARN", "SQLite busy outside event transaction; worker will retry", retry=retries)
                    time.sleep(DB_LOCK_RETRY_SECONDS)
                    continue
                self.last_error = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
                time.sleep(3)
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                self._diag(state="ERROR", phase="WORKER_LOOP_ERROR", waitingReason=self.last_error)
                self._trace("ERROR", "Worker loop error", error=self.last_error)
                traceback.print_exc()
                time.sleep(3)

    def _probe_candidate(self, run_id, event_key, asset, *, tier="", index=0, count=0):
        last = None
        media_attempt = 0
        infra_attempt = 0
        while not self.stop_event.is_set():
            self._db_op("read run state before media probe")
            current = self.store.run_snapshot(run_id)
            self._db_recovered()
            if not current or current.get("state") == "STOPPED":
                return {"ok": False, "hard": False, "infra": True, "reason": "RUN_STOPPED"}
            if current.get("state") == "PAUSED":
                self._diag(phase="PAUSED", waitingReason="Operator paused canonical audit")
                time.sleep(1); continue

            self._diag(
                candidateTier=str(tier or asset.get("tier") or "").upper(),
                candidateIndex=int(index or 0), candidateCount=int(count or 0),
                assetKey=asset.get("assetKey") or "", assetTitle=asset.get("title") or "",
                assetProvider=asset.get("provider") or "", probeAttempt=media_attempt + 1,
                probeMaxAttempts=SOFT_RETRIES, waitingReason=""
            )
            result = self.probe.probe(asset)
            current_after_probe = self.store.run_snapshot(run_id)
            if self.stop_event.is_set() or not current_after_probe or current_after_probe.get("state") == "STOPPED":
                self._trace("INFO", "Probe result discarded because audit run was replaced/stopped", event=event_key, asset=asset.get("assetKey"))
                return {"ok": False, "hard": False, "infra": True, "reason": "RUN_REPLACED"}
            reason = str(result.get("reason") or "")
            infra = bool(result.get("infra")) or _infra_failure_reason(reason)
            hard = bool(result.get("hard")) or _hard_media_failure_reason(reason)
            self._diag(lastProbeResult=reason or ("PLAYING_TIME_ADVANCED" if result.get("ok") else "UNKNOWN"))

            if infra:
                infra_attempt += 1
                self._note_event_evidence("infra", reason)
                result["infra"] = True; result["infraAttempt"] = infra_attempt
                # Persist raw infrastructure evidence, but record_probe guarantees it
                # cannot alter runtime state or canonical validity.
                self._write(
                    "persist audit infrastructure probe evidence", "record_probe",
                    run_id, event_key, asset, max(1, media_attempt + 1), result, self.probe.browser,
                    run_id=run_id, ordinal=int(self.current.get("ordinal") or 0), event_key=event_key,
                    pending_phase="PROBE_COMPLETE_WAITING_DB",
                    pending_note=f"Audit infrastructure result ({reason}); waiting for serialized DB writer"
                )
                if infra_attempt >= INFRA_RETRIES:
                    self._diag(phase="DEFERRED_INFRA", waitingReason=f"Audit infrastructure failed {infra_attempt}/{INFRA_RETRIES} independent attempts: {reason}")
                    self._trace("WARN", "Probe infrastructure exhausted; media remains non-failed and event may defer", asset=asset.get("assetKey"), reason=reason, attempts=infra_attempt)
                    result["infraExhausted"] = True
                    return result
                self._diag(phase="RESTARTING_PROBE_INFRA", waitingReason=f"Restarting Chrome after infrastructure failure {infra_attempt}/{INFRA_RETRIES}: {reason}")
                self.probe.restart()
                time.sleep(random.uniform(1.0, 2.5))
                continue

            media_attempt += 1
            if hard:
                result["hard"] = True
                self._note_event_evidence("hard", reason)
            elif not result.get("ok"):
                self._note_event_evidence("soft", reason)

            self._write(
                "persist canonical browser probe result", "record_probe",
                run_id, event_key, asset, media_attempt, result, self.probe.browser,
                run_id=run_id, ordinal=int(self.current.get("ordinal") or 0), event_key=event_key,
                pending_phase="PROBE_COMPLETE_WAITING_DB",
                pending_note=f"{str(tier or asset.get('tier') or '').upper()} probe complete ({reason or 'result'}); waiting for serialized DB writer"
            )
            self._trace(
                "INFO" if result.get("ok") else "WARN",
                f"{str(tier or asset.get('tier') or '').upper()} probe {'PASS' if result.get('ok') else ('HARD FAIL' if hard else 'INCONCLUSIVE')}",
                asset=asset.get("assetKey"), provider=asset.get("provider"), reason=reason, attempt=media_attempt
            )
            last = result
            if result.get("ok") or hard:
                return result
            if media_attempt >= SOFT_RETRIES:
                result["inconclusive"] = True
                return result

            # A second soft-negative observation must be independent: throw away
            # this Chrome session, wait a small jittered interval, then retry.
            self._diag(phase="SOFT_RETRY_FRESH_BROWSER", waitingReason=f"Soft negative {media_attempt}/{SOFT_RETRIES}; recreating Chrome before independent retry")
            self.probe.restart()
            time.sleep(random.uniform(1.5, 3.5))
        return last or {"ok": False, "hard": False, "infra": True, "reason": "NO_RESULT"}

    def _select_one(self, run_id, event_key, candidates, *, tier="", tested=None):
        candidates=list(candidates)
        tested=tested if tested is not None else set()

        def runtime_rank(a):
            state=str(a.get("runtimeState") or "").upper()
            if state=="PLAYED":
                return 0
            if state=="FAILED":
                return 2
            return 1

        candidates.sort(key=lambda a:(
            runtime_rank(a),
            0 if str(a.get("validationState") or "").upper()=="VERIFIED" else 1,
            -float(a.get("durationSeconds") or 0),str(a.get("assetKey")),
        ))
        available=[a for a in candidates if a.get("assetKey") not in tested]
        retained=None
        for idx,asset in enumerate(available,1):
            was_recent_playable=_recent_playable(asset)
            tested.add(asset.get("assetKey"))
            result=self._probe_candidate(
                run_id,event_key,asset,tier=tier or asset.get("tier") or "",
                index=idx,count=len(available)
            )
            if result.get("ok"):
                return asset
            if (
                was_recent_playable
                and not result.get("hard")
                and _transient_media_failure_reason(result.get("reason"))
                and retained is None
            ):
                retained=dict(asset)
                retained["_selectionEvidence"]="RECENT_PLAYBACK_RETAINED"
                retained["_currentProbeWarning"]=str(result.get("reason") or "")
        if retained:
            self._diag(
                lastProbeResult=f"RETAINED_PLAYABLE_AFTER_TRANSIENT_{retained.get('_currentProbeWarning') or 'FAILURE'}",
                waitingReason=""
            )
            self._trace(
                "WARN",
                f"{str(tier or retained.get('tier') or '').upper()} retained from recent PLAYED evidence after transient audit failure",
                asset=retained.get("assetKey"),reason=retained.get("_currentProbeWarning")
            )
            return retained
        return None


    @staticmethod
    def _plan_candidate(item):
        if not isinstance(item, dict):
            return None
        key = str(item.get("assetKey") or HistoryRepository.asset_key_for(item) or "")
        if not key:
            return None
        url = _asset_url(item, str(item.get("canonicalUrl") or ""))
        return {
            "assetKey": key,
            "provider": str(item.get("provider") or item.get("source") or ""),
            "providerMediaId": str(item.get("providerMediaId") or item.get("videoId") or item.get("youtubeId") or ""),
            "title": str(item.get("title") or item.get("name") or key),
            "durationSeconds": (lambda v: (float(v) if str(v or "").replace(".", "", 1).isdigit() else 0.0))(item.get("durationSeconds") or item.get("duration") or 0),
            "validationState": str(item.get("validationState") or ""),
            "runtimeState": str(item.get("runtimeCatalogState") or item.get("runtimeState") or ""),
            "runtimeSuccessAt": float(item.get("runtimeSuccessAt") or 0),
            "runtimeFailureAt": float(item.get("runtimeFailureAt") or 0),
            "runtimeFailureReason": str(item.get("runtimeFailureReason") or ""),
            "associationState": "ASSIGNED",
            "associationMethod": str(item.get("associationMethod") or "PRODUCTION_PLAYBACK_PLAN"),
            "url": url,
            "youtubeId": _youtube_id(item, url),
            "tier": _tier(item),
            "item": item,
        }

    def _production_plan(self, item):
        league = str(item["league"] or "").upper()
        query = urlencode({"date": item["event_date"], "league": league, "eventId": item["event_id"]})
        req = Request(
            MAIN_API + "/api/history/event/media?" + query,
            headers={"User-Agent": f"SportsBigBoard-CanonicalAudit/{APP_VERSION}-{AUDIT_GENERATION}"}
        )
        try:
            with urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            plan = payload.get("plan") if isinstance(payload, dict) else {}
            return {"ok": bool(payload.get("ok", True)), "plan": plan or {}, "reason": "", "compatibility": False}
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                payload = {}
            raw_reason = str(payload.get("error") or f"HTTP_{exc.code}")
            if raw_reason in {"BAD_HISTORY_EVENT", "HISTORY_EVENT_NOT_FOUND"} and _special_event_league(league):
                return {
                    "ok": False, "plan": {}, "reason": "ENDPOINT_UNSUPPORTED_SPECIAL_EVENT",
                    "rawReason": raw_reason, "compatibility": True,
                }
            return {"ok": False, "plan": {}, "reason": raw_reason, "compatibility": False}
        except Exception as exc:
            return {"ok": False, "plan": {}, "reason": f"PRODUCTION_PLAN_TRANSPORT_{type(exc).__name__.upper()}", "message": str(exc), "infra": True, "compatibility": False}

    def _load_assets_with_production_parity(self, item):
        self._db_op("read normalized event media")
        direct = self.store.event_assets(item["canonical_event_key"])
        self._db_recovered()
        self._diag(dbAssetCount=len(direct))

        self._diag(lastOperation="load production playback plan")
        prod = self._production_plan(item)
        plan = prod.get("plan") or {}
        media = plan.get("media") or []
        playable = plan.get("playable") or []
        production_state = "OK" if prod.get("ok") else (prod.get("reason") or "UNAVAILABLE")
        self._diag(
            productionMediaCount=len(media), productionPlayableCount=len(playable),
            productionPlanState=production_state,
            productionCompatibility=bool(prod.get("compatibility"))
        )
        if prod.get("compatibility"):
            self._note_event_evidence("compatibility", production_state)
        if prod.get("infra"):
            self._note_event_evidence("infra", production_state)

        merged = {str(a.get("assetKey") or ""): dict(a) for a in direct if a.get("assetKey")}
        for raw in media:
            candidate = self._plan_candidate(raw)
            if not candidate:
                continue
            key = candidate["assetKey"]
            if key in merged:
                # Production plan carries browser-facing transport fields. Keep the
                # normalized DB relationship metadata while filling any missing transport.
                for field in ("url", "youtubeId", "title", "tier", "provider", "validationState", "runtimeState"):
                    if not merged[key].get(field) and candidate.get(field):
                        merged[key][field] = candidate[field]
            else:
                merged[key] = candidate

        self._trace(
            "INFO", "Production-plan parity loaded",
            event=item["canonical_event_key"], dbAssets=len(direct),
            productionMedia=len(media), productionPlayable=len(playable),
            productionState=self.snapshot().get("productionPlanState")
        )
        return list(merged.values()), prod

    def _discover_preferred(self, run, item, pass_number=1):
        league = str(item["league"] or "").upper()
        body = _jdumps({
            "date": item["event_date"], "league": league,
            "eventId": item["event_id"], "force": True
        }).encode("utf-8")
        req = Request(
            MAIN_API + "/api/history/event/discover", data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"SportsBigBoard-CanonicalAudit/{APP_VERSION}-{AUDIT_GENERATION}"
            }
        )
        self._diag(
            discoveryPass=pass_number, discoveryMaxPasses=DISCOVERY_PASSES,
            discoveryResult="REQUESTING", waitingReason=""
        )
        self._trace("INFO", f"Targeted discovery pass {pass_number}/{DISCOVERY_PASSES}", event=item["canonical_event_key"])
        while not self.stop_event.is_set():
            self._db_op("read exact run state before targeted discovery")
            current = self.store.run_snapshot(int(run["id"]))
            self._db_recovered()
            if self.stop_event.is_set() or not current or current["state"] in {"STOPPED"}:
                return {"ok": False, "reason": "RUN_REPLACED"}
            if current["state"] == "PAUSED":
                self._diag(phase="PAUSED", waitingReason="Operator paused canonical audit")
                time.sleep(1)
                continue
            try:
                # Rehydration is intentionally serialized even when media probes run
                # in parallel. This prevents a worker pool from stampeding the main
                # discovery backend or amplifying SQLite writer contention.
                with DISCOVERY_SEMAPHORE:
                    with urlopen(req, timeout=DISCOVERY_HTTP_TIMEOUT_SECONDS) as resp:
                        payload = json.loads(resp.read().decode("utf-8"))
                # The request may have been in flight when RESET/START/STOP retired
                # this worker. Verify the exact run still exists before accepting it.
                current_after_request = self.store.run_snapshot(int(run["id"]))
                if self.stop_event.is_set() or not current_after_request or current_after_request.get("state") == "STOPPED":
                    self._trace("INFO", "Discovery response discarded because audit run was replaced/stopped", event=item["canonical_event_key"], passNumber=pass_number)
                    return {"ok": False, "reason": "RUN_REPLACED"}
                result = {"ok": bool(payload.get("ok")), "payload": payload, "reason": str(payload.get("error") or "")}
                self._diag(discoveryResult="OK" if result["ok"] else (result["reason"] or "EMPTY"))
                return result
            except HTTPError as exc:
                try:
                    payload = json.loads(exc.read().decode("utf-8"))
                except Exception:
                    payload = {}
                if exc.code == 423 or payload.get("error") == "SEARCH_PAUSED_BY_PRIORITY":
                    note = "Playback Priority is active; deterministic queue is waiting on this same event."
                    self._diag(phase="WAITING_DISCOVERY_PRIORITY", waitingReason=note, discoveryResult="PRIORITY_BLOCKED")
                    try:
                        self._db_op("persist discovery priority wait")
                        self._write(
                            "persist discovery priority wait", "queue_phase",
                            run["id"], item["ordinal"], "WAITING_DISCOVERY_PRIORITY", note,
                            run_id=int(run["id"]), ordinal=int(item["ordinal"]), event_key=item["canonical_event_key"]
                        )
                        self._db_recovered()
                    except sqlite3.OperationalError:
                        pass
                    time.sleep(DISCOVERY_RETRY_SECONDS)
                    continue
                reason = str(payload.get("error") or f"HTTP_{exc.code}")
                if reason in {"BAD_HISTORY_EVENT", "HISTORY_EVENT_NOT_FOUND"} and _special_event_league(league):
                    reason = "DISCOVERY_ENDPOINT_UNSUPPORTED_SPECIAL_EVENT"
                    self._note_event_evidence("compatibility", reason)
                self._diag(discoveryResult=reason)
                if exc.code in {400, 404}:
                    return {"ok": False, "reason": reason, "compatibility": reason.endswith("UNSUPPORTED_SPECIAL_EVENT")}
                # R11 bounded rehydration repair: one non-priority HTTP failure
                # consumes this discovery pass. The outer DISCOVERY_PASSES loop
                # owns retry count so a single game can never hold the entire
                # deterministic audit queue forever.
                self._diag(waitingReason="Discovery HTTP failure; continuing bounded rehydration")
                self._trace(
                    "WARN", f"Targeted discovery pass {pass_number}/{DISCOVERY_PASSES} HTTP failure; advancing bounded retry",
                    event=item["canonical_event_key"], reason=reason
                )
                return {"ok": False, "reason": reason}
            except (URLError, TimeoutError) as exc:
                reason = f"DISCOVERY_TRANSPORT_{type(exc).__name__.upper()}"
                self._note_event_evidence("infra", reason)
                self._diag(
                    discoveryResult=f"{type(exc).__name__}",
                    waitingReason="Discovery transport timed out; continuing bounded rehydration"
                )
                self._trace(
                    "WARN", f"Targeted discovery pass {pass_number}/{DISCOVERY_PASSES} transport failure; advancing bounded retry",
                    event=item["canonical_event_key"], reason=reason
                )
                return {"ok": False, "reason": reason}
        return {"ok": False, "reason": "WORKER_STOPPED"}

    def audit_event(self, run, item):
        run_id = int(run["id"])
        event_key = item["canonical_event_key"]
        self._reset_event_evidence()
        self._db_op("set LOAD_MEDIA phase")
        self._write("set LOAD_MEDIA phase", "queue_phase", run_id, item["ordinal"], "LOAD_MEDIA", run_id=run_id, ordinal=int(item["ordinal"]), event_key=event_key)
        self._db_recovered()
        self._diag(phase="LOAD_MEDIA", progress=True)

        assets, production = self._load_assets_with_production_parity(item)
        buckets = {tier: [a for a in assets if a["tier"] == tier] for tier in ("gold", "green", "extended", "blue")}
        self._diag(
            candidateCounts={k: len(v) for k, v in buckets.items()},
            lastOperation="classify production + normalized candidates"
        )
        selected = {"gold": None, "green": None, "extended": None, "blue": []}
        tested = set()

        # Supplemental Gold is bounded to one canonical candidate.
        if buckets["gold"]:
            self._db_op("set TEST_GOLD phase")
            self._write("set TEST_GOLD phase", "queue_phase", run_id, item["ordinal"], "TEST_GOLD", run_id=run_id, ordinal=int(item["ordinal"]), event_key=event_key)
            self._db_recovered()
            self._diag(phase="TEST_GOLD")
            selected["gold"] = self._select_one(run_id, event_key, buckets["gold"], tier="GOLD", tested=tested)

        # Verify both preferred tiers when candidates already exist.
        for tier in ("green", "extended"):
            if buckets[tier]:
                phase = "TEST_PURPLE" if tier == "extended" else "TEST_GREEN"
                self._db_op(f"set {phase} phase")
                self._write(f"set {phase} phase", "queue_phase", run_id, item["ordinal"], phase, run_id=run_id, ordinal=int(item["ordinal"]), event_key=event_key)
                self._db_recovered()
                self._diag(phase=phase)
                selected[tier] = self._select_one(
                    run_id, event_key, buckets[tier],
                    tier="PURPLE" if tier == "extended" else "GREEN", tested=tested
                )

        # R10 policy: one healthy Green OR Purple is enough preferred recap coverage.
        # Only rehydrate when no preferred recap candidate survives canonical playback.
        discovery_reason = ""
        if not selected["green"] and not selected["extended"]:
            for pass_number in range(1, DISCOVERY_PASSES + 1):
                phase = "TARGETED_REHYDRATION"
                self._db_op("set TARGETED_REHYDRATION phase")
                self._write(f"set {phase} phase", "queue_phase", run_id, item["ordinal"], phase, run_id=run_id, ordinal=int(item["ordinal"]), event_key=event_key)
                self._db_recovered()
                self._diag(phase=phase)
                discovery = self._discover_preferred(run, item, pass_number)
                discovery_reason = discovery.get("reason") or ""
                if discovery_reason in {"RUN_STOPPED", "RUN_REPLACED", "WORKER_STOPPED"}:
                    return {"health": "SKIPPED", "note": discovery_reason}
                if not discovery.get("ok") and discovery_reason in {"BAD_HISTORY_EVENT", "HISTORY_EVENT_NOT_FOUND", "DISCOVERY_ENDPOINT_UNSUPPORTED_SPECIAL_EVENT"}:
                    break
                if DISCOVERY_SETTLE_SECONDS:
                    self._diag(phase="DISCOVERY_SETTLE", waitingReason=f"Waiting {DISCOVERY_SETTLE_SECONDS:g}s for production catalog commit")
                    time.sleep(DISCOVERY_SETTLE_SECONDS)

                assets, production = self._load_assets_with_production_parity(item)
                new_buckets = {tier: [a for a in assets if a["tier"] == tier] for tier in ("green", "extended", "blue", "gold")}
                buckets = new_buckets
                for tier in ("green", "extended"):
                    if selected[tier]:
                        continue
                    fresh = [a for a in new_buckets[tier] if a.get("assetKey") not in tested]
                    if fresh:
                        phase = "RETEST_PURPLE" if tier == "extended" else "RETEST_GREEN"
                        self._db_op(f"set {phase} phase")
                        self._write(f"set {phase} phase", "queue_phase", run_id, item["ordinal"], phase, run_id=run_id, ordinal=int(item["ordinal"]), event_key=event_key)
                        self._db_recovered()
                        self._diag(phase=phase)
                        selected[tier] = self._select_one(
                            run_id, event_key, fresh,
                            tier="PURPLE" if tier == "extended" else "GREEN", tested=tested
                        )
                if selected["green"] or selected["extended"]:
                    break

        preferred = bool(selected["green"] or selected["extended"])
        if not preferred:
            self._db_op("set BLUE_FALLBACK phase")
            self._write("set BLUE_FALLBACK phase", "queue_phase", run_id, item["ordinal"], "BLUE_FALLBACK", run_id=run_id, ordinal=int(item["ordinal"]), event_key=event_key)
            self._db_recovered()
            self._diag(phase="BLUE_FALLBACK")
            blue_candidates = [a for a in buckets.get("blue", []) if a.get("assetKey") not in tested]
            blue_candidates.sort(key=lambda a: (-float(a.get("durationSeconds") or 0), str(a.get("assetKey"))))
            for idx, asset in enumerate(blue_candidates, 1):
                tested.add(asset.get("assetKey"))
                result = self._probe_candidate(
                    run_id, event_key, asset, tier="BLUE",
                    index=idx, count=len(blue_candidates)
                )
                if result.get("ok"):
                    selected["blue"].append(asset)
                elif _recent_playable(asset) and not result.get("hard") and _transient_media_failure_reason(result.get("reason")):
                    retained_blue=dict(asset)
                    retained_blue["_selectionEvidence"]="RECENT_PLAYBACK_RETAINED"
                    retained_blue["_currentProbeWarning"]=str(result.get("reason") or "")
                    selected["blue"].append(retained_blue)
                    self._trace(
                        "WARN","BLUE retained from recent PLAYED evidence after transient audit failure",
                        asset=asset.get("assetKey"),reason=result.get("reason")
                    )
                if len(selected["blue"]) >= BLUE_FALLBACK_TARGET:
                    break

        evidence = getattr(self, "event_evidence", {"infra": [], "soft": [], "hard": [], "compatibility": []})
        if preferred:
            health = "HEALTHY"
            rehydration_state = ""
            rehydration_reason = ""
        elif selected["blue"] or selected["gold"]:
            health = "DEGRADED"
            rehydration_state = "PREFERRED_MEDIA_REQUIRED"
            rehydration_reason = "No healthy Green/Purple; canonical fallback remains playable"
        elif evidence.get("infra"):
            # Infrastructure uncertainty cannot change canonical health/package.
            note = "Audit infrastructure inconclusive; media/package left untouched: " + ", ".join(evidence["infra"][:5])
            if discovery_reason:
                note += f"; discovery={discovery_reason}"
            return {"health": "INCONCLUSIVE", "note": note, "deferred": True}
        elif evidence.get("soft"):
            # Multiple soft failures, even from independent Chrome sessions, are
            # insufficient to declare the website media dead. Keep existing package.
            note = "Independent soft-negative probes remain inconclusive; canonical package left untouched: " + ", ".join(evidence["soft"][:5])
            return {"health": "INCONCLUSIVE", "note": note}
        elif not assets and evidence.get("compatibility"):
            note = "Special-event production/discovery endpoint does not support this event identity; normalized catalog has no certifiable asset yet"
            return {"health": "INCONCLUSIVE", "note": note}
        elif assets:
            # Reaching here means the available assets produced only definitive hard
            # failures. This is the only path that may declare UNPLAYABLE.
            health = "UNPLAYABLE"
            rehydration_state = "PREFERRED_MEDIA_REQUIRED"
            rehydration_reason = "All assigned media produced definitive hard playback failures"
        else:
            health = "NO_MEDIA"
            rehydration_state = "PREFERRED_MEDIA_REQUIRED"
            rehydration_reason = "No assigned GAME media exists after successful discovery checks"
        if not preferred and discovery_reason:
            rehydration_reason = f"{rehydration_reason}; discovery={discovery_reason}".strip("; ")

        current_run = self.store.run_snapshot(run_id)
        self._db_recovered()
        if not current_run or current_run.get("state") == "STOPPED":
            return {"health": "SKIPPED", "note": "RUN_STOPPED_BEFORE_CANONICALIZE"}

        # Multiple lanes may probe adjacent games concurrently, but canonical package
        # writes remain strictly ordinal. This preserves the audit's deterministic
        # website-wide sequence while still overlapping expensive browser/network work.
        commit_wait_announced = False
        while not self.stop_event.is_set() and not self.store.commit_turn_ready(run_id, int(item["ordinal"])):
            current_run = self.store.run_snapshot(run_id)
            if not current_run or current_run.get("state") == "STOPPED":
                return {"health": "SKIPPED", "note": "RUN_STOPPED_BEFORE_CANONICALIZE"}
            self._diag(phase="WAITING_COMMIT_ORDER", waitingReason="Earlier queue ordinal is still being certified")
            if not commit_wait_announced:
                try:
                    self._write("set WAITING_COMMIT_ORDER phase", "queue_phase", run_id, item["ordinal"], "WAITING_COMMIT_ORDER", "Earlier queue ordinal is still being certified", run_id=run_id, ordinal=int(item["ordinal"]), event_key=event_key)
                    commit_wait_announced = True
                except AuditRunReplaced:
                    return {"health": "SKIPPED", "note": "RUN_REPLACED_BEFORE_CANONICALIZE"}
            time.sleep(0.5)
        if self.stop_event.is_set():
            return {"health": "SKIPPED", "note": "WORKER_STOPPED_BEFORE_CANONICALIZE"}
        self._diag(waitingReason="")

        self._db_op("canonicalize shared event-media package")
        self._write("set CANONICALIZE phase", "queue_phase", run_id, item["ordinal"], "CANONICALIZE", run_id=run_id, ordinal=int(item["ordinal"]), event_key=event_key)
        self._db_recovered()
        self._diag(phase="CANONICALIZE")
        package = self._write(
            "canonicalize shared event-media package", "canonicalize",
            run_id, item, selected, health, rehydration_state, rehydration_reason,
            run_id=run_id, ordinal=int(item["ordinal"]), event_key=event_key,
            pending_phase="CANONICAL_PACKAGE_WAITING_DB",
            pending_note="Canonical package is ready; waiting for serialized DB writer"
        )
        self._db_recovered()
        note = (
            f"canonical package: green={bool(selected['green'])} "
            f"purple={bool(selected['extended'])} gold={bool(selected['gold'])} "
            f"blue={len(selected['blue'])} • productionMedia={self.snapshot().get('productionMediaCount',0)} "
            f"productionPlayable={self.snapshot().get('productionPlayableCount',0)}"
        )
        return {"health": health, "note": note, "package": package}


class AuditStatusCache(threading.Thread):
    """Small background DB snapshot so /status itself performs zero SQLite reads."""
    daemon = True

    def __init__(self, store):
        super().__init__(name="canonical-media-audit-status-cache")
        self.store = store
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.data = {"run": None, "summary": {}, "newestEligibleDate": "", "storageReadError": "", "updatedAt": 0.0, "lastAttemptAt": 0.0}

    def request_refresh(self):
        self.wake_event.set()

    def snapshot(self):
        with self.lock:
            data = dict(self.data)
        data["ageSeconds"] = max(0.0, round(_now() - float(data.get("updatedAt") or _now()), 1))
        return data

    def refresh(self):
        try:
            data = {
                "run": self.store.run_snapshot(),
                "summary": self.store.summary(),
                "newestEligibleDate": self.store.newest_eligible_date(),
                "storageReadError": "",
                "updatedAt": _now(),
                "lastAttemptAt": _now(),
            }
        except Exception as exc:
            with self.lock:
                data = dict(self.data)
            # Preserve updatedAt as the last GOOD snapshot time. A cache refresh
            # failure is operator telemetry, not a fresh status snapshot.
            data["storageReadError"] = f"{type(exc).__name__}: {exc}"
            data["lastAttemptAt"] = _now()
        with self.lock:
            self.data = data

    def run(self):
        self.refresh()
        while not self.stop_event.is_set():
            self.wake_event.wait(STATUS_CACHE_REFRESH_SECONDS)
            self.wake_event.clear()
            if not self.stop_event.is_set():
                self.refresh()

    def stop(self):
        self.stop_event.set(); self.wake_event.set()


STORE = AuditStore(DB_PATH)
# Startup recovery is maintenance, never a service-readiness prerequisite.  The
# audit API must be able to answer heartbeat/status even when the shared SQLite
# writer is temporarily owned by the main Sports Big Board backend.
PLAYABLE_RECOVERY = {"state":"PENDING","restoredAssets":0,"requeuedOrdinals":[]}
ALTERNATE_RECOVERY = {"state":"PENDING","restoredAssets":0,"requeuedOrdinals":[]}
RECOVERY = {"state":"PENDING","runId":0,"requeued":0,"recoveredPackages":0}
STARTUP_RECOVERY = {"state":"PENDING","stage":"","attempt":0,"lastError":"","updatedAt":_now()}
STATUS_CACHE = AuditStatusCache(STORE)
STATUS_CACHE.start()
DB_WRITER = SerializedAuditDbWriter(STORE)
DB_WRITER.start()
WORKER_CONTROL_LOCK = threading.RLock()
PROBES = []
WORKERS = []
STARTUP_RECOVERY_THREAD = None

def _spawn_workers(reason="service start"):
    global PROBES, WORKERS
    PROBES = []
    WORKERS = []
    for lane in range(1, AUDIT_WORKER_COUNT + 1):
        probe = BrowserProbe()
        worker = CanonicalAuditWorker(STORE, probe, DB_WRITER, worker_lane=lane)
        PROBES.append(probe)
        WORKERS.append(worker)
        worker.start()
        worker._trace("INFO", f"Canonical audit lane {lane}/{AUDIT_WORKER_COUNT} spawned: {reason}")
    return WORKERS


def _retire_workers(reason="operator control"):
    global WORKERS, PROBES
    old = list(WORKERS)
    if not old:
        return {"hadWorkers": False, "joined": True, "workers": 0}
    for worker in old:
        try:
            worker._trace("WARN", f"Canonical audit worker retired: {reason}")
        except Exception:
            pass
        worker.stop()
    deadline = time.time() + CONTROL_WORKER_JOIN_SECONDS
    while any(w.is_alive() for w in old) and time.time() < deadline:
        time.sleep(0.05)
    joined = all(not w.is_alive() for w in old)
    return {"hadWorkers": True, "joined": joined, "workers": len(old)}


def _worker_status_payload():
    rows = []
    for worker in WORKERS:
        rows.append({
            "lane": worker.worker_lane,
            "alive": worker.is_alive(),
            "current": dict(worker.current or {}),
            "lastError": worker.last_error,
            "diagnostics": worker.snapshot(),
        })
    active = [r for r in rows if r.get("current") and r["current"].get("ordinal")]
    primary = min(active, key=lambda r: int(r["current"].get("ordinal") or 10**9)) if active else (rows[0] if rows else {"alive": False, "current": {}, "lastError": "", "diagnostics": {}})
    return primary, rows

def _run_startup_recovery():
    global PLAYABLE_RECOVERY, ALTERNATE_RECOVERY, RECOVERY, STARTUP_RECOVERY
    retry_seconds = max(1.0, float(os.environ.get("SBB_MEDIA_AUDIT_STARTUP_RECOVERY_RETRY_SECONDS", "3")))
    max_wait_seconds = max(30.0, float(os.environ.get("SBB_MEDIA_AUDIT_STARTUP_RECOVERY_MAX_WAIT_SECONDS", "300")))
    stages = [
        ("PLAYABLE_EVIDENCE", "PLAYABLE_RECOVERY", STORE.recover_transient_playable_quarantines),
        ("HEALTHY_ALTERNATIVES", "ALTERNATE_RECOVERY", STORE.recover_healthy_audit_alternatives),
        ("QUEUE_EXCEPTIONS", "RECOVERY", STORE.recover_exception_failures),
    ]
    for stage, target, fn in stages:
        started = _now(); attempt = 0
        while True:
            attempt += 1
            STARTUP_RECOVERY = {
                "state":"RUNNING", "stage":stage, "attempt":attempt,
                "lastError":"", "updatedAt":_now(),
            }
            try:
                result = dict(fn() or {})
                result["state"] = "DONE"
                result["attempts"] = attempt
                if target == "PLAYABLE_RECOVERY":
                    PLAYABLE_RECOVERY = result
                elif target == "ALTERNATE_RECOVERY":
                    ALTERNATE_RECOVERY = result
                else:
                    RECOVERY = result
                break
            except Exception as exc:
                if _is_db_locked(exc):
                    STARTUP_RECOVERY = {
                        "state":"WAITING_DATABASE_LOCK", "stage":stage, "attempt":attempt,
                        "lastError":f"{type(exc).__name__}: {exc}", "updatedAt":_now(),
                    }
                    # Startup recovery is deliberately fail-soft.  Heartbeat, status,
                    # and workers remain alive while this maintenance pass waits.
                    if _now() - started >= max_wait_seconds:
                        STARTUP_RECOVERY["state"] = "WAITING_DATABASE_LOCK_LONG"
                    # Never give up on queue-restart recovery: old ACTIVE ordinals
                    # must eventually be returned to PENDING, but this retry runs
                    # entirely off the heartbeat/service-readiness path.
                    time.sleep(retry_seconds)
                    continue
                traceback.print_exc()
                failed = {
                    "state":"ERROR", "attempts":attempt,
                    "error":f"{type(exc).__name__}: {exc}",
                }
                if target == "PLAYABLE_RECOVERY":
                    PLAYABLE_RECOVERY = failed
                elif target == "ALTERNATE_RECOVERY":
                    ALTERNATE_RECOVERY = failed
                else:
                    RECOVERY = failed
                break
    STARTUP_RECOVERY = {"state":"DONE","stage":"COMPLETE","attempt":0,"lastError":"","updatedAt":_now()}
    try:
        STATUS_CACHE.request_refresh()
    except Exception:
        pass
    if RECOVERY.get("requeued") and WORKERS:
        WORKERS[0]._trace(
            "WARN",
            f"Recovered {RECOVERY['requeued']} prior worker/infrastructure failures for deterministic retry",
            runId=RECOVERY.get("runId"),
        )


def _start_startup_recovery():
    global STARTUP_RECOVERY_THREAD
    STARTUP_RECOVERY_THREAD = threading.Thread(
        target=_run_startup_recovery,
        name="media-audit-startup-recovery",
        daemon=True,
    )
    STARTUP_RECOVERY_THREAD.start()
    return STARTUP_RECOVERY_THREAD


_spawn_workers("service start")
_start_startup_recovery()


def _json(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    origin = str(handler.headers.get("Origin") or "")
    if origin and (origin.endswith(".github.io") or origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1")):
        handler.send_header("Access-Control-Allow-Origin", origin)
    handler.send_header("Vary", "Origin")
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers(); handler.wfile.write(body)


def _body(handler, max_bytes=65536):
    length = min(max_bytes, int(handler.headers.get("Content-Length") or 0))
    return json.loads(handler.rfile.read(length).decode("utf-8") or "{}")


class Handler(BaseHTTPRequestHandler):
    server_version = "SportsBigBoardMediaAudit/" + APP_VERSION

    def log_message(self, fmt, *args):
        print("[media-audit-api] " + fmt % args, flush=True)

    def do_OPTIONS(self):
        self.send_response(204)
        origin = str(self.headers.get("Origin") or "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path); qs = parse_qs(parsed.query)
        try:
            if parsed.path == "/status":
                # Deliberately memory-only: the operator heartbeat must remain cheap
                # even when inventory/catalog SQLite reads are slow or contended.
                cached = STATUS_CACHE.snapshot()
                primary_worker, worker_rows = _worker_status_payload()
                browser_names = [getattr(p, "browser", "") for p in PROBES if getattr(p, "browser", "")]
                browser_errors = [getattr(p, "last_error", "") for p in PROBES if getattr(p, "last_error", "")]
                primary_worker = {
                    **primary_worker,
                    "recoveredExceptionFailures": RECOVERY,
                    "recoveredPlayableEvidence": PLAYABLE_RECOVERY,
                    "recoveredAlternatives": ALTERNATE_RECOVERY,
                }
                return _json(self, {
                    "ok": True, "version": APP_VERSION, "generation": AUDIT_GENERATION,
                    "canonical": True, "browserOwned": False, "probeUrl": PROBE_URL,
                    "timezone": AUDIT_TIMEZONE, "browser": browser_names[0] if browser_names else "",
                    "browserError": browser_errors[0] if browser_errors else "",
                    "storageReadError": cached.get("storageReadError", ""),
                    "statusCacheAgeSeconds": cached.get("ageSeconds", 0),
                    "workerCount": AUDIT_WORKER_COUNT, "workers": worker_rows, "worker": primary_worker,
                    "dbWriter": DB_WRITER.snapshot(),
                    "startupRecovery": dict(STARTUP_RECOVERY),
                    "run": cached.get("run"), "summary": cached.get("summary") or {},
                    "newestEligibleDate": cached.get("newestEligibleDate", "")
                })
            if parsed.path == "/inventory":
                return _json(self, {"ok": True, **STORE.inventory(limit=(qs.get("limit") or [100])[-1], offset=(qs.get("offset") or [0])[-1], league=(qs.get("league") or [""])[-1], health=(qs.get("health") or [""])[-1], search=(qs.get("search") or [""])[-1])})
            if parsed.path == "/event":
                event_key = str((qs.get("event") or [""])[-1])
                return _json(self, {"ok": True, **STORE.event_detail(event_key)})
            if parsed.path == "/rehydration.json":
                return _json(self, STORE.rehydration_manifest())
            if parsed.path == "/failures.csv":
                manifest = STORE.rehydration_manifest(); out = io.StringIO(); writer = csv.writer(out)
                writer.writerow(["date", "league", "eventId", "game", "health", "rehydrationState", "reason"])
                for g in manifest["games"]: writer.writerow([g["date"], g["league"], g["eventId"], g["game"], g["health"], g["rehydrationState"], g["reason"]])
                raw = out.getvalue().encode("utf-8")
                self.send_response(200)
                origin=str(self.headers.get("Origin") or "")
                if origin and (origin.endswith(".github.io") or origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1")):
                    self.send_header("Access-Control-Allow-Origin",origin)
                self.send_header("Vary","Origin"); self.send_header("Content-Type", "text/csv; charset=utf-8"); self.send_header("Content-Disposition", "attachment; filename=sports-big-board-media-audit-failures.csv"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw); return
            return _json(self, {"ok": False, "error": "NOT_FOUND"}, 404)
        except Exception as exc:
            traceback.print_exc(); return _json(self, {"ok": False, "error": "MEDIA_AUDIT_API_ERROR", "message": f"{type(exc).__name__}: {exc}"}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            body = _body(self)
            if parsed.path == "/start":
                # START replaces any previous worker/run atomically. A stale in-flight
                # discovery request from the old run can never coexist as authority.
                with WORKER_CONTROL_LOCK:
                    existing = STORE.active_run()
                    if existing and existing.get("state") in {"RUNNING", "PAUSED"}:
                        STORE.set_run_state("STOPPED")
                    retired = _retire_workers("new audit run requested")
                    run = STORE.start_run(body.get("mode") or "ALL", body.get("startDate") or "")
                    _spawn_workers("new audit run")
                    STATUS_CACHE.request_refresh()
                return _json(self, {"ok": True, "run": run, "workerReset": retired})
            if parsed.path == "/pause":
                run = STORE.set_run_state("PAUSED"); STATUS_CACHE.request_refresh(); return _json(self, {"ok": True, "run": run})
            if parsed.path == "/resume":
                run = STORE.set_run_state("RUNNING"); STATUS_CACHE.request_refresh(); return _json(self, {"ok": True, "run": run})
            if parsed.path == "/stop":
                with WORKER_CONTROL_LOCK:
                    run = STORE.set_run_state("STOPPED")
                    retired = _retire_workers("audit stopped")
                    STATUS_CACHE.request_refresh()
                    _spawn_workers("idle after stop")
                return _json(self, {"ok": True, "run": run, "workerReset": retired})
            if parsed.path == "/reset":
                with WORKER_CONTROL_LOCK:
                    existing = STORE.active_run()
                    if existing and existing.get("state") in {"RUNNING", "PAUSED"}:
                        STORE.set_run_state("STOPPED")
                    retired = _retire_workers("audit reset")
                    result = STORE.reset_run(recertify=bool(body.get("recertify")))
                    _spawn_workers("idle after reset")
                    STATUS_CACHE.request_refresh()
                return _json(self, {**result, "workerReset": retired, "run": None})
            return _json(self, {"ok": False, "error": "NOT_FOUND"}, 404)
        except Exception as exc:
            traceback.print_exc(); return _json(self, {"ok": False, "error": "MEDIA_AUDIT_API_ERROR", "message": f"{type(exc).__name__}: {exc}"}, 500)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Sports Big Board canonical Media Audit {AUDIT_GENERATION} listening on http://{HOST}:{PORT}", flush=True)
    print(f"Probe origin: {PROBE_URL}", flush=True)
    stop = threading.Event()
    def shutdown(_sig, _frame):
        stop.set(); _retire_workers("service shutdown"); DB_WRITER.stop(); STATUS_CACHE.stop(); threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown); signal.signal(signal.SIGINT, shutdown)
    try: server.serve_forever(poll_interval=0.5)
    finally: _retire_workers("service close"); DB_WRITER.stop(); STATUS_CACHE.stop(); server.server_close()


if __name__ == "__main__":
    main()

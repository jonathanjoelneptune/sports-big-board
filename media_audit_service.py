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
AUDIT_GENERATION = "R10"
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
AUDIT_TIMEZONE = os.environ.get("SBB_MEDIA_AUDIT_TIMEZONE", "America/Los_Angeles").strip() or "America/Los_Angeles"
try:
    AUDIT_TZ = ZoneInfo(AUDIT_TIMEZONE)
except Exception:
    AUDIT_TIMEZONE = "UTC"; AUDIT_TZ = timezone.utc

ASSIGNED = "ASSIGNED"
QUARANTINED = "QUARANTINED"
TERMINAL_QUEUE = {"DONE", "FAILED", "SKIPPED"}
INFRA_FAILURES = {"BROWSER_WORKER_ERROR","PROBE_PAGE_NOT_READY","PROBE_EXCEPTION","YOUTUBE_API_LOAD_ERROR","YOUTUBE_API_LOAD_TIMEOUT","INVALID_PROBE_RESULT","EMPTY_PROBE_RESULT"}
MANAGED_METHODS = {
    "CANONICAL_MEDIA_AUDIT",
    "MEDIA_AUDIT_FAILED",
    "MEDIA_AUDIT_SUPERSEDED",
    "MEDIA_AUDIT_BLUE_SUPPRESSED",
    "MEDIA_AUDIT_NON_CANONICAL",
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
    def __init__(self, db_path: Path):
        self.db_path = str(db_path)
        self.lock = threading.RLock()
        self.repo = HistoryRepository(self.db_path)
        self._init_schema()

    def connect(self, timeout=None):
        wait_ms = DB_BUSY_TIMEOUT_MS if timeout is None else max(1000, int(float(timeout) * 1000))
        conn = sqlite3.connect(self.db_path, timeout=wait_ms / 1000.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={wait_ms}")
        return conn

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
                    if mode == "FAILED" and (not pkg or str(pkg["health"]) not in {"DEGRADED", "UNPLAYABLE", "NO_MEDIA", "FAILED"}):
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

    def recover_exception_failures(self):
        """Requeue R9/R10 worker exceptions without erasing real media outcomes.

        Normal audit outcomes are written as DONE with HEALTHY/DEGRADED/UNPLAYABLE/
        NO_MEDIA. A queue row in FAILED with no canonical package is therefore an
        infrastructure/worker exception and is safe to retry in deterministic order.
        """
        now = _now()
        with self.lock, closing(self.connect()) as conn:
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
                "SELECT COUNT(*) FROM history_media_audit_queue WHERE run_id=? AND state IN ('DONE','FAILED','SKIPPED')",
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

    def next_queue_item(self, run_id: int):
        with self.lock, closing(self.connect()) as conn:
            # Never jump ahead of a lower ordinal non-terminal item.
            row = conn.execute(
                "SELECT * FROM history_media_audit_queue WHERE run_id=? AND state NOT IN ('DONE','FAILED','SKIPPED') ORDER BY ordinal ASC LIMIT 1",
                (run_id,),
            ).fetchone()
            if not row:
                return None
            now = _now()
            if row["state"] == "PENDING":
                conn.execute("UPDATE history_media_audit_queue SET state='ACTIVE',started_at=?,phase='STARTING' WHERE run_id=? AND ordinal=?", (now, run_id, row["ordinal"]))
                conn.execute("UPDATE history_media_audit_run SET current_ordinal=?,current_event_key=?,current_phase='STARTING',updated_at=? WHERE id=?", (row["ordinal"], row["canonical_event_key"], now, run_id))
                conn.commit()
                row = conn.execute("SELECT * FROM history_media_audit_queue WHERE run_id=? AND ordinal=?", (run_id, row["ordinal"])).fetchone()
            return dict(row)

    def queue_phase(self, run_id, ordinal, phase, note=""):
        now = _now()
        with self.lock, closing(self.connect()) as conn:
            conn.execute("UPDATE history_media_audit_queue SET phase=?,note=? WHERE run_id=? AND ordinal=?", (phase, str(note or "")[:1000], run_id, ordinal))
            conn.execute("UPDATE history_media_audit_run SET current_phase=?,updated_at=? WHERE id=?", (phase, now, run_id))
            conn.commit()

    def finish_queue_item(self, run_id, ordinal, health, note="", failed=False):
        now = _now()
        state = "FAILED" if failed else "DONE"
        with self.lock, closing(self.connect()) as conn:
            conn.execute("UPDATE history_media_audit_queue SET state=?,phase='COMPLETE',health=?,note=?,completed_at=? WHERE run_id=? AND ordinal=?", (state, health, str(note or "")[:1000], now, run_id, ordinal))
            processed = int(conn.execute("SELECT COUNT(*) FROM history_media_audit_queue WHERE run_id=? AND state IN ('DONE','FAILED','SKIPPED')", (run_id,)).fetchone()[0] or 0)
            conn.execute("UPDATE history_media_audit_run SET processed_games=?,updated_at=?,last_error=? WHERE id=?", (processed, now, str(note or "")[:1000] if failed else "", run_id))
            conn.commit()

    def complete_run_if_done(self, run_id):
        with self.lock, closing(self.connect()) as conn:
            remaining = int(conn.execute("SELECT COUNT(*) FROM history_media_audit_queue WHERE run_id=? AND state NOT IN ('DONE','FAILED','SKIPPED')", (run_id,)).fetchone()[0] or 0)
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
        now = _now()
        state = "PLAYED" if result.get("ok") else "FAILED"
        reason = str(result.get("reason") or ("PLAYING_TIME_ADVANCED" if result.get("ok") else "UNKNOWN"))[:500]
        with self.lock:
            # Canonical worker owns the result directly. Source identity is global, while
            # event identity lives in history_event_media; do not depend on provider JSON
            # redundantly carrying date/league/eventId.
            with closing(self.connect()) as conn:
                src=conn.execute("SELECT asset_json FROM history_source_media WHERE asset_key=?",(asset["assetKey"],)).fetchone()
                item=_jloads(src["asset_json"],{}) if src else {}
                if result.get("ok"):
                    item["runtimeState"]="playing-confirmed"; item["verifiedPlayable"]=True; item.pop("runtimeFailureReason",None)
                else:
                    item["runtimeState"]="failed"; item["verifiedPlayable"]=False; item["runtimeFailureReason"]=reason
                conn.execute(
                    "UPDATE history_source_media SET asset_json=?,validation_state=CASE WHEN ? THEN 'VERIFIED' ELSE validation_state END,verified_at=CASE WHEN ? THEN ? ELSE verified_at END,runtime_state=?,runtime_success_at=CASE WHEN ? THEN ? ELSE runtime_success_at END,runtime_failure_at=CASE WHEN ? THEN runtime_failure_at ELSE ? END,runtime_failure_reason=CASE WHEN ? THEN '' ELSE ? END,updated_at=? WHERE asset_key=?",
                    (_jdumps(item),1 if result.get("ok") else 0,1 if result.get("ok") else 0,now,state, 1 if result.get("ok") else 0, now, 1 if result.get("ok") else 0, now, 1 if result.get("ok") else 0, reason, now, asset["assetKey"]),
                )
                conn.execute(
                    "INSERT INTO history_media_verification(asset_key,verification_type,state,reason,details_json,verified_at,verification_version) VALUES(?,?,?,?,?,?,?)",
                    (asset["assetKey"], "CANONICAL_BROWSER", state, reason, _jdumps({"auditRunId": run_id, "generation": AUDIT_GENERATION, "browser": browser, "probeOrigin": PROBE_URL, "startupMs": result.get("startupMs"), "currentTimeDelta": result.get("currentTimeDelta")}), now, VERIFICATION_VERSION),
                )
                conn.execute(
                    "INSERT INTO history_media_audit_asset_result(run_id,canonical_event_key,asset_key,tier,attempt,state,reason,startup_ms,current_time_delta,browser,probe_origin,tested_at,details_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, event_key, asset["assetKey"], asset["tier"], attempt, state, reason, float(result.get("startupMs") or 0), float(result.get("currentTimeDelta") or 0), browser, PROBE_URL, now, _jdumps(result)),
                )
                conn.commit()
        return state

    def canonicalize(self, run_id, queue_item, selections, health, rehydration_state="", rehydration_reason=""):
        event_key = queue_item["canonical_event_key"]
        chosen = {k: (v or {}).get("assetKey", "") for k, v in selections.items() if k in {"gold", "green", "extended"}}
        blue_keys = [x["assetKey"] for x in selections.get("blue", [])]
        chosen_keys = {v for v in chosen.values() if v} | set(blue_keys)
        preferred = bool(chosen.get("green") or chosen.get("extended"))
        now = _now()
        with self.lock, closing(self.connect()) as conn:
            rows = conn.execute("SELECT asset_key,association_state,association_method FROM history_event_media WHERE canonical_event_key=? AND (association_state='ASSIGNED' OR association_method LIKE 'MEDIA_AUDIT_%' OR association_method='CANONICAL_MEDIA_AUDIT')", (event_key,)).fetchall()
            source_tiers = {}
            for r in conn.execute("SELECT asset_key,asset_json FROM history_source_media WHERE asset_key IN (SELECT asset_key FROM history_event_media WHERE canonical_event_key=?)", (event_key,)).fetchall():
                source_tiers[r["asset_key"]] = _tier(_jloads(r["asset_json"], {}))
            for row in rows:
                asset_key = row["asset_key"]
                tier = source_tiers.get(asset_key, "blue")
                if asset_key in chosen_keys:
                    state, method, evidence = ASSIGNED, "CANONICAL_MEDIA_AUDIT", f"canonical {tier} selected by {AUDIT_GENERATION} run {run_id}"
                else:
                    runtime = conn.execute("SELECT runtime_state FROM history_source_media WHERE asset_key=?", (asset_key,)).fetchone()
                    runtime_failed = bool(runtime and str(runtime["runtime_state"] or "").upper() == "FAILED")
                    if runtime_failed:
                        method, evidence = "MEDIA_AUDIT_FAILED", f"failed canonical playback certification in run {run_id}"
                    elif tier == "blue" and preferred:
                        method, evidence = "MEDIA_AUDIT_BLUE_SUPPRESSED", "Blue suppressed because healthy Green/Purple canonical media exists"
                    elif tier in {"gold", "green", "extended"}:
                        method, evidence = "MEDIA_AUDIT_SUPERSEDED", f"healthy/nonselected duplicate {tier} outside canonical package"
                    else:
                        method, evidence = "MEDIA_AUDIT_NON_CANONICAL", "outside canonical verified package"
                    state = QUARANTINED
                conn.execute("UPDATE history_event_media SET association_state=?,association_method=?,association_evidence=?,updated_at=? WHERE canonical_event_key=? AND asset_key=?", (state, method, evidence, now, event_key, asset_key))
            conn.execute(
                """INSERT INTO history_media_canonical_package(canonical_event_key,audit_run_id,health,gold_asset_key,green_asset_key,purple_asset_key,blue_asset_keys_json,preferred_complete,preferred_playable,rehydration_state,rehydration_reason,certified_at,worker_generation,details_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(canonical_event_key) DO UPDATE SET audit_run_id=excluded.audit_run_id,health=excluded.health,gold_asset_key=excluded.gold_asset_key,green_asset_key=excluded.green_asset_key,purple_asset_key=excluded.purple_asset_key,blue_asset_keys_json=excluded.blue_asset_keys_json,preferred_complete=excluded.preferred_complete,preferred_playable=excluded.preferred_playable,rehydration_state=excluded.rehydration_state,rehydration_reason=excluded.rehydration_reason,certified_at=excluded.certified_at,worker_generation=excluded.worker_generation,details_json=excluded.details_json""",
                (event_key, run_id, health, chosen.get("gold", ""), chosen.get("green", ""), chosen.get("extended", ""), _jdumps(blue_keys), 1 if chosen.get("green") and chosen.get("extended") else 0, 1 if preferred else 0, rehydration_state, rehydration_reason, now, AUDIT_GENERATION, _jdumps({"selections": {"gold": chosen.get("gold", ""), "green": chosen.get("green", ""), "purple": chosen.get("extended", ""), "blue": blue_keys}})),
            )
            conn.commit()
        return {"health": health, "preferredPlayable": preferred, "selected": chosen, "blue": blue_keys}

    def inventory(self, limit=100, offset=0, league="", health="", search=""):
        limit = max(1, min(500, int(limit or 100)))
        offset = max(0, int(offset or 0))
        league, health, search = str(league or "").upper(), str(health or "").upper(), str(search or "").lower()
        with closing(self.connect()) as conn:
            events = conn.execute("SELECT canonical_event_key,league,event_id,event_date,event_json,final_at FROM history_catalog_event WHERE event_date<=? ORDER BY event_date DESC,canonical_event_key", (_today(),)).fetchall()
            packages = {r["canonical_event_key"]: dict(r) for r in conn.execute("SELECT * FROM history_media_canonical_package").fetchall()}
            latest=conn.execute("SELECT id FROM history_media_audit_run ORDER BY id DESC LIMIT 1").fetchone()
            queue={}
            if latest:
                queue={r["canonical_event_key"]:dict(r) for r in conn.execute("SELECT canonical_event_key,ordinal,state,phase FROM history_media_audit_queue WHERE run_id=?",(latest["id"],)).fetchall()}
        rows = []
        for event_row in events:
            event = _jloads(event_row["event_json"], {})
            final = _event_final(event_row["event_date"], event_row["final_at"], event)
            away, home = _team_name(event, "away"), _team_name(event, "home")
            game = f"{away} @ {home}".strip(" @") or str(event_row["event_id"])
            pkg = packages.get(event_row["canonical_event_key"])
            row_health = str(pkg.get("health") if pkg else ("UNTESTED" if final else "WAITING_FINAL"))
            if league and str(event_row["league"]).upper() != league:
                continue
            if health and row_health != health:
                continue
            if search and search not in f"{game} {event_row['league']} {event_row['event_id']}".lower():
                continue
            q=queue.get(event_row["canonical_event_key"]) or {}
            rows.append({
                "canonicalEventKey": event_row["canonical_event_key"], "date": event_row["event_date"], "league": event_row["league"], "eventId": event_row["event_id"], "game": game,
                "final": final, "health": row_health, "certifiedAt": float(pkg.get("certified_at") or 0) if pkg else 0,
                "gold": str(pkg.get("gold_asset_key") or "") if pkg else "", "green": str(pkg.get("green_asset_key") or "") if pkg else "", "purple": str(pkg.get("purple_asset_key") or "") if pkg else "",
                "blueCount": len(_jloads(pkg.get("blue_asset_keys_json"), [])) if pkg else 0,
                "rehydrationState": str(pkg.get("rehydration_state") or "") if pkg else "",
                "queueOrdinal":int(q.get("ordinal") or 0),"queueState":str(q.get("state") or ""),"queuePhase":str(q.get("phase") or ""),
            })
        if queue:
            queued=[r for r in rows if r.get("queueOrdinal")]; other=[r for r in rows if not r.get("queueOrdinal")]
            queued.sort(key=lambda r:r["queueOrdinal"]); rows=queued+other
        total = len(rows)
        return {"rows": rows[offset:offset + limit], "total": total, "limit": limit, "offset": offset}

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
        return {"games": total_events, "certifiedGames": certified, "staleGames": stale, "health": package_counts, "playedAssets": played_assets, "failedAssets": failed_assets}

    def rehydration_manifest(self):
        with closing(self.connect()) as conn:
            rows = conn.execute("""SELECT p.*,e.league,e.event_id,e.event_date,e.event_json FROM history_media_canonical_package p JOIN history_catalog_event e ON e.canonical_event_key=p.canonical_event_key WHERE p.rehydration_state<>'' OR p.health IN ('UNPLAYABLE','NO_MEDIA','DEGRADED') ORDER BY e.event_date DESC,e.league,e.event_id""").fetchall()
        games = []
        for row in rows:
            event = _jloads(row["event_json"], {})
            games.append({
                "date": row["event_date"], "league": row["league"], "eventId": row["event_id"], "canonicalEventKey": row["canonical_event_key"],
                "game": f"{_team_name(event,'away')} @ {_team_name(event,'home')}".strip(" @"), "health": row["health"],
                "rehydrationState": row["rehydration_state"], "reason": row["rehydration_reason"],
                "canonicalGreen": row["green_asset_key"], "canonicalPurple": row["purple_asset_key"], "canonicalBlue": _jloads(row["blue_asset_keys_json"], []),
            })
        return {"generatedAt": _now(), "generation": AUDIT_GENERATION, "games": games}


class BrowserProbe:
    def __init__(self):
        self.driver = None
        self.lock = threading.RLock()
        self.browser = ""
        self.last_error = ""

    def close(self):
        with self.lock:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None

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
            return {"ok": False, "hard": True, "reason": "NON_VIDEO_MEDIA_URL", "startupMs": 0, "currentTimeDelta": 0}
        if not youtube_id and not url:
            return {"ok": False, "hard": True, "reason": "MEDIA_URL_MISSING", "startupMs": 0, "currentTimeDelta": 0}
        payload = {"kind": "youtube" if youtube_id else "direct", "youtubeId": youtube_id, "url": url, "assetKey": asset.get("assetKey")}
        with self.lock:
            driver = self._ensure()
            try:
                driver.get(PROBE_URL + ("?worker=" + AUDIT_GENERATION + "&t=" + str(int(_now()))))
                result = driver.execute_async_script(
                    """const input=arguments[0], done=arguments[arguments.length-1];
                    const finish=(v)=>done(v||{ok:false,reason:'EMPTY_PROBE_RESULT'});
                    if(!window.SBB_MEDIA_PROBE||!window.SBB_MEDIA_PROBE.probe){finish({ok:false,hard:false,reason:'PROBE_PAGE_NOT_READY'});return;}
                    window.SBB_MEDIA_PROBE.probe(input).then(finish).catch(e=>finish({ok:false,hard:false,reason:'PROBE_EXCEPTION',message:String(e&&e.message||e)}));""",
                    payload,
                )
                return result if isinstance(result, dict) else {"ok": False, "hard": False, "reason": "INVALID_PROBE_RESULT"}
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                try:
                    driver.quit()
                except Exception:
                    pass
                self.driver = None
                return {"ok": False, "hard": False, "reason": "BROWSER_WORKER_ERROR", "message": self.last_error}


class CanonicalAuditWorker(threading.Thread):
    daemon = True

    def __init__(self, store: AuditStore, probe: BrowserProbe):
        super().__init__(name="canonical-media-audit")
        self.store, self.probe = store, probe
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
                item = self.store.next_queue_item(int(run["id"]))
                self._db_recovered()
                if not item:
                    self._db_op("complete run if queue empty")
                    self.store.complete_run_if_done(int(run["id"]))
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
                self._trace("INFO", f"Queue #{item['ordinal']} started: {item['game']}", league=item["league"], event=item["canonical_event_key"])

                try:
                    result = self.audit_event(run, item)
                    current_run = self.store.run_snapshot(int(run["id"]))
                    self._db_recovered()
                    if current_run and current_run.get("state") != "STOPPED":
                        self._db_op("finish queue item")
                        self.store.finish_queue_item(
                            run["id"], item["ordinal"], result.get("health", "FAILED"),
                            result.get("note", ""), failed=bool(result.get("failed"))
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
                        "WARN", f"SQLite busy on queue #{item['ordinal']}; same ordinal will retry",
                        operation=snap.get("dbOperation") or "", retry=retries, event=item["canonical_event_key"]
                    )
                    # Do not mark media or queue item failed. Deterministic next_queue_item
                    # will return this same ACTIVE/PENDING lowest ordinal after the lock clears.
                    time.sleep(DB_LOCK_RETRY_SECONDS)
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
                            self._db_op("persist worker exception retry phase")
                            self.store.queue_phase(
                                run["id"], item["ordinal"], "RETRY_WORKER_EXCEPTION",
                                f"{msg} • retry {attempt}/{WORKER_EXCEPTION_RETRIES}"
                            )
                            self._db_recovered()
                        except sqlite3.OperationalError as db_exc:
                            if _is_db_locked(db_exc):
                                self._diag(
                                    phase="WAITING_DATABASE_LOCK", dbState="LOCKED",
                                    dbLockRetries=int(self.snapshot().get("dbLockRetries") or 0)+1,
                                    lastDbLockAt=_now(), waitingReason=f"{type(db_exc).__name__}: {db_exc}"
                                )
                            else:
                                raise
                        time.sleep(min(10.0, 1.5 * attempt))
                        continue

                    current_run = self.store.run_snapshot(int(run["id"]))
                    if current_run and current_run.get("state") != "STOPPED":
                        self._db_op("terminal worker exception after bounded retries")
                        self.store.finish_queue_item(
                            run["id"], item["ordinal"], "FAILED",
                            f"{msg} • exhausted {WORKER_EXCEPTION_RETRIES} retries", failed=True
                        )
                    self._trace("ERROR", f"Queue #{item['ordinal']} terminal worker exception", error=msg)
                finally:
                    self.current = {}

                self._db_op("complete run if done")
                self.store.complete_run_if_done(int(run["id"]))
                self._db_recovered()
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
        while not self.stop_event.is_set():
            self._db_op("read run state before media probe")
            current = self.store.run_snapshot(run_id)
            self._db_recovered()
            if not current or current.get("state") == "STOPPED":
                return {"ok": False, "hard": False, "reason": "RUN_STOPPED"}
            if current.get("state") == "PAUSED":
                self._diag(phase="PAUSED", waitingReason="Operator paused canonical audit")
                time.sleep(1)
                continue

            self._diag(
                candidateTier=str(tier or asset.get("tier") or "").upper(),
                candidateIndex=int(index or 0), candidateCount=int(count or 0),
                assetKey=asset.get("assetKey") or "", assetTitle=asset.get("title") or "",
                assetProvider=asset.get("provider") or "", probeAttempt=media_attempt + 1,
                probeMaxAttempts=SOFT_RETRIES, waitingReason=""
            )
            result = self.probe.probe(asset)
            reason = str(result.get("reason") or "")
            self._diag(lastProbeResult=reason or ("PLAYING_TIME_ADVANCED" if result.get("ok") else "UNKNOWN"))
            if reason in INFRA_FAILURES:
                self._diag(phase="WAITING_PROBE_INFRASTRUCTURE", waitingReason=reason)
                self._trace("WARN", "Playback probe infrastructure unavailable; media not failed", reason=reason, asset=asset.get("assetKey"))
                try:
                    self._db_op("persist probe infrastructure wait phase")
                    self.store.queue_phase(
                        run_id, int(current.get("current_ordinal") or 0),
                        "WAITING_PROBE_INFRASTRUCTURE", reason
                    )
                    self._db_recovered()
                except sqlite3.OperationalError:
                    pass
                time.sleep(DISCOVERY_RETRY_SECONDS)
                continue

            media_attempt += 1
            self._db_op("persist canonical browser probe result")
            self.store.record_probe(run_id, event_key, asset, media_attempt, result, self.probe.browser)
            self._db_recovered()
            self._trace(
                "INFO" if result.get("ok") else "WARN",
                f"{str(tier or asset.get('tier') or '').upper()} probe {'PASS' if result.get('ok') else 'FAIL'}",
                asset=asset.get("assetKey"), provider=asset.get("provider"), reason=reason, attempt=media_attempt
            )
            last = result
            if result.get("ok") or result.get("hard") or media_attempt >= SOFT_RETRIES:
                break
            time.sleep(1.0)
        return last or {"ok": False, "reason": "NO_RESULT"}

    def _select_one(self, run_id, event_key, candidates, *, tier="", tested=None):
        candidates = list(candidates)
        tested = tested if tested is not None else set()

        def runtime_rank(a):
            state = str(a.get("runtimeState") or "").upper()
            if state == "PLAYED":
                return 0
            if state == "FAILED":
                return 2
            return 1

        candidates.sort(key=lambda a: (
            runtime_rank(a),
            0 if str(a.get("validationState") or "").upper() == "VERIFIED" else 1,
            -float(a.get("durationSeconds") or 0), str(a.get("assetKey")),
        ))
        available = [a for a in candidates if a.get("assetKey") not in tested]
        for idx, asset in enumerate(available, 1):
            tested.add(asset.get("assetKey"))
            result = self._probe_candidate(
                run_id, event_key, asset, tier=tier or asset.get("tier") or "",
                index=idx, count=len(available)
            )
            if result.get("ok"):
                return asset
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
        query = urlencode({
            "date": item["event_date"], "league": str(item["league"] or "").upper(),
            "eventId": item["event_id"],
        })
        req = Request(
            MAIN_API + "/api/history/event/media?" + query,
            headers={"User-Agent": f"SportsBigBoard-CanonicalAudit/{APP_VERSION}-{AUDIT_GENERATION}"}
        )
        try:
            with urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            plan = payload.get("plan") if isinstance(payload, dict) else {}
            return {"ok": bool(payload.get("ok", True)), "plan": plan or {}, "reason": ""}
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                payload = {}
            # Special Events can still be served directly from normalized SQLite
            # even when the legacy history endpoint rejects their league identifier.
            return {"ok": False, "plan": {}, "reason": str(payload.get("error") or f"HTTP_{exc.code}")}
        except Exception as exc:
            return {"ok": False, "plan": {}, "reason": f"{type(exc).__name__}: {exc}"}

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
        self._diag(
            productionMediaCount=len(media), productionPlayableCount=len(playable),
            productionPlanState="OK" if prod.get("ok") else (prod.get("reason") or "UNAVAILABLE")
        )

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
            self._db_op("read run state before targeted discovery")
            current = self.store.active_run()
            self._db_recovered()
            if not current or current["state"] in {"STOPPED"}:
                return {"ok": False, "reason": "RUN_STOPPED"}
            if current["state"] == "PAUSED":
                self._diag(phase="PAUSED", waitingReason="Operator paused canonical audit")
                time.sleep(1)
                continue
            try:
                with urlopen(req, timeout=120) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
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
                        self.store.queue_phase(run["id"], item["ordinal"], "WAITING_DISCOVERY_PRIORITY", note)
                        self._db_recovered()
                    except sqlite3.OperationalError:
                        pass
                    time.sleep(DISCOVERY_RETRY_SECONDS)
                    continue
                reason = str(payload.get("error") or f"HTTP_{exc.code}")
                self._diag(discoveryResult=reason)
                if exc.code in {400, 404}:
                    return {"ok": False, "reason": reason}
                time.sleep(DISCOVERY_RETRY_SECONDS)
            except (URLError, TimeoutError) as exc:
                self._diag(discoveryResult=f"{type(exc).__name__}", waitingReason="Discovery transport retry")
                time.sleep(DISCOVERY_RETRY_SECONDS)
        return {"ok": False, "reason": "WORKER_STOPPED"}

    def audit_event(self, run, item):
        run_id = int(run["id"])
        event_key = item["canonical_event_key"]
        self._db_op("set LOAD_MEDIA phase")
        self.store.queue_phase(run_id, item["ordinal"], "LOAD_MEDIA")
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
            self.store.queue_phase(run_id, item["ordinal"], "TEST_GOLD")
            self._db_recovered()
            self._diag(phase="TEST_GOLD")
            selected["gold"] = self._select_one(run_id, event_key, buckets["gold"], tier="GOLD", tested=tested)

        # Verify both preferred tiers when candidates already exist.
        for tier in ("green", "extended"):
            if buckets[tier]:
                phase = "TEST_PURPLE" if tier == "extended" else "TEST_GREEN"
                self._db_op(f"set {phase} phase")
                self.store.queue_phase(run_id, item["ordinal"], phase)
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
                self.store.queue_phase(run_id, item["ordinal"], phase)
                self._db_recovered()
                self._diag(phase=phase)
                discovery = self._discover_preferred(run, item, pass_number)
                discovery_reason = discovery.get("reason") or ""
                if not discovery.get("ok") and discovery_reason in {"BAD_HISTORY_EVENT", "HISTORY_EVENT_NOT_FOUND"}:
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
                        self.store.queue_phase(run_id, item["ordinal"], phase)
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
            self.store.queue_phase(run_id, item["ordinal"], "BLUE_FALLBACK")
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
                    if len(selected["blue"]) >= BLUE_FALLBACK_TARGET:
                        break

        if preferred:
            health = "HEALTHY"
            # Missing the second preferred tier is informational, not a repair blocker.
            rehydration_state = ""
            rehydration_reason = ""
        elif selected["blue"] or selected["gold"]:
            health = "DEGRADED"
            rehydration_state = "PREFERRED_MEDIA_REQUIRED"
            rehydration_reason = "No healthy Green/Purple; canonical fallback remains playable"
        elif assets:
            health = "UNPLAYABLE"
            rehydration_state = "PREFERRED_MEDIA_REQUIRED"
            rehydration_reason = "Assigned media exists but no asset passed canonical browser playback"
        else:
            health = "NO_MEDIA"
            rehydration_state = "PREFERRED_MEDIA_REQUIRED"
            rehydration_reason = "No assigned GAME media exists"
        if not preferred and discovery_reason:
            rehydration_reason = f"{rehydration_reason}; discovery={discovery_reason}".strip("; ")

        current_run = self.store.run_snapshot(run_id)
        self._db_recovered()
        if not current_run or current_run.get("state") == "STOPPED":
            return {"health": "SKIPPED", "note": "RUN_STOPPED_BEFORE_CANONICALIZE"}

        self._db_op("canonicalize shared event-media package")
        self.store.queue_phase(run_id, item["ordinal"], "CANONICALIZE")
        self._db_recovered()
        self._diag(phase="CANONICALIZE")
        package = self.store.canonicalize(
            run_id, item, selected, health, rehydration_state, rehydration_reason
        )
        self._db_recovered()
        note = (
            f"canonical package: green={bool(selected['green'])} "
            f"purple={bool(selected['extended'])} gold={bool(selected['gold'])} "
            f"blue={len(selected['blue'])} • productionMedia={self.snapshot().get('productionMediaCount',0)} "
            f"productionPlayable={self.snapshot().get('productionPlayableCount',0)}"
        )
        return {"health": health, "note": note, "package": package}


STORE = AuditStore(DB_PATH)
RECOVERY = STORE.recover_exception_failures()
PROBE = BrowserProbe()
WORKER = CanonicalAuditWorker(STORE, PROBE)
WORKER.start()
if RECOVERY.get("requeued"):
    WORKER._trace("WARN", f"Recovered {RECOVERY['requeued']} prior worker/infrastructure failures for deterministic retry", runId=RECOVERY.get("runId"))


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
                storage_error = ""
                run_snapshot = None
                summary = {}
                newest = ""
                try:
                    run_snapshot = STORE.run_snapshot()
                    summary = STORE.summary()
                    newest = STORE.newest_eligible_date()
                except sqlite3.OperationalError as exc:
                    if not _is_db_locked(exc):
                        raise
                    storage_error = f"{type(exc).__name__}: {exc}"
                return _json(self, {
                    "ok": True, "version": APP_VERSION, "generation": AUDIT_GENERATION,
                    "canonical": True, "browserOwned": False, "probeUrl": PROBE_URL,
                    "timezone": AUDIT_TIMEZONE, "browser": PROBE.browser,
                    "browserError": PROBE.last_error, "storageReadError": storage_error,
                    "worker": {
                        "alive": WORKER.is_alive(), "current": WORKER.current,
                        "lastError": WORKER.last_error, "diagnostics": WORKER.snapshot(),
                        "recoveredExceptionFailures": RECOVERY
                    },
                    "run": run_snapshot, "summary": summary, "newestEligibleDate": newest
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
                return _json(self, {"ok": True, "run": STORE.start_run(body.get("mode") or "ALL", body.get("startDate") or "")})
            if parsed.path == "/pause":
                return _json(self, {"ok": True, "run": STORE.set_run_state("PAUSED")})
            if parsed.path == "/resume":
                return _json(self, {"ok": True, "run": STORE.set_run_state("RUNNING")})
            if parsed.path == "/stop":
                return _json(self, {"ok": True, "run": STORE.set_run_state("STOPPED")})
            if parsed.path == "/reset":
                existing=STORE.active_run()
                if existing and existing.get("state") in {"RUNNING","PAUSED"}:
                    STORE.set_run_state("STOPPED")
                    deadline=time.time()+40
                    while time.time()<deadline and WORKER.current and int(WORKER.current.get("runId") or 0)==int(existing.get("id") or 0):
                        time.sleep(0.25)
                return _json(self, STORE.reset_run(recertify=bool(body.get("recertify"))))
            return _json(self, {"ok": False, "error": "NOT_FOUND"}, 404)
        except Exception as exc:
            traceback.print_exc(); return _json(self, {"ok": False, "error": "MEDIA_AUDIT_API_ERROR", "message": f"{type(exc).__name__}: {exc}"}, 500)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Sports Big Board canonical Media Audit {AUDIT_GENERATION} listening on http://{HOST}:{PORT}", flush=True)
    print(f"Probe origin: {PROBE_URL}", flush=True)
    stop = threading.Event()
    def shutdown(_sig, _frame):
        stop.set(); WORKER.stop(); threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown); signal.signal(signal.SIGINT, shutdown)
    try: server.serve_forever(poll_interval=0.5)
    finally: WORKER.stop(); server.server_close()


if __name__ == "__main__":
    main()

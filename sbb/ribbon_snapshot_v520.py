"""Sports Big Board v5.2.1 — server-prepared ribbon snapshot authority.

The browser should never have to discover what a score card means. Day State remains
canonical event/media truth; this service continuously serializes its already-built
read model into a tiny persistent hot cache that is safe to serve without running
provider, media, matcher, or Game Center work on the request thread.

Hot path:
    providers/workers -> canonical repositories -> Day State
                                              -> RibbonSnapshotStore
browser -> GET /api/ribbon-snapshot?date=YYYY-MM-DD -> SQLite/memory only

The service never builds a Day State snapshot itself. A cold miss focuses the normal
Day State worker and returns 202. This preserves one backend authority and prevents
ribbon first-paint requests from competing with media/provider work.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import day_state

VERSION = "5.2.1-ribbon-snapshot-2"
_STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
_DB_PATH = _STATE_DIR / "ribbon-snapshot.sqlite3"
_DATE_RE = __import__('re').compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_SERVER = None
_STORE = None
_STOP = threading.Event()
_STATS = {
    "version": VERSION,
    "served": 0,
    "hits": 0,
    "misses": 0,
    "writes": 0,
    "unchanged": 0,
    "hotRefreshes": 0,
    "coldFocused": 0,
    "lastError": "",
    "lastWriteAt": 0.0,
}


def _clean_date(value):
    text = str(value or "")[:10]
    return text if _DATE_RE.fullmatch(text) else ""


def _json_dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _revision(snapshot):
    summary = snapshot.get("summary") or {}
    basis = "|".join([
        str(snapshot.get("date") or ""),
        str(snapshot.get("sourceRevision") or ""),
        str(snapshot.get("ribbonAuthorityRevision") or ""),
        str(snapshot.get("registryRevision") or ""),
        str(snapshot.get("generatedAt") or ""),
        str(summary.get("games") or snapshot.get("scoreGameCount") or 0),
        str(summary.get("playable") or 0),
        str(summary.get("live") or 0),
    ])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _project(snapshot):
    """Return the complete, already-renderable ribbon read model.

    Keep scoreRowsByLeague + eventPlans intact because those two objects are the
    browser's existing canonical ingestion contract. Everything expensive (aliases,
    flags, round names, media associations) has already been resolved by Day State.
    """
    if not isinstance(snapshot, dict) or not _clean_date(snapshot.get("date")):
        return None
    out = {
        "ok": True,
        "version": str(snapshot.get("version") or ""),
        "engineVersion": str(snapshot.get("engineVersion") or ""),
        "ribbonSnapshotVersion": VERSION,
        "date": _clean_date(snapshot.get("date")),
        "generatedAt": float(snapshot.get("generatedAt") or time.time()),
        "sourceRevision": str(snapshot.get("sourceRevision") or ""),
        "registryRevision": int(snapshot.get("registryRevision") or 0),
        "scoreRowsByLeague": snapshot.get("scoreRowsByLeague") or {},
        "scoreGameCount": int(snapshot.get("scoreGameCount") or (snapshot.get("summary") or {}).get("games") or 0),
        "eventPlans": snapshot.get("eventPlans") or {},
        "catalogFirst": bool(snapshot.get("catalogFirst", True)),
        "compact": True,
        "catalogEventCount": int(snapshot.get("catalogEventCount") or 0),
        "scoreInventoryComplete": bool(snapshot.get("scoreInventoryComplete")),
        "summary": snapshot.get("summary") or {},
        "projectionDiagnostics": snapshot.get("projectionDiagnostics") or {},
        "ribbonAuthorityVersion": snapshot.get("ribbonAuthorityVersion") or "",
        "ribbonAuthorityRevision": snapshot.get("ribbonAuthorityRevision") or "",
        "cache": {"state": "RIBBON_SNAPSHOT", "ageSeconds": 0},
    }
    out["ribbonRevision"] = _revision(out)
    return out


class RibbonSnapshotStore:
    def __init__(self, path=_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.memory = {}
        with self.lock, closing(self._connect()) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS ribbon_snapshot(
                    day TEXT PRIMARY KEY,
                    revision TEXT NOT NULL,
                    generated_at REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_ribbon_snapshot_updated ON ribbon_snapshot(updated_at)")
            con.commit()

    def _connect(self):
        con = sqlite3.connect(self.path, timeout=1.0)
        con.row_factory = sqlite3.Row
        return con

    def put(self, payload):
        day = _clean_date((payload or {}).get("date"))
        if not day:
            return False
        revision = str(payload.get("ribbonRevision") or _revision(payload))
        with self.lock:
            current = self.memory.get(day)
            if current and str(current.get("ribbonRevision")) == revision:
                _STATS["unchanged"] += 1
                return False
            raw = _json_dumps(payload)
            with closing(self._connect()) as con:
                row = con.execute("SELECT revision FROM ribbon_snapshot WHERE day=?", (day,)).fetchone()
                if row and str(row["revision"]) == revision:
                    self.memory[day] = payload
                    _STATS["unchanged"] += 1
                    return False
                now = time.time()
                con.execute("""
                    INSERT INTO ribbon_snapshot(day,revision,generated_at,payload_json,updated_at)
                    VALUES(?,?,?,?,?)
                    ON CONFLICT(day) DO UPDATE SET
                        revision=excluded.revision,
                        generated_at=excluded.generated_at,
                        payload_json=excluded.payload_json,
                        updated_at=excluded.updated_at
                """, (day, revision, float(payload.get("generatedAt") or now), raw, now))
                con.commit()
            self.memory[day] = payload
        _STATS["writes"] += 1
        _STATS["lastWriteAt"] = time.time()
        return True

    def get(self, day):
        day = _clean_date(day)
        if not day:
            return None
        with self.lock:
            hit = self.memory.get(day)
            if hit:
                return dict(hit)
            with closing(self._connect()) as con:
                row = con.execute("SELECT payload_json FROM ribbon_snapshot WHERE day=?", (day,)).fetchone()
            if not row:
                return None
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                return None
            self.memory[day] = payload
            return dict(payload)

    def status(self, limit=14):
        with self.lock, closing(self._connect()) as con:
            rows = con.execute("""
                SELECT day,revision,generated_at,updated_at,length(payload_json) bytes
                FROM ribbon_snapshot ORDER BY day DESC LIMIT ?
            """, (max(1, min(60, int(limit or 14))),)).fetchall()
        return [dict(row) for row in rows]


def _engine():
    try:
        return day_state.engine()
    except Exception:
        return None


def _refresh_from_day_state(day):
    engine = _engine()
    if not engine:
        return None
    try:
        snapshot = engine.get(day, allow_build=False)
    except Exception as exc:
        _STATS["lastError"] = f"{type(exc).__name__}: {exc}"
        return None
    payload = _project(snapshot) if snapshot else None
    if payload:
        _STORE.put(payload)
        _STATS["hotRefreshes"] += 1
    return payload


def _hot_days(engine):
    today = datetime.strptime(engine.today(), "%Y-%m-%d").date()
    values = {(today + timedelta(days=d)).isoformat() for d in (-2, -1, 0, 1, 2)}
    try:
        values.update(day for day, until in engine.focus_dates.items() if until > time.time())
    except Exception:
        pass
    return sorted(values)


def _worker():
    # Day State already performs the actual builds. This loop only snapshots rows
    # that already exist, so it cannot steal provider/media bandwidth from startup.
    while not _STOP.is_set():
        engine = _engine()
        if not engine or _STORE is None:
            _STOP.wait(0.25)
            continue
        for day in _hot_days(engine):
            if _STOP.is_set():
                return
            _refresh_from_day_state(day)
        _STOP.wait(2.0)


def _serve(server, handler, parsed):
    qs = parse_qs(parsed.query)
    day = _clean_date((qs.get("date") or [""])[-1])
    if not day:
        return server.send_json(handler, {"ok": False, "error": "DATE_REQUIRED"}, 400)

    _STATS["served"] += 1
    payload = _STORE.get(day) if _STORE else None
    if payload:
        _STATS["hits"] += 1
        age = max(0.0, time.time() - float(payload.get("generatedAt") or 0))
        payload["cache"] = {"state": "RIBBON_SNAPSHOT_HIT", "ageSeconds": round(age, 1)}
        return server.send_json(handler, payload, 200, {
            "X-SBB-Ribbon-Snapshot": "HIT",
            "X-SBB-Ribbon-Revision": str(payload.get("ribbonRevision") or ""),
            "Cache-Control": "no-store",
        })

    # One local SQLite/memory read from Day State is still cheap. Never call build().
    payload = _refresh_from_day_state(day)
    if payload:
        _STATS["hits"] += 1
        payload["cache"] = {"state": "RIBBON_SNAPSHOT_MATERIALIZED", "ageSeconds": 0}
        return server.send_json(handler, payload, 200, {
            "X-SBB-Ribbon-Snapshot": "MATERIALIZED",
            "X-SBB-Ribbon-Revision": str(payload.get("ribbonRevision") or ""),
            "Cache-Control": "no-store",
        })

    _STATS["misses"] += 1
    engine = _engine()
    if engine:
        try:
            engine.focus(day)
            _STATS["coldFocused"] += 1
        except Exception:
            pass
    return server.send_json(handler, {
        "ok": True,
        "pending": True,
        "date": day,
        "ribbonSnapshotVersion": VERSION,
        "message": "Ribbon snapshot warming from canonical Day State.",
    }, 202, {"X-SBB-Ribbon-Snapshot": "WARMING", "Cache-Control": "no-store"})


def _install_into_server():
    global _SERVER, _STORE
    deadline = time.time() + 120
    server = None
    while time.time() < deadline:
        candidate = sys.modules.get("__main__")
        engine = _engine()
        if candidate and engine and hasattr(candidate, "Handler") and hasattr(candidate, "send_json"):
            server = candidate
            break
        time.sleep(0.2)
    if not server:
        _STATS["lastError"] = "SERVER_INSTALL_TIMEOUT"
        return

    _SERVER = server
    _STORE = RibbonSnapshotStore()
    Handler = server.Handler
    if not getattr(Handler, "__sbbRibbonSnapshotV520", False):
        old_get = Handler.do_GET

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/ribbon-snapshot":
                return _serve(server, self, parsed)
            if parsed.path == "/api/ribbon-snapshot/status":
                return server.send_json(self, {
                    "ok": True,
                    **_STATS,
                    "snapshots": _STORE.status(31),
                }, 200)
            return old_get(self)

        Handler.do_GET = do_GET
        Handler.__sbbRibbonSnapshotV520 = True

    threading.Thread(target=_worker, daemon=True, name="sbb-ribbon-snapshot-v520").start()


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-ribbon-snapshot-install-v520").start()


def diagnostics():
    return {**_STATS, "installed": _INSTALLED, "store": (_STORE.status(7) if _STORE else [])}

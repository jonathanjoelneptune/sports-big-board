"""Sports Big Board Day State Engine.

Day State is the read model for the Big Board. Provider/schedule/media workers write
canonical data into the normalized repositories; Day State continuously projects
that data into the compact shape the ribbon already consumes.

Architecture:
    providers/workers -> canonical repositories -> DayStateEngine -> /api/day-state
                                                   -> /api/history/ribbon (cache-first)

The browser remains a renderer. It no longer needs to discover the meaning of a
historical day before showing it, and dynamically-created competitions are enrolled
through Competition Registry 2.0 without hard-coded league branches.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
import time
from collections import deque
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import competition_registry as registry

_STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
_DB_PATH = _STATE_DIR / "day-state.sqlite3"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ENGINE = None


def _clean_date(value):
    value = str(value or "")[:10]
    return value if _DATE_RE.fullmatch(value) else ""


def _event_status(event):
    raw = (event or {}).get("status")
    if isinstance(raw, dict):
        raw = raw.get("type") or raw.get("name") or raw.get("state") or raw.get("description")
    value = str(raw or "").upper()
    if any(token in value for token in ("FINAL","COMPLETED","FINISHED","FT")):
        return "FINAL"
    if any(token in value for token in ("LIVE","IN_PROGRESS","IN PROGRESS","HALFTIME","QTR","PERIOD")):
        return "LIVE"
    if "POSTPON" in value:
        return "POSTPONED"
    if "CANCEL" in value:
        return "CANCELLED"
    return "SCHEDULED"


def _plan_playable_count(plans):
    count = 0
    for plan in (plans or {}).values():
        if any(bool(x.get("verifiedPlayable")) and (x.get("youtubeId") or x.get("mediaUrl")) for x in (plan.get("playable") or plan.get("media") or [])):
            count += 1
    return count


class DayStateStore:
    def __init__(self, path=_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.lock, closing(self._connect()) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS day_state (
                    day TEXT PRIMARY KEY,
                    snapshot_json TEXT NOT NULL,
                    generated_at REAL NOT NULL DEFAULT 0,
                    registry_revision INTEGER NOT NULL DEFAULT 0,
                    source_revision TEXT NOT NULL DEFAULT '',
                    event_count INTEGER NOT NULL DEFAULT 0,
                    live_count INTEGER NOT NULL DEFAULT 0,
                    final_count INTEGER NOT NULL DEFAULT 0,
                    scheduled_count INTEGER NOT NULL DEFAULT 0,
                    playable_count INTEGER NOT NULL DEFAULT 0,
                    stale_after REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_day_state_stale ON day_state(stale_after)")
            conn.commit()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def put(self, snapshot):
        day = _clean_date(snapshot.get("date"))
        if not day:
            raise ValueError("day state snapshot requires YYYY-MM-DD date")
        now = time.time()
        summary = snapshot.get("summary") or {}
        raw = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        with self.lock, closing(self._connect()) as conn:
            conn.execute("""
                INSERT INTO day_state(
                    day,snapshot_json,generated_at,registry_revision,source_revision,
                    event_count,live_count,final_count,scheduled_count,playable_count,
                    stale_after,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(day) DO UPDATE SET
                    snapshot_json=excluded.snapshot_json,
                    generated_at=excluded.generated_at,
                    registry_revision=excluded.registry_revision,
                    source_revision=excluded.source_revision,
                    event_count=excluded.event_count,
                    live_count=excluded.live_count,
                    final_count=excluded.final_count,
                    scheduled_count=excluded.scheduled_count,
                    playable_count=excluded.playable_count,
                    stale_after=excluded.stale_after,
                    updated_at=excluded.updated_at
            """, (
                day, raw, float(snapshot.get("generatedAt") or now),
                int(snapshot.get("registryRevision") or 0),
                str(snapshot.get("sourceRevision") or ""),
                int(summary.get("games") or 0),
                int(summary.get("live") or 0),
                int(summary.get("final") or 0),
                int(summary.get("scheduled") or 0),
                int(summary.get("playable") or 0),
                float(snapshot.get("staleAfter") or 0),
                now,
            ))
            conn.commit()

    def get(self, day):
        day = _clean_date(day)
        if not day:
            return None
        with self.lock, closing(self._connect()) as conn:
            row = conn.execute("SELECT snapshot_json FROM day_state WHERE day=?", (day,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["snapshot_json"])
        except Exception:
            return None

    def status(self, limit=21):
        with self.lock, closing(self._connect()) as conn:
            rows = conn.execute("""
                SELECT day,generated_at,registry_revision,event_count,live_count,
                       final_count,scheduled_count,playable_count,stale_after
                FROM day_state
                ORDER BY day DESC LIMIT ?
            """, (max(1, min(90, int(limit or 21))),)).fetchall()
        return [dict(row) for row in rows]


class DayStateEngine:
    HOT_LIVE_SECONDS = 15
    HOT_TODAY_SECONDS = 20
    HOT_NEAR_SECONDS = 60
    HISTORICAL_SECONDS = 6 * 60 * 60

    def __init__(self, server, store=None):
        self.server = server
        self.store = store or DayStateStore()
        self.lock = threading.RLock()
        self.cache = {}
        self.queue = deque()
        self.queued = set()
        self.focus_dates = {}
        self.running = True
        self.last_build = {}
        self.last_error = ""
        self.builds = 0
        self.hits = 0
        self.misses = 0
        self.registry_events = 0
        registry.subscribe(self._on_registry_event, replay=True)

    def today(self):
        try:
            fn = getattr(self.server, "_history_schedule_sync_today", None)
            if callable(fn):
                return _clean_date(fn())
        except Exception:
            pass
        return datetime.now().date().isoformat()

    def freshness_seconds(self, day, snapshot=None):
        snapshot = snapshot or {}
        summary = snapshot.get("summary") or {}
        today = self.today()
        if day == today:
            return self.HOT_LIVE_SECONDS if int(summary.get("live") or 0) else self.HOT_TODAY_SECONDS
        try:
            delta = abs((datetime.strptime(day, "%Y-%m-%d").date() - datetime.strptime(today, "%Y-%m-%d").date()).days)
        except Exception:
            delta = 99
        return self.HOT_NEAR_SECONDS if delta <= 2 else self.HISTORICAL_SECONDS

    def _on_registry_event(self, event):
        self.registry_events += 1
        comp = (event or {}).get("competition") or {}
        cid = str(comp.get("id") or "").upper()
        if not cid:
            return
        # Registry membership is backend membership. Keep HISTORY_LEAGUES aligned
        # even when the competition was inserted by a new future builder.
        try:
            leagues = list(self.server.HISTORY_LEAGUES)
            if (event or {}).get("action") == "UNREGISTER":
                self.server.HISTORY_LEAGUES = tuple(x for x in leagues if str(x).upper() != cid)
            elif cid not in [str(x).upper() for x in leagues] and comp.get("historyEnabled", True):
                self.server.HISTORY_LEAGUES = tuple([*leagues, cid])
        except Exception:
            pass

        if (event or {}).get("action") == "UNREGISTER":
            return

        # Builder registration may precede canonical event upserts by a few
        # milliseconds. Queue a delayed competition sweep instead of racing it.
        threading.Thread(
            target=self._enqueue_competition_dates_after_registration,
            args=(cid,),
            daemon=True,
            name=f"sbb-day-state-enroll-{cid.lower()}",
        ).start()

    def _enqueue_competition_dates_after_registration(self, cid):
        # Competition Builder publishes the registry entry immediately before it
        # upserts that competition's canonical schedule rows. Retry briefly so a
        # large tournament cannot lose its historical Day State enrollment to that
        # intentional ordering.
        rows = []
        for attempt in range(10):
            time.sleep(0.35 if attempt < 3 else 0.75)
            try:
                rows = self.server.HISTORY_REPOSITORY.catalog_events(league=cid, limit=50000)
            except Exception:
                rows = []
            if rows:
                break
        dates = sorted({_clean_date(row.get("date")) for row in rows if _clean_date(row.get("date"))})
        for day in dates:
            self.enqueue(day, priority=True)

    def enqueue(self, day, *, priority=False):
        day = _clean_date(day)
        if not day:
            return False
        with self.lock:
            if day in self.queued:
                return False
            self.queued.add(day)
            if priority:
                self.queue.appendleft(day)
            else:
                self.queue.append(day)
        return True

    def focus(self, day, seconds=180):
        day = _clean_date(day)
        if not day:
            return
        self.focus_dates[day] = time.time() + max(30, int(seconds or 180))
        self.enqueue(day, priority=True)

    def _source_revision(self):
        parts = [f"registry:{registry.revision()}"]
        for name in ("HISTORY_SCHEDULE_SYNC_STATE", "HISTORY_DATABASE_AUDIT_STATE", "OPERATOR_MEDIA_PLAYLIST_CRAWL_STATE"):
            try:
                state = getattr(self.server, name, {}) or {}
                parts.append(f"{name}:{int(float(state.get('lastRun') or state.get('lastAt') or state.get('revision') or 0))}")
            except Exception:
                pass
        return "|".join(parts)

    def _build_facts(self, score_rows, plans, summary):
        leagues = [lg for lg, rows in score_rows.items() if rows]
        facts = [
            {"key":"GAMES","value":summary["games"],"text":f"{summary['games']} games on the board"},
            {"key":"FINAL","value":summary["final"],"text":f"{summary['final']} final"},
            {"key":"LIVE","value":summary["live"],"text":f"{summary['live']} live"},
            {"key":"PLAYABLE","value":summary["playable"],"text":f"{summary['playable']} games with playable media"},
            {"key":"COMPETITIONS","value":len(leagues),"text":f"{len(leagues)} competitions represented"},
        ]
        return facts

    def build(self, day):
        day = _clean_date(day)
        if not day:
            raise ValueError("YYYY-MM-DD day required")
        started = time.perf_counter()

        score_rows_fn = getattr(self.server, "_history_day_score_rows")
        plans_fn = getattr(self.server, "_history_day_ribbon_plans")
        inventory_fn = getattr(self.server, "_history_day_score_inventory_complete")

        score_rows = score_rows_fn(day)
        plans = plans_fn(day, score_rows)
        inventory = bool(inventory_fn(day))

        games = sum(len(rows or []) for rows in score_rows.values())
        status_counts = {"LIVE":0,"FINAL":0,"SCHEDULED":0,"POSTPONED":0,"CANCELLED":0}
        for rows in score_rows.values():
            for event in rows or []:
                status_counts[_event_status(event)] = status_counts.get(_event_status(event), 0) + 1
        playable = _plan_playable_count(plans)
        summary = {
            "games":games,
            "live":status_counts.get("LIVE",0),
            "final":status_counts.get("FINAL",0),
            "scheduled":status_counts.get("SCHEDULED",0),
            "postponed":status_counts.get("POSTPONED",0),
            "cancelled":status_counts.get("CANCELLED",0),
            "playable":playable,
            "competitions":sum(1 for rows in score_rows.values() if rows),
        }
        generated = time.time()
        ttl = self.freshness_seconds(day, {"summary":summary})
        snapshot = {
            "ok":True,
            "version":str(getattr(self.server, "APP_VERSION", "")),
            "engineVersion":"4.7.0",
            "date":day,
            "generatedAt":generated,
            "staleAfter":generated + ttl,
            "freshForSeconds":ttl,
            "registryRevision":registry.revision(),
            "sourceRevision":self._source_revision(),
            "scoreRowsByLeague":score_rows,
            "scoreGameCount":games,
            "eventPlans":plans,
            "catalogFirst":True,
            "compact":True,
            "catalogEventCount":len(plans),
            "scoreInventoryComplete":inventory,
            "summary":summary,
            "facts":self._build_facts(score_rows, plans, summary),
            "timing":{"buildMs":round((time.perf_counter()-started)*1000.0,1)},
        }
        self.store.put(snapshot)
        with self.lock:
            self.cache[day] = snapshot
            self.last_build[day] = generated
            self.builds += 1
        return snapshot

    def get(self, day, *, allow_build=True, force=False):
        day = _clean_date(day)
        if not day:
            raise ValueError("YYYY-MM-DD day required")
        now = time.time()
        with self.lock:
            cached = self.cache.get(day)
        if not cached:
            cached = self.store.get(day)
            if cached:
                with self.lock:
                    self.cache[day] = cached

        if cached and not force:
            age = max(0, now - float(cached.get("generatedAt") or 0))
            ttl = self.freshness_seconds(day, cached)
            if age <= ttl:
                self.hits += 1
                out = dict(cached)
                out["cache"] = {"state":"HIT","ageSeconds":round(age,1)}
                return out

        self.misses += 1
        if allow_build:
            snapshot = self.build(day)
            out = dict(snapshot)
            out["cache"] = {"state":"MISS_REBUILT","ageSeconds":0}
            return out

        if cached:
            out = dict(cached)
            out["cache"] = {"state":"STALE","ageSeconds":round(max(0, now-float(cached.get('generatedAt') or 0)),1)}
            return out
        return None

    def registry_status(self):
        snap = registry.backend_catalog()
        history = {str(x).upper() for x in getattr(self.server, "HISTORY_LEAGUES", ())}
        rows = []
        for comp in snap["competitions"]:
            row = dict(comp)
            row["historyEnrolled"] = row["id"] in history
            row["dayStateEnrolled"] = bool(row.get("dayStateEnabled", True))
            rows.append(row)
        snap["competitions"] = rows
        return snap

    def status(self):
        today = self.today()
        now = time.time()
        with self.lock:
            queue = list(self.queue)
        return {
            "ok":True,
            "version":"4.7.0",
            "today":today,
            "builds":self.builds,
            "cacheHits":self.hits,
            "cacheMisses":self.misses,
            "queueDepth":len(queue),
            "queue":queue[:25],
            "registryEvents":self.registry_events,
            "registryRevision":registry.revision(),
            "lastError":self.last_error,
            "snapshots":self.store.status(31),
            "focusDates":[day for day,until in self.focus_dates.items() if until>now],
        }

    def worker(self):
        # Initial hot-window warmup.
        today = datetime.strptime(self.today(), "%Y-%m-%d").date()
        for delta in (-1,0,1,2):
            self.enqueue((today + timedelta(days=delta)).isoformat(), priority=(delta in (0,-1)))

        while self.running:
            now = time.time()
            for day, until in list(self.focus_dates.items()):
                if until <= now:
                    self.focus_dates.pop(day, None)
                else:
                    self.enqueue(day, priority=True)

            # Keep live/today snapshots continuously hot.
            self.enqueue(self.today(), priority=True)

            day = None
            with self.lock:
                if self.queue:
                    day = self.queue.popleft()
                    self.queued.discard(day)
            if day:
                try:
                    self.get(day, force=True)
                    self.last_error = ""
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                # Live/current day refreshes more aggressively.
                delay = 2 if day == self.today() else 0.1
                time.sleep(delay)
                continue

            time.sleep(2)

    def serve_day_state(self, handler, parsed):
        qs = parse_qs(parsed.query)
        day = _clean_date((qs.get("date") or [""])[-1])
        if not day:
            return self.server.send_json(handler, {"ok":False,"error":"DATE_REQUIRED"}, 400)
        self.focus(day)
        try:
            payload = self.get(day)
        except Exception as exc:
            return self.server.send_json(handler, {"ok":False,"error":"DAY_STATE_BUILD_FAILED","message":str(exc)}, 500)
        return self.server.send_json(handler, payload, 200, {"X-SBB-Day-State":str((payload.get("cache") or {}).get("state") or "READY")})

    def serve_ribbon(self, handler, parsed):
        qs = parse_qs(parsed.query)
        day = _clean_date((qs.get("date") or [""])[-1])
        if not day:
            return self.server.send_json(handler, {"ok":False,"error":"DATE_REQUIRED"}, 400)
        self.focus(day)
        try:
            payload = self.get(day)
        except Exception:
            return False
        # Exact backward-compatible /api/history/ribbon read model.
        return self.server.send_json(
            handler,
            {
                "ok":True,
                "version":payload.get("version"),
                "date":day,
                "scoreRowsByLeague":payload.get("scoreRowsByLeague") or {},
                "scoreGameCount":payload.get("scoreGameCount") or 0,
                "eventPlans":payload.get("eventPlans") or {},
                "catalogFirst":True,
                "compact":True,
                "catalogEventCount":payload.get("catalogEventCount") or 0,
                "scoreInventoryComplete":bool(payload.get("scoreInventoryComplete")),
                "timing":{"dayStateMs":0.0, **(payload.get("timing") or {})},
                "dayState":{
                    "engineVersion":"4.7.0",
                    "generatedAt":payload.get("generatedAt"),
                    "cache":payload.get("cache") or {},
                    "summary":payload.get("summary") or {},
                },
            },
            200,
            {"X-SBB-Day-State":"1"},
        )


def engine():
    return _ENGINE


def _install_into_server():
    global _ENGINE
    deadline = time.time() + 120
    server = None
    while time.time() < deadline:
        server = sys.modules.get("__main__")
        if server and all(hasattr(server, name) for name in (
            "Handler","send_json","HISTORY_REPOSITORY","HISTORY_LEAGUES",
            "_history_day_score_rows","_history_day_ribbon_plans","_history_day_score_inventory_complete",
        )):
            break
        time.sleep(0.2)
    if not server:
        return

    _ENGINE = DayStateEngine(server)
    Handler = server.Handler
    if not getattr(Handler, "__sbbDayStateInstalled", False):
        old_get = Handler.do_GET
        old_post = Handler.do_POST

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/day-state":
                return _ENGINE.serve_day_state(self, parsed)
            if parsed.path == "/api/day-state/status":
                return server.send_json(self, _ENGINE.status(), 200)
            if parsed.path == "/api/competition-registry":
                return server.send_json(self, {"ok":True, **_ENGINE.registry_status()}, 200)
            if parsed.path == "/api/history/ribbon":
                handled = _ENGINE.serve_ribbon(self, parsed)
                if handled is not False:
                    return handled
            return old_get(self)

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/day-state/rebuild":
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                except Exception:
                    body = {}
                day = _clean_date(body.get("date"))
                if not day:
                    return server.send_json(self, {"ok":False,"error":"DATE_REQUIRED"}, 400)
                try:
                    payload = _ENGINE.get(day, force=True)
                    return server.send_json(self, {"ok":True,"snapshot":payload}, 200)
                except Exception as exc:
                    return server.send_json(self, {"ok":False,"error":"DAY_STATE_BUILD_FAILED","message":str(exc)}, 500)
            return old_post(self)

        Handler.do_GET = do_GET
        Handler.do_POST = do_POST
        Handler.__sbbDayStateInstalled = True

    threading.Thread(target=_ENGINE.worker, daemon=True, name="sbb-day-state-engine").start()


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-day-state-install").start()

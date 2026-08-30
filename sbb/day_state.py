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

def _event_identity(event):
    """Stable-enough canonical event identity for Day State row merging."""
    if not isinstance(event, dict):
        return ""
    for key in ("scoreEventId","matchId","espnEventId","gamePk","canonicalEventId","eventId","id"):
        value = event.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _merge_future_catalog_rows(server, day, score_rows, today):
    """Merge future canonical catalog rows into the ribbon read model.

    The legacy history-day score cache was designed around completed/current dates
    and can legitimately be empty for a future tournament date even though
    history_catalog_event already owns scheduled games. Day State is the canonical
    read model, so future scheduled catalog rows must be projected here rather than
    making the browser rediscover them.
    """
    normalized = {
        str(league or "").upper(): [dict(row) for row in (rows or []) if isinstance(row, dict)]
        for league, rows in (score_rows or {}).items()
    }
    diagnostics = {
        "future": bool(day and today and day > today),
        "catalogCandidates": 0,
        "catalogAdded": 0,
        "rowsBefore": sum(len(rows) for rows in normalized.values()),
        "rowsAfter": 0,
        "leaguesAdded": [],
    }
    if not diagnostics["future"]:
        diagnostics["rowsAfter"] = diagnostics["rowsBefore"]
        return normalized, diagnostics

    repo = getattr(server, "HISTORY_REPOSITORY", None)
    if repo is None or not hasattr(repo, "catalog_events"):
        diagnostics["rowsAfter"] = diagnostics["rowsBefore"]
        return normalized, diagnostics

    try:
        catalog = repo.catalog_events(date_from=day, date_to=day, limit=50000) or []
    except Exception:
        catalog = []

    diagnostics["catalogCandidates"] = len(catalog)
    existing = {}
    for league, rows in normalized.items():
        existing[league] = {_event_identity(row) for row in rows if _event_identity(row)}

    leagues_added = set()
    for catalog_row in catalog:
        if not isinstance(catalog_row, dict):
            continue
        league = str(catalog_row.get("league") or "").upper()
        if not league:
            continue
        event_id = str(catalog_row.get("eventId") or "")
        event = dict(catalog_row.get("event") or {})
        identity = _event_identity(event) or event_id
        if identity and identity in existing.setdefault(league, set()):
            continue

        # The catalog normally stores the complete schedule JSON. The defaults
        # below make even a minimal imported bracket row renderable as SCHEDULED.
        event.setdefault("competitionId", league)
        event.setdefault("league", league)
        event.setdefault("__sbbLeague", league)
        event.setdefault("__sbbDate", day)
        event.setdefault("date", day)
        if event_id:
            event.setdefault("eventId", event_id)
            event.setdefault("id", event_id)
        if not event.get("status"):
            event["status"] = "SCHEDULED"

        normalized.setdefault(league, []).append(event)
        if identity:
            existing[league].add(identity)
        diagnostics["catalogAdded"] += 1
        leagues_added.add(league)

    diagnostics["rowsAfter"] = sum(len(rows) for rows in normalized.values())
    diagnostics["leaguesAdded"] = sorted(leagues_added)
    return normalized, diagnostics


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
    HISTORICAL_SECONDS = 12 * 60 * 60
    HISTORICAL_COMPLETE_SECONDS = 24 * 60 * 60

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
        self.build_locks = {}
        self.last_error = ""
        self.builds = 0
        self.prewarm_queued = 0
        self.prewarm_built = 0
        self.next_today_refresh = 0.0
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
        if delta <= 2:
            return self.HOT_NEAR_SECONDS
        if (
            day < today
            and bool(snapshot.get("scoreInventoryComplete"))
            and int(summary.get("live") or 0) == 0
            and int(summary.get("scheduled") or 0) == 0
            and int(summary.get("games") or 0) > 0
        ):
            return self.HISTORICAL_COMPLETE_SECONDS
        return self.HISTORICAL_SECONDS

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
            args=(cid, comp),
            daemon=True,
            name=f"sbb-day-state-enroll-{cid.lower()}",
        ).start()

    def _enqueue_competition_dates_after_registration(self, cid, comp=None):
        # Competition Builder publishes registry membership immediately before its
        # schedule rows. Retry briefly, then warm SPECIAL_EVENT dates in the
        # background. Dynamic leagues do not enqueue an entire season.
        comp = dict(comp or {})
        if comp.get("dayStateEnabled", True) is False:
            return
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
        if not dates:
            return

        today = datetime.strptime(self.today(), "%Y-%m-%d").date()
        typ = str(comp.get("type") or "").upper()
        if typ == "SPECIAL_EVENT":
            # Warm the closest completed dates first, then upcoming event dates.
            def rank(value):
                d = datetime.strptime(value, "%Y-%m-%d").date()
                delta = (d - today).days
                return (1 if delta > 0 else 0, abs(delta))
            dates.sort(key=rank)
        else:
            # A data-driven league may contain hundreds/thousands of dates. Day
            # State only prewarms its near-live window; old dates remain on-demand.
            dates = [
                value for value in dates
                if abs((datetime.strptime(value, "%Y-%m-%d").date() - today).days) <= 2
            ]

        for value in dates:
            if self.enqueue(value, priority=False):
                self.prewarm_queued += 1

    def enqueue(self, day, *, priority=False):
        day = _clean_date(day)
        if not day:
            return False
        with self.lock:
            if day in self.queued:
                # A user-selected date must jump ahead of background tournament
                # warmup rather than waiting behind every queued historical day.
                if priority:
                    try:
                        self.queue.remove(day)
                    except ValueError:
                        pass
                    self.queue.appendleft(day)
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

    def _future_catalog_event_count(self, day):
        if not day or day <= self.today():
            return 0
        try:
            return int(self.server.HISTORY_REPOSITORY.catalog_event_count(
                date_from=day, date_to=day
            ) or 0)
        except Exception:
            return 0

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

    def _build_mutex(self, day):
        with self.lock:
            mutex = self.build_locks.get(day)
            if mutex is None:
                mutex = threading.Lock()
                self.build_locks[day] = mutex
            return mutex

    def build(self, day):
        day = _clean_date(day)
        if not day:
            raise ValueError("YYYY-MM-DD day required")
        requested_at = time.time()
        mutex = self._build_mutex(day)
        with mutex:
            # Collapse a worker build and a simultaneous cold ribbon fallback into
            # one canonical computation.
            with self.lock:
                concurrent = self.cache.get(day)
            if not concurrent:
                concurrent = self.store.get(day)
                if concurrent:
                    with self.lock:
                        self.cache[day] = concurrent
            if concurrent and float(concurrent.get("generatedAt") or 0) >= requested_at - 0.05:
                return concurrent

            return self._build_locked(day)

    def _build_locked(self, day):
        started = time.perf_counter()

        score_rows_fn = getattr(self.server, "_history_day_score_rows")
        plans_fn = getattr(self.server, "_history_day_ribbon_plans")
        inventory_fn = getattr(self.server, "_history_day_score_inventory_complete")

        score_rows = score_rows_fn(day)
        score_rows, projection_diagnostics = _merge_future_catalog_rows(
            self.server, day, score_rows, self.today()
        )
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
            "engineVersion":"4.7.9",
            "date":day,
            "generatedAt":generated,
            "staleAfter":generated + ttl,
            "freshForSeconds":ttl,
            "registryRevision":registry.revision(),
            "sourceRevision":self._source_revision(),
            "scoreRowsByLeague":score_rows,
            "scoreGameCount":games,
            "projectionDiagnostics":projection_diagnostics,
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
        snapshots = self.store.status(31)
        for row in snapshots:
            try:
                snap = self.store.get(row.get("day"))
                row["stale_after"] = float(row.get("generated_at") or 0) + self.freshness_seconds(row.get("day"), snap or {})
            except Exception:
                pass
        return {
            "ok":True,
            "version":"4.7.9",
            "today":today,
            "builds":self.builds,
            "cacheHits":self.hits,
            "cacheMisses":self.misses,
            "queueDepth":len(queue),
            "queue":queue[:25],
            "registryEvents":self.registry_events,
            "registryRevision":registry.revision(),
            "prewarmQueued":self.prewarm_queued,
            "prewarmBuilt":self.prewarm_built,
            "lastError":self.last_error,
            "snapshots":snapshots,
            "focusDates":[day for day,until in self.focus_dates.items() if until>now],
        }

    def worker(self):
        # Initial hot-window warmup.
        today = datetime.strptime(self.today(), "%Y-%m-%d").date()
        for delta in (-1,0,1,2):
            self.enqueue((today + timedelta(days=delta)).isoformat(), priority=(delta in (0,-1)))
        self.next_today_refresh = time.time()

        while self.running:
            now = time.time()
            for day, until in list(self.focus_dates.items()):
                if until <= now:
                    self.focus_dates.pop(day, None)
                else:
                    self.enqueue(day, priority=True)

            # v4.7.5 fairness: today's snapshot gets a timed refresh slot instead
            # of being appended to the front on every loop. This lets tournament
            # prewarm dates actually drain from the queue.
            if now >= self.next_today_refresh:
                self.enqueue(self.today(), priority=True)
                self.next_today_refresh = now + self.HOT_TODAY_SECONDS

            day = None
            with self.lock:
                if self.queue:
                    day = self.queue.popleft()
                    self.queued.discard(day)
            if day:
                try:
                    self.get(day, force=True)
                    if day != self.today():
                        self.prewarm_built += 1
                    self.last_error = ""
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                time.sleep(0.15 if day != self.today() else 0.5)
                continue

            time.sleep(1)

    def serve_day_state(self, handler, parsed):
        qs = parse_qs(parsed.query)
        day = _clean_date((qs.get("date") or [""])[-1])
        if not day:
            return self.server.send_json(handler, {"ok":False,"error":"DATE_REQUIRED"}, 400)

        # v4.7.1: browser reads never build Day State synchronously. A selected
        # date is moved to the front of the background queue; the request gets a
        # fresh/stale snapshot immediately, or a PENDING response when no snapshot
        # exists yet. This removes the cache-hit/cache-miss latency lottery.
        self.focus(day)
        try:
            payload = self.get(day, allow_build=False)
        except Exception as exc:
            return self.server.send_json(
                handler,
                {"ok":False,"error":"DAY_STATE_READ_FAILED","message":str(exc)},
                500,
            )

        if payload is None:
            # Future schedule rows are local canonical catalog reads. When the
            # catalog already proves scheduled games exist, do one serialized
            # canonical build instead of returning a cold placeholder that cannot
            # produce a future score card.
            canonical_future = self._future_catalog_event_count(day)
            if canonical_future > 0:
                try:
                    payload = dict(self.build(day))
                    payload["cache"] = {
                        **(payload.get("cache") or {}),
                        "state":"FUTURE_CATALOG_REBUILT",
                        "ageSeconds":0,
                    }
                except Exception:
                    payload = None
            if payload is None:
                return self.server.send_json(
                    handler,
                    {
                        "ok":True,
                        "pending":True,
                        "date":day,
                        "cache":{"state":"COLD_WARMING","ageSeconds":0},
                        "message":"Day State is warming in the background.",
                    },
                    202,
                    {"X-SBB-Day-State":"COLD_WARMING"},
                )

        # A pre-v4.7.8 or otherwise incomplete future snapshot may be "fresh" by
        # age while still missing canonical scheduled events. Repair only that
        # proven mismatch; normal current/history reads remain nonblocking.
        if day > self.today():
            canonical_future = self._future_catalog_event_count(day)
            projected_games = int((payload.get("summary") or {}).get("games") or 0)
            if canonical_future > projected_games:
                try:
                    payload = dict(self.build(day))
                    payload["cache"] = {
                        **(payload.get("cache") or {}),
                        "state":"FUTURE_CATALOG_REBUILT",
                        "ageSeconds":0,
                    }
                except Exception:
                    pass

        state = str((payload.get("cache") or {}).get("state") or "READY")
        if state == "STALE":
            self.enqueue(day, priority=True)
            payload = dict(payload)
            payload["refreshQueued"] = True
            payload["cache"] = {**(payload.get("cache") or {}), "state":"STALE_REFRESHING"}
            state = "STALE_REFRESHING"

        return self.server.send_json(
            handler,
            payload,
            200,
            {"X-SBB-Day-State":state},
        )

    def serve_ribbon(self, handler, parsed):
        qs = parse_qs(parsed.query)
        day = _clean_date((qs.get("date") or [""])[-1])
        if not day:
            return self.server.send_json(handler, {"ok":False,"error":"DATE_REQUIRED"}, 400)

        # The ribbon route is cache-only. On a totally cold date, immediately
        # hand control back to the established history-ribbon handler instead of
        # blocking the HTTP request while Day State calculates the date.
        self.focus(day)
        try:
            payload = self.get(day, allow_build=False)
        except Exception:
            return False
        if payload is None:
            # The fallback route is allowed to wait for the canonical Day State
            # build, but build() is serialized per date so it cannot duplicate a
            # background worker calculation. The completed snapshot is persisted
            # for every later ribbon visit.
            try:
                payload = self.get(day, allow_build=True)
                payload = dict(payload)
                payload["cache"] = {**(payload.get("cache") or {}), "state":"COLD_FALLBACK_REBUILT"}
            except Exception:
                return False

        state = str((payload.get("cache") or {}).get("state") or "READY")
        if state == "STALE":
            self.enqueue(day, priority=True)
            payload = dict(payload)
            payload["cache"] = {**(payload.get("cache") or {}), "state":"STALE_REFRESHING"}

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
                    "engineVersion":"4.7.9",
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

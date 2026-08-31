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

def _sanitize_event_plans(server, plans):
    """Revalidate persisted EVENT_MEDIA at the Day State read boundary.

    The normalized catalog may contain a relationship written by an older matcher.
    Current Event Matcher evidence is authoritative: stale explicit-date/team
    conflicts are removed from the compact ribbon plan before the browser sees them.
    """
    stats={"checked":0,"rejected":0,"errors":0,"ambiguousAssets":0,"ambiguousRejected":0,"specialProofAccepted":0,"persistedAssignedAccepted":0}
    matcher=getattr(server,"_history_media_match_evidence",None)
    if not callable(matcher) or not isinstance(plans,dict):
        return plans,stats
    out={}
    for key,raw in plans.items():
        if not isinstance(raw,dict):
            out[key]=raw;continue
        plan=dict(raw)
        event=dict(plan.get("event") or {})
        league=str(plan.get("league") or str(key).split(":",1)[0] or event.get("competitionId") or event.get("__sbbLeague") or "").upper()
        date=str(plan.get("date") or event.get("__sbbDate") or event.get("gameDate") or event.get("date") or "")[:10]
        if league:
            event.setdefault("competitionId",league);event.setdefault("__sbbLeague",league);event.setdefault("league",league)
        if date:
            event.setdefault("__sbbDate",date);event.setdefault("date",date);event.setdefault("gameDate",date)

        def valid(item):
            if not isinstance(item,dict):return False
            stats["checked"]+=1
            # EVENT_MEDIA is the normalized relationship authority for persisted
            # ownership, but not every historical matcher result is equally strong.
            # Durable exact/provider/special-event proof may survive a later generic
            # matcher disagreement. Ordinary TITLE_TEAM_PAIR-style relationships
            # still pass through the current matcher so stale wrong-team/date links
            # continue to fail closed.
            method=str(item.get("associationMethod") or "").upper()
            canonical=str(item.get("canonicalEventKey") or "")
            scope=str(item.get("mediaScope") or "").upper()
            runtime=str(item.get("runtimeCatalogState") or item.get("runtimeState") or "").upper()
            if runtime=="FAILED" or runtime=="FAILED-QUARANTINED":
                stats["rejected"]+=1
                return False

            strong_methods={
                "PROVIDER_EVENT_ID","PROVIDER_SOURCE_EVENT_ID","PROVIDER_GAME_PK",
                "EXACT_EVENT_ID","CANONICAL_EVENT_ID",
            }
            direct_ids={str(item.get(k)) for k in ("scoreEventId","matchId","espnEventId","canonicalEventId") if item.get(k) not in (None,"")}
            event_ids={str(event.get(k)) for k in ("scoreEventId","matchId","espnEventId","canonicalEventId","eventId","id") if event.get(k) not in (None,"")}
            game_pk_match=(item.get("gamePk") not in (None,"") and event.get("gamePk") not in (None,"") and str(item.get("gamePk"))==str(event.get("gamePk")))
            proof=item.get("sbbPreprovenAssociation")
            proof_ok=(isinstance(proof,dict)
                      and str(proof.get("associationState") or "").upper()=="ASSIGNED"
                      and str(proof.get("canonicalEventKey") or canonical)==str(key))
            # ribbon_media_for_date() injects assetKey from history_source_media.
            # Its presence, together with the exact canonical event key and GAME
            # scope, proves this plan came from an ASSIGNED normalized EVENT_MEDIA
            # relationship rather than an untrusted legacy/browser-shaped plan.
            normalized_asset=bool(str(item.get("assetKey") or "").strip())
            durable=(normalized_asset or method.startswith("SPECIAL_EVENT_") or method in strong_methods
                     or bool(direct_ids and event_ids and direct_ids & event_ids)
                     or game_pk_match or proof_ok)
            if canonical==str(key) and scope=="GAME" and durable:
                stats["persistedAssignedAccepted"]+=1
                if method.startswith("SPECIAL_EVENT_"):
                    stats["specialProofAccepted"]+=1
                return True

            # Ordinary persisted title/team associations remain valid when the
            # current matcher can still prove them. This preserves good historical
            # links while rejecting stale/wrong associations like an old same-team
            # recap attached to a different date or game.
            try:
                scoped,evidence=matcher(dict(item),event)
            except Exception:
                stats["errors"]+=1;return True
            ok=str((scoped or {}).get("mediaScope") or "").upper()=="GAME" and str((evidence or {}).get("associationState") or "").upper()=="ASSIGNED"
            if not ok:stats["rejected"]+=1
            return ok

        for field in ("media","playable"):
            values=plan.get(field)
            if isinstance(values,list):plan[field]=[item for item in values if valid(item)]
        playable=plan.get("playable") or []
        plan["primary"]=playable[0] if playable else None
        plan["catalogPlayableCount"]=len(playable)
        plan["catalogTier"]=str((plan.get("primary") or {}).get("recapTier") or "").upper() or "NONE"
        out[key]=plan

    # A title-only team/date match is not sufficient to distinguish two games of a
    # same-day doubleheader. One physical asset appearing under multiple canonical
    # event plans is ambiguous unless provider identity proves one unique owner.
    owners={}
    def asset_key(item):
        if not isinstance(item,dict):return ""
        if item.get("youtubeId"):return "YT:"+str(item.get("youtubeId"))
        if item.get("mediaUrl"):return "URL:"+str(item.get("mediaUrl"))
        return "ID:"+str(item.get("assetKey") or item.get("id") or "") if (item.get("assetKey") or item.get("id")) else ""
    def direct_identity(item,event):
        media_ids={str(item.get(k)) for k in ("scoreEventId","matchId","espnEventId","canonicalEventId") if item.get(k) not in (None,"")}
        event_ids={str(event.get(k)) for k in ("scoreEventId","matchId","espnEventId","canonicalEventId","eventId","id") if event.get(k) not in (None,"")}
        if media_ids and event_ids and media_ids & event_ids:return True
        return item.get("gamePk") not in (None,"") and event.get("gamePk") not in (None,"") and str(item.get("gamePk"))==str(event.get("gamePk"))
    for key,plan in out.items():
        if not isinstance(plan,dict):continue
        event=plan.get("event") or {}
        seen=set()
        for item in plan.get("playable") or []:
            physical=asset_key(item)
            if not physical or physical in seen:continue
            seen.add(physical);owners.setdefault(physical,[]).append((key,item,event))
    for physical,found in owners.items():
        plan_keys={x[0] for x in found}
        if len(plan_keys)<2:continue
        stats["ambiguousAssets"]+=1
        proven={key for key,item,event in found if direct_identity(item,event)}
        keep=next(iter(proven)) if len(proven)==1 else None
        for key in plan_keys:
            if key==keep:continue
            plan=out.get(key) or {}
            for field in ("media","playable"):
                values=plan.get(field)
                if not isinstance(values,list):continue
                before=len(values);plan[field]=[item for item in values if asset_key(item)!=physical]
                stats["ambiguousRejected"]+=before-len(plan[field])
            playable=plan.get("playable") or []
            plan["primary"]=playable[0] if playable else None
            plan["catalogPlayableCount"]=len(playable)
            plan["catalogTier"]=str((plan.get("primary") or {}).get("recapTier") or "").upper() or "NONE"
    return out,stats


def _event_identity(event):
    """Stable-enough canonical event identity for Day State row merging."""
    if not isinstance(event, dict):
        return ""
    for key in ("scoreEventId","matchId","espnEventId","gamePk","canonicalEventId","eventId","id"):
        value = event.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _catalog_score_rows_for_day(server, day):
    """Fast canonical score-only projection for one date.

    This path intentionally does not build media plans, run discovery, contact
    providers, or assemble historical enrichment. It is safe for first paint.
    """
    rows_by_league = {}
    diagnostics = {
        "catalogCandidates": 0,
        "catalogProjected": 0,
        "leagues": [],
    }
    repo = getattr(server, "HISTORY_REPOSITORY", None)
    if repo is None or not hasattr(repo, "catalog_events"):
        return rows_by_league, diagnostics

    try:
        catalog = repo.catalog_events(date_from=day, date_to=day, limit=50000) or []
    except Exception:
        catalog = []

    diagnostics["catalogCandidates"] = len(catalog)
    seen = {}
    leagues = set()

    for catalog_row in catalog:
        if not isinstance(catalog_row, dict):
            continue
        league = str(catalog_row.get("league") or "").upper()
        if not league:
            continue

        event_id = str(catalog_row.get("eventId") or "")
        event = dict(catalog_row.get("event") or {})
        # Older catalog rows may expose useful canonical fields at the outer row.
        if not event:
            for key in (
                "id","eventId","matchId","scoreEventId","espnEventId","gamePk",
                "date","gameDate","scheduledAt","status","away","home",
                "awayScore","homeScore","league","competitionId"
            ):
                if catalog_row.get(key) not in (None, ""):
                    event[key] = catalog_row.get(key)

        identity = _event_identity(event) or event_id
        league_seen = seen.setdefault(league, set())
        if identity and identity in league_seen:
            continue

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

        rows_by_league.setdefault(league, []).append(event)
        if identity:
            league_seen.add(identity)
        diagnostics["catalogProjected"] += 1
        leagues.add(league)

    diagnostics["leagues"] = sorted(leagues)
    return rows_by_league, diagnostics


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

    def _build_thin_catalog_snapshot(self, day, *, persist=True):
        """Build a score-only historical Day State snapshot for first paint."""
        day = _clean_date(day)
        if not day:
            raise ValueError("YYYY-MM-DD day required")
        started = time.perf_counter()
        score_rows, catalog_diag = _catalog_score_rows_for_day(self.server, day)

        games = sum(len(rows or []) for rows in score_rows.values())
        status_counts = {"LIVE":0,"FINAL":0,"SCHEDULED":0,"POSTPONED":0,"CANCELLED":0}
        for rows in score_rows.values():
            for event in rows or []:
                status = _event_status(event)
                status_counts[status] = status_counts.get(status, 0) + 1

        summary = {
            "games":games,
            "live":status_counts.get("LIVE",0),
            "final":status_counts.get("FINAL",0),
            "scheduled":status_counts.get("SCHEDULED",0),
            "postponed":status_counts.get("POSTPONED",0),
            "cancelled":status_counts.get("CANCELLED",0),
            "playable":0,
            "competitions":sum(1 for rows in score_rows.values() if rows),
        }
        generated = time.time()
        # Thin snapshots exist only to give the browser immediate canonical scores.
        # The focused background worker replaces them with a full snapshot.
        snapshot = {
            "ok":True,
            "version":str(getattr(self.server, "APP_VERSION", "")),
            "engineVersion":"4.7.20",
            "date":day,
            "generatedAt":generated,
            "staleAfter":generated + 15,
            "freshForSeconds":15,
            "registryRevision":registry.revision(),
            "sourceRevision":self._source_revision(),
            "scoreRowsByLeague":score_rows,
            "scoreGameCount":games,
            "projectionDiagnostics":{
                "future":False,
                "thinCatalog":True,
                "catalogCandidates":catalog_diag.get("catalogCandidates",0),
                "catalogAdded":catalog_diag.get("catalogProjected",0),
                "rowsBefore":0,
                "rowsAfter":games,
                "leaguesAdded":catalog_diag.get("leagues",[]),
            },
            "eventPlans":{},
            "catalogFirst":True,
            "compact":True,
            "catalogEventCount":catalog_diag.get("catalogCandidates",0),
            "scoreInventoryComplete":False,
            "thinSnapshot":True,
            "summary":summary,
            "facts":self._build_facts(score_rows, {}, summary),
            "timing":{
                "thinCatalogMs":round((time.perf_counter()-started)*1000.0,1),
                "buildMs":round((time.perf_counter()-started)*1000.0,1),
            },
        }
        if persist:
            self.store.put(snapshot)
            with self.lock:
                self.cache[day] = snapshot
                self.last_build[day] = generated
        return snapshot

    def _cold_historical_thin(self, day):
        if not day or day >= self.today():
            return None
        try:
            payload = dict(self._build_thin_catalog_snapshot(day, persist=True))
            payload["cache"] = {
                **(payload.get("cache") or {}),
                "state":"COLD_THIN_CATALOG",
                "ageSeconds":0,
            }
            return payload
        except Exception as exc:
            self.last_error = f"thin:{type(exc).__name__}: {exc}"
            return None

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
        media_safety_started = time.perf_counter()
        plans, media_safety = _sanitize_event_plans(self.server, plans)
        media_safety_ms = round((time.perf_counter()-media_safety_started)*1000.0,1)
        projection_diagnostics = {**projection_diagnostics,
            "mediaSafetyChecked":int(media_safety.get("checked") or 0),
            "mediaSafetyRejected":int(media_safety.get("rejected") or 0),
            "mediaSafetyErrors":int(media_safety.get("errors") or 0),
            "mediaSafetyAmbiguousAssets":int(media_safety.get("ambiguousAssets") or 0),
            "mediaSafetyAmbiguousRejected":int(media_safety.get("ambiguousRejected") or 0),
            "mediaSafetySpecialProofAccepted":int(media_safety.get("specialProofAccepted") or 0),
            "mediaSafetyPersistedAssignedAccepted":int(media_safety.get("persistedAssignedAccepted") or 0),
        }
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
            "engineVersion":"4.7.20",
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
            "timing":{"buildMs":round((time.perf_counter()-started)*1000.0,1),"mediaSafetyMs":media_safety_ms},
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

        # A persisted historical snapshot is valuable first-paint state. v4.7.19 discarded
        # every prior generation before proving that the replacement projection was
        # at least as complete, which turned healthy historical WATCH cards into
        # FIND while the new read model caught up. Preserve a non-empty historical
        # snapshot across generation changes and refresh it in the background. Only
        # empty/incomplete generation rows are discarded for cold catalog recovery.
        if cached and str(cached.get("engineVersion") or "") != "4.7.20":
            old_engine=str(cached.get("engineVersion") or "UNKNOWN")
            old_games=int((cached.get("summary") or {}).get("games") or cached.get("scoreGameCount") or 0)
            if day < self.today() and old_games>0:
                cached=dict(cached)
                cached["engineCompatibility"]={"state":"PRESERVED_NONEMPTY_HISTORY","from":old_engine,"to":"4.7.20"}
                self.enqueue(day, priority=True)
            else:
                cached = None
                with self.lock:
                    self.cache.pop(day, None)

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
            "version":"4.7.18",
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

    def serve_thin_probe(self, handler, parsed):
        """Non-mutating score-only catalog projection used by efficiency certification."""
        qs = parse_qs(parsed.query)
        day = _clean_date((qs.get("date") or [""])[-1])
        if not day:
            return self.server.send_json(handler, {"ok":False,"error":"DATE_REQUIRED"}, 400)

        started = time.perf_counter()
        try:
            score_rows, catalog_diag = _catalog_score_rows_for_day(self.server, day)
            games = sum(len(rows or []) for rows in score_rows.values())
            counts = {"LIVE":0,"FINAL":0,"SCHEDULED":0,"POSTPONED":0,"CANCELLED":0}
            for rows in score_rows.values():
                for event in rows or []:
                    status = _event_status(event)
                    counts[status] = counts.get(status, 0) + 1
            elapsed = round((time.perf_counter()-started)*1000.0, 1)
            return self.server.send_json(
                handler,
                {
                    "ok":True,
                    "date":day,
                    "thinProbe":True,
                    "scoreGameCount":games,
                    "summary":{
                        "games":games,
                        "live":counts.get("LIVE",0),
                        "final":counts.get("FINAL",0),
                        "scheduled":counts.get("SCHEDULED",0),
                        "postponed":counts.get("POSTPONED",0),
                        "cancelled":counts.get("CANCELLED",0),
                        "competitions":sum(1 for rows in score_rows.values() if rows),
                    },
                    "projectionDiagnostics":{
                        "catalogCandidates":int(catalog_diag.get("catalogCandidates") or 0),
                        "catalogProjected":int(catalog_diag.get("catalogProjected") or 0),
                        "leagues":list(catalog_diag.get("leagues") or []),
                    },
                    "cache":{"state":"THIN_PROBE","ageSeconds":0},
                    "timing":{"thinCatalogMs":elapsed},
                },
                200,
                {"X-SBB-Day-State":"THIN_PROBE"},
            )
        except Exception as exc:
            return self.server.send_json(
                handler,
                {
                    "ok":False,
                    "error":"THIN_PROBE_FAILED",
                    "errorType":type(exc).__name__,
                    "message":str(exc),
                    "date":day,
                    "timing":{"thinCatalogMs":round((time.perf_counter()-started)*1000.0,1)},
                },
                500,
                {"X-SBB-Day-State":"THIN_PROBE_FAILED"},
            )

    def serve_day_state(self, handler, parsed):
        qs = parse_qs(parsed.query)
        day = _clean_date((qs.get("date") or [""])[-1])
        if not day:
            return self.server.send_json(handler, {"ok":False,"error":"DATE_REQUIRED"}, 400)

        # v4.7.10: interactive browser reads never wait for the expensive full
        # historical build. Read a persisted snapshot first. A totally cold past
        # date gets a local score-only catalog projection immediately, then the
        # background worker is focused to replace it with the full snapshot.
        thin_probe = str((qs.get("thinProbe") or [""])[-1]).lower() in ("1","true","yes")
        if thin_probe:
            # Compatibility alias; certification uses the dedicated route so this
            # request cannot collide with ordinary Day State cache/inflight identity.
            return self.serve_thin_probe(handler, parsed)

        try:
            payload = self.get(day, allow_build=False)
        except Exception as exc:
            return self.server.send_json(
                handler,
                {"ok":False,"error":"DAY_STATE_READ_FAILED","message":str(exc)},
                500,
            )

        if payload is None and day < self.today():
            payload = self._cold_historical_thin(day)

        # Queue the full canonical build only after a cold thin snapshot has been
        # produced, so the worker cannot race first paint and hold it for seconds.
        self.focus(day)

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
                    "engineVersion":"4.7.20",
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
            if parsed.path == "/api/day-state/thin":
                return _ENGINE.serve_thin_probe(self, parsed)
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

# v4.7.17 persistent AP Top 25 College Football season service.
try:
    from . import cfb_ranked as _cfb_ranked
    _cfb_ranked.install()
except Exception:
    pass

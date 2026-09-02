"""Sports Big Board v5.1.22 — durable Game Center identity + tennis routing.

Two repairs live here because they share one architectural rule: the browser sends
sporting-event identity, while the backend owns provider identity.

1. Previously-successful Game Centers are indexed in SQLite by event fingerprint
   (competition/date/away/home). A changed score-provider alias can therefore resolve
   to the Game Center already stored locally without a network schedule lookup.
2. Registry-defined tennis competitions are routed through the canonical tennis Game
   Center adapter at the backend function boundary. This does not depend on Handler
   wrapper ordering and therefore cannot fall through to the fixed-league validator.
"""
from __future__ import annotations

import copy
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone

from . import competition_registry as registry

VERSION = "5.1.22-game-center-identity-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False

_STATE = {
    "version": VERSION,
    "installed": False,
    "backfilled": 0,
    "fingerprintHits": 0,
    "dateScanHits": 0,
    "aliasesRepaired": 0,
    "providerFetchAvoided": 0,
    "tennisRoutes": 0,
    "tennisHits": 0,
    "tennisPending": 0,
    "ambiguous": 0,
    "lastError": "",
}


def _clean(value):
    return str(value or "").strip()


def _event_date(data, scheduled=""):
    event=(data or {}).get("event") or {}
    raw=_clean(scheduled or event.get("scheduledAt") or event.get("date") or (data or {}).get("date"))
    m=re.match(r"^(\d{4}-\d{2}-\d{2})",raw)
    return m.group(1) if m else ""


def _team_from_data(data, side):
    data=data or {};board=data.get("scoreboard") or {};event=data.get("event") or {}
    return ((board.get(side) or {}).get("team") or event.get(f"{side}Team") or {})


def _start_epoch(value):
    text=_clean(value)
    if not text:return 0.0
    try:
        dt=datetime.fromisoformat(text.replace("Z","+00:00"))
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).timestamp()
    except Exception:return 0.0


def _ensure_schema(repo):
    with repo._lock, repo._db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS game_center_fingerprints(
                competition TEXT NOT NULL,
                event_date TEXT NOT NULL,
                away_key TEXT NOT NULL,
                home_key TEXT NOT NULL,
                game_number INTEGER NOT NULL DEFAULT 0,
                scheduled_at TEXT NOT NULL DEFAULT '',
                resolved_event_id TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(competition,event_date,away_key,home_key,resolved_event_id)
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_gc_fingerprint_lookup ON game_center_fingerprints(competition,event_date,away_key,home_key)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_gc_fingerprint_resolved ON game_center_fingerprints(competition,resolved_event_id)")


def _fingerprint_values(server, competition, event_id, data, scheduled="", updated_at=None):
    data=data or {};event=data.get("event") or {}
    away=_team_from_data(data,"away");home=_team_from_data(data,"home")
    clean_team=getattr(server,"_gc_clean_team_hint",lambda v:re.sub(r"[^a-z0-9]","",_clean(v).lower()))
    away_key=clean_team(away);home_key=clean_team(home);date=_event_date(data,scheduled)
    try:game_number=int(event.get("gameNumber") or data.get("gameNumber") or 0)
    except Exception:game_number=0
    scheduled_at=_clean(scheduled or event.get("scheduledAt") or data.get("scheduledAt"))
    return {
        "competition":_clean(competition).upper(),"event_date":date,
        "away_key":away_key,"home_key":home_key,"game_number":game_number,
        "scheduled_at":scheduled_at,"resolved_event_id":_clean(event_id),
        "updated_at":float(updated_at or time.time()),
    }


def _upsert_fingerprint(server, competition, event_id, data, scheduled="", updated_at=None, *, hint_keys=None):
    repo=server.GAME_CENTER_REPOSITORY
    row=_fingerprint_values(server,competition,event_id,data,scheduled,updated_at)
    if hint_keys:
        row["away_key"]=_clean(hint_keys[0]);row["home_key"]=_clean(hint_keys[1])
    if not all(row.get(k) for k in ("competition","event_date","away_key","home_key","resolved_event_id")):
        return False
    with repo._lock, repo._db() as con:
        con.execute("""
            INSERT INTO game_center_fingerprints(
                competition,event_date,away_key,home_key,game_number,scheduled_at,resolved_event_id,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(competition,event_date,away_key,home_key,resolved_event_id) DO UPDATE SET
                game_number=excluded.game_number,scheduled_at=excluded.scheduled_at,updated_at=excluded.updated_at
        """,(
            row["competition"],row["event_date"],row["away_key"],row["home_key"],row["game_number"],
            row["scheduled_at"],row["resolved_event_id"],row["updated_at"],
        ))
    return True


def _backfill(server):
    repo=server.GAME_CENTER_REPOSITORY;count=0
    _ensure_schema(repo)
    with repo._lock, repo._db() as con:
        rows=con.execute("SELECT competition,event_id,scheduled_at,updated_at,payload_json FROM game_centers ORDER BY updated_at DESC").fetchall()
    for raw in rows:
        try:
            data=json.loads(raw["payload_json"])
            if _upsert_fingerprint(server,raw["competition"],raw["event_id"],data,raw["scheduled_at"],raw["updated_at"]):count+=1
        except Exception:continue
    _STATE["backfilled"]=count
    return count


def _rank_candidates(rows,hints):
    if len(rows)<=1:return rows[0] if rows else None
    try:wanted_number=int((hints or {}).get("gameNumber") or 0)
    except Exception:wanted_number=0
    if wanted_number:
        numbered=[r for r in rows if int(r.get("game_number") or 0)==wanted_number]
        if len(numbered)==1:return numbered[0]
        if numbered:rows=numbered
    wanted=_start_epoch((hints or {}).get("start") or (hints or {}).get("scheduledAt"))
    if wanted:
        ranked=[]
        for row in rows:
            actual=_start_epoch(row.get("scheduled_at"))
            if actual:ranked.append((abs(actual-wanted),row))
        ranked.sort(key=lambda x:x[0])
        if ranked and (len(ranked)==1 or ranked[0][0]+60<ranked[1][0]):return ranked[0][1]
    _STATE["ambiguous"]+=1
    return None


def _fingerprint_lookup(server, competition, hints):
    hints=hints or {};date=_clean(hints.get("date"))[:10]
    clean_team=server._gc_clean_team_hint
    away_key=clean_team(hints.get("away"));home_key=clean_team(hints.get("home"))
    if not (date and away_key and home_key):return ""
    repo=server.GAME_CENTER_REPOSITORY
    with repo._lock, repo._db() as con:
        rows=[dict(r) for r in con.execute("""
            SELECT resolved_event_id,game_number,scheduled_at,updated_at
            FROM game_center_fingerprints
            WHERE competition=? AND event_date=? AND away_key=? AND home_key=?
            ORDER BY updated_at DESC LIMIT 12
        """,(_clean(competition).upper(),date,away_key,home_key)).fetchall()]
    chosen=_rank_candidates(rows,hints)
    if not chosen:return ""
    event_id=_clean(chosen.get("resolved_event_id"))
    record=server._game_center_cached_record(competition,event_id) if event_id else None
    if record and server._game_center_record_matches_hints(record,hints):
        _STATE["fingerprintHits"]+=1
        return event_id
    return ""


def _cached_date_scan(server, competition, hints):
    """One bounded local rescue for pre-v5.1.22 snapshots without matching keys."""
    hints=hints or {};date=_clean(hints.get("date"))[:10]
    if not date or not hints.get("away") or not hints.get("home"):return ""
    repo=server.GAME_CENTER_REPOSITORY;comp=_clean(competition).upper()
    with repo._lock, repo._db() as con:
        raw=con.execute("""
            SELECT event_id,scheduled_at,updated_at,payload_json
            FROM game_centers
            WHERE competition=? AND substr(scheduled_at,1,10)=?
            ORDER BY updated_at DESC LIMIT 96
        """,(comp,date)).fetchall()
    candidates=[]
    for row in raw:
        try:data=json.loads(row["payload_json"])
        except Exception:continue
        record={"data":data,"eventId":row["event_id"],"scheduledAt":row["scheduled_at"]}
        try:matches=server._game_center_record_matches_hints(record,hints)
        except Exception:matches=False
        if matches:
            vals=_fingerprint_values(server,comp,row["event_id"],data,row["scheduled_at"],row["updated_at"])
            candidates.append(vals)
    chosen=_rank_candidates(candidates,hints)
    if not chosen:return ""
    event_id=_clean(chosen.get("resolved_event_id"))
    if not event_id:return ""
    away_key=server._gc_clean_team_hint(hints.get("away"));home_key=server._gc_clean_team_hint(hints.get("home"))
    record=server._game_center_cached_record(comp,event_id)
    if record:
        _upsert_fingerprint(server,comp,event_id,record.get("data") or {},record.get("scheduledAt") or "",record.get("savedAt"),hint_keys=(away_key,home_key))
    _STATE["dateScanHits"]+=1
    return event_id


def _repair_alias(server, competition, requested, resolved, hints):
    if not requested or not resolved or requested==resolved:return
    server.GAME_CENTER_REPOSITORY.put_alias(
        competition,requested,resolved,(hints or {}).get("date") or "",
        (hints or {}).get("away") or "",(hints or {}).get("home") or "",
    )
    _STATE["aliasesRepaired"]+=1


def _is_tennis(competition):
    row=registry.get(competition) or {}
    return _clean(row.get("sportId")).lower()=="tennis"


def _tennis_open(server, competition, event_id, force=False, hints=None):
    """Function-boundary tennis route used by the generic async endpoint."""
    from . import tennis_game_center as tennis
    hints=dict(hints or {});cid=_clean(competition).upper();eid=_clean(event_id)
    comp=tennis._find_comp(cid) or registry.get(cid) or {"id":cid,"name":cid,"sportId":"tennis"}
    qs={k:[_clean(v)] for k,v in hints.items()}
    event=(tennis._find_event(comp,eid)
           or tennis._history_event(server,cid,eid,_clean(hints.get("date"))[:10])
           or tennis._synthetic_event(cid,eid,qs))
    if not event:
        raise ValueError("Canonical tennis event identity is incomplete")
    comp={**comp,"id":cid,"sportId":"tennis"}
    key=tennis._route_key(cid,eid)
    if force:
        with tennis._ROUTE_LOCK:tennis._ROUTE_RESULTS.pop(key,None)
    hit=tennis._result_get(key)
    if hit and hit.get("data") and not force:
        _STATE["tennisHits"]+=1
        return copy.deepcopy(hit["data"]),"TENNIS-CANONICAL-HIT",False,eid
    if hit and hit.get("error") and not force:
        raise RuntimeError(_clean(hit.get("error")))
    with tennis._ROUTE_LOCK:job=dict(tennis._ROUTE_JOBS.get(key) or {})
    if force or not job or not job.get("pending"):
        tennis._start_route_job(comp,event,eid)
    _STATE["tennisPending"]+=1
    return None,"PENDING",True,eid


def _install_server_patch(server):
    if getattr(server,"__sbbGameCenterIdentityV5122",False):return True
    required=("GAME_CENTER_REPOSITORY","_resolve_game_center_event_id","_game_center_open","_game_center_store",
              "_gc_clean_team_hint","_game_center_cached_record","_game_center_record_matches_hints")
    if not all(hasattr(server,name) for name in required):return False
    _backfill(server)

    original_resolve=server._resolve_game_center_event_id
    original_open=server._game_center_open
    original_store=server._game_center_store

    def resolve(competition,event_id,hints=None,allow_fetch=False):
        competition=_clean(competition).upper();requested=_clean(event_id);hints=hints or {}
        if _is_tennis(competition):return requested
        # First use all pre-existing zero-network resolution paths: durable aliases,
        # exact repository ids and already-resident event index rows.
        try:resolved=original_resolve(competition,requested,hints,allow_fetch=False)
        except Exception:resolved=""
        if resolved:return resolved
        # Then use the durable event fingerprint index. This is the key v5.1.22
        # repair for "we had this Game Center before but the score alias changed".
        resolved=_fingerprint_lookup(server,competition,hints)
        if not resolved:resolved=_cached_date_scan(server,competition,hints)
        if resolved:
            _repair_alias(server,competition,requested,resolved,hints)
            _STATE["providerFetchAvoided"]+=1
            return resolved
        if not allow_fetch:return ""
        return original_resolve(competition,requested,hints,allow_fetch=True)

    def store(competition,event_id,data,saved_at=None):
        result=original_store(competition,event_id,data,saved_at)
        try:
            row=result or server.GAME_CENTER_REPOSITORY.get(competition,event_id) or {}
            payload=(row.get("data") or data or {}) if isinstance(row,dict) else (data or {})
            _upsert_fingerprint(server,competition,event_id,payload,(row or {}).get("scheduledAt") if isinstance(row,dict) else "",(row or {}).get("savedAt") if isinstance(row,dict) else saved_at)
        except Exception as exc:_STATE["lastError"]=f"fingerprint-store:{type(exc).__name__}: {exc}"
        return result

    def open_game_center(competition,event_id,force=False,hints=None):
        if _is_tennis(competition):
            _STATE["tennisRoutes"]+=1
            return _tennis_open(server,competition,event_id,force,hints)
        return original_open(competition,event_id,force,hints)

    resolve.__sbbV5122=True;resolve.__sbbOriginal=original_resolve
    store.__sbbV5122=True;store.__sbbOriginal=original_store
    open_game_center.__sbbV5122=True;open_game_center.__sbbOriginal=original_open
    server._resolve_game_center_event_id=resolve
    server._game_center_store=store
    server._game_center_open=open_game_center
    server.GAME_CENTER_IDENTITY_V5122_STATE=_STATE
    server.__sbbGameCenterIdentityV5122=True
    _STATE["installed"]=True
    try:
        server.MILESTONE_CONSOLE.record("game-center","PASS","v5.1.22 durable Game Center identity + tennis router installed",dict(_STATE))
    except Exception:pass
    return True


def _worker():
    deadline=time.time()+120
    while time.time()<deadline:
        server=sys.modules.get("__main__")
        try:
            if server is not None and _install_server_patch(server):return
        except Exception as exc:_STATE["lastError"]=f"install:{type(exc).__name__}: {exc}"
        time.sleep(.2)


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:return False
        _INSTALLED=True
    threading.Thread(target=_worker,daemon=True,name="sbb-game-center-identity-v5122").start()
    return True


def snapshot():
    return dict(_STATE)


__all__=["VERSION","install","snapshot","_install_server_patch","_fingerprint_lookup","_cached_date_scan"]

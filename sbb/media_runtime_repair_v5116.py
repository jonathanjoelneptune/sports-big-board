"""Sports Big Board v5.1.16 — recent media continuity + ribbon projection repair.

Narrow runtime fixes derived from the v5.1.15 Backend Inspector audit:
- recent MLB finals with no authoritative media are re-opened through the existing
  discovery pipeline in a low-priority background lane;
- special-event/NFL ribbon plans may recover already-authoritative DB media when the
  compact projection is empty;
- retired CFB rows/plans are suppressed at the read-model boundary;
- obviously wrong LLWS links restored by the old v4.7.21 relationship recovery are
  quarantined and filtered before they can reach playback.

No repository-wide scans run on startup.  Provider work begins only after the normal
board has had time to become responsive.
"""
from __future__ import annotations

import copy
import json
import re
import sys
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta

from .history_repository import HistoryRepository

VERSION="5.1.16-media-runtime-repair-1"
_INSTALL_LOCK=threading.Lock()
_INSTALLED=False
_ORIGINAL_EVENT_MEDIA=None


def _clean(v):return str(v or "").strip()

def _event_id(row):
    for key in ("scoreEventId","espnEventId","gameCenterEventId","gamePk","canonicalEventId","eventId","matchId","id"):
        if (row or {}).get(key) not in (None,""):return str((row or {}).get(key))
    return ""

def _usable(item):
    state=_clean((item or {}).get("runtimeCatalogState") or (item or {}).get("runtimeState")).upper()
    return state!="FAILED" and bool((item or {}).get("verifiedPlayable")) and bool((item or {}).get("youtubeId") or (item or {}).get("mediaUrl"))

def _norm(v):
    v=_clean(v).lower().replace("&"," and ")
    v=re.sub(r"[^a-z0-9]+"," ",v)
    return re.sub(r"\s+"," ",v).strip()

def _aliases(team):
    values=[]
    if isinstance(team,dict):
        for k in ("name","displayName","shortName","abbreviation","region","group"):
            if team.get(k):values.append(team.get(k))
        a=team.get("aliases") or []
        if isinstance(a,str):a=[a]
        values.extend(a)
    elif team:values.append(team)
    out=[]
    stop={"ll","little","league","team","baseball","region"}
    for value in values:
        n=_norm(value)
        if n:out.append(n)
        parts=[x for x in n.split() if x not in stop and len(x)>=3]
        out.extend(parts)
    return list(dict.fromkeys(out))

def _team(event,side):
    return (event or {}).get(side+"Team") or (event or {}).get(side) or {}

def _catalog_event(repo,date,league,event_id):
    try:
        rows=repo.catalog_events(league=league,date_from=date,date_to=date,limit=200) or []
    except Exception:return {}
    for row in rows:
        ev=dict((row or {}).get("event") or {})
        if _clean((row or {}).get("eventId") or _event_id(ev))==_clean(event_id):return ev
    return {}

def _explicit_title_pair(title):
    text=_clean(title)
    m=re.search(r"(.+?)\s+(?:vs\.?|versus|v\.?|at)\s+(.+?)(?:\s*[|—–-]\s*|$)",text,re.I)
    return (_norm(m.group(1)),_norm(m.group(2))) if m else ("","")

def _side_matches(text,aliases):
    if not text:return False
    return any(alias and (alias in text or text in alias) for alias in aliases)

def _bad_llws_restore(item,event):
    if _clean((item or {}).get("associationMethod")).upper()!="V4721_DATABASE_AUTHORITY_RESTORE":return False
    left,right=_explicit_title_pair((item or {}).get("title"))
    if not left or not right:return False
    away=_aliases(_team(event,"away"));home=_aliases(_team(event,"home"))
    if not away or not home:return False
    direct=_side_matches(left,away) and _side_matches(right,home)
    reverse=_side_matches(left,home) and _side_matches(right,away)
    return not (direct or reverse)

def _sanitize_media(repo,date,league,event_id,rows):
    if not _clean(league).upper().startswith("LLWS"):return list(rows or [])
    event=_catalog_event(repo,date,_clean(league).upper(),event_id)
    if not event:return list(rows or [])
    return [x for x in (rows or []) if not (isinstance(x,dict) and _bad_llws_restore(x,event))]

def _event_media(self,date,league,event_id,include_failed=True):
    rows=_ORIGINAL_EVENT_MEDIA(self,date,league,event_id,include_failed=include_failed)
    return _sanitize_media(self,_clean(date)[:10],_clean(league).upper(),event_id,rows)


def _purge_retired_cfb_history(server):
    """Surgical second-pass cleanup of the normalized history repository only.

    The old retirement marker can remain valid; this does not rescan state files or
    invalidate Day State caches. It only removes any CFB rows that were reintroduced
    into the live history repository after the original one-time retirement.
    """
    repo=getattr(server,"HISTORY_REPOSITORY",None)
    if repo is None:return {"rows":0}
    changed=0
    try:
        with repo._lock, closing(repo._connect()) as conn:
            statements=(
                "DELETE FROM history_event_media WHERE UPPER(canonical_event_key) LIKE 'CFB:%'",
                "DELETE FROM history_catalog_event WHERE UPPER(COALESCE(league,''))='CFB' OR UPPER(canonical_event_key) LIKE 'CFB:%'",
                "DELETE FROM history_day WHERE UPPER(COALESCE(league,''))='CFB'",
                "DELETE FROM history_event_discovery WHERE UPPER(COALESCE(league,''))='CFB'",
            )
            for sql in statements:
                before=conn.total_changes
                try:conn.execute(sql)
                except Exception:continue
                changed+=conn.total_changes-before
            conn.commit()
    except Exception:pass
    try:
        from . import competition_registry as registry
        registry.unregister("CFB")
    except Exception:pass
    return {"rows":changed}


def _quarantine_bad_llws(server):
    repo=getattr(server,"HISTORY_REPOSITORY",None)
    if repo is None:return {"checked":0,"quarantined":0}
    checked=quarantined=0
    try:
        with repo._lock, closing(repo._connect()) as conn:
            rows=conn.execute("""SELECT em.canonical_event_key,em.asset_key,e.event_date,e.league,e.event_id,e.event_json,s.asset_json
              FROM history_event_media em
              JOIN history_catalog_event e ON e.canonical_event_key=em.canonical_event_key
              JOIN history_source_media s ON s.asset_key=em.asset_key
              WHERE em.association_state='ASSIGNED'
                AND em.association_method='V4721_DATABASE_AUTHORITY_RESTORE'
                AND UPPER(e.league) LIKE 'LLWS%'""").fetchall()
            now=time.time()
            for row in rows:
                checked+=1
                try:event=json.loads(row["event_json"] or "{}")
                except Exception:event={}
                try:item=json.loads(row["asset_json"] or "{}")
                except Exception:item={}
                item.setdefault("associationMethod","V4721_DATABASE_AUTHORITY_RESTORE")
                if not _bad_llws_restore(item,event):continue
                conn.execute("""UPDATE history_event_media SET association_state='QUARANTINED',association_confidence=0,
                  association_method='V5116_TITLE_PAIR_CONFLICT',association_evidence=?,updated_at=?
                  WHERE canonical_event_key=? AND asset_key=?""",
                  ("v5.1.16 rejected restored LLWS asset because explicit title participants conflict with target event",now,row["canonical_event_key"],row["asset_key"]))
                quarantined+=1
            conn.commit()
    except Exception as exc:
        try:server.MILESTONE_CONSOLE.record("media","WARN","v5.1.16 LLWS quarantine could not complete",{"error":f"{type(exc).__name__}: {exc}"})
        except Exception:pass
    return {"checked":checked,"quarantined":quarantined}


def _plan_for(plans,league,event_id,row):
    key=f"{league}:{event_id}"
    if key in plans:return key,plans[key]
    ids={_clean(event_id)}
    for k in ("scoreEventId","espnEventId","gameCenterEventId","gamePk","canonicalEventId","eventId","matchId","id"):
        if (row or {}).get(k) not in (None,""):ids.add(str((row or {}).get(k)))
    for pkey,plan in plans.items():
        if _clean((plan or {}).get("league") or str(pkey).split(":",1)[0]).upper()!=league:continue
        pev=(plan or {}).get("event") or {}
        pids={_clean((plan or {}).get("eventId")),*[_clean(pev.get(k)) for k in ("scoreEventId","espnEventId","gameCenterEventId","gamePk","canonicalEventId","eventId","matchId","id")]}
        if ids & {x for x in pids if x}:return pkey,plan
    return key,None


def _custom_special(league):
    try:
        from . import competition_builder as cb
        comp=cb.SERVICE.get(league)
        return bool(comp and _clean(comp.get("type")).upper()=="SPECIAL_EVENT")
    except Exception:return False


def _patch_server(server):
    if getattr(server,"__sbbMediaRuntimeRepairV5116",False):return True
    required=("_history_day_score_rows","_history_day_ribbon_plans","HISTORY_REPOSITORY","_history_discover_event")
    if not all(hasattr(server,x) for x in required):return False
    original_scores=server._history_day_score_rows
    original_plans=server._history_day_ribbon_plans

    def score_rows(date,*args,**kwargs):
        out=original_scores(date,*args,**kwargs) or {}
        if not isinstance(out,dict):return out
        # Retired CFB must never escape into a current read model again.
        return {k:v for k,v in out.items() if _clean(k).upper()!="CFB"}

    def ribbon_plans(date,score_rows_arg=None,*args,**kwargs):
        rows=score_rows_arg if isinstance(score_rows_arg,dict) else score_rows(date)
        rows={k:v for k,v in (rows or {}).items() if _clean(k).upper()!="CFB"}
        plans=original_plans(date,rows,*args,**kwargs) or {}
        if not isinstance(plans,dict):return plans
        plans={k:v for k,v in plans.items() if _clean((v or {}).get("league") or str(k).split(":",1)[0]).upper()!="CFB"}
        repo=server.HISTORY_REPOSITORY
        for league_raw,games in rows.items():
            league=_clean(league_raw).upper()
            # Only special events and the one known NFL edge need the compatibility
            # fallback. Core leagues keep the original single-bulk-read fast path.
            if league!="NFL" and not _custom_special(league):continue
            for row in games or []:
                if not isinstance(row,dict):continue
                eid=_event_id(row)
                if not eid:continue
                pkey,plan=_plan_for(plans,league,eid,row)
                existing=list((plan or {}).get("playable") or [])
                if league.startswith("LLWS") and plan:
                    event=row
                    for field in ("media","playable"):
                        if isinstance(plan.get(field),list):plan[field]=[x for x in plan[field] if not _bad_llws_restore(x,event)]
                    existing=list(plan.get("playable") or [])
                if existing:continue
                try:media=list(repo.event_media(date,league,eid,include_failed=False) or [])
                except TypeError:media=list(repo.event_media(date,league,eid) or [])
                except Exception:media=[]
                media=_sanitize_media(repo,date,league,eid,media)
                playable=[x for x in media if _usable(x)]
                if not playable:continue
                if not plan:
                    plan={"eventId":eid,"league":league,"event":copy.deepcopy(row),"canonicalEventKey":f"{league}:{eid}"}
                else:plan=dict(plan)
                plan["media"]=media;plan["playable"]=playable;plan["databaseAuthorityFallback"]=True
                plans[pkey]=plan
        return plans

    server._history_day_score_rows=score_rows
    server._history_day_ribbon_plans=ribbon_plans
    server.__sbbMediaRuntimeRepairV5116=True
    try:
        server.SBB_BACKEND_WIRING.setdefault("media",{})["v5116"]="recent MLB continuity + special-event ribbon authority + LLWS conflict guard"
    except Exception:pass
    return True


def _is_final(row):
    status=_clean((row or {}).get("status") or (row or {}).get("state")).lower()
    return any(x in status for x in ("final","finished","complete","ft"))


def _recent_mlb_sweep(server,max_events=12):
    # Low priority: do not compete with active playback.
    try:
        if callable(getattr(server,"_history_work_mode",None)) and server._history_work_mode()=="playback":return {"skipped":"playback"}
    except Exception:pass
    try:today=datetime.fromisoformat(server._client_date_iso(0)).date()
    except Exception:today=datetime.now().date()
    attempted=restored=0
    for delta in range(4,-1,-1):
        day=(today-timedelta(days=delta)).isoformat()
        try:rows=(server._history_day_score_rows(day) or {}).get("MLB") or []
        except Exception:rows=[]
        for event in rows:
            if attempted>=max_events:return {"attempted":attempted,"restored":restored}
            if not isinstance(event,dict) or not _is_final(event):continue
            eid=_event_id(event)
            if not eid:continue
            try:existing=server.HISTORY_REPOSITORY.event_media(day,"MLB",eid,include_failed=False) or []
            except Exception:existing=[]
            if any(_usable(x) for x in existing):continue
            attempted+=1
            owner=f"recent-media-v5116:{threading.get_ident()}"
            claim=""
            try:
                claim=server.HISTORY_REPOSITORY.canonical_event_key("MLB",eid)
                if hasattr(server.HISTORY_REPOSITORY,"claim_event") and not server.HISTORY_REPOSITORY.claim_event(claim,owner,lease_seconds=180):continue
                result=server._history_discover_event(day,"MLB",event,force=True,allow_search_rescue=False,pass_target_tier="green") or {}
                if result.get("playable") or any(_usable(x) for x in (result.get("media") or [])):restored+=1
            except Exception as exc:
                try:server.MILESTONE_CONSOLE.record("media","WARN","recent MLB repair event failed",{"date":day,"eventId":eid,"error":f"{type(exc).__name__}: {exc}"})
                except Exception:pass
            finally:
                if claim and hasattr(server.HISTORY_REPOSITORY,"release_event_claim"):
                    try:server.HISTORY_REPOSITORY.release_event_claim(claim,owner)
                    except Exception:pass
            time.sleep(.35)
    return {"attempted":attempted,"restored":restored}


def _worker():
    server=None
    for _ in range(600):
        server=sys.modules.get("__main__")
        if server is not None and _patch_server(server):break
        time.sleep(.2)
    else:return
    # One cheap, targeted integrity cleanup; no repository-wide startup scan.
    time.sleep(8)
    cfb=_purge_retired_cfb_history(server)
    result=_quarantine_bad_llws(server)
    try:server.MILESTONE_CONSOLE.record("media","PASS","v5.1.16 media integrity guards installed",{"cfb":cfb,"llws":result})
    except Exception:pass
    # Let score/ribbon startup finish before provider recovery begins.
    time.sleep(45)
    while True:
        started=time.time();result=_recent_mlb_sweep(server,max_events=12)
        try:
            server.SBB_BACKEND_WIRING.setdefault("media",{})["recentRepairState"]={**result,"lastAt":time.time()}
        except Exception:pass
        # Keep this lane deliberately sparse. The normal workers remain primary.
        time.sleep(max(30,300-(time.time()-started)))


def install():
    global _INSTALLED,_ORIGINAL_EVENT_MEDIA
    with _INSTALL_LOCK:
        if _INSTALLED:return False
        _ORIGINAL_EVENT_MEDIA=HistoryRepository.event_media
        HistoryRepository.event_media=_event_media
        _INSTALLED=True
    threading.Thread(target=_worker,daemon=True,name="sbb-media-runtime-repair-v5116").start()
    return True


__all__=["VERSION","install"]

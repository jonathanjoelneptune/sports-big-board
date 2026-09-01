"""Sports Big Board v5.1.18 — nonblocking canonical score fallback.

This endpoint is deliberately score-only.  It reads already-persisted canonical
catalog events and never runs media discovery, Game Center providers, audits, or
Day State reconstruction.  The browser uses it only when the richer Day State
read model is slow/unavailable, so a healthy historical date cannot paint as
"0 games" just because enrichment is still catching up.
"""
from __future__ import annotations
import re
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

_INSTALLED=False
_LOCK=threading.Lock()
_DATE=re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _event_identity(event, fallback=""):
    if isinstance(event,dict):
        for key in ("scoreEventId","matchId","espnEventId","gamePk","canonicalEventId","eventId","id"):
            value=event.get(key)
            if value not in (None,""):return str(value)
    return str(fallback or "")


def _payload(server, day):
    repo=getattr(server,"HISTORY_REPOSITORY",None)
    rows=[]
    if repo is not None and hasattr(repo,"catalog_events"):
        rows=repo.catalog_events(date_from=day,date_to=day,limit=50000) or []
    out={};seen={}
    for row in rows:
        if not isinstance(row,dict):continue
        league=str(row.get("league") or "").upper()
        if not league or league=="CFB":continue
        event=dict(row.get("event") or {})
        eid=str(row.get("eventId") or "")
        ident=_event_identity(event,eid)
        if ident and ident in seen.setdefault(league,set()):continue
        event.setdefault("competitionId",league);event.setdefault("league",league);event.setdefault("__sbbLeague",league)
        event.setdefault("date",day);event.setdefault("gameDate",day);event.setdefault("__sbbDate",day)
        if eid:
            event.setdefault("eventId",eid);event.setdefault("id",eid)
        if not event.get("status"):event["status"]="SCHEDULED"
        out.setdefault(league,[]).append(event)
        if ident:seen[league].add(ident)
    count=sum(len(v) for v in out.values())
    return {"ok":True,"version":str(getattr(server,"APP_VERSION","")),"date":day,
            "scoreRowsByLeague":out,"scoreGameCount":count,"eventPlans":{},
            "catalogFirst":True,"compact":True,"scoreInventoryComplete":False,
            "fastCanonical":True,"cache":{"state":"CANONICAL_SCORE_FAST_PATH","ageSeconds":0},
            "summary":{"games":count,"competitions":sum(1 for v in out.values() if v)}}


def _patch(server):
    Handler=getattr(server,"Handler",None)
    if Handler is None:return False
    if getattr(Handler,"__sbbDayStateFastPathV5118",False):return True
    old_get=Handler.do_GET
    def do_GET(self):
        parsed=urlparse(self.path)
        if parsed.path=="/api/day-state/fast":
            day=str((parse_qs(parsed.query).get("date") or [""])[-1])[:10]
            if not _DATE.fullmatch(day):return server.send_json(self,{"ok":False,"error":"DATE_REQUIRED"},400)
            started=time.perf_counter()
            try:
                data=_payload(server,day)
                data["timing"]={"canonicalScoreMs":round((time.perf_counter()-started)*1000,1)}
                return server.send_json(self,data,200,{"X-SBB-Day-State":"CANONICAL_SCORE_FAST_PATH"})
            except Exception as exc:
                return server.send_json(self,{"ok":False,"error":"CANONICAL_SCORE_FAST_PATH_FAILED","message":f"{type(exc).__name__}: {exc}"},500)
        return old_get(self)
    Handler.do_GET=do_GET
    Handler.__sbbDayStateFastPathV5118=True
    try:server.MILESTONE_CONSOLE.record("day-state","PASS","v5.1.18 canonical score fast path installed",{})
    except Exception:pass
    return True


def _worker():
    for _ in range(600):
        server=sys.modules.get("__main__")
        if server is not None and hasattr(server,"send_json") and _patch(server):return
        time.sleep(.2)


def install():
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:return False
        _INSTALLED=True
    threading.Thread(target=_worker,daemon=True,name="sbb-day-state-fast-path-v5118").start()
    return True

__all__=["install","_payload"]

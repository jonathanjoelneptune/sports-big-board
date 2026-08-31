"""Sports Big Board v4.7.21 — CFB Game Center runtime enrollment.

CFB already owns canonical ESPN event IDs and the multisport ESPN summary adapter,
but server.py's legacy Game Center support/index lists stopped at NFL/NBA/NHL/MLS/EPL.
This module installs after package startup and enrolls CFB in the actual server-owned
Game Center resolver without changing score-provider identity.

v4.7.25 stability additions keep this enrollment bounded and cache-local so a CFB
click cannot repeatedly rescan the entire ranked-season/catalog state while the
browser is polling a preparing Game Center.
"""
from __future__ import annotations

import sys
import threading
import time

VERSION = "4.7.21-game-center-runtime-1"
_LOCK = threading.Lock()
_INDEX_LOCK = threading.RLock()
_INSTALLED = False
_CFB_DATE_CACHE = {}
_CFB_DATE_CACHE_TTL = 60.0


def _event_id(event):
    event=event or {}
    for key in ("espnEventId","scoreEventId","eventId","id","matchId"):
        value=str(event.get(key) or "").strip()
        if value:return value
    return ""


def _cfb_events_for_date(server, day):
    day = str(day or "")[:10]
    if not day:
        return []
    now=time.time()
    with _INDEX_LOCK:
        cached=_CFB_DATE_CACHE.get(day)
        if cached and now-float(cached[0] or 0)<_CFB_DATE_CACHE_TTL:
            return [dict(x) for x in cached[1]]

    rows = []
    # The ranked-season state is the first authority because its event IDs are the
    # ESPN IDs that the summary endpoint accepts directly. This is local JSON and
    # bounded to one season; no provider call occurs on a Game Center click.
    try:
        from . import cfb_ranked
        state = cfb_ranked._load_state()
        for week in (state.get("weeks") or {}).values():
            for event in (week or {}).get("events") or []:
                if str(event.get("date") or event.get("gameDate") or "")[:10] == day:
                    item=dict(event)
                    eid=_event_id(item)
                    if eid:
                        item.setdefault("id",eid);item.setdefault("eventId",eid)
                        item.setdefault("espnEventId",eid);item.setdefault("scoreEventId",eid)
                    rows.append(item)
    except Exception:
        pass

    # Fallback to canonical history only when the ranked-season state has not yet
    # materialized the date. Limit the query and cache the result so a UI poll loop
    # can never turn into repeated full-catalog scans.
    if not rows:
        repo = getattr(server, "HISTORY_REPOSITORY", None)
        if repo is not None and hasattr(repo, "catalog_events"):
            try:
                catalog = repo.catalog_events(date_from=day, date_to=day, limit=512) or []
            except Exception:
                catalog = []
            for record in catalog:
                if str((record or {}).get("league") or "").upper() != "CFB":
                    continue
                event = dict((record or {}).get("event") or {})
                eid = str((record or {}).get("eventId") or _event_id(event) or "")
                if eid:
                    event.setdefault("id", eid)
                    event.setdefault("eventId", eid)
                    event.setdefault("espnEventId", eid)
                    event.setdefault("scoreEventId", eid)
                event.setdefault("date", day)
                rows.append(event)

    # Deterministic de-duplication prevents duplicate index rows when ranked-state
    # compatibility shapes contain the same game in more than one week bucket.
    dedup=[];seen=set()
    for row in rows:
        eid=_event_id(row)
        key=eid or repr(sorted((row or {}).items()))
        if key in seen:continue
        seen.add(key);dedup.append(row)
    with _INDEX_LOCK:
        _CFB_DATE_CACHE[day]=(now,[dict(x) for x in dedup])
        if len(_CFB_DATE_CACHE)>32:
            for key in sorted(_CFB_DATE_CACHE,key=lambda k:_CFB_DATE_CACHE[k][0])[:-24]:
                _CFB_DATE_CACHE.pop(key,None)
    return dedup


def _ensure_cfb_index(server, day):
    day = str(day or "")[:10]
    if not day:
        return 0
    try:
        with server.GAME_CENTER_EVENT_INDEX_LOCK:
            current = list(server.GAME_CENTER_EVENT_INDEX.get(("CFB", day)) or [])
        if any(str(x.get("provider") or "official") == "official" for x in current):
            return len(current)
    except Exception:
        pass
    rows = _cfb_events_for_date(server, day)
    if not rows:
        return 0
    try:
        indexed=server._index_game_center_events("CFB", rows, day, "official") or []
        return len(indexed)
    except Exception:
        return 0


def _patch_server(server):
    if getattr(server, "__sbbGameCenterRuntimeV4721", False):
        # Refresh wiring diagnostics even when another import path called us first.
        try:
            server.SBB_BACKEND_WIRING["gameCenter"]["supported"] = sorted(server.GAME_CENTER_SUPPORTED)
        except Exception:
            pass
        return True
    required = ("GAME_CENTER_SUPPORTED", "_game_center_index_rows", "_index_game_center_events")
    if not all(hasattr(server, name) for name in required):
        return False

    try:
        supported = server.GAME_CENTER_SUPPORTED
        if isinstance(supported, set):
            supported.add("CFB")
        else:
            server.GAME_CENTER_SUPPORTED = set(supported or ()) | {"CFB"}
    except Exception:
        return False

    original = server._game_center_index_rows

    def game_center_index_rows(competition, date, allow_fetch=False):
        comp = str(competition or "").upper()
        if comp == "CFB":
            _ensure_cfb_index(server, date)
            # CFB already has canonical ESPN IDs. Never issue a second scoreboard
            # provider fetch from the Game Center resolver merely to rediscover the
            # same event; the summary fetch is the only network operation needed.
            return original(comp, date, allow_fetch=False)
        return original(comp, date, allow_fetch=allow_fetch)

    server._game_center_index_rows = game_center_index_rows
    server.__sbbGameCenterRuntimeV4721 = True

    # One explicit wiring snapshot makes it possible for diagnostics/tests to prove
    # that the ribbon and Game Center are using the intended backend authorities.
    server.SBB_BACKEND_WIRING={
        "version":VERSION,
        "ribbon":{
            "owner":"DayStateEngine",
            "catalog":"HistoryRepository.history_catalog_event",
            "media":"HistoryRepository normalized EVENT_MEDIA/COLLECTION_MEDIA",
        },
        "gameCenter":{
            "owner":"server Game Center repository",
            "supported":sorted(server.GAME_CENTER_SUPPORTED),
            "CFB":"ESPN summary via canonical cfb_ranked event ID",
            "CFBIndex":"local ranked-state/history catalog; no click-time scoreboard fetch",
        },
    }
    try:
        server.MILESTONE_CONSOLE.record(
            "game-center", "PASS", "CFB Game Center runtime enrolled",
            {"version": VERSION, "provider": "ESPN", "competition": "CFB", "boundedIndex":True},
        )
    except Exception:
        pass
    return True


def _worker():
    for _ in range(600):
        server = sys.modules.get("__main__")
        if server is not None and _patch_server(server):
            return
        time.sleep(.2)


def install():
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return False
        _INSTALLED = True
    threading.Thread(target=_worker, daemon=True, name="sbb-game-center-runtime-v4721").start()
    return True


__all__ = ["VERSION", "install", "_patch_server", "_ensure_cfb_index", "_cfb_events_for_date"]

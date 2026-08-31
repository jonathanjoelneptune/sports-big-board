"""Sports Big Board v4.7.21 — CFB Game Center runtime enrollment.

CFB already owns canonical ESPN event IDs and the multisport ESPN summary adapter,
but server.py's legacy Game Center support/index lists stopped at NFL/NBA/NHL/MLS/EPL.
This module installs after package startup and enrolls CFB in the actual server-owned
Game Center resolver without changing score-provider identity.
"""
from __future__ import annotations

import sys
import threading
import time

VERSION = "4.7.21-game-center-runtime-1"
_LOCK = threading.Lock()
_INSTALLED = False


def _cfb_events_for_date(server, day):
    day = str(day or "")[:10]
    rows = []
    try:
        from . import cfb_ranked
        state = cfb_ranked._load_state()
        for week in (state.get("weeks") or {}).values():
            for event in (week or {}).get("events") or []:
                if str(event.get("date") or event.get("gameDate") or "")[:10] == day:
                    rows.append(dict(event))
    except Exception:
        pass
    if rows:
        return rows
    repo = getattr(server, "HISTORY_REPOSITORY", None)
    if repo is None or not hasattr(repo, "catalog_events"):
        return []
    try:
        catalog = repo.catalog_events(date_from=day, date_to=day, limit=5000) or []
    except Exception:
        return []
    for record in catalog:
        if str((record or {}).get("league") or "").upper() != "CFB":
            continue
        event = dict((record or {}).get("event") or {})
        eid = str((record or {}).get("eventId") or event.get("eventId") or event.get("id") or "")
        if eid:
            event.setdefault("id", eid)
            event.setdefault("eventId", eid)
            event.setdefault("espnEventId", eid)
            event.setdefault("scoreEventId", eid)
        event.setdefault("date", day)
        rows.append(event)
    return rows


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
        return len(server._index_game_center_events("CFB", rows, day, "official") or [])
    except Exception:
        return 0


def _patch_server(server):
    if getattr(server, "__sbbGameCenterRuntimeV4721", False):
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
            # Once the canonical CFB schedule has been indexed, the original owner
            # returns it immediately. Do not make a second scoreboard request here.
            return original(comp, date, allow_fetch=False)
        return original(comp, date, allow_fetch=allow_fetch)

    server._game_center_index_rows = game_center_index_rows
    server.__sbbGameCenterRuntimeV4721 = True
    try:
        server.MILESTONE_CONSOLE.record(
            "game-center", "PASS", "CFB Game Center runtime enrolled",
            {"version": VERSION, "provider": "ESPN", "competition": "CFB"},
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

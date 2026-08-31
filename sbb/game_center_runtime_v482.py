"""Sports Big Board v4.8.2 — Game Center score-identity normalization.

NBA/NHL score ribbons can carry a score-provider alias even when the same row also
contains the authoritative ESPN event fingerprint.  The core Game Center resolver
correctly refuses to call ESPN with an unverified alias; this runtime layer closes
that gap by resolving date + away/home against the existing authoritative ESPN day
scoreboard before the summary request is issued.

This module does not add Game Center support to competitions that have no provider.
Those remain explicit capability boundaries and are reported N/A by certification.
"""
from __future__ import annotations

import re
import sys
import threading
import time

VERSION = "4.8.2-game-center-score-identity-1"
_LOCK = threading.Lock()
_INSTALLED = False

_TARGETS = frozenset({"NBA", "NHL"})


def _clean(value):
    return str(value or "").strip()


def _event_id(event):
    event = event or {}
    for key in ("espnEventId", "scoreEventId", "eventId", "id", "matchId"):
        value = _clean(event.get(key))
        if value:
            return value
    return ""


def _hint_date(hints):
    hints = hints or {}
    for key in ("date", "gameDate", "__sbbDate", "scheduledAt", "start"):
        raw = _clean(hints.get(key))
        match = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
        if match:
            return match.group(1)
    return ""


def _hint_event(hints):
    hints = hints or {}
    away = _clean(hints.get("away"))
    home = _clean(hints.get("home"))
    return {
        "awayTeam": {"name": away, "displayName": away, "abbreviation": away},
        "homeTeam": {"name": home, "displayName": home, "abbreviation": home},
        "date": _hint_date(hints),
    }


def _same_pair(server, row, target):
    try:
        return bool(server._same_team_pair(row, target))
    except Exception:
        return False


def _resolve_from_espn_scoreboard(server, competition, requested_id="", hints=None):
    """Return a verified ESPN event id from the authoritative day scoreboard."""
    competition = _clean(competition).upper()
    if competition not in _TARGETS:
        return ""
    hints = hints or {}
    day = _hint_date(hints)
    target = _hint_event(hints)
    if not day or not _clean(hints.get("away")) or not _clean(hints.get("home")):
        return ""

    try:
        rows = list(server._espn_scoreboard(competition, day) or [])
    except Exception:
        rows = []
    if not rows:
        return ""

    requested_id = _clean(requested_id)
    # Prefer an exact requested-id row only after the sporting-event fingerprint
    # also matches. This retains the server's protection against arbitrary aliases.
    if requested_id:
        for row in rows:
            if _event_id(row) == requested_id and _same_pair(server, row, target):
                try:
                    server._index_game_center_events(competition, rows, day, "official")
                except Exception:
                    pass
                return requested_id

    matches = [row for row in rows if _same_pair(server, row, target)]
    if len(matches) != 1:
        return ""
    resolved = _event_id(matches[0])
    if not resolved:
        return ""
    try:
        server._index_game_center_events(competition, rows, day, "official")
    except Exception:
        pass
    return resolved


def _patch_server(server):
    if getattr(server, "__sbbGameCenterRuntimeV482", False):
        return True
    required = ("_resolve_game_center_event_id", "_espn_scoreboard", "_same_team_pair")
    if not all(hasattr(server, name) for name in required):
        return False

    original = server._resolve_game_center_event_id

    def resolve_game_center_event_id(competition, event_id, hints=None, allow_fetch=False):
        resolved = original(competition, event_id, hints=hints, allow_fetch=allow_fetch)
        if resolved:
            return resolved
        comp = _clean(competition).upper()
        if comp not in _TARGETS:
            return resolved
        official = _resolve_from_espn_scoreboard(server, comp, event_id, hints)
        if official:
            # Best-effort alias persistence. Repository APIs evolved across releases,
            # so the runtime resolver remains correct even when no alias writer exists.
            repo = getattr(server, "GAME_CENTER_REPOSITORY", None)
            requested = _clean(event_id)
            if repo is not None and requested and requested != official:
                for method_name in ("put_alias", "set_alias", "remember_alias"):
                    method = getattr(repo, method_name, None)
                    if not callable(method):
                        continue
                    try:
                        method(comp, requested, official)
                        break
                    except TypeError:
                        try:
                            method(comp, requested, official, _hint_event(hints))
                            break
                        except Exception:
                            pass
                    except Exception:
                        pass
            return official
        return ""

    server._resolve_game_center_event_id = resolve_game_center_event_id
    server.__sbbGameCenterRuntimeV482 = True
    try:
        wiring = getattr(server, "SBB_BACKEND_WIRING", None)
        if isinstance(wiring, dict):
            wiring.setdefault("gameCenter", {})["v482ScoreIdentity"] = "NBA/NHL date+team fingerprint -> ESPN day scoreboard event id"
    except Exception:
        pass
    try:
        server.MILESTONE_CONSOLE.record(
            "game-center", "PASS", "v4.8.2 NBA/NHL score identity normalizer enrolled",
            {"version": VERSION, "competitions": sorted(_TARGETS), "authority": "ESPN day scoreboard"},
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
    threading.Thread(target=_worker, daemon=True, name="sbb-game-center-runtime-v482").start()
    return True


__all__ = ["VERSION", "install", "_patch_server", "_resolve_from_espn_scoreboard"]

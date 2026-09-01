"""Sports Big Board v5.0.8 — CFB Game Center capability enrollment.

The mature multisport Game Center adapter already knows how to fetch and normalize
ESPN College Football (``football/college-football``), including quarter linescores
and win probability.  The remaining defect was one layer higher: ``server.py`` did
not enroll CFB in ``GAME_CENTER_SUPPORTED`` and its generic ESPN scoreboard helper
had no CFB route.  The browser therefore treated CFB as Game Center-capable while
the backend validation/resolution boundary still rejected the same competition.

This runtime layer closes only that seam:
  * enroll CFB in the backend Game Center capability set;
  * preserve v4.7.21's local ranked-state/history identity authority as the fast path;
  * expose a bounded/cached ESPN CFB day scoreboard only as a cold-state rescue;
  * resolve a score-ribbon CFB alias only after date + away/home fingerprint match;
  * leave the existing multisport CFB summary/normalization adapter untouched;
  * leave playback, curated media, SelectedEvent, and A/B player ownership untouched.

The narrow patch is intentional: Game Center data can no longer create a retry loop
for an unsupported CFB competition, and the fix cannot redirect the USC media path.
"""
from __future__ import annotations

import copy
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from urllib.parse import urlencode

VERSION = "5.0.8-cfb-game-center-1"
_LOCK = threading.Lock()
_INSTALLED = False
_TARGET = "CFB"
_ESPN_SPORT = "football"
_ESPN_SLUG = "college-football"
_SCOREBOARD_CACHE = {}
_SCOREBOARD_CACHE_LOCK = threading.Lock()
_SCOREBOARD_CACHE_TTL = 300.0
_SCOREBOARD_EMPTY_TTL = 15.0


def _clean(value):
    return str(value or "").strip()


def _date_hint(hints):
    hints = hints or {}
    for key in ("date", "gameDate", "__sbbDate", "scheduledAt", "start"):
        raw = _clean(hints.get(key))
        match = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
        if match:
            return match.group(1)
    return ""


def _event_id(event):
    event = event or {}
    for key in ("espnEventId", "scoreEventId", "eventId", "id", "matchId"):
        value = _clean(event.get(key))
        if value:
            return value
    return ""


def _team_hint(value):
    if isinstance(value, dict):
        return _clean(
            value.get("abbreviation")
            or value.get("shortName")
            or value.get("displayName")
            or value.get("name")
        )
    return _clean(value)


def _target_event(hints):
    hints = hints or {}
    away = _team_hint(hints.get("away"))
    home = _team_hint(hints.get("home"))
    return {
        "awayTeam": {"name": away, "displayName": away, "abbreviation": away},
        "homeTeam": {"name": home, "displayName": home, "abbreviation": home},
        "date": _date_hint(hints),
    }


def _viewer_date_matches(server, raw_date, target, tz_value="", utc_offset_minutes=None):
    if not raw_date:
        return True
    helper = getattr(server, "_event_on_viewer_date", None)
    if callable(helper):
        try:
            return bool(helper(str(raw_date), target, tz_value, utc_offset_minutes))
        except Exception:
            pass
    return str(raw_date)[:10] == str(target)


def _team_from_competitor(row):
    row = row or {}
    team = row.get("team") or {}
    name = team.get("displayName") or team.get("shortDisplayName") or team.get("name") or ""
    return {
        "id": str(team.get("id") or ""),
        "name": name,
        "displayName": name,
        "shortName": team.get("shortDisplayName") or team.get("name") or "",
        "abbreviation": team.get("abbreviation") or "",
        "logo": team.get("logo") or "",
        "score": row.get("score"),
    }


def _scoreboard_events(payload):
    if not isinstance(payload, dict):
        return []
    rows = payload.get("events")
    return [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []


def _cfb_scoreboard(server, date, tz_value="", utc_offset_minutes=None):
    """Return one viewer day of ESPN CFB rows in the server scoreboard shape.

    Exact date is the normal fast path. Neighbor dates are requested only when the
    exact date produces no viewer-day events, protecting UTC/date-edge games without
    tripling every click. Positive results are cached five minutes and empty results
    briefly, so Game Center partial polling cannot repeatedly hammer ESPN.
    """
    try:
        target = datetime.strptime(str(date)[:10], "%Y-%m-%d").date()
    except Exception:
        return []

    cache_key = (str(target), _clean(tz_value), str(utc_offset_minutes))
    now = time.time()
    with _SCOREBOARD_CACHE_LOCK:
        cached = _SCOREBOARD_CACHE.get(cache_key)
        if cached:
            ttl = _SCOREBOARD_CACHE_TTL if cached.get("rows") else _SCOREBOARD_EMPTY_TTL
            if now - float(cached.get("at") or 0) < ttl:
                return copy.deepcopy(cached.get("rows") or [])

    fetch = getattr(server, "_espn_fetch_json", None)
    base = _clean(getattr(server, "ESPN_SITE_API", ""))
    if not callable(fetch) or not base:
        return []

    merged = {}

    def fetch_delta(delta):
        exact = (target + timedelta(days=delta)).strftime("%Y%m%d")
        url = (
            f"{base.rstrip('/')}/{_ESPN_SPORT}/{_ESPN_SLUG}/scoreboard?"
            + urlencode({"dates": exact, "limit": 1000, "groups": 80})
        )
        return fetch(url, timeout=8)

    def merge_payload(payload):
        for event in _scoreboard_events(payload):
            raw_date = _clean(event.get("date"))
            if raw_date and not _viewer_date_matches(
                server, raw_date, target, tz_value, utc_offset_minutes
            ):
                continue
            event_id = _event_id(event)
            if not event_id:
                continue
            prior = merged.get(event_id)
            if prior is None or len(str(event)) > len(str(prior)):
                merged[event_id] = event

    try:
        merge_payload(fetch_delta(0))
    except Exception:
        pass

    if not merged:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(fetch_delta, delta) for delta in (-1, 1)]
            for future in as_completed(futures):
                try:
                    merge_payload(future.result())
                except Exception:
                    pass

    out = []
    for event_id, event in merged.items():
        competition = ((event.get("competitions") or [{}])[0] or {})
        sides = {}
        for competitor in competition.get("competitors") or []:
            side = _clean(competitor.get("homeAway")).lower()
            if side in ("away", "home"):
                sides[side] = _team_from_competitor(competitor)
        away = sides.get("away") or {}
        home = sides.get("home") or {}
        if not away or not home:
            continue

        status = event.get("status") or competition.get("status") or {}
        typ = status.get("type") or {}
        state = _clean(typ.get("state"))
        detail = _clean(
            typ.get("shortDetail")
            or typ.get("detail")
            or typ.get("description")
            or state
        )
        completed = bool(typ.get("completed")) or state.lower() == "post"
        report = "FINAL" if completed else ("LIVE" if state.lower() == "in" else detail or state)
        state_payload = {
            "description": detail or state,
            "status": state,
            "completed": completed,
            "report": report,
        }
        if status.get("displayClock"):
            state_payload["clock"] = status.get("displayClock")
        if status.get("period") is not None:
            state_payload["period"] = status.get("period")

        out.append(
            {
                "id": event_id,
                "matchId": event_id,
                "eventId": event_id,
                "espnEventId": event_id,
                "date": event.get("date"),
                "scheduledAt": event.get("date"),
                "scheduledGameDate": str(date)[:10],
                "name": event.get("name") or event.get("shortName") or "",
                "shortName": event.get("shortName") or "",
                "leagueName": "College Football",
                "competitionId": _TARGET,
                "awayTeam": away,
                "homeTeam": home,
                "awayScore": away.get("score"),
                "homeScore": home.get("score"),
                "score": {
                    "awayScore": away.get("score"),
                    "homeScore": home.get("score"),
                },
                "state": state_payload,
                "status": detail or state,
                "completed": completed,
                "__sbbLeague": _TARGET,
                "source": "ESPN",
                "scoreProvider": "ESPN",
                "gameCenterProviderHint": "espn",
            }
        )

    out.sort(key=lambda row: (_clean(row.get("date")), _event_id(row)))
    with _SCOREBOARD_CACHE_LOCK:
        _SCOREBOARD_CACHE[cache_key] = {"at": time.time(), "rows": copy.deepcopy(out)}
        if len(_SCOREBOARD_CACHE) > 32:
            oldest = min(
                _SCOREBOARD_CACHE,
                key=lambda key: float(_SCOREBOARD_CACHE[key].get("at") or 0),
            )
            _SCOREBOARD_CACHE.pop(oldest, None)
    return out


def _same_pair(server, row, target):
    try:
        return bool(server._same_team_pair(row, target))
    except Exception:
        return False


def _remember_alias(server, requested, official, hints):
    requested = _clean(requested)
    official = _clean(official)
    if not requested or not official:
        return
    repo = getattr(server, "GAME_CENTER_REPOSITORY", None)
    method = getattr(repo, "put_alias", None) if repo is not None else None
    if not callable(method):
        return
    hints = hints or {}
    day = _date_hint(hints)
    away = _team_hint(hints.get("away"))
    home = _team_hint(hints.get("home"))
    try:
        method(_TARGET, requested, official, day, away, home)
        return
    except TypeError:
        pass
    except Exception:
        return
    try:
        method(_TARGET, requested, official)
    except Exception:
        pass


def _resolve_from_espn_scoreboard(server, requested_id="", hints=None):
    """Resolve a CFB score identity only after ESPN date/team verification."""
    hints = hints or {}
    day = _date_hint(hints)
    away = _team_hint(hints.get("away"))
    home = _team_hint(hints.get("home"))
    if not day or not away or not home:
        return ""

    try:
        rows = list(server._espn_scoreboard(_TARGET, day) or [])
    except Exception:
        rows = []
    if not rows:
        return ""

    target = _target_event(hints)
    requested_id = _clean(requested_id)
    if requested_id:
        for row in rows:
            if _event_id(row) == requested_id and _same_pair(server, row, target):
                try:
                    server._index_game_center_events(_TARGET, rows, day, "official")
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
        server._index_game_center_events(_TARGET, rows, day, "official")
    except Exception:
        pass
    return resolved


def _multisport_cfb_adapter_ready():
    """Enroll CFB only when the existing detailed-summary adapter is present."""
    try:
        from . import game_center_multisport as multisport
        return _TARGET in getattr(multisport, "_ESPN_COMPETITIONS", {})
    except Exception:
        return False


def _patch_server(server):
    if getattr(server, "__sbbGameCenterRuntimeV508", False):
        return True
    required = (
        "_resolve_game_center_event_id",
        "_espn_scoreboard",
        "_same_team_pair",
        "fetch_espn_game_center",
        "GAME_CENTER_SUPPORTED",
    )
    if not all(hasattr(server, name) for name in required):
        return False
    if not _multisport_cfb_adapter_ready():
        # Fail closed: never advertise a server capability before its provider
        # adapter exists.  v4.7.17+ should always satisfy this guard.
        return False

    original_scoreboard = server._espn_scoreboard
    original_resolver = server._resolve_game_center_event_id

    def espn_scoreboard(league, date, tz_value="", utc_offset_minutes=None):
        if _clean(league).upper() == _TARGET:
            return _cfb_scoreboard(server, date, tz_value, utc_offset_minutes)
        return original_scoreboard(league, date, tz_value, utc_offset_minutes)

    server._espn_scoreboard = espn_scoreboard

    # Validation reads this set dynamically, so enrollment after both CFB provider
    # and CFB identity adapters are installed immediately repairs the boundary.
    supported = set(getattr(server, "GAME_CENTER_SUPPORTED", set()) or set())
    supported.add(_TARGET)
    server.GAME_CENTER_SUPPORTED = supported

    def resolve_game_center_event_id(competition, event_id, hints=None, allow_fetch=False):
        comp = _clean(competition).upper()
        if comp != _TARGET:
            return original_resolver(competition, event_id, hints=hints, allow_fetch=allow_fetch)

        # v5.0.8 LOCAL-FIRST: v4.7.21 already resolves canonical CFB ESPN IDs
        # from bounded local ranked-state/history data. Keep that path authoritative
        # and network-free whenever it succeeds.
        resolved = original_resolver(comp, event_id, hints=hints, allow_fetch=allow_fetch)
        if resolved:
            return resolved

        # Cold-state rescue only. A numeric-looking CFB id is never trusted merely
        # because it looks like ESPN; require a complete sporting-event fingerprint
        # before one cached scoreboard verification is allowed.
        complete_fingerprint = bool(
            _date_hint(hints)
            and _team_hint((hints or {}).get("away"))
            and _team_hint((hints or {}).get("home"))
        )
        if not complete_fingerprint:
            return ""
        verified = _resolve_from_espn_scoreboard(server, event_id, hints)
        if verified:
            _remember_alias(server, event_id, verified, hints)
            return verified
        return ""

    server._resolve_game_center_event_id = resolve_game_center_event_id
    server.__sbbGameCenterRuntimeV508 = True

    try:
        wiring = getattr(server, "SBB_BACKEND_WIRING", None)
        if isinstance(wiring, dict):
            gc = wiring.setdefault("gameCenter", {})
            gc["v508CfbCapability"] = "CFB enrolled after multisport ESPN adapter verification"
            gc["v508CfbIdentity"] = "v4721 local-first; cold-state date + away/home fingerprint -> ESPN college-football event id"
    except Exception:
        pass
    try:
        server.MILESTONE_CONSOLE.record(
            "game-center",
            "PASS",
            "v5.0.8 CFB Game Center capability boundary enrolled",
            {
                "version": VERSION,
                "competition": _TARGET,
                "provider": "ESPN",
                "scoreboard": f"{_ESPN_SPORT}/{_ESPN_SLUG}",
                "summaryAdapter": "sbb.game_center_multisport",
            },
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
    threading.Thread(
        target=_worker, daemon=True, name="sbb-game-center-runtime-v508"
    ).start()
    return True


__all__ = [
    "VERSION",
    "install",
    "_patch_server",
    "_cfb_scoreboard",
    "_resolve_from_espn_scoreboard",
]

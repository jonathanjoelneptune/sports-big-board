"""Sports Big Board v5.2.3 — always-on integrity lane.

Interactive playback and ribbon work never wait for this module.  Conversely,
operator PLAYBACK/SEARCH modes only govern optional discovery; they do not suspend
canonical result correctness, Game Center persistence, or trusted-playlist catch-up.
"""
from __future__ import annotations

import copy
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

from . import competition_builder as builder
from . import tennis_game_center as tennis_gc

VERSION = "5.2.3-integrity-lane-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_SERVER = None
_STOP = threading.Event()
_STATE_LOCK = threading.RLock()
_STATE = {
    "version": VERSION,
    "installed": False,
    "resultHeartbeat": 0.0,
    "playlistHeartbeat": 0.0,
    "gameCenterHeartbeat": 0.0,
    "lastResultRun": 0.0,
    "lastPlaylistKick": 0.0,
    "lastGameCenterWarm": 0.0,
    "resultFinalized": 0,
    "gameCentersWarmed": 0,
    "playlistKicks": 0,
    "unresolvedPastTennis": 0,
    "recentTennisMediaGaps": 0,
    "lastResultError": "",
    "lastPlaylistError": "",
    "lastGameCenterError": "",
    "workModeIndependent": True,
}
_PLAYLIST_LAST_KICK = {}
_GC_LAST_TRY = {}


def _clean(v):
    return str(v or "").strip()


def _local_today():
    try:
        tz = getattr(_SERVER, "MEDIA_PREWARM_STATE", {}).get("timezone") if _SERVER else ""
        tz = _clean(tz) or "America/Los_Angeles"
        if ZoneInfo:
            return datetime.now(ZoneInfo(tz)).date()
    except Exception:
        pass
    return datetime.now().date()


def _event_date(event):
    return _clean((event or {}).get("date") or (event or {}).get("gameDate") or (event or {}).get("scheduledAt"))[:10]


def _event_id(event):
    for key in ("eventId", "matchId", "scoreEventId", "espnEventId", "canonicalEventId", "id"):
        v = (event or {}).get(key)
        if v not in (None, ""):
            return str(v)
    return ""


def _team(event, side):
    value = (event or {}).get(f"{side}Team") or (event or {}).get(side) or {}
    return dict(value) if isinstance(value, dict) else {"name": _clean(value), "displayName": _clean(value)}


def _team_name(event, side):
    team = _team(event, side)
    return _clean(team.get("displayName") or team.get("name") or team.get("shortName") or team.get("abbreviation"))


def _status(event):
    raw = (event or {}).get("status")
    if isinstance(raw, dict):
        raw = raw.get("type") or raw.get("name") or raw.get("state") or raw.get("description")
    return _clean(raw).upper()


def _terminal(event):
    s = _status(event)
    return any(x in s for x in ("FINAL", "COMPLETED", "FINISHED", "CANCEL", "POSTPON", "WALKOVER", "WO"))


def _past_unresolved(event, today=None):
    day = _event_date(event)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return False
    today = today or _local_today()
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except Exception:
        return False
    return d < today and not _terminal(event)


def _score_value(value):
    try:
        return int(float(value))
    except Exception:
        return "" if value in (None, "") else value


def _competitor_score(comp, other=None):
    raw = (comp or {}).get("score")
    if isinstance(raw, dict):
        raw = raw.get("value") or raw.get("displayValue")
    value = _score_value(raw)
    if value != "":
        return value
    # ESPN tennis linescores are game scores per set. If aggregate sets-won is not
    # present, derive it without guessing from game totals.
    if other is not None:
        left = list((comp or {}).get("linescores") or [])
        right = list((other or {}).get("linescores") or [])
        wins = 0
        for i in range(min(len(left), len(right))):
            a = _score_value((left[i] or {}).get("value") if isinstance(left[i], dict) else left[i])
            b = _score_value((right[i] or {}).get("value") if isinstance(right[i], dict) else right[i])
            if isinstance(a, int) and isinstance(b, int) and a > b:
                wins += 1
        return wins
    return ""


def _espn_completed(match):
    status = (match or {}).get("status") or {}
    stype = status.get("type") if isinstance(status, dict) else {}
    if not isinstance(stype, dict):
        stype = {}
    if stype.get("completed") is True:
        return True
    text = " ".join(_clean(x) for x in (
        stype.get("state"), stype.get("name"), stype.get("description"), stype.get("detail"),
        status.get("type") if isinstance(status, dict) and not isinstance(status.get("type"), dict) else "",
    )).lower()
    return any(token in text for token in ("final", "complete", "finished", "post"))


def _resolved_competitors(event, match):
    espn_away, espn_home = tennis_gc._competitor_map(match)
    a_name, h_name = tennis_gc._match_names(match)
    target_a, target_h = _team_name(event, "away"), _team_name(event, "home")
    direct = tennis_gc._person_similarity(target_a, a_name) + tennis_gc._person_similarity(target_h, h_name)
    reverse = tennis_gc._person_similarity(target_a, h_name) + tennis_gc._person_similarity(target_h, a_name)
    if reverse > direct:
        espn_away, espn_home = espn_home, espn_away
        a_name, h_name = h_name, a_name
        direct = reverse
    if direct < 1.50:
        return None, None
    return espn_away, espn_home


def _apply_final(event, row):
    match = (row or {}).get("match") or {}
    if not _espn_completed(match):
        return None
    away_comp, home_comp = _resolved_competitors(event, match)
    if away_comp is None or home_comp is None:
        return None
    away_score = _competitor_score(away_comp, home_comp)
    home_score = _competitor_score(home_comp, away_comp)
    if away_score == "" or home_score == "":
        return None

    out = copy.deepcopy(event)
    out["status"] = "FINAL"
    out["state"] = "FINAL"
    out["awayScore"] = away_score
    out["homeScore"] = home_score
    out["score"] = {"away": away_score, "home": home_score}
    for side, score in (("away", away_score), ("home", home_score)):
        team = _team(out, side)
        team["score"] = score
        out[side] = team
        out[f"{side}Team"] = team
    out["participants"] = [out.get("awayTeam") or {}, out.get("homeTeam") or {}]
    out["espnMatchId"] = _clean(match.get("id")) or out.get("espnMatchId") or ""
    out["resultAuthority"] = "ESPN_TENNIS_FINALIZER_V523"
    out["resultFinalizedAt"] = time.time()
    out["gameCenterProviderHint"] = "competition-builder"
    return out


def _shell(event):
    return {
        "scoreboard": {
            "away": {"team": _team(event, "away")},
            "home": {"team": _team(event, "home")},
        },
        "event": dict(event or {}),
    }


def _finalize_competition(server, comp, max_events=20):
    today = _local_today()
    unresolved = [dict(ev) for ev in (comp.get("events") or []) if _past_unresolved(ev, today)]
    unresolved.sort(key=lambda ev: (_event_date(ev), _clean(ev.get("scheduledAt"))), reverse=True)
    if not unresolved:
        return 0, 0

    by_id = {_event_id(ev): dict(ev) for ev in (comp.get("events") or []) if _event_id(ev)}
    changed = 0
    attempted = 0
    for event in unresolved[:max_events]:
        attempted += 1
        try:
            row = tennis_gc._resolve_match(comp, _shell(event), _event_date(event), event)
            fixed = _apply_final(event, row) if row else None
            if fixed:
                by_id[_event_id(event)] = fixed
                changed += 1
        except Exception as exc:
            with _STATE_LOCK:
                _STATE["lastResultError"] = f"{type(exc).__name__}: {exc}"[:300]

    if changed:
        original = list(comp.get("events") or [])
        merged = [by_id.get(_event_id(ev), dict(ev)) for ev in original]
        before = dict(comp)
        persisted = builder._persist_event_reconciliation(server, comp, merged)
        next_comp = dict(persisted) if isinstance(persisted, dict) else {**before, "events": merged}
        comp.clear(); comp.update(next_comp)
        # Day State/RibbonSnapshot are read models; ask them to rebuild after the
        # canonical repository has been updated. Never do this on a request thread.
        try:
            from . import day_state
            engine = getattr(day_state, "_ENGINE", None)
            if engine:
                dates = sorted({_event_date(ev) for ev in merged if _event_date(ev)})
                for day in dates[-3:]:
                    try:
                        if hasattr(engine, "focus"):
                            engine.focus(day)
                        elif hasattr(engine, "request"):
                            engine.request(day)
                    except Exception:
                        pass
        except Exception:
            pass
    return changed, len(unresolved)


def _warm_gc_for_recent_finals(comp, max_events=3):
    today = _local_today()
    candidates = []
    for ev in comp.get("events") or []:
        try:
            d = datetime.strptime(_event_date(ev), "%Y-%m-%d").date()
        except Exception:
            continue
        if (today - d).days not in (0, 1, 2) or not _terminal(ev):
            continue
        eid = _event_id(ev)
        if not eid:
            continue
        if tennis_gc.peek_tennis_game_center(comp.get("id"), eid):
            continue
        if time.time() - float(_GC_LAST_TRY.get((comp.get("id"), eid)) or 0) < 900:
            continue
        candidates.append(dict(ev))
    candidates.sort(key=lambda ev: (_event_date(ev), _clean(ev.get("scheduledAt"))), reverse=True)
    warmed = 0
    for ev in candidates[:max_events]:
        key = (str(comp.get("id") or "").upper(), _event_id(ev))
        _GC_LAST_TRY[key] = time.time()
        try:
            data = tennis_gc._tennis_game_center(comp, ev)
            if isinstance(data, dict):
                try:
                    tennis_gc._result_put(tennis_gc._route_key(*key), data=data)
                except Exception:
                    pass
                warmed += 1
        except Exception as exc:
            with _STATE_LOCK:
                _STATE["lastGameCenterError"] = f"{type(exc).__name__}: {exc}"[:300]
    return warmed


def _recent_media_gaps(server, comp, days=2):
    repo = getattr(server, "HISTORY_REPOSITORY", None)
    if repo is None or not hasattr(repo, "event_media"):
        return 0
    today = _local_today()
    gaps = 0
    for ev in comp.get("events") or []:
        try:
            d = datetime.strptime(_event_date(ev), "%Y-%m-%d").date()
        except Exception:
            continue
        if (today - d).days < 0 or (today - d).days > days or not _terminal(ev):
            continue
        try:
            rows = repo.event_media(_event_date(ev), str(comp.get("id") or "").upper(), _event_id(ev), include_failed=False) or []
        except TypeError:
            try:
                rows = repo.event_media(_event_date(ev), str(comp.get("id") or "").upper(), _event_id(ev)) or []
            except Exception:
                rows = []
        except Exception:
            rows = []
        playable = [x for x in rows if isinstance(x, dict) and x.get("verifiedPlayable") and (x.get("youtubeId") or x.get("mediaUrl"))]
        if not playable:
            gaps += 1
    return gaps


def _tennis_competitions():
    out = []
    try:
        for comp in builder._load():
            if not comp.get("enabled", True):
                continue
            if _clean(comp.get("sportId")).lower() != "tennis":
                continue
            out.append(dict(comp))
    except Exception:
        pass
    return out


def _result_worker():
    if _STOP.wait(3.0):
        return
    while not _STOP.is_set():
        with _STATE_LOCK:
            _STATE["resultHeartbeat"] = time.time()
            _STATE["gameCenterHeartbeat"] = time.time()
        try:
            if _SERVER and hasattr(_SERVER, "_history_worker_beat"):
                _SERVER._history_worker_beat("integrity-results", "integrity:tennis-results")
        except Exception:
            pass
        server = _SERVER
        if server:
            finalized = 0
            unresolved = 0
            warmed = 0
            for comp in _tennis_competitions():
                try:
                    c, u = _finalize_competition(server, comp, max_events=20)
                    finalized += c; unresolved += u
                    warmed += _warm_gc_for_recent_finals(comp, max_events=3)
                except Exception as exc:
                    with _STATE_LOCK:
                        _STATE["lastResultError"] = f"{type(exc).__name__}: {exc}"[:300]
            with _STATE_LOCK:
                _STATE["lastResultRun"] = time.time()
                _STATE["resultFinalized"] += finalized
                _STATE["unresolvedPastTennis"] = max(0, unresolved - finalized)
                _STATE["gameCentersWarmed"] += warmed
                if warmed:
                    _STATE["lastGameCenterWarm"] = time.time()
            try:
                if hasattr(server, "_history_worker_beat"):
                    server._history_worker_beat("integrity-results", "integrity:idle", progress=bool(finalized or warmed))
            except Exception:
                pass
        _STOP.wait(60.0)


def _playlist_worker():
    """Trusted-playlist integrity lane. It never uses YouTube Search.

    Competition Builder has already normalized the operator playlists.  This worker
    only keeps active/recent tennis playlist ingestion alive even when optional deep
    discovery is in PLAYBACK priority.
    """
    if _STOP.wait(8.0):
        return
    while not _STOP.is_set():
        with _STATE_LOCK:
            _STATE["playlistHeartbeat"] = time.time()
        try:
            if _SERVER and hasattr(_SERVER, "_history_worker_beat"):
                _SERVER._history_worker_beat("integrity-playlists", "integrity:trusted-playlists")
                # v5.2.3 supersedes the old playlist-crawler health ownership.
                # Keep the legacy row explicit rather than reporting a false stale
                # heartbeat after its responsibilities moved into this integrity lane.
                _SERVER._history_worker_beat("playlist-crawler", "superseded:integrity-playlists")
        except Exception:
            pass
        server = _SERVER
        if server:
            total_gaps = 0
            for comp in _tennis_competitions():
                cid = str(comp.get("id") or "").upper()
                try:
                    gaps = _recent_media_gaps(server, comp, days=2)
                    total_gaps += gaps
                    # Always make sure the wizard-defined playlists are registered.
                    builder._register_media_sources(server, comp, force_crawl=False)
                    # If recent final matches are missing media, kick a trusted
                    # playlist recrawl at most every 15 minutes. This path uses
                    # playlists/playlistItems/videos, not the exhausted Search API.
                    if gaps and time.time() - float(_PLAYLIST_LAST_KICK.get(cid) or 0) >= 900:
                        state = getattr(server, "OPERATOR_MEDIA_PLAYLIST_CRAWL_STATE", {}) or {}
                        if not bool(state.get("running")):
                            builder._register_media_sources(server, comp, force_crawl=True)
                            _PLAYLIST_LAST_KICK[cid] = time.time()
                            with _STATE_LOCK:
                                _STATE["playlistKicks"] += 1
                                _STATE["lastPlaylistKick"] = time.time()
                            try:
                                state["integrityHeartbeat"] = time.time()
                                state["integrityLane"] = VERSION
                            except Exception:
                                pass
                except Exception as exc:
                    with _STATE_LOCK:
                        _STATE["lastPlaylistError"] = f"{type(exc).__name__}: {exc}"[:300]
            with _STATE_LOCK:
                _STATE["recentTennisMediaGaps"] = total_gaps
            try:
                if hasattr(server, "_history_worker_beat"):
                    server._history_worker_beat("integrity-playlists", "integrity:idle", progress=bool(total_gaps==0))
            except Exception:
                pass
        _STOP.wait(90.0)


def _install_into_server():
    global _SERVER
    deadline = time.time() + 120
    server = None
    while time.time() < deadline:
        candidate = sys.modules.get("__main__")
        if candidate and hasattr(candidate, "Handler") and hasattr(candidate, "send_json") and hasattr(candidate, "HISTORY_REPOSITORY"):
            server = candidate
            break
        time.sleep(0.2)
    if not server:
        return
    _SERVER = server
    try:
        lock=getattr(server,"HISTORY_WORKER_HEALTH_LOCK",None)
        health=getattr(server,"HISTORY_WORKER_HEALTH",None)
        if lock is not None and isinstance(health,dict):
            with lock:
                for name in ("integrity-results","integrity-playlists"):
                    health.setdefault(name,{"heartbeat":time.time(),"phase":"integrity:starting","lastProgress":0.0,"iterations":0,"blocked":0,"current":""})
    except Exception:
        pass

    Handler = server.Handler
    if not getattr(Handler, "__sbbIntegrityLaneV523", False):
        old_get = Handler.do_GET

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/integrity/status":
                with _STATE_LOCK:
                    payload = copy.deepcopy(_STATE)
                payload["ok"] = True
                payload["serverWorkMode"] = str(getattr(server, "_history_work_mode", lambda: "unknown")())
                payload["deepDiscoverySuspended"] = bool(getattr(server, "_history_search_suspended", lambda: False)())
                payload["integritySuspended"] = False
                return server.send_json(self, payload, 200, {"Cache-Control": "no-store"})
            return old_get(self)

        Handler.do_GET = do_GET
        Handler.__sbbIntegrityLaneV523 = True

    with _STATE_LOCK:
        _STATE["installed"] = True
    threading.Thread(target=_result_worker, daemon=True, name="sbb-integrity-results-v523").start()
    threading.Thread(target=_playlist_worker, daemon=True, name="sbb-integrity-playlists-v523").start()


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-integrity-install-v523").start()
    return True


def diagnostics():
    with _STATE_LOCK:
        return copy.deepcopy(_STATE)


__all__ = ["VERSION", "install", "diagnostics"]

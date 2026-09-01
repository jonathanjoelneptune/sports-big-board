"""Sports Big Board v5.1.15 — populated NCAAF Game Center.

NCAAF keeps ESPN event identity because the ranked schedule/ribbon is built from
ESPN/AP data.  Detailed Game Center data uses the same American-football model as
NFL, but adds a bounded Highlightly NCAA FBS completeness fallback when ESPN only
returns a score shell.

Provider path:
    NCAAF ESPN event id
      -> ESPN college-football summary (fast/canonical identity)
      -> if incomplete, verified Highlightly NCAA match lookup by date + teams
      -> Highlightly match detail + box score
      -> normalize through the shared NFL football contract
      -> merge into one NCAAF Game Center payload

The old CFB Game Center runtime is never imported or revived.
"""
from __future__ import annotations

import copy
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, parse_qs, urlparse, unquote

from . import game_center as _gc

VERSION = "5.1.15-ncaaf-game-center-4"
_TARGET = "NCAAF"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ORIGINAL_FETCH = _gc.fetch_espn_game_center
_ORIGINAL_NORMALIZE = _gc.normalize_espn_summary
_ORIGINAL_COVERAGE = _gc.game_center_coverage

_LOOKUP_LOCK = threading.RLock()
_LOOKUP_CACHE = {}
_LOOKUP_TTL = 10 * 60.0
_LOOKUP_EMPTY_TTL = 30.0

# v5.1.15: NCAAF score rows already carry the canonical ESPN event id.  Keep a
# tiny NCAAF-only cache/job lane so the public route never has to pass that exact
# id through the generic cross-provider resolver (which has no NCAAF scoreboard
# index and was the source of the "Unable to resolve ... from score identity" error).
_DIRECT_LOCK = threading.RLock()
_DIRECT_CACHE = {}
_DIRECT_JOBS = {}
_DIRECT_FINAL_TTL = 6 * 60 * 60.0
_DIRECT_PARTIAL_TTL = 2 * 60.0


def _clean(value):
    return str(value or "").strip()


def _team_hint(value):
    if isinstance(value, dict):
        return _clean(
            value.get("abbreviation")
            or value.get("shortName")
            or value.get("displayName")
            or value.get("name")
        )
    return _clean(value)


def _team_key(value):
    value = _team_hint(value).lower()
    value = value.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", value)


def _date_hint(hints):
    hints = hints or {}
    for key in ("date", "gameDate", "__sbbDate", "scheduledAt", "start"):
        raw = _clean(hints.get(key))
        match = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
        if match:
            return match.group(1)
    return ""


def _event_start_epoch(value):
    raw = _clean(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _unwrap_rows(payload):
    if isinstance(payload, dict):
        rows = payload.get("data")
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def _row_event(row):
    row = row or {}
    return {
        "awayTeam": row.get("awayTeam") or row.get("away") or {},
        "homeTeam": row.get("homeTeam") or row.get("home") or {},
        "scheduledAt": row.get("date") or row.get("scheduledAt") or "",
    }


def _same_pair(server, row, away, home):
    target = {
        "awayTeam": {"name": away, "displayName": away, "abbreviation": away},
        "homeTeam": {"name": home, "displayName": home, "abbreviation": home},
    }
    helper = getattr(server, "_same_team_pair", None)
    if callable(helper):
        try:
            return bool(helper(_row_event(row), target))
        except Exception:
            pass
    r = _row_event(row)
    return (
        _team_key(r.get("awayTeam")) == _team_key(away)
        and _team_key(r.get("homeTeam")) == _team_key(home)
    )


def _highlightly_fetch(server, path, params=None, timeout=8):
    fetch = getattr(server, "_highlightly_gc_fetch_json", None)
    if not callable(fetch):
        raise RuntimeError("Highlightly Game Center transport is unavailable")
    base = "https://american-football.highlightly.net"
    query = "?" + urlencode(params or {}) if params else ""
    return fetch(f"{base}{path}{query}", timeout=timeout)


def _lookup_highlightly_match(server, hints):
    """Resolve one NCAA FBS Highlightly match only after date/team verification.

    The first request is team-pair specific and cheap. A date inventory is a rescue
    path for provider abbreviation differences. Neighbor dates are tried only after
    the exact viewer date has no verified match, covering late-night UTC boundaries.
    """
    hints = hints or {}
    day = _date_hint(hints)
    away = _team_hint(hints.get("away"))
    home = _team_hint(hints.get("home"))
    if not day or not away or not home:
        return ""

    cache_key = (day, _team_key(away), _team_key(home))
    now = time.time()
    with _LOOKUP_LOCK:
        hit = _LOOKUP_CACHE.get(cache_key)
        if hit:
            ttl = _LOOKUP_TTL if hit.get("matchId") else _LOOKUP_EMPTY_TTL
            if now - float(hit.get("at") or 0) < ttl:
                return _clean(hit.get("matchId"))

    wanted_start = _event_start_epoch(hints.get("start") or hints.get("scheduledAt"))

    def choose(rows):
        candidates = []
        for row in rows:
            if not _same_pair(server, row, away, home):
                continue
            # The shared American-football API contains NFL and NCAA. A verified
            # college team pair is authoritative; explicitly exclude NFL rows.
            if _clean(row.get("league")).upper() == "NFL":
                continue
            match_id = _clean(row.get("id") or row.get("matchId"))
            if not match_id:
                continue
            start = _event_start_epoch(row.get("date") or row.get("scheduledAt"))
            distance = abs(start - wanted_start) if (start is not None and wanted_start is not None) else 0.0
            candidates.append((distance, match_id))
        candidates.sort(key=lambda x: (x[0], x[1]))
        if not candidates:
            return ""
        if len(candidates) == 1:
            return candidates[0][1]
        # Same teams can theoretically meet twice; kickoff time breaks the tie.
        if wanted_start is not None and candidates[0][0] + 60 < candidates[1][0]:
            return candidates[0][1]
        return ""

    def exact_pair_query(query_day):
        params = {
            "date": query_day,
            "awayTeamAbbreviation": away,
            "homeTeamAbbreviation": home,
            "limit": 25,
            "offset": 0,
        }
        try:
            result = choose(_unwrap_rows(_highlightly_fetch(server, "/matches", params, timeout=8)))
            if result:
                return result
        except Exception:
            pass
        return ""

    def date_inventory(query_day):
        try:
            payload = _highlightly_fetch(
                server, "/matches", {"date": query_day, "limit": 100, "offset": 0}, timeout=8
            )
            return choose(_unwrap_rows(payload))
        except Exception:
            return ""

    match_id = exact_pair_query(day) or date_inventory(day)
    if not match_id:
        try:
            parsed = datetime.strptime(day, "%Y-%m-%d").date()
            for delta in (-1, 1):
                neighbor = (parsed + timedelta(days=delta)).isoformat()
                match_id = exact_pair_query(neighbor)
                if match_id:
                    break
        except Exception:
            pass

    with _LOOKUP_LOCK:
        _LOOKUP_CACHE[cache_key] = {"at": time.time(), "matchId": match_id}
        if len(_LOOKUP_CACHE) > 128:
            oldest = min(_LOOKUP_CACHE, key=lambda k: float(_LOOKUP_CACHE[k].get("at") or 0))
            _LOOKUP_CACHE.pop(oldest, None)
    return match_id


def _period_scores(match):
    state = (match or {}).get("state") or {}
    score = state.get("score") if isinstance(state, dict) else {}
    if not isinstance(score, dict):
        return []
    names = [
        ("firstPeriod", "Q1"),
        ("secondPeriod", "Q2"),
        ("thirdPeriod", "Q3"),
        ("fourthPeriod", "Q4"),
        ("firstOvertimePeriod", "OT"),
        ("secondOvertimePeriod", "2OT"),
        ("thirdOvertimePeriod", "3OT"),
        ("fourthOvertimePeriod", "4OT"),
    ]
    out = []
    for index, (key, label) in enumerate(names, 1):
        value = _clean(score.get(key))
        if not value:
            continue
        parts = [x.strip() for x in value.replace(":", "-").split("-")]
        if len(parts) != 2:
            continue
        # Highlightly current score is rendered away-home elsewhere. Period values
        # follow the same API convention in the American-football product.
        out.append({"num": index, "label": label, "away": parts[0], "home": parts[1]})
    return out


def _flatten_highlightly_events(match):
    """Turn Highlightly drive/event payloads into the shared football PBP rows."""
    raw = (match or {}).get("events") or []
    if isinstance(raw, dict):
        raw = raw.get("data") or raw.get("items") or list(raw.values())
    timeline = []
    scoring = []
    for drive_index, drive in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(drive, dict):
            continue
        drive_scoring = bool(drive.get("isScoringPlay"))
        details = drive.get("playDetails") or []
        if isinstance(details, list) and details:
            for play_index, play in enumerate(details):
                if not isinstance(play, dict):
                    continue
                desc = _clean(play.get("text") or play.get("description") or play.get("type"))
                period = play.get("period") or ""
                clock = _clean(play.get("clock"))
                play_type = _clean(play.get("type"))
                scoring_flag = bool(
                    play.get("isScoringPlay")
                    or re.search(r"\b(touchdown|field goal|extra point|safety|two-point|2-point)\b", (desc + " " + play_type).lower())
                )
                entry = {
                    "id": f"hl:{drive_index}:{play_index}",
                    "index": len(timeline),
                    "period": period,
                    "periodLabel": " ".join(x for x in (f"Q{period}" if str(period).isdigit() else _clean(period), clock) if x),
                    "description": desc or play_type or "Play",
                    "scoreAway": play.get("awayScore", ""),
                    "scoreHome": play.get("homeScore", ""),
                    "isScoring": scoring_flag,
                }
                timeline.append(entry)
                if scoring_flag:
                    scoring.append(entry)
        else:
            desc = _clean(drive.get("description") or drive.get("result"))
            start = drive.get("start") or {}
            period = start.get("period") if isinstance(start, dict) else ""
            clock = _clean(start.get("clock") if isinstance(start, dict) else "")
            entry = {
                "id": f"hl:drive:{drive_index}",
                "index": len(timeline),
                "period": period,
                "periodLabel": " ".join(x for x in (_clean(period), clock) if x),
                "description": desc or "Drive",
                "scoreAway": drive.get("awayScore", ""),
                "scoreHome": drive.get("homeScore", ""),
                "isScoring": drive_scoring,
            }
            timeline.append(entry)
            if drive_scoring:
                scoring.append(entry)
    return timeline, scoring


def _rewrite_public_identity(data, event_id, highlightly_match_id=""):
    out = copy.deepcopy(data or {})
    event = out.setdefault("event", {})
    event["competitionId"] = _TARGET
    event["sportId"] = "american-football"
    event["eventKind"] = "game"
    event["eventId"] = str(event_id or event.get("eventId") or "")
    out["competitionId"] = _TARGET
    out["eventId"] = str(event_id or out.get("eventId") or "")
    board = out.setdefault("scoreboard", {})
    if board.get("periods"):
        board["lineScoreType"] = "quarters"
    if highlightly_match_id:
        out["highlightlyMatchId"] = str(highlightly_match_id)
        out["providerEventIds"] = {
            **(out.get("providerEventIds") or {}),
            "espn": str(event_id or ""),
            "highlightly": str(highlightly_match_id),
        }
    out["gameCenterArchitecture"] = "NFL_SHARED_FOOTBALL"
    return out


def normalize_ncaaf_summary(payload, event_id):
    # Normalize as NFL first so team/player stats and football presentation stay on
    # the proven shared contract. Then restore NCAAF as the public namespace.
    normalized = _ORIGINAL_NORMALIZE(payload, "NFL", event_id)
    out = _rewrite_public_identity(normalized, event_id)
    _gc._apply_coverage_fields(out)
    return out


def fetch_espn_game_center(competition, event_id, fetch_json, site_api_base):
    competition = _clean(competition).upper()
    if competition != _TARGET:
        return _ORIGINAL_FETCH(competition, event_id, fetch_json, site_api_base)
    base = str(site_api_base).rstrip("/")
    payload = fetch_json(f"{base}/football/college-football/summary?event={event_id}", timeout=10)
    return normalize_ncaaf_summary(payload, event_id)


def game_center_coverage(data):
    comp = _clean((data or {}).get("competitionId") or (((data or {}).get("event") or {}).get("competitionId"))).upper()
    if comp != _TARGET:
        return _ORIGINAL_COVERAGE(data)
    probe = copy.deepcopy(data or {})
    probe["competitionId"] = "NFL"
    probe.setdefault("event", {})["competitionId"] = "NFL"
    result = dict(_ORIGINAL_COVERAGE(probe))
    result["competitionId"] = _TARGET
    return result


def _highlightly_enrichment(server, espn_data, event_id, hints):
    match_id = _lookup_highlightly_match(server, hints)
    if not match_id:
        return espn_data
    try:
        detail_payload = _highlightly_fetch(server, f"/matches/{match_id}", timeout=10)
        detail_rows = _unwrap_rows(detail_payload)
        match = detail_rows[0] if detail_rows else (detail_payload if isinstance(detail_payload, dict) else {})
        # Explicit box-score call gives the richest player tables even when the
        # match-detail plan omits embedded player data.
        try:
            box_payload = _highlightly_fetch(server, f"/box-score/{match_id}", timeout=10)
        except Exception:
            box_payload = None

        normalized = _gc.normalize_highlightly_game_center(
            match, "NFL", str(match_id), statistics_payload=None, box_payload=box_payload
        )
        periods = _period_scores(match)
        if periods:
            normalized.setdefault("scoreboard", {})["periods"] = periods
            normalized["scoreboard"]["lineScoreType"] = "quarters"
        timeline, scoring = _flatten_highlightly_events(match)
        if timeline:
            normalized["timeline"] = timeline
        if scoring:
            normalized["scoringPlays"] = scoring
        normalized["source"] = "Highlightly NCAA FBS match detail"
        normalized = _rewrite_public_identity(normalized, event_id, match_id)
        _gc._apply_coverage_fields(normalized)

        merged = _gc.merge_game_centers(normalized, espn_data)
        merged = _rewrite_public_identity(merged, event_id, match_id)
        merged["source"] = "ESPN Game Summary + Highlightly NCAA FBS"
        merged["ncaafEnrichment"] = {
            "provider": "highlightly",
            "reason": "ESPN_GAME_CENTER_INCOMPLETE",
            "matchId": str(match_id),
            "teamStats": len(merged.get("teamStats") or []),
            "playerSections": len(merged.get("playerStatSections") or []),
            "plays": len(merged.get("timeline") or []),
            "scoringPlays": len(merged.get("scoringPlays") or []),
        }
        _gc._apply_coverage_fields(merged)
        return merged
    except Exception as exc:
        out = copy.deepcopy(espn_data or {})
        out["ncaafEnrichmentError"] = f"{type(exc).__name__}: {exc}"
        return out



def _bool_qs(qs, name, default=False):
    raw = _clean((qs.get(name) or ["1" if default else "0"])[-1]).lower()
    return raw in {"1", "true", "yes", "on"}


def _direct_cache_ttl(data):
    status=_clean((((data or {}).get("scoreboard") or {}).get("status") or ((data or {}).get("event") or {}).get("status"))).lower()
    final=any(x in status for x in ("final","complete","finished","post")) and not bool((data or {}).get("live"))
    return _DIRECT_FINAL_TTL if final else _DIRECT_PARTIAL_TTL

def _direct_cache_get(event_id):
    now=time.time()
    with _DIRECT_LOCK:
        row=_DIRECT_CACHE.get(str(event_id))
        if not row:return None
        if now >= float(row.get("expiresAt") or 0):
            _DIRECT_CACHE.pop(str(event_id),None);return None
        return copy.deepcopy(row)

def peek_direct_game_center(event_id):
    """Read the NCAAF direct cache without causing provider work."""
    row=_direct_cache_get(event_id)
    return copy.deepcopy((row or {}).get("data")) if row else None

def _direct_fetch_and_cache(server,event_id,hints):
    # This is the critical v5.1.15 path: the exact ESPN id from the selected score
    # goes straight to the shared refresh/provider adapter. No alias/index lookup.
    data=server._game_center_refresh(_TARGET,str(event_id),hints=dict(hints or {}))
    data=_rewrite_public_identity(data,event_id,_clean((data or {}).get("highlightlyMatchId")))
    now=time.time();ttl=_direct_cache_ttl(data)
    with _DIRECT_LOCK:
        _DIRECT_CACHE[str(event_id)]={"data":copy.deepcopy(data),"at":now,"expiresAt":now+ttl}
    return data

def _start_direct_job(server,event_id,hints):
    key=str(event_id)
    with _DIRECT_LOCK:
        existing=_DIRECT_JOBS.get(key)
        if existing and existing.get("pending"):
            return False
        _DIRECT_JOBS[key]={"pending":True,"startedAt":time.time(),"error":""}
    def run():
        try:
            _direct_fetch_and_cache(server,key,hints)
            with _DIRECT_LOCK:
                _DIRECT_JOBS[key]={"pending":False,"completedAt":time.time(),"error":""}
        except Exception as exc:
            with _DIRECT_LOCK:
                _DIRECT_JOBS[key]={"pending":False,"completedAt":time.time(),"error":f"{type(exc).__name__}: {exc}"}
    threading.Thread(target=run,daemon=True,name=f"sbb-ncaaf-gc-{key[-8:]}").start()
    return True

def _direct_job_state(event_id):
    with _DIRECT_LOCK:return dict(_DIRECT_JOBS.get(str(event_id)) or {})

def _serve_shared_ncaaf_game_center(server, handler, parsed):
    """Serve NCAAF from its canonical ESPN id without generic identity resolution."""
    match = re.fullmatch(r"/api/events/NCAAF/([^/]+)/game-center", parsed.path, re.I)
    if not match:
        return False
    event_id = unquote(match.group(1))
    if not re.fullmatch(r"\d{6,12}",event_id):
        return server.send_json(handler,{"ok":False,"error":"BAD_GAME_CENTER_EVENT","message":"NCAAF Game Center requires the canonical numeric ESPN event id."},400)
    qs = parse_qs(parsed.query)
    force = _bool_qs(qs, "refresh", False) or _bool_qs(qs, "force", False)
    async_mode = not (_clean((qs.get("async") or ["1"])[-1]).lower() in {"0", "false", "no", "off"})
    hints = {
        "date": _clean((qs.get("date") or [""])[-1])[:10],
        "away": _clean((qs.get("away") or [""])[-1]),
        "home": _clean((qs.get("home") or [""])[-1]),
        "start": _clean((qs.get("start") or [""])[-1]),
        "gameNumber": _clean((qs.get("gameNumber") or [""])[-1]),
        "provider": _clean((qs.get("provider") or [""])[-1]),
    }
    try:
        cached=None if force else _direct_cache_get(event_id)
        if cached:
            return server.send_json(handler,{"ok":True,"data":cached.get("data"),"cache":"NCAAF_DIRECT_HIT","pending":False,"resolvedEventId":event_id,"contract":"1.0","route":"NCAAF_CANONICAL_ESPN"},200,{"X-SBB-GameCenter-Cache":"NCAAF_DIRECT_HIT"})

        if not async_mode:
            data=_direct_fetch_and_cache(server,event_id,hints)
            return server.send_json(handler,{"ok":True,"data":data,"cache":"NCAAF_DIRECT_REFRESH","pending":False,"resolvedEventId":event_id,"contract":"1.0","route":"NCAAF_CANONICAL_ESPN"},200,{"X-SBB-GameCenter-Cache":"NCAAF_DIRECT_REFRESH"})

        job=_direct_job_state(event_id)
        if job and not job.get("pending") and job.get("error") and not force:
            # Allow the next explicit retry/refresh to create a new job, but surface
            # the completed provider failure instead of an identity-resolution error.
            return server.send_json(handler,{"ok":False,"error":"NCAAF_GAME_CENTER_PROVIDER_ERROR","message":job.get("error"),"competition":_TARGET,"eventId":event_id,"resolvedEventId":event_id},502)
        if force or not job or not job.get("pending"):
            _start_direct_job(server,event_id,hints)
        return server.send_json(handler,{"ok":True,"pending":True,"cache":"PENDING","competition":_TARGET,"eventId":event_id,"resolvedEventId":event_id,"retryAfterMs":500,"contract":"1.0","route":"NCAAF_CANONICAL_ESPN"},202,{"X-SBB-GameCenter-Cache":"PENDING","Retry-After":"1"})
    except NotImplementedError as exc:
        return server.send_json(handler,{"ok":False,"error":"GAME_CENTER_PROVIDER_NOT_IMPLEMENTED","message":str(exc),"competition":_TARGET},501)
    except ValueError as exc:
        return server.send_json(handler,{"ok":False,"error":"BAD_GAME_CENTER_EVENT","message":str(exc)},400)
    except Exception as exc:
        return server.send_json(handler,{"ok":False,"error":"GAME_CENTER_ERROR","message":f"{type(exc).__name__}: {exc}"},502)


def _patch_server(server):
    """Install the NCAAF completeness fallback after server.py owns its globals."""
    if getattr(server, "__sbbNcaafGameCenterV5115", False):
        return True
    required = (
        "GAME_CENTER_SUPPORTED",
        "_game_center_refresh",
        "_game_center_needs_enrichment",
        "_highlightly_gc_fetch_json",
        "_same_team_pair",
        "send_json",
        "Handler",
    )
    if not all(hasattr(server, name) for name in required):
        return False
    # Competition Builder owns the NCAAF schedule, so wait until its generic
    # handler is installed and then wrap *above* it.  Otherwise a race can put
    # the generic custom Game Center back on top after this patch.
    if not getattr(server.Handler, "__sbbCompetitionBuilderInstalled", False):
        return False

    supported = getattr(server, "GAME_CENTER_SUPPORTED", None)
    if hasattr(supported, "add"):
        supported.add(_TARGET)
    elif isinstance(supported, list) and _TARGET not in supported:
        supported.append(_TARGET)

    # Allow the existing Highlightly detail helper to understand NCAAF if another
    # server path ever gives it a verified hl-* id. This does not change score IDs.
    mapping = getattr(server, "HIGHLIGHTLY_COMPETITION_KEY", None)
    if isinstance(mapping, dict):
        mapping[_TARGET] = "nfl"

    original_refresh = server._game_center_refresh

    def game_center_refresh(competition, event_id, hints=None):
        comp = _clean(competition).upper()
        data = original_refresh(competition, event_id, hints=hints)
        if comp != _TARGET:
            return data
        try:
            incomplete = bool(server._game_center_needs_enrichment(data, _TARGET))
        except Exception:
            incomplete = not bool((game_center_coverage(data) or {}).get("complete"))
        if not incomplete:
            return _rewrite_public_identity(data, event_id)
        enriched = _highlightly_enrichment(server, data, event_id, hints or {})
        return _rewrite_public_identity(enriched, event_id, _clean((enriched or {}).get("highlightlyMatchId")))

    server._game_center_refresh = game_center_refresh

    Handler = server.Handler
    if not getattr(Handler, "__sbbNcaafSharedGameCenterRouteV5115", False):
        old_get = Handler.do_GET
        def do_GET(self):
            parsed = urlparse(self.path)
            handled = _serve_shared_ncaaf_game_center(server, self, parsed)
            if handled is not False:
                return handled
            return old_get(self)
        Handler.do_GET = do_GET
        Handler.__sbbNcaafSharedGameCenterRouteV5115 = True

    server.__sbbNcaafGameCenterV5115 = True
    try:
        wiring = getattr(server, "SBB_BACKEND_WIRING", None)
        if isinstance(wiring, dict):
            gc = wiring.setdefault("gameCenter", {})
            gc["ncaaf"] = "canonical ESPN event id -> ESPN summary -> Highlightly NCAA FBS completeness fallback -> shared NFL football contract"
    except Exception:
        pass
    try:
        server.MILESTONE_CONSOLE.record(
            "game-center",
            "PASS",
            "v5.1.15 NCAAF canonical ESPN Game Center route installed",
            {"primary": "ESPN college-football", "fallback": "Highlightly NCAA FBS", "namespace": _TARGET},
        )
    except Exception:
        pass
    return True


def _worker():
    for _ in range(600):
        server = sys.modules.get("__main__")
        if server is not None and _patch_server(server):
            return
        time.sleep(0.2)


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        _gc.fetch_espn_game_center = fetch_espn_game_center
        _gc.game_center_coverage = game_center_coverage
        _INSTALLED = True
    threading.Thread(target=_worker, daemon=True, name="sbb-ncaaf-game-center-v5115").start()
    return True


__all__ = [
    "VERSION",
    "install",
    "fetch_espn_game_center",
    "normalize_ncaaf_summary",
    "game_center_coverage",
    "_lookup_highlightly_match",
    "_highlightly_enrichment",
    "peek_direct_game_center",
]

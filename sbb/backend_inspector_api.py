"""Sports Big Board v5.1.14 backend inspector read model.

One bounded, read-only endpoint exposes the authoritative normalized media
relationships and already-cached Game Center readiness for every game on a date.
It never launches media discovery and never fetches a Game Center provider.

This exists specifically to compare:
  history media DB authority -> compact ribbon event plan -> frontend rendering
without conflating those three layers.
"""
from __future__ import annotations

import copy
import re
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

VERSION = "5.1.14-backend-inspector-api-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean(value):
    return str(value or "").strip()


def _league(row):
    return _clean((row or {}).get("competitionId") or (row or {}).get("__sbbLeague") or (row or {}).get("league")).upper()


def _event_id(row):
    for key in ("gameCenterEventId", "scoreEventId", "espnEventId", "gamePk", "canonicalEventId", "eventId", "matchId", "id"):
        value = (row or {}).get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _team_obj(row, side):
    row = row or {}
    return row.get(f"{side}Team") or row.get(side) or {}


def _team_key(value):
    if isinstance(value, dict):
        value = value.get("abbreviation") or value.get("displayName") or value.get("name") or value.get("shortName") or ""
    return re.sub(r"[^a-z0-9]+", "", _clean(value).lower().replace("&", "and"))


def _same_team_pair(a, b):
    return bool(
        _team_key(_team_obj(a, "away"))
        and _team_key(_team_obj(a, "away")) == _team_key(_team_obj(b, "away"))
        and _team_key(_team_obj(a, "home"))
        and _team_key(_team_obj(a, "home")) == _team_key(_team_obj(b, "home"))
    )


def _media_key(item):
    item = item or {}
    return _clean(item.get("youtubeId") or item.get("mediaUrl") or item.get("externalUrl") or item.get("assetKey") or item.get("id"))


def _runtime_usable(item):
    item = item or {}
    state = _clean(item.get("runtimeCatalogState") or item.get("runtimeState") or item.get("validationState")).upper()
    if state in {"FAILED", "FAILED-QUARANTINED", "REJECTED", "BROKEN"}:
        return False
    return bool(item.get("verifiedPlayable")) and bool(item.get("youtubeId") or item.get("mediaUrl"))


def _tier(item):
    raw = _clean((item or {}).get("recapTier") or (item or {}).get("tier")).lower()
    if raw in {"gold", "green", "extended", "blue"}:
        return raw
    return "blue" if _runtime_usable(item) else ""


def _media_summary(server, date, league, event_id, score_row=None, catalog_rows=None):
    repo = getattr(server, "HISTORY_REPOSITORY", None)
    rows = []
    resolved_media_event_id = event_id
    identity_resolution = "EXACT"

    def read_event_media(candidate_id):
        if repo is None or not hasattr(repo, "event_media") or not candidate_id:
            return []
        try:
            return list(repo.event_media(date, league, candidate_id, include_failed=False) or [])
        except TypeError:
            try:
                return list(repo.event_media(date, league, candidate_id) or [])
            except Exception:
                return []
        except Exception:
            return []

    rows = read_event_media(event_id)
    # The audit database can legitimately retain a canonical event identity while
    # a score provider changes IDs.  Resolve that read-only disconnect by exact
    # alias/team-date evidence, but never guess across ambiguous same-team games.
    if not rows and score_row and catalog_rows:
        score_ids = {str((score_row or {}).get(k)) for k in ("scoreEventId","espnEventId","gameCenterEventId","matchId","gamePk","canonicalEventId","eventId","id") if (score_row or {}).get(k) not in (None,"")}
        id_matches = []
        team_matches = []
        for cat in catalog_rows:
            if not isinstance(cat, dict):
                continue
            ev = dict(cat.get("event") or {})
            cid = _clean(cat.get("eventId") or _event_id(ev))
            if not cid:
                continue
            cat_ids = {str(ev.get(k)) for k in ("scoreEventId","espnEventId","gameCenterEventId","matchId","gamePk","canonicalEventId","eventId","id") if ev.get(k) not in (None,"")}
            cat_ids.add(cid)
            if score_ids and score_ids & cat_ids:
                id_matches.append(cid)
            elif _same_team_pair(score_row, ev):
                team_matches.append(cid)
        candidates = list(dict.fromkeys(id_matches or team_matches))
        if len(candidates) == 1:
            fallback_rows = read_event_media(candidates[0])
            if fallback_rows:
                rows = fallback_rows
                resolved_media_event_id = candidates[0]
                identity_resolution = "CATALOG_ID" if id_matches else "TEAM_DATE_FALLBACK"

    # Deduplicate physical assets while retaining the richest relationship record.
    deduped = []
    seen = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        try:
            annotate = getattr(server, "annotate_media_tier", None)
            if callable(annotate) and not item.get("recapTier"):
                item = annotate(item) or item
        except Exception:
            pass
        key = _media_key(item)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(item)

    playable = [x for x in deduped if _runtime_usable(x)]
    tiers = {"green": 0, "extended": 0, "gold": 0, "blue": 0}
    for item in playable:
        t = _tier(item)
        if t in tiers:
            tiers[t] += 1
    return {
        "media": deduped,
        "playable": playable,
        "mediaCount": len(deduped),
        "playableCount": len(playable),
        "tiers": tiers,
        "resolvedMediaEventId": resolved_media_event_id,
        "identityResolution": identity_resolution,
    }


def _game_center_summary(server, league, event_id):
    repo = getattr(server, "GAME_CENTER_REPOSITORY", None)
    if repo is None or not event_id:
        return {"state": "MISS", "cached": False}
    resolved = ""
    try:
        resolved = _clean(repo.resolve_alias(league, event_id))
    except Exception:
        resolved = ""
    record = None
    for candidate in (resolved, event_id):
        if not candidate:
            continue
        try:
            record = repo.get(league, candidate)
        except Exception:
            record = None
        if record:
            resolved = candidate
            break
    if not record:
        return {"state": "MISS", "cached": False, "resolvedEventId": resolved or event_id}

    data = copy.deepcopy(record.get("data") or {})
    coverage = data.get("coverage") or {}
    if not coverage:
        coverage_fn = getattr(server, "game_center_coverage", None)
        if callable(coverage_fn):
            try:
                coverage = dict(coverage_fn(data) or {})
            except Exception:
                coverage = {}
    sections = data.get("playerStatSections") or []
    player_rows = sum(len((section or {}).get("rows") or []) for section in sections if isinstance(section, dict))
    team_stats = data.get("teamStats") or []
    timeline = data.get("timeline") or []
    scoring = data.get("scoringPlays") or []
    complete = bool(coverage.get("complete"))
    if not coverage:
        # A non-empty shell is still PARTIAL; only an explicit coverage result or
        # real rich fields can call the cache RICH.
        complete = bool(team_stats and (sections or timeline))
    return {
        "state": "RICH" if complete else "PARTIAL",
        "cached": True,
        "resolvedEventId": resolved or event_id,
        "source": _clean(data.get("source") or record.get("provider")),
        "savedAt": record.get("savedAt"),
        "expiresAt": record.get("expiresAt"),
        "complete": complete,
        "teamStats": len(team_stats),
        "playerSections": len(sections),
        "playerRows": player_rows,
        "plays": len(timeline),
        "scoringPlays": len(scoring),
        "coverage": coverage,
    }


def _date_payload(server, date):
    try:
        score_rows = server._history_day_score_rows(date) or {}
    except Exception:
        score_rows = {}

    games = {}
    retired = []
    catalog_by_league = {}
    repo = getattr(server, "HISTORY_REPOSITORY", None)
    if repo is not None and hasattr(repo, "catalog_events"):
        try:
            for cat in repo.catalog_events(date_from=date, date_to=date, limit=50000) or []:
                if not isinstance(cat, dict):
                    continue
                lg = _clean(cat.get("league") or ((cat.get("event") or {}).get("competitionId"))).upper()
                if lg:
                    catalog_by_league.setdefault(lg, []).append(cat)
        except Exception:
            catalog_by_league = {}
    summary = {
        "activeGames": 0,
        "retiredCfbGames": 0,
        "gamesWithMedia": 0,
        "playableGames": 0,
        "mediaAssets": 0,
        "playableAssets": 0,
        "tiers": {"green": 0, "extended": 0, "purple": 0, "gold": 0, "blue": 0},
        "gcCached": 0,
        "gcRich": 0,
        "gcPartial": 0,
        "gcMissing": 0,
    }

    for league_raw, rows in (score_rows or {}).items():
        league = _clean(league_raw).upper()
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            event_id = _event_id(row)
            if league == "CFB":
                retired.append({"league": league, "eventId": event_id, "event": row})
                summary["retiredCfbGames"] += 1
                continue
            if not league or not event_id:
                continue
            media = _media_summary(server, date, league, event_id, score_row=row, catalog_rows=catalog_by_league.get(league) or [])
            gc = _game_center_summary(server, league, event_id)
            key = f"{league}:{event_id}"
            games[key] = {
                "league": league,
                "eventId": event_id,
                "media": media.get("media") or [],
                "playable": media.get("playable") or [],
                "mediaCount": media.get("mediaCount") or 0,
                "playableCount": media.get("playableCount") or 0,
                "tiers": media.get("tiers") or {},
                "resolvedMediaEventId": media.get("resolvedMediaEventId") or event_id,
                "mediaIdentityResolution": media.get("identityResolution") or "EXACT",
                "gameCenter": gc,
            }
            summary["activeGames"] += 1
            if media.get("mediaCount"):
                summary["gamesWithMedia"] += 1
            if media.get("playableCount"):
                summary["playableGames"] += 1
            summary["mediaAssets"] += int(media.get("mediaCount") or 0)
            summary["playableAssets"] += int(media.get("playableCount") or 0)
            for tier in ("green", "extended", "gold", "blue"):
                summary["tiers"][tier] += int((media.get("tiers") or {}).get(tier) or 0)
            summary["tiers"]["purple"] = summary["tiers"]["extended"]
            if gc.get("cached"):
                summary["gcCached"] += 1
                if gc.get("state") == "RICH":
                    summary["gcRich"] += 1
                else:
                    summary["gcPartial"] += 1
            else:
                summary["gcMissing"] += 1

    return {
        "ok": True,
        "version": getattr(server, "APP_VERSION", ""),
        "inspectorVersion": VERSION,
        "date": date,
        "summary": summary,
        "games": games,
        "retired": retired,
        "readOnly": True,
        "providerFetches": False,
        "generatedAt": time.time(),
    }


def _install_into_server():
    for _ in range(600):
        server = sys.modules.get("__main__")
        if server and all(hasattr(server, name) for name in ("Handler", "send_json", "HISTORY_REPOSITORY", "GAME_CENTER_REPOSITORY", "_history_day_score_rows")):
            break
        time.sleep(0.2)
    else:
        return

    Handler = server.Handler
    if getattr(Handler, "__sbbBackendInspectorApiV5114", False):
        return
    old_get = Handler.do_GET

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/backend-inspector/date":
            qs = parse_qs(parsed.query)
            date = _clean((qs.get("date") or [""])[-1])[:10]
            if not _DATE_RE.fullmatch(date):
                return server.send_json(self, {"ok": False, "error": "DATE_REQUIRED"}, 400)
            try:
                return server.send_json(self, _date_payload(server, date), 200)
            except Exception as exc:
                return server.send_json(self, {"ok": False, "error": "BACKEND_INSPECTOR_FAILED", "message": f"{type(exc).__name__}: {exc}"}, 500)
        return old_get(self)

    Handler.do_GET = do_GET
    Handler.__sbbBackendInspectorApiV5114 = True


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-backend-inspector-api-v5114").start()
    return True


__all__ = ["VERSION", "install"]

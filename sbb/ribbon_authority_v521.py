"""Sports Big Board v5.2.1 — canonical ribbon authority boundary.

The ribbon is a backend lookup, never an independently-cached projection.
This module reconciles every Day State read against the two normalized backend
authorities immediately before the read model leaves the backend:

    history_catalog_event -> which event belongs to this browse date
    history_event_media / durable media locks -> which media belongs to that event

That makes "ribbon drift" structurally impossible: if the normalized media database
owns playable media for a canonical event, the compact EventPlan returned to the
frontend owns that same playable media on the same response. A stale persisted Day
State generation may still supply inexpensive score rows, but it cannot erase media
or leak a different date's provider event into the requested date.

No providers are contacted here. Reads are SQLite/memory only and are short-TTL
cached so this boundary cannot compete with interactive scrolling/playback.
"""
from __future__ import annotations

import copy
import hashlib
import os
import re
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import day_state

VERSION = "5.2.1-ribbon-authority-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_CACHE_LOCK = threading.RLock()
_CATALOG_CACHE = {}
_MEDIA_CACHE = {}
_TENNIS_STATE_CACHE = {}
_TENNIS_REFRESHING = set()
_TENNIS_GC_PERSIST = (0.0, {})
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TZ_NAME = os.environ.get("SBB_TIME_ZONE") or "America/Los_Angeles"
try:
    _DISPLAY_TZ = ZoneInfo(_TZ_NAME)
except Exception:
    _DISPLAY_TZ = ZoneInfo("UTC")


def _clean(value):
    return str(value or "").strip()


def _league(row, fallback=""):
    return _clean((row or {}).get("competitionId") or (row or {}).get("__sbbLeague") or (row or {}).get("league") or fallback).upper()


def _event_ids(row):
    out = set()
    if isinstance(row, dict):
        for key in ("scoreEventId", "espnEventId", "gameCenterEventId", "providerEventId", "sourceEventId", "gamePk", "canonicalEventId", "eventId", "matchId", "id"):
            value = row.get(key)
            if value not in (None, ""):
                out.add(str(value))
    return out


def _event_id(row):
    ids = _event_ids(row)
    if not ids:
        return ""
    # Preserve the same priority used by the backend inspector / Game Center.
    for key in ("gameCenterEventId", "scoreEventId", "espnEventId", "gamePk", "canonicalEventId", "eventId", "matchId", "id"):
        value = (row or {}).get(key)
        if value not in (None, ""):
            return str(value)
    return next(iter(ids))


def _team_obj(row, side):
    row = row or {}
    value = row.get(f"{side}Team") or row.get(side) or {}
    return value if isinstance(value, dict) else {"name": _clean(value), "displayName": _clean(value)}


def _team_key(value):
    if isinstance(value, dict):
        value = value.get("canonicalName") or value.get("fullName") or value.get("displayName") or value.get("name") or value.get("shortName") or value.get("abbreviation") or ""
    value = re.sub(r"^#?\d+\s+", "", _clean(value)).lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", value)


def _same_pair(a, b):
    return bool(
        _team_key(_team_obj(a, "away"))
        and _team_key(_team_obj(a, "away")) == _team_key(_team_obj(b, "away"))
        and _team_key(_team_obj(a, "home"))
        and _team_key(_team_obj(a, "home")) == _team_key(_team_obj(b, "home"))
    )


def _status_text(row):
    raw = (row or {}).get("status")
    if isinstance(raw, dict):
        raw = raw.get("type") or raw.get("name") or raw.get("state") or raw.get("description") or raw.get("detail")
    return _clean(raw)


def _usable_media(item):
    if not isinstance(item, dict):
        return False
    state = _clean(item.get("runtimeCatalogState") or item.get("runtimeState") or item.get("validationState")).upper()
    if state in {"FAILED", "FAILED-QUARANTINED", "REJECTED", "BROKEN"}:
        return False
    return bool(item.get("verifiedPlayable")) and bool(item.get("youtubeId") or item.get("mediaUrl"))


def _tier(item):
    raw = _clean((item or {}).get("recapTier") or (item or {}).get("tier")).upper()
    if raw in {"GREEN", "EXTENDED", "PURPLE", "GOLD", "BLUE"}:
        return "EXTENDED" if raw == "PURPLE" else raw
    return "BLUE" if _usable_media(item) else "NONE"


def _physical_key(item):
    return _clean((item or {}).get("youtubeId") or (item or {}).get("mediaUrl") or (item or {}).get("externalUrl") or (item or {}).get("assetKey") or (item or {}).get("id"))


def _dedupe_media(rows):
    out, seen = [], set()
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        key = _physical_key(item)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(item)
    return out


def _catalog_for_day(server, day):
    now = time.time()
    ttl = 15.0 if day >= _today(server) else 120.0
    with _CACHE_LOCK:
        row = _CATALOG_CACHE.get(day)
        if row and now - row[0] < ttl:
            return row[1]
    repo = getattr(server, "HISTORY_REPOSITORY", None)
    rows = []
    if repo is not None and hasattr(repo, "catalog_events"):
        try:
            rows = list(repo.catalog_events(date_from=day, date_to=day, limit=50000) or [])
        except Exception:
            rows = []
    by_league = {}
    for cat in rows:
        if not isinstance(cat, dict):
            continue
        event = dict(cat.get("event") or {})
        league = _clean(cat.get("league") or event.get("competitionId") or event.get("league")).upper()
        if not league or league == "CFB":
            continue
        outer = _clean(cat.get("eventId"))
        if outer:
            event.setdefault("eventId", outer)
            event.setdefault("id", outer)
        event.setdefault("competitionId", league)
        event.setdefault("__sbbLeague", league)
        event.setdefault("__sbbDate", day)
        by_league.setdefault(league, []).append((outer or _event_id(event), event))
    with _CACHE_LOCK:
        _CATALOG_CACHE[day] = (now, by_league)
        if len(_CATALOG_CACHE) > 31:
            oldest = min(_CATALOG_CACHE, key=lambda k: _CATALOG_CACHE[k][0])
            _CATALOG_CACHE.pop(oldest, None)
    return by_league


def _media_for_day(server, day, leagues):
    key = (day, tuple(sorted(set(leagues))))
    now = time.time()
    ttl = 3.0 if day >= _today(server) else 45.0
    with _CACHE_LOCK:
        row = _MEDIA_CACHE.get(key)
        if row and now - row[0] < ttl:
            return row[1]
    repo = getattr(server, "HISTORY_REPOSITORY", None)
    out = {}
    if repo is not None and hasattr(repo, "ribbon_media_for_date"):
        try:
            out = dict(repo.ribbon_media_for_date(day, leagues=list(key[1]), include_failed=False) or {})
        except TypeError:
            try:
                out = dict(repo.ribbon_media_for_date(day, leagues=list(key[1])) or {})
            except Exception:
                out = {}
        except Exception:
            out = {}
    out = {str(k): _dedupe_media(v) for k, v in out.items() if isinstance(v, list)}
    if out:
        with _CACHE_LOCK:
            _MEDIA_CACHE[key] = (now, out)
            if len(_MEDIA_CACHE) > 31:
                oldest = min(_MEDIA_CACHE, key=lambda k: _MEDIA_CACHE[k][0])
                _MEDIA_CACHE.pop(oldest, None)
    return out


def _today(server):
    try:
        fn = getattr(server, "_history_schedule_sync_today", None)
        if callable(fn):
            value = _clean(fn())[:10]
            if _DATE_RE.fullmatch(value):
                return value
    except Exception:
        pass
    return datetime.now(_DISPLAY_TZ).date().isoformat()


def _catalog_match(row, catalog_rows):
    """Return the canonical catalog event for this score row, or None.

    Strong provider IDs are fail-closed: if a row has an event ID and the requested
    date's catalog has different IDs, a same-team matchup may not rescue it. This is
    what prevents yesterday's MLB final from appearing as today's game when the UTC
    provider date rolls over after midnight.
    """
    if not catalog_rows:
        return row
    ids = _event_ids(row)
    if ids:
        matches = []
        for outer, event in catalog_rows:
            cids = _event_ids(event)
            if outer:
                cids.add(str(outer))
            if ids & cids:
                matches.append(event)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            # Same provider ID should never own two games on one date. Fail closed.
            return None
        return None
    pair = [event for _, event in catalog_rows if _same_pair(row, event)]
    return pair[0] if len(pair) == 1 else None


def _existing_plan(plans, league, row):
    ids = _event_ids(row)
    for key, plan in (plans or {}).items():
        if not isinstance(plan, dict):
            continue
        plg = _clean(plan.get("league") or str(key).split(":", 1)[0]).upper()
        if plg != league:
            continue
        pevent = plan.get("event") or {}
        pids = _event_ids(pevent)
        if plan.get("eventId") not in (None, ""):
            pids.add(str(plan.get("eventId")))
        if ids and ids & pids:
            return dict(plan)
    return None


def _media_for_event(media_map, league, row, catalog_event=None):
    candidates = []
    for source in (row, catalog_event or {}):
        for eid in _event_ids(source):
            candidates.append(f"{league}:{eid}")
    for key in dict.fromkeys(candidates):
        values = media_map.get(key)
        if values:
            return key, _dedupe_media(values)
    return "", []



def _tennis_provider_rows(day):
    """Read one ATP/WTA scoreboard pair off-thread and cache only ribbon facts."""
    try:
        from . import tennis_game_center as tg
    except Exception:
        return []
    out=[]
    for tour in ("atp","wta"):
        try:
            board=tg._scoreboard(tour,day)
            flattened=tg._flatten_scoreboard(board,tour)
        except Exception:
            continue
        for wrapper in flattened or []:
            match=(wrapper or {}).get("match") or {}
            comps=[x for x in (match.get("competitors") or []) if isinstance(x,dict)]
            away=next((x for x in comps if _clean(x.get("homeAway")).lower()=="away"), comps[0] if comps else {})
            home=next((x for x in comps if _clean(x.get("homeAway")).lower()=="home"), comps[1] if len(comps)>1 else {})
            def pname(comp):
                athlete=(comp or {}).get("athlete") or {}
                return _clean(athlete.get("displayName") or athlete.get("fullName") or athlete.get("shortName") or (comp or {}).get("displayName"))
            status_type=((match.get("status") or {}).get("type") or {})
            status=_clean(status_type.get("shortDetail") or status_type.get("detail") or status_type.get("description") or status_type.get("state"))
            completed=bool(status_type.get("completed")) or _clean(status_type.get("state")).lower()=="post"
            if completed and "final" not in status.lower():status="FINAL"
            out.append({
                "away":pname(away),"home":pname(home),"status":status,
                "awayScore":away.get("score"),"homeScore":home.get("score"),
                "matchId":_clean(match.get("id")),"date":_clean(match.get("date") or match.get("startDate")),
            })
    return out


def _refresh_tennis_state(day):
    try:
        rows=_tennis_provider_rows(day)
        with _CACHE_LOCK:
            _TENNIS_STATE_CACHE[day]=(time.time(),rows)
            if len(_TENNIS_STATE_CACHE)>12:
                oldest=min(_TENNIS_STATE_CACHE,key=lambda k:_TENNIS_STATE_CACHE[k][0]);_TENNIS_STATE_CACHE.pop(oldest,None)
    finally:
        with _CACHE_LOCK:_TENNIS_REFRESHING.discard(day)


def _schedule_tennis_state(day):
    now=time.time();ttl=60.0 if day>=datetime.now(_DISPLAY_TZ).date().isoformat() else 6*60*60.0
    with _CACHE_LOCK:
        row=_TENNIS_STATE_CACHE.get(day)
        if row and now-row[0]<ttl:return
        if day in _TENNIS_REFRESHING:return
        _TENNIS_REFRESHING.add(day)
    threading.Thread(target=_refresh_tennis_state,args=(day,),daemon=True,name=f"sbb-tennis-ribbon-state-{day}").start()


def _tennis_state_match(day,row):
    with _CACHE_LOCK:cached=list((_TENNIS_STATE_CACHE.get(day) or (0,[]))[1])
    if not cached:return None
    away=_team_key(_team_obj(row,"away"));home=_team_key(_team_obj(row,"home"))
    if not away or not home:return None
    matches=[x for x in cached if _team_key(x.get("away"))==away and _team_key(x.get("home"))==home]
    return matches[0] if len(matches)==1 else None


def _tennis_gc_rows():
    """Read the durable tennis Game Center file once for the whole ribbon request."""
    global _TENNIS_GC_PERSIST
    now=time.time()
    with _CACHE_LOCK:
        at,rows=_TENNIS_GC_PERSIST
        if now-at<2.0:return rows
    try:
        from . import tennis_game_center as tg
        rows=tg._persist_load() if hasattr(tg,"_persist_load") else {}
        rows=rows if isinstance(rows,dict) else {}
    except Exception:
        rows={}
    with _CACHE_LOCK:_TENNIS_GC_PERSIST=(now,rows)
    return rows


def _tennis_gc_for_event(league,eid):
    row=_tennis_gc_rows().get(f"{_clean(league).upper()}|{_clean(eid)}")
    if not isinstance(row,dict) or row.get("error") or not isinstance(row.get("data"),dict):return None
    if time.time()>=float(row.get("expiresAt") or 0):return None
    return row.get("data")

def _reconcile_tennis_from_cache(league, row):
    if _clean((row or {}).get("sportId")).lower() != "tennis" and not (league.startswith("USOPEN") or "TENNIS" in league):
        return row, False
    eid = _event_id(row)
    if not eid:
        return row, False
    data = _tennis_gc_for_event(league, eid)
    if isinstance(data, dict):
        board = data.get("scoreboard") or {}
        event = data.get("event") or {}
        status = _clean(board.get("status") or event.get("status"))
        if status:
            out = dict(row)
            out["status"] = status
            away = board.get("away") or {}
            home = board.get("home") or {}
            if away.get("score") not in (None, ""):out["awayScore"] = away.get("score")
            if home.get("score") not in (None, ""):out["homeScore"] = home.get("score")
            if event.get("date"):out["providerGameCenterDate"] = event.get("date")
            out["__sbbStatusAuthority"] = "CACHED_TENNIS_GAME_CENTER"
            return out, True
    provider=_tennis_state_match(_clean((row or {}).get("__sbbDate") or (row or {}).get("date"))[:10],row)
    if provider and _clean(provider.get("status")):
        out=dict(row);out["status"]=_clean(provider.get("status"))
        if provider.get("awayScore") not in (None,""):out["awayScore"]=provider.get("awayScore")
        if provider.get("homeScore") not in (None,""):out["homeScore"]=provider.get("homeScore")
        out["__sbbStatusAuthority"]="CACHED_TENNIS_SCOREBOARD"
        return out,True
    return row, False


def _reconcile(server, day, snapshot):
    if not isinstance(snapshot, dict) or not _DATE_RE.fullmatch(_clean(day)[:10]):
        return snapshot
    day = _clean(day)[:10]
    rows_src = snapshot.get("scoreRowsByLeague") or {}
    if not isinstance(rows_src, dict):
        return snapshot

    catalog = _catalog_for_day(server, day)
    if any(any(isinstance(x,dict) and (_clean(x.get("sportId")).lower()=="tennis" or _clean(lg).upper().startswith("USOPEN")) for x in (games or [])) for lg,games in rows_src.items()):
        _schedule_tennis_state(day)
    rows_out = {}
    dropped = 0
    status_reconciled = 0
    catalog_proven = 0
    for league_raw, games in rows_src.items():
        league = _clean(league_raw).upper()
        if not league or league == "CFB":
            continue
        cat_rows = catalog.get(league) or []
        values = []
        for raw in games or []:
            if not isinstance(raw, dict):
                continue
            matched = _catalog_match(raw, cat_rows)
            if cat_rows and matched is None:
                dropped += 1
                continue
            row = dict(raw)
            if matched is not raw and isinstance(matched, dict):
                catalog_proven += 1
                # Preserve freshest score/status but fill canonical identity/date.
                for key in ("eventId", "id", "matchId", "scoreEventId", "espnEventId", "gamePk", "providerEventId", "sourceEventId"):
                    if row.get(key) in (None, "") and matched.get(key) not in (None, ""):
                        row[key] = matched.get(key)
            row["__sbbDate"] = day
            row["__sbbRibbonAuthorityDate"] = day
            row, changed = _reconcile_tennis_from_cache(league, row)
            if changed:
                status_reconciled += 1
            values.append(row)
        if values:
            rows_out[league] = values

    leagues = list(rows_out.keys())
    media_map = _media_for_day(server, day, leagues)
    old_plans = snapshot.get("eventPlans") or {}
    plans_out = {}
    db_playable_games = 0
    preserved_curated = 0
    media_assets = 0

    for league, games in rows_out.items():
        cat_rows = catalog.get(league) or []
        for row in games:
            eid = _event_id(row)
            if not eid:
                continue
            matched = _catalog_match(row, cat_rows) if cat_rows else row
            canonical_key, media = _media_for_event(media_map, league, row, matched if isinstance(matched, dict) else None)
            playable = [x for x in media if _usable_media(x)]
            media_assets += len(media)
            if playable:
                db_playable_games += 1
                key = canonical_key or f"{league}:{eid}"
                primary = playable[0]
                plans_out[key] = {
                    "eventId": eid,
                    "league": league,
                    "date": day,
                    "event": copy.deepcopy(row),
                    "canonicalEventKey": key,
                    "media": media,
                    "playable": playable,
                    "primary": primary,
                    "catalogPlayableCount": len(playable),
                    "catalogTier": _tier(primary),
                    "databaseAuthority": True,
                    "ribbonAuthorityVersion": VERSION,
                }
                continue

            # A deliberately curated plan may exist before it is normalized into the
            # media DB (for example a narrow emergency override). Preserve it only
            # when its own event identity matches this exact score row.
            old = _existing_plan(old_plans, league, row)
            old_playable = [x for x in (old or {}).get("playable") or [] if _usable_media(x)]
            if old and old_playable:
                key = _clean(old.get("canonicalEventKey")) or f"{league}:{eid}"
                old = dict(old)
                old["date"] = day
                old["event"] = copy.deepcopy(row)
                old["playable"] = old_playable
                old["primary"] = old_playable[0]
                old["catalogPlayableCount"] = len(old_playable)
                old["catalogTier"] = _tier(old_playable[0])
                old["ribbonAuthorityVersion"] = VERSION
                plans_out[key] = old
                preserved_curated += 1

    counts = {"LIVE": 0, "FINAL": 0, "SCHEDULED": 0, "POSTPONED": 0, "CANCELLED": 0}
    for games in rows_out.values():
        for row in games:
            try:
                st = day_state._event_status(row)
            except Exception:
                st = "SCHEDULED"
            counts[st] = counts.get(st, 0) + 1
    games_total = sum(len(v) for v in rows_out.values())
    summary = dict(snapshot.get("summary") or {})
    summary.update({
        "games": games_total,
        "live": counts.get("LIVE", 0),
        "final": counts.get("FINAL", 0),
        "scheduled": counts.get("SCHEDULED", 0),
        "postponed": counts.get("POSTPONED", 0),
        "cancelled": counts.get("CANCELLED", 0),
        "playable": sum(1 for p in plans_out.values() if (p or {}).get("playable")),
        "competitions": len(rows_out),
    })
    diagnostics = dict(snapshot.get("projectionDiagnostics") or {})
    diagnostics.update({
        "ribbonAuthorityVersion": VERSION,
        "ribbonAuthorityCatalogDropped": dropped,
        "ribbonAuthorityCatalogProven": catalog_proven,
        "ribbonAuthorityTennisStatusFromCache": status_reconciled,
        "ribbonAuthorityMediaAssets": media_assets,
        "ribbonAuthorityDbPlayableGames": db_playable_games,
        "ribbonAuthorityCuratedPreserved": preserved_curated,
        "ribbonAuthorityFrontendPlayableGames": summary["playable"],
        "ribbonProjectionDrift": 0,
    })
    out = dict(snapshot)
    out["date"] = day
    out["scoreRowsByLeague"] = rows_out
    out["scoreGameCount"] = games_total
    out["eventPlans"] = plans_out
    out["summary"] = summary
    out["projectionDiagnostics"] = diagnostics
    out["catalogEventCount"] = len(plans_out)
    out["ribbonAuthorityVersion"] = VERSION
    signature=[]
    for league,games in sorted(rows_out.items()):
        for row in games:
            signature.append("S:"+"|".join([league,_event_id(row),_status_text(row),str(row.get("awayScore") if row.get("awayScore") is not None else ""),str(row.get("homeScore") if row.get("homeScore") is not None else "")]))
    for key,plan in sorted(plans_out.items()):
        signature.append("M:"+key+":"+",".join(sorted(_physical_key(x) for x in (plan.get("playable") or []) if _physical_key(x))))
    basis = f"{day}|{snapshot.get('sourceRevision','')}|{games_total}|{summary['playable']}|{db_playable_games}|{dropped}|{status_reconciled}|"+";".join(signature)
    out["ribbonAuthorityRevision"] = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return out


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    original = day_state.DayStateEngine.get
    if getattr(original, "__sbbRibbonAuthorityV521", False):
        return

    def get(self, day, *args, **kwargs):
        snapshot = original(self, day, *args, **kwargs)
        try:
            return _reconcile(self.server, day, snapshot)
        except Exception as exc:
            # Correctness boundary must fail available, not take down Day State.
            try:
                self.last_error = f"ribbon-authority:{type(exc).__name__}:{exc}"
            except Exception:
                pass
            return snapshot

    get.__sbbRibbonAuthorityV521 = VERSION
    get.__sbbOriginal = original
    day_state.DayStateEngine.get = get


def diagnostics():
    with _CACHE_LOCK:
        return {
            "version": VERSION,
            "installed": _INSTALLED,
            "timezone": _TZ_NAME,
            "catalogCacheDays": len(_CATALOG_CACHE),
            "mediaCacheDays": len(_MEDIA_CACHE),
        }

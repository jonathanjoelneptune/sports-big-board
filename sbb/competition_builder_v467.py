"""Sports Big Board v4.6.7 tournament realization + soccer Game Center patch.

Keeps the v4.6.6 Competition Builder contracts intact while adding:
- deterministic realized tournament participants/results from a sport-native
  provider when available (2026 FIFA World Cup -> ESPN fifa.world), written into
  existing canonical schedule slots without changing Sports Big Board event IDs;
- custom soccer competitions using the standard ESPN soccer Game Center shape
  so scoring plays, team stats, player sections/lineups and commentary populate.
"""
from __future__ import annotations

import re
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

from . import competition_builder as base
from .game_center import game_center_coverage, normalize_espn_summary

_INSTALLED = False
_LOCK = threading.RLock()
_GAME_CENTER_CACHE = {}
_ORIGINAL_WINDOW_PROMPT = base._window_prompt
_ORIGINAL_RECONCILE = base.reconcile_competition_results
_ORIGINAL_HANDLE_GET = base._handle_get

_NAME_ALIASES = {
    "usa": "united states",
    "u s a": "united states",
    "us": "united states",
    "united states of america": "united states",
    "korea republic": "south korea",
    "republic of korea": "south korea",
    "korea rep": "south korea",
    "ir iran": "iran",
    "cote d ivoire": "ivory coast",
    "côte d ivoire": "ivory coast",
    "cape verde": "cabo verde",
    "turkiye": "turkey",
    "türkiye": "turkey",
}


def _clean(value):
    return str(value or "").strip()


def _name_key(value):
    key = base._name_key(value)
    return _NAME_ALIASES.get(key, key)


def _team_name(event, side):
    return base._participant_name(event, side)


def _pair_key(event):
    return (_name_key(_team_name(event, "away")), _name_key(_team_name(event, "home")))


def _unordered_pair_key(event):
    return tuple(sorted(x for x in _pair_key(event) if x))


def _round_key(event):
    value = _clean((event or {}).get("round") or (event or {}).get("stage"))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _venue_key(event):
    value = _clean((event or {}).get("venue"))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _scheduled_clock(event):
    text = _clean((event or {}).get("scheduledAt") or (event or {}).get("date"))
    m = re.search(r"T(\d{2}):(\d{2})", text)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def _date_key(event):
    return _clean((event or {}).get("date") or (event or {}).get("gameDate"))[:10]


def _placeholder_event(event):
    return base._placeholder_participant(_team_name(event, "away")) or base._placeholder_participant(_team_name(event, "home"))


def _needs_realized_refresh(event, today=None):
    """Refresh unresolved future bracket slots too, but only replace them when official teams exist."""
    if _placeholder_event(event):
        return True
    date = _date_key(event)
    today = _clean(today or base._today())[:10]
    if date and date <= today:
        status = _clean((event or {}).get("status")).upper()
        if status not in {"POSTPONED", "CANCELLED", "CANCELED"}:
            return (event or {}).get("awayScore") in (None, "") or (event or {}).get("homeScore") in (None, "")
    return False


def _espn_slug_for_comp(comp):
    explicit = _clean((comp or {}).get("espnLeagueSlug") or (comp or {}).get("providerLeagueSlug"))
    if explicit:
        return explicit
    if _clean((comp or {}).get("sportId")) != "football":
        return ""
    name = _clean((comp or {}).get("name")).lower()
    short = _clean((comp or {}).get("shortName")).lower()
    cid = _clean((comp or {}).get("id")).lower()
    if "world cup" in name or "world cup" in short or cid in {"wc2026", "world_cup", "worldcup"}:
        return "fifa.world"
    return ""


def _window_prompt_v467(d, window_start, window_end, source_urls, expected):
    prompt = _ORIGINAL_WINDOW_PROMPT(d, window_start, window_end, source_urls, expected)
    today = base._today()
    return prompt + f"""

v4.6.7 PARTICIPANT REALIZATION POLICY (today is {today}):
- For every match dated today or earlier, return the ACTUAL teams/countries that played or are officially assigned to that match. Never return Winner Match X, Loser Match X, TBA, TBD, group-position placeholders, or bracket labels for a past match.
- For a future match, return actual teams as soon as both participants are officially determined. Keep bracket/TBA labels only while the participant is genuinely unresolved.
- If the competition has already completed, every returned match must use the realized participant names and official result/status.
- When the source exposes a stable provider match ID, place that provider ID in eventId. Do not fabricate an ID merely to fill the field.
"""


def _viewer_date(iso_value):
    text = _clean(iso_value)
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.date().isoformat()
        tz_name = os.environ.get("SBB_SCHEDULE_TIMEZONE") or "America/Los_Angeles"
        if ZoneInfo:
            return dt.astimezone(ZoneInfo(tz_name)).date().isoformat()
        return dt.astimezone(timezone.utc).date().isoformat()
    except Exception:
        return text[:10]


# os is deliberately imported after function declarations to keep the patch dependency-light.
import os


def _espn_fetch(server, url, timeout=10):
    fn = getattr(server, "_espn_fetch_json", None) or getattr(server, "fetch_json", None)
    if not callable(fn):
        raise RuntimeError("ESPN JSON transport is unavailable")
    return fn(url, timeout=timeout)


def _espn_team(row):
    team = (row or {}).get("team") or {}
    return _clean(team.get("displayName") or team.get("shortDisplayName") or team.get("name") or team.get("location") or team.get("abbreviation"))


def _espn_scoreboard_rows(server, comp, start_date, end_date):
    slug = _espn_slug_for_comp(comp)
    if not slug:
        return []
    start = re.sub(r"[^0-9]", "", _clean(start_date)[:10])
    end = re.sub(r"[^0-9]", "", _clean(end_date)[:10])
    if len(start) != 8 or len(end) != 8:
        return []
    api = _clean(getattr(server, "ESPN_SITE_API", "")) or "https://site.api.espn.com/apis/site/v2/sports"
    dates = start if start == end else f"{start}-{end}"
    url = f"{api.rstrip('/')}/soccer/{slug}/scoreboard?dates={dates}&limit=250"
    payload = _espn_fetch(server, url, timeout=12)
    out = []
    for raw in (payload or {}).get("events") or []:
        comps = raw.get("competitions") or []
        game = (comps[0] if comps else {}) or {}
        sides = {}
        for row in game.get("competitors") or []:
            side = _clean(row.get("homeAway")).lower()
            if side in {"away", "home"}:
                sides[side] = row
        away_row = sides.get("away") or {}
        home_row = sides.get("home") or {}
        away = _espn_team(away_row)
        home = _espn_team(home_row)
        if not away or not home or base._placeholder_participant(away) or base._placeholder_participant(home):
            continue
        status = game.get("status") or raw.get("status") or {}
        stype = status.get("type") or {}
        completed = bool(stype.get("completed")) or _clean(stype.get("state")).lower() == "post"
        detail = _clean(stype.get("shortDetail") or stype.get("detail") or stype.get("description"))
        if not detail:
            detail = "FINAL" if completed else (_clean(stype.get("state")) or "SCHEDULED")
        venue = _clean((game.get("venue") or {}).get("fullName") or (game.get("venue") or {}).get("name"))
        season = raw.get("season") or game.get("season") or {}
        stage = _clean((season.get("type") or {}).get("name") if isinstance(season.get("type"), dict) else season.get("type"))
        links = raw.get("links") or game.get("links") or []
        source_url = next((_clean(x.get("href")) for x in links if isinstance(x, dict) and x.get("href")), "")
        provider_id = _clean(raw.get("id") or game.get("id"))
        scheduled = _clean(raw.get("date") or game.get("date"))
        out.append({
            "eventId": provider_id,
            "providerEventId": provider_id,
            "espnEventId": provider_id,
            "date": _viewer_date(scheduled),
            "scheduledAt": scheduled,
            "away": away,
            "home": home,
            "awayScore": away_row.get("score"),
            "homeScore": home_row.get("score"),
            "status": detail.upper() if completed else detail,
            "round": stage,
            "stage": stage,
            "venue": venue,
            "broadcast": "",
            "sourceUrl": source_url or url,
            "resultProvider": "ESPN",
        })
    return out


def _slot_similarity(old, realized):
    if _date_key(old) != _date_key(realized):
        return -1
    score = 0
    old_pair = _pair_key(old)
    new_pair = _pair_key(realized)
    if old_pair == new_pair and all(old_pair):
        score += 120
    elif _unordered_pair_key(old) == _unordered_pair_key(realized) and len(_unordered_pair_key(old)) == 2:
        score += 90
    else:
        for name in old_pair:
            if name and name in new_pair and not base._placeholder_participant(name):
                score += 20
    old_sched = _clean((old or {}).get("scheduledAt"))
    new_sched = _clean((realized or {}).get("scheduledAt"))
    if old_sched and new_sched and old_sched == new_sched:
        score += 80
    old_clock = _scheduled_clock(old)
    new_clock = _scheduled_clock(realized)
    if old_clock and new_clock and old_clock == new_clock:
        score += 45
    old_venue = _venue_key(old)
    new_venue = _venue_key(realized)
    if old_venue and new_venue and old_venue == new_venue:
        score += 30
    old_round = _round_key(old)
    new_round = _round_key(realized)
    if old_round and new_round and old_round == new_round:
        score += 18
    return score


def _match_realized_rows(events, realized_rows, target_ids=None):
    """Map provider/result rows onto stable canonical schedule slots."""
    targets = [e for e in events if target_ids is None or _clean(e.get("eventId")) in target_ids]
    remaining = {_clean(e.get("eventId")): e for e in targets if _clean(e.get("eventId"))}
    mapping = {}

    for row in realized_rows:
        rid = _clean(row.get("eventId"))
        if rid and rid in remaining:
            mapping[rid] = row
            remaining.pop(rid, None)

    unused_rows = [r for r in realized_rows if r not in mapping.values()]
    candidates = []
    for eid, old in remaining.items():
        for row in unused_rows:
            value = _slot_similarity(old, row)
            if value >= 0:
                candidates.append((value, eid, row))
    candidates.sort(key=lambda x: x[0], reverse=True)
    used = set()
    for value, eid, row in candidates:
        marker = id(row)
        if eid not in remaining or marker in used:
            continue
        if value < 30:
            continue
        mapping[eid] = row
        remaining.pop(eid, None)
        used.add(marker)

    by_date_old = {}
    for eid, old in remaining.items():
        by_date_old.setdefault(_date_key(old), []).append((eid, old))
    by_date_new = {}
    for row in unused_rows:
        if id(row) in used:
            continue
        by_date_new.setdefault(_date_key(row), []).append(row)
    for date, old_rows in by_date_old.items():
        new_rows = by_date_new.get(date) or []
        if not date or len(old_rows) != len(new_rows) or not old_rows:
            continue
        old_rows = sorted(old_rows, key=lambda x: (_scheduled_clock(x[1]), _venue_key(x[1]), _round_key(x[1]), x[0]))
        new_rows = sorted(new_rows, key=lambda x: (_scheduled_clock(x), _venue_key(x), _round_key(x), _clean(x.get("eventId"))))
        for (eid, _old), row in zip(old_rows, new_rows):
            if eid in remaining:
                mapping[eid] = row
                remaining.pop(eid, None)
    return mapping


def _merge_realized_results(comp, realized_rows, target_ids=None):
    events = list((comp or {}).get("events") or [])
    mapping = _match_realized_rows(events, realized_rows, target_ids=target_ids)
    updated = []
    changed = 0
    matched = []
    for idx, old in enumerate(events):
        eid = _clean(old.get("eventId"))
        row = mapping.get(eid)
        if not row:
            updated.append(old)
            continue
        provider_id = _clean(row.get("espnEventId") or row.get("providerEventId") or row.get("eventId"))
        merged = {
            **old,
            **row,
            "awayTeam": row.get("away"),
            "homeTeam": row.get("home"),
            "id": eid,
            "eventId": eid,
            "matchId": eid,
            "competitionId": comp.get("id"),
            "competitionName": comp.get("name"),
            "participantResolution": "REALIZED",
            "participantsResolvedAt": time.time(),
        }
        if provider_id:
            merged["providerEventId"] = provider_id
            if _espn_slug_for_comp(comp):
                merged["espnEventId"] = provider_id
        normalized = base.normalize_event(comp, merged, idx)
        normalized["id"] = eid
        normalized["eventId"] = eid
        normalized["matchId"] = eid
        before = (_pair_key(old), old.get("awayScore"), old.get("homeScore"), _clean(old.get("status")))
        after = (_pair_key(normalized), normalized.get("awayScore"), normalized.get("homeScore"), _clean(normalized.get("status")))
        if before != after or _clean(old.get("espnEventId")) != _clean(normalized.get("espnEventId")):
            changed += 1
        matched.append(eid)
        updated.append(normalized)
    return updated, changed, matched


def reconcile_competition_results(server, comp, force=False):
    """Deterministic realized-result reconciliation with v4.6.6 web fallback."""
    if not comp:
        return {"attempted": False, "updated": 0, "targets": 0, "remaining": 0, "errors": ["competition missing"]}
    slug = _espn_slug_for_comp(comp)
    targets = [dict(ev) for ev in (comp.get("events") or []) if _needs_realized_refresh(ev)]
    if not targets:
        return {"attempted": False, "updated": 0, "targets": 0, "remaining": 0, "errors": []}

    if not slug or not callable(getattr(server, "_espn_fetch_json", None) or getattr(server, "fetch_json", None)):
        return _ORIGINAL_RECONCILE(server, comp, force=force)

    cid = _clean(comp.get("id")).upper()
    now = time.time()
    period = max(900, min(21600, int(comp.get("refreshMinutes") or 30) * 60))
    if not force and now - float(base._RESULT_RECONCILE_AT.get(cid) or 0) < period:
        return {"attempted": False, "updated": 0, "targets": len(targets), "remaining": len(targets), "errors": []}
    base._RESULT_RECONCILE_AT[cid] = now

    errors = []
    dates = [_date_key(x) for x in targets if _date_key(x)]
    realized = []
    try:
        realized = _espn_scoreboard_rows(server, comp, min(dates), max(dates)) if dates else []
    except Exception as exc:
        errors.append(f"ESPN {slug}: {type(exc).__name__}: {exc}")

    if not realized:
        fallback = _ORIGINAL_RECONCILE(server, comp, force=True)
        fallback["provider"] = "WEB_FALLBACK"
        fallback["errors"] = errors + list(fallback.get("errors") or [])
        return fallback

    target_ids = {_clean(x.get("eventId")) for x in targets}
    updated, changed, matched = _merge_realized_results(comp, realized, target_ids=target_ids)
    persisted = base._persist_event_reconciliation(server, comp, updated) if matched else comp

    repaired = 0
    if matched:
        current = persisted or {**comp, "events": updated}
        matched_set = set(matched)
        for event in current.get("events") or []:
            if _clean(event.get("eventId")) not in matched_set:
                continue
            try:
                repaired += int((base._repair_event_media(server, current, event, force=True) or {}).get("assigned") or 0)
            except Exception:
                pass

    remaining_events = (persisted or {}).get("events", updated)
    remaining = sum(1 for ev in remaining_events if _needs_realized_refresh(ev))
    source_urls = sorted({_clean(x.get("sourceUrl")) for x in realized if _clean(x.get("sourceUrl"))})
    return {
        "attempted": True,
        "updated": changed,
        "targets": len(targets),
        "matched": len(matched),
        "remaining": remaining,
        "mediaRepaired": repaired,
        "provider": "ESPN",
        "providerLeague": slug,
        "errors": errors[-12:],
        "sourceUrls": source_urls[:12],
    }


def _team_for_game_center(stored, provider):
    stored = dict(stored or {})
    provider = dict(provider or {})
    merged = {**stored, **provider}
    if stored.get("logo") or stored.get("logoUrl"):
        merged["logo"] = stored.get("logo") or stored.get("logoUrl")
    name = _clean(provider.get("name") or provider.get("displayName") or stored.get("name") or stored.get("displayName"))
    if name:
        merged["name"] = name
        merged["displayName"] = name
    return merged


def _resolve_espn_event_id(server, comp, event):
    direct = _clean(event.get("espnEventId") or event.get("providerEventId"))
    if direct:
        return direct
    slug = _espn_slug_for_comp(comp)
    date = _date_key(event)
    if not slug or not date:
        return ""
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
        rows = _espn_scoreboard_rows(server, comp, (d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat())
    except Exception:
        return ""
    exact = _pair_key(event)
    unordered = _unordered_pair_key(event)
    for row in rows:
        if _pair_key(row) == exact and all(exact):
            return _clean(row.get("espnEventId") or row.get("providerEventId") or row.get("eventId"))
    for row in rows:
        if unordered and _unordered_pair_key(row) == unordered:
            return _clean(row.get("espnEventId") or row.get("providerEventId") or row.get("eventId"))
    return ""


def _canonicalize_soccer_game_center(comp, stored_event, provider_data, espn_id):
    data = deepcopy(provider_data or {})
    canonical_id = _clean(stored_event.get("eventId"))
    cid = _clean(comp.get("id")).upper()
    stored_event = base._decorate_event_artwork(comp, stored_event)
    pevent = data.get("event") or {}
    pboard = data.get("scoreboard") or {}
    stored_away = stored_event.get("awayTeam") or stored_event.get("away") or {}
    stored_home = stored_event.get("homeTeam") or stored_event.get("home") or {}
    provider_away = pevent.get("awayTeam") or ((pboard.get("away") or {}).get("team") or {})
    provider_home = pevent.get("homeTeam") or ((pboard.get("home") or {}).get("team") or {})
    away = _team_for_game_center(stored_away, provider_away)
    home = _team_for_game_center(stored_home, provider_home)

    event = {
        **stored_event,
        **pevent,
        "id": canonical_id,
        "eventId": canonical_id,
        "matchId": canonical_id,
        "competitionId": cid,
        "competitionName": comp.get("name"),
        "sportId": "football",
        "eventKind": "match",
        "date": _date_key(stored_event),
        "gameDate": _date_key(stored_event),
        "awayTeam": away,
        "homeTeam": home,
        "away": away,
        "home": home,
        "espnEventId": espn_id,
        "providerEventId": espn_id,
    }
    board = dict(pboard)
    board["away"] = {**(pboard.get("away") or {}), "team": away}
    board["home"] = {**(pboard.get("home") or {}), "team": home}
    data.update({
        "competitionId": cid,
        "competitionName": comp.get("name"),
        "eventId": canonical_id,
        "providerEventId": espn_id,
        "espnEventId": espn_id,
        "event": event,
        "scoreboard": board,
        "source": f"ESPN {_clean(comp.get('name'))} Game Summary",
    })

    shadow = deepcopy(data)
    shadow["competitionId"] = "EPL"
    shadow.setdefault("event", {})["competitionId"] = "EPL"
    coverage = game_center_coverage(shadow)
    data["coverage"] = coverage
    data["partial"] = not bool(coverage.get("complete"))
    data["quality"] = {
        "level": "rich" if coverage.get("complete") else ("partial" if coverage.get("identity") else "shell"),
        "score": coverage.get("richness", 0),
        **coverage,
    }
    return data


def soccer_game_center(server, comp, event):
    slug = _espn_slug_for_comp(comp)
    if not slug:
        raise NotImplementedError("No soccer provider mapping configured")
    key = f"{_clean(comp.get('id')).upper()}:{_clean(event.get('eventId'))}"
    now = time.time()
    with _LOCK:
        cached = _GAME_CENTER_CACHE.get(key)
    if cached:
        status = _clean((cached.get("data") or {}).get("event", {}).get("status")).lower()
        ttl = 15 if re.search(r"live|progress|half|period", status) else (300 if re.search(r"final|finished|complete", status) else 60)
        if now - float(cached.get("savedAt") or 0) < ttl:
            return deepcopy(cached.get("data") or {})

    espn_id = _resolve_espn_event_id(server, comp, event)
    if not espn_id:
        raise RuntimeError("ESPN event could not be resolved from the tournament matchup")
    api = _clean(getattr(server, "ESPN_SITE_API", "")) or "https://site.api.espn.com/apis/site/v2/sports"
    payload = _espn_fetch(server, f"{api.rstrip('/')}/soccer/{slug}/summary?event={espn_id}", timeout=10)
    normalized = normalize_espn_summary(payload, "EPL", espn_id)
    data = _canonicalize_soccer_game_center(comp, event, normalized, espn_id)
    with _LOCK:
        _GAME_CENTER_CACHE[key] = {"savedAt": now, "data": deepcopy(data)}
    return data


def _handle_get_v467(server, handler, parsed):
    match = re.fullmatch(r"/api/events/([^/]+)/([^/]+)/game-center", parsed.path)
    if match:
        cid = unquote(match.group(1)).upper()
        eid = unquote(match.group(2))
        comp = base._find(cid)
        if comp and _espn_slug_for_comp(comp):
            event = next((x for x in comp.get("events") or [] if _clean(x.get("eventId")) == eid), None)
            if not event:
                return base._send(server, handler, {"ok": False, "error": "CUSTOM_EVENT_NOT_FOUND"}, 404)
            event = base._decorate_event_artwork(comp, event)
            try:
                data = soccer_game_center(server, comp, event)
                return base._send(server, handler, {
                    "ok": True,
                    "data": data,
                    "resolvedEventId": eid,
                    "providerEventId": data.get("providerEventId"),
                    "cache": "ESPN-SOCCER",
                }, 200)
            except Exception as exc:
                fallback = base.generic_game_center(comp, event)
                fallback["providerError"] = f"{type(exc).__name__}: {exc}"
                fallback["source"] = "competition-builder fallback after ESPN soccer Game Center error"
                return base._send(server, handler, {
                    "ok": True,
                    "data": fallback,
                    "resolvedEventId": eid,
                    "cache": "CUSTOM-COMPETITION-FALLBACK",
                }, 200)
    return _ORIGINAL_HANDLE_GET(server, handler, parsed)


def _refresh_active_v467(server):
    """Retain v4.6.6 work while resolving known future bracket slots early."""
    while True:
        try:
            now = time.time()
            for comp in base._load():
                if base.lifecycle(comp) != "ACTIVE" or not comp.get("enabled", True) or not comp.get("autoRefresh") or comp.get("scheduleMode") != "AUTO_DISCOVER":
                    continue
                last = float(comp.get("lastAutoRefreshAt") or 0)
                period = max(5, int(comp.get("refreshMinutes") or 30)) * 60
                if now - last < period:
                    continue
                try:
                    preview = base.discover_schedule(server, comp)
                    raw = dict(comp)
                    raw["lastAutoRefreshAt"] = time.time()
                    raw["lastDiscoverySources"] = preview.get("sourceUrls") or []
                    base.save_competition(raw, preview.get("events") or [], server)
                except Exception:
                    rows = base._load()
                    for x in rows:
                        if x.get("id") == comp.get("id"):
                            x["lastAutoRefreshAt"] = time.time()
                            x["lastRefreshError"] = "auto refresh failed"
                            x["updatedAt"] = time.time()
                    base._save(rows)
        except Exception:
            pass
        try:
            for comp in base._load():
                if not comp.get("enabled", True) or not comp.get("backgroundDiscovery", True):
                    continue
                if not any(_needs_realized_refresh(ev) for ev in comp.get("events") or []):
                    continue
                report = reconcile_competition_results(server, comp, force=False)
                if report.get("attempted"):
                    break
        except Exception:
            pass
        try:
            base._run_generic_gap_once(server)
        except Exception:
            pass
        time.sleep(60)


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    base._window_prompt = _window_prompt_v467
    base.reconcile_competition_results = reconcile_competition_results
    base._handle_get = _handle_get_v467
    base._refresh_active = _refresh_active_v467

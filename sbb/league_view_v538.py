"""Sports Big Board v5.3.9 — cached League View read model.

League View is intentionally read-only. It never owns scores, playback, selected-event
identity, or the historical catalog. It projects public league standings, playoff seed
context, rankings, and recent/today event summaries into a compact right-drawer model.
Daily/multi-game recap playback can therefore show league context instead of a stale
single-game Game Center.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

VERSION = "5.3.9-league-view-1"
_STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
_CACHE_PATH = _STATE_DIR / "league-view-v538.json"
_TTL_SECONDS = 10 * 60
_LOCK = threading.RLock()
_CACHE = {}
_INSTALLED = False

# ESPN competition slugs are enrichment sources only. Unknown/special competitions
# fail soft so the browser can still show its local event-context fallback.
ESPN_COMPETITIONS = {
    "MLB": ("baseball", "mlb", "MLB"),
    "NFL": ("football", "nfl", "NFL"),
    "NBA": ("basketball", "nba", "NBA"),
    "NHL": ("hockey", "nhl", "NHL"),
    "NCAAF": ("football", "college-football", "NCAAF"),
    "EPL": ("soccer", "eng.1", "PREMIER LEAGUE"),
    "MLS": ("soccer", "usa.1", "MLS"),
    "WC2026": ("soccer", "fifa.world", "2026 WORLD CUP"),
    "WORLD-CUP-2026": ("soccer", "fifa.world", "2026 WORLD CUP"),
    "FIFA-WORLD-CUP-2026": ("soccer", "fifa.world", "2026 WORLD CUP"),
    "LLWS2026": ("baseball", "little-league-world-series", "LITTLE LEAGUE WORLD SERIES"),
    # ESPN tennis scoreboards do not expose a conventional standings table. The
    # scoreboard fetch remains useful for event/round context and fails soft.
    "USOPEN-2026": ("tennis", "atp", "US OPEN"),
}

CORE_LEAGUES = {"MLB", "NFL", "NBA", "NHL", "NCAAF", "EPL", "MLS"}


def _clean(value):
    return str(value or "").strip()


def _norm(value):
    return re.sub(r"[^a-z0-9]+", "-", _clean(value).lower()).strip("-")


def _load_cache():
    global _CACHE
    try:
        payload = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            _CACHE = payload
    except Exception:
        _CACHE = {}


def _persist_cache():
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(_CACHE, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
        os.replace(tmp, _CACHE_PATH)
    except Exception:
        pass


def _http_json(url, timeout=7.0):
    req = Request(url, headers={"User-Agent": "SportsBigBoard/5.3.9", "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _stat_value(stats, names):
    wanted = {_norm(x) for x in names}
    for row in stats or []:
        if not isinstance(row, dict):
            continue
        labels = {_norm(row.get("name")), _norm(row.get("abbreviation")), _norm(row.get("displayName")), _norm(row.get("shortDisplayName"))}
        if labels & wanted:
            value = row.get("displayValue")
            if value in (None, ""):
                value = row.get("value")
            return _clean(value)
    return ""


def _team_logo(team):
    for row in team.get("logos") or []:
        if isinstance(row, dict) and _clean(row.get("href")):
            return _clean(row.get("href"))
    logo = team.get("logo")
    if isinstance(logo, dict):
        logo = logo.get("href") or logo.get("url")
    return _clean(logo)


def _standing_entry(entry):
    team = entry.get("team") if isinstance(entry.get("team"), dict) else {}
    stats = entry.get("stats") if isinstance(entry.get("stats"), list) else []
    wins = _stat_value(stats, ["wins", "w"])
    losses = _stat_value(stats, ["losses", "l"])
    ties = _stat_value(stats, ["ties", "t"])
    pct = _stat_value(stats, ["winpercent", "win percentage", "pct"])
    points = _stat_value(stats, ["points", "pts"])
    games_behind = _stat_value(stats, ["gamesbehind", "games behind", "gb"])
    seed = _stat_value(stats, ["playoffseed", "playoff seed", "seed"])
    rank = _stat_value(stats, ["rank", "overallrank", "overall rank"])
    record = _stat_value(stats, ["overall", "record"])
    if not record and (wins or losses):
        record = "-".join(x for x in (wins, losses, ties) if x != "")
    return {
        "id": _clean(team.get("id") or team.get("uid")),
        "name": _clean(team.get("displayName") or team.get("shortDisplayName") or team.get("name")),
        "abbreviation": _clean(team.get("abbreviation") or team.get("shortName")),
        "logo": _team_logo(team),
        "record": record,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "pct": pct,
        "points": points,
        "gamesBehind": games_behind,
        "seed": seed,
        "rank": rank,
        "streak": _stat_value(stats, ["streak"]),
        "differential": _stat_value(stats, ["pointdifferential", "run differential", "goaldifferential", "differential"]),
    }


def _group_name(node, fallback="STANDINGS"):
    return _clean(node.get("name") or node.get("shortName") or node.get("abbreviation") or fallback).upper()


def _parse_standings(payload):
    groups = []
    seen = set()

    def walk(node, parent=""):
        if not isinstance(node, dict):
            return
        name = _group_name(node, parent or "STANDINGS")
        standings = node.get("standings") if isinstance(node.get("standings"), dict) else {}
        entries = standings.get("entries") if isinstance(standings.get("entries"), list) else []
        if entries:
            rows = [_standing_entry(x) for x in entries if isinstance(x, dict)]
            rows = [x for x in rows if x.get("name")]
            signature = (name, tuple(x.get("id") or x.get("name") for x in rows))
            if rows and signature not in seen:
                seen.add(signature)
                groups.append({"name": name, "entries": rows})
        for child in node.get("children") or []:
            walk(child, name)

    if isinstance(payload, dict):
        walk(payload)
        for child in payload.get("children") or []:
            walk(child)
    return groups[:20]


def _seed_number(value):
    try:
        return int(re.sub(r"[^0-9]", "", _clean(value)) or "999")
    except Exception:
        return 999


def _playoff_race(groups):
    # Entries can occur in both conference and division nodes. Deduplicate by team
    # and keep the richest row, then sort any published playoff seed to the front.
    teams = {}
    for group in groups:
        for row in group.get("entries") or []:
            key = row.get("id") or _norm(row.get("name"))
            if not key:
                continue
            prior = teams.get(key)
            if prior is None or (row.get("seed") and not prior.get("seed")):
                teams[key] = dict(row)
    seeded = [row for row in teams.values() if row.get("seed")]
    seeded.sort(key=lambda row: (_seed_number(row.get("seed")), _norm(row.get("name"))))
    return seeded[:16]


def _competition_team(competitor):
    team = competitor.get("team") if isinstance(competitor.get("team"), dict) else {}
    score = competitor.get("score")
    if isinstance(score, dict):
        score = score.get("displayValue") or score.get("value")
    return {
        "name": _clean(team.get("displayName") or team.get("shortDisplayName") or team.get("name")),
        "abbreviation": _clean(team.get("abbreviation")),
        "logo": _team_logo(team),
        "score": _clean(score),
        "winner": bool(competitor.get("winner")),
        "homeAway": _clean(competitor.get("homeAway")),
    }


def _parse_scoreboard(payload):
    out = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        comp = (event.get("competitions") or [{}])[0]
        if not isinstance(comp, dict):
            comp = {}
        competitors = [_competition_team(x) for x in comp.get("competitors") or [] if isinstance(x, dict)]
        home = next((x for x in competitors if x.get("homeAway") == "home"), competitors[-1] if competitors else {})
        away = next((x for x in competitors if x.get("homeAway") == "away"), competitors[0] if competitors else {})
        status = event.get("status") if isinstance(event.get("status"), dict) else {}
        stype = status.get("type") if isinstance(status.get("type"), dict) else {}
        season = event.get("season") if isinstance(event.get("season"), dict) else {}
        week = event.get("week") if isinstance(event.get("week"), dict) else {}
        round_value = comp.get("round") or season.get("type") or week.get("text") or week.get("number") or ""
        series = comp.get("series") if isinstance(comp.get("series"), dict) else {}
        series_value = series.get("summary") or series.get("title") or series.get("description") or comp.get("seriesSummary") or ""
        out.append({
            "id": _clean(event.get("id")),
            "date": _clean(event.get("date")),
            "name": _clean(event.get("shortName") or event.get("name")),
            "status": _clean(stype.get("shortDetail") or stype.get("detail") or stype.get("description")),
            "state": _clean(stype.get("state")),
            "away": away,
            "home": home,
            "round": _clean(round_value),
            "series": _clean(series_value),
            "venue": _clean((comp.get("venue") or {}).get("fullName") if isinstance(comp.get("venue"), dict) else ""),
        })
    return out[:20]


def _fetch_rankings(sport, competition):
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{competition}/rankings"
    try:
        payload = _http_json(url)
    except Exception:
        return []
    rankings = payload.get("rankings") or []
    if not rankings:
        return []
    poll = next((x for x in rankings if "AP" in _clean(x.get("name")).upper()), rankings[0])
    out = []
    for row in poll.get("ranks") or []:
        team = row.get("team") if isinstance(row.get("team"), dict) else {}
        out.append({
            "rank": _clean(row.get("current") or row.get("rank")),
            "previous": _clean(row.get("previous")),
            "name": _clean(team.get("displayName") or team.get("name")),
            "abbreviation": _clean(team.get("abbreviation")),
            "logo": _team_logo(team),
            "record": _clean(row.get("recordSummary") or row.get("record")),
            "points": _clean(row.get("points")),
        })
    return out[:25]


def _fetch_source(league):
    spec = ESPN_COMPETITIONS.get(league)
    if not spec:
        return {"standings": [], "games": [], "rankings": [], "sourceErrors": ["No public League View adapter for this competition yet."]}
    sport, competition, _ = spec
    standings_url = f"https://site.api.espn.com/apis/v2/sports/{sport}/{competition}/standings?region=us&lang=en&contentorigin=espn&type=0&level=2"
    scoreboard_url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{competition}/scoreboard?limit=100"
    errors = []
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="sbb-league-view") as pool:
        f_standings = pool.submit(_http_json, standings_url)
        f_scoreboard = pool.submit(_http_json, scoreboard_url)
        f_rankings = pool.submit(_fetch_rankings, sport, competition) if league == "NCAAF" else None
        try:
            standings_payload = f_standings.result()
            standings = _parse_standings(standings_payload)
        except Exception as exc:
            standings = []
            errors.append(f"standings: {type(exc).__name__}")
        try:
            scoreboard_payload = f_scoreboard.result()
            games = _parse_scoreboard(scoreboard_payload)
        except Exception as exc:
            games = []
            errors.append(f"scoreboard: {type(exc).__name__}")
        try:
            rankings = f_rankings.result() if f_rankings else []
        except Exception as exc:
            rankings = []
            errors.append(f"rankings: {type(exc).__name__}")
    return {"standings": standings, "games": games, "rankings": rankings, "sourceErrors": errors}


def _payload(league, force=False):
    league = _clean(league).upper()
    now = time.time()
    with _LOCK:
        cached = _CACHE.get(league)
        if not force and isinstance(cached, dict) and now - float(cached.get("savedAt") or 0) < _TTL_SECONDS:
            return cached
    spec = ESPN_COMPETITIONS.get(league)
    label = spec[2] if spec else league.replace("-", " ")
    source = _fetch_source(league)
    standings = source.get("standings") or []
    result = {
        "ok": True,
        "version": VERSION,
        "league": league,
        "label": label,
        "specialEvent": league not in CORE_LEAGUES,
        "savedAt": now,
        "standings": standings,
        "playoffRace": _playoff_race(standings),
        "rankings": source.get("rankings") or [],
        "games": source.get("games") or [],
        "source": "ESPN_PUBLIC_ENRICHMENT",
        "sourceErrors": source.get("sourceErrors") or [],
    }
    with _LOCK:
        _CACHE[league] = result
        _persist_cache()
    return result


def _install_into_server():
    deadline = time.time() + 120
    server = None
    while time.time() < deadline:
        candidate = sys.modules.get("__main__")
        if candidate and hasattr(candidate, "Handler") and hasattr(candidate, "send_json"):
            server = candidate
            break
        time.sleep(.2)
    if not server:
        return
    _load_cache()
    Handler = server.Handler
    if getattr(Handler, "__sbbLeagueViewV538", False):
        return
    old_get = Handler.do_GET

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/league-view":
            qs = parse_qs(parsed.query)
            league = _clean((qs.get("league") or [""])[0]).upper()
            force = _clean((qs.get("force") or [""])[0]).lower() in {"1", "true", "yes"}
            if not league:
                return server.send_json(self, {"ok": False, "error": "league is required"}, 400)
            try:
                payload = _payload(league, force=force)
            except Exception as exc:
                payload = {"ok": False, "version": VERSION, "league": league, "error": f"{type(exc).__name__}: {exc}"}
            return server.send_json(self, payload, 200 if payload.get("ok") else 502, {"Cache-Control": "private, max-age=120"})
        return old_get(self)

    Handler.do_GET = do_GET
    Handler.__sbbLeagueViewV538 = True


def install():
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return False
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-league-view-v538").start()
    return True


__all__ = ["VERSION", "install"]

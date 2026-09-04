"""Sports Big Board v5.4.9 — cached League View read model.

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

VERSION = "5.4.9-league-view-4"
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


# Provider conference tables do not always include division child nodes. Keep a
# small canonical division roster so League View can still project the familiar
# MLB/NFL/NHL standings structure from a conference-level table. The mapping only
# organizes provider records; it never supplies scores or standings values.
_STATIC_DIVISIONS = {
    "MLB": {
        "AL": [("EAST", {"BAL","BOS","NYY","TB","TOR"}), ("CENTRAL", {"CWS","CLE","DET","KC","MIN"}), ("WEST", {"HOU","LAA","ATH","OAK","SEA","TEX"})],
        "NL": [("EAST", {"ATL","MIA","NYM","PHI","WSH"}), ("CENTRAL", {"CHC","CIN","MIL","PIT","STL"}), ("WEST", {"ARI","COL","LAD","SD","SF"})],
    },
    "NFL": {
        "AFC": [("EAST", {"BUF","MIA","NE","NYJ"}), ("NORTH", {"BAL","CIN","CLE","PIT"}), ("SOUTH", {"HOU","IND","JAX","TEN"}), ("WEST", {"DEN","KC","LV","LAC"})],
        "NFC": [("EAST", {"DAL","NYG","PHI","WSH"}), ("NORTH", {"CHI","DET","GB","MIN"}), ("SOUTH", {"ATL","CAR","NO","TB"}), ("WEST", {"ARI","LAR","SF","SEA"})],
    },
    "NHL": {
        "EAST": [("ATLANTIC", {"BOS","BUF","DET","FLA","MTL","OTT","TB","TOR"}), ("METROPOLITAN", {"CAR","CBJ","NJ","NYI","NYR","PHI","PIT","WSH"})],
        "WEST": [("CENTRAL", {"CHI","COL","DAL","MIN","NSH","STL","UTA","WPG"}), ("PACIFIC", {"ANA","CGY","EDM","LAK","SJS","SEA","VAN","VGK"})],
    },
}

def _abbr_key(row):
    return _clean(row.get("abbreviation")).upper().replace(".", "")

def _synthesize_divisions(league, bucket):
    if bucket.get("divisions") or not bucket.get("standings"):
        return
    definitions = (_STATIC_DIVISIONS.get(league) or {}).get(bucket.get("key")) or []
    if not definitions:
        return
    standings = [dict(x) for x in bucket.get("standings") or []]
    for name, abbreviations in definitions:
        rows = [row for row in standings if _abbr_key(row) in abbreviations]
        if rows:
            bucket["divisions"].append({"name": name, "entries": rows, "synthetic": True})


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
    req = Request(url, headers={"User-Agent": "SportsBigBoard/5.4.9", "Accept": "application/json"})
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
        "gamesPlayed": _stat_value(stats, ["gamesplayed", "games played", "gp", "mp"]),
        "conferenceRecord": _stat_value(stats, ["conference", "conference record", "confrecord", "conf"]),
        "seed": seed,
        "rank": rank,
        "streak": _stat_value(stats, ["streak"]),
        "differential": _stat_value(stats, ["pointdifferential", "run differential", "goaldifferential", "goal differential", "differential", "diff"]),
        "form": [],
    }


def _group_name(node, fallback="STANDINGS"):
    return _clean(node.get("name") or node.get("shortName") or node.get("abbreviation") or fallback).upper()


def _parse_standings(payload):
    groups = []
    seen = set()

    def walk(node, parent="", path=()):
        if not isinstance(node, dict):
            return
        name = _group_name(node, parent or "STANDINGS")
        current_path = tuple(x for x in (*path, name) if x)
        standings = node.get("standings") if isinstance(node.get("standings"), dict) else {}
        entries = standings.get("entries") if isinstance(standings.get("entries"), list) else []
        if entries:
            rows = [_standing_entry(x) for x in entries if isinstance(x, dict)]
            rows = [x for x in rows if x.get("name")]
            signature = (name, tuple(x.get("id") or x.get("name") for x in rows))
            if rows and signature not in seen:
                seen.add(signature)
                groups.append({"name": name, "parent": parent, "path": list(current_path), "entries": rows})
        for child in node.get("children") or []:
            walk(child, name, current_path)

    if isinstance(payload, dict):
        walk(payload)
    return groups[:28]


def _number(value, default=None):
    raw = _clean(value).replace(",", "")
    if not raw:
        return default
    try:
        return float(re.sub(r"[^0-9+\-.]", "", raw))
    except Exception:
        return default


def _conference_key(league, group):
    text = " ".join([_clean(group.get("parent")), *[str(x) for x in group.get("path") or []], _clean(group.get("name"))]).upper()
    if league == "MLB":
        if "AMERICAN LEAGUE" in text or re.search(r"\bAL\b", text): return "AL"
        if "NATIONAL LEAGUE" in text or re.search(r"\bNL\b", text): return "NL"
    if league == "NFL":
        if re.search(r"\bAFC\b|AMERICAN FOOTBALL CONFERENCE", text): return "AFC"
        if re.search(r"\bNFC\b|NATIONAL FOOTBALL CONFERENCE", text): return "NFC"
    if league in {"NBA", "NHL"}:
        if "EASTERN CONFERENCE" in text or re.search(r"\bEAST\b", text): return "EAST"
        if "WESTERN CONFERENCE" in text or re.search(r"\bWEST\b", text): return "WEST"
    return ""


def _division_name(league, group):
    name = _clean(group.get("name")).upper()
    text = " ".join([_clean(group.get("parent")), name]).upper()
    if league == "MLB":
        for token in ("EAST", "CENTRAL", "WEST"):
            if token in name and ("LEAGUE" not in name or len(name.split()) > 2): return token
    if league == "NFL":
        for token in ("EAST", "NORTH", "SOUTH", "WEST"):
            if token in name: return token
    if league == "NHL":
        for token in ("ATLANTIC", "METROPOLITAN", "CENTRAL", "PACIFIC"):
            if token in name: return token
    return ""


def _format_relative(value):
    if value is None:
        return "—"
    if abs(value) < 0.05:
        return "—"
    amount = round(abs(float(value)) * 2) / 2
    text = str(int(amount)) if float(amount).is_integer() else f"{amount:.1f}"
    return f"+{text}" if value < 0 else text


def _wildcard_relative(rows, qualifying_slots=3):
    """Project GB against the last current Wild Card position, not division lead.

    ESPN's `gamesBehind` is normally relative to a division/conference leader.
    Subtracting the cutoff team's leader-relative GB converts every row to the
    Wild Card cut line. When GB is absent, use the standard W/L/T games-back
    equation. Negative values mean the club is that many games *above* the cut
    and are displayed with a plus sign; the cutoff itself is an em dash.
    """
    rows=[dict(row) for row in (rows or [])]
    if not rows:
        return rows
    cut_index=min(max(0,int(qualifying_slots)-1),len(rows)-1)
    cutoff=rows[cut_index]
    cutoff_gb=_number(cutoff.get("gamesBehind"),None)
    cw=_number(cutoff.get("wins"),None);cl=_number(cutoff.get("losses"),None);ct=_number(cutoff.get("ties"),0) or 0
    for row in rows:
        delta=None;gb=_number(row.get("gamesBehind"),None)
        if gb is not None and cutoff_gb is not None:
            delta=gb-cutoff_gb
        else:
            w=_number(row.get("wins"),None);l=_number(row.get("losses"),None);t=_number(row.get("ties"),0) or 0
            if None not in (w,l,cw,cl):
                # Same formula as conventional games behind, with each tie worth
                # half a win for leagues that publish ties.
                delta=((cw+ct/2)-(w+t/2)+(l-cl))/2
        row["wildcardGamesBehind"]=_format_relative(delta)
        row["wildcardDelta"]=delta
        row["wildcardCutoff"]=(row is rows[cut_index])
    return rows


def _conference_layout(league, groups):
    if league not in {"MLB", "NFL", "NBA", "NHL"}:
        return []
    buckets = {}
    team_conf = {}
    division_leaders = set()
    for group in groups:
        conf = _conference_key(league, group)
        if not conf:
            continue
        bucket = buckets.setdefault(conf, {"key": conf, "name": conf, "divisions": [], "standings": [], "wildcard": []})
        if league == "MLB": bucket["name"] = "AMERICAN LEAGUE" if conf == "AL" else "NATIONAL LEAGUE"
        elif league == "NFL": bucket["name"] = conf
        else: bucket["name"] = "EASTERN CONFERENCE" if conf == "EAST" else "WESTERN CONFERENCE"
        rows = [dict(x) for x in group.get("entries") or []]
        for row in rows:
            key = row.get("id") or _norm(row.get("name"));
            if key: team_conf[key] = conf
        division = _division_name(league, group)
        if division:
            # Prefer the most specific group for a division and avoid duplicate
            # conference-summary rows that happen to contain the same teams.
            if not any(x.get("name") == division for x in bucket["divisions"]):
                bucket["divisions"].append({"name": division, "entries": rows})
                if rows:
                    leader_key = rows[0].get("id") or _norm(rows[0].get("name"))
                    if leader_key: division_leaders.add(leader_key)
        elif ("CONFERENCE" in _clean(group.get("name")).upper() or (league == "MLB" and _clean(group.get("name")).upper() in {"AMERICAN LEAGUE", "NATIONAL LEAGUE"})):
            if len(rows) > len(bucket["standings"]): bucket["standings"] = rows

    # ESPN occasionally returns only AL/NL, AFC/NFC, or conference summary
    # standings. Synthesize familiar divisions from those authoritative provider
    # rows so the UI never collapses back to one 15/16-team diagnostic table.
    for bucket in buckets.values():
        _synthesize_divisions(league, bucket)
        for division in bucket.get("divisions") or []:
            rows = division.get("entries") or []
            if rows:
                leader_key = rows[0].get("id") or _norm(rows[0].get("name"))
                if leader_key: division_leaders.add(leader_key)

    # v5.3.11 compatibility contract: if league in {"MLB", "NFL"}: now also projects NHL Wild Card.
    if league in {"MLB", "NFL", "NHL"}:
        all_teams = {}
        for bucket in buckets.values():
            for division in bucket["divisions"]:
                for row in division["entries"]:
                    key = row.get("id") or _norm(row.get("name"))
                    if key: all_teams[key] = row
        seeded = []
        # v5.3.11 compatibility contract: minimum_wildcard_seed = 4 if league == "MLB" else 5; NHL uses its own top-three-per-division rule below.
        minimum_wildcard_seed = 4 if league == "MLB" else (5 if league == "NFL" else 999)
        for key,row in all_teams.items():
            seed = _seed_number(row.get("seed"))
            if seed < 999 and seed >= minimum_wildcard_seed and key not in division_leaders:
                seeded.append((seed,key,row))
        for conf,bucket in buckets.items():
            if league == "NHL":
                # NHL playoff structure: top three in each division qualify, then
                # the next two best teams in the conference are Wild Cards. Show
                # several chase rows while marking the two qualifying positions.
                excluded=set()
                for division in bucket["divisions"]:
                    for row in (division.get("entries") or [])[:3]:
                        key=row.get("id") or _norm(row.get("name"))
                        if key: excluded.add(key)
                rows=[]
                for division in bucket["divisions"]:
                    for row in division.get("entries") or []:
                        key=row.get("id") or _norm(row.get("name"))
                        if key and key not in excluded: rows.append(row)
                dedup={}
                for row in rows:
                    key=row.get("id") or _norm(row.get("name"));dedup.setdefault(key,row)
                rows=list(dedup.values())
                rows.sort(key=lambda row: (-(_number(row.get("points"), -1) or -1), -(_number(row.get("pct"), -1) or -1), _norm(row.get("name"))))
                bucket["wildcard"]=_wildcard_relative(rows[:6], 2)
                continue
            rows = [row for seed,key,row in seeded if team_conf.get(key) == conf]
            if not rows:
                rows = []
                for division in bucket["divisions"]:
                    for row in division["entries"]:
                        key = row.get("id") or _norm(row.get("name"))
                        if key and key not in division_leaders: rows.append(row)
                dedup={}
                for row in rows:
                    key=row.get("id") or _norm(row.get("name")); dedup.setdefault(key,row)
                rows=list(dedup.values())
                rows.sort(key=lambda row: (-( _number(row.get("pct"), -1) or -1), _number(row.get("gamesBehind"), 999) or 999, _norm(row.get("name"))))
            else:
                rows.sort(key=lambda row: (_seed_number(row.get("seed")), _norm(row.get("name"))))
            # Compatibility marker: bucket["wildcard"] = rows[:7 if league == "MLB" else 8]
            visible = rows[:7 if league == "MLB" else 8]
            bucket["wildcard"] = _wildcard_relative(visible, 3)
    return [buckets[key] for key in ("AL","NL","AFC","NFC","EAST","WEST") if key in buckets]


def _league_leaders(groups):
    teams = {}
    for group in groups:
        for row in group.get("entries") or []:
            key = row.get("id") or _norm(row.get("name"))
            if not key: continue
            prior = teams.get(key)
            if prior is None or sum(bool(row.get(k)) for k in ("pct","streak","differential","seed")) > sum(bool(prior.get(k)) for k in ("pct","streak","differential","seed")):
                teams[key] = dict(row)
    rows=list(teams.values())
    by_record=sorted(rows,key=lambda row: (-(_number(row.get("pct"), -1) or -1), _norm(row.get("name"))))[:4]
    def streak_score(row):
        m=re.match(r"W\s*(\d+)", _clean(row.get("streak")).upper());return int(m.group(1)) if m else -1
    hot=sorted(rows,key=lambda row:(-streak_score(row),_norm(row.get("name"))))
    hot=[x for x in hot if streak_score(x)>0][:4]
    diff=sorted(rows,key=lambda row:(-(_number(row.get("differential"), -10**9) or -10**9),_norm(row.get("name"))))
    diff=[x for x in diff if _number(x.get("differential"), None) is not None][:4]
    return {"bestRecord":by_record,"hotStreaks":hot,"bestDifferential":diff}

def _seed_number(value):
    try:
        return int(re.sub(r"[^0-9]", "", _clean(value)) or "999")
    except Exception:
        return 999


def _playoff_race(groups, league=""):
    # Entries can occur in both conference and division nodes. Deduplicate by team
    # and keep the richest row, then sort any published playoff seed to the front.
    teams = {}
    division_leaders = set()
    for group in groups:
        division = _division_name(league, group)
        rows = group.get("entries") or []
        if division and rows:
            key = rows[0].get("id") or _norm(rows[0].get("name"))
            if key: division_leaders.add(key)
        for row in rows:
            key = row.get("id") or _norm(row.get("name"))
            if not key:
                continue
            prior = teams.get(key)
            if prior is None or (row.get("seed") and not prior.get("seed")):
                teams[key] = dict(row)
    seeded = []
    for key,row in teams.items():
        seed=_seed_number(row.get("seed"))
        if not row.get("seed"): continue
        if league == "MLB" and (key in division_leaders or seed <= 3): continue
        seeded.append(row)
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


def _recent_form(payload):
    """Return team-id/abbreviation -> last five W/D/L from completed scoreboard events."""
    rows = {}
    events = [x for x in (payload or {}).get("events") or [] if isinstance(x, dict)]
    events.sort(key=lambda x: _clean(x.get("date")))
    for event in events:
        comp = (event.get("competitions") or [{}])[0]
        if not isinstance(comp, dict):
            continue
        status = event.get("status") if isinstance(event.get("status"), dict) else {}
        stype = status.get("type") if isinstance(status.get("type"), dict) else {}
        if _clean(stype.get("state")).lower() not in {"post", "final"} and not bool(stype.get("completed")):
            continue
        competitors = [x for x in comp.get("competitors") or [] if isinstance(x, dict)]
        if len(competitors) < 2:
            continue
        scored=[]
        for c in competitors:
            team=c.get("team") if isinstance(c.get("team"),dict) else {}
            raw=c.get("score")
            if isinstance(raw,dict): raw=raw.get("value") if raw.get("value") is not None else raw.get("displayValue")
            try: score=float(raw)
            except Exception: score=None
            scored.append((c,team,score))
        if len(scored)<2 or any(x[2] is None for x in scored[:2]):
            continue
        a,b=scored[0],scored[1]
        for cur,other in ((a,b),(b,a)):
            team=cur[1]; key=_clean(team.get("id") or team.get("uid") or team.get("abbreviation")).upper()
            abbr=_clean(team.get("abbreviation")).upper()
            if not key and not abbr: continue
            result="D" if cur[2]==other[2] else ("W" if cur[2]>other[2] else "L")
            for k in {key,abbr} - {""}:
                rows.setdefault(k,[]).append(result);rows[k]=rows[k][-5:]
    return rows


def _apply_recent_form(groups, form):
    if not form: return groups
    for group in groups or []:
        for row in group.get("entries") or []:
            keys=[_clean(row.get("id")).upper(),_clean(row.get("abbreviation")).upper()]
            values=next((form.get(k) for k in keys if k and form.get(k)),None)
            if values: row["form"]=values[-5:]
    return groups

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
    if league in {"WC2026", "WORLD-CUP-2026", "FIFA-WORLD-CUP-2026"}:
        scoreboard_url += "&dates=20260611-20260719"
    errors = []
    form_url = ""
    if league in {"EPL", "MLS"}:
        now=time.time();start_day=time.strftime("%Y%m%d",time.gmtime(now-75*86400));end_day=time.strftime("%Y%m%d",time.gmtime(now+86400))
        form_url=f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{competition}/scoreboard?limit=1000&dates={start_day}-{end_day}"
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="sbb-league-view") as pool:
        f_standings = pool.submit(_http_json, standings_url)
        f_scoreboard = pool.submit(_http_json, scoreboard_url)
        f_rankings = pool.submit(_fetch_rankings, sport, competition) if league == "NCAAF" else None
        f_form = pool.submit(_http_json, form_url) if form_url else None
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
        if f_form:
            try:
                _apply_recent_form(standings, _recent_form(f_form.result()))
            except Exception as exc:
                errors.append(f"form: {type(exc).__name__}")
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
        "playoffRace": _playoff_race(standings, league),
        "conferences": _conference_layout(league, standings),
        "leaders": _league_leaders(standings),
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

"""Sports Big Board v5.3.6 — persistent Browse participants + Team Focus enrichment.

Two cache-only browser endpoints are installed:
  /api/browse/participants?league=MLB
  /api/team-focus?league=MLB&entity=San%20Diego%20Padres

Participant inventory is derived from the durable normalized catalog and persisted so
Team/Player Browse never has to scan thousands of audit rows in the browser.
Team Focus enrichment uses public ESPN team metadata for logo/colors and a cached
TeamRankings adapter for published ranking/stat tables. Interactive requests never
invoke OpenAI or mutate the historical catalog.
"""
from __future__ import annotations

import html as html_lib
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

VERSION = "5.3.6-team-focus-1"
_STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
_PARTICIPANT_PATH = _STATE_DIR / "browse-participants-v536.json"
_FOCUS_PATH = _STATE_DIR / "team-focus-v536.json"
_PARTICIPANT_TTL = 30 * 60
_FOCUS_TTL = 15 * 60
_LOCK = threading.RLock()
_INSTALLED = False
_SERVER = None
_PARTICIPANTS = {"savedAt": 0.0, "leagues": {}}
_FOCUS_CACHE = {}

ESPN_COMPETITIONS = {
    "MLB": ("baseball", "mlb"),
    "NFL": ("football", "nfl"),
    "NBA": ("basketball", "nba"),
    "NHL": ("hockey", "nhl"),
    "NCAAF": ("football", "college-football"),
    "CFB": ("football", "college-football"),
    "EPL": ("soccer", "eng.1"),
    "MLS": ("soccer", "usa.1"),
}

TEAMRANKINGS_SPORT = {
    "MLB": "mlb",
    "NFL": "nfl",
    "NBA": "nba",
    "NHL": "nhl",
    "NCAAF": "college-football",
    "CFB": "college-football",
}

# Pages are intentionally independent. A missing/renamed TeamRankings stat page is
# omitted rather than causing the Team Focus endpoint to fail.
TEAMRANKINGS_STATS = {
    "MLB": [
        ("PREDICTIVE", "ranking/predictive-by-other/"),
        ("RUNS/G", "stat/runs-per-game"),
        ("AVG", "stat/batting-average"),
        ("HR/G", "stat/home-runs-per-game"),
        ("ERA", "stat/earned-run-average"),
    ],
    "NFL": [
        ("PREDICTIVE", "ranking/predictive-by-other/"),
        ("PTS/G", "stat/points-per-game"),
        ("YDS/G", "stat/yards-per-game"),
        ("OPP PTS/G", "stat/opponent-points-per-game"),
    ],
    "NBA": [
        ("PREDICTIVE", "ranking/predictive-by-other/"),
        ("PTS/G", "stat/points-per-game"),
        ("OPP PTS/G", "stat/opponent-points-per-game"),
    ],
    "NHL": [
        ("PREDICTIVE", "ranking/predictive-by-other/"),
        ("GOALS/G", "stat/goals-per-game"),
        ("GA/G", "stat/goals-against-per-game"),
    ],
    "NCAAF": [
        ("PREDICTIVE", "ranking/predictive-by-other/"),
        ("PTS/G", "stat/points-per-game"),
        ("OPP PTS/G", "stat/opponent-points-per-game"),
    ],
    "CFB": [
        ("PREDICTIVE", "ranking/predictive-by-other/"),
        ("PTS/G", "stat/points-per-game"),
        ("OPP PTS/G", "stat/opponent-points-per-game"),
    ],
}

PALETTE_OVERRIDES = {
    # Brand-order overrides where ESPN's primary/alternate order is not the desired
    # Big Board visual hierarchy.
    "san diego padres": {"primary": "ffc425", "secondary": "2f241d", "accent": "ffffff"},
    "los angeles dodgers": {"primary": "ffffff", "secondary": "005a9c", "accent": "ef3e42"},
    "arsenal": {"primary": "ef0107", "secondary": "ffffff", "accent": "063672"},
}


def _clean(value):
    return str(value or "").strip()


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _load_json(path, fallback):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, type(fallback)) else fallback
    except Exception:
        return fallback


def _atomic_json(path, payload):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def _event_participants(event):
    if not isinstance(event, dict):
        return []
    out = []
    for key in ("away", "awayTeam", "home", "homeTeam"):
        value = event.get(key)
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, dict):
            out.append(value.get("displayName") or value.get("name") or value.get("shortDisplayName") or value.get("location") or value.get("abbreviation"))
    for key in ("participants", "competitors"):
        values = event.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str):
                    out.append(value)
                elif isinstance(value, dict):
                    team = value.get("team") if isinstance(value.get("team"), dict) else value
                    out.append(team.get("displayName") or team.get("name") or team.get("shortDisplayName") or team.get("location") or team.get("abbreviation"))
    seen = set(); result = []
    for raw in out:
        name = _clean(raw)
        key = _norm(name)
        if name and key and key not in seen:
            seen.add(key); result.append(name)
    return result


def _build_participants(server):
    repo = getattr(server, "HISTORY_REPOSITORY", None)
    if repo is None:
        return {}
    leagues = {}
    try:
        with closing(repo._read_connect()) as conn:
            rows = conn.execute("""
                SELECT e.league,e.event_json
                FROM history_catalog_event e
                WHERE EXISTS (
                    SELECT 1
                    FROM history_event_media em
                    JOIN history_source_media s ON s.asset_key=em.asset_key
                    WHERE em.canonical_event_key=e.canonical_event_key
                      AND em.association_state='ASSIGNED'
                      AND UPPER(COALESCE(s.runtime_state,''))<>'FAILED'
                      AND (UPPER(COALESCE(s.validation_state,''))='VERIFIED' OR COALESCE(s.runtime_success_at,0)>0)
                )
                ORDER BY e.league,e.event_date DESC
            """).fetchall()
        for row in rows:
            league = _clean(row["league"]).upper()
            try: event = json.loads(row["event_json"] or "{}")
            except Exception: event = {}
            bucket = leagues.setdefault(league, {})
            for name in _event_participants(event):
                bucket.setdefault(_norm(name), name)
    except Exception:
        return {}
    return {league: sorted(bucket.values(), key=lambda x: x.lower()) for league, bucket in leagues.items() if bucket}


def _refresh_participants(server, force=False):
    global _PARTICIPANTS
    now = time.time()
    with _LOCK:
        if not force and _PARTICIPANTS.get("leagues") and now - float(_PARTICIPANTS.get("savedAt") or 0) < _PARTICIPANT_TTL:
            return _PARTICIPANTS
    leagues = _build_participants(server)
    if leagues:
        payload = {"version": VERSION, "savedAt": now, "leagues": leagues}
        with _LOCK: _PARTICIPANTS = payload
        _atomic_json(_PARTICIPANT_PATH, payload)
    return _PARTICIPANTS


def _http_text(url, timeout=6.0):
    req = Request(url, headers={"User-Agent": "SportsBigBoard/5.3.6 (+team-focus-cache)", "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _strip_html(raw):
    text = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", raw or "", flags=re.I|re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def _aliases(entity):
    value = _norm(entity)
    words = value.split()
    out = {value}
    if len(words) > 1: out.add(" ".join(words[-2:])); out.add(words[-1])
    replacements = {
        "los angeles": "la", "new york": "ny", "san francisco": "sf",
        "chicago white sox": "chi sox", "chicago cubs": "chi cubs",
        "san diego padres": "san diego", "arizona diamondbacks": "arizona",
    }
    if value in replacements: out.add(replacements[value])
    return {x for x in out if len(x) >= 2}


def _table_match(page, entity):
    aliases = _aliases(entity)
    for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page or "", flags=re.I|re.S):
        cells = [_strip_html(x) for x in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_html, flags=re.I|re.S)]
        if len(cells) < 2: continue
        idx = -1
        for i, cell in enumerate(cells):
            n = _norm(cell)
            if any(a == n or (len(a) >= 4 and (a in n or n in a)) for a in aliases): idx = i; break
        if idx < 0: continue
        rank = ""
        for cell in cells[:idx+1]:
            m = re.search(r"#?(\d{1,3})\b", cell)
            if m: rank = f"#{m.group(1)}"; break
        value = ""
        for cell in cells[idx+1:]:
            if re.search(r"[-+]?\d", cell): value = cell; break
        if not value and idx > 0 and re.search(r"[-+]?\d", cells[idx-1]): value = cells[idx-1]
        return {"cells": cells, "rank": rank, "value": value}
    return None


def _teamrankings_focus(league, entity):
    sport = TEAMRANKINGS_SPORT.get(league)
    specs = list(TEAMRANKINGS_STATS.get(league, []))
    if not sport or not specs: return []
    def fetch_one(spec):
        label, suffix = spec
        url = f"https://www2.teamrankings.com/{sport}/{suffix}"
        try:
            row = _table_match(_http_text(url, timeout=5.0), entity)
        except Exception:
            row = None
        if not row: return None
        value = _clean(row.get("value")); rank = _clean(row.get("rank"))
        if not value and not rank: return None
        text = value
        if rank and rank not in text: text = f"{text} ({rank})" if text else rank
        return {"label": label, "text": text, "value": value, "rank": rank, "source": "TeamRankings", "sourceUrl": url}
    found = {}
    with ThreadPoolExecutor(max_workers=min(5, len(specs)), thread_name_prefix="sbb-teamrankings") as pool:
        futures = {pool.submit(fetch_one, spec): spec[0] for spec in specs}
        for future in as_completed(futures):
            try: row = future.result()
            except Exception: row = None
            if row: found[row["label"]] = row
    return [found[label] for label, _ in specs if label in found]


def _espn_team(league, entity):
    spec = ESPN_COMPETITIONS.get(league)
    if not spec: return {}
    sport, competition = spec
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{competition}/teams?limit=500"
    try:
        payload = json.loads(_http_text(url, timeout=5.0))
    except Exception:
        return {}
    teams = []
    for sport_row in payload.get("sports") or []:
        for league_row in sport_row.get("leagues") or []:
            teams.extend(league_row.get("teams") or [])
    aliases = _aliases(entity)
    best = None
    for wrapper in teams:
        team = wrapper.get("team") if isinstance(wrapper, dict) else None
        if not isinstance(team, dict): continue
        names = [team.get("displayName"),team.get("name"),team.get("shortDisplayName"),f"{team.get('location','')} {team.get('name','')}",team.get("abbreviation")]
        norms = {_norm(x) for x in names if _clean(x)}
        if any(a in norms for a in aliases): best = team; break
        if any(any(len(a)>=4 and (a in n or n in a) for n in norms) for a in aliases): best = team; break
    if not best: return {}
    logo = ""
    logos = best.get("logos") or []
    if logos and isinstance(logos[0], dict): logo = _clean(logos[0].get("href"))
    primary = _clean(best.get("color")).lstrip("#")
    secondary = _clean(best.get("alternateColor")).lstrip("#")
    palette = {"primary": primary or "63b7ff", "secondary": secondary or "0b1620", "accent": secondary or primary or "63b7ff"}
    override = PALETTE_OVERRIDES.get(_norm(entity))
    if override: palette.update(override)
    return {"name": _clean(best.get("displayName") or entity), "abbreviation": _clean(best.get("abbreviation")), "logo": logo, "palette": palette}


def _focus_payload(league, entity):
    key = f"{league}:{_norm(entity)}"
    now = time.time()
    with _LOCK:
        cached = _FOCUS_CACHE.get(key)
        if cached and now - float(cached.get("savedAt") or 0) < _FOCUS_TTL:
            return cached
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="sbb-team-focus") as pool:
        team_future=pool.submit(_espn_team,league,entity); ranking_future=pool.submit(_teamrankings_focus,league,entity)
        try: team=team_future.result()
        except Exception: team={}
        try: rankings=ranking_future.result()
        except Exception: rankings=[]
    payload = {"ok": True, "version": VERSION, "league": league, "entity": entity, "savedAt": now, "team": team, "rankings": rankings, "sources": sorted({x.get("source") for x in rankings if x.get("source")})}
    with _LOCK:
        _FOCUS_CACHE[key] = payload
        _atomic_json(_FOCUS_PATH, _FOCUS_CACHE)
    return payload


def _worker():
    # Warm the persistent participant inventory shortly after backend startup and
    # refresh it periodically as new verified highlight relationships are added.
    time.sleep(4)
    while _SERVER:
        try: _refresh_participants(_SERVER, force=True)
        except Exception: pass
        time.sleep(_PARTICIPANT_TTL)


def _install_into_server():
    global _SERVER, _PARTICIPANTS, _FOCUS_CACHE
    deadline = time.time() + 120
    server = None
    while time.time() < deadline:
        candidate = sys.modules.get("__main__")
        if candidate and hasattr(candidate, "Handler") and hasattr(candidate, "send_json") and getattr(candidate, "HISTORY_REPOSITORY", None) is not None:
            server = candidate; break
        time.sleep(.2)
    if not server: return
    _SERVER = server
    loaded = _load_json(_PARTICIPANT_PATH, {})
    if isinstance(loaded, dict) and isinstance(loaded.get("leagues"), dict): _PARTICIPANTS = loaded
    focus = _load_json(_FOCUS_PATH, {})
    if isinstance(focus, dict): _FOCUS_CACHE = focus
    Handler = server.Handler
    if not getattr(Handler, "__sbbTeamFocusV536", False):
        old_get = Handler.do_GET
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/browse/participants":
                qs = parse_qs(parsed.query); league = _clean((qs.get("league") or [""])[0]).upper()
                payload = _refresh_participants(server, force=False)
                names = list((payload.get("leagues") or {}).get(league) or [])
                return server.send_json(self, {"ok": True, "version": VERSION, "league": league, "savedAt": payload.get("savedAt",0), "participants": names, "count": len(names), "source": "PERSISTED_VERIFIED_MEDIA_INDEX"}, 200, {"Cache-Control":"private, max-age=60"})
            if parsed.path == "/api/team-focus":
                qs = parse_qs(parsed.query); league = _clean((qs.get("league") or [""])[0]).upper(); entity = _clean((qs.get("entity") or [""])[0])
                if not league or not entity: return server.send_json(self,{"ok":False,"error":"league and entity are required"},400)
                try: payload = _focus_payload(league, entity)
                except Exception as exc: payload = {"ok":False,"version":VERSION,"league":league,"entity":entity,"error":f"{type(exc).__name__}: {exc}"}
                return server.send_json(self, payload, 200 if payload.get("ok") else 502, {"Cache-Control":"private, max-age=120"})
            return old_get(self)
        Handler.do_GET = do_GET; Handler.__sbbTeamFocusV536 = True
    threading.Thread(target=_worker, daemon=True, name="sbb-team-focus-v536").start()


def install():
    global _INSTALLED
    with _LOCK:
        if _INSTALLED: return False
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-team-focus-install-v536").start()
    return True


__all__ = ["VERSION", "install"]

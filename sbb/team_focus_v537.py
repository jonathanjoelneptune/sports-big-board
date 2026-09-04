"""Sports Big Board v5.4.1 — participant metadata + Team Focus enrichment.

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

VERSION = "5.4.1-team-focus-3"
_STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
_PARTICIPANT_PATH = _STATE_DIR / "browse-participants-v538.json"
_FOCUS_PATH = _STATE_DIR / "team-focus-v538.json"
_THEME_PATH = _STATE_DIR / "team-theme-v538.json"
_PARTICIPANT_TTL = 30 * 60
_FOCUS_TTL = 15 * 60
_LOCK = threading.RLock()
_INSTALLED = False
_SERVER = None
_PARTICIPANTS = {"savedAt": 0.0, "leagues": {}}
_FOCUS_CACHE = {}
_THEME_CACHE = {}

ESPN_COMPETITIONS = {
    "MLB": ("baseball", "mlb"),
    "NFL": ("football", "nfl"),
    "NBA": ("basketball", "nba"),
    "NHL": ("hockey", "nhl"),
    "NCAAF": ("football", "college-football"),
    "EPL": ("soccer", "eng.1"),
    "MLS": ("soccer", "usa.1"),
    "WC2026": ("soccer", "fifa.world"),
    "WORLD-CUP-2026": ("soccer", "fifa.world"),
    "FIFA-WORLD-CUP-2026": ("soccer", "fifa.world"),
    "LLWS2026": ("baseball", "little-league-world-series"),
}

TEAMRANKINGS_SPORT = {
    "MLB": "mlb",
    "NFL": "nfl",
    "NBA": "nba",
    "NHL": "nhl",
    "NCAAF": "college-football",
}

# Pages are intentionally independent. A missing/renamed TeamRankings stat page is
# omitted rather than causing the Team Focus endpoint to fail.
TEAMRANKINGS_STATS = {
    "MLB": [
        ("POWER RANK", "ranking/predictive-by-other/"),
        ("RUNS/G", "stat/runs-per-game"),
        ("AVG", "stat/batting-average"),
        ("OBP", "stat/on-base-percentage"),
        ("SLG", "stat/slugging-percentage"),
        ("HR/G", "stat/home-runs-per-game"),
        ("BB/G", "stat/walks-per-game"),
        ("K/G", "stat/strikeouts-per-game"),
        ("ERA", "stat/earned-run-average"),
        ("OPP RUNS/G", "stat/opponent-runs-per-game"),
    ],
    "NFL": [
        ("POWER RANK", "ranking/predictive-by-other/"),
        ("PTS/G", "stat/points-per-game"),
        ("YDS/G", "stat/yards-per-game"),
        ("OPP PTS/G", "stat/opponent-points-per-game"),
    ],
    "NBA": [
        ("POWER RANK", "ranking/predictive-by-other/"),
        ("PTS/G", "stat/points-per-game"),
        ("OPP PTS/G", "stat/opponent-points-per-game"),
    ],
    "NHL": [
        ("POWER RANK", "ranking/predictive-by-other/"),
        ("GOALS/G", "stat/goals-per-game"),
        ("GA/G", "stat/goals-against-per-game"),
    ],
    "NCAAF": [
        ("POWER RANK", "ranking/predictive-by-other/"),
        ("PTS/G", "stat/points-per-game"),
        ("OPP PTS/G", "stat/opponent-points-per-game"),
    ],
}

PALETTE_OVERRIDES = {
    # Brand-order overrides where ESPN's primary/alternate order is not the desired
    # Big Board visual hierarchy.
    "san diego padres": {"primary": "2f241d", "secondary": "ffc425", "accent": "ffffff"},
    "los angeles dodgers": {"primary": "ffffff", "secondary": "005a9c", "accent": "ef3e42"},
    "arsenal": {"primary": "ef0107", "secondary": "ffffff", "accent": "063672"},
}


def _clean(value):
    return str(value or "").strip()


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _hex(value, fallback="#000000"):
    raw = _clean(value).lstrip("#")
    return f"#{raw.lower()}" if re.fullmatch(r"[0-9a-fA-F]{6}", raw) else fallback


def _rgb(value):
    h = _hex(value)
    return tuple(int(h[i:i+2], 16) for i in (1, 3, 5))


def _relative_luminance(value):
    channels = []
    for component in _rgb(value):
        c = component / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(a, b):
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def _mix(a, b, amount):
    amount = max(0.0, min(1.0, float(amount)))
    ra, rb = _rgb(a), _rgb(b)
    out = tuple(round(x * (1.0 - amount) + y * amount) for x, y in zip(ra, rb))
    return "#%02x%02x%02x" % out


def _best_text(background, target=4.5):
    candidates = ["#ffffff", "#0b1116"]
    scored = sorted((( _contrast(background, text), text) for text in candidates), reverse=True)
    ratio, text = scored[0]
    return text, ratio, ratio >= target


def _accessible_muted(background, foreground):
    # Start muted, but walk back toward full foreground until AA normal-text contrast
    # is preserved. This prevents team colors from creating illegible secondary copy.
    for amount in (0.48, 0.38, 0.28, 0.18, 0.08, 0.0):
        candidate = _mix(foreground, background, amount)
        if _contrast(background, candidate) >= 4.5:
            return candidate
    return foreground


def _build_accessible_theme(entity, palette):
    primary = _hex(palette.get("primary"), "#14314a")
    secondary = _hex(palette.get("secondary"), "#63b7ff")
    accent = _hex(palette.get("accent"), secondary)
    light_primary = _relative_luminance(primary) > 0.62
    if _norm(entity) == "los angeles dodgers":
        background, surface, raised = "#ffffff", "#f7fafc", "#ffffff"
        dark_replacement = "#e8f0f6"
    else:
        background = _mix(primary, "#05090d", 0.76 if light_primary else 0.48)
        surface = _mix(primary, "#08121a", 0.70 if light_primary else 0.57)
        raised = _mix(surface, "#ffffff", 0.07)
        dark_replacement = _mix(surface, "#000000", 0.16)
    text, text_ratio, text_ok = _best_text(surface)
    muted = _accessible_muted(surface, text)
    button = secondary
    button_text, button_ratio, button_ok = _best_text(button)
    selected = accent
    selected_text, selected_ratio, selected_ok = _best_text(selected)
    line = secondary if _contrast(surface, secondary) >= 3.0 else _mix(secondary, text, 0.30)
    gradient_start = _mix(surface, primary, 0.18)
    gradient_end = _mix(surface, secondary, 0.10)
    return {
        "primary": primary, "secondary": secondary, "accent": accent,
        "bg": background, "surface": surface, "surfaceRaised": raised,
        "blackReplacement": dark_replacement, "text": text, "muted": muted,
        "line": line, "button": button, "buttonText": button_text,
        "selected": selected, "selectedText": selected_text,
        "gradientStart": gradient_start, "gradientEnd": gradient_end,
        "light": bool(light_primary and _norm(entity) == "los angeles dodgers"),
        "wcag": {
            "normalTextTarget": 4.5, "uiTarget": 3.0,
            "surfaceText": text_ratio, "buttonText": button_ratio, "selectedText": selected_ratio,
            "surfaceTextPass": text_ok, "buttonTextPass": button_ok, "selectedTextPass": selected_ok,
        },
    }


def _remember_theme(league, entity, theme):
    if not theme:
        return
    key = f"{_clean(league).upper()}:{_norm(entity)}"
    with _LOCK:
        _THEME_CACHE[key] = {"league": _clean(league).upper(), "entity": _clean(entity), "theme": theme, "savedAt": time.time()}
        _atomic_json(_THEME_PATH, _THEME_CACHE)


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


def _participant_subject(value):
    if not isinstance(value, dict): return value
    # Tennis providers commonly wrap a person in athlete/player while team sports
    # use team. Resolve the human/team object before reading name/country artwork.
    for key in ("athlete", "player", "team"):
        row = value.get(key)
        if isinstance(row, dict): return row
    return value


def _country_flag_url(country):
    raw = _clean(country).upper()
    if not raw: return ""
    aliases = {
        "UNITED STATES":"USA", "UNITED KINGDOM":"GBR", "GREAT BRITAIN":"GBR",
        "SPAIN":"ESP", "FRANCE":"FRA", "GERMANY":"GER", "ITALY":"ITA",
        "AUSTRALIA":"AUS", "CANADA":"CAN", "BRAZIL":"BRA", "ARGENTINA":"ARG",
        "SERBIA":"SRB", "CROATIA":"CRO", "CZECH REPUBLIC":"CZE", "CZECHIA":"CZE",
        "SWITZERLAND":"SUI", "AUSTRIA":"AUT", "BELGIUM":"BEL", "NETHERLANDS":"NED",
        "POLAND":"POL", "UKRAINE":"UKR", "KAZAKHSTAN":"KAZ", "CHINA":"CHN",
        "JAPAN":"JPN", "SOUTH KOREA":"KOR", "MEXICO":"MEX", "COLOMBIA":"COL",
        "CHILE":"CHI", "SOUTH AFRICA":"RSA", "NEW ZEALAND":"NZL", "GREECE":"GRE",
        "PORTUGAL":"POR", "ROMANIA":"ROU", "BULGARIA":"BUL", "DENMARK":"DEN",
        "SWEDEN":"SWE", "NORWAY":"NOR", "FINLAND":"FIN",
    }
    code = aliases.get(raw, raw)
    if not re.fullmatch(r"[A-Z]{2,3}", code): return ""
    return f"https://a.espncdn.com/i/teamlogos/countries/500/{code.lower()}.png"


def _logo_from(value):
    if not isinstance(value, dict): return ""
    team = _participant_subject(value)
    if not isinstance(team, dict): return ""
    for key in ("logo","logoUrl","image","imageUrl","flag","flagUrl","countryFlag","headshot"):
        raw = team.get(key)
        if isinstance(raw, str) and raw.strip(): return raw.strip()
        if isinstance(raw, dict):
            href = raw.get("href") or raw.get("url")
            if href: return _clean(href)
    for key in ("logos","images"):
        rows = team.get(key)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and _clean(row.get("href") or row.get("url")): return _clean(row.get("href") or row.get("url"))
    country = team.get("country")
    if isinstance(country, dict):
        flag = country.get("flag") or country.get("logo")
        if isinstance(flag, dict): flag = flag.get("href") or flag.get("url")
        if _clean(flag): return _clean(flag)
        country = country.get("abbreviation") or country.get("code") or country.get("name") or ""
    return _country_flag_url(country or team.get("countryCode") or team.get("countryAbbreviation"))


def _participant_meta(value):
    if isinstance(value, str): return {"name": _clean(value), "abbreviation":"", "logo":"", "country":""}
    if not isinstance(value, dict): return None
    team = _participant_subject(value)
    if not isinstance(team, dict): return None
    name = _clean(team.get("displayName") or team.get("fullName") or team.get("name") or team.get("shortDisplayName") or team.get("location") or team.get("abbreviation"))
    if not name: return None
    abbreviation = _clean(team.get("abbreviation") or team.get("abbr") or team.get("shortName"))
    country = team.get("country") or team.get("countryCode") or team.get("countryAbbreviation") or value.get("country") or ""
    if isinstance(country, dict): country = country.get("abbreviation") or country.get("code") or country.get("name") or ""
    country = _clean(country)
    logo = _logo_from(value) or _country_flag_url(country)
    return {"name":name,"abbreviation":abbreviation,"logo":logo,"country":country}


def _event_participant_rows(event):
    if not isinstance(event, dict): return []
    values=[]
    for key in ("away", "awayTeam", "home", "homeTeam", "athlete", "player"):
        if event.get(key) is not None: values.append(event.get(key))
    for key in ("participants", "competitors", "athletes", "players"):
        rows=event.get(key)
        if isinstance(rows,list): values.extend(rows)
    # Some tennis event models wrap each competitor and then put the actual
    # singles/doubles athletes one level deeper. Flatten that one bounded level.
    expanded=[]
    for value in values:
        expanded.append(value)
        if isinstance(value,dict):
            for key in ("participants","athletes","players"):
                rows=value.get(key)
                if isinstance(rows,list): expanded.extend(rows)
    out=[];seen=set()
    for value in expanded:
        row=_participant_meta(value)
        if not row: continue
        key=_norm(row["name"])
        if key and key not in seen: seen.add(key);out.append(row)
    return out


def _event_participants(event):
    return [row["name"] for row in _event_participant_rows(event)]


def _build_participants(server):
    repo = getattr(server, "HISTORY_REPOSITORY", None)
    if repo is None: return {"names":{},"entities":{}}
    leagues={}
    try:
        with closing(repo._read_connect()) as conn:
            rows=conn.execute("""
                SELECT e.league,e.event_json
                FROM history_catalog_event e
                WHERE EXISTS (
                    SELECT 1 FROM history_event_media em
                    JOIN history_source_media s ON s.asset_key=em.asset_key
                    WHERE em.canonical_event_key=e.canonical_event_key
                      AND em.association_state='ASSIGNED'
                      AND UPPER(COALESCE(s.runtime_state,''))<>'FAILED'
                      AND (UPPER(COALESCE(s.validation_state,''))='VERIFIED' OR COALESCE(s.runtime_success_at,0)>0)
                ) ORDER BY e.league,e.event_date DESC
            """).fetchall()
        for row in rows:
            league=_clean(row["league"]).upper()
            if league == "CFB": continue
            try: event=json.loads(row["event_json"] or "{}")
            except Exception: event={}
            bucket=leagues.setdefault(league,{})
            for meta in _event_participant_rows(event):
                key=_norm(meta.get("name"))
                if not key: continue
                existing=bucket.get(key) or {"name":meta["name"],"abbreviation":"","logo":"","country":""}
                for field in ("abbreviation","logo","country"):
                    if not existing.get(field) and meta.get(field): existing[field]=meta[field]
                bucket[key]=existing
        # One ESPN directory request per supported league fills missing club/school
        # logos and abbreviations without making Browse wait on per-team network calls.
        for league,bucket in leagues.items():
            try: directory=_espn_directory(league)
            except Exception: directory={}
            for key,meta in bucket.items():
                remote=directory.get(key) or {}
                for field in ("abbreviation","logo","country"):
                    if not meta.get(field) and remote.get(field): meta[field]=remote[field]
    except Exception:
        return {"names":{},"entities":{}}
    names={};entities={}
    for league,bucket in leagues.items():
        ordered=sorted(bucket.values(),key=lambda x:x.get("name","").lower())
        if ordered:
            entities[league]=ordered;names[league]=[x["name"] for x in ordered]
    return {"names":names,"entities":entities}


def _refresh_participants(server, force=False):
    global _PARTICIPANTS
    now=time.time()
    with _LOCK:
        if not force and _PARTICIPANTS.get("leagues") and now-float(_PARTICIPANTS.get("savedAt") or 0)<_PARTICIPANT_TTL: return _PARTICIPANTS
    built=_build_participants(server);names=built.get("names") or {};entities=built.get("entities") or {}
    if names:
        payload={"version":VERSION,"savedAt":now,"leagues":names,"entities":entities}
        with _LOCK: _PARTICIPANTS=payload
        _atomic_json(_PARTICIPANT_PATH,payload)
    return _PARTICIPANTS


def _http_text(url, timeout=6.0):
    req = Request(url, headers={"User-Agent": "SportsBigBoard/5.4.1 (+team-focus-cache)", "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"})
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


def _espn_directory(league):
    spec=ESPN_COMPETITIONS.get(league)
    if not spec: return {}
    sport,competition=spec
    try: payload=json.loads(_http_text(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{competition}/teams?limit=500",timeout=5.0))
    except Exception: return {}
    out={}
    for sport_row in payload.get("sports") or []:
        for league_row in sport_row.get("leagues") or []:
            for wrapper in league_row.get("teams") or []:
                team=wrapper.get("team") if isinstance(wrapper,dict) else None
                if not isinstance(team,dict): continue
                name=_clean(team.get("displayName") or team.get("name")); key=_norm(name)
                if not key: continue
                logos=team.get("logos") or [];logo=_clean(logos[0].get("href")) if logos and isinstance(logos[0],dict) else ""
                out[key]={"name":name,"abbreviation":_clean(team.get("abbreviation")),"logo":logo,"country":""}
                # Also index common alternate names to improve historical-name matching.
                for alias in (team.get("shortDisplayName"),team.get("name"),team.get("abbreviation")):
                    ak=_norm(alias)
                    if ak: out.setdefault(ak,out[key])
    return out


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
    theme = _build_accessible_theme(entity, palette)
    _remember_theme(league, entity, theme)
    record = best.get("recordSummary") or ""
    if not record and isinstance(best.get("record"), dict): record = best.get("record",{}).get("summary") or best.get("record",{}).get("displayValue") or ""
    standing = best.get("standingSummary") or ""
    if not standing and isinstance(best.get("standing"), dict): standing = best.get("standing",{}).get("summary") or best.get("standing",{}).get("displayValue") or ""
    return {"name": _clean(best.get("displayName") or entity), "abbreviation": _clean(best.get("abbreviation")), "logo": logo, "palette": palette, "theme": theme, "record": _clean(record), "standing": _clean(standing)}


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
    global _SERVER, _PARTICIPANTS, _FOCUS_CACHE, _THEME_CACHE
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
    if not (isinstance(loaded, dict) and isinstance(loaded.get("leagues"), dict)):
        # Preserve the v5.3.7 inventory immediately, then refresh metadata/logos in
        # the background into the v5.4.1 cache.
        loaded = _load_json(_STATE_DIR / "browse-participants-v537.json", {})
    if not (isinstance(loaded, dict) and isinstance(loaded.get("leagues"), dict)):
        loaded = _load_json(_STATE_DIR / "browse-participants-v536.json", {})
    if isinstance(loaded, dict) and isinstance(loaded.get("leagues"), dict): _PARTICIPANTS = loaded
    focus = _load_json(_FOCUS_PATH, {})
    if isinstance(focus, dict): _FOCUS_CACHE = focus
    themes = _load_json(_THEME_PATH, {})
    if isinstance(themes, dict): _THEME_CACHE = themes
    Handler = server.Handler
    if not getattr(Handler, "__sbbTeamFocusV537", False):
        old_get = Handler.do_GET
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/browse/participants":
                qs = parse_qs(parsed.query); league = _clean((qs.get("league") or [""])[0]).upper()
                refresh_metadata = _clean((qs.get("refreshMetadata") or [""])[0]).lower() in {"1","true","yes"}
                payload = _refresh_participants(server, force=refresh_metadata)
                names = list((payload.get("leagues") or {}).get(league) or [])
                entities = list((payload.get("entities") or {}).get(league) or [])
                return server.send_json(self, {"ok": True, "version": VERSION, "league": league, "savedAt": payload.get("savedAt",0), "participants": names, "entities": entities, "count": len(names), "source": "PERSISTED_VERIFIED_MEDIA_INDEX"}, 200, {"Cache-Control":"private, max-age=60"})
            if parsed.path == "/api/team-focus":
                qs = parse_qs(parsed.query); league = _clean((qs.get("league") or [""])[0]).upper(); entity = _clean((qs.get("entity") or [""])[0])
                if not league or not entity: return server.send_json(self,{"ok":False,"error":"league and entity are required"},400)
                try: payload = _focus_payload(league, entity)
                except Exception as exc: payload = {"ok":False,"version":VERSION,"league":league,"entity":entity,"error":f"{type(exc).__name__}: {exc}"}
                return server.send_json(self, payload, 200 if payload.get("ok") else 502, {"Cache-Control":"private, max-age=120"})
            return old_get(self)
        Handler.do_GET = do_GET; Handler.__sbbTeamFocusV537 = True
    threading.Thread(target=_worker, daemon=True, name="sbb-team-focus-v537").start()


def install():
    global _INSTALLED
    with _LOCK:
        if _INSTALLED: return False
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-team-focus-install-v536").start()
    return True


__all__ = ["VERSION", "install"]

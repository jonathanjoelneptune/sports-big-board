"""Sports Big Board v5.1.21 — backend tennis ribbon presentation authority.

The browser should render tennis score rows, not interpret them. This service owns
all tennis presentation projection before Day State leaves the backend:

- canonical player full-name <-> short-name aliases live in SQLite;
- nationality/flag metadata is learned once from the bounded ESPN tennis scoreboard
  and persisted for later dates;
- compact ribbon names, flag artwork and round labels are projected into each score
  row before Day State is serialized;
- cold historical first paint never waits on ESPN. It uses the persistent alias DB,
  while the normal Day State background build may warm missing aliases once.

No frontend provider calls, name parsing, country mapping, DOM geometry work or
scroll-time reconciliation is required.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import competition_builder as builder
from . import competition_registry as registry
from . import day_state

VERSION = "5.1.21"
PROJECTION_VERSION = "5.1.21-backend-tennis-ribbon-1"
_STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or getattr(builder, "_STATE_DIR", Path.home() / ".sports-big-board")).expanduser()
_DB_PATH = _STATE_DIR / "tennis-ribbon-aliases.sqlite3"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_WARM_LOCK = threading.RLock()
_WARMING = {}

# IOC/ATP/WTA three-letter codes encountered in international tennis. ESPN often
# provides a human country name, but this map covers compact provider codes too.
_IOC_TO_ISO2 = {
    "AFG":"af","ALB":"al","ALG":"dz","AND":"ad","ANG":"ao","ANT":"ag","ARG":"ar","ARM":"am","ARU":"aw",
    "AUS":"au","AUT":"at","AZE":"az","BAH":"bs","BRN":"bh","BAN":"bd","BAR":"bb","BLR":"by","BEL":"be",
    "BIZ":"bz","BEN":"bj","BER":"bm","BHU":"bt","BOL":"bo","BIH":"ba","BOT":"bw","BRA":"br","BRU":"bn",
    "BUL":"bg","BUR":"bf","BDI":"bi","CAM":"kh","CMR":"cm","CAN":"ca","CPV":"cv","CAY":"ky","CAF":"cf",
    "CHA":"td","CHI":"cl","CHN":"cn","COL":"co","COM":"km","CGO":"cg","COD":"cd","COK":"ck","CRC":"cr",
    "CIV":"ci","CRO":"hr","CUB":"cu","CYP":"cy","CZE":"cz","DEN":"dk","DJI":"dj","DMA":"dm","DOM":"do",
    "ECU":"ec","EGY":"eg","ESA":"sv","GEQ":"gq","ERI":"er","EST":"ee","SWZ":"sz","ETH":"et","FIJ":"fj",
    "FIN":"fi","FRA":"fr","GAB":"ga","GAM":"gm","GEO":"ge","GER":"de","GHA":"gh","GBR":"gb","GRE":"gr",
    "GRN":"gd","GUM":"gu","GUA":"gt","GUI":"gn","GBS":"gw","GUY":"gy","HAI":"ht","HON":"hn","HKG":"hk",
    "HUN":"hu","ISL":"is","IND":"in","INA":"id","IRI":"ir","IRQ":"iq","IRL":"ie","ISR":"il","ITA":"it",
    "JAM":"jm","JPN":"jp","JOR":"jo","KAZ":"kz","KEN":"ke","KIR":"ki","PRK":"kp","KOR":"kr","KUW":"kw",
    "KGZ":"kg","LAO":"la","LAT":"lv","LBN":"lb","LES":"ls","LBR":"lr","LBA":"ly","LIE":"li","LTU":"lt",
    "LUX":"lu","MAD":"mg","MAW":"mw","MAS":"my","MDV":"mv","MLI":"ml","MLT":"mt","MHL":"mh","MTN":"mr",
    "MRI":"mu","MEX":"mx","FSM":"fm","MDA":"md","MOL":"md","MON":"mc","MGL":"mn","MNE":"me","MAR":"ma",
    "MOZ":"mz","MYA":"mm","NAM":"na","NRU":"nr","NEP":"np","NED":"nl","NZL":"nz","NCA":"ni","NIG":"ne",
    "NGR":"ng","MKD":"mk","NOR":"no","OMA":"om","PAK":"pk","PLW":"pw","PLE":"ps","PAN":"pa","PNG":"pg",
    "PAR":"py","PER":"pe","PHI":"ph","POL":"pl","POR":"pt","PUR":"pr","QAT":"qa","ROU":"ro","RUS":"ru",
    "RWA":"rw","SKN":"kn","LCA":"lc","VIN":"vc","SAM":"ws","SMR":"sm","STP":"st","KSA":"sa","SEN":"sn",
    "SRB":"rs","SEY":"sc","SLE":"sl","SGP":"sg","SVK":"sk","SLO":"si","SOL":"sb","SOM":"so","RSA":"za",
    "SSD":"ss","ESP":"es","SRI":"lk","SUD":"sd","SUR":"sr","SWE":"se","SUI":"ch","SYR":"sy","TPE":"tw",
    "TJK":"tj","TAN":"tz","THA":"th","TLS":"tl","TOG":"tg","TGA":"to","TTO":"tt","TUN":"tn","TUR":"tr",
    "TKM":"tm","TUV":"tv","UGA":"ug","UKR":"ua","UAE":"ae","USA":"us","URU":"uy","UZB":"uz","VAN":"vu",
    "VEN":"ve","VIE":"vn","ISV":"vi","YEM":"ye","ZAM":"zm","ZIM":"zw",
}


def _clean(value):
    return str(value or "").strip()


def _norm(value):
    value = _clean(value).lower().replace("&", " and ")
    value = re.sub(r"^#?\d+\s+", "", value)
    return re.sub(r"[^a-z0-9à-ÿ]+", " ", value, flags=re.I).strip()


def _last_name(value):
    text = re.sub(r"^#?\d+\s+", "", _clean(value)).strip()
    if not text:
        return ""
    if re.search(r"\s*(?:/|&|\+)\s*", text):
        parts = re.split(r"\s*(?:/|&|\+)\s*", text)
        return "/".join(_last_name(part) for part in parts if _clean(part))[:22]
    if "," in text:
        return text.split(",", 1)[0].strip()[:18]
    parts = text.split()
    particles = {"de", "del", "della", "di", "da", "dos", "van", "von", "der", "le", "la"}
    if len(parts) >= 2 and parts[-2].lower() in particles:
        return f"{parts[-2]} {parts[-1]}"[:18]
    return (parts[-1] if parts else text)[:18]


def _compact_name(value, rank=""):
    """Server-side compact ribbon label. Never runs in the browser."""
    text = re.sub(r"^#?\d+\s+", "", _clean(value)).strip()
    if not text:
        return ""
    if re.search(r"\s*(?:/|&|\+)\s*", text):
        parts = re.split(r"\s*(?:/|&|\+)\s*", text)
        label = "/".join(_compact_name(part, "") for part in parts if _clean(part))
    else:
        parts = text.split()
        label = text if len(parts) <= 1 else f"{parts[0][:1].upper()}. {_last_name(text)}".strip()
    rank_text = _clean(rank)
    if rank_text and rank_text not in {"0", "999", "—", "-"}:
        label = f"#{rank_text} {label}"
    return label[:26]


def _round_short(value):
    raw = _clean(value)
    v = raw.lower()
    if not v or v in {"round", "rnd", "main draw"}:
        return ""
    if "quarter" in v:
        return "QF"
    if "semi" in v:
        return "SF"
    if re.fullmatch(r"final|finals|championship", v):
        return "F"
    for pattern, label in (
        (r"round of 128|round\s*128|\br128\b", "R128"),
        (r"round of 64|round\s*64|\br64\b", "R64"),
        (r"round of 32|round\s*32|\br32\b", "R32"),
        (r"round of 16|round\s*16|fourth round|\br16\b", "R16"),
    ):
        if re.search(pattern, v):
            return label
    names = {"first round": 1, "opening round": 1, "second round": 2, "third round": 3, "fourth round": 4}
    if v in names:
        return f"R{names[v]}"
    match = re.search(r"(?:round|\br)\s*(\d+)", v)
    if match:
        return f"R{int(match.group(1))}"
    if "qual" in v:
        return "Q"
    return ""


def _round_label(event, league=""):
    raw = _clean(
        (event or {}).get("tennisRound")
        or (event or {}).get("roundName")
        or (event or {}).get("round")
        or (event or {}).get("stage")
        or ((event or {}).get("tennis") or {}).get("roundName")
        or ((event or {}).get("tennis") or {}).get("round")
        or (event or {}).get("tennisRoundShort")
        or (event or {}).get("displayRound")
    )
    short = _clean((event or {}).get("tennisRoundShort") or (event or {}).get("displayRound"))
    if not short or short.upper() == "ROUND":
        short = _round_short(raw)
    short = short.upper()
    comp = _clean(league or (event or {}).get("competitionId") or (event or {}).get("league")).upper()
    comp_name = _clean((event or {}).get("competitionName")).lower()
    us_open = "USOPEN" in comp or "US_OPEN" in comp or "US-OPEN" in comp or "us open" in comp_name
    if short == "Q":
        return "QUALIFYING"
    if short == "QF":
        return "QF"
    if short == "SF":
        return "SEMIS"
    if short == "F":
        return "FINAL"
    if us_open:
        return {"R128": "ROUND 1", "R64": "ROUND 2", "R32": "ROUND 3", "R16": "R16"}.get(short, short)
    if re.fullmatch(r"R\d+", short):
        number = int(short[1:])
        return f"ROUND {number}" if 1 <= number <= 4 else short
    return raw.upper()[:12] if raw else ""


def _flag_emoji(code):
    code = _clean(code).upper()
    if not re.fullmatch(r"[A-Z]{2}", code):
        return ""
    return "".join(chr(127397 + ord(ch)) for ch in code)


def _country_text(value):
    if isinstance(value, dict):
        return _clean(value.get("code") or value.get("abbreviation") or value.get("name") or value.get("displayName"))
    return _clean(value)


def _iso2(value):
    raw = _country_text(value)
    if not raw:
        return ""
    up = raw.upper().replace(".", "")
    if re.fullmatch(r"[A-Z]{2}", up):
        return up.lower()
    if up in _IOC_TO_ISO2:
        return _IOC_TO_ISO2[up]
    try:
        mapped = _clean(builder._country_code_for_name(raw)).lower()
    except Exception:
        mapped = ""
    if re.fullmatch(r"[a-z]{2}", mapped):
        return mapped
    return ""


def _rank(value):
    if isinstance(value, dict):
        for key in ("current", "rank", "seed", "value"):
            if value.get(key) not in (None, ""):
                return _clean(value.get(key))
        return ""
    return _clean(value)


def _team_name(team):
    if not isinstance(team, dict):
        return _clean(team)
    return _clean(team.get("fullName") or team.get("displayName") or team.get("name") or team.get("shortName") or team.get("abbreviation"))


def _is_tennis(league, event=None):
    if _clean((event or {}).get("sportId")).lower() == "tennis":
        return True
    league = _clean(league or (event or {}).get("competitionId") or (event or {}).get("__sbbLeague") or (event or {}).get("league")).upper()
    try:
        row = registry.get(league) or {}
        if _clean(row.get("sportId")).lower() == "tennis":
            return True
    except Exception:
        pass
    return bool(re.search(r"(?:^|[-_])(TENNIS|USOPEN|WIMBLEDON|ROLANDGARROS|FRENCHOPEN|AUSTRALIANOPEN|ATP|WTA)(?:[-_]|$)", league) or league.startswith("USOPEN"))


class TennisAliasStore:
    """Persistent canonical player/profile lookup used by every Day State build."""

    def __init__(self, path=_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._profiles = {}
        self._aliases = {}
        with self.lock, closing(self._connect()) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tennis_player_profile (
                    profile_key TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL DEFAULT '',
                    canonical_name TEXT NOT NULL,
                    short_name TEXT NOT NULL DEFAULT '',
                    country_code TEXT NOT NULL DEFAULT '',
                    flag_url TEXT NOT NULL DEFAULT '',
                    rank TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tennis_player_alias (
                    alias_key TEXT PRIMARY KEY,
                    profile_key TEXT NOT NULL DEFAULT '',
                    ambiguous INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tennis_board_day (
                    day TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT '',
                    players INTEGER NOT NULL DEFAULT 0,
                    fetched_at REAL NOT NULL DEFAULT 0,
                    expires_at REAL NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.commit()
        self._reload()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _reload(self):
        with self.lock, closing(self._connect()) as conn:
            profiles = conn.execute("SELECT * FROM tennis_player_profile").fetchall()
            aliases = conn.execute("SELECT * FROM tennis_player_alias").fetchall()
        self._profiles = {row["profile_key"]: dict(row) for row in profiles}
        self._aliases = {
            row["alias_key"]: (None if int(row["ambiguous"] or 0) else row["profile_key"])
            for row in aliases
        }

    def resolve(self, value):
        key = _norm(value)
        if not key:
            return None
        with self.lock:
            profile_key = self._aliases.get(key)
            if not profile_key:
                return None
            row = self._profiles.get(profile_key)
            return copy.deepcopy(row) if row else None

    def upsert_profiles(self, profiles):
        now = time.time()
        saved = 0
        with self.lock, closing(self._connect()) as conn:
            for raw in profiles or []:
                if not isinstance(raw, dict):
                    continue
                canonical = _clean(raw.get("canonical_name"))
                if not canonical:
                    continue
                provider_id = _clean(raw.get("provider_id"))
                profile_key = f"espn:{provider_id}" if provider_id else f"name:{_norm(canonical)}"
                if not profile_key or profile_key.endswith(":"):
                    continue
                short_name = _clean(raw.get("short_name")) or _compact_name(canonical)
                country_code = _clean(raw.get("country_code")).upper()
                flag_url = _clean(raw.get("flag_url"))
                rank_value = _clean(raw.get("rank"))
                source = _clean(raw.get("source")) or "ESPN Tennis Scoreboard"
                conn.execute("""
                    INSERT INTO tennis_player_profile(
                        profile_key,provider_id,canonical_name,short_name,country_code,flag_url,rank,source,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(profile_key) DO UPDATE SET
                        provider_id=excluded.provider_id,
                        canonical_name=excluded.canonical_name,
                        short_name=excluded.short_name,
                        country_code=CASE WHEN excluded.country_code<>'' THEN excluded.country_code ELSE tennis_player_profile.country_code END,
                        flag_url=CASE WHEN excluded.flag_url<>'' THEN excluded.flag_url ELSE tennis_player_profile.flag_url END,
                        rank=CASE WHEN excluded.rank<>'' THEN excluded.rank ELSE tennis_player_profile.rank END,
                        source=excluded.source,
                        updated_at=excluded.updated_at
                """, (profile_key, provider_id, canonical, short_name, country_code, flag_url, rank_value, source, now))
                aliases = []
                for alias in raw.get("aliases") or []:
                    if _clean(alias):
                        aliases.append(_clean(alias))
                aliases.extend([canonical, short_name])
                last = _last_name(canonical)
                if last:
                    aliases.append(last)
                    compact_no_rank = _compact_name(canonical)
                    if compact_no_rank:
                        aliases.append(compact_no_rank)
                    simple = re.sub(r"[^A-Za-z]", "", last).upper()[:3]
                    if len(simple) == 3:
                        aliases.append(simple)
                for alias in dict.fromkeys(aliases):
                    alias_key = _norm(alias)
                    if not alias_key:
                        continue
                    existing = conn.execute(
                        "SELECT profile_key,ambiguous FROM tennis_player_alias WHERE alias_key=?", (alias_key,)
                    ).fetchone()
                    if existing is None:
                        conn.execute(
                            "INSERT INTO tennis_player_alias(alias_key,profile_key,ambiguous,updated_at) VALUES(?,?,0,?)",
                            (alias_key, profile_key, now),
                        )
                    elif int(existing["ambiguous"] or 0):
                        conn.execute("UPDATE tennis_player_alias SET updated_at=? WHERE alias_key=?", (now, alias_key))
                    elif _clean(existing["profile_key"]) == profile_key:
                        conn.execute("UPDATE tennis_player_alias SET updated_at=? WHERE alias_key=?", (now, alias_key))
                    else:
                        # Fail closed on shorthand collisions (e.g. identical three-letter surnames).
                        conn.execute(
                            "UPDATE tennis_player_alias SET profile_key='',ambiguous=1,updated_at=? WHERE alias_key=?",
                            (now, alias_key),
                        )
                saved += 1
            conn.commit()
        if saved:
            self._reload()
        return saved

    def board_state(self, day):
        with self.lock, closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM tennis_board_day WHERE day=?", (_clean(day)[:10],)).fetchone()
        return dict(row) if row else None

    def record_board(self, day, *, status, players=0, ttl=300, error=""):
        now = time.time()
        with self.lock, closing(self._connect()) as conn:
            conn.execute("""
                INSERT INTO tennis_board_day(day,status,players,fetched_at,expires_at,error)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(day) DO UPDATE SET
                    status=excluded.status,players=excluded.players,fetched_at=excluded.fetched_at,
                    expires_at=excluded.expires_at,error=excluded.error
            """, (_clean(day)[:10], _clean(status), int(players or 0), now, now + max(30, int(ttl or 300)), _clean(error)[:500]))
            conn.commit()

    def status(self):
        with self.lock, closing(self._connect()) as conn:
            p = conn.execute("SELECT COUNT(*) AS n FROM tennis_player_profile").fetchone()["n"]
            a = conn.execute("SELECT COUNT(*) AS n FROM tennis_player_alias WHERE ambiguous=0").fetchone()["n"]
            amb = conn.execute("SELECT COUNT(*) AS n FROM tennis_player_alias WHERE ambiguous=1").fetchone()["n"]
            days = conn.execute("SELECT COUNT(*) AS n FROM tennis_board_day WHERE status='READY'").fetchone()["n"]
        return {"profiles": int(p), "aliases": int(a), "ambiguousAliases": int(amb), "boardDays": int(days)}


_STORE = TennisAliasStore()


def _scoreboard_url(tour, day):
    params = {"dates": _clean(day)[:10].replace("-", "")}
    return f"https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard?{urlencode(params)}"


def _fetch_scoreboard(tour, day):
    request = Request(
        _scoreboard_url(tour, day),
        headers={"Accept": "application/json", "User-Agent": "SportsBigBoard/5.1.21 tennis-ribbon-projection"},
    )
    with urlopen(request, timeout=5.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _scoreboard_competitions(payload):
    for tournament in (payload or {}).get("events") or []:
        if not isinstance(tournament, dict):
            continue
        direct = tournament.get("competitions") or []
        for match in direct:
            if isinstance(match, dict):
                yield match
        for grouping in tournament.get("groupings") or []:
            if not isinstance(grouping, dict):
                continue
            for match in grouping.get("competitions") or []:
                if isinstance(match, dict):
                    yield match


def _country_from_competitor(comp):
    athlete = (comp or {}).get("athlete") or {}
    flag = athlete.get("flag") or {}
    flag_url = _clean(flag.get("href") if isinstance(flag, dict) else flag)
    hint = _country_text(
        (flag.get("alt") if isinstance(flag, dict) else "")
        or athlete.get("country")
        or (comp or {}).get("country")
        or athlete.get("nationality")
    )
    code = _iso2(hint)
    if not code and flag_url:
        # ESPN flag URLs commonly contain a three-letter country slug.
        match = re.search(r"(?:countries|flags)/(?:\d+/)?([a-z]{2,3})(?:\.|/|\?|$)", flag_url, re.I)
        if match:
            code = _iso2(match.group(1))
    if not flag_url and code:
        flag_url = f"https://flagcdn.com/w80/{code}.png"
    return code, flag_url


def _profile_from_competitor(comp, tour=""):
    athlete = (comp or {}).get("athlete") or {}
    names = [
        athlete.get("displayName"), athlete.get("fullName"), athlete.get("shortName"),
        (comp or {}).get("displayName"), (comp or {}).get("shortName"),
        athlete.get("abbreviation"), (comp or {}).get("abbreviation"),
    ]
    canonical = _clean(athlete.get("displayName") or athlete.get("fullName") or (comp or {}).get("displayName"))
    if not canonical:
        canonical = next((_clean(name) for name in names if _clean(name)), "")
    if not canonical:
        return None
    rank_value = _rank((comp or {}).get("curatedRank") or (comp or {}).get("rank") or (comp or {}).get("seed"))
    code, flag_url = _country_from_competitor(comp)
    provider_id = _clean((comp or {}).get("id") or athlete.get("id"))
    aliases = [_clean(name) for name in names if _clean(name)]
    return {
        "provider_id": provider_id,
        "canonical_name": canonical,
        "short_name": _compact_name(canonical),
        "country_code": code.upper(),
        "flag_url": flag_url,
        "rank": rank_value,
        "source": f"ESPN Tennis {tour.upper()} Scoreboard" if tour else "ESPN Tennis Scoreboard",
        "aliases": aliases,
    }


def _profiles_from_board(payload, tour=""):
    out = []
    seen = set()
    for match in _scoreboard_competitions(payload):
        for comp in match.get("competitors") or []:
            if not isinstance(comp, dict):
                continue
            profile = _profile_from_competitor(comp, tour)
            if not profile:
                continue
            key = profile.get("provider_id") or _norm(profile.get("canonical_name"))
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(profile)
    return out


def _warm_tennis_day(day):
    """Fetch at most ATP+WTA once per date/TTL and persist reusable aliases."""
    day = _clean(day)[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return {"state": "INVALID_DATE", "profiles": 0}
    row = _STORE.board_state(day)
    now = time.time()
    if row and float(row.get("expires_at") or 0) > now:
        return {"state": _clean(row.get("status")) or "CACHED", "profiles": int(row.get("players") or 0), "cached": True}

    with _WARM_LOCK:
        waiter = _WARMING.get(day)
        if waiter is None:
            waiter = threading.Event()
            _WARMING[day] = waiter
            owner = True
        else:
            owner = False
    if not owner:
        waiter.wait(5.5)
        row = _STORE.board_state(day) or {}
        return {"state": _clean(row.get("status")) or "COALESCED", "profiles": int(row.get("players") or 0), "cached": True}

    try:
        profiles = []
        errors = []
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="sbb-tennis-ribbon") as pool:
            futures = {pool.submit(_fetch_scoreboard, tour, day): tour for tour in ("atp", "wta")}
            for future in as_completed(futures):
                tour = futures[future]
                try:
                    profiles.extend(_profiles_from_board(future.result(), tour))
                except Exception as exc:
                    errors.append(f"{tour}:{type(exc).__name__}:{exc}")
        saved = _STORE.upsert_profiles(profiles)
        try:
            today = datetime.now().date().isoformat()
            ttl = 30 * 24 * 60 * 60 if day < today else (15 * 60 if day == today else 2 * 60 * 60)
        except Exception:
            ttl = 15 * 60
        state = "READY" if profiles else ("PARTIAL" if not errors else "ERROR")
        if profiles and errors:
            state = "PARTIAL"
        _STORE.record_board(day, status=state, players=saved or len(profiles), ttl=(ttl if profiles else 5 * 60), error=" | ".join(errors))
        return {"state": state, "profiles": saved or len(profiles), "errors": errors}
    finally:
        with _WARM_LOCK:
            event = _WARMING.pop(day, None)
            if event:
                event.set()


def _team_country_code(team):
    if not isinstance(team, dict):
        return ""
    for value in (
        team.get("countryCode"), team.get("country"), team.get("nationalityCode"),
        team.get("nationality"), team.get("group"),
    ):
        code = _iso2(value)
        if code:
            return code
    return ""


def _project_team(team, stats):
    source = dict(team or {}) if isinstance(team, dict) else {"name": _clean(team), "displayName": _clean(team)}
    original_abbr = _clean(source.get("providerAbbreviation") or source.get("abbreviation") or source.get("abbr"))
    requested_name = _team_name(source)
    profile = _STORE.resolve(requested_name)
    if not profile and original_abbr and _norm(original_abbr) != _norm(requested_name):
        profile = _STORE.resolve(original_abbr)
    if profile:
        stats["tennisAliasHits"] += 1
    else:
        stats["tennisAliasMisses"] += 1

    canonical = _clean((profile or {}).get("canonical_name")) or requested_name
    rank_value = _rank(
        source.get("rank") or source.get("seed") or source.get("ranking")
        or ((source.get("curatedRank") or {}).get("current") if isinstance(source.get("curatedRank"), dict) else source.get("curatedRank"))
        or (profile or {}).get("rank")
    )
    short = _compact_name(canonical, rank_value) or _clean((profile or {}).get("short_name")) or original_abbr or canonical

    if canonical:
        source["canonicalName"] = canonical
        source["fullName"] = canonical
        source["name"] = canonical
        source["displayName"] = canonical
    if original_abbr and original_abbr != short:
        source["providerAbbreviation"] = original_abbr
    source["abbreviation"] = short
    source["shortName"] = short
    source["ribbonName"] = short
    if rank_value:
        source["rank"] = rank_value

    code = _clean((profile or {}).get("country_code")).lower() or _team_country_code(source)
    flag_url = _clean((profile or {}).get("flag_url"))
    if not flag_url and code:
        flag_url = f"https://flagcdn.com/w80/{code}.png"
    if code:
        source["countryCode"] = code.upper()
        source["flagEmoji"] = _flag_emoji(code)
    if flag_url:
        # Generic buildTeamRow already renders team.logo. A country flag therefore
        # appears on the very first card construction with zero tennis DOM patching.
        source["flagUrl"] = flag_url
        source["flagImage"] = flag_url
        source["logo"] = flag_url
        source["logoUrl"] = flag_url
        source["image"] = flag_url
        source["imageUrl"] = flag_url
        source["artworkType"] = "COUNTRY_FLAG"
        stats["tennisFlags"] += 1
    else:
        stats["tennisMissingFlags"] += 1

    aliases = []
    for value in [*(source.get("aliases") or []), requested_name, canonical, short, original_abbr]:
        if _clean(value) and _clean(value) not in aliases:
            aliases.append(_clean(value))
    source["aliases"] = aliases
    source["__sbbTennisPresentation"] = PROJECTION_VERSION
    return source


def _project_event(event, league, stats):
    out = dict(event or {})
    away_raw = out.get("awayTeam") if isinstance(out.get("awayTeam"), dict) else out.get("away")
    home_raw = out.get("homeTeam") if isinstance(out.get("homeTeam"), dict) else out.get("home")
    away = _project_team(away_raw or {}, stats)
    home = _project_team(home_raw or {}, stats)
    out["away"] = away
    out["home"] = home
    out["awayTeam"] = away
    out["homeTeam"] = home
    out["participants"] = [away, home]
    out["sportId"] = "tennis"
    out["__sbbTennisPresentation"] = PROJECTION_VERSION
    round_short = _round_short(
        out.get("tennisRoundShort") or out.get("displayRound") or out.get("roundName") or out.get("round") or out.get("stage")
    )
    if round_short:
        out["tennisRoundShort"] = round_short
    ribbon_label = _round_label(out, league)
    if ribbon_label:
        out["ribbonContextLabel"] = ribbon_label
        out["tennisRibbonLabel"] = ribbon_label
    stats["tennisPresentationRows"] += 1
    return out


def project_rows(day, rows_by_league, *, warm=False):
    """Return Day State rows already ready for generic score-card rendering."""
    source = rows_by_league or {}
    stats = {
        "tennisBackendProjectionVersion": PROJECTION_VERSION,
        "tennisPresentationRows": 0,
        "tennisAliasHits": 0,
        "tennisAliasMisses": 0,
        "tennisFlags": 0,
        "tennisMissingFlags": 0,
        "tennisWarmState": "NOT_NEEDED",
    }
    tennis_present = False
    projected = {}
    for league, rows in source.items():
        league_key = _clean(league).upper()
        values = []
        for event in rows or []:
            if isinstance(event, dict) and _is_tennis(league_key, event):
                tennis_present = True
                values.append(_project_event(event, league_key, stats))
            else:
                values.append(dict(event) if isinstance(event, dict) else event)
        projected[league] = values

    # The interactive/cold thin path passes warm=False and can only read SQLite.
    # The background/full Day State build may make one coalesced provider warm when
    # a visible tennis participant still lacks a flag/profile.
    if warm and tennis_present and stats["tennisMissingFlags"] > 0:
        warm_result = _warm_tennis_day(day)
        stats["tennisWarmState"] = _clean(warm_result.get("state")) or "UNKNOWN"
        if int(warm_result.get("profiles") or 0) > 0:
            # Re-project from the original rows after the alias DB has been updated.
            retry_stats = {
                "tennisBackendProjectionVersion": PROJECTION_VERSION,
                "tennisPresentationRows": 0,
                "tennisAliasHits": 0,
                "tennisAliasMisses": 0,
                "tennisFlags": 0,
                "tennisMissingFlags": 0,
                "tennisWarmState": stats["tennisWarmState"],
            }
            projected = {}
            for league, rows in source.items():
                league_key = _clean(league).upper()
                values = []
                for event in rows or []:
                    if isinstance(event, dict) and _is_tennis(league_key, event):
                        values.append(_project_event(event, league_key, retry_stats))
                    else:
                        values.append(dict(event) if isinstance(event, dict) else event)
                projected[league] = values
            stats = retry_stats
    elif tennis_present:
        stats["tennisWarmState"] = "CACHE_ONLY" if not warm else "READY_FROM_ALIAS_DB"
    return projected, stats


def _project_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return snapshot
    rows = snapshot.get("scoreRowsByLeague")
    if not isinstance(rows, dict):
        return snapshot
    projected, stats = project_rows(snapshot.get("date"), rows, warm=False)
    snapshot["scoreRowsByLeague"] = projected
    snapshot["tennisPresentationVersion"] = PROJECTION_VERSION
    diagnostics = dict(snapshot.get("projectionDiagnostics") or {})
    diagnostics.update(stats)
    diagnostics["tennisAliasStore"] = _STORE.status()
    snapshot["projectionDiagnostics"] = diagnostics
    return snapshot


def install():
    """Install one backend projection at Day State's canonical read-model boundary."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True

    original_catalog = day_state._catalog_score_rows_for_day
    original_merge = day_state._merge_future_catalog_rows
    original_put = day_state.DayStateStore.put
    original_get = day_state.DayStateStore.get

    def catalog_rows_for_day(server, day):
        rows, diagnostics = original_catalog(server, day)
        projected, tennis = project_rows(day, rows, warm=False)
        return projected, {**(diagnostics or {}), **tennis}

    def merge_catalog_rows(server, day, score_rows, today):
        rows, diagnostics = original_merge(server, day, score_rows, today)
        projected, tennis = project_rows(day, rows, warm=True)
        return projected, {**(diagnostics or {}), **tennis, "tennisAliasStore": _STORE.status()}

    def store_put(self, snapshot):
        return original_put(self, _project_snapshot(snapshot))

    def store_get(self, day):
        snapshot = original_get(self, day)
        if isinstance(snapshot, dict) and snapshot.get("tennisPresentationVersion") != PROJECTION_VERSION:
            _project_snapshot(snapshot)
        return snapshot

    catalog_rows_for_day.__sbbTennisBackendProjection = PROJECTION_VERSION
    merge_catalog_rows.__sbbTennisBackendProjection = PROJECTION_VERSION
    store_put.__sbbTennisBackendProjection = PROJECTION_VERSION
    store_get.__sbbTennisBackendProjection = PROJECTION_VERSION

    day_state._catalog_score_rows_for_day = catalog_rows_for_day
    day_state._merge_future_catalog_rows = merge_catalog_rows
    day_state.DayStateStore.put = store_put
    day_state.DayStateStore.get = store_get


def diagnostics():
    return {"version": PROJECTION_VERSION, "store": _STORE.status(), "installed": _INSTALLED}

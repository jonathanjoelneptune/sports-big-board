"""Media scope classification for Sports Big Board.

Scope is independent from recap quality. A league/day roundup can be excellent
media without being a recap for any one game. Only GAME-scoped assets are allowed
to participate in an individual game's Gold/Green/Purple/Blue ladder.
"""
import re
from datetime import datetime

GAME = "GAME"
DAY_LEAGUE = "DAY_LEAGUE"
WEEK_LEAGUE = "WEEK_LEAGUE"
PLAYER = "PLAYER"
SEASON_LEAGUE = "SEASON_LEAGUE"
OTHER = "OTHER"
COLLECTION_SCOPES = {DAY_LEAGUE, WEEK_LEAGUE, SEASON_LEAGUE}
VALID_SCOPES = {GAME, DAY_LEAGUE, WEEK_LEAGUE, PLAYER, SEASON_LEAGUE, OTHER}

ROUNDUP = "ROUNDUP"
TOP_PLAYS = "TOP_PLAYS"
WEEKLY_RECAP = "WEEKLY_RECAP"
DAILY_RECAP = "DAILY_RECAP"

_DAILY_ROUNDUP_RE = re.compile(
    r"\b(nightly recap|daily recap|daily highlights|nightly highlights|nightly roundup|daily roundup|"
    r"around the league|around the nba|around the nhl|around the mlb|all games|every game|"
    r"night in the nba|night in the nhl|night in baseball|what happened (?:today|tonight))\b",
    re.I,
)
_DAILY_RE = re.compile(
    r"\b(nightly recap|daily recap|daily highlights|nightly highlights|nightly roundup|daily roundup|"
    r"around the league|around the nba|around the nhl|around the mlb|all games|every game|"
    r"top\s*(?:10|5|plays?)|top plays?|plays? of the (?:day|night)|best plays?|best of the (?:day|night)|"
    r"night in the nba|night in the nhl|night in baseball|what happened (?:today|tonight))\b",
    re.I,
)
_WEEKLY_RE = re.compile(
    r"\b(?:week(?:ly)?\s*(?:\d{1,2})?\s*(?:recap|roundup|highlights?|top plays?)|"
    r"(?:recap|roundup|highlights?|top plays?)\s*(?:of\s*)?week\s*\d{1,2}|"
    r"every touchdown(?:s)?\s*(?:from|of)?\s*week\s*\d{1,2})\b",
    re.I,
)
_SEASON_RE = re.compile(r"\b(season recap|season highlights|month in review|monthly recap|playoffs recap|tournament recap)\b", re.I)
_TOP_PLAYS_RE = re.compile(r"\b(top\s*(?:10|5|plays?)|top plays?|plays? of the (?:day|night|week)|best plays?|best of the (?:day|night|week))\b", re.I)
_GAME_RE = re.compile(r"\b(full game highlights|game highlights|game recap|game summary|condensed game|full match highlights|match highlights|match recap)\b", re.I)


def _text(item):
    item = item or {}
    return " ".join(str(item.get(k) or "") for k in ("title", "subtitle", "description")).strip()


def _title(item):
    return str((item or {}).get("title") or "").strip()


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _aliases(name):
    text = _norm(name)
    if not text:
        return set()
    parts = text.split()
    out = {text}
    if parts:
        out.add(parts[-1])
    if len(parts) >= 2:
        out.add(" ".join(parts[-2:]))
    # A few common generic location/team words are too weak by themselves.
    return {x for x in out if len(x) >= 3 and x not in {"fc", "united", "city", "new", "los", "san"}}


def _mentions(text, team):
    hay = f" {_norm(text)} "
    return any(f" {alias} " in hay for alias in _aliases(team))


def collection_kind(item, scope=None):
    scope = str(scope or (item or {}).get("mediaScope") or "").upper()
    text = _text(item)
    if _TOP_PLAYS_RE.search(text):
        return TOP_PLAYS
    if scope == WEEK_LEAGUE:
        return WEEKLY_RECAP
    if scope == DAY_LEAGUE:
        return DAILY_RECAP
    return ROUNDUP


_MONTHS = {name.lower(): i for i, name in enumerate(("January","February","March","April","May","June","July","August","September","October","November","December"),1)}
_MONTHS.update({name[:3].lower(): i for name,i in list(_MONTHS.items())})


def day_key(item=None, date=""):
    text = _text(item or {})
    iso = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if iso:
        try: return f"{int(iso.group(1)):04d}-{int(iso.group(2)):02d}-{int(iso.group(3)):02d}"
        except Exception: pass
    named = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(20\d{2})\b", text, re.I)
    if named:
        month=_MONTHS.get(named.group(1).lower()) or _MONTHS.get(named.group(1)[:3].lower())
        if month:
            return f"{int(named.group(3)):04d}-{month:02d}-{int(named.group(2)):02d}"
    return str(date or (item or {}).get("date") or "")[:10]


def week_key(item=None, date=""):
    text = _text(item or {})
    m = re.search(r"\bweek\s*(\d{1,2})\b", text, re.I)
    year = str(date or (item or {}).get("date") or "")[:4]
    if m:
        return f"{year or 'unknown'}:W{int(m.group(1))}"
    try:
        d = datetime.fromisoformat(str(date or (item or {}).get("date") or "")[:10])
        iso = d.isocalendar()
        return f"{iso.year}:ISO-W{iso.week:02d}"
    except Exception:
        return f"{year or 'unknown'}:WEEK"


def classify(item, *, league="", date="", away="", home=""):
    item = item or {}
    explicit = str(item.get("mediaScope") or "").upper()
    if explicit in VALID_SCOPES:
        return explicit

    text = _text(item)
    title = _title(item)

    # Sporting-event identifiers are stronger than editorial wording. Generic
    # YouTube `eventId` is intentionally excluded because it is usually a video id.
    if any(item.get(k) not in (None, "") for k in ("scoreEventId", "matchId", "espnEventId", "canonicalEventId")):
        return GAME
    source_type = str(item.get("sourceType") or "").lower()
    if source_type in {"espn-event-video", "mlb-game-content", "nfl-event-video", "official-nfl-club-site"}:
        return GAME
    if item.get("gamePk") and "mlb" in str(item.get("sourceLabel") or item.get("source") or "").lower():
        return GAME

    # Explicit league-wide roundup language wins before matchup inference. A
    # nightly recap description can enumerate every game; descriptions are never
    # used as the two-team authority below.
    if _DAILY_ROUNDUP_RE.search(title):
        return DAY_LEAGUE
    if _SEASON_RE.search(title):
        return SEASON_LEAGUE

    # For generic channel/catalog media, require both opponents in the TITLE.
    if away and home and _mentions(title, away) and _mentions(title, home):
        return GAME
    ia = str(item.get("away") or item.get("awayTeamName") or "")
    ih = str(item.get("home") or item.get("homeTeamName") or "")
    if away and home and ia and ih and _mentions(ia, away) and _mentions(ih, home):
        return GAME

    # Once a specific game has failed to match, league/day/week editorial forms
    # become collection media. This keeps "Top plays Nets vs Lakers" game scoped
    # while "NBA Top 10 Plays" becomes Silver.
    if _WEEKLY_RE.search(text):
        return WEEK_LEAGUE
    if _DAILY_RE.search(text):
        return DAY_LEAGUE
    if _SEASON_RE.search(text):
        return SEASON_LEAGUE

    if _GAME_RE.search(title) and away and home:
        # A generic game-recap title without both target teams is not enough to
        # bind it to this event. It may be a different game from the same day.
        return OTHER

    if re.search(r"\b\d{2,3}[- ]?(?:pt|point)|double[- ]double|triple[- ]double|player highlights?\b", text, re.I):
        return PLAYER
    return OTHER


def annotate(item, *, league="", date="", away="", home=""):
    out = dict(item or {})
    scope = classify(out, league=league, date=date, away=away, home=home)
    out["mediaScope"] = scope
    if scope in COLLECTION_SCOPES:
        out["collectionTier"] = "silver"
        out["displayTier"] = "silver"
        out["collectionKind"] = collection_kind(out, scope)
        out["collectionPeriodKey"] = week_key(out, date) if scope == WEEK_LEAGUE else day_key(out, date)
    return out


def is_game(item, **kwargs):
    return classify(item, **kwargs) == GAME


def is_collection(item, **kwargs):
    return classify(item, **kwargs) in COLLECTION_SCOPES

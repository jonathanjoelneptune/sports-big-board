"""Media scope + intent classification for Sports Big Board v4.

Scope answers *what the media covers*. Intent answers *what kind of program it is*.
Neither is the game's Gold/Green/Purple/Blue quality tier. Only GAME-scoped media
may be associated to an individual sporting event; collection scopes render Silver.
"""
import re
from datetime import datetime
from .catalog_contract import (
    MEDIA_CLASSIFIER_VERSION,
    INTENT_RECAP, INTENT_CONDENSED_GAME, INTENT_EXTENDED_HIGHLIGHTS,
    INTENT_HIGHLIGHT, INTENT_TOP_PLAYS, INTENT_PLAYER_HIGHLIGHTS,
    INTENT_INTERVIEW, INTENT_ANALYSIS, INTENT_PRESS_CONFERENCE,
    INTENT_FULL_GAME, INTENT_OTHER,
)

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
    r"night in the nba|night in the nhl|night in baseball|what happened (?:today|tonight))\b", re.I)
_DAILY_RE = re.compile(
    r"\b(nightly recap|daily recap|daily highlights|nightly highlights|nightly roundup|daily roundup|"
    r"around the league|around the nba|around the nhl|around the mlb|all games|every game|"
    r"top\s*(?:10|5|plays?)|top plays?|plays? of the (?:day|night)|best plays?|best of the (?:day|night)|"
    r"night in the nba|night in the nhl|night in baseball|what happened (?:today|tonight))\b", re.I)
_WEEKLY_RE = re.compile(
    r"\b(?:week(?:ly)?\s*(?:\d{1,2})?\s*(?:recap|roundup|highlights?|top plays?)|"
    r"(?:recap|roundup|highlights?|top plays?)\s*(?:of\s*)?week\s*\d{1,2}|"
    r"every touchdown(?:s)?\s*(?:from|of)?\s*week\s*\d{1,2})\b", re.I)
_SEASON_RE = re.compile(r"\b(season recap|season highlights|month in review|monthly recap|playoffs recap|tournament recap)\b", re.I)
_TOP_PLAYS_RE = re.compile(r"\b(top\s*(?:10|5|plays?)|top plays?|plays? of the (?:day|night|week)|best plays?|best of the (?:day|night|week))\b", re.I)
_GAME_RE = re.compile(r"\b(full game highlights|game highlights|game recap|game summary|condensed game|full match highlights|match highlights|match recap)\b", re.I)


def _text(item):
    item = item or {}
    return " ".join(str(item.get(k) or "") for k in ("title", "subtitle", "description")).strip()


def _title(item): return str((item or {}).get("title") or "").strip()
def _norm(value): return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _aliases(name):
    text = _norm(name)
    if not text: return set()
    parts = text.split(); out = {text}
    if parts: out.add(parts[-1])
    if len(parts) >= 2: out.add(" ".join(parts[-2:]))
    return {x for x in out if len(x) >= 3 and x not in {"fc","united","city","new","los","san"}}


def _mentions(text, team):
    hay = f" {_norm(text)} "
    return any(f" {alias} " in hay for alias in _aliases(team))


def collection_kind(item, scope=None):
    scope = str(scope or (item or {}).get("mediaScope") or "").upper(); text = _text(item)
    if _TOP_PLAYS_RE.search(text): return TOP_PLAYS
    if scope == WEEK_LEAGUE: return WEEKLY_RECAP
    if scope == DAY_LEAGUE: return DAILY_RECAP
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
        if month: return f"{int(named.group(3)):04d}-{month:02d}-{int(named.group(2)):02d}"
    return str(date or (item or {}).get("date") or "")[:10]


def week_key(item=None, date=""):
    text = _text(item or {}); m = re.search(r"\bweek\s*(\d{1,2})\b", text, re.I)
    year = str(date or (item or {}).get("date") or "")[:4]
    if m: return f"{year or 'unknown'}:W{int(m.group(1))}"
    try:
        d = datetime.fromisoformat(str(date or (item or {}).get("date") or "")[:10]); iso = d.isocalendar()
        return f"{iso.year}:ISO-W{iso.week:02d}"
    except Exception: return f"{year or 'unknown'}:WEEK"


def classify_with_reason(item, *, league="", date="", away="", home=""):
    item = item or {}; explicit = str(item.get("mediaScope") or "").upper(); title = _title(item); text = _text(item)
    if explicit in VALID_SCOPES:
        return explicit, float(item.get("mediaScopeConfidence") or 1.0), str(item.get("mediaScopeReason") or "EXPLICIT_SCOPE")
    if any(item.get(k) not in (None, "") for k in ("scoreEventId","matchId","espnEventId","canonicalEventId")):
        return GAME, 1.0, "AUTHORITATIVE_EVENT_ID"
    source_type = str(item.get("sourceType") or "").lower()
    if source_type in {"espn-event-video","mlb-game-content","nfl-event-video","official-nfl-club-site"}:
        return GAME, 0.99, "AUTHORITATIVE_GAME_SOURCE"
    if item.get("gamePk") and "mlb" in str(item.get("sourceLabel") or item.get("source") or "").lower():
        return GAME, 0.99, "MLB_GAME_PK"
    if _DAILY_ROUNDUP_RE.search(title): return DAY_LEAGUE, 0.99, "DAILY_ROUNDUP_TITLE"
    if _SEASON_RE.search(title): return SEASON_LEAGUE, 0.98, "SEASON_ROUNDUP_TITLE"
    if away and home and _mentions(title, away) and _mentions(title, home): return GAME, 0.96, "TARGET_TEAM_PAIR_TITLE"
    ia=str(item.get("away") or item.get("awayTeamName") or ""); ih=str(item.get("home") or item.get("homeTeamName") or "")
    if away and home and ia and ih and _mentions(ia, away) and _mentions(ih, home): return GAME, 0.99, "TARGET_TEAM_PAIR_FIELDS"
    if _WEEKLY_RE.search(text): return WEEK_LEAGUE, 0.97, "WEEKLY_COLLECTION_LANGUAGE"
    if _DAILY_RE.search(text): return DAY_LEAGUE, 0.96, "DAILY_COLLECTION_LANGUAGE"
    if _SEASON_RE.search(text): return SEASON_LEAGUE, 0.96, "SEASON_COLLECTION_LANGUAGE"
    if _GAME_RE.search(title) and away and home: return OTHER, 0.90, "GAME_TITLE_MISSING_TARGET_PAIR"
    if _GAME_RE.search(title) and re.search(r"\b(?:vs\.?|versus|at)\b|@", title, re.I):
        return GAME, 0.90, "GENERIC_MATCHUP_TITLE"
    if re.search(r"\b\d{2,3}[- ]?(?:pt|point)|double[- ]double|triple[- ]double|player highlights?\b", text, re.I):
        return PLAYER, 0.94, "PLAYER_PACKAGE_LANGUAGE"
    return OTHER, 0.50, "NO_SCOPE_SIGNAL"


def classify(item, **kwargs): return classify_with_reason(item, **kwargs)[0]


def classify_intent(item, scope=None):
    text = _text(item); title = _title(item); scope = str(scope or (item or {}).get("mediaScope") or "").upper()
    if _TOP_PLAYS_RE.search(text): return INTENT_TOP_PLAYS, 0.99, "TOP_PLAYS_LANGUAGE"
    if re.search(r"\bpress conference|postgame presser|post-game presser\b", text, re.I): return INTENT_PRESS_CONFERENCE, 0.99, "PRESS_CONFERENCE_LANGUAGE"
    if re.search(r"\binterview|one-on-one|1-on-1\b", text, re.I): return INTENT_INTERVIEW, 0.95, "INTERVIEW_LANGUAGE"
    if re.search(r"\bfull game|full match|complete game\b", title, re.I) and not re.search(r"highlights", title, re.I): return INTENT_FULL_GAME, 0.96, "FULL_GAME_LANGUAGE"
    if re.search(r"\bcondensed game\b", text, re.I): return INTENT_CONDENSED_GAME, 0.99, "CONDENSED_GAME_LANGUAGE"
    if re.search(r"\bfull game highlights|full match highlights|extended highlights|extended recap\b", text, re.I): return INTENT_EXTENDED_HIGHLIGHTS, 0.98, "EXTENDED_HIGHLIGHTS_LANGUAGE"
    if scope == PLAYER or re.search(r"\bplayer highlights?\b|\b\d{2,3}[- ]?(?:pt|point)\b", text, re.I): return INTENT_PLAYER_HIGHLIGHTS, 0.94, "PLAYER_HIGHLIGHTS_LANGUAGE"
    if re.search(r"\bgame recap|game summary|match recap|nightly recap|daily recap|weekly recap|roundup|postgame recap\b", text, re.I): return INTENT_RECAP, 0.96, "RECAP_LANGUAGE"
    if re.search(r"\banalysis|breakdown|reaction|film room|takeaways\b", text, re.I): return INTENT_ANALYSIS, 0.90, "ANALYSIS_LANGUAGE"
    if re.search(r"\bhighlights?\b", text, re.I): return INTENT_HIGHLIGHT, 0.86, "HIGHLIGHT_LANGUAGE"
    return INTENT_OTHER, 0.50, "NO_INTENT_SIGNAL"


def annotate(item, *, league="", date="", away="", home=""):
    out = dict(item or {})
    scope, confidence, reason = classify_with_reason(out, league=league, date=date, away=away, home=home)
    out["mediaScope"] = scope; out["mediaScopeConfidence"] = round(float(confidence), 4)
    out["mediaScopeReason"] = reason; out["mediaClassifierVersion"] = MEDIA_CLASSIFIER_VERSION
    intent, iconf, ireason = classify_intent(out, scope)
    out["mediaIntent"] = intent; out["mediaIntentConfidence"] = round(float(iconf), 4); out["mediaIntentReason"] = ireason
    if scope in COLLECTION_SCOPES:
        out["collectionTier"] = "silver"; out["displayTier"] = "silver"; out["collectionKind"] = collection_kind(out, scope)
        out["collectionPeriodKey"] = week_key(out, date) if scope == WEEK_LEAGUE else day_key(out, date)
    return out


def is_game(item, **kwargs): return classify(item, **kwargs) == GAME
def is_collection(item, **kwargs): return classify(item, **kwargs) in COLLECTION_SCOPES

"""Media scope + Silver collection classification for Sports Big Board v4.1.22.

Scope answers *what the media covers*. Intent answers *what kind of program it is*.
Neither is the game's Gold/Green/Purple/Blue quality tier. Only GAME-scoped media
may be associated to an individual sporting event. Silver is intentionally narrower:
only high-confidence DAY_LEAGUE, WEEK_LEAGUE and ROUND_LEAGUE league-wide roundup programming is
promoted. Season/player/team features remain SOURCE_MEDIA but do not become Silver.
"""
import re
from datetime import datetime, timezone
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
ROUND_LEAGUE = "ROUND_LEAGUE"
PLAYER = "PLAYER"
SEASON_LEAGUE = "SEASON_LEAGUE"
OTHER = "OTHER"
# COLLECTION_SCOPES remains the broad taxonomy vocabulary for compatibility.
# SILVER_SCOPES is the actual v4.1.22 presentation/promotion contract.
COLLECTION_SCOPES = {DAY_LEAGUE, WEEK_LEAGUE, ROUND_LEAGUE, SEASON_LEAGUE}
SILVER_SCOPES = {DAY_LEAGUE, WEEK_LEAGUE, ROUND_LEAGUE}
VALID_SCOPES = {GAME, DAY_LEAGUE, WEEK_LEAGUE, ROUND_LEAGUE, PLAYER, SEASON_LEAGUE, OTHER}

ROUNDUP = "ROUNDUP"
TOP_PLAYS = "TOP_PLAYS"
WEEKLY_RECAP = "WEEKLY_RECAP"
DAILY_RECAP = "DAILY_RECAP"
SCORING_ROUNDUP = "SCORING_ROUNDUP"
BEST_GOALS = "BEST_GOALS"
BEST_SAVES = "BEST_SAVES"

# Strong collection language. v4.1.4's generic "best plays" / "top 10" rules were
# too broad and promoted player packages, historical features and ordinary game clips.
_DAILY_RECAP_TITLE_RE = re.compile(
    r"\b(nightly recap|daily recap|nightly roundup|daily roundup|daily highlights|nightly highlights|"
    r"around the (?:nba|nhl|mlb|nfl|league)|night in (?:the nba|the nhl|baseball)|"
    r"highlights? from all games|highlights? from every game|all games (?:recap|highlights?)|"
    r"what happened (?:today|tonight))\b", re.I)
_DAILY_TOP_TITLE_RE = re.compile(
    r"\b(?:nba(?:'s)?|nhl(?:'s)?|mlb(?:'s)?|nfl(?:'s)?|mls(?:'s)?|premier league(?:'s)?)?\s*"
    r"(?:top\s*(?:\d{1,2})?\s*plays?|plays? of the (?:day|night)|best of the (?:day|night))\b", re.I)
_DATED_LEAGUE_TOP_RE = re.compile(
    r"\b(?:top\s*(?:\d{1,2})?\s*(?:mlb|nba|nhl|nfl|mls)\s*plays?|top plays? in (?:mlb|nba|nhl|nfl|mls))\b", re.I)
_WEEKLY_RECAP_TITLE_RE = re.compile(
    r"\b(?:week\s*\d{1,2}\s*(?:recap|roundup|highlights?)|(?:recap|roundup|highlights?)\s*(?:of\s*)?week\s*\d{1,2})\b", re.I)
_WEEKLY_TOP_TITLE_RE = re.compile(
    r"\b(?:the\s+)?top\s*(?:\d{1,2})?\s*plays?\s*(?:of|from)?\s*week\s*\d{1,2}\b|"
    r"\bplays? of week\s*\d{1,2}\b|"
    r"\bevery\s+(?:team(?:'s|s')?\s+)?(?:best\s+play|touchdown)s?\s*(?:from|of)?\s*week\s*\d{1,2}\b", re.I)
_WEEKLY_CATEGORY_TOP_RE = re.compile(
    r"\btop\s+(?:goals?|saves?|plays?|hits?)\s+(?:from|of)\s+week\s*\d{1,2}\b", re.I)
_SEASON_RE = re.compile(r"\b(season recap|season highlights|month in review|monthly recap|playoffs recap|tournament recap)\b", re.I)
_TOP_PLAYS_RE = re.compile(r"\b(top\s*(?:\d{1,2})?\s*plays?|plays? of the (?:day|night|week)|best of the (?:day|night|week))\b", re.I)
_GAME_RE = re.compile(r"\b(full game highlights|game highlights|game recap|game summary|condensed game|full match highlights|match highlights|match recap)\b", re.I)
_WEEK_NUM_RE = re.compile(r"\bweek\s*(\d{1,2})\b", re.I)
_ROUND_NUM_RE = re.compile(r"\b(matchweek|mwk|matchday)\s*(\d{1,2})\b", re.I)
_SCORING_GOALS_PHRASE_RE = re.compile(r"\b(?:every|all(?:\s+of)?)\s+(?:the\s+)?(?:goal|touchdown)s?\b", re.I)
_SCORING_ROUNDUP_RE = re.compile(r"(?:\b(?:every|all(?:\s+of)?)\s+(?:the\s+)?(?:goal|touchdown)s?\b.*\b(?:matchweek|mwk|matchday|week)\s*\d{1,2}\b|\b(?:matchweek|mwk|matchday|week)\s*\d{1,2}\b.*\b(?:every|all(?:\s+of)?)\s+(?:the\s+)?(?:goal|touchdown)s?\b)", re.I)
_ROUND_TOP_RE = re.compile(r"\b(?:best|top)\s+(?:goals?|saves?|plays?)\s+(?:of|from)\s+(?:matchweek|mwk|matchday)\s*\d{1,2}\b|\bthings you may have missed in (?:matchweek|mwk|matchday)\s*\d{1,2}\b|\bmust[- ]see golazos?\b.*\bmatchday\s*\d{1,2}\b|\bwhat a save\b.*\bmatchday(?:s)?\s*\d{1,2}\b", re.I)
_BEST_GOALS_RE = re.compile(r"\b(?:best|top)\s+goals?\s+(?:of|from)\s+(?:matchweek|mwk|matchday|week)\s*\d{1,2}\b|\bmust[- ]see golazos?\b", re.I)
_BEST_SAVES_RE = re.compile(r"\b(?:best|top)\s+saves?\s+(?:of|from)\s+(?:matchweek|mwk|matchday|week)\s*\d{1,2}\b|\bwhat a save\b", re.I)
_NON_GAME_RECAP_PROGRAM_RE = re.compile(r"\b(?:post[- ]?game show|post[- ]?game live|instant reaction|reaction(?:s)?(?: to)?|reacts? to|analysis show|film room|podcast|press conference|presser|interview)\b",re.I)

# A title containing these signals is about a player/team/game/feature rather than a
# league-wide roundup unless an even stronger explicit roundup phrase proves otherwise.
_FEATURE_OR_NARROW_RE = re.compile(
    r"\b(?:vs\.?|versus|from\s+\d+[- ]?(?:td|pt|point|goal|yard)|series\s+(?:win|victory)|"
    r"first[- ]round|second[- ]round|conference finals?|finals? series|season highlights?|"
    r"career highlights?|all[- ]time|in .* history|history of|trade deadline|behind the scenes|"
    r"mic(?:'d|ed) up|interview|press conference|reaction|breakdown|film room|takeaways|"
    r"so far|reserve|rookie|player highlights?)\b", re.I)
_POSSESSIVE_BEST_RE = re.compile(r"\b[A-Za-z0-9.'’-]+(?:\s+[A-Za-z0-9.'’-]+){0,4}(?:'s|’s)\s+(?:best|top)\s+plays?\b", re.I)

_MONTHS = {name.lower(): i for i, name in enumerate(("January","February","March","April","May","June","July","August","September","October","November","December"),1)}
_MONTHS.update({name[:3].lower(): i for name,i in list(_MONTHS.items())})

_OFFICIAL_YOUTUBE_CHANNEL_IDS = {
    "MLB":"UCoLrcjPV5PbUrUyXq5mjc_A",
    "MLS":"UCSZbXT5TLLW_i-5W8FZpFsg",
    "NFL":"UCDVYQ4Zhbm3S2dlz7P1GBDg",
    "NBA":"UCWJ2lWNubArHWmf3FIHbfcQ",
    "NHL":"UCqFMzb-4AUf6WAIbl132QKA",
    "EPL":"UCG5qGWdu8nIRZqJ_GgDwQ-w",
}
_OFFICIAL_LEAGUE_LABELS = {
    "MLB":{"mlb","major league baseball"},
    "MLS":{"mls","major league soccer"},
    "NFL":{"nfl","national football league"},
    "NBA":{"nba","national basketball association"},
    "NHL":{"nhl","national hockey league"},
    "EPL":{"premier league","the premier league"},
}


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


def _parse_iso_date(value):
    text=str(value or "").strip()
    if not text: return ""
    try:
        dt=datetime.fromisoformat(text.replace("Z","+00:00"))
        return dt.date().isoformat()
    except Exception:
        m=re.match(r"^(20\d{2})-(\d{2})-(\d{2})",text)
        return m.group(0) if m else ""


def _explicit_day_from_title(item):
    text = _title(item); item=item or {}
    iso = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if iso:
        try: return f"{int(iso.group(1)):04d}-{int(iso.group(2)):02d}-{int(iso.group(3)):02d}"
        except Exception: pass
    # 8/21/26 and 08/21/2026 are common official-league title shapes.
    slash = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text)
    if slash:
        try:
            y=int(slash.group(3)); y=(2000+y if y<100 else y)
            return f"{y:04d}-{int(slash.group(1)):02d}-{int(slash.group(2)):02d}"
        except Exception: pass
    named = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(20\d{2})\b", text, re.I)
    if named:
        month=_MONTHS.get(named.group(1).lower()) or _MONTHS.get(named.group(1)[:3].lower())
        if month: return f"{int(named.group(3)):04d}-{month:02d}-{int(named.group(2)):02d}"
    # Official daily roundups often use compact month/day labels such as "8/21".
    # Infer only the year from publication/source chronology; the title still owns
    # the month/day so an upload on 8/22 can correctly cover the games from 8/21.
    ref=_parse_iso_date(item.get("publishedAt") or item.get("published") or item.get("date") or item.get("sourceDate"))
    if ref:
        try: ref_year=int(ref[:4])
        except Exception: ref_year=0
        short_slash=re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!/\d)(?!\d)",text)
        if short_slash and ref_year:
            try: return f"{ref_year:04d}-{int(short_slash.group(1)):02d}-{int(short_slash.group(2)):02d}"
            except Exception: pass
        short_named=re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?\b",text,re.I)
        if short_named and ref_year:
            month=_MONTHS.get(short_named.group(1).lower()) or _MONTHS.get(short_named.group(1)[:3].lower())
            if month: return f"{ref_year:04d}-{month:02d}-{int(short_named.group(2)):02d}"
    return ""


def day_key(item=None, date=""):
    """Resolve the *coverage* day, never merely the crawler encounter day.

    Explicit title dates win. Publication date is second because official roundup
    uploads commonly omit a date in the title. Discovery/source date is last resort.
    """
    item=item or {}
    explicit=_explicit_day_from_title(item)
    if explicit: return explicit
    published=_parse_iso_date(item.get("publishedAt") or item.get("published"))
    if published: return published
    return str(date or item.get("date") or "")[:10]


def season_id_for_date(league, date=""):
    league=str(league or "").upper()
    try: d=datetime.fromisoformat(str(date or "")[:10])
    except Exception: return "unknown"
    y=d.year; m=d.month
    if league in {"NBA","NHL","EPL"}:
        start=y if m>=7 else y-1
        return f"{start}-{str(start+1)[-2:]}"
    if league=="NFL":
        return str(y-1 if m<=2 else y)
    return str(y)


def explicit_season_id(item=None, league=""):
    text=_text(item or {}); league=str(league or (item or {}).get("league") or "").upper()
    m=re.search(r"\b(20\d{2})\s*[-–]\s*(\d{2,4})\s+(?:NBA|NHL|NFL|MLB|MLS|Premier League)?\s*Season\b",text,re.I)
    if m:
        start=int(m.group(1)); return f"{start}-{int(m.group(2))%100:02d}"
    m=re.search(r"\b(20\d{2})\s+(?:NBA|NHL|NFL|MLB|MLS|Premier League)?\s*Season\b",text,re.I)
    if m:
        y=int(m.group(1))
        if league in {"NBA","NHL","EPL"}: return f"{y}-{str(y+1)[-2:]}"
        return str(y)
    return ""


def season_id(item=None, league="", date=""):
    explicit=explicit_season_id(item,league)
    if explicit: return explicit
    text=_text(item or {})
    return season_id_for_date(league,date or day_key(item,date))


def week_key(item=None, date="", league=""):
    item=item or {}; text=_title(item); m=_WEEK_NUM_RE.search(text)
    sid=season_id(item,league=league or item.get("league"),date=date or item.get("date"))
    if m: return f"{sid}:W{int(m.group(1))}"
    # This fallback is for non-Silver callers only. Strict Silver weekly promotion
    # requires an explicit league-season Week N signal.
    try:
        d=datetime.fromisoformat(str(date or item.get("date") or "")[:10]); iso=d.isocalendar()
        return f"{iso.year}:ISO-W{iso.week:02d}"
    except Exception: return f"{sid}:WEEK"


def round_key(item=None, date="", league=""):
    """Canonical soccer round identity, separate from ISO/calendar weeks."""
    item=item or {}; title=_title(item); m=_ROUND_NUM_RE.search(title)
    sid=season_id(item,league=league or item.get("league"),date=date or item.get("date") or item.get("publishedAt"))
    if m:
        label=str(m.group(1) or "").lower(); prefix="MD" if label=="matchday" else "MW"; return f"{sid}:{prefix}{int(m.group(2))}"
    number,kind=_explicit_round_metadata(item)
    if number: return f"{sid}:{'MD' if kind=='MATCHDAY' else 'MW'}{number}"
    return f"{sid}:ROUND"


def source_authority(item, league=""):
    """Return source authority independently from title semantics.

    Official league feeds/channels are preferred Silver sources. Major broadcasters
    are allowed as a fallback only when roundup language is strong. Team/club and
    unknown publishers remain useful SOURCE_MEDIA but do not qualify as league-wide
    Silver by themselves.
    """
    item=item or {}; league=str(league or item.get("league") or "").upper()
    source_type=str(item.get("sourceType") or "").lower()
    channel_id=str(item.get("channelId") or item.get("officialChannelId") or "").strip()
    label=" ".join(str(item.get(k) or "") for k in ("channelName","channelTitle","sourceLabel","source","provider")).lower()
    expected_channel=_OFFICIAL_YOUTUBE_CHANNEL_IDS.get(league,"")
    if expected_channel and channel_id==expected_channel:
        return "LEAGUE_OFFICIAL",1.0,"VERIFIED_LEAGUE_CHANNEL_ID"
    if item.get("officialLeagueSource") is True or (item.get("officialChannelId") and (not expected_channel or str(item.get("officialChannelId"))==expected_channel)) or "official-league" in source_type or "official-channel" in source_type:
        return "LEAGUE_OFFICIAL",1.0,"OFFICIAL_LEAGUE_CHANNEL"
    if league=="MLB" and ("mlb stats" in label or source_type.startswith("mlb-") or re.search(r"\bmlb\b",label)):
        return "LEAGUE_OFFICIAL",0.99,"MLB_OFFICIAL_SOURCE"
    # Only exact known league publisher labels count as official when a verified
    # channel ID is unavailable.  Do not promote an arbitrary "NBA Highlights" or
    # "Official Sports" channel merely because its label starts with a league token.
    norm_label=_norm(label)
    if norm_label in {_norm(x) for x in _OFFICIAL_LEAGUE_LABELS.get(league,set())}:
        return "LEAGUE_OFFICIAL",0.97,"LEAGUE_CHANNEL_LABEL"
    if "official-team" in source_type or "official-nfl-club" in source_type or "club-site" in source_type:
        return "TEAM_OFFICIAL",0.92,"OFFICIAL_TEAM_SOURCE"
    if re.search(r"\bespn\b|sportscenter|fox sports|fs1|nbc sports|cbs sports|sportsnet|nba tv|nhl network|nfl network|mlb network|apple tv|mls season pass",label,re.I):
        return "TRUSTED_BROADCAST",0.90,"TRUSTED_BROADCAST_SOURCE"
    # A channel self-describing itself as "official" is not proof of league authority.
    # Keep it in SOURCE_MEDIA unless its verified ID, explicit league-source metadata,
    # exact league publisher label, or trusted broadcaster identity proves authority.
    return "UNKNOWN",0.35,"UNPROVEN_SOURCE_AUTHORITY"


def _narrow_title(title):
    title=str(title or "")
    return bool(_POSSESSIVE_BEST_RE.search(title) or _FEATURE_OR_NARROW_RE.search(title))


def _daily_collection_signal(item, league=""):
    title=_title(item)
    if not title or _narrow_title(title): return False,""
    explicit_day=_explicit_day_from_title(item)
    if _DAILY_RECAP_TITLE_RE.search(title): return True,"DAILY_ROUNDUP_TITLE"
    if _DAILY_TOP_TITLE_RE.search(title):
        # "Top Plays" alone is not enough. Require day/night semantics, explicit date,
        # or a league token in the title so player/team packages stay out of Silver.
        if re.search(r"of the (?:day|night)|best of the (?:day|night)",title,re.I) or explicit_day:
            return True,"DAILY_TOP_PLAYS_TITLE"
    if _DATED_LEAGUE_TOP_RE.search(title) and explicit_day:
        return True,"DATED_LEAGUE_TOP_PLAYS_TITLE"
    return False,""


def _weekly_collection_signal(item, league=""):
    title=_title(item)
    if not title or not _WEEK_NUM_RE.search(title) or _narrow_title(title): return False,""
    if _WEEKLY_TOP_TITLE_RE.search(title) or _WEEKLY_CATEGORY_TOP_RE.search(title): return True,"WEEKLY_TOP_PLAYS_TITLE"
    if _WEEKLY_RECAP_TITLE_RE.search(title): return True,"WEEKLY_RECAP_TITLE"
    return False,""


def _explicit_round_metadata(item):
    item=item or {}
    try: number=int(item.get("collectionRoundNumber") or 0)
    except Exception: number=0
    kind=str(item.get("collectionRoundType") or "MATCHWEEK").upper()
    if number>0 and kind in {"MATCHWEEK","MATCHDAY"}: return number,kind
    return 0,""

def _round_collection_signal(item, league=""):
    title=_title(item); league=str(league or (item or {}).get("league") or "").upper(); explicit_num,explicit_kind=_explicit_round_metadata(item)
    if league not in {"EPL","MLS"} or not title or _narrow_title(title): return False,""
    if _SCORING_ROUNDUP_RE.search(title): return True,"ROUND_SCORING_ROUNDUP_TITLE"
    # v4.1.22: a trusted playlist collector may have already resolved Matchweek N
    # from title+description (e.g. "Opening Weekend" + "Match Week 1"). Carry that
    # explicit round identity directly into Silver instead of rediscovering it by date.
    if explicit_num and _SCORING_GOALS_PHRASE_RE.search(_text(item)): return True,"EXPLICIT_ROUND_SCORING_ROUNDUP"
    if _ROUND_TOP_RE.search(title): return True,"ROUND_TOP_PLAYS_TITLE"
    return False,""


def collection_kind(item, scope=None):
    scope=str(scope or (item or {}).get("mediaScope") or "").upper(); title=_title(item)
    if scope in SILVER_SCOPES and _BEST_GOALS_RE.search(title): return BEST_GOALS
    if scope in SILVER_SCOPES and _BEST_SAVES_RE.search(title): return BEST_SAVES
    if _SCORING_ROUNDUP_RE.search(title) or (_explicit_round_metadata(item)[0] and _SCORING_GOALS_PHRASE_RE.search(_text(item))): return SCORING_ROUNDUP
    if scope==WEEK_LEAGUE and (_WEEKLY_TOP_TITLE_RE.search(title) or _WEEKLY_CATEGORY_TOP_RE.search(title)): return TOP_PLAYS
    if scope==ROUND_LEAGUE and _ROUND_TOP_RE.search(title): return TOP_PLAYS
    if scope==DAY_LEAGUE and (_DAILY_TOP_TITLE_RE.search(title) or _DATED_LEAGUE_TOP_RE.search(title)): return TOP_PLAYS
    if scope==WEEK_LEAGUE: return WEEKLY_RECAP
    if scope==DAY_LEAGUE: return DAILY_RECAP
    return ROUNDUP

def classify_with_reason(item, *, league="", date="", away="", home=""):
    item=item or {}; explicit=str(item.get("mediaScope") or "").upper(); title=_title(item); text=_text(item)
    if explicit in VALID_SCOPES:
        return explicit,float(item.get("mediaScopeConfidence") or 1.0),str(item.get("mediaScopeReason") or "EXPLICIT_SCOPE")
    # v4.1.22: studio/reaction/postgame-show programming can remain in SOURCE_MEDIA,
    # but may not become GAME media merely because a provider endpoint was event-scoped.
    if _NON_GAME_RECAP_PROGRAM_RE.search(text) and not re.search(r"\b(?:full game highlights|game highlights|full match highlights|match highlights|condensed game|extended highlights)\b",text,re.I):
        return OTHER,0.995,"NON_GAME_POSTGAME_OR_REACTION_PROGRAM"
    if any(item.get(k) not in (None, "") for k in ("scoreEventId","matchId","espnEventId","canonicalEventId")):
        return GAME,1.0,"AUTHORITATIVE_EVENT_ID"
    source_type=str(item.get("sourceType") or "").lower()
    if source_type in {"espn-event-video","mlb-game-content","nfl-event-video","official-nfl-club-site",
                        "official-nhl-game-recap","official-nhl-condensed-game","official-mls-match-snapshot","official-mls-match-highlights",
                        "official-premierleague-match-highlights","trusted-nbc-epl-extended","official-premierleague-youtube-highlights","trusted-nbc-epl-youtube-highlights","official-nfl-game-highlights","official-nfl-extended-highlights","official-nfl-public-video","official-nfl-team-video","official-nfl-youtube-playlist"}:
        return GAME,0.99,"AUTHORITATIVE_GAME_SOURCE"
    if item.get("gamePk") and "mlb" in str(item.get("sourceLabel") or item.get("source") or "").lower():
        return GAME,0.99,"MLB_GAME_PK"
    if away and home and _mentions(title,away) and _mentions(title,home): return GAME,0.96,"TARGET_TEAM_PAIR_TITLE"
    ia=str(item.get("away") or item.get("awayTeamName") or ""); ih=str(item.get("home") or item.get("homeTeamName") or "")
    if away and home and ia and ih and _mentions(ia,away) and _mentions(ih,home): return GAME,0.99,"TARGET_TEAM_PAIR_FIELDS"
    round_signal,rr=_round_collection_signal(item,league)
    if round_signal: return ROUND_LEAGUE,0.995,rr
    daily,dr=_daily_collection_signal(item,league)
    if daily: return DAY_LEAGUE,0.995,dr
    weekly,wr=_weekly_collection_signal(item,league)
    if weekly: return WEEK_LEAGUE,0.995,wr
    if _SEASON_RE.search(title): return SEASON_LEAGUE,0.98,"SEASON_ROUNDUP_TITLE"
    if _GAME_RE.search(title) and away and home: return OTHER,0.90,"GAME_TITLE_MISSING_TARGET_PAIR"
    if _GAME_RE.search(title) and re.search(r"\b(?:vs\.?|versus|at)\b|@",title,re.I): return GAME,0.90,"GENERIC_MATCHUP_TITLE"
    if re.search(r"\b\d{2,3}[- ]?(?:pt|point)|double[- ]double|triple[- ]double|player highlights?\b",text,re.I) or _POSSESSIVE_BEST_RE.search(title):
        return PLAYER,0.94,"PLAYER_PACKAGE_LANGUAGE"
    if _SEASON_RE.search(text): return SEASON_LEAGUE,0.90,"SEASON_FEATURE_LANGUAGE"
    return OTHER,0.50,"NO_SCOPE_SIGNAL"

def classify(item, **kwargs): return classify_with_reason(item, **kwargs)[0]


def classify_intent(item, scope=None):
    text=_text(item); title=_title(item); scope=str(scope or (item or {}).get("mediaScope") or "").upper()
    if scope in SILVER_SCOPES and collection_kind(item,scope) in {TOP_PLAYS,BEST_GOALS,BEST_SAVES}: return INTENT_TOP_PLAYS,0.99,"TOP_PLAYS_LANGUAGE"
    if re.search(r"\bpress conference|postgame presser|post-game presser\b",text,re.I): return INTENT_PRESS_CONFERENCE,0.99,"PRESS_CONFERENCE_LANGUAGE"
    if re.search(r"\binterview|one-on-one|1-on-1\b",text,re.I): return INTENT_INTERVIEW,0.95,"INTERVIEW_LANGUAGE"
    if _NON_GAME_RECAP_PROGRAM_RE.search(text): return INTENT_ANALYSIS,0.98,"NON_GAME_ANALYSIS_PROGRAM"
    if re.search(r"\bfull game|full match|complete game\b",title,re.I) and not re.search(r"highlights",title,re.I): return INTENT_FULL_GAME,0.96,"FULL_GAME_LANGUAGE"
    if re.search(r"\bcondensed game\b",text,re.I): return INTENT_CONDENSED_GAME,0.99,"CONDENSED_GAME_LANGUAGE"
    if re.search(r"\bfull game highlights|full match highlights|extended highlights|extended recap\b",text,re.I): return INTENT_EXTENDED_HIGHLIGHTS,0.98,"EXTENDED_HIGHLIGHTS_LANGUAGE"
    if scope==PLAYER or re.search(r"\bplayer highlights?\b|\b\d{2,3}[- ]?(?:pt|point)\b",text,re.I): return INTENT_PLAYER_HIGHLIGHTS,0.94,"PLAYER_HIGHLIGHTS_LANGUAGE"
    if scope in SILVER_SCOPES or re.search(r"\bgame recap|game summary|match recap|nightly recap|daily recap|weekly recap|roundup|postgame recap\b",text,re.I): return INTENT_RECAP,0.96,"RECAP_LANGUAGE"
    if re.search(r"\banalysis|breakdown|reaction|film room|takeaways\b",text,re.I): return INTENT_ANALYSIS,0.90,"ANALYSIS_LANGUAGE"
    if re.search(r"\bhighlights?\b",text,re.I): return INTENT_HIGHLIGHT,0.86,"HIGHLIGHT_LANGUAGE"
    return INTENT_OTHER,0.50,"NO_INTENT_SIGNAL"

def silver_eligibility(item, *, league="", date=""):
    """Return a strict Silver promotion decision and canonical collection identity."""
    # Never trust stale/explicit classifier fields for Silver promotion. The strict
    # v5 classifier must independently prove the collection semantics each time.
    base=strip_classifier_fields(item or {})
    scope,confidence,reason=classify_with_reason(base,league=league,date=date)
    authority,authority_conf,authority_reason=source_authority(base,league)
    result={
        "eligible":False,"scope":scope,"scopeConfidence":float(confidence),"scopeReason":reason,
        "sourceAuthority":authority,"sourceAuthorityConfidence":authority_conf,"sourceAuthorityReason":authority_reason,
        "periodKey":"","collectionKind":collection_kind(base,scope),"reason":"",
    }
    if scope not in SILVER_SCOPES:
        result["reason"]="NOT_SILVER_SCOPE"; return result
    if authority not in {"LEAGUE_OFFICIAL","TRUSTED_BROADCAST"}:
        result["reason"]="SOURCE_NOT_LEAGUE_WIDE_AUTHORITY"; return result
    if scope==DAY_LEAGUE:
        ok,_=_daily_collection_signal(base,league)
        if not ok: result["reason"]="WEAK_DAILY_COLLECTION_SEMANTICS"; return result
        if not (_explicit_day_from_title(base) or _parse_iso_date(base.get("publishedAt") or base.get("published"))):
            result["reason"]="UNRESOLVED_DAILY_PERIOD"; return result
        period=day_key(base,date)
        if not re.match(r"^20\d{2}-\d{2}-\d{2}$",period): result["reason"]="UNRESOLVED_DAILY_PERIOD"; return result
    elif scope==WEEK_LEAGUE:
        ok,_=_weekly_collection_signal(base,league)
        if not ok: result["reason"]="WEAK_WEEKLY_COLLECTION_SEMANTICS"; return result
        if not explicit_season_id(base,league): result["reason"]="UNRESOLVED_SEASON_ID"; return result
        period=week_key(base,date,league)
        if ":W" not in period or period.endswith(":WEEK"): result["reason"]="UNRESOLVED_SEASON_WEEK"; return result
    else:
        ok,_=_round_collection_signal(base,league)
        if not ok: result["reason"]="WEAK_ROUND_COLLECTION_SEMANTICS"; return result
        period=round_key(base,date,league)
        if not re.search(r":(?:MW|MD)\d{1,2}$",period): result["reason"]="UNRESOLVED_LEAGUE_ROUND"; return result
    result.update({"eligible":True,"periodKey":period,"reason":"SILVER_PROMOTION_APPROVED"})
    return result


def annotate(item, *, league="", date="", away="", home=""):
    out=dict(item or {})
    scope,confidence,reason=classify_with_reason(out,league=league,date=date,away=away,home=home)
    out["mediaScope"]=scope; out["mediaScopeConfidence"]=round(float(confidence),4)
    out["mediaScopeReason"]=reason; out["mediaClassifierVersion"]=MEDIA_CLASSIFIER_VERSION
    intent,iconf,ireason=classify_intent(out,scope)
    out["mediaIntent"]=intent; out["mediaIntentConfidence"]=round(float(iconf),4); out["mediaIntentReason"]=ireason
    authority,aconf,areason=source_authority(out,league)
    out["sourceAuthority"]=authority; out["sourceAuthorityConfidence"]=round(float(aconf),4); out["sourceAuthorityReason"]=areason
    if scope in SILVER_SCOPES:
        decision=silver_eligibility(out,league=league,date=date)
        if decision.get("eligible"):
            out["collectionTier"]="silver"; out["displayTier"]="silver"; out["collectionKind"]=decision["collectionKind"]
            out["collectionPeriodKey"]=decision["periodKey"]
            out["collectionPromotionApproved"]=True; out["collectionPromotionReason"]=decision["reason"]
            if scope==WEEK_LEAGUE:
                out["collectionSeasonId"]=season_id(out,league,date); m=_WEEK_NUM_RE.search(_title(out)); out["collectionSeasonWeek"]=int(m.group(1)) if m else 0
            elif scope==ROUND_LEAGUE:
                out["collectionSeasonId"]=season_id(out,league,date); m=_ROUND_NUM_RE.search(_title(out)); explicit_num,explicit_kind=_explicit_round_metadata(out); out["collectionRoundNumber"]=int(m.group(2)) if m else explicit_num; out["collectionRoundType"]=("MATCHDAY" if m and str(m.group(1)).lower()=="matchday" else (explicit_kind or "MATCHWEEK"))
        else:
            out["collectionPromotionApproved"]=False; out["collectionPromotionReason"]=decision.get("reason") or "SILVER_PROMOTION_REJECTED"
    return out


def strip_classifier_fields(item):
    out=dict(item or {})
    for key in (
        "mediaScope","mediaScopeConfidence","mediaScopeReason","mediaIntent","mediaIntentConfidence","mediaIntentReason","mediaClassifierVersion",
        "collectionTier","displayTier","collectionKind","collectionPeriodKey","collectionPromotionApproved","collectionPromotionReason","collectionSeasonId","collectionSeasonWeek",
        "sourceAuthority","sourceAuthorityConfidence","sourceAuthorityReason",
    ):
        out.pop(key,None)
    return out


def is_game(item, **kwargs): return classify(item, **kwargs)==GAME
def is_collection(item, **kwargs): return classify(item, **kwargs) in COLLECTION_SCOPES
def is_silver(item, **kwargs):
    league=kwargs.pop("league",""); date=kwargs.pop("date","")
    return bool(silver_eligibility(strip_classifier_fields(item),league=league,date=date).get("eligible"))

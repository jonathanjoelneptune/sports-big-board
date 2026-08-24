"""Evidence-based media-to-event association for the v4 historical catalog.

v4.1.0 is deliberately fail-closed. Source media may be broad/ambiguous, but an
EVENT_MEDIA relationship must prove one canonical sporting event. Matchup-title,
calendar/season, and provider-id conflicts are evaluated before positive provider
identity so a stale or over-broad provider adapter cannot launder the wrong asset
into a game merely by stamping the current event id onto it.
"""
import re
from datetime import datetime
from .catalog_contract import EVENT_MATCHER_VERSION, ASSIGNED, QUARANTINED
from .media_scope import GAME

_GENERIC = {"fc","united","city","new","los","san","club","the","cf","sc"}
_MONTHS = {name.lower(): i for i, name in enumerate(("January","February","March","April","May","June","July","August","September","October","November","December"),1)}
_MONTHS.update({name[:3].lower(): i for name,i in list(_MONTHS.items())})
_MATCHUP_MARKER = re.compile(r"(?:\bvs\.?\b|\bversus\b|\s@\s)", re.I)


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def team_name(event, side):
    event = event if isinstance(event, dict) else {}
    value = event.get(f"{side}Team") or event.get(side) or event.get(f"{side}TeamName") or ""
    if isinstance(value, dict):
        return str(value.get("displayName") or value.get("name") or value.get("shortName") or value.get("abbreviation") or value.get("abbr") or "").strip()
    return str(value or "").strip()


def aliases(name):
    text = _norm(name)
    if not text: return set()
    words = text.split(); out = {text}
    # Keep club/location tokens useful without allowing generic suffixes such as
    # FC/United/City to become proof by themselves.
    if words and words[-1] not in _GENERIC and len(words[-1])>=4: out.add(words[-1])
    if len(words) >= 2: out.add(" ".join(words[-2:]))
    if len(words) >= 3: out.add(" ".join(words[-3:]))
    meaningful=[w for w in words if w not in _GENERIC and len(w)>=4]
    if len(meaningful)==1: out.add(meaningful[0])
    return {x for x in out if len(x)>=3 and x not in _GENERIC}


def mentions(text, name):
    hay=f" {_norm(text)} "
    return any(f" {alias} " in hay for alias in aliases(name))


def event_ids(item):
    item=item if isinstance(item,dict) else {}
    return {str(item.get(k)) for k in ("scoreEventId","matchId","espnEventId","canonicalEventId") if item.get(k) not in (None,"")}


def _text(item):
    item=item if isinstance(item,dict) else {}
    return " ".join(str(item.get(k) or "") for k in ("title","subtitle","description"))


def _explicit_dates(item):
    """Dates explicitly written in source text; never synthesize from target date."""
    text=str((item or {}).get("title") or ""); out=set()
    for y,m,d in re.findall(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b",text):
        try: out.add(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")
        except Exception: pass
    pat=r"\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(20\d{2})\b"
    for mon,d,y in re.findall(pat,text,re.I):
        month=_MONTHS.get(mon.lower()) or _MONTHS.get(mon[:3].lower())
        if month:
            try: out.add(f"{int(y):04d}-{month:02d}-{int(d):02d}")
            except Exception: pass
    return out


def _explicit_years(item):
    return {int(x) for x in re.findall(r"\b(20\d{2})\b",str((item or {}).get("title") or ""))}


def _date_conflict(item, event_date, league, pair_proven=False):
    if not event_date: return None
    dates=_explicit_dates(item)
    # Sports titles often say "August 21" and put the year elsewhere (or omit it).
    # Resolve month/day against the event year only for conflict checking.
    text=str((item or {}).get("title") or "")
    try: event_year=int(str(event_date)[:4])
    except Exception: event_year=0
    pat=r"\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?\b"
    if event_year:
        for mon,d in re.findall(pat,text,re.I):
            month=_MONTHS.get(mon.lower()) or _MONTHS.get(mon[:3].lower())
            if month:
                try: dates.add(f"{event_year:04d}-{month:02d}-{int(d):02d}")
                except Exception: pass
    if not dates: return None
    if event_date in dates: return None
    # MLB series routinely repeat the same matchup on consecutive dates. An
    # explicit title date is therefore authoritative and must match exactly.
    if str(league or "").upper()=="MLB":
        return f"media dates={sorted(dates)} event={event_date}"
    # Other providers sometimes stamp publication date one day after a late game.
    # Permit that only when the exact opponent pair itself is proven.
    try:
        target=datetime.strptime(event_date,"%Y-%m-%d").date()
        if pair_proven and min(abs((datetime.strptime(x,"%Y-%m-%d").date()-target).days) for x in dates)<=1:
            return None
    except Exception: pass
    return f"media dates={sorted(dates)} event={event_date}"


def _season_conflict(item,event_date):
    if not event_date: return None
    try: year=int(str(event_date)[:4])
    except Exception: return None
    years=_explicit_years(item)
    if years and year not in years:
        return f"media years={sorted(years)} eventYear={year}"
    return None


def match_event(item,event,*,league="",date=""):
    """Return durable association evidence. Only ASSIGNED may affect game coverage."""
    item=item if isinstance(item,dict) else {}; event=event if isinstance(event,dict) else {}
    scope=str(item.get("mediaScope") or "").upper(); away,home=team_name(event,"away"),team_name(event,"home")
    event_date=str(date or event.get("date") or event.get("eventDate") or "")[:10]
    title=str(item.get("title") or ""); text=_text(item)
    pair_title=bool(away and home and mentions(title,away) and mentions(title,home))
    matchup_title=bool(_MATCHUP_MARKER.search(title) or (re.search(r"\bat\b",title,re.I) and re.search(r"\b(?:full game|full match|game highlights?|match highlights?|game recap|match recap)\b",title,re.I)))
    item_away=str(item.get("away") or item.get("awayTeamName") or ""); item_home=str(item.get("home") or item.get("homeTeamName") or "")
    pair_fields=bool(away and home and item_away and item_home and aliases(item_away)&aliases(away) and aliases(item_home)&aliases(home))
    pair_proven=pair_title or pair_fields

    base={"matcherVersion":EVENT_MATCHER_VERSION,"associationState":QUARANTINED,"associationConfidence":0.0,"associationMethod":"NO_MATCH","associationEvidence":""}
    if scope!=GAME:
        base.update(associationMethod="NON_GAME_SCOPE",associationEvidence=f"mediaScope={scope or 'UNKNOWN'}"); return base

    # Explicit conflicting metadata always defeats a copied/stale provider id.
    season_conflict=_season_conflict(item,event_date)
    if season_conflict:
        base.update(associationMethod="SEASON_MISMATCH",associationEvidence=season_conflict); return base
    date_conflict=_date_conflict(item,event_date,league,pair_proven=pair_proven)
    if date_conflict:
        base.update(associationMethod="DATE_MISMATCH",associationEvidence=date_conflict); return base
    if matchup_title and away and home and not pair_title:
        base.update(associationMethod="TITLE_TEAM_PAIR_CONFLICT",associationEvidence=f"matchup title does not prove {away} + {home}: {title[:240]}"); return base
    if item_away and item_home and away and home and not pair_fields:
        base.update(associationMethod="TEAM_FIELD_CONFLICT",associationEvidence=f"media={item_away} @ {item_home}; event={away} @ {home}"); return base

    target_ids=event_ids(event)
    for key in ("id","eventId"):
        if event.get(key) not in (None,""): target_ids.add(str(event.get(key)))
    item_ids=event_ids(item)
    if item_ids and target_ids:
        overlap=sorted(item_ids & target_ids)
        if overlap:
            base.update(associationState=ASSIGNED,associationConfidence=1.0,associationMethod="PROVIDER_EVENT_ID",associationEvidence="event id="+overlap[0]); return base
        base.update(associationMethod="CONFLICTING_EVENT_ID",associationEvidence=f"media={sorted(item_ids)} event={sorted(target_ids)}"); return base

    if item.get("gamePk") not in (None,"") and event.get("gamePk") not in (None,""):
        if str(item.get("gamePk"))==str(event.get("gamePk")):
            base.update(associationState=ASSIGNED,associationConfidence=1.0,associationMethod="PROVIDER_GAME_PK",associationEvidence=f"gamePk={item.get('gamePk')}")
        else:
            base.update(associationMethod="CONFLICTING_GAME_PK",associationEvidence=f"media={item.get('gamePk')} event={event.get('gamePk')}")
        return base

    if pair_fields:
        base.update(associationState=ASSIGNED,associationConfidence=0.99,associationMethod="EXACT_TEAM_PAIR_FIELDS",associationEvidence=f"{item_away} @ {item_home}"); return base
    if pair_title:
        base.update(associationState=ASSIGNED,associationConfidence=0.96,associationMethod="EXACT_TEAM_PAIR_TITLE",associationEvidence=f"title mentions {away} + {home}"); return base

    source_type=str(item.get("sourceType") or "").lower()
    if source_type in {"espn-event-video","mlb-game-content","nfl-event-video","official-nfl-club-site"} and target_ids and item.get("sourceEventId"):
        if str(item.get("sourceEventId")) in target_ids:
            base.update(associationState=ASSIGNED,associationConfidence=1.0,associationMethod="PROVIDER_SOURCE_EVENT_ID",associationEvidence=f"sourceEventId={item.get('sourceEventId')}"); return base

    base.update(associationMethod="UNPROVEN_GAME_ASSOCIATION",associationEvidence=f"could not prove {away} @ {home} from title/provider ids")
    return base

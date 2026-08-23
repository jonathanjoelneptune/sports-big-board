"""Evidence-based media-to-event association for the v4 historical catalog."""
import re
from .catalog_contract import EVENT_MATCHER_VERSION, ASSIGNED, QUARANTINED
from .media_scope import GAME

_GENERIC = {"fc","united","city","new","los","san","club","the","cf","sc"}


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
    if not text:
        return set()
    words = text.split()
    out = {text}
    if words:
        out.add(words[-1])
    if len(words) >= 2:
        out.add(" ".join(words[-2:]))
    if len(words) >= 3:
        out.add(" ".join(words[-3:]))
    return {x for x in out if len(x) >= 3 and x not in _GENERIC}


def mentions(text, name):
    hay = f" {_norm(text)} "
    return any(f" {alias} " in hay for alias in aliases(name))


def event_ids(item):
    item = item if isinstance(item, dict) else {}
    return {str(item.get(k)) for k in ("scoreEventId","matchId","espnEventId","canonicalEventId") if item.get(k) not in (None, "")}


def match_event(item, event, *, league="", date=""):
    """Return durable association evidence.

    `state=ASSIGNED` is the only result allowed to affect game coverage. A GAME
    scoped asset that cannot prove membership is quarantined instead of deleted.
    """
    item = item if isinstance(item, dict) else {}
    event = event if isinstance(event, dict) else {}
    scope = str(item.get("mediaScope") or "").upper()
    away, home = team_name(event, "away"), team_name(event, "home")
    target_ids = event_ids(event)
    for key in ("id", "eventId"):
        if event.get(key) not in (None, ""):
            target_ids.add(str(event.get(key)))
    item_ids = event_ids(item)

    base = {
        "matcherVersion": EVENT_MATCHER_VERSION,
        "associationState": QUARANTINED,
        "associationConfidence": 0.0,
        "associationMethod": "NO_MATCH",
        "associationEvidence": "",
    }
    if scope != GAME:
        base.update(associationMethod="NON_GAME_SCOPE", associationEvidence=f"mediaScope={scope or 'UNKNOWN'}")
        return base

    if item_ids and target_ids:
        overlap = sorted(item_ids & target_ids)
        if overlap:
            base.update(associationState=ASSIGNED, associationConfidence=1.0,
                        associationMethod="PROVIDER_EVENT_ID", associationEvidence="event id=" + overlap[0])
            return base
        # IDs from the same identity family conflict. This is stronger than title.
        base.update(associationMethod="CONFLICTING_EVENT_ID",
                    associationEvidence=f"media={sorted(item_ids)} event={sorted(target_ids)}")
        return base

    if item.get("gamePk") not in (None, "") and event.get("gamePk") not in (None, ""):
        if str(item.get("gamePk")) == str(event.get("gamePk")):
            base.update(associationState=ASSIGNED, associationConfidence=1.0,
                        associationMethod="PROVIDER_GAME_PK", associationEvidence=f"gamePk={item.get('gamePk')}")
        else:
            base.update(associationMethod="CONFLICTING_GAME_PK",
                        associationEvidence=f"media={item.get('gamePk')} event={event.get('gamePk')}")
        return base

    item_away = str(item.get("away") or item.get("awayTeamName") or "")
    item_home = str(item.get("home") or item.get("homeTeamName") or "")
    if away and home and item_away and item_home:
        if aliases(item_away) & aliases(away) and aliases(item_home) & aliases(home):
            base.update(associationState=ASSIGNED, associationConfidence=0.99,
                        associationMethod="EXACT_TEAM_PAIR_FIELDS",
                        associationEvidence=f"{item_away} @ {item_home}")
            return base

    title = str(item.get("title") or "")
    if away and home and mentions(title, away) and mentions(title, home):
        base.update(associationState=ASSIGNED, associationConfidence=0.96,
                    associationMethod="EXACT_TEAM_PAIR_TITLE",
                    associationEvidence=f"title mentions {away} + {home}")
        return base

    source_type = str(item.get("sourceType") or "").lower()
    # Provider-specific game lanes can omit both club names from a result-story
    # title. They are accepted only when the event's canonical provider id has
    # already been copied into the source row by that provider adapter.
    if source_type in {"espn-event-video","mlb-game-content","nfl-event-video","official-nfl-club-site"} and target_ids and item.get("sourceEventId"):
        if str(item.get("sourceEventId")) in target_ids:
            base.update(associationState=ASSIGNED, associationConfidence=1.0,
                        associationMethod="PROVIDER_SOURCE_EVENT_ID",
                        associationEvidence=f"sourceEventId={item.get('sourceEventId')}")
            return base

    base.update(associationMethod="UNPROVEN_GAME_ASSOCIATION",
                associationEvidence=f"could not prove {away} @ {home} from title/provider ids")
    return base

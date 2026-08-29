"""Sports Big Board v4.6.14 — media-facing participant alias resolution.

The v4.6.13 tournament-wide crawler proved that LLWS playlist ingestion was healthy,
but 2026 LLWS media titles use public-facing geographic identities (Alabama, Ohio,
Nicaragua, Czechia, Japan, PA/NJ, etc.) while the schedule intentionally stores the
actual Little League club plus richer location metadata (Phenix City, Alabama;
West Side LL / Hamilton, Ohio; South Czech Republic LL / Brno, Czechia).

v4.6.14 converts those imported identities into deterministic media aliases and
performs a direct two-sided "<team> vs <team>" title match before falling back to
the generic event matcher. This remains generic for future special events.

No schedule rows, canonical event IDs, source-media assets, or existing EVENT_MEDIA
relationships are rewritten.
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata

from . import competition_builder as base
from . import competition_builder_v4612 as rules
from . import competition_builder_v4613 as tournament

_INSTALLED = False
_INSTALL_LOCK = threading.Lock()
_ORIGINAL_PARTICIPANT_ALIASES = rules._participant_aliases
_ORIGINAL_TOURNAMENT_MATCH = tournament._match_item_across_competition

_US_STATES = {
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California",
    "CO":"Colorado","CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia",
    "HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa",
    "KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland",
    "MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi",
    "MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire",
    "NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina",
    "ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania",
    "RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota","TN":"Tennessee",
    "TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington",
    "WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming","DC":"Washington DC",
}
_STATE_ABBR = {v.casefold(): k for k, v in _US_STATES.items()}

_COMMON_EQUIVALENTS = {
    "dominican republic": ("DR",),
    "dr": ("Dominican Republic",),
    "curacao": ("Curaçao",),
    "czechia": ("Czech Republic",),
    "czech republic": ("Czechia",),
    "south korea": ("Korea",),
}


def _clean(value):
    return str(value or "").strip()


def _norm(value):
    text = unicodedata.normalize("NFKD", _clean(value))
    text = text.encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _append_alias(rows, value, score, source):
    value = _clean(value)
    key = _norm(value)
    if not key:
        return
    existing = next((row for row in rows if row["key"] == key), None)
    if existing:
        if score > existing["score"]:
            existing.update(value=value, score=score, source=source)
        return
    rows.append({"value": value, "key": key, "score": int(score), "source": source})


def _media_alias_details(team):
    """Build public/media-facing aliases from the generic imported participant object."""
    if isinstance(team, str):
        team = {"name": team, "displayName": team}
    team = dict(team or {})
    rows = []

    _append_alias(rows, team.get("name"), 100, "NAME")
    _append_alias(rows, team.get("displayName"), 100, "DISPLAY_NAME")
    _append_alias(rows, team.get("teamName"), 100, "TEAM_NAME")

    aliases = team.get("aliases") or []
    if isinstance(aliases, str):
        aliases = re.split(r"[\r\n]+", aliases)
    for value in aliases:
        _append_alias(rows, value, 94, "IMPORTED_ALIAS")

    group = _clean(team.get("group") or team.get("region"))
    _append_alias(rows, group, 72, "GROUP")
    if re.search(r"\s+Region$", group, re.I):
        _append_alias(rows, re.sub(r"\s+Region$", "", group, flags=re.I), 78, "GROUP_WITHOUT_REGION")

    abbreviation = _clean(team.get("abbreviation") or team.get("abbr"))
    if abbreviation and len(abbreviation) <= 5:
        _append_alias(rows, abbreviation, 70, "ABBREVIATION")

    # Imported locations are often "City, State/Country". Media titles use only
    # the public-facing state/country portion. Derive that final component.
    for row in list(rows):
        value = row["value"]
        if "," not in value:
            continue
        tail = _clean(value.rsplit(",", 1)[-1])
        if not tail:
            continue
        _append_alias(rows, tail, 98, "LOCATION_TAIL")
        state = _US_STATES.get(tail.upper())
        if state:
            _append_alias(rows, state, 100, "US_STATE_FROM_ABBREVIATION")
        abbr = _STATE_ABBR.get(tail.casefold())
        if abbr:
            _append_alias(rows, abbr, 86, "US_STATE_ABBREVIATION")

    # If a full US state was already present, also allow the standard postal
    # abbreviation. This is needed for official recap titles such as PA vs. NJ.
    for row in list(rows):
        abbr = _STATE_ABBR.get(row["value"].casefold())
        if abbr:
            _append_alias(rows, abbr, 86, "US_STATE_ABBREVIATION")

    for row in list(rows):
        for value in _COMMON_EQUIVALENTS.get(row["key"], ()):
            _append_alias(rows, value, 96, "COMMON_MEDIA_EQUIVALENT")

    # One-character abbreviations create too many false positives in natural
    # titles (for example West's "W"). Keep them out of media title matching.
    return [row for row in rows if len(row["key"]) >= 2]


def _participant_aliases_v4614(team):
    return [row["value"] for row in _media_alias_details(team)]


def _event_team(event, side):
    event = event or {}
    value = event.get(f"{side}Team")
    if value in (None, ""):
        value = event.get(side)
    if isinstance(value, dict):
        return dict(value)
    return {"name": _clean(value), "displayName": _clean(value)}


def _contains_alias(text, alias_key):
    text = _norm(text)
    alias_key = _norm(alias_key)
    if not alias_key:
        return False
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(alias_key) + r"(?![a-z0-9])", text))


def _title_sides(item):
    title = _clean((item or {}).get("title") or (item or {}).get("headline"))
    normalized = _norm(title)
    match = re.search(r"^(.*?)\bvs\b(.*)$", normalized)
    if not match:
        return "", "", normalized
    return match.group(1).strip(), match.group(2).strip(), normalized


def _best_alias_hit(text, team):
    hits = [
        row for row in _media_alias_details(team)
        if _contains_alias(text, row["key"])
    ]
    if not hits:
        return None
    hits.sort(key=lambda row: (row["score"], len(row["key"])), reverse=True)
    return hits[0]


def _direct_title_pair_evidence(item, event):
    """Prove a two-participant title pair independent of the generic league matcher."""
    left, right, whole = _title_sides(item)
    away = _event_team(event, "away")
    home = _event_team(event, "home")

    if left and right:
        # Standard and reversed order are both valid; tournament source titles do
        # not guarantee home/away ordering.
        patterns = (
            ("NORMAL", _best_alias_hit(left, away), _best_alias_hit(right, home)),
            ("REVERSED", _best_alias_hit(left, home), _best_alias_hit(right, away)),
        )
        viable = [
            (order, first, second)
            for order, first, second in patterns
            if first and second
        ]
        if viable:
            viable.sort(
                key=lambda row: (
                    row[1]["score"] + row[2]["score"],
                    len(row[1]["key"]) + len(row[2]["key"]),
                ),
                reverse=True,
            )
            order, first, second = viable[0]
            return {
                "associationState": "ASSIGNED",
                "associationMethod": "SPECIAL_EVENT_TITLE_ALIAS_PAIR",
                "titlePairOrder": order,
                "titlePairScore": first["score"] + second["score"],
                "titleAlias1": first["value"],
                "titleAlias1Source": first["source"],
                "titleAlias2": second["value"],
                "titleAlias2Source": second["source"],
            }

    # Fallback for a rare title format with no explicit "vs". Both independent
    # participant aliases still have to occur; use a higher minimum score because
    # side separation is unavailable.
    away_hit = _best_alias_hit(whole, away)
    home_hit = _best_alias_hit(whole, home)
    if away_hit and home_hit and min(away_hit["score"], home_hit["score"]) >= 78:
        return {
            "associationState": "ASSIGNED",
            "associationMethod": "SPECIAL_EVENT_TITLE_ALIAS_PAIR_UNSPLIT",
            "titlePairOrder": "UNSPLIT",
            "titlePairScore": away_hit["score"] + home_hit["score"],
            "titleAlias1": away_hit["value"],
            "titleAlias1Source": away_hit["source"],
            "titleAlias2": home_hit["value"],
            "titleAlias2Source": home_hit["source"],
        }
    return None


def _record_event(record, competition_id):
    record = record or {}
    event = dict(record.get("event") or {})
    event.setdefault("eventId", record.get("eventId"))
    event.setdefault("date", record.get("date"))
    event.setdefault("competitionId", competition_id)
    event.setdefault("__sbbLeague", competition_id)
    event.setdefault("__sbbDate", record.get("date"))
    return event


def _match_item_across_competition_v4614(server, comp, item, records, playlist_row=None):
    allowed, reason = tournament._playlist_title_allows(comp, playlist_row, item)
    if not allowed:
        return {
            "state": "REJECTED_TITLE_RULE",
            "reason": reason,
            "match": None,
            "matches": 0,
        }

    cid = _clean(comp.get("id")).upper()

    # First use the imported identity data directly. This is the missing step that
    # v4.6.13 delegated to the generic matcher.
    direct = []
    for record in records or []:
        event = _record_event(record, cid)
        evidence = _direct_title_pair_evidence(item, event)
        if evidence:
            direct.append((record, evidence))

    if direct:
        try:
            default_year = int(
                _clean((item or {}).get("publishedAt"))[:4]
                or int(comp.get("year") or 0)
            )
        except Exception:
            default_year = int(comp.get("year") or 0)
        selected, resolution = tournament._choose_match(
            server, item, direct, default_year=default_year
        )
        return {
            "state": "ASSIGNED" if selected else "AMBIGUOUS",
            "reason": resolution,
            "match": selected,
            "matches": len(tournament._dedupe_matches(direct)),
            "directTitleAliasPair": True,
        }

    # Preserve every generic/proven association path from v4.6.13.
    return _ORIGINAL_TOURNAMENT_MATCH(
        server, comp, item, records, playlist_row=playlist_row
    )


def _reassociate_after_install():
    server = None
    for _ in range(600):
        server = getattr(base, "_SERVER", None)
        if server is not None and hasattr(server, "_operator_media_playlists_load"):
            break
        time.sleep(0.2)
    else:
        return

    # Wait for the historical catalog and prior overlays to finish startup.
    time.sleep(2)
    for comp in base._load():
        if (
            _clean(comp.get("type")).upper() != "SPECIAL_EVENT"
            or not comp.get("enabled", True)
        ):
            continue
        try:
            tournament._reassociate_existing_competition(server, comp)
        except Exception:
            pass


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True

    # Expand aliases for both the v4.6.12 generic matcher wrapper and the direct
    # v4.6.14 title-pair path.
    rules._participant_aliases = _participant_aliases_v4614
    tournament._match_item_across_competition = _match_item_across_competition_v4614

    threading.Thread(
        target=_reassociate_after_install,
        daemon=True,
        name="sbb-v4614-media-alias-reassociate",
    ).start()

"""Sports Big Board v4.6.13 — tournament-wide playlist association hardening.

Special-event operator playlists are small, curated collections. Their source-media
items must therefore be matched against the complete competition schedule before
publication date is allowed to narrow the candidate set.

This module:
- keeps the existing built-in-league playlist crawler untouched;
- replaces only SPECIAL_EVENT operator playlist association;
- filters by v4.6.12 required/excluded title phrases first;
- tries participant name/alias/group/abbreviation evidence across every event;
- uses provider IDs, explicit title date/game number, then publication proximity
  only as deterministic tie-breakers;
- re-associates already-downloaded operator playlist source media at startup;
- exposes durable association statistics for the History Audit UI.

No source media is deleted and canonical Sports Big Board event IDs are preserved.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from urllib.parse import parse_qs

from . import competition_builder as base
from . import competition_builder_v4612 as rules

_INSTALLED = False
_INSTALL_LOCK = threading.Lock()
_ORIGINAL_OPERATOR_CRAWL = None
_ORIGINAL_HANDLE_GET = None


def _clean(value):
    return str(value or "").strip()


def _is_special_event(comp):
    return bool(comp and _clean(comp.get("type")).upper() == "SPECIAL_EVENT")


def _media_id(item):
    item = item or {}
    return _clean(
        item.get("youtubeId")
        or item.get("mediaId")
        or item.get("id")
        or item.get("mediaUrl")
        or item.get("externalUrl")
    )


def _record_key(record):
    record = record or {}
    return _clean(
        record.get("canonicalEventKey")
        or record.get("eventId")
        or ((record.get("event") or {}).get("eventId"))
        or ((record.get("event") or {}).get("id"))
    )


def _event_date(record):
    record = record or {}
    return _clean(record.get("date") or ((record.get("event") or {}).get("date")))[:10]


def _event_number(record):
    event = (record or {}).get("event") or {}
    value = event.get("gameNumber")
    try:
        return int(value)
    except Exception:
        return None


def _team_name(event, side):
    event = event or {}
    value = event.get(f"{side}Team") or event.get(side) or event.get(f"{side}TeamName") or ""
    if isinstance(value, dict):
        return _clean(
            value.get("displayName")
            or value.get("name")
            or value.get("shortName")
            or value.get("abbreviation")
            or value.get("abbr")
        )
    return _clean(value)


def _playlist_row_for_item(rows, item):
    item = item or {}
    internal = _clean(item.get("operatorPlaylistId"))
    provider = _clean(
        item.get("playlistId")
        or item.get("sourcePlaylistId")
        or item.get("youtubePlaylistId")
    )
    for row in rows or []:
        if internal and internal == _clean(row.get("id")):
            return row
        if provider and provider == _clean(row.get("playlistId")):
            return row
    return None


def _phrases(value):
    return rules._phrases(value)


def _playlist_title_allows(comp, row, item):
    """Use exact operator-row rules when known; fall back to v4.6.12 competition rules."""
    if row:
        required = [x.casefold() for x in _phrases(row.get("requiredTitlePhrases"))]
        excluded = [x.casefold() for x in _phrases(row.get("excludedTitlePhrases"))]
        text = " ".join(
            _clean((item or {}).get(k))
            for k in ("title", "subtitle", "description", "headline")
        ).casefold()
        if excluded and any(x in text for x in excluded):
            return False, "EXCLUDED_TITLE_PHRASE"
        if required and not any(x in text for x in required):
            return False, "REQUIRED_TITLE_PHRASE_MISSING"
        return True, ""
    allowed, detail = rules._title_rule_allows(comp, item)
    return bool(allowed), _clean((detail or {}).get("reason"))


def _competition_records(server, comp):
    cid = _clean(comp.get("id")).upper()
    start = _clean(comp.get("startDate"))[:10]
    end = _clean(comp.get("endDate"))[:10]
    try:
        records = server.HISTORY_REPOSITORY.catalog_events(
            league=cid,
            date_from=start,
            date_to=end,
            limit=50000,
        )
    except Exception:
        records = []
    if records:
        return records

    # Fallback is useful immediately after creation if the history index has not
    # completed yet. save_competition normally indexes these before media crawl.
    out = []
    for event in comp.get("events") or []:
        eid = _clean(event.get("eventId") or event.get("id"))
        if not eid:
            continue
        out.append({
            "canonicalEventKey": f"{cid}:{eid}",
            "eventId": eid,
            "date": _clean(event.get("date"))[:10],
            "event": dict(event),
        })
    return out


def _explicit_title_date(server, item, default_year):
    title = _clean((item or {}).get("title"))
    try:
        value = server._epl_numeric_date_from_text(title)
        if value:
            return _clean(value)[:10]
    except Exception:
        pass
    try:
        value = server._named_date_from_text(title, default_year)
        if value:
            return _clean(value)[:10]
    except Exception:
        pass
    return ""


def _published_date(item):
    value = _clean((item or {}).get("publishedAt") or (item or {}).get("published"))[:10]
    return value if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else ""


def _title_game_number(item):
    title = _clean((item or {}).get("title"))
    match = re.search(r"\bgame\s*#?\s*(\d{1,3})\b", title, re.I)
    return int(match.group(1)) if match else None


def _days_apart(a, b):
    try:
        da = datetime.strptime(a, "%Y-%m-%d").date()
        db = datetime.strptime(b, "%Y-%m-%d").date()
        return abs((da - db).days)
    except Exception:
        return 9999


def _dedupe_matches(matches):
    out = {}
    for record, evidence in matches or []:
        key = _record_key(record)
        if key and key not in out:
            out[key] = (record, evidence)
    return list(out.values())


def _choose_match(server, item, matches, default_year=0):
    """Choose one proven event without guessing.

    Matchup/alias evidence has already proven every entry in ``matches``.
    Tie-breaking is only needed when the same participants meet more than once.
    """
    matches = _dedupe_matches(matches)
    if len(matches) <= 1:
        return (matches[0] if matches else None), "UNIQUE_PAIR" if matches else "NO_MATCH"

    # Provider identity is stronger than calendar inference.
    provider_methods = {
        "PROVIDER_EVENT_ID",
        "PROVIDER_GAME_PK",
        "PROVIDER_SOURCE_EVENT_ID",
    }
    strong = [
        row for row in matches
        if _clean((row[1] or {}).get("associationMethod")).upper() in provider_methods
    ]
    if len(strong) == 1:
        return strong[0], "PROVIDER_ID"

    game_number = _title_game_number(item)
    if game_number is not None:
        numbered = [row for row in matches if _event_number(row[0]) == game_number]
        if len(numbered) == 1:
            return numbered[0], "GAME_NUMBER"

    explicit = _explicit_title_date(server, item, default_year)
    if explicit:
        exact = [row for row in matches if _event_date(row[0]) == explicit]
        if len(exact) == 1:
            return exact[0], "EXPLICIT_TITLE_DATE"

    published = _published_date(item)
    if published:
        ranked = sorted(
            (( _days_apart(_event_date(row[0]), published), row) for row in matches),
            key=lambda x: x[0],
        )
        if ranked:
            best_gap = ranked[0][0]
            best = [row for gap, row in ranked if gap == best_gap]
            # Tournament uploads usually land the same day or shortly after.
            # Do not use publication proximity as proof across a large gap.
            if best_gap <= 3 and len(best) == 1:
                return best[0], "PUBLICATION_PROXIMITY"

    return None, "AMBIGUOUS_REPEATED_MATCHUP"


def _match_item_across_competition(server, comp, item, records, playlist_row=None):
    allowed, reason = _playlist_title_allows(comp, playlist_row, item)
    if not allowed:
        return {
            "state": "REJECTED_TITLE_RULE",
            "reason": reason,
            "match": None,
            "matches": 0,
        }

    cid = _clean(comp.get("id")).upper()
    matches = []
    for record in records:
        event = dict((record or {}).get("event") or {})
        event.setdefault("competitionId", cid)
        event.setdefault("__sbbLeague", cid)
        event.setdefault("__sbbDate", _event_date(record))
        try:
            scoped, evidence = server._history_media_match_evidence(dict(item), event)
        except Exception:
            continue
        if (
            _clean((scoped or {}).get("mediaScope")).upper() == "GAME"
            and _clean((evidence or {}).get("associationState")).upper() == "ASSIGNED"
        ):
            matches.append((record, evidence))

    try:
        default_year = int(
            _clean((item or {}).get("publishedAt"))[:4]
            or int(comp.get("year") or 0)
        )
    except Exception:
        default_year = int(comp.get("year") or 0)

    selected, method = _choose_match(server, item, matches, default_year=default_year)
    return {
        "state": "ASSIGNED" if selected else ("AMBIGUOUS" if matches else "UNMATCHED"),
        "reason": method,
        "match": selected,
        "matches": len(_dedupe_matches(matches)),
    }


def _decorate_assignment(comp, playlist_row, item, record, evidence, resolution):
    event = dict((record or {}).get("event") or {})
    eid = _clean((record or {}).get("eventId") or event.get("eventId") or event.get("id"))
    row = dict(item or {})
    row.update({
        "league": _clean(comp.get("id")).upper(),
        "competitionId": _clean(comp.get("id")).upper(),
        "competitionName": _clean(comp.get("name")),
        "eventId": eid,
        "matchId": eid,
        "scoreEventId": eid,
        "canonicalEventId": eid,
        "canonicalEventKey": _record_key(record),
        "date": _event_date(record),
        "gameDate": _event_date(record),
        "__sbbDate": _event_date(record),
        "away": _team_name(event, "away"),
        "home": _team_name(event, "home"),
        "associationMethod": _clean((evidence or {}).get("associationMethod")),
        "associationResolution": resolution,
        "participantAliasMatch": (evidence or {}).get("participantAliasMatch"),
    })
    if playlist_row:
        row["operatorPlaylistId"] = _clean(playlist_row.get("id"))
        row["playlistId"] = _clean(playlist_row.get("playlistId"))
        row["sourcePlaylistId"] = _clean(playlist_row.get("playlistId"))
        row["operatorPlaylistTitle"] = _clean(playlist_row.get("title"))
    return row


def _associate_items(server, comp, records, items, playlist_rows):
    result = {
        "items": len(items or []),
        "assigned": 0,
        "alreadyAssociated": 0,
        "ambiguous": 0,
        "unmatched": 0,
        "titleRuleRejected": 0,
        "resolutionMethods": {},
    }
    assigned_ids = set()

    for item in items or []:
        playlist_row = _playlist_row_for_item(playlist_rows, item)
        outcome = _match_item_across_competition(
            server, comp, item, records, playlist_row=playlist_row
        )
        state = outcome["state"]
        if state == "REJECTED_TITLE_RULE":
            result["titleRuleRejected"] += 1
            continue
        if state == "AMBIGUOUS":
            result["ambiguous"] += 1
            continue
        if state != "ASSIGNED" or not outcome.get("match"):
            result["unmatched"] += 1
            continue

        record, evidence = outcome["match"]
        decorated = _decorate_assignment(
            comp, playlist_row, item, record, evidence, outcome["reason"]
        )
        media_id = _media_id(item)
        try:
            added = int(
                server.HISTORY_REPOSITORY.put_event_media(
                    _event_date(record),
                    _clean(comp.get("id")).upper(),
                    _clean(record.get("eventId") or ((record.get("event") or {}).get("eventId"))),
                    [decorated],
                )
                or 0
            )
        except Exception:
            added = 0

        if media_id:
            assigned_ids.add(media_id)
        if added > 0:
            result["assigned"] += 1
        else:
            result["alreadyAssociated"] += 1
        method = outcome["reason"]
        result["resolutionMethods"][method] = result["resolutionMethods"].get(method, 0) + 1

    result["resolvedAssets"] = len(assigned_ids)
    return result


def _special_event_playlist_crawl(server, playlist_id, force=True):
    oid = _clean(playlist_id)
    rows = server._operator_media_playlists_load()
    row = next(
        (x for x in rows if _clean(x.get("id")) == oid or _clean(x.get("playlistId")) == oid),
        None,
    )
    if not row:
        raise ValueError("Playlist is not registered.")

    league = _clean(row.get("league")).upper()
    comp = base._find(league)
    if not _is_special_event(comp):
        return _ORIGINAL_OPERATOR_CRAWL(playlist_id, force=force)

    cfg = server._operator_playlist_to_curated(row)
    start = int(row.get("seasonStart") or comp.get("year") or 0)
    end = int(row.get("seasonEnd") or start or 0)

    with server.OPERATOR_MEDIA_PLAYLIST_CRAWL_LOCK:
        server.OPERATOR_MEDIA_PLAYLIST_CRAWL_STATE.update(
            running=True, lastPlaylistId=_clean(row.get("id")), lastError=""
        )
        try:
            items = [
                dict(x)
                for x in server._curated_playlist_items(
                    league, cfg, force=bool(force)
                )
            ]
            for item in items:
                # v4.6.12 only stamped the internal operator ID. Persist both
                # identities so multi-playlist title rules stay deterministic.
                item["operatorPlaylistId"] = _clean(row.get("id"))
                item["operatorPlaylistTitle"] = _clean(row.get("title"))
                item["playlistId"] = _clean(row.get("playlistId"))
                item["sourcePlaylistId"] = _clean(row.get("playlistId"))
                item["league"] = league
                item["competitionId"] = league

            server.HISTORY_REPOSITORY.put_source_media(
                items, league=league, catalog_state="UNASSIGNED"
            )

            records = _competition_records(server, comp)
            association = _associate_items(server, comp, records, items, [row])

            stats = server.HISTORY_REPOSITORY.playlist_asset_stats(row.get("playlistId"))
            stats.update({
                "playlistItems": len(items),
                "hydrated": len(items),
                "associatedThisCrawl": association["resolvedAssets"],
                "ambiguousThisCrawl": association["ambiguous"],
                "unmatchedThisCrawl": association["unmatched"],
                "titleRuleRejectedThisCrawl": association["titleRuleRejected"],
                "fullCompetitionCompared": True,
                "competitionEventCandidates": len(records),
                "lastAssociationMethods": association["resolutionMethods"],
                "lastCrawlAt": time.time(),
                "lastError": "",
            })

            for saved in rows:
                if _clean(saved.get("id")) == _clean(row.get("id")):
                    saved["stats"] = stats
                    saved["lastCrawlAt"] = stats["lastCrawlAt"]
                    saved["lastError"] = ""
                    saved["updatedAt"] = time.time()
            server._operator_media_playlists_save(rows)
            server.OPERATOR_MEDIA_PLAYLIST_CRAWL_STATE.update(
                running=False, lastRun=time.time(), lastError=""
            )
            return {
                "ok": True,
                "playlist": next(
                    x for x in rows if _clean(x.get("id")) == _clean(row.get("id"))
                ),
                "stats": stats,
                "association": association,
            }
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            for saved in rows:
                if _clean(saved.get("id")) == _clean(row.get("id")):
                    saved["lastError"] = message
                    saved["lastCrawlAt"] = time.time()
                    saved["updatedAt"] = time.time()
            try:
                server._operator_media_playlists_save(rows)
            except Exception:
                pass
            server.OPERATOR_MEDIA_PLAYLIST_CRAWL_STATE.update(
                running=False, lastRun=time.time(), lastError=message
            )
            raise


def _reassociate_existing_competition(server, comp):
    """Re-prove already-downloaded operator playlist media without redownloading it."""
    if not _is_special_event(comp):
        return {"attempted": False, "reason": "NOT_SPECIAL_EVENT"}

    cid = _clean(comp.get("id")).upper()
    rows = [
        row for row in server._operator_media_playlists_load()
        if _clean(row.get("league")).upper() == cid and row.get("enabled", True)
    ]
    if not rows:
        return {"attempted": False, "reason": "NO_OPERATOR_PLAYLISTS"}

    try:
        source_items = list(base._league_source_media(server, cid) or [])
    except Exception:
        source_items = []

    playlist_ids = {_clean(row.get("id")) for row in rows}
    youtube_ids = {_clean(row.get("playlistId")) for row in rows}
    items = []
    for item in source_items:
        internal = _clean((item or {}).get("operatorPlaylistId"))
        provider = _clean(
            (item or {}).get("playlistId")
            or (item or {}).get("sourcePlaylistId")
            or (item or {}).get("youtubePlaylistId")
        )
        source_type = _clean((item or {}).get("sourceType")).lower()
        if (
            internal in playlist_ids
            or provider in youtube_ids
            or source_type == "operator-youtube-game-playlist"
        ):
            items.append(dict(item))

    records = _competition_records(server, comp)
    result = _associate_items(server, comp, records, items, rows)
    result.update({
        "attempted": True,
        "competitionId": cid,
        "competitionEvents": len(records),
        "sourceItems": len(items),
    })

    # Refresh durable playlist statistics after the association pass.
    registry = server._operator_media_playlists_load()
    changed = False
    for row in registry:
        if _clean(row.get("league")).upper() != cid:
            continue
        try:
            stats = server.HISTORY_REPOSITORY.playlist_asset_stats(row.get("playlistId"))
        except Exception:
            continue
        existing = dict(row.get("stats") or {})
        existing.update(stats)
        existing.update({
            "reassociatedExistingAt": time.time(),
            "reassociatedExistingResolved": result.get("resolvedAssets", 0),
            "reassociatedExistingAmbiguous": result.get("ambiguous", 0),
            "fullCompetitionCompared": True,
        })
        row["stats"] = existing
        row["updatedAt"] = time.time()
        changed = True
    if changed:
        try:
            server._operator_media_playlists_save(registry)
        except Exception:
            pass
    return result


def _is_playable(item):
    item = item or {}
    if item.get("runtimeFailed") or item.get("poisoned"):
        return False
    has_transport = bool(item.get("youtubeId") or item.get("mediaUrl"))
    verified = item.get("verifiedPlayable")
    return has_transport and verified is not False


def _association_stats(server, comp):
    cid = _clean(comp.get("id")).upper()
    records = _competition_records(server, comp)
    games_with_media = 0
    games_with_playable = 0
    associated_ids = set()
    tiers = {"gold": 0, "green": 0, "extended": 0, "blue": 0}

    for record in records:
        event = record.get("event") or {}
        eid = _clean(record.get("eventId") or event.get("eventId") or event.get("id"))
        try:
            media = list(
                server.HISTORY_REPOSITORY.event_media(
                    _event_date(record), cid, eid, include_failed=False
                )
                or []
            )
        except Exception:
            media = []
        if media:
            games_with_media += 1
        playable = [item for item in media if _is_playable(item)]
        if playable:
            games_with_playable += 1
            best = "blue"
            priority = {"gold": 4, "green": 3, "extended": 2, "blue": 1}
            for item in playable:
                tier = _clean(item.get("recapTier") or "blue").lower()
                if tier not in priority:
                    tier = "blue"
                if priority[tier] > priority[best]:
                    best = tier
                mid = _media_id(item)
                if mid:
                    associated_ids.add(mid)
            tiers[best] += 1

    playlist_rows = [
        row for row in server._operator_media_playlists_load()
        if _clean(row.get("league")).upper() == cid
    ]
    orphaned = 0
    playlist_assigned = 0
    playlist_assets = 0
    for row in playlist_rows:
        try:
            stats = server.HISTORY_REPOSITORY.playlist_asset_stats(row.get("playlistId"))
        except Exception:
            stats = row.get("stats") or {}
        orphaned += int(stats.get("orphaned") or 0)
        playlist_assigned += int(stats.get("assigned") or 0)
        playlist_assets += int(stats.get("assets") or stats.get("hydrated") or 0)

    total = len(records)
    return {
        "competitionId": cid,
        "games": total,
        "gamesWithAssociatedMedia": games_with_media,
        "gamesWithPlayableAssociatedMedia": games_with_playable,
        "gamesWithoutPlayableAssociatedMedia": max(0, total - games_with_playable),
        "associatedAssets": len(associated_ids),
        "playlistAssignedAssets": playlist_assigned,
        "orphanedAssets": orphaned,
        "playlistAssets": playlist_assets,
        "playlists": len(playlist_rows),
        "best": tiers,
    }


def _handle_get(server, handler, parsed):
    if parsed.path == "/api/competition-builder/media-association-stats":
        qs = parse_qs(parsed.query)
        cid = _clean((qs.get("id") or [""])[-1]).upper()
        comp = base._find(cid)
        if not comp:
            return base._send(
                server, handler,
                {"ok": False, "error": "COMPETITION_NOT_FOUND"},
                404,
            )
        return base._send(
            server, handler,
            {"ok": True, "data": _association_stats(server, comp)},
            200,
        )
    if parsed.path == "/api/competition-builder/reassociate-media":
        qs = parse_qs(parsed.query)
        cid = _clean((qs.get("id") or [""])[-1]).upper()
        comp = base._find(cid)
        if not comp:
            return base._send(
                server, handler,
                {"ok": False, "error": "COMPETITION_NOT_FOUND"},
                404,
            )
        result = _reassociate_existing_competition(server, comp)
        return base._send(
            server, handler,
            {"ok": True, "data": result, "stats": _association_stats(server, comp)},
            200,
        )
    return _ORIGINAL_HANDLE_GET(server, handler, parsed)


def _startup_reassociate(server):
    # Give competition/history startup a moment to finish indexing saved events.
    time.sleep(3)
    for comp in base._load():
        if not _is_special_event(comp) or not comp.get("enabled", True):
            continue
        try:
            _reassociate_existing_competition(server, comp)
        except Exception:
            pass


def _install_when_ready():
    global _ORIGINAL_OPERATOR_CRAWL, _ORIGINAL_HANDLE_GET

    server = None
    for _ in range(600):
        server = getattr(base, "_SERVER", None)
        matcher = getattr(server, "_history_media_match_evidence", None) if server else None
        if (
            server is not None
            and hasattr(server, "_operator_media_playlist_crawl")
            and callable(matcher)
            and getattr(matcher, "__sbb_v4612_wrapped", False)
        ):
            break
        time.sleep(0.2)
    else:
        return

    if _ORIGINAL_OPERATOR_CRAWL is None:
        _ORIGINAL_OPERATOR_CRAWL = server._operator_media_playlist_crawl

        def crawl(playlist_id, force=True):
            rows = server._operator_media_playlists_load()
            oid = _clean(playlist_id)
            row = next(
                (
                    x for x in rows
                    if _clean(x.get("id")) == oid
                    or _clean(x.get("playlistId")) == oid
                ),
                None,
            )
            comp = base._find(_clean((row or {}).get("league")).upper()) if row else None
            if _is_special_event(comp):
                return _special_event_playlist_crawl(
                    server, playlist_id, force=force
                )
            return _ORIGINAL_OPERATOR_CRAWL(playlist_id, force=force)

        crawl.__sbb_v4613_tournament_wide = True
        server._operator_media_playlist_crawl = crawl

    if _ORIGINAL_HANDLE_GET is None:
        _ORIGINAL_HANDLE_GET = base._handle_get
        base._handle_get = _handle_get

    threading.Thread(
        target=_startup_reassociate,
        args=(server,),
        daemon=True,
        name="sbb-v4613-startup-reassociate",
    ).start()


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    threading.Thread(
        target=_install_when_ready,
        daemon=True,
        name="sbb-competition-builder-v4613-install",
    ).start()

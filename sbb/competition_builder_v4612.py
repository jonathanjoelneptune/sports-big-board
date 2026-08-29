"""Sports Big Board v4.6.12 — reusable special-event media association rules.

Adds non-destructive matching hints on top of the persistent Competition Builder:
- per-playlist required/excluded title phrases
- participant alias/group evidence from imported schedule JSON
- persistent media-rule updates after a competition has already been created
- automatic force recrawl when media rules are changed

The underlying source-media catalog is never deleted. Title rules only decide
whether an asset is eligible to associate to a GAME event.
"""
from __future__ import annotations

import re
import threading
import time
from copy import deepcopy
from urllib.parse import parse_qs

from . import competition_builder as base

_INSTALLED = False
_INSTALL_LOCK = threading.Lock()
_ORIGINAL_REGISTER_MEDIA_SOURCES = None
_ORIGINAL_REPAIR_EVENT_MEDIA = None
_ORIGINAL_HANDLE_POST = None


def _clean(value):
    return str(value or "").strip()


def _phrases(value):
    if value is None:
        return []
    if isinstance(value, str):
        rows = re.split(r"[\r\n]+", value)
    else:
        rows = list(value or [])
    out = []
    for row in rows:
        text = _clean(row)
        if text and text.casefold() not in {x.casefold() for x in out}:
            out.append(text)
    return out


def _youtube_playlist_id(value):
    text = _clean(value)
    if not text:
        return ""
    m = re.search(r"(?:[?&]list=|youtube\.com/playlist\?list=)([A-Za-z0-9_-]+)", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", text):
        return text
    return ""


def _source_rule_rows(comp):
    rows = []
    for tier, sources in ((comp or {}).get("mediaSources") or {}).items():
        for raw in sources or []:
            src = dict(raw or {}) if isinstance(raw, dict) else {"url": raw}
            required = _phrases(src.get("requiredTitlePhrases") or src.get("requiredTitlePhrase"))
            excluded = _phrases(src.get("excludedTitlePhrases") or src.get("excludedTitlePhrase"))
            if not required and not excluded:
                continue
            url = _clean(src.get("url") or src.get("playlistId"))
            rows.append({
                "tier": _clean(tier).lower(),
                "url": url,
                "playlistId": _youtube_playlist_id(url),
                "requiredTitlePhrases": required,
                "excludedTitlePhrases": excluded,
            })
    return rows


def _candidate_playlist_id(item):
    for key in ("playlistId", "sourcePlaylistId", "youtubePlaylistId", "playlist", "sourcePlaylist"):
        value = (item or {}).get(key)
        if isinstance(value, dict):
            value = value.get("id") or value.get("playlistId")
        pid = _youtube_playlist_id(value)
        if pid:
            return pid
    for key in ("sourceUrl", "playlistUrl", "externalUrl"):
        pid = _youtube_playlist_id((item or {}).get(key))
        if pid:
            return pid
    return ""


def _rule_for_item(comp, item):
    rows = _source_rule_rows(comp)
    if not rows:
        return None
    pid = _candidate_playlist_id(item)
    if pid:
        exact = [r for r in rows if r.get("playlistId") == pid]
        if exact:
            return exact[0]
    # Operator source-media records from older crawls may not carry playlistId.
    # If the competition has one configured rule (the common special-event case),
    # it is safe and deterministic to use that rule.
    if len(rows) == 1:
        return rows[0]
    # If multiple sources use the exact same rule, the rule is still unambiguous.
    sigs = {
        (
            tuple(x.casefold() for x in r.get("requiredTitlePhrases") or []),
            tuple(x.casefold() for x in r.get("excludedTitlePhrases") or []),
        )
        for r in rows
    }
    if len(sigs) == 1:
        return rows[0]
    return None


def _title_rule_allows(comp, item):
    rule = _rule_for_item(comp, item)
    if not rule:
        return True, None
    text = " ".join(_clean((item or {}).get(k)) for k in ("title", "description", "headline")).casefold()
    required = [x.casefold() for x in rule.get("requiredTitlePhrases") or []]
    excluded = [x.casefold() for x in rule.get("excludedTitlePhrases") or []]
    if excluded and any(x in text for x in excluded):
        return False, {**rule, "reason": "EXCLUDED_TITLE_PHRASE"}
    if required and not any(x in text for x in required):
        return False, {**rule, "reason": "REQUIRED_TITLE_PHRASE_MISSING"}
    return True, rule


def _participant_aliases(team):
    if isinstance(team, str):
        values = [team]
    else:
        team = dict(team or {})
        values = [
            team.get("name"),
            team.get("displayName"),
            team.get("teamName"),
            team.get("abbreviation"),
            team.get("abbr"),
            team.get("shortName"),
            team.get("group"),
            team.get("region"),
        ]
        aliases = team.get("aliases") or []
        if isinstance(aliases, str):
            aliases = re.split(r"[\r\n,]+", aliases)
        values.extend(aliases)
    out = []
    for value in values:
        value = _clean(value)
        if value and value.casefold() not in {x.casefold() for x in out}:
            out.append(value)
    return out[:8]


def _team_obj(event, side):
    value = (event or {}).get(f"{side}Team")
    if value in (None, ""):
        value = (event or {}).get(side)
    if isinstance(value, dict):
        return dict(value)
    return {"name": _clean(value), "displayName": _clean(value)}


def _event_alias_variants(event):
    event = dict(event or {})
    away_obj = _team_obj(event, "away")
    home_obj = _team_obj(event, "home")
    away_names = _participant_aliases(away_obj) or [_clean(away_obj.get("name"))]
    home_names = _participant_aliases(home_obj) or [_clean(home_obj.get("name"))]
    seen = set()
    variants = []
    for away in away_names[:5]:
        for home in home_names[:5]:
            if not away or not home:
                continue
            key = (away.casefold(), home.casefold())
            if key in seen:
                continue
            seen.add(key)
            row = deepcopy(event)
            a = dict(away_obj)
            h = dict(home_obj)
            a["name"] = away
            a["displayName"] = away
            h["name"] = home
            h["displayName"] = home
            row["away"] = a
            row["home"] = h
            row["awayTeam"] = a
            row["homeTeam"] = h
            row["awayName"] = away
            row["homeName"] = home
            row["awayTeamName"] = away
            row["homeTeamName"] = home
            variants.append(row)
            if len(variants) >= 25:
                return variants
    return variants or [event]


def _wrap_server_matcher(server):
    original = getattr(server, "_history_media_match_evidence", None)
    if not callable(original) or getattr(original, "__sbb_v4612_wrapped", False):
        return

    def wrapped(item, row):
        league = _clean((row or {}).get("competitionId") or (row or {}).get("__sbbLeague") or (row or {}).get("league")).upper()
        comp = base._find(league) if league else None
        if not comp:
            return original(item, row)

        allowed, rule = _title_rule_allows(comp, item)
        if not allowed:
            scoped, evidence = original(item, row)
            evidence = dict(evidence or {})
            evidence.update({
                "associationState": "REJECTED",
                "associationMethod": "PLAYLIST_TITLE_RULE",
                "mediaRuleReason": (rule or {}).get("reason") or "TITLE_RULE",
            })
            return scoped, evidence

        first_scoped = None
        first_evidence = None
        for variant in _event_alias_variants(row):
            scoped, evidence = original(item, variant)
            if first_scoped is None:
                first_scoped, first_evidence = scoped, evidence
            if _clean((evidence or {}).get("associationState")).upper() == "ASSIGNED":
                evidence = dict(evidence or {})
                evidence["participantAliasMatch"] = (
                    _clean((variant.get("awayTeam") or {}).get("name")),
                    _clean((variant.get("homeTeam") or {}).get("name")),
                )
                if rule:
                    evidence["playlistTitleRule"] = {
                        "requiredTitlePhrases": list(rule.get("requiredTitlePhrases") or []),
                        "excludedTitlePhrases": list(rule.get("excludedTitlePhrases") or []),
                    }
                return scoped, evidence
        return first_scoped, first_evidence

    wrapped.__sbb_v4612_wrapped = True
    wrapped.__sbb_v4612_original = original
    server._history_media_match_evidence = wrapped


def _wrap_playlist_normalize(server):
    original = getattr(server, "_operator_media_playlist_normalize", None)
    if not callable(original) or getattr(original, "__sbb_v4612_wrapped", False):
        return

    def wrapped(raw, existing=None):
        out = original(raw, existing)
        raw = dict(raw or {})
        existing = dict(existing or {})
        out["requiredTitlePhrases"] = _phrases(
            raw.get("requiredTitlePhrases")
            if "requiredTitlePhrases" in raw
            else existing.get("requiredTitlePhrases")
        )
        out["excludedTitlePhrases"] = _phrases(
            raw.get("excludedTitlePhrases")
            if "excludedTitlePhrases" in raw
            else existing.get("excludedTitlePhrases")
        )
        return out

    wrapped.__sbb_v4612_wrapped = True
    wrapped.__sbb_v4612_original = original
    server._operator_media_playlist_normalize = wrapped


def _register_media_sources(server, comp, force_crawl=False):
    required = (
        "_operator_media_playlists_load",
        "_operator_media_playlist_normalize",
        "_operator_media_playlists_save",
        "_operator_media_playlist_crawl_async",
    )
    if not all(hasattr(server, n) for n in required):
        return []
    rows = server._operator_media_playlists_load()
    objective = {"green": "quick", "purple": "extended", "blue": "coverage"}
    changed = False
    crawl_ids = []
    for tier, sources in ((comp or {}).get("mediaSources") or {}).items():
        for src in sources or []:
            src = dict(src or {}) if isinstance(src, dict) else {"url": src}
            url = _clean(src.get("url"))
            if not url:
                continue
            pid = server._youtube_playlist_id(url)
            if not pid:
                continue
            existing = next((
                x for x in rows
                if _clean(x.get("league")).upper() == comp["id"]
                and _clean(x.get("playlistId")) == pid
                and _clean(x.get("objective")) == objective.get(tier, "coverage")
            ), None)
            raw = {
                "league": comp["id"],
                "url": url,
                "playlistId": pid,
                "seasonStart": comp["year"],
                "seasonEnd": comp["year"],
                "objective": objective.get(tier, "coverage"),
                "priority": _clean(src.get("priority") or "PRIMARY"),
                "trust": _clean(src.get("trust") or "OPERATOR_TRUSTED"),
                "enabled": True,
                "autoRecrawl": True,
                "recrawlMinutes": int(src.get("recrawlMinutes") or 60),
                "resolveMetadata": True,
                "requiredTitlePhrases": _phrases(src.get("requiredTitlePhrases")),
                "excludedTitlePhrases": _phrases(src.get("excludedTitlePhrases")),
            }
            try:
                norm = server._operator_media_playlist_normalize(raw, existing)
            except Exception:
                continue
            if existing:
                idx = rows.index(existing)
                if rows[idx] != norm:
                    rows[idx] = norm
                    changed = True
            else:
                rows.append(norm)
                changed = True
            stats = (existing or {}).get("stats") or {}
            if (
                force_crawl
                or not float((existing or {}).get("lastCrawlAt") or 0)
                or int(stats.get("associatedThisCrawl") or 0) <= 0
            ):
                crawl_ids.append(_clean(norm.get("id")))
    if changed:
        try:
            server._operator_media_playlists_save(rows)
        except Exception:
            return []
    for playlist_id in dict.fromkeys(x for x in crawl_ids if x):
        try:
            server._operator_media_playlist_crawl_async(playlist_id, force=bool(force_crawl))
        except Exception:
            pass
    return list(dict.fromkeys(x for x in crawl_ids if x))


def _repair_event_media(server, comp, event, force=False):
    cid = comp["id"]
    eid = _clean((event or {}).get("eventId"))
    key = f"{cid}:{eid}"
    now = time.time()
    if not force and now - float(base._ASSOCIATION_REPAIR_AT.get(key) or 0) < 120:
        return {"attempted": False, "assigned": 0, "candidates": 0}
    base._ASSOCIATION_REPAIR_AT[key] = now
    try:
        existing = server.HISTORY_REPOSITORY.event_media(event.get("date"), cid, eid, include_failed=False)
    except Exception:
        existing = []
    if existing and not force:
        return {"attempted": False, "assigned": len(existing), "candidates": 0}

    candidates = base._league_source_media(server, cid)
    assigned = 0
    rejected_by_title_rule = 0
    alias_assigned = 0
    for item in candidates:
        allowed, _rule = _title_rule_allows(comp, item)
        if not allowed:
            rejected_by_title_rule += 1
            continue
        try:
            matched = None
            for variant in _event_alias_variants(event):
                scoped, evidence = server._history_media_match_evidence(dict(item), variant)
                if (
                    scoped.get("mediaScope") == "GAME"
                    and _clean((evidence or {}).get("associationState")).upper() == "ASSIGNED"
                ):
                    matched = (scoped, evidence, variant)
                    break
            if not matched:
                continue
            _scoped, evidence, variant = matched
            original_away = event.get("awayTeam") or event.get("away")
            original_home = event.get("homeTeam") or event.get("home")
            decorated = dict(item)
            decorated.update({
                "league": cid,
                "competitionId": cid,
                "competitionName": comp["name"],
                "eventId": eid,
                "matchId": eid,
                "scoreEventId": eid,
                "canonicalEventId": eid,
                "date": event.get("date"),
                "gameDate": event.get("date"),
                "__sbbDate": event.get("date"),
                "away": original_away,
                "home": original_home,
                "participantAliasMatch": {
                    "away": _clean((variant.get("awayTeam") or {}).get("name")),
                    "home": _clean((variant.get("homeTeam") or {}).get("name")),
                },
                "playlistTitleRuleMatched": bool(_rule),
            })
            added = int(server.HISTORY_REPOSITORY.put_event_media(event.get("date"), cid, eid, [decorated]) or 0)
            assigned += added
            if added and evidence.get("participantAliasMatch"):
                alias_assigned += added
        except Exception:
            continue
    return {
        "attempted": True,
        "assigned": assigned,
        "candidates": len(candidates),
        "titleRuleRejected": rejected_by_title_rule,
        "aliasAssigned": alias_assigned,
    }


def _objective_tier(value):
    value = _clean(value).lower()
    return {"quick": "green", "extended": "purple", "coverage": "blue", "green": "green", "purple": "purple", "blue": "blue"}.get(value, "green")


def _update_media_rules(server, body):
    cid = _clean(body.get("id") or body.get("competitionId") or body.get("league")).upper()
    comp = base._find(cid)
    if not comp:
        raise ValueError("Competition not found.")
    url = _clean(body.get("url") or body.get("playlistUrl") or body.get("playlistId"))
    if not url:
        raise ValueError("Playlist URL or ID is required.")
    tier = _objective_tier(body.get("tier") or body.get("objective"))
    required = _phrases(body.get("requiredTitlePhrases"))
    excluded = _phrases(body.get("excludedTitlePhrases"))
    media = deepcopy(comp.get("mediaSources") or {"green": [], "purple": [], "blue": []})
    for key in ("green", "purple", "blue"):
        media.setdefault(key, [])
    target_pid = _youtube_playlist_id(url)
    found = False
    updated = []
    for src in media[tier]:
        row = dict(src or {}) if isinstance(src, dict) else {"url": src}
        row_url = _clean(row.get("url") or row.get("playlistId"))
        same = row_url == url or (target_pid and _youtube_playlist_id(row_url) == target_pid)
        if same:
            row["url"] = row_url or url
            row["requiredTitlePhrases"] = required
            row["excludedTitlePhrases"] = excluded
            found = True
        updated.append(row)
    if not found:
        updated.append({
            "url": url,
            "requiredTitlePhrases": required,
            "excludedTitlePhrases": excluded,
        })
    media[tier] = updated
    raw = deepcopy(comp)
    raw["mediaSources"] = media
    events = list(comp.get("events") or [])
    saved = base.save_competition(raw, events, server)
    # save_competition already enrolls sources; force one explicit recrawl here
    # because the operator just changed association eligibility.
    persisted = base._find(cid)
    if persisted:
        base._register_media_sources(server, persisted, force_crawl=True)
    return {
        "competition": saved,
        "tier": tier,
        "url": url,
        "requiredTitlePhrases": required,
        "excludedTitlePhrases": excluded,
        "recrawlStarted": True,
    }


def _handle_post(server, handler, parsed):
    if parsed.path != "/api/competition-builder/media-rules":
        return _ORIGINAL_HANDLE_POST(server, handler, parsed)
    try:
        body = base._read_body(handler)
        result = _update_media_rules(server, body)
        return base._send(server, handler, {"ok": True, **result}, 200)
    except ValueError as exc:
        return base._send(server, handler, {"ok": False, "error": "BAD_MEDIA_RULE", "message": str(exc)}, 400)
    except Exception as exc:
        return base._send(server, handler, {"ok": False, "error": "MEDIA_RULE_UPDATE_FAILED", "message": str(exc)}, 500)


def _install_when_ready():
    global _ORIGINAL_REGISTER_MEDIA_SOURCES, _ORIGINAL_REPAIR_EVENT_MEDIA, _ORIGINAL_HANDLE_POST
    for _ in range(600):
        server = getattr(base, "_SERVER", None)
        if server is not None and hasattr(server, "_history_media_match_evidence"):
            break
        time.sleep(0.2)
    else:
        return

    _wrap_playlist_normalize(server)
    _wrap_server_matcher(server)

    if _ORIGINAL_REGISTER_MEDIA_SOURCES is None:
        _ORIGINAL_REGISTER_MEDIA_SOURCES = base._register_media_sources
        base._register_media_sources = _register_media_sources
    if _ORIGINAL_REPAIR_EVENT_MEDIA is None:
        _ORIGINAL_REPAIR_EVENT_MEDIA = base._repair_event_media
        base._repair_event_media = _repair_event_media
    if _ORIGINAL_HANDLE_POST is None:
        _ORIGINAL_HANDLE_POST = base._handle_post
        base._handle_post = _handle_post

    # Re-register existing custom competitions so media-rule metadata is copied
    # into the operator playlist registry without requiring recreation.
    for comp in base._load():
        try:
            base._register_media_sources(server, comp, force_crawl=False)
        except Exception:
            pass


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    threading.Thread(
        target=_install_when_ready,
        name="sbb-competition-builder-v4612-install",
        daemon=True,
    ).start()

"""NFL GAME-media source cutover to official club/native packages.

The official NFL YouTube weekly recap playlists have repeatedly produced GAME
assets that pass catalog validation but fail iframe playback in the deployed Big
Board.  Sports Big Board already has a stronger 32-club acquisition path: each
matchup walks both clubs' official video sitemaps, resolves the package page, and
validates native/direct media before promotion.

This adapter makes that existing club path authoritative without changing the
player, MediaManifest, canonical event, or score/ribbon ownership boundaries.
It intentionally preserves the old YouTube assets in history for audit purposes
while preventing them from satisfying current NFL GAME playback.
"""
from __future__ import annotations

import re
import sys
import threading
import time

_LOCK = threading.Lock()
_INSTALLED = False

# Both-team matching remains owned by server._nfl_team_title_disposition.  These
# patterns only widen the package vocabulary *after* that matcher has accepted
# the event identity and after its reaction/interview exclusions have run.
_ADDITIONAL_GAME_PACKAGE_RX = re.compile(
    r"\b(?:top plays?|game recap|cinematic recap|extended highlights?|full highlights?)\b",
    re.I,
)
_TEAM_REACTION_RX = re.compile(
    r"press conference|interview|game trailer|preview|mic.?d|victory sound|"
    r"film session|film room|players.? table|total access|insider|reaction|"
    r"post[- ]?game|speech",
    re.I,
)


def expanded_team_title_disposition(title, away, home, original):
    """Safely widen official-club GAME package titles.

    The original classifier is still the authority for event identity and the
    hard rejection classes.  We only promote titles that already matched both
    teams and that are not reaction/interview content.
    """
    base = original(title, away, home)
    if base in {"GAME_PACKAGE", "EVENT_MISMATCH", "POSTGAME_REACTION"}:
        return base
    text = str(title or "")
    if _TEAM_REACTION_RX.search(text):
        return "POSTGAME_REACTION"
    if _ADDITIONAL_GAME_PACKAGE_RX.search(text):
        return "GAME_PACKAGE"
    return base


def _is_team_source(item):
    row = dict(item or {})
    return bool(
        row.get("officialTeamSource")
        or str(row.get("provider") or "").upper() == "NFL-TEAM-SITE"
        or str(row.get("sourceType") or "").lower() == "official-nfl-team-video"
        or str(row.get("discoverySourceFamily") or "").lower() == "nfl-team-video"
    )


def team_media_objective(item, original):
    """Classify official club packages into the established Quick/Extended lanes."""
    if not _is_team_source(item):
        return original(item)

    row = dict(item or {})
    text = " ".join(str(row.get(k) or "") for k in ("title", "description")).lower()
    try:
        duration = int(row.get("durationSeconds") or row.get("duration") or 0)
    except Exception:
        duration = 0

    # A true full/condensed replay remains out of scope.  "Full Game Highlights"
    # is a highlights package, not a full-game replay, and is handled below.
    replay_text = re.sub(r"\bfull game highlights?\b", "", text)
    if re.search(r"\bcondensed game\b|\bfull[- ]game\b", replay_text):
        return ""

    # When duration is available, retain the existing American-football package
    # windows: Quick 45-390 s and Extended 540-1800 s.
    if duration:
        if 45 <= duration <= 390:
            return "quick"
        if 540 <= duration <= 1800:
            return "extended"
        return original(item)

    # Club CMS pages do not always publish duration metadata.  Strong package
    # labels provide an intentional fallback rather than discarding the asset.
    if re.search(r"\bfull game highlights?\b|\bextended highlights?\b|\bcinematic recap\b", text):
        return "extended"
    if re.search(r"\bgame highlights?\b|\btop plays?\b|\bgame recap\b|\bfull highlights?\b", text):
        return "quick"
    return original(item)


def _retired_playlist_asset(item, league):
    row = dict(item or {})
    if str(league or row.get("league") or "").upper() != "NFL":
        return False
    family = str(row.get("discoverySourceFamily") or "").lower()
    source_type = str(row.get("sourceType") or "").lower()
    return family == "nfl-youtube-playlist" or source_type == "official-nfl-youtube-playlist"


def install():
    """Patch the composed server once its NFL acquisition functions exist."""
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True

    def runner():
        deadline = time.time() + 90
        server = None
        required = (
            "_nfl_team_title_disposition",
            "_nfl_media_objective",
            "_nfl_team_video_results",
            "_nfl_public_video_results",
            "_nfl_youtube_playlist_results",
            "_history_persisted_candidate_disposition",
            "_game_media_source_registry",
        )
        while time.time() < deadline:
            main = sys.modules.get("__main__")
            imported = sys.modules.get("server")
            server = next(
                (mod for mod in (main, imported) if mod and all(callable(getattr(mod, name, None)) for name in required)),
                None,
            )
            if server:
                break
            time.sleep(0.2)
        if not server:
            return

        original_title = server._nfl_team_title_disposition
        original_objective = server._nfl_media_objective
        original_team_results = server._nfl_team_video_results
        original_public_results = server._nfl_public_video_results
        original_playlist_results = server._nfl_youtube_playlist_results
        original_persisted_disposition = server._history_persisted_candidate_disposition
        original_registry = server._game_media_source_registry

        if getattr(original_team_results, "__sbbNflClubSourceCutover", False):
            return

        state = {
            "installed": True,
            "teamQuickAccepted": 0,
            "teamExtendedAccepted": 0,
            "leaguePlaylistGameRequestsBlocked": 0,
            "legacyPlaylistCandidatesRetired": 0,
        }

        def title_guard(title, away, home):
            return expanded_team_title_disposition(title, away, home, original_title)

        def objective_guard(item):
            return team_media_objective(item, original_objective)

        def team_results_guard(date, away, home, max_items=6, validate_native=False, objective="quick"):
            rows = list(
                original_team_results(
                    date,
                    away,
                    home,
                    max_items=max_items,
                    validate_native=validate_native,
                    objective=objective,
                )
                or []
            )
            wanted = str(objective or "").lower()
            floor = 140 if wanted == "quick" else 138
            for row in rows:
                row["importance"] = max(floor, int(row.get("importance") or 0))
                row["sourcePriority"] = "PRIMARY"
                row["sourceLabel"] = row.get("sourceLabel") or "NFL Official Team Video"
                row["nflClubSourcePrimary"] = True
            if wanted == "quick":
                state["teamQuickAccepted"] += len(rows)
            elif wanted == "extended":
                state["teamExtendedAccepted"] += len(rows)
            return rows

        def public_results_guard(date, away, home, max_items=6, validate_native=False, allow_historical=False, objective="quick"):
            rows = list(
                original_public_results(
                    date,
                    away,
                    home,
                    max_items=max_items,
                    validate_native=validate_native,
                    allow_historical=allow_historical,
                    objective=objective,
                )
                or []
            )
            wanted = str(objective or "").lower()
            floor = 134 if wanted == "quick" else 132
            for row in rows:
                row["importance"] = max(floor, int(row.get("importance") or 0))
                row["sourcePriority"] = "SECONDARY"
            return rows

        def playlist_results_guard(date, away, home, max_items=8, objective="extended"):
            # Cut the failing league-owned embed source out of NFL GAME media.
            # The playlist catalog itself is retained for audit/history and can
            # still be inspected independently; it simply cannot satisfy Green
            # or Purple GAME acquisition anymore.
            if str(objective or "").lower() in {"quick", "extended"}:
                state["leaguePlaylistGameRequestsBlocked"] += 1
                return []
            return original_playlist_results(date, away, home, max_items=max_items, objective=objective)

        def persisted_disposition_guard(item, league, event_id, objective=""):
            if _retired_playlist_asset(item, league):
                state["legacyPlaylistCandidatesRetired"] += 1
                return "PERSISTENCE_NON_PLAYABLE"
            return original_persisted_disposition(item, league, event_id, objective=objective)

        def registry_guard():
            rows = [dict(x) for x in (original_registry() or [])]
            for row in rows:
                if str(row.get("league") or "").upper() != "NFL":
                    continue
                collector = str(row.get("collector") or "").lower()
                if collector == "nfl-team-video":
                    row.update(
                        {
                            "priority": "PRIMARY",
                            "title": "NFL Official Team Video Sites",
                            "active": True,
                            "notes": "Primary Green/Purple source. Scans both clubs for each matchup and validates native/direct media before promotion.",
                        }
                    )
                elif collector == "nfl-public-video":
                    row.update(
                        {
                            "priority": "SECONDARY",
                            "active": True,
                            "notes": "Secondary official NFL.com matchup package source after both club sites.",
                        }
                    )
                elif collector == "nfl-youtube-playlist":
                    row.update(
                        {
                            "priority": "RETIRED",
                            "active": False,
                            "notes": "Retained for audit/history only. Disabled for NFL GAME Green/Purple acquisition because league-owned embeds repeatedly fail deployed iframe playback.",
                        }
                    )
            return rows

        title_guard.__sbbNflClubSourceCutover = True
        objective_guard.__sbbNflClubSourceCutover = True
        team_results_guard.__sbbNflClubSourceCutover = True
        public_results_guard.__sbbNflClubSourceCutover = True
        playlist_results_guard.__sbbNflClubSourceCutover = True
        persisted_disposition_guard.__sbbNflClubSourceCutover = True
        registry_guard.__sbbNflClubSourceCutover = True

        server._nfl_team_title_disposition = title_guard
        server._nfl_media_objective = objective_guard
        server._nfl_team_video_results = team_results_guard
        server._nfl_public_video_results = public_results_guard
        server._nfl_youtube_playlist_results = playlist_results_guard
        server._history_persisted_candidate_disposition = persisted_disposition_guard
        server._game_media_source_registry = registry_guard
        server.NFL_CLUB_SOURCE_CUTOVER_STATE = state

    threading.Thread(target=runner, name="sbb-nfl-club-source-cutover", daemon=True).start()


def snapshot():
    main = sys.modules.get("__main__")
    imported = sys.modules.get("server")
    server = main if main and hasattr(main, "NFL_CLUB_SOURCE_CUTOVER_STATE") else imported
    return dict(getattr(server, "NFL_CLUB_SOURCE_CUTOVER_STATE", {}) or {}) if server else {}

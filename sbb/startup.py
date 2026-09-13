"""Deterministic Sports Big Board backend startup registration.

Priority 1 ownership consolidation makes backend startup explicit and inspectable
without changing the legacy import/install timing contract. The old ``sbb`` package
pre-imported several compatibility modules before invoking their installers; those
phases are represented here deliberately so consolidation does not become a hidden
startup-order rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import threading
import time
from typing import Any


@dataclass(frozen=True)
class StartupRegistration:
    key: str
    module: str
    installer: str = "install"


@dataclass(frozen=True)
class StartupPhase:
    name: str
    load_keys: tuple[str, ...]
    install_keys: tuple[str, ...]


# Flat install order is the application contract and is also useful for startup
# diagnostics. Backend Inspector now registers through the shared route table; the
# shared dispatcher is installed last so every unmigrated Handler wrapper remains
# beneath it as a compatibility fallback.
STARTUP_REGISTRATIONS = (
    StartupRegistration("nfl-weekly-playlists", "nfl_weekly_playlists"),
    StartupRegistration("competition-builder", "competition_builder"),
    StartupRegistration("competition-builder-v467", "competition_builder_v467"),
    StartupRegistration("historical-media-v4610", "historical_media_v4610"),
    StartupRegistration("competition-builder-v4612", "competition_builder_v4612"),
    StartupRegistration("competition-builder-v4613", "competition_builder_v4613"),
    StartupRegistration("competition-builder-v4614", "competition_builder_v4614"),
    StartupRegistration("competition-builder-v4615", "competition_builder_v4615"),
    StartupRegistration("special-event-media-v4616", "special_event_media_v4616"),
    StartupRegistration("tennis-ribbon-projection", "tennis_ribbon_projection"),
    StartupRegistration("ribbon-authority-v521", "ribbon_authority_v521"),
    StartupRegistration("day-state", "day_state"),
    StartupRegistration("ribbon-snapshot-v520", "ribbon_snapshot_v520"),
    StartupRegistration("game-center-multisport", "game_center_multisport"),
    StartupRegistration("ncaaf-game-center", "ncaaf_game_center"),
    StartupRegistration("history-readiness-repair", "history_readiness_repair"),
    StartupRegistration("ncaaf-namespace-reset", "ncaaf_namespace_reset"),
    StartupRegistration("runtime-path-repair-v5110", "runtime_path_repair_v5110"),
    StartupRegistration("database-authority", "database_authority"),
    StartupRegistration("backend-inspector-api", "backend_inspector_routes"),
    StartupRegistration("ncaaf-ranked", "ncaaf_ranked"),
    StartupRegistration("media-runtime-repair-v5116", "media_runtime_repair_v5116"),
    StartupRegistration("media-authority-v5117", "media_authority_v5117"),
    StartupRegistration("tennis-game-center", "tennis_game_center"),
    StartupRegistration("game-center-identity-v5122", "game_center_identity_v5122"),
    StartupRegistration("current-news-v522", "current_news_v522"),
    StartupRegistration("release-identity-v523", "release_identity_v523"),
    StartupRegistration("integrity-lane-v523", "integrity_lane_v523"),
    StartupRegistration("backend-snapshot-v523", "backend_snapshot_v523"),
    StartupRegistration("current-news-v523", "current_news_v523"),
    StartupRegistration("team-focus-v537", "team_focus_v537"),
    StartupRegistration("league-view-v538", "league_view_v538"),
    StartupRegistration("canonical-shadow-v600", "canonical_shadow_v600"),
    StartupRegistration("canonical-certification-v610", "canonical_certification_v610"),
    StartupRegistration("canonical-epl-fpl-state-v6116", "canonical_epl_fpl_state_followup_v6116"),
    StartupRegistration("nfl-club-sources", "nfl_club_sources"),
    StartupRegistration("nfl-audit-migration", "nfl_audit_migration"),
    StartupRegistration("shared-route-dispatcher", "route_registry"),
)

_REGISTRATION_BY_KEY = {item.key: item for item in STARTUP_REGISTRATIONS}

# These phases mirror the previous sbb/__init__.py *import timing* as well as its
# install order. In particular, the first compatibility modules are all imported
# before any installer runs, then later modules are loaded at the same boundaries
# where the legacy file imported them.
STARTUP_PHASES = (
    StartupPhase(
        "legacy-initial-imports",
        (
            "nfl-weekly-playlists", "competition-builder", "competition-builder-v467",
            "historical-media-v4610", "competition-builder-v4612", "competition-builder-v4613",
            "competition-builder-v4614", "competition-builder-v4615", "special-event-media-v4616",
            "day-state", "ribbon-authority-v521", "tennis-ribbon-projection",
            "game-center-multisport", "history-readiness-repair", "runtime-path-repair-v5110",
            "database-authority", "backend-inspector-api",
        ),
        (
            "nfl-weekly-playlists", "competition-builder", "competition-builder-v467",
            "historical-media-v4610", "competition-builder-v4612", "competition-builder-v4613",
            "competition-builder-v4614", "competition-builder-v4615", "special-event-media-v4616",
            "tennis-ribbon-projection", "ribbon-authority-v521", "day-state",
        ),
    ),
    StartupPhase("ribbon-snapshot", ("ribbon-snapshot-v520",), ("ribbon-snapshot-v520", "game-center-multisport")),
    StartupPhase("ncaaf-game-center", ("ncaaf-game-center",), ("ncaaf-game-center", "history-readiness-repair")),
    StartupPhase(
        "ncaaf-and-database-authority",
        ("ncaaf-namespace-reset", "ncaaf-ranked"),
        ("ncaaf-namespace-reset", "runtime-path-repair-v5110", "database-authority", "backend-inspector-api", "ncaaf-ranked"),
    ),
    StartupPhase(
        "media-runtime",
        ("media-runtime-repair-v5116", "media-authority-v5117", "tennis-game-center"),
        ("media-runtime-repair-v5116", "media-authority-v5117", "tennis-game-center"),
    ),
    StartupPhase("game-center-identity", ("game-center-identity-v5122",), ("game-center-identity-v5122",)),
    StartupPhase("current-news-v522", ("current-news-v522",), ("current-news-v522",)),
    StartupPhase(
        "release-integrity-news-v523",
        ("release-identity-v523", "integrity-lane-v523", "backend-snapshot-v523", "current-news-v523"),
        ("release-identity-v523", "integrity-lane-v523", "backend-snapshot-v523", "current-news-v523"),
    ),
    StartupPhase("team-focus", ("team-focus-v537",), ("team-focus-v537",)),
    StartupPhase("league-view", ("league-view-v538",), ("league-view-v538",)),
    StartupPhase("canonical-shadow", ("canonical-shadow-v600",), ("canonical-shadow-v600",)),
    StartupPhase("canonical-certification", ("canonical-certification-v610",), ("canonical-certification-v610",)),
    StartupPhase("canonical-epl-fpl-state-v6116", ("canonical-epl-fpl-state-v6116",), ("canonical-epl-fpl-state-v6116",)),
    StartupPhase("nfl-club-sources", ("nfl-club-sources",), ("nfl-club-sources",)),
    StartupPhase("nfl-audit-migration", ("nfl-audit-migration",), ("nfl-audit-migration",)),
    StartupPhase("shared-route-authority", ("shared-route-dispatcher",), ("shared-route-dispatcher",)),
)

_LOCK = threading.RLock()
_BOOTSTRAPPING = False
_BOOTSTRAPPED = False
_RESULTS: list[dict[str, Any]] = []
_MODULES: dict[str, Any] = {}


def _record(
    registration: StartupRegistration,
    *,
    stage: str,
    phase: str,
    started_at: float,
    result: Any = None,
    error: BaseException | None = None,
) -> None:
    finished_at = time.time()
    _RESULTS.append(
        {
            "key": registration.key,
            "module": registration.module,
            "installer": registration.installer,
            "stage": stage,
            "phase": phase,
            "ok": error is None,
            "result": result if isinstance(result, (bool, int, float, str, type(None))) else type(result).__name__,
            "error": "" if error is None else f"{type(error).__name__}: {error}",
            "startedAt": started_at,
            "finishedAt": finished_at,
            "durationMs": round((finished_at - started_at) * 1000.0, 3),
        }
    )


def _load(key: str, phase: str) -> None:
    if key in _MODULES:
        return
    registration = _REGISTRATION_BY_KEY[key]
    started_at = time.time()
    try:
        module = import_module(f".{registration.module}", __package__)
    except BaseException as exc:
        with _LOCK:
            _record(registration, stage="IMPORT", phase=phase, started_at=started_at, error=exc)
        raise
    _MODULES[key] = module


def _install(key: str, phase: str) -> None:
    registration = _REGISTRATION_BY_KEY[key]
    if key not in _MODULES:
        _load(key, phase)
    started_at = time.time()
    try:
        installer = getattr(_MODULES[key], registration.installer)
        result = installer()
    except BaseException as exc:
        with _LOCK:
            _record(registration, stage="INSTALL", phase=phase, started_at=started_at, error=exc)
        raise
    with _LOCK:
        _record(registration, stage="INSTALL", phase=phase, started_at=started_at, result=result)


def bootstrap() -> bool:
    """Run the legacy-compatible startup phases once in deterministic order."""
    global _BOOTSTRAPPING, _BOOTSTRAPPED
    with _LOCK:
        if _BOOTSTRAPPED or _BOOTSTRAPPING:
            return False
        _BOOTSTRAPPING = True
        _RESULTS.clear()
        _MODULES.clear()

    try:
        for phase in STARTUP_PHASES:
            for key in phase.load_keys:
                _load(key, phase.name)
            for key in phase.install_keys:
                _install(key, phase.name)
        with _LOCK:
            _BOOTSTRAPPED = True
        return True
    finally:
        with _LOCK:
            _BOOTSTRAPPING = False


def startup_snapshot() -> dict[str, Any]:
    with _LOCK:
        install_results = [item for item in _RESULTS if item.get("stage") == "INSTALL"]
        return {
            "bootstrapping": _BOOTSTRAPPING,
            "bootstrapped": _BOOTSTRAPPED,
            "registered": len(STARTUP_REGISTRATIONS),
            "phases": len(STARTUP_PHASES),
            "loaded": len(_MODULES),
            "completed": len(install_results),
            "services": [dict(item) for item in _RESULTS],
        }


__all__ = [
    "StartupRegistration", "StartupPhase", "STARTUP_REGISTRATIONS", "STARTUP_PHASES",
    "bootstrap", "startup_snapshot",
]

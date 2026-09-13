"""Deterministic Sports Big Board backend startup registration.

Priority 1 ownership consolidation: keep the existing installer behavior and order,
but make startup explicit, inspectable, and testable instead of scattering import-
time installer calls through ``sbb.__init__``.

This is intentionally a compatibility bridge. Individual services may continue to
use their existing ``install()`` implementations while they migrate to dependency
injection and the shared route registry.
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


# Order is part of the production contract. This list is a direct projection of
# the legacy sbb/__init__.py installer order as of v6.1.16, followed by the new
# shared route dispatcher so it becomes the outermost compatibility authority.
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
    StartupRegistration("nfl-club-sources", "nfl_club_sources"),
    StartupRegistration("nfl-audit-migration", "nfl_audit_migration"),
    StartupRegistration("shared-route-dispatcher", "route_registry"),
)

_LOCK = threading.RLock()
_BOOTSTRAPPING = False
_BOOTSTRAPPED = False
_RESULTS: list[dict[str, Any]] = []


def _record(registration: StartupRegistration, *, started_at: float, result: Any = None, error: BaseException | None = None) -> None:
    finished_at = time.time()
    _RESULTS.append(
        {
            "key": registration.key,
            "module": registration.module,
            "installer": registration.installer,
            "ok": error is None,
            "result": result if isinstance(result, (bool, int, float, str, type(None))) else type(result).__name__,
            "error": "" if error is None else f"{type(error).__name__}: {error}",
            "startedAt": started_at,
            "finishedAt": finished_at,
            "durationMs": round((finished_at - started_at) * 1000.0, 3),
        }
    )


def bootstrap() -> bool:
    """Install every registered backend service once, in deterministic order.

    Returns ``True`` only for the caller that performs startup. Repeated imports
    are no-ops. A failed installer remains fail-fast, matching the legacy import
    behavior, while leaving an inspectable startup trace for diagnosis.
    """
    global _BOOTSTRAPPING, _BOOTSTRAPPED
    with _LOCK:
        if _BOOTSTRAPPED or _BOOTSTRAPPING:
            return False
        _BOOTSTRAPPING = True
        _RESULTS.clear()

    try:
        for registration in STARTUP_REGISTRATIONS:
            started_at = time.time()
            try:
                module = import_module(f".{registration.module}", __package__)
                installer = getattr(module, registration.installer)
                result = installer()
            except BaseException as exc:
                with _LOCK:
                    _record(registration, started_at=started_at, error=exc)
                raise
            else:
                with _LOCK:
                    _record(registration, started_at=started_at, result=result)
        with _LOCK:
            _BOOTSTRAPPED = True
        return True
    finally:
        with _LOCK:
            _BOOTSTRAPPING = False


def startup_snapshot() -> dict[str, Any]:
    with _LOCK:
        return {
            "bootstrapping": _BOOTSTRAPPING,
            "bootstrapped": _BOOTSTRAPPED,
            "registered": len(STARTUP_REGISTRATIONS),
            "completed": len(_RESULTS),
            "services": [dict(item) for item in _RESULTS],
        }


__all__ = ["StartupRegistration", "STARTUP_REGISTRATIONS", "bootstrap", "startup_snapshot"]

"""NFL media-audit migration for the club/native source cutover.

This module makes the background official-source audit perform the actual NFL
Green/Purple turnover after the league-owned YouTube recap playlists were
retired from playback. Existing source-media rows are preserved for provenance,
but retired playlist assets are marked runtime-failed so they no longer satisfy
the audit's Green/Extended objective flags.
"""
from __future__ import annotations

import sys
import threading
import time

_LOCK = threading.Lock()
_INSTALLED = False
_RETIRE_REASON = "SOURCE_RETIRED:NFL_YOUTUBE_PLAYLIST"
_POLICY_VERSION = 2


def active_nfl_audit_sources():
    """Return the active NFL audit stack in objective/fallback order."""
    return [
        {"key": "nfl-team-video-quick", "version": _POLICY_VERSION, "objective": "quick", "sourceFamily": "nfl-team-video"},
        {"key": "nfl-public-video-quick", "version": _POLICY_VERSION, "objective": "quick", "sourceFamily": "nfl-public-video"},
        {"key": "nfl-team-video-extended", "version": _POLICY_VERSION, "objective": "extended", "sourceFamily": "nfl-team-video"},
        {"key": "nfl-public-video-extended", "version": _POLICY_VERSION, "objective": "extended", "sourceFamily": "nfl-public-video"},
    ]


def configure_audit_sources(server):
    """Replace retired playlist audit lanes and bump replacement-source versions."""
    sources = getattr(server, "HISTORY_OFFICIAL_CATCHUP_SOURCES", None)
    if not isinstance(sources, dict):
        return False
    sources["NFL"] = [dict(row) for row in active_nfl_audit_sources()]
    return True


def _is_source_retired_item(item, league="NFL"):
    row = dict(item or {})
    if str(league or row.get("league") or "").upper() != "NFL":
        return False
    if bool(row.get("sourceRetired")) and str(row.get("sourceRetiredReason") or "").startswith("SOURCE_RETIRED:NFL_YOUTUBE_PLAYLIST"):
        return True
    family = str(row.get("discoverySourceFamily") or "").lower()
    source_type = str(row.get("sourceType") or "").lower()
    return family == "nfl-youtube-playlist" or source_type == "official-nfl-youtube-playlist"


def retire_persisted_playlist_assets(repository, now=None):
    """Mark assigned legacy NFL playlist assets runtime-failed without deleting them.

    The history audit's objective SQL only counts VERIFIED GAME assets whose
    runtime state is not FAILED. Marking the retired source FAILED therefore
    reopens Green/Purple gaps naturally while retaining the media row and event
    association for audit/provenance.
    """
    if repository is None or not callable(getattr(repository, "_connect", None)):
        return {"matched": 0, "retired": 0}
    now = float(now or time.time())
    matched = retired = 0
    lock = getattr(repository, "_lock", _LOCK)
    with lock:
        conn = repository._connect()
        try:
            rows = conn.execute(
                """SELECT DISTINCT s.asset_key,s.asset_json,s.runtime_state,s.runtime_failure_reason
                   FROM history_source_media s
                   JOIN history_event_media em ON em.asset_key=s.asset_key
                   JOIN history_catalog_event e ON e.canonical_event_key=em.canonical_event_key
                   WHERE e.league='NFL' AND em.association_state='ASSIGNED'
                     AND (
                       lower(COALESCE(json_extract(s.asset_json,'$.discoverySourceFamily'),''))='nfl-youtube-playlist'
                       OR lower(COALESCE(json_extract(s.asset_json,'$.sourceType'),''))='official-nfl-youtube-playlist'
                       OR (
                         COALESCE(json_extract(s.asset_json,'$.sourceRetired'),0)=1
                         AND COALESCE(json_extract(s.asset_json,'$.sourceRetiredReason'),'') LIKE 'SOURCE_RETIRED:NFL_YOUTUBE_PLAYLIST%'
                       )
                     )"""
            ).fetchall()
            matched = len(rows)
            for row in rows:
                item = repository._load_obj(row["asset_json"])
                already = (
                    str(row["runtime_state"] or "").upper() == "FAILED"
                    and str(row["runtime_failure_reason"] or "") == _RETIRE_REASON
                    and bool(item.get("sourceRetired"))
                )
                if already:
                    continue
                item["verifiedPlayable"] = False
                item["runtimeState"] = "failed"
                item["runtimeCatalogState"] = "FAILED"
                item["runtimeFailureReason"] = _RETIRE_REASON
                item["sourceRetired"] = True
                item["sourceRetiredReason"] = _RETIRE_REASON
                item.setdefault("sourceRetiredAt", now)
                conn.execute(
                    """UPDATE history_source_media
                       SET asset_json=?,runtime_state='FAILED',runtime_failure_at=?,runtime_failure_reason=?,updated_at=?
                       WHERE asset_key=?""",
                    (repository._dump_obj(item), now, _RETIRE_REASON, now, str(row["asset_key"])),
                )
                retired += 1
            conn.commit()
        finally:
            conn.close()
    return {"matched": matched, "retired": retired}


def persisted_disposition(item, league, event_id, objective, original):
    """Keep retired rows non-playable even if another discovery pass rehydrates them."""
    if _is_source_retired_item(item, league):
        return "PERSISTENCE_NON_PLAYABLE"
    return original(item, league, event_id, objective=objective)


def install():
    """Install once after server history/audit objects have been composed."""
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True

    def runner():
        deadline = time.time() + 90
        server = None
        while time.time() < deadline:
            main = sys.modules.get("__main__")
            imported = sys.modules.get("server")
            server = next(
                (
                    mod
                    for mod in (main, imported)
                    if mod
                    and isinstance(getattr(mod, "HISTORY_OFFICIAL_CATCHUP_SOURCES", None), dict)
                    and getattr(mod, "HISTORY_REPOSITORY", None) is not None
                    and callable(getattr(mod, "_history_persisted_candidate_disposition", None))
                ),
                None,
            )
            if server:
                break
            time.sleep(0.2)
        if not server:
            return

        original_disposition = server._history_persisted_candidate_disposition
        if getattr(original_disposition, "__sbbNflAuditMigration", False):
            return

        configured = configure_audit_sources(server)
        retired = retire_persisted_playlist_assets(server.HISTORY_REPOSITORY)

        def disposition_guard(item, league, event_id, objective=""):
            return persisted_disposition(item, league, event_id, objective, original_disposition)

        disposition_guard.__sbbNflAuditMigration = True
        server._history_persisted_candidate_disposition = disposition_guard
        server.NFL_AUDIT_SOURCE_MIGRATION_STATE = {
            "installed": True,
            "policyVersion": _POLICY_VERSION,
            "auditSourcesConfigured": bool(configured),
            "activeSources": active_nfl_audit_sources(),
            "retiredPlaylistAssetsMatched": int(retired.get("matched") or 0),
            "retiredPlaylistAssetsChanged": int(retired.get("retired") or 0),
            "historyPreserved": True,
        }

    threading.Thread(target=runner, name="sbb-nfl-audit-source-migration", daemon=True).start()


def snapshot():
    main = sys.modules.get("__main__")
    imported = sys.modules.get("server")
    server = main if main and hasattr(main, "NFL_AUDIT_SOURCE_MIGRATION_STATE") else imported
    return dict(getattr(server, "NFL_AUDIT_SOURCE_MIGRATION_STATE", {}) or {}) if server else {}


__all__ = [
    "active_nfl_audit_sources",
    "configure_audit_sources",
    "retire_persisted_playlist_assets",
    "persisted_disposition",
    "install",
    "snapshot",
]

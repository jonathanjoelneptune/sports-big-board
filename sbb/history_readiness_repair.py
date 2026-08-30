"""Sports Big Board v4.7.17 — database-first historical ribbon readiness.

Normalized SQLite verification state is the playback-readiness authority for
persisted GAME media.  Older asset_json snapshots may predate verifiedPlayable;
this repair derives that flag from history_source_media columns at read time so a
verified historical recap does not regress to FIND merely because it has never
been played in the current browser/session.
"""
from __future__ import annotations

import threading

from .history_repository import HistoryRepository

VERSION = "4.7.17-history-readiness-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ORIGINAL_HYDRATE = HistoryRepository._hydrate_asset


def _row_value(row, key, default=""):
    try:
        value = row[key]
    except Exception:
        try:
            value = row.get(key, default)
        except Exception:
            value = default
    return default if value is None else value


def _hydrate_asset(row):
    item = _ORIGINAL_HYDRATE(row)
    validation = str(_row_value(row, "validation_state", item.get("validationState") or "")).upper()
    runtime = str(_row_value(row, "runtime_state", item.get("runtimeCatalogState") or "UNKNOWN")).upper()
    has_transport = bool(str(item.get("youtubeId") or "").strip() or str(item.get("mediaUrl") or "").strip())
    if runtime == "FAILED":
        item["verifiedPlayable"] = False
    elif runtime == "PLAYED":
        item["verifiedPlayable"] = bool(has_transport)
    elif validation == "VERIFIED" and has_transport:
        item["verifiedPlayable"] = True
        item["databaseVerifiedPlayable"] = True
    else:
        # Normalized verification state supersedes a stale optimistic JSON flag.
        item["verifiedPlayable"] = False
    item["validationState"] = validation or "CANDIDATE"
    item["runtimeCatalogState"] = runtime or "UNKNOWN"
    return item


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        HistoryRepository._hydrate_asset = staticmethod(_hydrate_asset)
        _INSTALLED = True
        return True


__all__ = ["VERSION", "install", "_hydrate_asset"]

"""Sports Big Board v4.7.18 — database-first historical readiness repair.

Normalized SQLite validation/runtime columns remain the authority for persisted
media.  This layer repairs two legacy hydration gaps without doing any provider
search:
- old asset_json snapshots can omit ``verifiedPlayable`` even when SQLite says VERIFIED;
- old YouTube rows can retain only ``externalUrl`` even though their YouTube ID is
  recoverable locally.  Recovering that identity makes EVENT_MEDIA and Silver
  roundups immediately playable again instead of falling through to FIND/PENDING.
"""
from __future__ import annotations

import re
import threading
from urllib.parse import parse_qs, urlparse

from .history_repository import HistoryRepository

VERSION = "4.7.18-history-readiness-2"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ORIGINAL_HYDRATE = HistoryRepository._hydrate_asset
_ORIGINAL_ROUNDUP_MEDIA = HistoryRepository.roundup_media
_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def _row_value(row, key, default=""):
    try:
        value = row[key]
    except Exception:
        try:
            value = row.get(key, default)
        except Exception:
            value = default
    return default if value is None else value


def _youtube_id_from_url(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else "https://" + raw.lstrip("/"))
        host = (parsed.hostname or "").lower().removeprefix("www.")
        candidate = ""
        if host in {"youtu.be"}:
            candidate = parsed.path.strip("/").split("/", 1)[0]
        elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
            if parsed.path.rstrip("/") == "/watch":
                candidate = (parse_qs(parsed.query).get("v") or [""])[0]
            else:
                parts = [x for x in parsed.path.split("/") if x]
                if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live", "v"}:
                    candidate = parts[1]
        candidate = str(candidate or "").strip()
        return candidate if _YOUTUBE_ID_RE.fullmatch(candidate) else ""
    except Exception:
        return ""


def _repair_transport(item):
    """Recover a locally-provable playback transport without network I/O."""
    if not isinstance(item, dict):
        return False
    youtube_id = str(item.get("youtubeId") or "").strip()
    if not youtube_id:
        for key in ("externalUrl", "canonicalUrl", "url", "embedUrl"):
            youtube_id = _youtube_id_from_url(item.get(key))
            if youtube_id:
                item["youtubeId"] = youtube_id
                item["transportRecoveredFrom"] = key
                item.setdefault("provider", "YOUTUBE")
                break
    media_url = str(item.get("mediaUrl") or "").strip()
    if not media_url:
        external = str(item.get("externalUrl") or "").strip()
        # Only promote an external URL to native media when it is self-evidently a
        # direct asset. Brightcove/player pages remain external-only.
        if re.search(r"\.(?:mp4|m4v|webm|m3u8)(?:[?#]|$)", external, re.I):
            item["mediaUrl"] = external
            media_url = external
            item["transportRecoveredFrom"] = "externalUrl-direct"
    return bool(str(item.get("youtubeId") or "").strip() or media_url)


def _apply_database_truth(item, *, validation="", runtime=""):
    validation = str(validation or item.get("validationState") or "").upper()
    runtime = str(runtime or item.get("runtimeCatalogState") or "UNKNOWN").upper()
    has_transport = _repair_transport(item)
    if runtime == "FAILED":
        item["verifiedPlayable"] = False
    elif runtime == "PLAYED":
        item["verifiedPlayable"] = bool(has_transport)
    elif validation == "VERIFIED" and has_transport:
        item["verifiedPlayable"] = True
        item["databaseVerifiedPlayable"] = True
    else:
        # Normalized verification state supersedes stale optimistic JSON.
        item["verifiedPlayable"] = False
    item["validationState"] = validation or "CANDIDATE"
    item["runtimeCatalogState"] = runtime or "UNKNOWN"
    return item


def _hydrate_asset(row):
    item = _ORIGINAL_HYDRATE(row)
    canonical_url = str(_row_value(row, "canonical_url", "") or "").strip()
    if canonical_url and not item.get("canonicalUrl"):
        item["canonicalUrl"] = canonical_url
    provider = str(_row_value(row, "provider", item.get("provider") or "") or "").upper()
    provider_media_id = str(_row_value(row, "provider_media_id", "") or "").strip()
    if not item.get("youtubeId") and "YOUTUBE" in provider and _YOUTUBE_ID_RE.fullmatch(provider_media_id):
        item["youtubeId"] = provider_media_id
        item["transportRecoveredFrom"] = "provider_media_id"
    return _apply_database_truth(
        item,
        validation=_row_value(row, "validation_state", item.get("validationState") or ""),
        runtime=_row_value(row, "runtime_state", item.get("runtimeCatalogState") or "UNKNOWN"),
    )


def _roundup_media(self, date, league=None):
    """Keep Silver read-only and database-first while repairing old transport JSON."""
    rows = _ORIGINAL_ROUNDUP_MEDIA(self, date, league)
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        _apply_database_truth(
            item,
            validation=item.get("validationState") or "",
            runtime=item.get("runtimeCatalogState") or "UNKNOWN",
        )
    return rows


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        HistoryRepository._hydrate_asset = staticmethod(_hydrate_asset)
        HistoryRepository.roundup_media = _roundup_media
        _INSTALLED = True
        return True


__all__ = [
    "VERSION", "install", "_hydrate_asset", "_roundup_media",
    "_youtube_id_from_url", "_repair_transport", "_apply_database_truth",
]

"""Sports Big Board v5.1.17 — durable verified event-media authority.

Once an exact GAME asset has been ASSIGNED to a canonical event and the source is
VERIFIED with a real playback transport, that relationship becomes durable local
truth. Later discovery/audit/classifier passes may add better media, but they cannot
silently make a previously-complete game fall back to FIND MEDIA merely because the
same source was not rediscovered or a generic matcher changed its opinion.

A lock is vetoed only by a real runtime FAILED state. The lock itself is retained so
an asset that is revalidated can immediately return without rediscovery.
"""
from __future__ import annotations

import copy
import json
import threading
import time
from contextlib import closing

from .history_repository import HistoryRepository

VERSION = "5.1.17-media-authority-lock-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False

_ORIG_EVENT_MEDIA = None
_ORIG_RIBBON_MEDIA = None
_ORIG_PUT_EVENT_MEDIA = None
_ORIG_RECORD_RUNTIME = None
_ORIG_RECORD_VERIFICATION = None
_ORIG_REPAIR_EVENT = None

_LOCK_TABLE = "history_event_media_lock"
_TABLE_LOCK = threading.RLock()
_INITIALIZED_PATHS = set()
_RISKY_METHODS = {
    "MULTI_EVENT_CANDIDATE_ENCOUNTER",
    "CROSS_EVENT_ASSET_CONFLICT",
    "TITLE_TEAM_PAIR_CONFLICT",
    "TEAM_FIELD_CONFLICT",
    "DATE_MISMATCH",
    "SEASON_MISMATCH",
    "NON_GAME_SCOPE_EVENT_LINK",
    "UNPROVEN_GAME_ASSOCIATION",
    "V5116_TITLE_PAIR_CONFLICT",
}


def _clean(v):
    return str(v or "").strip()


def _transport(item):
    if not isinstance(item, dict):
        return False
    if _clean(item.get("youtubeId")):
        return True
    if _clean(item.get("mediaUrl")):
        return True
    # A direct canonical URL or provider media id can be sufficient because the
    # existing readiness repair can reconstruct YouTube/native transport locally.
    return bool(_clean(item.get("canonicalUrl")) or _clean(item.get("providerMediaId")))


def _init_lock_table(repo):
    now = time.time()
    with repo._lock, closing(repo._connect()) as conn:
        conn.execute(
            f"""CREATE TABLE IF NOT EXISTS {_LOCK_TABLE} (
                canonical_event_key TEXT NOT NULL,
                asset_key TEXT NOT NULL,
                lock_reason TEXT NOT NULL DEFAULT '',
                locked_at REAL NOT NULL DEFAULT 0,
                last_confirmed_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(canonical_event_key,asset_key),
                FOREIGN KEY(canonical_event_key) REFERENCES history_catalog_event(canonical_event_key) ON DELETE CASCADE,
                FOREIGN KEY(asset_key) REFERENCES history_source_media(asset_key) ON DELETE CASCADE
            )"""
        )
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_media_lock_asset ON {_LOCK_TABLE}(asset_key)")
        conn.execute(
            "INSERT INTO history_catalog_meta(key,value,updated_at) VALUES('media_authority_lock_version',?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (VERSION, now),
        )
        conn.commit()


def _ensure_lock_table(repo):
    path=_clean(getattr(repo,"path","") or id(repo))
    with _TABLE_LOCK:
        if path in _INITIALIZED_PATHS:return True
        _init_lock_table(repo)
        _INITIALIZED_PATHS.add(path)
    return True


def _eligible_rows(conn, *, canonical_key="", asset_key=""):
    clauses = [
        "em.association_state='ASSIGNED'",
        "UPPER(COALESCE(s.validation_state,''))='VERIFIED'",
        "UPPER(COALESCE(s.runtime_state,''))<>'FAILED'",
        "UPPER(COALESCE(s.scope,''))='GAME'",
        "COALESCE(em.association_confidence,0)>=0.90",
        "UPPER(COALESCE(em.association_method,'')) NOT IN (%s)" % ",".join("?" for _ in _RISKY_METHODS),
        "(COALESCE(s.canonical_url,'')<>'' OR COALESCE(s.provider_media_id,'')<>'' OR COALESCE(json_extract(s.asset_json,'$.youtubeId'),'')<>'' OR COALESCE(json_extract(s.asset_json,'$.mediaUrl'),'')<>'')",
        # Do not permanently bless the specific legacy LLWS restore class that
        # v5.1.16 proved can contain unrelated games.
        "NOT (UPPER(COALESCE(e.league,'')) LIKE 'LLWS%' AND UPPER(COALESCE(em.association_method,''))='V4721_DATABASE_AUTHORITY_RESTORE')",
    ]
    params = [*sorted(_RISKY_METHODS)]
    if canonical_key:
        clauses.append("em.canonical_event_key=?")
        params.append(str(canonical_key))
    if asset_key:
        clauses.append("em.asset_key=?")
        params.append(str(asset_key))
    sql = f"""SELECT em.canonical_event_key,em.asset_key,em.association_method,em.association_confidence,e.league
      FROM history_event_media em
      JOIN history_catalog_event e ON e.canonical_event_key=em.canonical_event_key
      JOIN history_source_media s ON s.asset_key=em.asset_key
      WHERE {' AND '.join(clauses)}"""
    return conn.execute(sql, params).fetchall()


def _lock_eligible(repo, *, canonical_key="", asset_key="", reason="VERIFIED_ASSIGNED_GAME_MEDIA"):
    _ensure_lock_table(repo)
    now = time.time()
    count = 0
    with repo._lock, closing(repo._connect()) as conn:
        try:
            rows = _eligible_rows(conn, canonical_key=canonical_key, asset_key=asset_key)
        except Exception:
            return 0
        for row in rows:
            method = _clean(row["association_method"])
            lock_reason = f"{reason}:{method or 'ASSIGNED'}"
            cur = conn.execute(
                f"""INSERT INTO {_LOCK_TABLE}(canonical_event_key,asset_key,lock_reason,locked_at,last_confirmed_at)
                    VALUES(?,?,?,?,?)
                    ON CONFLICT(canonical_event_key,asset_key) DO UPDATE SET
                      lock_reason=excluded.lock_reason,last_confirmed_at=excluded.last_confirmed_at""",
                (row["canonical_event_key"], row["asset_key"], lock_reason, now, now),
            )
            count += 1 if cur.rowcount else 0
            # Freeze the normalized relationship/scope at the moment it becomes
            # durable authority. Discovery can enrich it, but generic reclassification
            # cannot silently demote this exact event asset later.
            conn.execute(
                "UPDATE history_source_media SET catalog_state='ASSIGNED',quarantine_reason='',scope='GAME',updated_at=? WHERE asset_key=? AND UPPER(COALESCE(runtime_state,''))<>'FAILED'",
                (now, row["asset_key"]),
            )
        conn.commit()
    return count


def _restore_locked_links(repo, *, canonical_key="", asset_key=""):
    try:_ensure_lock_table(repo)
    except Exception:return 0
    now = time.time()
    clauses = ["UPPER(COALESCE(s.runtime_state,''))<>'FAILED'"]
    params = []
    if canonical_key:
        clauses.append("l.canonical_event_key=?")
        params.append(str(canonical_key))
    if asset_key:
        clauses.append("l.asset_key=?")
        params.append(str(asset_key))
    with repo._lock, closing(repo._connect()) as conn:
        try:
            rows = conn.execute(
                f"""SELECT l.canonical_event_key,l.asset_key,l.lock_reason
                    FROM {_LOCK_TABLE} l
                    JOIN history_source_media s ON s.asset_key=l.asset_key
                    WHERE {' AND '.join(clauses)}""",
                params,
            ).fetchall()
        except Exception:
            return 0
        restored = 0
        for row in rows:
            cur = conn.execute(
                """INSERT INTO history_event_media(
                     canonical_event_key,asset_key,association_state,association_confidence,
                     association_method,association_evidence,matcher_version,first_associated_at,updated_at)
                   VALUES(?,?,'ASSIGNED',0.995,'V5117_LOCKED_VERIFIED_MEDIA',?,5117,?,?)
                   ON CONFLICT(canonical_event_key,asset_key) DO UPDATE SET
                     association_state='ASSIGNED',
                     association_confidence=MAX(COALESCE(history_event_media.association_confidence,0),0.995),
                     association_method='V5117_LOCKED_VERIFIED_MEDIA',
                     association_evidence=excluded.association_evidence,
                     matcher_version=MAX(COALESCE(history_event_media.matcher_version,0),5117),
                     updated_at=excluded.updated_at""",
                (row["canonical_event_key"], row["asset_key"], f"durable media authority lock: {row['lock_reason']}", now, now),
            )
            restored += int(cur.rowcount or 0)
            conn.execute(
                "UPDATE history_source_media SET catalog_state='ASSIGNED',quarantine_reason='',scope='GAME',updated_at=? WHERE asset_key=?",
                (now, row["asset_key"]),
            )
        conn.commit()
    return restored


def _hydrate_locked(repo, row, key):
    item = repo._hydrate_asset(row)
    item["canonicalEventKey"] = key
    item["associationConfidence"] = max(float(row["association_confidence"] or 0), 0.995)
    item["associationMethod"] = "V5117_LOCKED_VERIFIED_MEDIA"
    item["associationEvidence"] = f"durable media authority lock: {_clean(row['lock_reason'])}"
    item["mediaAuthorityLocked"] = True
    item["mediaAuthorityLockReason"] = _clean(row["lock_reason"])
    item["mediaAuthorityLockedAt"] = float(row["locked_at"] or 0)
    item["validationState"] = _clean(row["validation_state"] or "VERIFIED").upper()
    runtime = _clean(row["runtime_state"] or "UNKNOWN").upper()
    item["runtimeCatalogState"] = runtime
    has_transport = _transport(item)
    item["verifiedPlayable"] = bool(runtime != "FAILED" and has_transport)
    return item


def _locked_event_rows(repo, key):
    try:
        with closing(repo._read_connect()) as conn:
            return conn.execute(
                f"""SELECT s.*,l.lock_reason,l.locked_at,l.last_confirmed_at,
                      COALESCE(em.association_confidence,0.995) association_confidence
                    FROM {_LOCK_TABLE} l
                    JOIN history_source_media s ON s.asset_key=l.asset_key
                    LEFT JOIN history_event_media em ON em.canonical_event_key=l.canonical_event_key AND em.asset_key=l.asset_key
                    WHERE l.canonical_event_key=?
                    ORDER BY l.last_confirmed_at DESC,s.verified_at DESC,s.updated_at DESC""",
                (key,),
            ).fetchall()
    except Exception:
        return []


def _event_media(self, date, league, event_id, include_failed=True):
    base = list(_ORIG_EVENT_MEDIA(self, date, league, event_id, include_failed=include_failed) or [])
    key = self.canonical_event_key(league, event_id)
    by_asset = {str((x or {}).get("assetKey") or ""): x for x in base if isinstance(x, dict) and (x or {}).get("assetKey")}
    for row in _locked_event_rows(self, key):
        runtime = _clean(row["runtime_state"]).upper()
        if runtime == "FAILED" and not include_failed:
            continue
        item = _hydrate_locked(self, row, key)
        asset = _clean(item.get("assetKey"))
        if asset in by_asset:
            by_asset[asset].update({
                "mediaAuthorityLocked": True,
                "mediaAuthorityLockReason": item.get("mediaAuthorityLockReason"),
                "mediaAuthorityLockedAt": item.get("mediaAuthorityLockedAt"),
            })
            if runtime != "FAILED" and _transport(by_asset[asset]):
                by_asset[asset]["verifiedPlayable"] = True
        else:
            base.append(item)
            if asset:
                by_asset[asset] = item
    return base


def _ribbon_media_for_date(self, date, leagues=None, include_failed=False):
    out = dict(_ORIG_RIBBON_MEDIA(self, date, leagues=leagues, include_failed=include_failed) or {})
    date = _clean(date)[:10]
    selected = [str(x or "").upper() for x in (leagues or []) if _clean(x)]
    clauses = ["e.event_date=?"]
    params = [date]
    if selected:
        clauses.append("e.league IN (%s)" % ",".join("?" for _ in selected))
        params.extend(selected)
    if not include_failed:
        clauses.append("UPPER(COALESCE(s.runtime_state,''))<>'FAILED'")
    try:
        with closing(self._read_connect()) as conn:
            rows = conn.execute(
                f"""SELECT e.canonical_event_key,e.event_id,s.*,l.lock_reason,l.locked_at,l.last_confirmed_at,
                      COALESCE(em.association_confidence,0.995) association_confidence
                    FROM {_LOCK_TABLE} l
                    JOIN history_catalog_event e ON e.canonical_event_key=l.canonical_event_key
                    JOIN history_source_media s ON s.asset_key=l.asset_key
                    LEFT JOIN history_event_media em ON em.canonical_event_key=l.canonical_event_key AND em.asset_key=l.asset_key
                    WHERE {' AND '.join(clauses)}
                    ORDER BY e.canonical_event_key,l.last_confirmed_at DESC,s.verified_at DESC""",
                params,
            ).fetchall()
    except Exception:
        return out
    for row in rows:
        key = _clean(row["canonical_event_key"])
        if not key:
            continue
        item = _hydrate_locked(self, row, key)
        item.setdefault("matchId", _clean(row["event_id"]))
        item.setdefault("scoreEventId", _clean(row["event_id"]))
        bucket = out.setdefault(key, [])
        asset = _clean(item.get("assetKey"))
        existing = next((x for x in bucket if _clean((x or {}).get("assetKey")) == asset and asset), None)
        if existing:
            existing.update({
                "mediaAuthorityLocked": True,
                "mediaAuthorityLockReason": item.get("mediaAuthorityLockReason"),
                "mediaAuthorityLockedAt": item.get("mediaAuthorityLockedAt"),
            })
            if _clean(item.get("runtimeCatalogState")).upper() != "FAILED" and _transport(existing):
                existing["verifiedPlayable"] = True
        else:
            bucket.append(item)
    return out


def _put_event_media(self, date, league, event_id, rows):
    result = _ORIG_PUT_EVENT_MEDIA(self, date, league, event_id, rows)
    key = self.canonical_event_key(league, event_id)
    _lock_eligible(self, canonical_key=key, reason="PUT_EVENT_MEDIA_VERIFIED")
    _restore_locked_links(self, canonical_key=key)
    return result


def _record_runtime(self, date, league, event_id, asset_key, *, success=False, reason=""):
    result = _ORIG_RECORD_RUNTIME(self, date, league, event_id, asset_key, success=success, reason=reason)
    if result and success:
        key = self.canonical_event_key(league, event_id)
        _lock_eligible(self, canonical_key=key, asset_key=asset_key, reason="RUNTIME_PLAY_CONFIRMED")
    return result


def _record_verification(self, asset_key, verification_type, state, *, reason="", details=None, verified_at=None):
    result = _ORIG_RECORD_VERIFICATION(self, asset_key, verification_type, state, reason=reason, details=details, verified_at=verified_at)
    if result and _clean(state).upper() in {"VERIFIED", "PLAYED", "PASS", "SUCCESS"}:
        _lock_eligible(self, asset_key=asset_key, reason=f"VERIFICATION_{_clean(verification_type).upper() or 'VERIFIED'}")
    return result


def _repair_event_associations(self, matcher_version=None, force=False):
    kwargs = {"force": force}
    if matcher_version is not None:
        kwargs["matcher_version"] = matcher_version
    result = _ORIG_REPAIR_EVENT(self, **kwargs)
    restored = _restore_locked_links(self)
    if isinstance(result, dict):
        result = {**result, "lockedMediaRestored": restored, "mediaAuthority": VERSION}
    return result


def bootstrap_existing_locks(repo):
    """One local INSERT/SELECT; no provider work and no event-by-event scan."""
    return _lock_eligible(repo, reason="V5117_EXISTING_VERIFIED_BOOTSTRAP")


def lock_summary(repo):
    try:
        with closing(repo._read_connect()) as conn:
            row = conn.execute(
                f"""SELECT COUNT(*) locks,COUNT(DISTINCT canonical_event_key) games,
                      SUM(CASE WHEN UPPER(COALESCE(s.runtime_state,''))='FAILED' THEN 1 ELSE 0 END) failed
                    FROM {_LOCK_TABLE} l JOIN history_source_media s ON s.asset_key=l.asset_key"""
            ).fetchone()
        return {"locks": int(row["locks"] or 0), "games": int(row["games"] or 0), "runtimeFailed": int(row["failed"] or 0)}
    except Exception as exc:
        return {"locks": 0, "games": 0, "runtimeFailed": 0, "error": f"{type(exc).__name__}: {exc}"}


def install():
    global _INSTALLED, _ORIG_EVENT_MEDIA, _ORIG_RIBBON_MEDIA, _ORIG_PUT_EVENT_MEDIA
    global _ORIG_RECORD_RUNTIME, _ORIG_RECORD_VERIFICATION, _ORIG_REPAIR_EVENT
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        _ORIG_EVENT_MEDIA = HistoryRepository.event_media
        _ORIG_RIBBON_MEDIA = HistoryRepository.ribbon_media_for_date
        _ORIG_PUT_EVENT_MEDIA = HistoryRepository.put_event_media
        _ORIG_RECORD_RUNTIME = HistoryRepository.record_runtime
        _ORIG_RECORD_VERIFICATION = HistoryRepository.record_verification
        _ORIG_REPAIR_EVENT = HistoryRepository.repair_event_associations
        HistoryRepository.event_media = _event_media
        HistoryRepository.ribbon_media_for_date = _ribbon_media_for_date
        HistoryRepository.put_event_media = _put_event_media
        HistoryRepository.record_runtime = _record_runtime
        HistoryRepository.record_verification = _record_verification
        HistoryRepository.repair_event_associations = _repair_event_associations
        _INSTALLED = True

    # Each repository initializes its own SQLite file. The production singleton is
    # available shortly after server startup; initialize/seed locks after the board
    # has started rather than adding provider or scan work to launch.
    def worker():
        import sys
        for _ in range(600):
            server = sys.modules.get("__main__")
            repo = getattr(server, "HISTORY_REPOSITORY", None) if server else None
            if repo is not None:
                try:
                    _ensure_lock_table(repo)
                    # Let the v5.1.16 LLWS quarantine run first, then freeze the
                    # remaining clean verified relationships in one SQL transaction.
                    time.sleep(12)
                    bootstrap_existing_locks(repo)
                    _restore_locked_links(repo)
                    summary = lock_summary(repo)
                    try:
                        server.SBB_BACKEND_WIRING.setdefault("media", {})["v5117Authority"] = summary
                        server.MILESTONE_CONSOLE.record("media", "PASS", "v5.1.17 durable verified-media authority active", summary)
                    except Exception:
                        pass
                except Exception as exc:
                    try:
                        server.MILESTONE_CONSOLE.record("media", "WARN", "v5.1.17 media authority initialization failed", {"error": f"{type(exc).__name__}: {exc}"})
                    except Exception:
                        pass
                return
            time.sleep(.2)
    threading.Thread(target=worker, daemon=True, name="sbb-media-authority-v5117").start()
    return True


__all__ = ["VERSION", "install", "bootstrap_existing_locks", "lock_summary"]

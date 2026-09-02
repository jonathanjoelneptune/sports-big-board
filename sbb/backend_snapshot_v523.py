"""Sports Big Board v5.2.3 — materialized Historical Database Audit.

The Backend Inspector is a viewer, not an analysis job.  A daemon periodically
materializes the expensive catalog audit into one persistent compressed snapshot.
Interactive /api/history/audit requests filter/paginate that in-memory snapshot and
never scan the live 8k+ game / 28k+ asset database.
"""
from __future__ import annotations

import copy
import gzip
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VERSION = "5.2.3-backend-snapshot-1"
_STATE_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
_SNAPSHOT_PATH = _STATE_DIR / "backend-audit-snapshot-v523.json.gz"
_INSTALL_LOCK = threading.Lock()
_CACHE_LOCK = threading.RLock()
_BUILD_LOCK = threading.Lock()
_INSTALLED = False
_SERVER = None
_STOP = threading.Event()
_CACHE = {"generatedAt": 0.0, "base": {}, "rows": [], "total": 0}
_STATE = {
    "version": VERSION,
    "installed": False,
    "ready": False,
    "building": False,
    "generatedAt": 0.0,
    "rows": 0,
    "buildMs": 0,
    "lastError": "",
    "served": 0,
    "liveFallbacks": 0,
}


def _load_disk():
    global _CACHE
    try:
        with gzip.open(_SNAPSHOT_PATH, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            return False
        with _CACHE_LOCK:
            _CACHE = {
                "generatedAt": float(payload.get("generatedAt") or 0),
                "base": dict(payload.get("base") or {}),
                "rows": [dict(x) for x in payload.get("rows") if isinstance(x, dict)],
                "total": int(payload.get("total") or len(payload.get("rows") or [])),
            }
            _STATE["ready"] = bool(_CACHE["rows"])
            _STATE["generatedAt"] = _CACHE["generatedAt"]
            _STATE["rows"] = len(_CACHE["rows"])
        return True
    except Exception:
        return False


def _persist(payload):
    try:
        _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _SNAPSHOT_PATH.with_suffix(".tmp.gz")
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=4) as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"), default=str)
        os.replace(tmp, _SNAPSHOT_PATH)
        return True
    except Exception as exc:
        _STATE["lastError"] = f"persist: {type(exc).__name__}: {exc}"[:300]
        return False


def _audit_page(server, offset, limit=500):
    repo = getattr(server, "HISTORY_REPOSITORY", None)
    if repo is None or not hasattr(repo, "audit_catalog"):
        raise RuntimeError("HISTORY_REPOSITORY.audit_catalog unavailable")
    return repo.audit_catalog(
        date_from="", date_to="", league="", best_tier="", status="", search="",
        limit=limit, offset=offset,
        current_discovery_version=getattr(server, "HISTORY_DISCOVERY_VERSION", 0),
        quality_target=getattr(server, "HISTORY_QUALITY_TARGET_TIER", "gold"),
    ) or {}


def _build(server):
    if not _BUILD_LOCK.acquire(blocking=False):
        return False
    started = time.perf_counter()
    _STATE["building"] = True
    try:
        try:
            if server and hasattr(server,"_history_worker_beat"):
                server._history_worker_beat("integrity-backend-snapshot","integrity:materializing")
        except Exception:
            pass
        rows = []
        base = {}
        offset = 0
        total = None
        # 500-row query pages bound SQLite working-set and release the GIL/reader
        # connection between pages. This is daemon work only.
        while not _STOP.is_set():
            page = _audit_page(server, offset, 500)
            page_rows = [dict(x) for x in (page.get("rows") or []) if isinstance(x, dict)]
            if not base:
                base = {k: copy.deepcopy(v) for k, v in page.items() if k not in {"rows", "offset", "limit"}}
            if total is None:
                try:
                    total = int(page.get("total") or 0)
                except Exception:
                    total = 0
            rows.extend(page_rows)
            if not page_rows:
                break
            offset += len(page_rows)
            if total and offset >= total:
                break
            # Cooperative yield: this builder is lower priority than ribbon/Game Center.
            time.sleep(0.035)

        generated = time.time()
        payload = {"version": VERSION, "generatedAt": generated, "base": base, "rows": rows, "total": len(rows)}
        _persist(payload)
        with _CACHE_LOCK:
            _CACHE.update(generatedAt=generated, base=base, rows=rows, total=len(rows))
            _STATE.update(
                ready=True, generatedAt=generated, rows=len(rows),
                buildMs=round((time.perf_counter() - started) * 1000, 1), lastError="",
            )
        try:
            if server and hasattr(server,"_history_worker_beat"):
                server._history_worker_beat("integrity-backend-snapshot","integrity:idle",progress=True)
        except Exception:
            pass
        return True
    except Exception as exc:
        _STATE["lastError"] = f"build: {type(exc).__name__}: {exc}"[:300]
        return False
    finally:
        _STATE["building"] = False
        _BUILD_LOCK.release()


def _norm(v):
    return str(v or "").strip().lower()


def _match_status(row, wanted):
    wanted = _norm(wanted)
    if not wanted:
        return True
    effective = _norm(row.get("effectiveStatus") or row.get("discoveryState") or row.get("status"))
    best = _norm(row.get("bestTier") or "none")
    aliases = {
        "unindexed": ("unindexed", "index_pass_pending", "index pass pending"),
        "searched-empty": ("searched_empty", "source_exhausted_empty", "searched empty"),
        "coverage": ("coverage_complete", "verified_coverage_complete", "coverage complete"),
        "upgrade": ("upgrade_pending", "upgrade_eligible", "verified_upgrade_pending"),
        "partial": ("partial", "verified_partial"),
        "complete": ("quality_complete", "complete"),
        "degraded": ("degraded", "provider_degraded", "degraded_provider"),
        "candidate": ("candidate", "candidate_only"),
        "failed": ("failed", "runtime_failed"),
    }
    if wanted == "no-media":
        return best in ("", "none")
    needles = aliases.get(wanted, (wanted,))
    return any(n in effective for n in needles)


def _filter_rows(rows, qs):
    date_from = str((qs.get("dateFrom") or [""])[-1])[:10]
    date_to = str((qs.get("dateTo") or [""])[-1])[:10]
    league = str((qs.get("league") or [""])[-1]).upper().strip()
    best = _norm((qs.get("bestTier") or [""])[-1])
    status = _norm((qs.get("status") or [""])[-1])
    query = _norm((qs.get("q") or [""])[-1])[:120]

    out = []
    for row in rows:
        day = str(row.get("date") or "")[:10]
        if date_from and day < date_from:
            continue
        if date_to and day > date_to:
            continue
        if league and str(row.get("league") or "").upper() != league:
            continue
        row_best = _norm(row.get("bestTier") or "none")
        if best and row_best != best:
            continue
        if status and not _match_status(row, status):
            continue
        if query:
            hay = " ".join(str(row.get(k) or "") for k in ("game", "eventId", "league", "bestTier", "effectiveStatus", "lastError")).lower()
            if query not in hay:
                continue
        out.append(row)
    return out


def _payload(qs):
    with _CACHE_LOCK:
        base = copy.deepcopy(_CACHE.get("base") or {})
        rows = list(_CACHE.get("rows") or [])
        generated = float(_CACHE.get("generatedAt") or 0)
    try:
        limit = min(500, max(1, int((qs.get("limit") or ["100"])[-1] or 100)))
    except Exception:
        limit = 100
    try:
        offset = max(0, int((qs.get("offset") or ["0"])[-1] or 0))
    except Exception:
        offset = 0
    filtered = _filter_rows(rows, qs)
    page = filtered[offset:offset + limit]
    base.update({
        "ok": True,
        "version": getattr(_SERVER, "APP_VERSION", "5.2.3") if _SERVER else "5.2.3",
        "rows": page,
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "materialized": True,
        "snapshotVersion": VERSION,
        "snapshotGeneratedAt": generated,
        "snapshotAgeSeconds": round(max(0, time.time() - generated), 1) if generated else None,
        "snapshotRows": len(rows),
    })
    return base


def _interactive_recent(server, seconds=8.0):
    try:
        state = getattr(server, "CLIENT_ACTIVITY_STATE", {}) or {}
        last = max(float(state.get("lastInteractive") or 0), float(state.get("lastMedia") or 0))
        return bool(last and time.time() - last < float(seconds))
    except Exception:
        return False


def _worker():
    # A persisted image is loaded before the server is exposed. Re-materialization is
    # strictly low-priority and yields whenever the site was used recently, so opening
    # Backend can never cause the database scan it is trying to display.
    if _STOP.wait(8.0):
        return
    while not _STOP.is_set():
        if _SERVER:
            while _interactive_recent(_SERVER, 8.0) and not _STOP.is_set():
                try:
                    if hasattr(_SERVER, "_history_worker_beat"):
                        _SERVER._history_worker_beat("integrity-backend-snapshot", "integrity:yield-interactive", blocked=True)
                except Exception:
                    pass
                _STOP.wait(4.0)
            if not _STOP.is_set():
                _build(_SERVER)
        _STOP.wait(300.0)


def _install_into_server():
    global _SERVER
    _load_disk()
    deadline = time.time() + 120
    server = None
    while time.time() < deadline:
        candidate = sys.modules.get("__main__")
        if candidate and hasattr(candidate, "Handler") and hasattr(candidate, "send_json") and hasattr(candidate, "HISTORY_REPOSITORY"):
            server = candidate
            break
        time.sleep(0.2)
    if not server:
        return
    _SERVER = server
    try:
        lock=getattr(server,"HISTORY_WORKER_HEALTH_LOCK",None);health=getattr(server,"HISTORY_WORKER_HEALTH",None)
        if lock is not None and isinstance(health,dict):
            with lock:
                health.setdefault("integrity-backend-snapshot",{"heartbeat":time.time(),"phase":"integrity:starting","lastProgress":0.0,"iterations":0,"blocked":0,"current":""})
    except Exception:
        pass
    Handler = server.Handler
    if not getattr(Handler, "__sbbBackendSnapshotV523", False):
        old_get = Handler.do_GET

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/history/audit":
                with _CACHE_LOCK:
                    ready = bool(_CACHE.get("rows"))
                if ready:
                    _STATE["served"] += 1
                    return server.send_json(self, _payload(parse_qs(parsed.query)), 200, {
                        "Cache-Control": "no-store",
                        "X-SBB-Backend-Snapshot": VERSION,
                    })
                # First-ever migration has no materialized file yet. Preserve
                # correctness by allowing the old endpoint once while the daemon
                # creates the persistent snapshot. Every later request is RAM-only.
                _STATE["liveFallbacks"] += 1
                return old_get(self)
            if parsed.path == "/api/backend-snapshot/status":
                with _CACHE_LOCK:
                    status = copy.deepcopy(_STATE)
                status.update(ok=True, snapshotPath=str(_SNAPSHOT_PATH), requestBuildsDatabase=False)
                return server.send_json(self, status, 200, {"Cache-Control": "no-store"})
            if parsed.path == "/api/backend-snapshot/refresh":
                threading.Thread(target=_build, args=(server,), daemon=True, name="sbb-backend-snapshot-manual-v523").start()
                return server.send_json(self, {"ok": True, "accepted": True, "version": VERSION}, 202)
            return old_get(self)

        Handler.do_GET = do_GET
        Handler.__sbbBackendSnapshotV523 = True

    _STATE["installed"] = True
    threading.Thread(target=_worker, daemon=True, name="sbb-backend-snapshot-v523").start()


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-backend-snapshot-install-v523").start()
    return True


def diagnostics():
    with _CACHE_LOCK:
        return copy.deepcopy(_STATE)


__all__ = ["VERSION", "install", "diagnostics"]

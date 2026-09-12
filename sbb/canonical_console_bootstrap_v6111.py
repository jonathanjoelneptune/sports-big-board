"""Sports Big Board v6.1.11 canonical validation console bootstrap repair.

Shadow-only reliability patch. Production authority remains false.

The v6.1.10 run-integrity patch made validation decisions consult certification
worker health so stale-but-last-complete evidence could remain usable while a
league waited for its refresh turn. The validation snapshot evaluates 105
league/day decisions; calling CertificationEngine.health() from every decision
caused the expensive SQLite store health roll-up to be repeated roughly one
hundred times during a single console build. On a fresh backend process the
validation cache therefore remained empty long enough for the public console to
render only its shell and retry forever from the user's point of view.

This patch:
* captures certification health once per validation snapshot and serves that
  immutable value to every decision on the validation-build thread;
* skips the legacy consistency-write sweep only for the first snapshot so the
  console can establish a read model before doing any repair work;
* prevents concurrent duplicate validation builds from stacking after startup;
* exposes validation-build progress in /validation/health;
* rehydrates a compact persisted bootstrap snapshot when the live cache is still
  empty so a backend restart never returns a content-free snapshot contract.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from datetime import datetime

from . import canonical_shadow_v600 as shadow
from . import canonical_certification_v610 as v610
from . import canonical_validation_v612 as v612
from . import canonical_run_integrity_v6110 as v6110

VERSION = "6.1.11-canonical-console-bootstrap-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_HEALTH_LOCAL = threading.local()


def _clean(value):
    return str(value or "").strip()


def _load_json(value, fallback=None):
    try:
        return json.loads(value) if value else (fallback if fallback is not None else {})
    except Exception:
        return fallback if fallback is not None else {}


def _bootstrap_from_persisted(diag):
    cached = getattr(diag, "__sbbV6111BootstrapSnapshot", None)
    if cached:
        return cached
    path = _clean(getattr(diag.store, "path", ""))
    if not path or path == ":memory:":
        return None
    conn = None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT captured_at,release_version,summary_json,diagnostics_json
               FROM canonical_validation_snapshot ORDER BY captured_at DESC,id DESC LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        compact = _load_json(row["diagnostics_json"], {})
        summary = _load_json(row["summary_json"], compact.get("summary") or {})
        captured = float(row["captured_at"] or 0.0)
        window = compact.get("window") or {}
        snapshot = {
            "ok": True,
            "version": getattr(v612, "VERSION", VERSION),
            "releaseVersion": VERSION.split("-", 1)[0],
            "mode": "DIAGNOSTIC_SHADOW",
            "productionAuthority": False,
            "ready": False,
            "bootstrap": True,
            "persistedBootstrap": True,
            "bootstrapSourceRelease": _clean(row["release_version"]),
            "bootstrapMessage": "Live validation snapshot is rebuilding; showing the latest persisted diagnostic summary.",
            "capturedAt": captured,
            "capturedAtIso": v612._iso(captured) if captured else "",
            "capturedEastern": datetime.fromtimestamp(captured, shadow.ET).isoformat() if captured else "",
            "window": window,
            "summary": summary,
            "adapters": {},
            # Keep these collection keys present so the existing browser console
            # renders the persisted summary instead of entering its no-days retry
            # branch. Full matrix/event content replaces this bootstrap as soon as
            # the first live build finishes.
            "days": {},
            "discrepancies": [],
            "stateConsistencyViolations": compact.get("stateConsistencyViolations") or [],
            "mlsDiagnostics": compact.get("mlsDiagnostics") or [],
            "eventInventory": {},
            "probeHistory": [],
            "decisionHistory": [],
            "database": {"bootstrapFromPersistedSnapshot": True},
            "worker": {
                "validationBuildInProgress": bool(getattr(diag, "__sbbV6111BuildStartedAt", 0.0)),
            },
            "diagnosticHooks": {
                "persistedBootstrapSnapshot": True,
                "singleHealthReadPerValidationBuild": True,
                "productionAuthority": False,
            },
        }
        diag.__sbbV6111BootstrapSnapshot = snapshot
        return snapshot
    except Exception:
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _install_initial_consistency_gate():
    cls = v612.ValidationDiagnostics
    if getattr(cls, "__sbbV6111InitialConsistencyGate", False):
        return
    original = cls._enforce_local_consistency

    def enforce_local_consistency(self, day_from, day_to):
        # A diagnostic page should establish its first read model before it starts
        # a 105 league/day consistency-write sweep. Subsequent refreshes retain the
        # legacy behavior once a usable live snapshot exists.
        with self.lock:
            ready = bool((self.cache or {}).get("ready"))
        if not ready:
            self.__sbbV6111InitialConsistencySkipped = True
            return 0
        return original(self, day_from, day_to)

    cls._enforce_local_consistency = enforce_local_consistency
    cls.__sbbV6111InitialConsistencyGate = True


def _install_snapshot_bootstrap():
    cls = v612.ValidationDiagnostics
    if getattr(cls, "__sbbV6111PersistedBootstrap", False):
        return
    original_snapshot = cls.snapshot
    original_health = cls.health

    def snapshot(self):
        live = original_snapshot(self)
        if live:
            return live
        return _bootstrap_from_persisted(self)

    def health(self):
        payload = original_health(self)
        started = float(getattr(self, "__sbbV6111BuildStartedAt", 0.0) or 0.0)
        completed = float(getattr(self, "__sbbV6111LastBuildCompletedAt", 0.0) or 0.0)
        bootstrap = _bootstrap_from_persisted(self)
        payload.update({
            "consoleBootstrapVersion": VERSION,
            "buildInProgress": bool(started),
            "buildStartedAt": started,
            "buildAgeSeconds": round(max(0.0, time.time() - started), 3) if started else None,
            "lastBuildCompletedAtV6111": completed,
            "persistedBootstrapAvailable": bool(bootstrap),
            "singleHealthReadPerValidationBuild": True,
            "initialConsistencySweepDeferredUntilLiveSnapshot": True,
        })
        return payload

    cls.snapshot = snapshot
    cls.health = health
    cls.__sbbV6111PersistedBootstrap = True


def _install_single_health_read_per_build():
    engine_cls = v610.CertificationEngine
    diag_cls = v612.ValidationDiagnostics
    if getattr(diag_cls, "__sbbV6111SingleHealthPerBuild", False):
        return

    original_engine_health = engine_cls.health
    original_build = diag_cls.build_snapshot

    def engine_health(self):
        state = getattr(_HEALTH_LOCAL, "state", None)
        if state and state.get("engine") is self:
            state["served"] = int(state.get("served") or 0) + 1
            return state.get("payload") or {}
        return original_engine_health(self)

    def build_snapshot(self):
        lock = getattr(self, "__sbbV6111BuildLock", None)
        if lock is None:
            with self.lock:
                lock = getattr(self, "__sbbV6111BuildLock", None)
                if lock is None:
                    lock = threading.Lock()
                    self.__sbbV6111BuildLock = lock
        if not lock.acquire(blocking=False):
            self.__sbbV6111ConcurrentBuildSkips = int(getattr(self, "__sbbV6111ConcurrentBuildSkips", 0) or 0) + 1
            return self.snapshot()

        self.__sbbV6111BuildStartedAt = time.time()
        self.__sbbV6111HealthReadsThisBuild = 0
        try:
            # One expensive health roll-up for the entire 15-day build. Calls made
            # by the v6.1.10 decision wrapper and console-stage wrapper on this
            # thread receive the same immutable snapshot through thread-local state.
            payload = original_engine_health(self.engine) or {}
            self.__sbbV6111HealthReadsThisBuild = 1
            _HEALTH_LOCAL.state = {"engine": self.engine, "payload": payload, "served": 0}
            result = original_build(self)
            state = getattr(_HEALTH_LOCAL, "state", None) or {}
            self.__sbbV6111CachedHealthServesThisBuild = int(state.get("served") or 0)
            return result
        finally:
            _HEALTH_LOCAL.state = None
            self.__sbbV6111LastBuildCompletedAt = time.time()
            self.__sbbV6111BuildStartedAt = 0.0
            lock.release()

    engine_cls.health = engine_health
    diag_cls.build_snapshot = build_snapshot
    diag_cls.__sbbV6111SingleHealthPerBuild = True
    engine_cls.__sbbV6111ValidationHealthCache = True


def _runtime_patch():
    # v6.1.10 installs its final validation/worker wrappers asynchronously. Wait
    # for those exact runtime surfaces so this patch wraps the final methods rather
    # than being overwritten by the older installer thread.
    while True:
        diag = v612.engine()
        server = sys.modules.get("__main__")
        if (
            diag and server and hasattr(server, "Handler")
            and getattr(v612.ValidationDiagnostics, "__sbbV6110ConsoleStages", False)
            and getattr(v610.CertificationEngine, "__sbbV6110WorkerStages", False)
        ):
            break
        time.sleep(0.25)

    _install_single_health_read_per_build()
    try:
        server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update({
            "consoleBootstrapVersion": VERSION,
            "singleHealthReadPerValidationBuild": True,
            "persistedValidationBootstrap": True,
            "initialConsistencySweepDeferredUntilLiveSnapshot": True,
            "productionAuthority": False,
        })
    except Exception:
        pass


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    # These class-level changes are safe before the diagnostics instance appears.
    _install_initial_consistency_gate()
    _install_snapshot_bootstrap()
    threading.Thread(target=_runtime_patch, daemon=True, name="sbb-canonical-console-bootstrap-v6111").start()

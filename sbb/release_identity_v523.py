"""Sports Big Board release identity and safe mismatch policy.

The repository VERSION file is the only deployment release authority. This historical
module filename is retained for import compatibility, but it contains no hard-coded
semantic release number. A frontend/backend mismatch pauses optional discovery only;
integrity/read paths remain available while a deployment converges.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
_INSTALL_LOCK = threading.Lock()
_STATE_LOCK = threading.RLock()
_INSTALLED = False
_STATE = {
    "version": VERSION,
    "installed": False,
    "backendInspectorPatched": False,
    "frontendVersion": "",
    "frontendSeenAt": 0.0,
    "versionMatch": None,
    "discoveryPausedForMismatch": False,
}
_ORIGINAL_SEARCH_SUSPENDED = None
_ORIGINAL_GREEN_ENABLED = None


def _clean(value):
    return str(value or "").strip()


def _backend_version(server):
    return _clean(getattr(server, "APP_VERSION", VERSION)) or VERSION


def _record_frontend(server, frontend_version):
    frontend = _clean(frontend_version)
    backend = _backend_version(server)
    if not frontend:
        return
    with _STATE_LOCK:
        _STATE["version"] = backend
        _STATE["frontendVersion"] = frontend
        _STATE["frontendSeenAt"] = time.time()
        _STATE["versionMatch"] = frontend == backend
        _STATE["discoveryPausedForMismatch"] = frontend != backend


def _active_mismatch(server):
    """Only a recently observed mismatched frontend pauses optional discovery."""
    backend = _backend_version(server)
    with _STATE_LOCK:
        frontend = _clean(_STATE.get("frontendVersion"))
        seen = float(_STATE.get("frontendSeenAt") or 0)
    return bool(frontend and frontend != backend and time.time() - seen < 900.0)


def _install_mismatch_guard(server):
    global _ORIGINAL_SEARCH_SUSPENDED, _ORIGINAL_GREEN_ENABLED
    if getattr(server, "__sbbReleaseMismatchGuardV523", False):
        return
    original_search = getattr(server, "_history_search_suspended", None)
    original_green = getattr(server, "_history_green_worker_enabled", None)
    _ORIGINAL_SEARCH_SUSPENDED = original_search
    _ORIGINAL_GREEN_ENABLED = original_green
    if callable(original_search):
        def _history_search_suspended_release():
            if _active_mismatch(server):
                return True
            return bool(original_search())
        server._history_search_suspended = _history_search_suspended_release
    if callable(original_green):
        def _history_green_worker_enabled_release(worker_index):
            if _active_mismatch(server):
                return False, "frontend-backend-version-mismatch"
            return original_green(worker_index)
        server._history_green_worker_enabled = _history_green_worker_enabled_release
    server.__sbbReleaseMismatchGuardV523 = True


def _install_into_server():
    deadline = time.time() + 120
    server = None
    while time.time() < deadline:
        candidate = sys.modules.get("__main__")
        if candidate and hasattr(candidate, "Handler") and hasattr(candidate, "send_json"):
            server = candidate
            break
        time.sleep(0.2)
    if not server:
        return

    try:
        from . import backend_inspector_api
        backend_inspector_api.VERSION = f"{_backend_version(server)}-backend-inspector-api"
        _STATE["backendInspectorPatched"] = True
    except Exception:
        pass

    _install_mismatch_guard(server)
    Handler = server.Handler
    if not getattr(Handler, "__sbbReleaseIdentityV523", False):
        old_get = Handler.do_GET

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/release-identity":
                qs = parse_qs(parsed.query)
                frontend = _clean((qs.get("frontendVersion") or [""])[-1])
                if frontend:
                    _record_frontend(server, frontend)
                backend = _backend_version(server)
                mismatch = _active_mismatch(server)
                with _STATE_LOCK:
                    state = dict(_STATE)
                observed_frontend = state.get("frontendVersion") or frontend
                return server.send_json(self, {
                    "ok": True,
                    "version": backend,
                    "release": backend,
                    "backendVersion": backend,
                    "frontendVersion": observed_frontend,
                    "versionMatch": (observed_frontend or backend) == backend,
                    "optionalDiscoveryPausedForMismatch": mismatch,
                    "integrityPausedForMismatch": False,
                    "workerPolicy": {
                        "interactive": "never background-blocked",
                        "integrity": "always-on even during release mismatch",
                        "discovery": "paused for active release mismatch; otherwise operator-throttled",
                    },
                }, 200, {"Cache-Control": "no-store"})
            return old_get(self)

        Handler.do_GET = do_GET
        Handler.__sbbReleaseIdentityV523 = True

    with _STATE_LOCK:
        _STATE["version"] = _backend_version(server)
        _STATE["installed"] = True


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-release-identity").start()
    return True


def diagnostics():
    with _STATE_LOCK:
        return dict(_STATE)


__all__ = ["VERSION", "install", "diagnostics"]

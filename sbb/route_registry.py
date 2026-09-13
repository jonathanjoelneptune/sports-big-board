"""Shared Sports Big Board backend route registry.

Priority 1 ownership consolidation introduces one compatibility dispatcher for
feature routes. Existing modules may migrate one at a time from wrapping
``Handler.do_GET`` to registering an exact route here. Unmigrated wrappers remain
in the fallback chain, so this can land without a big-bang server rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass
import sys
import threading
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

RouteHandler = Callable[[Any, Any, dict[str, list[str]], Any], Any]


@dataclass(frozen=True)
class RouteRegistration:
    method: str
    path: str
    name: str
    handler: RouteHandler


_LOCK = threading.RLock()
_ROUTES: dict[tuple[str, str], RouteRegistration] = {}
_DISPATCHER_STARTED = False
_DISPATCHER_INSTALLED = False
_DISPATCHER_ERROR = ""


def _normalize_method(value: str) -> str:
    method = str(value or "GET").strip().upper()
    if method not in {"GET"}:
        raise ValueError(f"Unsupported shared route method: {method}")
    return method


def _normalize_path(value: str) -> str:
    path = str(value or "").strip()
    if not path.startswith("/"):
        raise ValueError("Shared route path must begin with '/'")
    return path


def register(method: str, path: str, handler: RouteHandler, *, name: str = "") -> bool:
    """Register one exact feature route.

    Dispatcher installation is a separate final startup step. That ordering keeps
    asynchronous legacy installers inside the compatibility fallback chain rather
    than allowing one of them to overwrite the shared dispatcher during boot.
    """
    if not callable(handler):
        raise TypeError("Shared route handler must be callable")
    method = _normalize_method(method)
    path = _normalize_path(path)
    key = (method, path)
    registration = RouteRegistration(method, path, str(name or path), handler)
    with _LOCK:
        current = _ROUTES.get(key)
        if current:
            if current.handler is handler:
                return False
            raise RuntimeError(f"Duplicate Sports Big Board route: {method} {path}")
        _ROUTES[key] = registration
    return True


def register_get(path: str, handler: RouteHandler, *, name: str = "") -> bool:
    return register("GET", path, handler, name=name)


def dispatch(method: str, request: Any, server: Any) -> tuple[bool, Any]:
    """Dispatch an exact registered route without touching the legacy fallback."""
    parsed = urlparse(request.path)
    key = (_normalize_method(method), parsed.path)
    with _LOCK:
        registration = _ROUTES.get(key)
    if not registration:
        return False, None
    query = parse_qs(parsed.query)
    return True, registration.handler(request, parsed, query, server)


def _install_dispatcher() -> None:
    global _DISPATCHER_INSTALLED, _DISPATCHER_ERROR
    try:
        # The package is imported while server.py is still building its globals.
        # Wait until Handler is ready, then give the already-invoked compatibility
        # installers a short settle window before capturing the final fallback.
        for _ in range(600):
            server = sys.modules.get("__main__")
            handler_cls = getattr(server, "Handler", None) if server else None
            if handler_cls is not None and callable(getattr(handler_cls, "do_GET", None)):
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("Sports Big Board Handler was not ready for shared routes")

        time.sleep(0.75)
        Handler = server.Handler
        with _LOCK:
            current_get = Handler.do_GET
            if getattr(current_get, "__sbbSharedRouteDispatcher", False):
                _DISPATCHER_INSTALLED = True
                return
            legacy_get = current_get

            def do_GET(self):
                matched, result = dispatch("GET", self, server)
                if matched:
                    return result
                return legacy_get(self)

            do_GET.__name__ = getattr(legacy_get, "__name__", "do_GET")
            do_GET.__doc__ = getattr(legacy_get, "__doc__", None)
            do_GET.__sbbSharedRouteDispatcher = True
            do_GET.__sbbSharedRouteFallback = legacy_get
            Handler.do_GET = do_GET
            Handler.__sbbSharedRouteRegistry = True
            Handler.__sbbSharedRouteFallback = legacy_get
            _DISPATCHER_INSTALLED = True
            _DISPATCHER_ERROR = ""
    except BaseException as exc:
        with _LOCK:
            _DISPATCHER_ERROR = f"{type(exc).__name__}: {exc}"


def ensure_dispatcher() -> bool:
    global _DISPATCHER_STARTED
    with _LOCK:
        if _DISPATCHER_INSTALLED or _DISPATCHER_STARTED:
            return False
        _DISPATCHER_STARTED = True
    threading.Thread(target=_install_dispatcher, daemon=True, name="sbb-shared-route-registry").start()
    return True


def install() -> bool:
    """Final startup registration for the shared route authority."""
    return ensure_dispatcher()


def snapshot() -> dict[str, Any]:
    with _LOCK:
        routes = [
            {"method": route.method, "path": route.path, "name": route.name}
            for route in sorted(_ROUTES.values(), key=lambda item: (item.method, item.path))
        ]
        return {
            "dispatcherStarted": _DISPATCHER_STARTED,
            "dispatcherInstalled": _DISPATCHER_INSTALLED,
            "dispatcherError": _DISPATCHER_ERROR,
            "routeCount": len(routes),
            "routes": routes,
        }


__all__ = ["RouteRegistration", "register", "register_get", "dispatch", "ensure_dispatcher", "install", "snapshot"]

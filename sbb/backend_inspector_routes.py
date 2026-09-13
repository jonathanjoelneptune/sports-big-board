"""Shared-route adapter for the read-only Backend Inspector API.

The inspector implementation remains isolated in ``backend_inspector_api``. This
module owns only HTTP registration, allowing Priority 1 to retire another direct
``Handler.do_GET`` wrapper without coupling the route registry to inspector logic.
"""
from __future__ import annotations

import threading

from . import backend_inspector_api as inspector
from .route_registry import register_get

_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _date_route(request, _parsed, query, server):
    date = inspector._clean((query.get("date") or [""])[-1])[:10]
    if not inspector._DATE_RE.fullmatch(date):
        return server.send_json(request, {"ok": False, "error": "DATE_REQUIRED"}, 400)
    try:
        return server.send_json(request, inspector._date_payload(server, date), 200)
    except Exception as exc:
        return server.send_json(
            request,
            {
                "ok": False,
                "error": "BACKEND_INSPECTOR_FAILED",
                "message": f"{type(exc).__name__}: {exc}",
            },
            500,
        )


def install() -> bool:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        register_get(
            "/api/backend-inspector/date",
            _date_route,
            name="backend-inspector-date",
        )
        _INSTALLED = True
        return True


__all__ = ["install"]

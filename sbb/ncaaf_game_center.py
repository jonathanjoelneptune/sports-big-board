"""Sports Big Board v5.1.11 — NCAAF Game Center on the shared NFL ESPN architecture.

NCAAF is a first-class public namespace. The adapter deliberately reuses the NFL
football normalization/completeness path while targeting ESPN's college-football
summary endpoint. No retired CFB Game Center runtime is imported or installed.
"""
from __future__ import annotations

import copy
import sys
import threading
import time

from . import game_center as _gc

VERSION = "5.1.11-ncaaf-game-center-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ORIGINAL_FETCH = _gc.fetch_espn_game_center
_ORIGINAL_NORMALIZE = _gc.normalize_espn_summary
_ORIGINAL_COVERAGE = _gc.game_center_coverage


def _rewrite_public_identity(data, event_id):
    out = copy.deepcopy(data or {})
    event = out.setdefault("event", {})
    event["competitionId"] = "NCAAF"
    event["sportId"] = "american-football"
    event["eventKind"] = "game"
    event.setdefault("eventId", str(event_id or ""))
    out["competitionId"] = "NCAAF"
    board = out.setdefault("scoreboard", {})
    if board.get("periods"):
        board["lineScoreType"] = "quarters"
    out["gameCenterArchitecture"] = "NFL_SHARED_ESPN_FOOTBALL"
    out["source"] = str(out.get("source") or "ESPN Game Summary")
    return out


def normalize_ncaaf_summary(payload, event_id):
    # Normalize as NFL first so quarter labels, player sections, PBP, scoring plays,
    # win probability, and completeness behavior are exactly the shared football path.
    normalized = _ORIGINAL_NORMALIZE(payload, "NFL", event_id)
    out = _rewrite_public_identity(normalized, event_id)
    _gc._apply_coverage_fields(out)
    return out


def fetch_espn_game_center(competition, event_id, fetch_json, site_api_base):
    competition = str(competition or "").upper()
    if competition != "NCAAF":
        return _ORIGINAL_FETCH(competition, event_id, fetch_json, site_api_base)
    base = str(site_api_base).rstrip("/")
    payload = fetch_json(f"{base}/football/college-football/summary?event={event_id}", timeout=10)
    return normalize_ncaaf_summary(payload, event_id)


def game_center_coverage(data):
    comp = str((data or {}).get("competitionId") or (((data or {}).get("event") or {}).get("competitionId")) or "").upper()
    if comp != "NCAAF":
        return _ORIGINAL_COVERAGE(data)
    # Apply the exact NFL richness/linescore contract, then restore NCAAF identity.
    probe = copy.deepcopy(data or {})
    probe["competitionId"] = "NFL"
    probe.setdefault("event", {})["competitionId"] = "NFL"
    result = dict(_ORIGINAL_COVERAGE(probe))
    result["competitionId"] = "NCAAF"
    return result


def _enable_server_support():
    # server.py defines GAME_CENTER_SUPPORTED after importing the sbb package.
    # Wait briefly for that definition, then enroll NCAAF in the same endpoint.
    for _ in range(600):
        server = sys.modules.get("__main__")
        supported = getattr(server, "GAME_CENTER_SUPPORTED", None)
        if hasattr(supported, "add"):
            supported.add("NCAAF")
            return
        if isinstance(supported, list):
            if "NCAAF" not in supported:
                supported.append("NCAAF")
            return
        time.sleep(0.05)


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        _gc.fetch_espn_game_center = fetch_espn_game_center
        _gc.game_center_coverage = game_center_coverage
        _INSTALLED = True
    threading.Thread(target=_enable_server_support, daemon=True, name="sbb-ncaaf-game-center-enroll").start()
    return True


__all__ = ["VERSION", "install", "fetch_espn_game_center", "normalize_ncaaf_summary", "game_center_coverage"]

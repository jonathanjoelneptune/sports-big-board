"""Sports Big Board v6.1.16 EPL official-FPL + stale-state follow-up.

Shadow/certification only. Production Day State remains the event authority.

The 2026-09-13 validation console proved that the prior canonical repairs resolved
NFL/NCAAF/MLB identity contradictions, but also exposed two remaining runtime
issues:

* Premier League PulseLive requests return HTTP 400 even while the official
  Premier League schedule is reachable. Use the league-operated Fantasy Premier
  League JSON schedule as the structured authoritative adapter.
* A repaired MLB date can retain a persisted RECONCILING row whose only reason was
  an already-cleared production-only contradiction. Recompile only that exact
  stale contradiction class after current hardening evidence is clean.

Both behaviors fail closed and keep production authority disabled.
"""
from __future__ import annotations

import sys
import threading
import time
from contextlib import closing

from . import canonical_shadow_v600 as shadow
from . import canonical_certification_v610 as v610
from . import canonical_certification_v611 as v611
from . import canonical_schedule_watchdogs_v6116 as watchdogs
from . import canonical_reconciliation_followup_v6116 as reconcile_followup

VERSION = "6.1.16-epl-fpl-state-followup-1"

EPL_SOURCE = "PREMIER_LEAGUE_OFFICIAL_SCHEDULE"
EPL_HOST = "fantasy.premierleague.com"
FPL_BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"

_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_PATCHED = False


def _clean(value):
    return str(value or "").strip()


def _fpl_team_map(payload):
    teams = payload.get("teams") if isinstance(payload, dict) else None
    if not isinstance(teams, list):
        raise RuntimeError("FPL bootstrap response missing teams[]")
    mapped = {}
    for row in teams:
        if not isinstance(row, dict):
            continue
        try:
            team_id = int(row.get("id"))
        except Exception:
            continue
        name = _clean(row.get("name"))
        if not name:
            continue
        mapped[team_id] = {
            "name": name,
            "short": _clean(row.get("short_name") or row.get("shortName")),
        }
    # Fail closed if this is not recognizably a full Premier League team universe.
    if len(mapped) < 20:
        raise RuntimeError(f"FPL bootstrap returned only {len(mapped)} recognized teams")
    return mapped


def _fpl_status(row):
    if bool(row.get("finished")) or bool(row.get("finished_provisional")):
        return "FINAL"
    if bool(row.get("started")):
        return "LIVE"
    return "SCHEDULED"


def _fpl_fixture_groups(fixtures, teams, days):
    if not isinstance(fixtures, list):
        raise RuntimeError("FPL fixtures response was not a list")
    # The endpoint is intended to be full-season. A partial response must not be
    # allowed to certify zero-game dates.
    if len(fixtures) < 300:
        raise RuntimeError(
            f"FPL fixtures response is incomplete ({len(fixtures)} rows; expected full season)"
        )

    wanted = set(days)
    groups = {}
    for row in fixtures:
        if not isinstance(row, dict):
            continue
        scheduled = _clean(row.get("kickoff_time"))
        day = v610._day_from_datetime(scheduled)
        if not day or day not in wanted:
            continue
        try:
            home_id = int(row.get("team_h"))
            away_id = int(row.get("team_a"))
        except Exception:
            continue
        home = teams.get(home_id)
        away = teams.get(away_id)
        if not home or not away:
            continue
        event_id = _clean(row.get("id"))
        if not event_id:
            continue

        event = {
            "competitionId": "EPL",
            "__sbbDate": day,
            "eventId": event_id,
            "scheduledAt": scheduled,
            "status": _fpl_status(row),
            "away": v610._team(away["name"], away.get("short")),
            "home": v610._team(home["name"], home.get("short")),
            "name": f"{away['name']} @ {home['name']}",
        }
        if row.get("team_a_score") is not None:
            event["awayScore"] = row.get("team_a_score")
        if row.get("team_h_score") is not None:
            event["homeScore"] = row.get("team_h_score")
        groups.setdefault(day, []).append(event)
    return groups


def _collect_epl_official_fpl(self, day_from, day_to):
    """Use the league-operated FPL schedule, then fail over to prior official path."""
    days = v610._date_range(day_from, day_to)
    headers = {
        "Referer": "https://fantasy.premierleague.com/",
        "Origin": "https://fantasy.premierleague.com",
        "Accept": "application/json,text/plain,*/*",
    }
    try:
        bootstrap = self._http(
            FPL_BOOTSTRAP_URL, headers=headers, cache_seconds=1800
        )
        fixtures = self._http(
            FPL_FIXTURES_URL, headers=headers, cache_seconds=300
        )
        teams = _fpl_team_map(bootstrap)
        groups = _fpl_fixture_groups(fixtures, teams, days)

        count = self.writer.snapshot(
            groups, days, "EPL", EPL_SOURCE, "AUTHORITATIVE"
        )
        endpoint = f"{FPL_FIXTURES_URL} + {FPL_BOOTSTRAP_URL}"
        self._mark_health(
            "EPL",
            EPL_SOURCE,
            "AUTHORITATIVE",
            day_from,
            day_to,
            True,
            count,
            "",
            endpoint,
        )
        return count
    except Exception as fpl_exc:
        # Retain the existing official-web/PulseLive route as a secondary fallback.
        # It records its own failed coverage if it also cannot prove the range.
        try:
            return watchdogs._collect_epl_v6116(self, day_from, day_to)
        except Exception as prior_exc:
            error = (
                f"FPL official API: {type(fpl_exc).__name__}: {fpl_exc}; "
                f"prior official path: {type(prior_exc).__name__}: {prior_exc}"
            )
            return self._failed_range(
                "EPL", EPL_SOURCE, "AUTHORITATIVE", days, error, FPL_FIXTURES_URL
            )


def _stale_known_conflict_rows(store):
    """Latest persisted rows whose only persisted blocker is old production-only data."""
    with store._lock, closing(store._connect(readonly=True)) as conn:
        rows = conn.execute(
            """
            SELECT d.*
              FROM daily_slate d
              JOIN (
                    SELECT slate_date,competition_id,MAX(version) AS version
                      FROM daily_slate
                     GROUP BY slate_date,competition_id
              ) latest
                ON latest.slate_date=d.slate_date
               AND latest.competition_id=d.competition_id
               AND latest.version=d.version
             WHERE d.certification_status='RECONCILING'
               AND d.certification_reason LIKE 'KNOWN_EVENT_UNIVERSE_CONFLICT:%'
             ORDER BY d.slate_date,d.competition_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _normalize_stale_known_conflicts(store):
    repaired = []
    skipped = []
    for row in _stale_known_conflict_rows(store):
        day = _clean(row.get("slate_date"))
        league = _clean(row.get("competition_id"))
        hard = v611._hardening_state(store, day, league, row)
        if hard.get("reasons"):
            skipped.append(
                {
                    "date": day,
                    "league": league,
                    "reason": "CURRENT_CONTRADICTION_STILL_PRESENT",
                    "currentReasons": list(hard.get("reasons") or []),
                }
            )
            continue
        try:
            slate, changed = store.compile_slate(
                day,
                league,
                "STALE_CONTRADICTION_NORMALIZATION",
                force_version=True,
            )
        except Exception as exc:
            skipped.append(
                {
                    "date": day,
                    "league": league,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        current = _clean((slate or {}).get("certification_status")).upper()
        if changed and current != "RECONCILING":
            repaired.append(
                {
                    "date": day,
                    "league": league,
                    "from": "RECONCILING",
                    "to": current,
                    "priorReason": row.get("certification_reason"),
                }
            )
        else:
            skipped.append(
                {
                    "date": day,
                    "league": league,
                    "reason": f"RECOMPILE_RESULT={current or 'UNKNOWN'}",
                }
            )
    return {
        "repaired": len(repaired),
        "rows": repaired,
        "skipped": skipped,
    }


def _install_post_run_state_normalizer():
    cls = v610.CertificationEngine
    if getattr(cls, "__sbbV6116StaleConflictNormalizer", False):
        return
    original = cls.run_horizon

    def run_horizon(self):
        stats = original(self)
        try:
            repair = _normalize_stale_known_conflicts(self.store)
            if isinstance(stats, dict):
                stats["staleConflictNormalization"] = repair
                self.last_stats = stats
        except Exception as exc:
            if isinstance(stats, dict):
                stats.setdefault("errors", []).append(
                    f"stale conflict normalization: {type(exc).__name__}: {exc}"
                )
            self.last_error = (
                f"stale conflict normalization: {type(exc).__name__}: {exc}"
            )
        return stats

    cls.run_horizon = run_horizon
    cls.__sbbV6116StaleConflictNormalizer = True


def _patch_health():
    cls = v610.CertificationEngine
    if getattr(cls, "__sbbV6116EplFplStateHealth", False):
        return
    original = cls.health

    def health(self):
        payload = original(self)
        payload["eplFplStateFollowupVersion"] = VERSION
        payload.setdefault("hardening", {}).update(
            {
                "eplOfficialFplApiAuthoritative": True,
                "eplOfficialFplApiHost": EPL_HOST,
                "staleKnownConflictStateNormalization": True,
                "productionAuthority": False,
            }
        )
        return payload

    cls.health = health
    cls.__sbbV6116EplFplStateHealth = True


def _runtime_install():
    global _PATCHED
    deadline = time.time() + 180
    engine = None
    while time.time() < deadline:
        engine = watchdogs.engine()
        if (
            engine is not None
            and getattr(reconcile_followup, "_PATCHED", False)
        ):
            break
        time.sleep(0.1)
    if engine is None:
        return

    # Make diagnostics and future collector lookups identify the actual league-
    # operated authoritative host rather than the retired PulseLive request path.
    v610.SOURCE_DEFS["EPL"] = {
        "authoritative": EPL_SOURCE,
        "host": EPL_HOST,
    }
    watchdogs.TRUSTED_SLATE_DATE_SOURCES.add(EPL_SOURCE)

    cls = v610.CertificationEngine
    cls._collect_epl = _collect_epl_official_fpl
    _install_post_run_state_normalizer()
    _patch_health()
    _PATCHED = True

    initial_state_repair = _normalize_stale_known_conflicts(engine.store)
    try:
        server = sys.modules.get("__main__")
        if server is not None:
            server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update(
                {
                    "eplFplStateFollowupVersion": VERSION,
                    "eplAuthoritativeSource": EPL_SOURCE,
                    "eplAuthoritativeHost": EPL_HOST,
                    "staleKnownConflictStateNormalization": True,
                    "initialStaleStateRepair": initial_state_repair,
                    "productionAuthority": False,
                }
            )
    except Exception:
        pass

    # Refresh immediately so all 15 EPL date decisions and any stale persisted
    # contradiction row are visible without waiting for the next cadence.
    try:
        engine.run_horizon()
    except Exception as exc:
        engine.last_error = (
            f"v6.1.16 EPL/FPL state follow-up: {type(exc).__name__}: {exc}"
        )


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    threading.Thread(
        target=_runtime_install,
        daemon=True,
        name="sbb-canonical-epl-fpl-state-followup-v6116",
    ).start()

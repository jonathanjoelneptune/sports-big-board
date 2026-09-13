"""Sports Big Board v6.1.16 EPL official-FPL + identity/state follow-up.

Shadow/certification only. Production Day State remains the event authority.

The EPL official FPL adapter is healthy, but live validation exposed a final
identity-normalization gap between the league-operated FPL team names and ESPN's
long-form team names:

* ``Man Utd`` vs ``Manchester United``
* ``Man City`` vs ``Manchester City``

Those variants caused otherwise identical EPL fixtures to exist as separate
canonical rows on 2026-09-06, 2026-09-13, and 2026-09-20. This layer keeps the
normalizer deliberately narrow: explicit aliases only, exact same Eastern slate
date, kickoff within the existing 20-minute identity tolerance, and a one-to-one
AUTHORITATIVE-only row paired with a broader INDEPENDENT/DIRECT-or-LEGACY row.

The league-operated Fantasy Premier League JSON schedule remains the structured
authoritative adapter, the old official-web/PulseLive collector remains fallback,
and stale persisted contradiction cleanup remains fail-closed. Production
authority stays disabled.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import defaultdict
from contextlib import closing

from . import canonical_shadow_v600 as shadow
from . import canonical_certification_v610 as v610
from . import canonical_certification_v611 as v611
from . import canonical_identity_ingestion_v619 as v619
from . import canonical_schedule_watchdogs_v6116 as watchdogs
from . import canonical_reconciliation_followup_v6116 as reconcile_followup

VERSION = "6.1.16-epl-fpl-state-followup-2"

EPL_SOURCE = "PREMIER_LEAGUE_OFFICIAL_SCHEDULE"
EPL_HOST = "fantasy.premierleague.com"
FPL_BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"
EPL_ALIAS_GROUPS = (
    ("Man Utd", "Manchester United"),
    ("Man City", "Manchester City"),
)

_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_PATCHED = False


def _clean(value):
    return str(value or "").strip()


def _install_epl_aliases():
    """Install only the provider spelling variants proven by validation evidence."""
    bucket = v619._ALIAS_LOOKUP.setdefault("EPL", {})
    for group in EPL_ALIAS_GROUPS:
        canonical = shadow._norm(group[0])
        for name in group:
            bucket[shadow._norm(name)] = canonical


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


def _mapping_sets(store, canonical_event_id):
    mapped = defaultdict(set)
    for row in store.mappings_for_event(canonical_event_id):
        provider = _clean(row.get("provider"))
        provider_event_id = _clean(row.get("provider_event_id"))
        if provider and provider_event_id:
            mapped[provider].add(provider_event_id)
    return mapped


def _provider_sets_compatible(store, first_id, second_id):
    """Do not merge rows that already disagree on a shared provider identity."""
    first = _mapping_sets(store, first_id)
    second = _mapping_sets(store, second_id)
    for provider in set(first) & set(second):
        if first[provider].isdisjoint(second[provider]):
            return False
    return True


def _repair_epl_alias_duplicates(engine, tolerance_seconds=20 * 60):
    """Merge only the one-to-one EPL aliases demonstrated by live validation."""
    store = engine.store
    _install_epl_aliases()
    with store._lock, closing(store._connect(readonly=True)) as conn:
        rows = [dict(x) for x in conn.execute(
            """SELECT * FROM canonical_event
               WHERE competition_id='EPL' AND active=1 AND scheduled_at<>''
               ORDER BY slate_date,scheduled_at,first_seen_at,canonical_event_id"""
        ).fetchall()]

    grouped = defaultdict(list)
    for row in rows:
        pair = v619._row_pair("EPL", row)
        ts = shadow._epoch(row.get("scheduled_at"))
        day = _clean(row.get("slate_date"))
        if not day or ts is None or not all(pair):
            continue
        grouped[(day, pair)].append(row)

    merged = []
    touched = set()
    for (day, _pair), candidates in grouped.items():
        candidates = sorted(
            candidates,
            key=lambda row: (
                shadow._epoch(row.get("scheduled_at")) or 0.0,
                row["canonical_event_id"],
            ),
        )
        clusters = []
        for row in candidates:
            ts = shadow._epoch(row.get("scheduled_at")) or 0.0
            if (
                not clusters
                or abs(ts - (shadow._epoch(clusters[-1][-1].get("scheduled_at")) or 0.0))
                > tolerance_seconds
            ):
                clusters.append([row])
            else:
                clusters[-1].append(row)

        for cluster in clusters:
            # Fail closed. The demonstrated defect is exactly one official-only
            # identity plus one ESPN/legacy identity for the same fixture.
            if len(cluster) != 2:
                continue
            first, second = cluster
            classes_first = set(store.evidence_classes(first["canonical_event_id"]))
            classes_second = set(store.evidence_classes(second["canonical_event_id"]))
            auth_only_first = "AUTHORITATIVE" in classes_first and "INDEPENDENT" not in classes_first
            auth_only_second = "AUTHORITATIVE" in classes_second and "INDEPENDENT" not in classes_second
            broad_first = "INDEPENDENT" in classes_first and bool(classes_first & {"DIRECT", "LEGACY"})
            broad_second = "INDEPENDENT" in classes_second and bool(classes_second & {"DIRECT", "LEGACY"})

            if auth_only_first and broad_second:
                loser, survivor = first, second
            elif auth_only_second and broad_first:
                loser, survivor = second, first
            else:
                continue

            if not _provider_sets_compatible(
                store,
                loser["canonical_event_id"],
                survivor["canonical_event_id"],
            ):
                continue

            if v619._merge_event(store, survivor, loser, day):
                merged.append({
                    "date": day,
                    "survivor": survivor["canonical_event_id"],
                    "merged": loser["canonical_event_id"],
                    "away": survivor.get("away_name"),
                    "home": survivor.get("home_name"),
                })
                touched.add(day)

    # Refresh legacy comparison IDs after any mapping movement, then compile the
    # touched EPL dates immediately so persisted/effective certification agrees.
    shadow_engine = getattr(engine, "shadow", None)
    for day in sorted(touched):
        if shadow_engine is not None:
            try:
                _count, legacy_ids, _touched, snapshot_present = shadow_engine.ingest_day_state(day)
                if snapshot_present:
                    store.record_comparison(day, "EPL", legacy_ids.get("EPL", set()))
            except Exception:
                pass
        try:
            store.compile_slate(
                day,
                "EPL",
                "EPL_EXPLICIT_ALIAS_RECONCILIATION",
                force_version=True,
            )
        except Exception:
            pass

    return {
        "merged": len(merged),
        "pairs": merged,
        "touched": sorted(touched),
    }


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


def _install_post_run_reconciliation():
    cls = v610.CertificationEngine
    if getattr(cls, "__sbbV6116EplIdentityStateReconciliation", False):
        return
    original = cls.run_horizon

    def run_horizon(self):
        stats = original(self)
        try:
            identity = _repair_epl_alias_duplicates(self)
            state = _normalize_stale_known_conflicts(self.store)
            if isinstance(stats, dict):
                stats["eplAliasReconciliation"] = identity
                stats["staleConflictNormalization"] = state
                self.last_stats = stats
        except Exception as exc:
            if isinstance(stats, dict):
                stats.setdefault("errors", []).append(
                    f"EPL identity/state reconciliation: {type(exc).__name__}: {exc}"
                )
            self.last_error = (
                f"EPL identity/state reconciliation: {type(exc).__name__}: {exc}"
            )
        return stats

    cls.run_horizon = run_horizon
    cls.__sbbV6116EplIdentityStateReconciliation = True


def _patch_health():
    cls = v610.CertificationEngine
    if getattr(cls, "__sbbV6116EplFplStateHealthV2", False):
        return
    original = cls.health

    def health(self):
        payload = original(self)
        payload["eplFplStateFollowupVersion"] = VERSION
        payload.setdefault("hardening", {}).update(
            {
                "eplOfficialFplApiAuthoritative": True,
                "eplOfficialFplApiHost": EPL_HOST,
                "eplExplicitTeamAliasNormalization": True,
                "eplPostCollectionAliasReconciliation": True,
                "staleKnownConflictStateNormalization": True,
                "productionAuthority": False,
            }
        )
        return payload

    cls.health = health
    cls.__sbbV6116EplFplStateHealthV2 = True


def _runtime_install():
    global _PATCHED
    deadline = time.time() + 180
    engine = None
    while time.time() < deadline:
        engine = watchdogs.engine()
        if engine is not None and getattr(reconcile_followup, "_PATCHED", False):
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
    _install_epl_aliases()

    cls = v610.CertificationEngine
    cls._collect_epl = _collect_epl_official_fpl
    _install_post_run_reconciliation()
    _patch_health()
    _PATCHED = True

    initial_identity_repair = _repair_epl_alias_duplicates(engine)
    initial_state_repair = _normalize_stale_known_conflicts(engine.store)
    try:
        server = sys.modules.get("__main__")
        if server is not None:
            server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update(
                {
                    "eplFplStateFollowupVersion": VERSION,
                    "eplAuthoritativeSource": EPL_SOURCE,
                    "eplAuthoritativeHost": EPL_HOST,
                    "eplExplicitTeamAliasNormalization": True,
                    "eplPostCollectionAliasReconciliation": True,
                    "initialEplIdentityRepair": initial_identity_repair,
                    "staleKnownConflictStateNormalization": True,
                    "initialStaleStateRepair": initial_state_repair,
                    "productionAuthority": False,
                }
            )
    except Exception:
        pass

    # Refresh immediately so the alias resolver applies to new FPL observations
    # and all 15 EPL date decisions become visible without waiting for cadence.
    try:
        engine.run_horizon()
    except Exception as exc:
        engine.last_error = (
            f"v6.1.16 EPL/FPL identity-state follow-up: {type(exc).__name__}: {exc}"
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

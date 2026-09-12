"""Sports Big Board v6.1.10 canonical run-integrity + throughput repair.

Shadow-only hardening for the canonical timeline lane. Production authority remains
false. This patch addresses the concrete validation defects observed after v6.1.9:

* inactive MERGED audit rows remain inspectable but never participate in live
  certification evidence decisions;
* one source/window evidence snapshot is persisted in one SQLite transaction so a
  collector cannot expose fresh coverage before all of its event evidence commits;
* validation bulk reads pin one SQLite snapshot for a transactionally consistent
  console view;
* last-complete certification evidence is retained only while a league is still
  waiting for its refresh turn in an active reconciliation run;
* worker health exposes current league/source/stage and completed leagues;
* NCAAF rank prefixes plus the demonstrated Georgia/Houston provider aliases are
  normalized conservatively, then the v6.1.9 duplicate repair is rerun.
"""
from __future__ import annotations

import re
import sys
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta

from . import canonical_shadow_v600 as shadow
from . import canonical_certification_v610 as v610
from . import canonical_certification_v611 as v611
from . import canonical_validation_v612 as v612
from . import canonical_identity_ingestion_v619 as v619

VERSION = "6.1.10-canonical-run-integrity-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_BATCH_LOCAL = threading.local()


def _clean(value):
    return str(value or "").strip()


def _active_event(event):
    value = event.get("active", 1)
    active = 1 if value is None else int(value or 0)
    return bool(active) and _clean(event.get("identity_state")).upper() != "MERGED"


# ---------------------------------------------------------------------------
# Narrow identity additions observed in the live v6.1.9 console.
# ---------------------------------------------------------------------------
_NCAAF_EXTRA_GROUPS = (
    ("Georgia", "Georgia Bulldogs"),
    ("Houston", "Houston Cougars"),
)
_NCAAF_EXTRA = {}
for _group in _NCAAF_EXTRA_GROUPS:
    _canonical = shadow._norm(_group[0])
    for _name in _group:
        _NCAAF_EXTRA[shadow._norm(_name)] = _canonical


def _install_alias_expansion():
    if getattr(v619, "__sbbV6110AliasExpansion", False):
        return
    original = v619._canonical_team_key

    def canonical_team_key(league, value):
        raw = _clean(value)
        if _clean(league).upper() == "NCAAF":
            # ESPN display names may carry the current poll rank (for example
            # '#2 Georgia Bulldogs'). Rank is presentation, never team identity.
            raw = re.sub(r"^\s*#?\s*\d+\s+", "", raw)
        key = original(league, raw)
        if _clean(league).upper() == "NCAAF":
            key = _NCAAF_EXTRA.get(key, key)
        return key

    v619._canonical_team_key = canonical_team_key
    v619.__sbbV6110AliasExpansion = True


# ---------------------------------------------------------------------------
# Source/window batching. Existing store methods keep their behavior, but their
# short-lived connections/commit calls share one real connection while a
# CertificationEvidenceWriter.snapshot is active on the current thread.
# ---------------------------------------------------------------------------
class _BatchConnectionProxy:
    def __init__(self, conn):
        self._conn = conn
        self.commit_calls = 0
        self.close_calls = 0

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._conn.executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        return self._conn.executescript(*args, **kwargs)

    def commit(self):
        # Commit once at the source/window boundary instead of once per event fact.
        self.commit_calls += 1

    def rollback(self):
        # The outer snapshot owns rollback semantics.
        return None

    def close(self):
        # closing(proxy) is used throughout the legacy store. Keep the real handle
        # alive until the source/window snapshot completes.
        self.close_calls += 1

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _install_batch_persistence():
    store_cls = shadow.CanonicalShadowStore
    writer_cls = v610.CertificationEvidenceWriter
    if getattr(store_cls, "__sbbV6110BatchPersistence", False):
        return

    original_connect = store_cls._connect
    original_snapshot = writer_cls.snapshot

    def connect(self, readonly=False):
        state = getattr(_BATCH_LOCAL, "state", None)
        if state and state.get("store") is self:
            # Reads during identity resolution must see uncommitted writes from the
            # same source snapshot; do not flip query_only on the shared handle.
            return state["proxy"]
        return original_connect(self, readonly)

    def snapshot(self, groups, days, league, source, source_class, success_days=None, errors=None):
        if getattr(_BATCH_LOCAL, "state", None):
            return original_snapshot(self, groups, days, league, source, source_class, success_days, errors)

        started = time.perf_counter()
        real = None
        proxy = None
        with self.store._lock:
            try:
                real = original_connect(self.store, False)
                proxy = _BatchConnectionProxy(real)
                real.execute("BEGIN IMMEDIATE")
                _BATCH_LOCAL.state = {"store": self.store, "proxy": proxy}
                result = original_snapshot(self, groups, days, league, source, source_class, success_days, errors)
                real.commit()
                self.store.__sbbV6110LastBatch = {
                    "league": league,
                    "source": source,
                    "sourceClass": source_class,
                    "events": int(result or 0),
                    "days": len(list(days or [])),
                    "durationMs": round((time.perf_counter() - started) * 1000.0, 2),
                    "suppressedCommitCalls": int(proxy.commit_calls),
                    "commits": 1,
                }
                return result
            except Exception:
                if real is not None:
                    try:
                        real.rollback()
                    except Exception:
                        pass
                raise
            finally:
                _BATCH_LOCAL.state = None
                if real is not None:
                    try:
                        real.close()
                    except Exception:
                        pass

    store_cls._connect = connect
    writer_cls.snapshot = snapshot
    store_cls.__sbbV6110BatchPersistence = True
    store_cls.__sbbV6110OriginalConnect = original_connect
    writer_cls.__sbbV6110BatchSnapshot = True


# ---------------------------------------------------------------------------
# Validation read integrity + live-row semantics.
# ---------------------------------------------------------------------------
def _install_transactional_bulk_read():
    cls = v612.ValidationDiagnostics
    if getattr(cls, "__sbbV6110TransactionalBulk", False):
        return

    def bulk(self, day_from, day_to):
        out = {
            "slates": [], "comparisons": [], "coverage": [], "events": [],
            "observations": [], "scores": [], "mappings": [], "tables": [],
        }
        try:
            with self.store._lock, closing(self._connect(readonly=True)) as conn:
                # Python's sqlite driver does not pin a read transaction for a
                # sequence of plain SELECTs. BEGIN makes all diagnostic tables come
                # from one WAL snapshot.
                conn.execute("BEGIN")
                tables = self._tables(conn)
                out["tables"] = sorted(tables)
                if "daily_slate" in tables:
                    out["slates"] = [dict(r) for r in conn.execute(
                        "SELECT * FROM daily_slate WHERE slate_date BETWEEN ? AND ? ORDER BY slate_date,competition_id,version DESC",
                        (day_from, day_to),
                    ).fetchall()]
                if "slate_comparison" in tables:
                    out["comparisons"] = [dict(r) for r in conn.execute(
                        "SELECT * FROM slate_comparison WHERE slate_date BETWEEN ? AND ? ORDER BY slate_date,competition_id,last_observed_at DESC,id DESC",
                        (day_from, day_to),
                    ).fetchall()]
                if "source_coverage" in tables:
                    out["coverage"] = [dict(r) for r in conn.execute(
                        "SELECT * FROM source_coverage WHERE slate_date BETWEEN ? AND ? ORDER BY slate_date,competition_id,source,last_observed_at DESC,id DESC",
                        (day_from, day_to),
                    ).fetchall()]
                if "canonical_event" in tables:
                    # Keep inactive/MERGED rows in the audit inventory. Live
                    # certification filtering happens in _decision below.
                    out["events"] = [dict(r) for r in conn.execute(
                        "SELECT * FROM canonical_event WHERE slate_date BETWEEN ? AND ? ORDER BY slate_date,competition_id,scheduled_at,canonical_event_id",
                        (day_from, day_to),
                    ).fetchall()]
                if "schedule_observation" in tables and "canonical_event" in tables:
                    out["observations"] = [dict(r) for r in conn.execute(
                        """SELECT so.*,ce.slate_date AS _slate_date,ce.competition_id AS _competition_id
                           FROM schedule_observation so JOIN canonical_event ce ON ce.canonical_event_id=so.canonical_event_id
                           WHERE ce.slate_date BETWEEN ? AND ? ORDER BY so.canonical_event_id,so.last_observed_at DESC""",
                        (day_from, day_to),
                    ).fetchall()]
                if "score_observation" in tables and "canonical_event" in tables:
                    out["scores"] = [dict(r) for r in conn.execute(
                        """SELECT so.*,ce.slate_date AS _slate_date,ce.competition_id AS _competition_id
                           FROM score_observation so JOIN canonical_event ce ON ce.canonical_event_id=so.canonical_event_id
                           WHERE ce.slate_date BETWEEN ? AND ? ORDER BY so.canonical_event_id""",
                        (day_from, day_to),
                    ).fetchall()]
                for table in ("provider_event_mapping", "provider_event_mappings", "canonical_provider_mapping"):
                    if table in tables:
                        out["mappings"] = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
                        break
                conn.rollback()
        except Exception as exc:
            self.last_error = f"bulk diagnostic read: {type(exc).__name__}: {exc}"
        return out

    cls._bulk = bulk
    cls.__sbbV6110TransactionalBulk = True


def _historically_complete(events, obs_by_event):
    for event in events:
        if not _active_event(event) or _clean(event.get("inclusion_state")).upper() != "INCLUDED":
            continue
        classes = {
            _clean(row.get("source_class")).upper()
            for row in obs_by_event.get(event.get("canonical_event_id"), [])
            if _clean(row.get("source_class"))
        }
        if not {"AUTHORITATIVE", "INDEPENDENT"} <= classes:
            return False
    return True


def _install_live_validation_decisions():
    cls = v612.ValidationDiagnostics
    if getattr(cls, "__sbbV6110LiveDecision", False):
        return
    original = cls._decision

    def decision(self, day, league, slate, comparison, cov_by_source, events, obs_by_event, event_by_id, adjacent_lookup):
        live_events = [event for event in events if _active_event(event)]
        merged_audit = [event for event in events if not _active_event(event)]
        result = original(
            self, day, league, slate, comparison, cov_by_source,
            live_events, obs_by_event, event_by_id, adjacent_lookup,
        )
        result["mergedAuditRows"] = [
            {
                "canonicalEventId": row.get("canonical_event_id"),
                "identityState": row.get("identity_state"),
                "removalState": row.get("removal_state"),
                "away": row.get("away_name"), "home": row.get("home_name"),
                "scheduledAt": row.get("scheduled_at"),
            }
            for row in merged_audit
        ]
        result["mergedAuditRowCount"] = len(merged_audit)
        trace = result.get("decisionTrace") or []
        trace.insert(max(0, len(trace) - 2), {
            "code": "MERGED_AUDIT_ROWS",
            "status": "PASS",
            "detail": f"{len(merged_audit)} inactive/merged audit row(s) excluded from live certification",
        })

        # Refresh grace is deliberately narrow. It only preserves a previously
        # CERTIFIED state while this league has not yet completed its refresh in
        # the currently active run, and only when the last stored evidence was
        # genuinely complete. Once the league collector finishes, failures are
        # evaluated normally and cannot be hidden by this rule.
        try:
            health = self.engine.health() or {}
        except Exception:
            health = {}
        run_in_progress = bool(health.get("runInProgress"))
        completed = set(health.get("currentRunCompletedLeagues") or [])
        run_age = float(health.get("currentRunAgeSeconds") or 0.0)
        max_grace = max(float(v610.FRESH_SECONDS) * 2.0, 7200.0)
        cov = result.get("sourceCoverage") or {}
        auth = cov.get("authoritative") or {}
        indep = cov.get("independent") or {}
        last_complete_coverage = bool(int(auth.get("success") or 0) and int(indep.get("success") or 0))
        no_hard_blocker = not bool(
            result.get("productionOnly") or result.get("unresolved") or result.get("unknown")
            or result.get("sourceCountConflict")
        )
        can_grace = bool(
            run_in_progress and league not in completed and run_age <= max_grace
            and _clean(result.get("persistedStatus")).upper() == "CERTIFIED"
            and last_complete_coverage and no_hard_blocker
            and _historically_complete(live_events, obs_by_event)
            and _clean(result.get("effectiveStatus")).upper() != "CERTIFIED"
        )
        if can_grace:
            stale_gaps = list(result.get("evidenceGaps") or [])
            result["refreshInProgressGrace"] = True
            result["refreshInProgressStaleEvidenceGaps"] = stale_gaps
            result["evidenceGaps"] = []
            result["effectiveStatus"] = "CERTIFIED"
            result["effectiveReason"] = "CERTIFICATION_EVIDENCE_COMPLETE | REFRESH_IN_PROGRESS_LAST_COMPLETE_EVIDENCE"
            result["cutoverReady"] = True
            result["stateConsistencyViolation"] = False
            for step in trace:
                code = step.get("code")
                if code in {"AUTHORITATIVE_COVERAGE", "INDEPENDENT_COVERAGE", "EVENT_EVIDENCE_COMPLETE"} and step.get("status") != "PASS":
                    step["status"] = "WARN"
                    step["detail"] = _clean(step.get("detail")) + " (refresh pending; last complete evidence retained)"
                elif code == "EFFECTIVE_CERTIFICATION":
                    step.update({"status": "PASS", "detail": "CERTIFIED (refresh in progress)"})
                elif code == "CUTOVER_READY":
                    step.update({"status": "PASS", "detail": "READY (refresh in progress)"})
        else:
            result["refreshInProgressGrace"] = False
        return result

    cls._decision = decision
    cls.__sbbV6110LiveDecision = True


# ---------------------------------------------------------------------------
# Worker stage observability. Install at runtime after v6.1.2 probe hooks and
# v6.1.8 run timing have attached so we preserve both older wrappers.
# ---------------------------------------------------------------------------
def _set_stage(engine, stage, league="", source="", source_class=""):
    engine.__sbbV6110Stage = stage
    engine.__sbbV6110League = league
    engine.__sbbV6110Source = source
    engine.__sbbV6110SourceClass = source_class
    engine.__sbbV6110StageStartedAt = time.time()


def _install_worker_stage_observability():
    cls = v610.CertificationEngine
    if getattr(cls, "__sbbV6110WorkerStages", False):
        return

    original_run = cls.run_horizon
    original_independent = cls._collect_espn_independent
    original_authoritative = cls._collect_authoritative
    original_health = cls.health

    def run_horizon(self):
        self.__sbbV6110RunStartedAt = time.time()
        self.__sbbV6110IndependentDone = set()
        self.__sbbV6110AuthoritativeDone = set()
        self.__sbbV6110CompletedLeagues = set()
        _set_stage(self, "RUN_START")
        try:
            return original_run(self)
        finally:
            self.__sbbV6110LastCompletedLeagues = sorted(getattr(self, "__sbbV6110CompletedLeagues", set()))
            self.__sbbV6110RunStartedAt = 0.0
            _set_stage(self, "IDLE")

    def collect_independent(self, league, day_from, day_to):
        _set_stage(self, "INDEPENDENT_COLLECT", league, v610.INDEPENDENT_SOURCE, "INDEPENDENT")
        try:
            return original_independent(self, league, day_from, day_to)
        finally:
            done = getattr(self, "__sbbV6110IndependentDone", set())
            done.add(league)
            self.__sbbV6110IndependentDone = done

    def collect_authoritative(self, league, day_from, day_to):
        source = v610.SOURCE_DEFS.get(league, {}).get("authoritative", "")
        _set_stage(self, "AUTHORITATIVE_COLLECT", league, source, "AUTHORITATIVE")
        try:
            return original_authoritative(self, league, day_from, day_to)
        finally:
            auth_done = getattr(self, "__sbbV6110AuthoritativeDone", set())
            auth_done.add(league)
            self.__sbbV6110AuthoritativeDone = auth_done
            if league in getattr(self, "__sbbV6110IndependentDone", set()):
                completed = getattr(self, "__sbbV6110CompletedLeagues", set())
                completed.add(league)
                self.__sbbV6110CompletedLeagues = completed

    def health(self):
        payload = original_health(self)
        started = float(getattr(self, "__sbbV6110RunStartedAt", 0.0) or 0.0)
        stage_started = float(getattr(self, "__sbbV6110StageStartedAt", 0.0) or 0.0)
        payload["runInProgress"] = bool(started) or bool(payload.get("runInProgress"))
        if started:
            payload["currentRunStartedAt"] = started
            payload["currentRunAgeSeconds"] = round(max(0.0, time.time() - started), 3)
        payload.update({
            "currentRunStage": _clean(getattr(self, "__sbbV6110Stage", "IDLE")) or "IDLE",
            "currentRunLeague": _clean(getattr(self, "__sbbV6110League", "")),
            "currentRunSource": _clean(getattr(self, "__sbbV6110Source", "")),
            "currentRunSourceClass": _clean(getattr(self, "__sbbV6110SourceClass", "")),
            "currentRunStageAgeSeconds": round(max(0.0, time.time() - stage_started), 3) if stage_started else None,
            "currentRunCompletedLeagues": sorted(getattr(self, "__sbbV6110CompletedLeagues", set())),
            "lastRunCompletedLeaguesV6110": list(getattr(self, "__sbbV6110LastCompletedLeagues", [])),
            "canonicalRunIntegrityVersion": VERSION,
            "batchPersistence": getattr(self.store, "__sbbV6110LastBatch", None),
        })
        return payload

    cls.run_horizon = run_horizon
    cls._collect_espn_independent = collect_independent
    cls._collect_authoritative = collect_authoritative
    cls.health = health
    cls.__sbbV6110WorkerStages = True


def _install_console_stage_fields():
    cls = v612.ValidationDiagnostics
    if getattr(cls, "__sbbV6110ConsoleStages", False):
        return
    original = cls.build_snapshot

    def build_snapshot(self):
        snapshot = original(self)
        try:
            health = self.engine.health() or {}
            worker = snapshot.setdefault("worker", {})
            worker.update({
                "certificationCurrentRunStage": health.get("currentRunStage") or "IDLE",
                "certificationCurrentRunLeague": health.get("currentRunLeague") or "",
                "certificationCurrentRunSource": health.get("currentRunSource") or "",
                "certificationCurrentRunSourceClass": health.get("currentRunSourceClass") or "",
                "certificationCurrentRunStageAgeSeconds": health.get("currentRunStageAgeSeconds"),
                "certificationCurrentRunCompletedLeagues": health.get("currentRunCompletedLeagues") or [],
                "certificationBatchPersistence": health.get("batchPersistence"),
            })
            snapshot.setdefault("diagnosticHooks", {}).update({
                "activeEventCertificationOnly": True,
                "transactionalValidationRead": True,
                "sourceWindowBatchPersistence": True,
                "workerStageObservability": True,
                "refreshInProgressGrace": True,
            })
            report = self._report(snapshot)
            with self.lock:
                self.cache["snapshot"] = snapshot
                self.cache["report"] = report
        except Exception:
            pass
        return snapshot

    cls.build_snapshot = build_snapshot
    cls.__sbbV6110ConsoleStages = True


def _runtime_repair():
    # Wait until the certification engine, v6.1.2 diagnostics, and v6.1.8 timing
    # wrapper are all live. This lets v6.1.10 wrap the final runtime surface rather
    # than racing an older installer thread.
    while True:
        engine = v611.engine()
        diag = v612.engine()
        server = sys.modules.get("__main__")
        if (
            engine and diag and server and hasattr(server, "Handler")
            and getattr(v610.CertificationEngine, "__sbbV618ReadinessObservability", False)
        ):
            break
        time.sleep(0.25)

    _install_worker_stage_observability()
    _install_console_stage_fields()
    repair = v619._repair_duplicate_identities(engine.store)
    try:
        server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update({
            "runIntegrityVersion": VERSION,
            "activeEventCertificationOnly": True,
            "transactionalValidationRead": True,
            "sourceWindowBatchPersistence": True,
            "refreshInProgressGrace": "UNTIL_LEAGUE_REFRESH_COMPLETES",
            "identityRepairV6110": repair,
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
    _install_alias_expansion()
    _install_batch_persistence()
    _install_transactional_bulk_read()
    _install_live_validation_decisions()
    threading.Thread(target=_runtime_repair, daemon=True, name="sbb-canonical-run-integrity-v6110").start()

"""Sports Big Board v6.1.5 canonical slate readiness repair.

This is a narrow shadow-lane hardening overlay. It does not make canonical data
production authority. It fixes three issues found by the live validation console:

* SQLite durability tuning was applied only to the schema-init connection even
  though canonical writes open a fresh connection for each operation. Reapply
  synchronous=NORMAL on every writable connection, matching the original WAL
  design intent and avoiding full-fsync cost on every tiny evidence commit.
* NCAAF UNKNOWN is an unresolved policy state and must never overwrite a
  previously resolved INCLUDED/EXCLUDED decision. Existing UNKNOWN rows with
  complete authoritative + independent evidence are repaired in place.
* Legacy Day State comparisons are rebucketed to the canonical Eastern slate
  date before mismatch accounting, so UTC-boundary games are classified on the
  canonical day instead of becoming false production-only/shadow-only blockers.

Production authority remains false. The current board remains the consumer until
an explicit later cutover.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from contextlib import closing
from datetime import date, datetime, timedelta

from . import canonical_shadow_v600 as shadow
from . import canonical_certification_v610 as v610
from . import canonical_certification_v611 as v611

VERSION = "6.1.5-canonical-slate-readiness-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _clean(value):
    return str(value or "").strip()


def _json_load(value):
    try:
        return json.loads(value) if value else {}
    except Exception:
        return {}


def _scheduled_et_day(value):
    ts = shadow._epoch(value)
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(ts, shadow.ET).date().isoformat()
    except Exception:
        return ""


def _adjacent_days(day):
    d = date.fromisoformat(day)
    return (d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat()


def _install_connection_tuning():
    cls = shadow.CanonicalShadowStore
    if getattr(cls, "__sbbV615WritableConnectionTuning", False):
        return
    original = cls._connect

    def _connect(self, readonly=False):
        conn = original(self, readonly)
        if not readonly:
            # _init_db() set this only on its own connection. SQLite PRAGMA
            # synchronous is connection-local, while canonical evidence writes
            # intentionally open many short-lived connections.
            conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    cls._connect = _connect
    cls.__sbbV615WritableConnectionTuning = True


def _install_ncaaf_state_precedence():
    cls = shadow.CanonicalShadowStore
    if getattr(cls, "__sbbV615NcaafStatePrecedence", False):
        return
    original = cls.upsert_event

    def upsert_event(
        self, canonical_event_id, league, slate_date, event, source,
        identity_state, inclusion_state, inclusion_reason,
    ):
        # UNKNOWN means "not decided yet". It may not regress a decision that a
        # certification source has already resolved. INCLUDED may still replace
        # EXCLUDED later if a team enters the Top 25; v6.0 already protects the
        # reverse INCLUDED -> non-INCLUDED transition.
        if league == "NCAAF" and _clean(inclusion_state).upper() == "UNKNOWN":
            try:
                with self._lock, closing(self._connect(readonly=True)) as conn:
                    row = conn.execute(
                        "SELECT inclusion_state,inclusion_reason FROM canonical_event WHERE canonical_event_id=?",
                        (canonical_event_id,),
                    ).fetchone()
                if row and _clean(row[0]).upper() in {"INCLUDED", "EXCLUDED"}:
                    inclusion_state = _clean(row[0]).upper()
                    inclusion_reason = _clean(row[1]) or inclusion_reason
            except Exception:
                pass
        return original(
            self, canonical_event_id, league, slate_date, event, source,
            identity_state, inclusion_state, inclusion_reason,
        )

    cls.upsert_event = upsert_event
    cls.__sbbV615NcaafStatePrecedence = True


def _normalized_legacy_ids(store, slate_date, league, legacy_ids):
    """Return production membership rebucketed to canonical Eastern ownership."""
    legacy = {str(x) for x in (legacy_ids or set()) if x}
    normalized = set(legacy)
    moves = []
    prev_day, next_day = _adjacent_days(slate_date)

    with store._lock, closing(store._connect(readonly=True)) as conn:
        if legacy:
            placeholders = ",".join("?" for _ in legacy)
            rows = conn.execute(
                f"SELECT canonical_event_id,slate_date,scheduled_at FROM canonical_event "
                f"WHERE canonical_event_id IN ({placeholders})",
                tuple(sorted(legacy)),
            ).fetchall()
            for row in rows:
                event_id = str(row[0])
                canonical_day = _clean(row[1])
                scheduled_day = _scheduled_et_day(row[2])
                if (
                    canonical_day and canonical_day != slate_date
                    and canonical_day in {prev_day, next_day}
                    and scheduled_day == canonical_day
                ):
                    normalized.discard(event_id)
                    moves.append({
                        "canonicalEventId": event_id,
                        "legacyDate": slate_date,
                        "canonicalDate": canonical_day,
                        "direction": "OUT",
                    })

        # If production observed a canonical-day event on the adjacent UTC day,
        # move that evidence onto the canonical day for comparison purposes.
        rows = conn.execute(
            """SELECT DISTINCT ce.canonical_event_id,ce.scheduled_at,so.observed_day
               FROM canonical_event ce
               JOIN schedule_observation so ON so.canonical_event_id=ce.canonical_event_id
               WHERE ce.slate_date=? AND ce.competition_id=? AND ce.active=1
                 AND so.source='DAY_STATE' AND so.observed_day IN (?,?)""",
            (slate_date, league, prev_day, next_day),
        ).fetchall()
        for row in rows:
            event_id = str(row[0])
            observed_day = _clean(row[2])
            if _scheduled_et_day(row[1]) != slate_date:
                continue
            normalized.add(event_id)
            moves.append({
                "canonicalEventId": event_id,
                "legacyDate": observed_day,
                "canonicalDate": slate_date,
                "direction": "IN",
            })

    unique = []
    seen = set()
    for move in moves:
        key = (move["canonicalEventId"], move["legacyDate"], move["canonicalDate"], move["direction"])
        if key not in seen:
            seen.add(key)
            unique.append(move)
    return normalized, unique


def _install_canonical_date_comparisons():
    cls = shadow.CanonicalShadowStore
    if getattr(cls, "__sbbV615CanonicalDateComparisons", False):
        return
    original = cls.record_comparison

    def record_comparison(self, slate_date, league, legacy_ids):
        normalized, moves = _normalized_legacy_ids(self, slate_date, league, legacy_ids)
        details = original(self, slate_date, league, normalized)
        if not moves:
            return details

        # Persist the rebucketing provenance as the newest comparison row so the
        # validation console can explain why a legacy UTC-day discrepancy stopped
        # being a cutover blocker.
        enriched = dict(details or {})
        enriched["legacyDateBucketMoves"] = moves
        digest = shadow._payload_hash(enriched)
        now = shadow._now()
        canonical_count = int(enriched.get("shadowDiscoveryCount") or 0)
        legacy_count = len(normalized)
        matched_count = int(enriched.get("matched") or 0)
        canonical_only = list(enriched.get("canonicalOnly") or [])
        legacy_only = list(enriched.get("legacyOnly") or [])
        with self._lock, closing(self._connect()) as conn:
            conn.execute(
                """INSERT INTO slate_comparison(
                    slate_date,competition_id,observed_at,last_observed_at,canonical_count,legacy_count,
                    matched_count,canonical_only_count,legacy_only_count,conflict_count,comparison_hash,details_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(slate_date,competition_id,comparison_hash) DO UPDATE SET
                    last_observed_at=excluded.last_observed_at, observation_count=observation_count+1""",
                (
                    slate_date, league, now, now, canonical_count, legacy_count,
                    matched_count, len(canonical_only), len(legacy_only), 0,
                    digest, shadow._json(enriched),
                ),
            )
            conn.commit()
        return enriched

    cls.record_comparison = record_comparison
    cls.__sbbV615CanonicalDateComparisons = True


def _repair_ncaaf_policy_states(store):
    """Resolve stale UNKNOWN rows only when both certification classes exist."""
    changed_days = set()
    repaired = 0
    with store._lock, closing(store._connect(readonly=True)) as conn:
        events = conn.execute(
            """SELECT canonical_event_id,slate_date FROM canonical_event
               WHERE competition_id='NCAAF' AND active=1 AND inclusion_state='UNKNOWN'"""
        ).fetchall()

    for event in events:
        event_id, slate_date = str(event[0]), str(event[1])
        with store._lock, closing(store._connect(readonly=True)) as conn:
            rows = conn.execute(
                """SELECT source_class,raw_json,last_observed_at FROM schedule_observation
                   WHERE canonical_event_id=? AND source_class IN ('AUTHORITATIVE','INDEPENDENT')
                   ORDER BY last_observed_at DESC""",
                (event_id,),
            ).fetchall()
        by_class = {}
        for row in rows:
            cls = _clean(row[0]).upper()
            by_class.setdefault(cls, row)
        if not {"AUTHORITATIVE", "INDEPENDENT"} <= set(by_class):
            continue

        states = []
        for cls in ("AUTHORITATIVE", "INDEPENDENT"):
            raw = _json_load(by_class[cls][1])
            state, _reason = v610._ncaaf_inclusion(raw)
            states.append(state)
        new_state = "INCLUDED" if "INCLUDED" in states else "EXCLUDED"
        new_reason = "NCAAF_TOP25" if new_state == "INCLUDED" else "NCAAF_OUTSIDE_TOP25"
        with store._lock, closing(store._connect()) as conn:
            cur = conn.execute(
                """UPDATE canonical_event SET inclusion_state=?,inclusion_reason=?,updated_at=?
                   WHERE canonical_event_id=? AND inclusion_state='UNKNOWN'""",
                (new_state, new_reason, shadow._now(), event_id),
            )
            conn.commit()
        if cur.rowcount:
            repaired += 1
            changed_days.add(slate_date)

    for day in sorted(changed_days):
        try:
            store.compile_slate(day, "NCAAF", "NCAAF_POLICY_REPAIR")
        except Exception:
            pass
    return {"repaired": repaired, "days": sorted(changed_days)}


def _install_engine_observability(engine):
    cls = v610.CertificationEngine
    if getattr(cls, "__sbbV615ReadinessObservability", False):
        return
    original_run = cls.run_horizon
    original_health = cls.health

    def run_horizon(self):
        self.__sbbV615RunStartedAt = time.time()
        started = time.perf_counter()
        try:
            result = original_run(self)
            if isinstance(result, dict):
                result["readinessPatchVersion"] = VERSION
                result["storageSynchronous"] = "NORMAL"
                result["wallSecondsV615"] = round(time.perf_counter() - started, 3)
                self.last_stats = result
            return result
        finally:
            self.__sbbV615RunStartedAt = 0.0

    def health(self):
        payload = original_health(self)
        started_at = float(getattr(self, "__sbbV615RunStartedAt", 0.0) or 0.0)
        payload["readinessRepair"] = {
            "version": VERSION,
            "writableConnectionSynchronous": "NORMAL",
            "ncaafResolvedStatePrecedence": True,
            "canonicalDateComparison": True,
            "productionAuthority": False,
        }
        payload["runInProgress"] = bool(started_at)
        payload["currentRunStartedAt"] = started_at
        payload["currentRunAgeSeconds"] = round(max(0.0, time.time() - started_at), 3) if started_at else None
        return payload

    cls.run_horizon = run_horizon
    cls.health = health
    cls.__sbbV615ReadinessObservability = True


def _runtime_repair():
    # The materializer installs this after v6.1.2, but keep startup tolerant of
    # import-thread races and future install-order changes.
    while True:
        engine = v611.engine()
        server = sys.modules.get("__main__")
        if engine and server and hasattr(server, "Handler"):
            break
        time.sleep(0.25)
    _install_engine_observability(engine)
    repair = _repair_ncaaf_policy_states(engine.store)
    try:
        server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update({
            "readinessRepairVersion": VERSION,
            "canonicalDateOwnership": "EASTERN",
            "ncaafPolicyRepair": repair,
            "productionAuthority": False,
        })
    except Exception:
        pass
    try:
        engine.run_horizon()
    except Exception as exc:
        engine.last_error = f"v6.1.5 readiness repair reconcile: {type(exc).__name__}: {exc}"


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    _install_connection_tuning()
    _install_ncaaf_state_precedence()
    _install_canonical_date_comparisons()
    threading.Thread(target=_runtime_repair, daemon=True, name="sbb-canonical-slate-readiness-v615").start()

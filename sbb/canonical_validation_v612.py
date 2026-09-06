"""Sports Big Board v6.1.2 canonical slate validation diagnostics.

This module is a shadow-only diagnostic/read-model layer.  It does not select,
remove, or publish production events.  It exists to make every canonical-slate
decision inspectable and exportable:

* one internally consistent D-7/D+7 validation snapshot drives the console;
* persisted source coverage rehydrates adapter status after backend restarts;
* every league/day gets a decision trace showing exactly why it is certified,
  reconciling, baseline, and/or blocked from cutover;
* discrepancy events carry schedule/source/date provenance, including explicit
  UTC-vs-Eastern boundary diagnostics (the first target is the MLS date bug);
* collector probes and slate decisions are recorded to lightweight audit tables;
* a cached, copy-ready validation report can be pasted directly into ChatGPT.

The v6 canonical SQLite database remains the shadow database of record.
Production authority remains false.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs

from . import canonical_shadow_v600 as shadow
from . import canonical_certification_v610 as v610
from . import canonical_certification_v611 as v611

VERSION = "6.1.2-validation-diagnostics-1"
ENABLED = str(os.environ.get("SBB_CANONICAL_VALIDATION_ENABLED") or "1").strip().lower() not in {"0", "false", "no", "off"}
REFRESH_SECONDS = max(30, int(os.environ.get("SBB_CANONICAL_VALIDATION_REFRESH_SECONDS") or 60))
PERSIST_SECONDS = max(300, int(os.environ.get("SBB_CANONICAL_VALIDATION_PERSIST_SECONDS") or 900))
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_DIAG = None


def _now():
    return time.time()


def _clean(value):
    return str(value or "").strip()


def _loads(value, fallback=None):
    try:
        return json.loads(value) if value else (fallback if fallback is not None else {})
    except Exception:
        return fallback if fallback is not None else {}


def _epoch(value):
    try:
        return float(value)
    except Exception:
        return 0.0


def _iso(ts):
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return ""


def _parse_dt(value):
    raw = _clean(value)
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _norm_team(value):
    return re.sub(r"[^a-z0-9]+", "", _clean(value).lower())


def _safe_row(row):
    return dict(row) if row is not None else {}


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _walk_date_fields(value, prefix="", depth=0, out=None):
    out = out if out is not None else []
    if depth > 4 or len(out) >= 80:
        return out
    if isinstance(value, dict):
        for key, child in value.items():
            p = f"{prefix}.{key}" if prefix else str(key)
            k = str(key).lower()
            if any(token in k for token in ("date", "time", "kickoff", "scheduled", "start", "slate")) and isinstance(child, (str, int, float)):
                out.append({"field": p, "value": str(child)})
            _walk_date_fields(child, p, depth + 1, out)
    elif isinstance(value, list):
        for idx, child in enumerate(value[:12]):
            _walk_date_fields(child, f"{prefix}[{idx}]", depth + 1, out)
    return out


class ValidationDiagnostics:
    def __init__(self, server, engine):
        self.server = server
        self.engine = engine
        self.store = engine.store
        self.lock = threading.RLock()
        self.cache = {"ready": False, "builtAt": 0.0, "buildSeconds": 0.0, "snapshot": None, "report": ""}
        self.probes = deque(maxlen=500)
        self.decisions = deque(maxlen=1000)
        self.last_error = ""
        self.last_persist_at = 0.0
        self.last_persist_hash = ""
        self._init_tables()

    def _connect(self, readonly=False):
        return self.store._connect(readonly=readonly)

    def _init_tables(self):
        try:
            with self.store._lock, shadow.closing(self._connect()) as conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS canonical_validation_probe(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observed_at REAL NOT NULL,
                    league TEXT,
                    source TEXT,
                    source_class TEXT,
                    operation TEXT,
                    success INTEGER NOT NULL,
                    duration_ms REAL,
                    result_count INTEGER,
                    error TEXT,
                    details_json TEXT
                )""")
                conn.execute("""CREATE TABLE IF NOT EXISTS canonical_validation_snapshot(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at REAL NOT NULL,
                    release_version TEXT,
                    snapshot_hash TEXT,
                    summary_json TEXT,
                    diagnostics_json TEXT
                )""")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_canonical_validation_probe_time ON canonical_validation_probe(observed_at DESC)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_canonical_validation_snapshot_time ON canonical_validation_snapshot(captured_at DESC)")
                conn.commit()
        except Exception as exc:
            self.last_error = f"diagnostic table init: {type(exc).__name__}: {exc}"

    def _tables(self, conn):
        try:
            return {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        except Exception:
            return set()

    def _rows(self, sql, args=()):
        try:
            with self.store._lock, shadow.closing(self._connect(readonly=True)) as conn:
                return [dict(r) for r in conn.execute(sql, args).fetchall()]
        except Exception:
            return []

    def record_probe(self, league, source, source_class, operation, success, duration_ms, result_count=0, error="", details=None):
        row = {
            "observedAt": _now(), "league": _clean(league), "source": _clean(source),
            "sourceClass": _clean(source_class).upper(), "operation": _clean(operation),
            "success": bool(success), "durationMs": round(float(duration_ms or 0), 2),
            "resultCount": int(result_count or 0), "error": _clean(error), "details": _jsonable(details or {}),
        }
        with self.lock:
            self.probes.appendleft(row)
        try:
            with self.store._lock, shadow.closing(self._connect()) as conn:
                conn.execute(
                    """INSERT INTO canonical_validation_probe(observed_at,league,source,source_class,operation,success,duration_ms,result_count,error,details_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (row["observedAt"], row["league"], row["source"], row["sourceClass"], row["operation"], int(row["success"]), row["durationMs"], row["resultCount"], row["error"], json.dumps(row["details"], separators=(",", ":"))),
                )
                conn.execute("DELETE FROM canonical_validation_probe WHERE id NOT IN (SELECT id FROM canonical_validation_probe ORDER BY id DESC LIMIT 2000)")
                conn.commit()
        except Exception:
            pass

    def record_decision(self, day, league, slate, changed):
        if not changed:
            return
        row = {
            "observedAt": _now(), "date": day, "league": league,
            "status": _clean((slate or {}).get("certification_status")),
            "reason": _clean((slate or {}).get("certification_reason")),
            "version": int((slate or {}).get("version") or 0),
        }
        with self.lock:
            self.decisions.appendleft(row)

    def _bulk(self, day_from, day_to):
        out = {"slates": [], "comparisons": [], "coverage": [], "events": [], "observations": [], "scores": [], "mappings": [], "tables": []}
        try:
            with self.store._lock, shadow.closing(self._connect(readonly=True)) as conn:
                tables = self._tables(conn)
                out["tables"] = sorted(tables)
                if "daily_slate" in tables:
                    out["slates"] = [dict(r) for r in conn.execute("SELECT * FROM daily_slate WHERE slate_date BETWEEN ? AND ? ORDER BY slate_date,competition_id,version DESC", (day_from, day_to)).fetchall()]
                if "slate_comparison" in tables:
                    out["comparisons"] = [dict(r) for r in conn.execute("SELECT * FROM slate_comparison WHERE slate_date BETWEEN ? AND ? ORDER BY slate_date,competition_id,last_observed_at DESC,id DESC", (day_from, day_to)).fetchall()]
                if "source_coverage" in tables:
                    out["coverage"] = [dict(r) for r in conn.execute("SELECT * FROM source_coverage WHERE slate_date BETWEEN ? AND ? ORDER BY slate_date,competition_id,source,last_observed_at DESC,id DESC", (day_from, day_to)).fetchall()]
                if "canonical_event" in tables:
                    out["events"] = [dict(r) for r in conn.execute("SELECT * FROM canonical_event WHERE slate_date BETWEEN ? AND ? ORDER BY slate_date,competition_id,scheduled_at,canonical_event_id", (day_from, day_to)).fetchall()]
                if "schedule_observation" in tables and "canonical_event" in tables:
                    out["observations"] = [dict(r) for r in conn.execute("""SELECT so.*,ce.slate_date AS _slate_date,ce.competition_id AS _competition_id
                        FROM schedule_observation so JOIN canonical_event ce ON ce.canonical_event_id=so.canonical_event_id
                        WHERE ce.slate_date BETWEEN ? AND ? ORDER BY so.canonical_event_id,so.last_observed_at DESC""", (day_from, day_to)).fetchall()]
                if "score_observation" in tables and "canonical_event" in tables:
                    out["scores"] = [dict(r) for r in conn.execute("""SELECT so.*,ce.slate_date AS _slate_date,ce.competition_id AS _competition_id
                        FROM score_observation so JOIN canonical_event ce ON ce.canonical_event_id=so.canonical_event_id
                        WHERE ce.slate_date BETWEEN ? AND ? ORDER BY so.canonical_event_id""", (day_from, day_to)).fetchall()]
                for table in ("provider_event_mapping", "provider_event_mappings", "canonical_provider_mapping"):
                    if table in tables:
                        out["mappings"] = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
                        break
        except Exception as exc:
            self.last_error = f"bulk diagnostic read: {type(exc).__name__}: {exc}"
        return out

    def _event_provenance(self, event, obs_rows, adjacent_lookup):
        raw = _loads(event.get("raw_json"), {})
        scheduled = _clean(event.get("scheduled_at") or raw.get("scheduledAt") or raw.get("date"))
        dt = _parse_dt(scheduled)
        utc_date = dt.astimezone(timezone.utc).date().isoformat() if dt else ""
        et_date = dt.astimezone(shadow.ET).date().isoformat() if dt else ""
        slate_date = _clean(event.get("slate_date"))
        date_fields = _walk_date_fields(raw)
        flags = []
        if slate_date and utc_date and et_date and slate_date == utc_date and slate_date != et_date:
            flags.append("LIKELY_UTC_DAY_LEAK")
        if slate_date and et_date and slate_date != et_date:
            flags.append("SLATE_DATE_DIFFERS_FROM_ET_START_DATE")
        canonical_raw_day = _clean(raw.get("__sbbDate") or raw.get("canonicalSlateDate") or raw.get("match_date"))[:10]
        if canonical_raw_day and slate_date and canonical_raw_day != slate_date:
            flags.append("RAW_COMPETITION_DATE_DIFFERS_FROM_STORED_SLATE_DATE")
        key = (_norm_team(event.get("away_name")), _norm_team(event.get("home_name")))
        adjacent = []
        for d, rows in adjacent_lookup.items():
            if d == slate_date:
                continue
            for other in rows:
                if (_norm_team(other.get("away_name")), _norm_team(other.get("home_name"))) == key:
                    if scheduled and _clean(other.get("scheduled_at")) == scheduled:
                        adjacent.append({"date": d, "canonicalEventId": other.get("canonical_event_id"), "scheduledAt": other.get("scheduled_at")})
        if adjacent:
            flags.append("SAME_MATCHUP_SAME_TIME_EXISTS_ON_ADJACENT_SLATE")
        obs = []
        for row in obs_rows[:20]:
            obs.append({
                "source": row.get("source"), "sourceClass": row.get("source_class"),
                "lastObservedAt": row.get("last_observed_at"), "scheduledAt": row.get("scheduled_at"),
                "status": row.get("status"), "raw": _loads(row.get("raw_json"), {}),
            })
        return {
            "slateDate": slate_date, "scheduledAt": scheduled, "scheduledUtcDate": utc_date,
            "scheduledEasternDate": et_date, "rawCompetitionDate": canonical_raw_day,
            "dateFields": date_fields, "flags": flags, "adjacentMatches": adjacent,
            "scheduleObservations": obs,
        }

    def _adapter_status(self, league, side, latest_cov, memory_health, today):
        source = v610.SOURCE_DEFS.get(league, {}).get("authoritative") if side == "authoritative" else v610.INDEPENDENT_SOURCE
        cls = "AUTHORITATIVE" if side == "authoritative" else "INDEPENDENT"
        persisted = latest_cov.get((today, league, source)) or {}
        mem = ((memory_health.get(league) or {}).get(side) or {}).get("health") or {}
        p_ts = float(persisted.get("last_observed_at") or 0)
        m_ts = float(mem.get("checkedAt") or 0)
        chosen = "memory" if m_ts >= p_ts and m_ts else "persisted" if p_ts else "none"
        data = mem if chosen == "memory" else persisted
        success = None if chosen == "none" else bool(data.get("success"))
        ts = m_ts if chosen == "memory" else p_ts
        age = max(0.0, _now() - ts) if ts else None
        stale = bool(ts and age is not None and age > v610.FRESH_SECONDS)
        if chosen == "none": state = "WAITING"
        elif stale: state = "STALE_OK" if success else "STALE_FAIL"
        elif chosen == "memory": state = "LIVE_OK" if success else "LIVE_FAIL"
        else: state = "PERSISTED_OK" if success else "PERSISTED_FAIL"
        return {
            "source": source, "sourceClass": cls, "state": state, "success": success,
            "provenance": chosen, "checkedAt": ts, "checkedAtIso": _iso(ts) if ts else "",
            "ageSeconds": round(age, 1) if age is not None else None, "stale": stale,
            "resultCount": int(data.get("eventCount") or data.get("result_count") or 0),
            "error": _clean(data.get("error")), "endpoint": _clean(data.get("endpoint")),
            "persisted": _jsonable(persisted), "memory": _jsonable(mem),
        }

    def _decision(self, day, league, slate, comparison, cov_by_source, events, obs_by_event, event_by_id, adjacent_lookup):
        comparison = comparison or {}
        details = _loads(comparison.get("details_json"), comparison.get("details") or {})
        production_ids = list(details.get("legacyOnly") or [])
        shadow_ids = list(details.get("canonicalOnly") or [])
        auth_source = v610.SOURCE_DEFS.get(league, {}).get("authoritative")
        ind_source = v610.INDEPENDENT_SOURCE
        auth = cov_by_source.get((day, league, auth_source)) or {}
        indep = cov_by_source.get((day, league, ind_source)) or {}
        today = datetime.now(shadow.ET).date().isoformat()

        def usable(row):
            if not row or not int(row.get("success") or 0):
                return False
            if day >= today and _now() - float(row.get("last_observed_at") or 0) > v610.FRESH_SECONDS:
                return False
            return True

        auth_ok, indep_ok = usable(auth), usable(indep)
        auth_count = int(auth.get("result_count") or 0) if auth_ok else None
        indep_count = int(indep.get("result_count") or 0) if indep_ok else None
        source_count_conflict = bool(auth_ok and indep_ok and auth_count != indep_count)
        included = [e for e in events if _clean(e.get("inclusion_state")) == "INCLUDED"]
        evidence_gaps = []
        for event in included:
            classes = set()
            for ob in obs_by_event.get(event.get("canonical_event_id"), []):
                ts = float(ob.get("last_observed_at") or 0)
                if day >= today and ts and _now() - ts > v610.FRESH_SECONDS:
                    continue
                classes.add(_clean(ob.get("source_class")).upper())
            missing = sorted({"AUTHORITATIVE", "INDEPENDENT"} - classes)
            if missing:
                evidence_gaps.append({"canonicalEventId": event.get("canonical_event_id"), "missing": missing})
        unknown = int((slate or {}).get("unknown_count") or 0)
        unresolved = int((slate or {}).get("unresolved_count") or 0)
        reasons = []
        contradiction = False
        if production_ids:
            reasons.append(f"KNOWN_EVENT_UNIVERSE_CONFLICT:{len(production_ids)}_PRODUCTION_ONLY"); contradiction = True
        if source_count_conflict:
            reasons.append(f"SOURCE_COUNT_CONFLICT:AUTHORITATIVE={auth_count}:INDEPENDENT={indep_count}"); contradiction = True
        if evidence_gaps and auth_ok and indep_ok:
            reasons.append(f"CROSS_SOURCE_EVENT_CONFLICT:{len(evidence_gaps)}_EVENTS"); contradiction = True
        if unresolved:
            reasons.append(f"UNRESOLVED_IDENTITIES:{unresolved}"); contradiction = True
        if unknown:
            reasons.append(f"UNKNOWN_INCLUSION:{unknown}"); contradiction = True
        if contradiction:
            effective = "RECONCILING"
        elif auth_ok and indep_ok and not evidence_gaps:
            effective = "CERTIFIED"
        else:
            effective = "SHADOW_BASELINE"
            if not auth_ok: reasons.append("AUTHORITATIVE_COVERAGE_INCOMPLETE")
            if not indep_ok: reasons.append("INDEPENDENT_COVERAGE_INCOMPLETE")
            if evidence_gaps: reasons.append(f"EVENT_EVIDENCE_INCOMPLETE:{len(evidence_gaps)}")
        cutover = effective == "CERTIFIED" and not production_ids and not unresolved and not unknown and not evidence_gaps and not source_count_conflict
        persisted = _clean((slate or {}).get("certification_status") or "NO_MANIFEST")
        consistency = persisted != effective
        if consistency:
            reasons.append(f"STATE_CONSISTENCY_VIOLATION:PERSISTED={persisted}:EFFECTIVE={effective}")

        prod_events, shadow_events = [], []
        for event_id in production_ids:
            e = event_by_id.get(event_id, {"canonical_event_id": event_id, "competition_id": league, "slate_date": day})
            item = dict(e)
            item["dateProvenance"] = self._event_provenance(e, obs_by_event.get(event_id, []), adjacent_lookup)
            prod_events.append(_jsonable(item))
        for event_id in shadow_ids:
            e = event_by_id.get(event_id, {"canonical_event_id": event_id, "competition_id": league, "slate_date": day})
            item = dict(e)
            item["dateProvenance"] = self._event_provenance(e, obs_by_event.get(event_id, []), adjacent_lookup)
            shadow_events.append(_jsonable(item))

        date_warnings = sum(bool(x.get("dateProvenance", {}).get("flags")) for x in prod_events + shadow_events)
        steps = [
            {"code":"MANIFEST_PRESENT","status":"PASS" if slate else "FAIL","detail":f"version {(slate or {}).get('version','—')}" if slate else "No persisted daily_slate row"},
            {"code":"AUTHORITATIVE_COVERAGE","status":"PASS" if auth_ok else "FAIL","detail":f"{auth_source}: {auth_count if auth_count is not None else 'unproven'} events"},
            {"code":"INDEPENDENT_COVERAGE","status":"PASS" if indep_ok else "FAIL","detail":f"{ind_source}: {indep_count if indep_count is not None else 'unproven'} events"},
            {"code":"SOURCE_COUNT_AGREEMENT","status":"FAIL" if source_count_conflict else "PASS" if auth_ok and indep_ok else "WARN","detail":f"authoritative={auth_count} independent={indep_count}"},
            {"code":"EVENT_EVIDENCE_COMPLETE","status":"FAIL" if evidence_gaps else "PASS" if auth_ok and indep_ok else "WARN","detail":f"{len(evidence_gaps)} included event evidence gap(s)"},
            {"code":"PRODUCTION_CONTRADICTIONS","status":"FAIL" if production_ids else "PASS","detail":f"{len(production_ids)} production-only event(s)"},
            {"code":"IDENTITY_RESOLUTION","status":"FAIL" if unresolved else "PASS","detail":f"{unresolved} unresolved identity row(s)"},
            {"code":"INCLUSION_POLICY","status":"FAIL" if unknown else "PASS","detail":f"{unknown} UNKNOWN inclusion row(s)"},
            {"code":"DATE_PROVENANCE","status":"WARN" if date_warnings else "PASS","detail":f"{date_warnings} discrepancy event(s) with date-boundary/provenance flags"},
            {"code":"EFFECTIVE_CERTIFICATION","status":"PASS" if effective=="CERTIFIED" else "FAIL" if effective=="RECONCILING" else "WARN","detail":effective},
            {"code":"CUTOVER_READY","status":"PASS" if cutover else "FAIL","detail":"READY" if cutover else "BLOCKED"},
        ]
        mls_diag = None
        if league == "MLS":
            likely = [x for x in prod_events if "LIKELY_UTC_DAY_LEAK" in x.get("dateProvenance", {}).get("flags", [])]
            prev_day = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
            mls_diag = {
                "productionOnly": len(prod_events), "likelyUtcDayLeaks": len(likely),
                "previousEasternDate": prev_day, "suspectedCause": "PROBABLE_PRODUCTION_UTC_DATE_BOUNDARY" if likely else "UNRESOLVED",
                "events": prod_events,
            }
        return {
            "league": league, "date": day, "persistedStatus": persisted, "effectiveStatus": effective,
            "persistedReason": _clean((slate or {}).get("certification_reason")),
            "effectiveReason": " | ".join(reasons) if reasons else "CERTIFICATION_EVIDENCE_COMPLETE",
            "stateConsistencyViolation": consistency, "cutoverReady": cutover,
            "universe": int((slate or {}).get("universe_count") or 0),
            "included": int((slate or {}).get("included_count") or 0),
            "excluded": int((slate or {}).get("excluded_count") or 0),
            "unknown": unknown, "unresolved": unresolved,
            "shadow": int(comparison.get("canonical_count") or 0), "production": int(comparison.get("legacy_count") or 0),
            "matched": int(comparison.get("matched_count") or 0), "shadowOnly": int(comparison.get("canonical_only_count") or len(shadow_ids)),
            "productionOnly": int(comparison.get("legacy_only_count") or len(production_ids)),
            "sourceCounts": {"authoritative": auth_count, "independent": indep_count},
            "sourceCoverage": {"authoritative": _jsonable(auth), "independent": _jsonable(indep)},
            "sourceCountConflict": source_count_conflict, "evidenceGaps": evidence_gaps,
            "productionOnlyEvents": prod_events, "shadowOnlyEvents": shadow_events,
            "decisionTrace": steps, "mlsDiagnosis": mls_diag,
        }

    def _enforce_local_consistency(self, day_from, day_to):
        changed = 0
        cursor = date.fromisoformat(day_from)
        end = date.fromisoformat(day_to)
        while cursor <= end:
            day = cursor.isoformat()
            for league in shadow.SUPPORTED_LEAGUES:
                try:
                    slates = self.store.latest_slates(day, league)
                    slate = slates[0] if slates else None
                    if not slate:
                        continue
                    hard = v611._hardening_state(self.store, day, league, slate)
                    if hard.get("reasons") and _clean(slate.get("certification_status")) != "RECONCILING":
                        reason = " | ".join(hard["reasons"])
                        conflicts = len(hard.get("productionOnlyIds") or []) + int(bool(hard.get("sourceCountConflict"))) + len(hard.get("evidenceGaps") or [])
                        _new, did = v611._clone_slate_status(self.store, slate, "RECONCILING", reason, conflicts)
                        changed += int(bool(did))
                except Exception:
                    continue
            cursor += timedelta(days=1)
        if changed:
            try:
                v611._rebuild_readiness_cache(self.engine)
            except Exception:
                pass
        return changed

    def build_snapshot(self):
        started = _now()
        today_obj = datetime.now(shadow.ET).date()
        day_from = (today_obj - timedelta(days=shadow.LOOKBACK_DAYS)).isoformat()
        day_to = (today_obj + timedelta(days=shadow.LOOKAHEAD_DAYS)).isoformat()
        today = today_obj.isoformat()
        self._enforce_local_consistency(day_from, day_to)
        bulk = self._bulk(day_from, day_to)

        latest_slates = {}
        for row in bulk["slates"]:
            latest_slates.setdefault((row.get("slate_date"), row.get("competition_id")), row)
        latest_comp = {}
        for row in bulk["comparisons"]:
            latest_comp.setdefault((row.get("slate_date"), row.get("competition_id")), row)
        latest_cov = {}
        for row in bulk["coverage"]:
            latest_cov.setdefault((row.get("slate_date"), row.get("competition_id"), row.get("source")), row)
        events_by_key = defaultdict(list); event_by_id = {}; events_by_day = defaultdict(list)
        for row in bulk["events"]:
            key=(row.get("slate_date"), row.get("competition_id")); events_by_key[key].append(row); event_by_id[row.get("canonical_event_id")]=row; events_by_day[row.get("slate_date")].append(row)
        obs_by_event = defaultdict(list)
        for row in bulk["observations"]:
            obs_by_event[row.get("canonical_event_id")].append(row)
        scores_by_event = defaultdict(list)
        for row in bulk["scores"]:
            scores_by_event[row.get("canonical_event_id")].append(row)
        mappings_by_event = defaultdict(list)
        for row in bulk["mappings"]:
            eid=row.get("canonical_event_id") or row.get("event_id") or row.get("sbb_event_id")
            if eid: mappings_by_event[eid].append(row)

        # Compact event inventory is exported for every event in the validation
        # horizon.  Raw schedule evidence remains attached to discrepancy events;
        # the full inventory keeps source/evidence/mapping anatomy without making
        # the browser payload unbounded.
        event_inventory = defaultdict(list)
        for event in bulk["events"]:
            eid=event.get("canonical_event_id"); obs=obs_by_event.get(eid,[])
            event_inventory[event.get("slate_date")].append({
                "canonicalEventId":eid,"league":event.get("competition_id"),
                "away":event.get("away_name"),"home":event.get("home_name"),
                "scheduledAt":event.get("scheduled_at"),"status":event.get("status"),
                "inclusionState":event.get("inclusion_state"),"identityState":event.get("identity_state"),
                "sources":sorted({str(x.get("source") or "") for x in obs if x.get("source")}),
                "sourceClasses":sorted({str(x.get("source_class") or "") for x in obs if x.get("source_class")}),
                "providerMappings":_jsonable(mappings_by_event.get(eid,[])[:20]),
                "scoreObservations":_jsonable(scores_by_event.get(eid,[])[:5]),
            })

        memory = {}
        try:
            memory = (self.engine.__sbbV611OriginalHealth().get("leagues") if hasattr(self.engine,"__sbbV611OriginalHealth") else self.engine.health().get("leagues")) or {}
        except Exception:
            memory = {}
        adapters = {}
        for league in shadow.SUPPORTED_LEAGUES:
            adapters[league] = {
                "authoritative": self._adapter_status(league, "authoritative", latest_cov, memory, today),
                "independent": self._adapter_status(league, "independent", latest_cov, memory, today),
            }

        days = {}; discrepancies=[]; consistency=[]; mls_findings=[]
        cursor=date.fromisoformat(day_from); end=date.fromisoformat(day_to)
        summary = {"leagueDays":0,"certified":0,"reconciling":0,"baseline":0,"cutoverReady":0,"productionOnly":0,"shadowOnly":0,"stateConsistencyViolations":0,"adapterFailures":0,"adapterWaiting":0,"dateProvenanceWarnings":0}
        for league, sides in adapters.items():
            for side in ("authoritative","independent"):
                state=sides[side]["state"]
                if "FAIL" in state: summary["adapterFailures"]+=1
                if state=="WAITING": summary["adapterWaiting"]+=1
        while cursor<=end:
            day=cursor.isoformat(); day_leagues={}; day_sum={"shadow":0,"production":0,"matched":0,"shadowOnly":0,"productionOnly":0,"certified":0,"reconciling":0,"baseline":0,"cutoverReady":0}
            adjacent={d:events_by_day.get(d,[]) for d in ((cursor-timedelta(days=1)).isoformat(),day,(cursor+timedelta(days=1)).isoformat())}
            for league in shadow.SUPPORTED_LEAGUES:
                decision=self._decision(day,league,latest_slates.get((day,league)),latest_comp.get((day,league)),latest_cov,events_by_key.get((day,league),[]),obs_by_event,event_by_id,adjacent)
                day_leagues[league]=decision; summary["leagueDays"]+=1
                state=decision["effectiveStatus"]
                if state=="CERTIFIED": summary["certified"]+=1; day_sum["certified"]+=1
                elif state=="RECONCILING": summary["reconciling"]+=1; day_sum["reconciling"]+=1
                else: summary["baseline"]+=1; day_sum["baseline"]+=1
                if decision["cutoverReady"]: summary["cutoverReady"]+=1; day_sum["cutoverReady"]+=1
                for key in ("shadow","production","matched","shadowOnly","productionOnly"): day_sum[key]+=int(decision[key]); summary[key if key in summary else key]=summary.get(key,0)+int(decision[key])
                if decision["stateConsistencyViolation"]: summary["stateConsistencyViolations"]+=1; consistency.append({"date":day,"league":league,"persisted":decision["persistedStatus"],"effective":decision["effectiveStatus"],"reason":decision["effectiveReason"]})
                for ev in decision["productionOnlyEvents"]:
                    discrepancies.append({"kind":"PRODUCTION_ONLY","date":day,"league":league,"event":ev})
                    summary["dateProvenanceWarnings"] += int(bool(ev.get("dateProvenance",{}).get("flags")))
                for ev in decision["shadowOnlyEvents"]:
                    discrepancies.append({"kind":"SHADOW_ONLY","date":day,"league":league,"event":ev})
                    summary["dateProvenanceWarnings"] += int(bool(ev.get("dateProvenance",{}).get("flags")))
                if decision.get("mlsDiagnosis") and (decision["mlsDiagnosis"].get("productionOnly") or decision["mlsDiagnosis"].get("likelyUtcDayLeaks")):
                    mls_findings.append({"date":day,**decision["mlsDiagnosis"]})
            days[day]={"summary":day_sum,"leagues":day_leagues}; cursor+=timedelta(days=1)

        db_stats={"tables":bulk["tables"],"canonicalEventsInWindow":len(bulk["events"]),"sourceCoverageRowsInWindow":len(bulk["coverage"]),"scheduleObservationsInWindow":len(bulk["observations"]),"scoreObservationsInWindow":len(bulk["scores"]),"providerMappingsRead":len(bulk["mappings"])}
        recent_probes=list(self.probes)[:100]
        if not recent_probes:
            recent_probes=self._rows("SELECT * FROM canonical_validation_probe ORDER BY observed_at DESC LIMIT 100")
        snapshot={
            "ok":True,"version":VERSION,"releaseVersion":"6.1.2","mode":"DIAGNOSTIC_SHADOW","productionAuthority":False,
            "capturedAt":_now(),"capturedAtIso":_iso(_now()),"capturedEastern":datetime.now(shadow.ET).isoformat(),
            "window":{"from":day_from,"to":day_to,"today":today},"summary":summary,"adapters":adapters,"days":days,
            "discrepancies":discrepancies,"stateConsistencyViolations":consistency,"mlsDiagnostics":mls_findings,
            "eventInventory":_jsonable(dict(event_inventory)),
            "database":db_stats,"probeHistory":_jsonable(recent_probes),"decisionHistory":list(self.decisions)[:100],
            "worker":{"certificationLastRunAt":getattr(self.engine,"last_run_at",0),"certificationLastError":getattr(self.engine,"last_error",""),"certificationLastStats":_jsonable(getattr(self.engine,"last_stats",{}))},
            "diagnosticHooks":{"collectorProbeLog":True,"decisionTrace":True,"dateProvenance":True,"persistedAdapterRehydration":True,"localConsistencyReconcile":True,"copyValidationConsole":True},
        }
        snapshot["summary"]["cutoverReadyPercent"] = round(100.0*summary["cutoverReady"]/summary["leagueDays"],2) if summary["leagueDays"] else 0.0
        report=self._report(snapshot)
        build_seconds=round(_now()-started,3)
        with self.lock:
            self.cache={"ready":True,"builtAt":_now(),"buildSeconds":build_seconds,"snapshot":snapshot,"report":report}
        self._persist_snapshot(snapshot)
        return snapshot

    def _persist_snapshot(self, snapshot):
        compact={"summary":snapshot.get("summary"),"stateConsistencyViolations":snapshot.get("stateConsistencyViolations"),"mlsDiagnostics":snapshot.get("mlsDiagnostics"),"window":snapshot.get("window")}
        digest=hashlib.sha256(json.dumps(compact,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
        if digest==self.last_persist_hash and _now()-self.last_persist_at<PERSIST_SECONDS:
            return
        try:
            with self.store._lock, shadow.closing(self._connect()) as conn:
                conn.execute("INSERT INTO canonical_validation_snapshot(captured_at,release_version,snapshot_hash,summary_json,diagnostics_json) VALUES(?,?,?,?,?)",(_now(),"6.1.2",digest,json.dumps(snapshot.get("summary"),separators=(",", ":")),json.dumps(compact,separators=(",", ":"))))
                conn.execute("DELETE FROM canonical_validation_snapshot WHERE id NOT IN (SELECT id FROM canonical_validation_snapshot ORDER BY id DESC LIMIT 100)")
                conn.commit()
            self.last_persist_at=_now(); self.last_persist_hash=digest
        except Exception:
            pass

    def _report(self,s):
        L=[]; add=L.append
        add("="*78); add("SPORTS BIG BOARD — CANONICAL SLATE VALIDATION DIAGNOSTIC"); add(f"Captured UTC: {s['capturedAtIso']}"); add(f"Captured ET:  {s['capturedEastern']}"); add(f"Release: {s['releaseVersion']} | Diagnostics: {s['version']}"); add(f"Window: {s['window']['from']} through {s['window']['to']} | Production authority: NO"); add("="*78)
        q=s["summary"]; add("\nVALIDATION SUMMARY");
        for k in ("leagueDays","certified","reconciling","baseline","cutoverReady","productionOnly","shadowOnly","stateConsistencyViolations","adapterFailures","adapterWaiting","dateProvenanceWarnings","cutoverReadyPercent"): add(f"{k}: {q.get(k)}")
        add("\nADAPTER STATUS")
        for lg,a in s["adapters"].items():
            for side in ("authoritative","independent"):
                x=a[side]; add(f"{lg} {side.upper()}: {x['state']} source={x['source']} count={x['resultCount']} age={x['ageSeconds']}s provenance={x['provenance']} error={x['error'] or '-'} endpoint={x['endpoint'] or '-'}")
        add("\n15-DAY LEAGUE/DATE DECISION MATRIX")
        for day,block in s["days"].items():
            add(f"\n## {day} summary={json.dumps(block['summary'],sort_keys=True)}")
            for lg,d in block["leagues"].items():
                add(f"{lg}: effective={d['effectiveStatus']} persisted={d['persistedStatus']} cutover={'READY' if d['cutoverReady'] else 'BLOCKED'} universe={d['universe']} included={d['included']} excluded={d['excluded']} shadow={d['shadow']} production={d['production']} matched={d['matched']} shadowOnly={d['shadowOnly']} productionOnly={d['productionOnly']} authCount={d['sourceCounts']['authoritative']} independentCount={d['sourceCounts']['independent']}")
                add(f"  reason: {d['effectiveReason']}")
                add("  trace: "+" | ".join(f"{x['code']}={x['status']}({x['detail']})" for x in d["decisionTrace"]))
        add("\nDISCREPANCY EVENTS WITH DATE/SOURCE PROVENANCE")
        if not s["discrepancies"]: add("None")
        for item in s["discrepancies"]:
            e=item["event"]; p=e.get("dateProvenance") or {}; add(f"{item['kind']} {item['date']} {item['league']} {e.get('away_name','TBD')} @ {e.get('home_name','TBD')} id={e.get('canonical_event_id')} scheduled={e.get('scheduled_at')} slateDate={p.get('slateDate')} utcDate={p.get('scheduledUtcDate')} easternDate={p.get('scheduledEasternDate')} rawCompetitionDate={p.get('rawCompetitionDate')} flags={','.join(p.get('flags') or []) or '-'}")
            for ob in p.get("scheduleObservations") or []: add(f"  observation source={ob.get('source')} class={ob.get('sourceClass')} last={ob.get('lastObservedAt')} scheduled={ob.get('scheduledAt')} status={ob.get('status')}")
        add("\nCANONICAL EVENT INVENTORY")
        for day,events in (s.get("eventInventory") or {}).items():
            add(f"## {day} events={len(events)}")
            for e in events:
                add(f"  {e.get('league')} {e.get('away')} @ {e.get('home')} id={e.get('canonicalEventId')} scheduled={e.get('scheduledAt')} status={e.get('status')} inclusion={e.get('inclusionState')} identity={e.get('identityState')} classes={','.join(e.get('sourceClasses') or [])} sources={','.join(e.get('sources') or [])}")
        add("\nMLS FOCUSED DIAGNOSTICS")
        add(json.dumps(s.get("mlsDiagnostics") or [],indent=2,sort_keys=True))
        add("\nSTATE CONSISTENCY VIOLATIONS"); add(json.dumps(s.get("stateConsistencyViolations") or [],indent=2,sort_keys=True))
        add("\nRECENT COLLECTOR PROBES"); add(json.dumps(s.get("probeHistory") or [],indent=2,sort_keys=True))
        add("\nWORKER / DATABASE"); add(json.dumps({"worker":s.get("worker"),"database":s.get("database"),"hooks":s.get("diagnosticHooks")},indent=2,sort_keys=True))
        add("\nRAW VALIDATION SNAPSHOT JSON (REPORT BODY OMITTED)"); add(json.dumps(s,indent=2,sort_keys=True))
        return "\n".join(L)

    def health(self):
        with self.lock:
            c=self.cache
            return {"ok":True,"version":VERSION,"productionAuthority":False,"ready":bool(c.get("ready")),"builtAt":c.get("builtAt",0),"ageSeconds":round(max(0,_now()-float(c.get("builtAt") or 0)),2) if c.get("builtAt") else None,"buildSeconds":c.get("buildSeconds",0),"lastError":self.last_error,"hooks":{"collectorProbeLog":True,"decisionTrace":True,"dateProvenance":True,"persistedAdapterRehydration":True,"copyValidationConsole":True}}

    def snapshot(self):
        with self.lock:
            return self.cache.get("snapshot")

    def report(self):
        with self.lock:
            return self.cache.get("report") or ""

    def worker(self):
        time.sleep(0.5)
        while True:
            try:
                self.build_snapshot(); self.last_error=""
            except Exception as exc:
                self.last_error=f"{type(exc).__name__}: {exc}"
            time.sleep(REFRESH_SECONDS)


def _install_probe_hooks(diag):
    cls=v610.CertificationEngine
    if getattr(cls,"__sbbV612ProbeHooks",False): return
    cls.__sbbV612ProbeHooks=True
    if hasattr(cls,"_collect_authoritative"):
        original=cls._collect_authoritative
        def collect_authoritative(self,league,day_from,day_to):
            started=_now(); source=v610.SOURCE_DEFS.get(league,{}).get("authoritative","")
            try:
                count=original(self,league,day_from,day_to)
                h=(getattr(self,"source_health",{}) or {}).get(f"{league}:{source}") or {}
                success=bool(h.get("success", True)); error=_clean(h.get("error")); count=int(h.get("eventCount") or count or 0)
                return count
            except Exception as exc:
                count=0; success=False; error=f"{type(exc).__name__}: {exc}"; raise
            finally:
                if _DIAG: _DIAG.record_probe(league,source,"AUTHORITATIVE","collect",success,(_now()-started)*1000,count,error,{"dayFrom":day_from,"dayTo":day_to,"health":_jsonable((getattr(self,"source_health",{}) or {}).get(f"{league}:{source}") or {})})
        cls._collect_authoritative=collect_authoritative
    if hasattr(cls,"_collect_espn_independent"):
        original_i=cls._collect_espn_independent
        def collect_independent(self,league,day_from,day_to):
            started=_now(); source=v610.INDEPENDENT_SOURCE
            try:
                count=original_i(self,league,day_from,day_to)
                h=(getattr(self,"source_health",{}) or {}).get(f"{league}:{source}") or {}
                success=bool(h.get("success", True)); error=_clean(h.get("error")); count=int(h.get("eventCount") or count or 0)
                return count
            except Exception as exc:
                count=0; success=False; error=f"{type(exc).__name__}: {exc}"; raise
            finally:
                if _DIAG: _DIAG.record_probe(league,source,"INDEPENDENT","collect",success,(_now()-started)*1000,count,error,{"dayFrom":day_from,"dayTo":day_to,"health":_jsonable((getattr(self,"source_health",{}) or {}).get(f"{league}:{source}") or {})})
        cls._collect_espn_independent=collect_independent
    if hasattr(cls,"run_horizon"):
        original_run=cls.run_horizon
        def run_horizon(self):
            started=_now()
            try:
                result=original_run(self); success=True; error=""; return result
            except Exception as exc:
                success=False; error=f"{type(exc).__name__}: {exc}"; raise
            finally:
                if _DIAG:
                    _DIAG.record_probe("ALL","CERTIFICATION_ENGINE","WORKER","run_horizon",success,(_now()-started)*1000,0,error,{})
                    try: _DIAG.build_snapshot()
                    except Exception: pass
        cls.run_horizon=run_horizon

    store_cls=shadow.CanonicalShadowStore
    if not getattr(store_cls,"__sbbV612DecisionHook",False):
        store_cls.__sbbV612DecisionHook=True
        original_compile=store_cls.compile_slate
        def compile_slate(self,slate_date,league,*args,**kwargs):
            slate,changed=original_compile(self,slate_date,league,*args,**kwargs)
            if _DIAG: _DIAG.record_decision(slate_date,league,slate,changed)
            return slate,changed
        store_cls.compile_slate=compile_slate


def _install_into_server():
    global _DIAG
    deadline=_now()+120; server=None; engine=None
    while _now()<deadline:
        server=sys.modules.get("__main__"); engine=v611.engine()
        if server and engine and hasattr(server,"Handler") and hasattr(server,"send_json"): break
        time.sleep(0.25)
    if not server or not engine: return
    _DIAG=ValidationDiagnostics(server,engine)
    _install_probe_hooks(_DIAG)
    try:
        server.SBB_BACKEND_WIRING.setdefault("canonicalSlate",{}).update({"validationDiagnosticsVersion":VERSION,"copyValidationConsole":True,"productionAuthority":False})
    except Exception: pass
    Handler=server.Handler
    if not getattr(Handler,"__sbbCanonicalValidationV612",False):
        old_get=Handler.do_GET
        def do_GET(self):
            parsed=shadow.urlparse(self.path); qs=parse_qs(parsed.query)
            if parsed.path=="/api/canonical/validation/health":
                return server.send_json(self,_DIAG.health(),200,{"X-SBB-Canonical-Validation":"DIAGNOSTIC-SHADOW"})
            if parsed.path in {"/api/canonical/validation/snapshot","/api/canonical/validation/console"}:
                snap=_DIAG.snapshot()
                return server.send_json(self,snap or {"ok":True,"version":VERSION,"ready":False,"productionAuthority":False},200,{"X-SBB-Canonical-Validation":"DIAGNOSTIC-SHADOW"})
            if parsed.path=="/api/canonical/validation/copy":
                report=_DIAG.report()
                return server.send_json(self,{"ok":True,"version":VERSION,"ready":bool(report),"productionAuthority":False,"bytes":len(report.encode("utf-8")),"report":report},200,{"X-SBB-Canonical-Validation":"DIAGNOSTIC-SHADOW"})
            if parsed.path=="/api/canonical/validation/league":
                day=shadow._day((qs.get("date") or [""])[-1]) or datetime.now(shadow.ET).date().isoformat(); league=_clean((qs.get("league") or [""])[-1]).upper(); snap=_DIAG.snapshot() or {}; row=(((snap.get("days") or {}).get(day) or {}).get("leagues") or {}).get(league)
                return server.send_json(self,{"ok":True,"version":VERSION,"date":day,"league":league,"diagnostics":row,"productionAuthority":False},200,{"X-SBB-Canonical-Validation":"DIAGNOSTIC-SHADOW"})
            if parsed.path=="/api/canonical/validation/mls":
                snap=_DIAG.snapshot() or {}; return server.send_json(self,{"ok":True,"version":VERSION,"productionAuthority":False,"mlsDiagnostics":snap.get("mlsDiagnostics") or []},200,{"X-SBB-Canonical-Validation":"DIAGNOSTIC-SHADOW"})
            if parsed.path=="/api/canonical/validation/history":
                rows=_DIAG._rows("SELECT * FROM canonical_validation_snapshot ORDER BY captured_at DESC LIMIT 50"); return server.send_json(self,{"ok":True,"version":VERSION,"rows":rows,"productionAuthority":False},200,{"X-SBB-Canonical-Validation":"DIAGNOSTIC-SHADOW"})
            return old_get(self)
        Handler.do_GET=do_GET; Handler.__sbbCanonicalValidationV612=True
    threading.Thread(target=_DIAG.worker,daemon=True,name="sbb-canonical-validation-v612").start()


def engine(): return _DIAG


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED or not ENABLED: return
        _INSTALLED=True
    threading.Thread(target=_install_into_server,daemon=True,name="sbb-canonical-validation-install-v612").start()

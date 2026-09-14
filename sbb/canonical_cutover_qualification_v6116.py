"""Sports Big Board v6.1.16 canonical cutover qualification.

This layer is intentionally downstream of canonical certification.  It does not
relax any certification rule.  It implements the three gates required before
canonical Day Slate authority can be enabled:

1. classify every SHADOW_ONLY event against the already-established canonical
   inclusion/identity/source-evidence policy;
2. persist one result per completed full certification horizon and require
   consecutive clean cycles;
3. expose a reversible, default-OFF Day State inventory authority flag.

When authority is enabled, only the Day State *event inventory/date/identity*
projection is replaced. Existing legacy score/status rows are preserved whenever
provider identity can bind them to the canonical event, and the normal Day State
media-plan, ticker, Game Center, score, and presentation code continues to run.
Any qualification or projection failure falls closed to the legacy inventory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import defaultdict
from contextlib import closing
from datetime import datetime

from . import canonical_shadow_v600 as shadow
from . import canonical_validation_v612 as validation
from . import day_state

VERSION = "6.1.16-canonical-cutover-qualification-1"
FLAG_ENV = "SBB_CANONICAL_DAY_SLATE_AUTHORITY"
REQUIRED_CYCLES = max(1, int(os.environ.get("SBB_CANONICAL_CUTOVER_CLEAN_CYCLES") or 3))
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_MANAGER = None
_ORIGINAL_MERGE = day_state._merge_future_catalog_rows


def _clean(value):
    return str(value or "").strip()


def _truthy(value):
    return _clean(value).lower() in {"1", "true", "yes", "on", "canonical"}


def _norm(value):
    return re.sub(r"[^a-z0-9]+", "", _clean(value).lower())


def _loads(value, fallback=None):
    try:
        return json.loads(value) if value else (fallback if fallback is not None else {})
    except Exception:
        return fallback if fallback is not None else {}


def _event_ids(event):
    event = event or {}
    out = set()
    for key in (
        "canonicalEventId", "__sbbCanonicalEventId", "scoreEventId", "matchId",
        "espnEventId", "gamePk", "eventId", "id",
    ):
        value = event.get(key)
        if value not in (None, ""):
            out.add(str(value))
    aliases = event.get("providerEventAliases") or []
    if isinstance(aliases, (list, tuple, set)):
        out.update(str(x) for x in aliases if x not in (None, ""))
    return out


def _team_name(event, side):
    value = (event or {}).get(side)
    if isinstance(value, dict):
        return _clean(value.get("displayName") or value.get("name") or value.get("shortDisplayName"))
    return _clean(value)


def _scheduled(event):
    event = event or {}
    return _clean(event.get("scheduledAt") or event.get("date") or event.get("startTime"))


def _epoch(value):
    return shadow._epoch(value)


def _same_matchup_time(canonical_row, legacy_event, tolerance=20 * 60):
    if _norm(canonical_row.get("away_name")) != _norm(_team_name(legacy_event, "away")):
        return False
    if _norm(canonical_row.get("home_name")) != _norm(_team_name(legacy_event, "home")):
        return False
    a = _epoch(canonical_row.get("scheduled_at"))
    b = _epoch(_scheduled(legacy_event))
    return a is not None and b is not None and abs(a - b) <= tolerance


def _summary_clean(summary):
    summary = summary or {}
    league_days = int(summary.get("leagueDays") or 0)
    return bool(
        league_days
        and int(summary.get("certified") or 0) == league_days
        and int(summary.get("cutoverReady") or 0) == league_days
        and int(summary.get("reconciling") or 0) == 0
        and int(summary.get("baseline") or 0) == 0
        and int(summary.get("productionOnly") or 0) == 0
        and int(summary.get("stateConsistencyViolations") or 0) == 0
        and int(summary.get("adapterFailures") or 0) == 0
        and int(summary.get("adapterWaiting") or 0) == 0
        and int(summary.get("dateProvenanceWarnings") or 0) == 0
    )


def classify_shadow_only(snapshot, store):
    """Classify current shadow-only rows without inventing a second inclusion policy.

    Canonical's existing inclusion_state/reason is the league-specific policy
    authority. Qualification adds only evidence/identity/date/cutover checks.
    """
    rows = []
    for item in snapshot.get("discrepancies") or []:
        if _clean(item.get("kind")).upper() != "SHADOW_ONLY":
            continue
        event = item.get("event") or {}
        event_id = _clean(event.get("canonical_event_id"))
        league = _clean(item.get("league") or event.get("competition_id")).upper()
        day = _clean(item.get("date") or event.get("slate_date"))
        classes = set(store.evidence_classes(event_id)) if event_id else set()
        provenance_flags = list((event.get("dateProvenance") or {}).get("flags") or [])
        decision = ((((snapshot.get("days") or {}).get(day) or {}).get("leagues") or {}).get(league) or {})
        checks = {
            "active": int(event.get("active") or 0) == 1,
            "includedByPolicy": _clean(event.get("inclusion_state")).upper() == "INCLUDED",
            "resolvedIdentity": _clean(event.get("identity_state")).upper() == "RESOLVED",
            "authoritativeEvidence": "AUTHORITATIVE" in classes,
            "independentEvidence": "INDEPENDENT" in classes,
            "dateProvenanceClean": not provenance_flags,
            "leagueDayCutoverReady": bool(decision.get("cutoverReady")),
        }
        classification = (
            "EXPECTED_CANONICAL_ADDITION"
            if all(checks.values())
            else "OVER_INCLUDED"
        )
        failed = [key for key, ok in checks.items() if not ok]
        rows.append({
            "classification": classification,
            "date": day,
            "league": league,
            "canonicalEventId": event_id,
            "away": event.get("away_name"),
            "home": event.get("home_name"),
            "scheduledAt": event.get("scheduled_at"),
            "inclusionReason": event.get("inclusion_reason") or "",
            "sourceClasses": sorted(classes),
            "checks": checks,
            "failedChecks": failed,
            "dateProvenanceFlags": provenance_flags,
        })
    expected = sum(x["classification"] == "EXPECTED_CANONICAL_ADDITION" for x in rows)
    over = sum(x["classification"] == "OVER_INCLUDED" for x in rows)
    return {
        "total": len(rows),
        "expectedCanonicalAdditions": expected,
        "overIncluded": over,
        "clean": over == 0,
        "events": rows,
    }


class CutoverQualification:
    def __init__(self, diagnostic):
        self.diag = diagnostic
        self.engine = diagnostic.engine
        self.store = diagnostic.store
        self.lock = threading.RLock()
        self.current = {}
        self.last_error = ""
        self._init_table()

    def _connect(self, readonly=False):
        return self.store._connect(readonly=readonly)

    def _init_table(self):
        with self.store._lock, closing(self._connect()) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS canonical_cutover_qualification_cycle(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_key TEXT NOT NULL UNIQUE,
                completed_at REAL NOT NULL,
                clean INTEGER NOT NULL,
                summary_hash TEXT NOT NULL,
                league_days INTEGER NOT NULL DEFAULT 0,
                cutover_ready INTEGER NOT NULL DEFAULT 0,
                shadow_only INTEGER NOT NULL DEFAULT 0,
                expected_additions INTEGER NOT NULL DEFAULT 0,
                over_included INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                snapshot_json TEXT NOT NULL DEFAULT '{}'
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cutover_cycle_completed ON canonical_cutover_qualification_cycle(completed_at DESC)")
            conn.commit()

    def _completed_run(self, snapshot):
        stats = getattr(self.engine, "last_stats", {}) or {}
        completed = float(stats.get("completedAt") or getattr(self.engine, "last_run_at", 0) or 0)
        if not completed:
            return None
        window = snapshot.get("window") or {}
        if _clean(stats.get("dayFrom")) != _clean(window.get("from")):
            return None
        if _clean(stats.get("dayTo")) != _clean(window.get("to")):
            return None
        errors = stats.get("errors") or []
        if errors or _clean(getattr(self.engine, "last_error", "")):
            return None
        return {
            "completedAt": completed,
            "runKey": f"{completed:.6f}",
            "authoritativeEvents": int(stats.get("authoritativeEvents") or 0),
            "independentEvents": int(stats.get("independentEvents") or 0),
        }

    def _cycles(self, limit=20):
        try:
            with self.store._lock, closing(self._connect(readonly=True)) as conn:
                rows = conn.execute(
                    "SELECT * FROM canonical_cutover_qualification_cycle ORDER BY completed_at DESC,id DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
                return [dict(x) for x in rows]
        except Exception:
            return []

    def consecutive_clean_cycles(self):
        count = 0
        for row in self._cycles(100):
            if not bool(row.get("clean")):
                break
            count += 1
        return count

    def _record_cycle(self, snapshot, audit):
        run = self._completed_run(snapshot)
        if not run:
            return False
        summary = snapshot.get("summary") or {}
        clean = _summary_clean(summary) and audit.get("overIncluded", 0) == 0
        reasons = []
        if not _summary_clean(summary):
            reasons.append("VALIDATION_NOT_CLEAN")
        if audit.get("overIncluded", 0):
            reasons.append(f"OVER_INCLUDED:{audit['overIncluded']}")
        reason = "QUALIFIED_CLEAN_CYCLE" if not reasons else " | ".join(reasons)
        compact = {
            "run": run,
            "summary": summary,
            "audit": {
                "total": audit.get("total", 0),
                "expectedCanonicalAdditions": audit.get("expectedCanonicalAdditions", 0),
                "overIncluded": audit.get("overIncluded", 0),
            },
        }
        digest = hashlib.sha256(json.dumps(compact, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.store._lock, closing(self._connect()) as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO canonical_cutover_qualification_cycle(
                    run_key,completed_at,clean,summary_hash,league_days,cutover_ready,shadow_only,
                    expected_additions,over_included,reason,snapshot_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run["runKey"], run["completedAt"], int(clean), digest,
                    int(summary.get("leagueDays") or 0), int(summary.get("cutoverReady") or 0),
                    int(summary.get("shadowOnly") or 0), int(audit.get("expectedCanonicalAdditions") or 0),
                    int(audit.get("overIncluded") or 0), reason,
                    json.dumps(compact, separators=(",", ":")),
                ),
            )
            conn.execute("DELETE FROM canonical_cutover_qualification_cycle WHERE id NOT IN (SELECT id FROM canonical_cutover_qualification_cycle ORDER BY completed_at DESC,id DESC LIMIT 100)")
            conn.commit()
            return bool(cur.rowcount)

    def authority_requested(self):
        return _truthy(os.environ.get(FLAG_ENV) or "0")

    def status(self):
        current = dict(self.current or {})
        cycles = self.consecutive_clean_cycles()
        current_clean = bool(current.get("clean"))
        qualified = current_clean and cycles >= REQUIRED_CYCLES
        requested = self.authority_requested()
        enabled = requested and qualified
        recent = self._cycles(10)
        return {
            "version": VERSION,
            "flag": FLAG_ENV,
            "requested": requested,
            "enabled": enabled,
            "qualified": qualified,
            "currentValidationClean": current_clean,
            "requiredConsecutiveCleanCycles": REQUIRED_CYCLES,
            "consecutiveCleanCycles": cycles,
            "productionAuthority": "CANONICAL_DAY_SLATE" if enabled else "LEGACY_DAY_STATE",
            "failClosedFallback": True,
            "current": current,
            "recentCycles": recent,
            "lastError": self.last_error,
        }

    def process_snapshot(self, snapshot):
        audit = classify_shadow_only(snapshot, self.store)
        clean = _summary_clean(snapshot.get("summary")) and audit.get("overIncluded", 0) == 0
        with self.lock:
            self.current = {
                "capturedAt": snapshot.get("capturedAt"),
                "window": snapshot.get("window"),
                "clean": clean,
                "summary": dict(snapshot.get("summary") or {}),
                "auditSummary": {k: audit.get(k) for k in ("total", "expectedCanonicalAdditions", "overIncluded", "clean")},
                "audit": audit,
            }
        self._record_cycle(snapshot, audit)
        return self.status()

    def _latest_score(self, canonical_event_id):
        try:
            with self.store._lock, closing(self._connect(readonly=True)) as conn:
                row = conn.execute(
                    """SELECT * FROM score_observation WHERE canonical_event_id=?
                       ORDER BY CASE source WHEN 'DAY_STATE' THEN 0 WHEN 'ESPN_DIRECT' THEN 1
                                  WHEN 'ESPN_INDEPENDENT' THEN 2 ELSE 3 END,
                                last_observed_at DESC LIMIT 1""",
                    (canonical_event_id,),
                ).fetchone()
                return dict(row) if row else {}
        except Exception:
            return {}

    def _provider_ids(self, canonical_event_id):
        out = set()
        for row in self.store.mappings_for_event(canonical_event_id):
            value = row.get("provider_event_id")
            if value not in (None, ""):
                out.add(str(value))
        return out

    def _canonical_event_payload(self, row, day, league):
        event = _loads(row.get("raw_json"), {})
        if not isinstance(event, dict):
            event = {}
        event = dict(event)
        event.setdefault("competitionId", league)
        event.setdefault("league", league)
        event["__sbbLeague"] = league
        event["__sbbDate"] = day
        event["canonicalSlateDate"] = day
        event["canonicalEventId"] = row.get("canonical_event_id")
        event["__sbbCanonicalEventId"] = row.get("canonical_event_id")
        if row.get("scheduled_at"):
            event["scheduledAt"] = row.get("scheduled_at")
        if not event.get("away"):
            event["away"] = {"name": row.get("away_name"), "displayName": row.get("away_name")}
        if not event.get("home"):
            event["home"] = {"name": row.get("home_name"), "displayName": row.get("home_name")}
        score = self._latest_score(row.get("canonical_event_id"))
        if score:
            if score.get("status"):
                event["status"] = score.get("status")
            if score.get("away_score") is not None:
                event["awayScore"] = score.get("away_score")
            if score.get("home_score") is not None:
                event["homeScore"] = score.get("home_score")
            if score.get("period") not in (None, ""):
                event["period"] = score.get("period")
            if score.get("clock") not in (None, ""):
                event["clock"] = score.get("clock")
        return event

    def project_day(self, day, legacy_rows):
        status = self.status()
        if not status.get("enabled"):
            return legacy_rows, {"used": False, "reason": "FLAG_OFF_OR_NOT_QUALIFIED", **status}
        current = status.get("current") or {}
        window = current.get("window") or {}
        if not (_clean(window.get("from")) <= day <= _clean(window.get("to"))):
            raise RuntimeError("requested date is outside the currently qualified validation window")

        output = {
            _clean(league).upper(): [dict(x) for x in rows if isinstance(x, dict)]
            for league, rows in (legacy_rows or {}).items()
        }
        canonical_events = self.store.events_for_day(day)
        canonical_by_league = defaultdict(list)
        for row in canonical_events:
            if _clean(row.get("inclusion_state")).upper() == "INCLUDED" and int(row.get("active") or 0) == 1:
                canonical_by_league[_clean(row.get("competition_id")).upper()].append(row)

        replaced = {}
        for league in shadow.SUPPORTED_LEAGUES:
            slates = self.store.latest_slates(day, league)
            slate = slates[0] if slates else None
            if not slate or _clean(slate.get("certification_status")).upper() != "CERTIFIED":
                raise RuntimeError(f"{day} {league} has no current CERTIFIED canonical slate")
            canonical_rows = canonical_by_league.get(league, [])
            legacy = list(output.get(league) or [])
            legacy_id_sets = [_event_ids(x) for x in legacy]
            used = set()
            projected = []
            for row in canonical_rows:
                canonical_id = _clean(row.get("canonical_event_id"))
                provider_ids = self._provider_ids(canonical_id)
                provider_ids.add(canonical_id)
                candidates = [
                    idx for idx, ids in enumerate(legacy_id_sets)
                    if idx not in used and ids & provider_ids
                ]
                if not candidates:
                    candidates = [
                        idx for idx, event in enumerate(legacy)
                        if idx not in used and _same_matchup_time(row, event)
                    ]
                if len(candidates) == 1:
                    idx = candidates[0]
                    used.add(idx)
                    event = dict(legacy[idx])
                    event["__sbbCanonicalEventId"] = canonical_id
                    event["canonicalEventId"] = canonical_id
                    event["__sbbDate"] = day
                    event["canonicalSlateDate"] = day
                    event.setdefault("competitionId", league)
                    event.setdefault("league", league)
                    projected.append(event)
                elif len(candidates) > 1:
                    raise RuntimeError(f"ambiguous legacy binding for {canonical_id}")
                else:
                    projected.append(self._canonical_event_payload(row, day, league))
            output[league] = projected
            replaced[league] = {"legacy": len(legacy), "canonical": len(projected), "matchedLegacy": len(used)}

        return output, {
            "used": True,
            "reason": "CANONICAL_DAY_SLATE_AUTHORITY",
            "version": VERSION,
            "replaced": replaced,
            "qualification": status,
        }


def _qualification_report(status):
    current = status.get("current") or {}
    audit = current.get("audit") or {}
    lines = [
        "CUTOVER QUALIFICATION",
        f"requested: {status.get('requested')}",
        f"enabled: {status.get('enabled')}",
        f"qualified: {status.get('qualified')}",
        f"consecutiveCleanCycles: {status.get('consecutiveCleanCycles')}/{status.get('requiredConsecutiveCleanCycles')}",
        f"shadowOnlyAudit: total={audit.get('total',0)} expected={audit.get('expectedCanonicalAdditions',0)} overIncluded={audit.get('overIncluded',0)}",
    ]
    for row in audit.get("events") or []:
        lines.append(
            f"  {row.get('classification')} {row.get('date')} {row.get('league')} "
            f"{row.get('away')} @ {row.get('home')} id={row.get('canonicalEventId')} "
            f"policy={row.get('inclusionReason') or '-'} classes={','.join(row.get('sourceClasses') or [])} "
            f"failed={','.join(row.get('failedChecks') or []) or '-'}"
        )
    return "\n".join(lines)


def _patch_validation():
    cls = validation.ValidationDiagnostics
    if getattr(cls, "__sbbCutoverQualificationV6116", False):
        return
    original_build = cls.build_snapshot
    original_report = cls._report

    def build_snapshot(self):
        snapshot = original_build(self)
        if _MANAGER is not None:
            status = _MANAGER.process_snapshot(snapshot)
            snapshot["cutoverQualification"] = status
            snapshot.setdefault("diagnosticHooks", {})["shadowOnlyQualification"] = True
            snapshot["diagnosticHooks"]["consecutiveCleanCycleGate"] = True
            snapshot["diagnosticHooks"]["reversibleDaySlateAuthority"] = True
            with self.lock:
                self.cache["snapshot"] = snapshot
                self.cache["report"] = self._report(snapshot)
        return snapshot

    def report(self, snapshot):
        base = original_report(self, snapshot)
        status = snapshot.get("cutoverQualification") or (_MANAGER.status() if _MANAGER else {})
        if not status:
            return base
        marker = "\nRAW VALIDATION SNAPSHOT JSON (REPORT BODY OMITTED)"
        section = "\n\n" + _qualification_report(status)
        if marker in base:
            return base.replace(marker, section + marker, 1)
        return base + section

    cls.build_snapshot = build_snapshot
    cls._report = report
    cls.__sbbCutoverQualificationV6116 = True


def _patch_day_state():
    if getattr(day_state, "__sbbCanonicalDaySlateAuthorityV6116", False):
        return

    def merge(server, day, score_rows, today):
        legacy_rows, diagnostics = _ORIGINAL_MERGE(server, day, score_rows, today)
        if _MANAGER is None:
            return legacy_rows, diagnostics
        try:
            projected, authority = _MANAGER.project_day(day, legacy_rows)
        except Exception as exc:
            authority = {
                "used": False,
                "reason": "CANONICAL_PROJECTION_FAILED_LEGACY_FALLBACK",
                "error": f"{type(exc).__name__}: {exc}",
                "qualification": _MANAGER.status(),
            }
            projected = legacy_rows
            _MANAGER.last_error = authority["error"]
        diagnostics = dict(diagnostics or {})
        diagnostics["canonicalDaySlateAuthority"] = authority
        return projected, diagnostics

    day_state._merge_future_catalog_rows = merge
    day_state.__sbbCanonicalDaySlateAuthorityV6116 = True


def _install_routes(server):
    Handler = server.Handler
    if getattr(Handler, "__sbbCanonicalCutoverQualificationV6116", False):
        return
    old_get = Handler.do_GET

    def do_GET(self):
        parsed = shadow.urlparse(self.path)
        if parsed.path in {"/api/canonical/cutover", "/api/canonical/cutover/qualification"}:
            return server.send_json(self, {"ok": True, **(_MANAGER.status() if _MANAGER else {})}, 200, {"X-SBB-Canonical-Cutover": "QUALIFICATION"})
        if parsed.path == "/api/canonical/cutover/audit":
            status = _MANAGER.status() if _MANAGER else {}
            audit = ((status.get("current") or {}).get("audit") or {})
            return server.send_json(self, {"ok": True, "version": VERSION, "audit": audit, "productionAuthority": status.get("productionAuthority", "LEGACY_DAY_STATE")}, 200, {"X-SBB-Canonical-Cutover": "AUDIT"})
        return old_get(self)

    Handler.do_GET = do_GET
    Handler.__sbbCanonicalCutoverQualificationV6116 = True


def _runtime_install():
    global _MANAGER
    validation.install()
    deadline = time.time() + 180
    diag = None
    server = None
    while time.time() < deadline:
        diag = validation.engine()
        server = sys.modules.get("__main__")
        if diag and server and hasattr(server, "Handler") and hasattr(server, "send_json"):
            break
        time.sleep(0.25)
    if not diag or not server:
        return
    _MANAGER = CutoverQualification(diag)
    _patch_validation()
    _patch_day_state()
    _install_routes(server)
    try:
        server.CANONICAL_CUTOVER_QUALIFICATION = _MANAGER
        server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update({
            "cutoverQualificationVersion": VERSION,
            "cutoverFlag": FLAG_ENV,
            "cutoverDefault": "LEGACY_DAY_STATE",
            "requiredConsecutiveCleanCycles": REQUIRED_CYCLES,
            "shadowOnlyQualification": True,
            "productionAuthority": False,
        })
    except Exception:
        pass
    try:
        snap = diag.snapshot()
        if snap:
            status = _MANAGER.process_snapshot(snap)
            snap["cutoverQualification"] = status
            with diag.lock:
                diag.cache["snapshot"] = snap
                diag.cache["report"] = diag._report(snap)
    except Exception as exc:
        _MANAGER.last_error = f"initial qualification: {type(exc).__name__}: {exc}"


def engine():
    return _MANAGER


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    threading.Thread(target=_runtime_install, daemon=True, name="sbb-canonical-cutover-qualification-v6116").start()

#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbb import canonical_shadow_v600 as shadow
from sbb import canonical_cutover_qualification_v6116 as cutover


CLEAN_SUMMARY = {
    "leagueDays": 105,
    "certified": 105,
    "reconciling": 0,
    "baseline": 0,
    "cutoverReady": 105,
    "productionOnly": 0,
    "shadowOnly": 1,
    "stateConsistencyViolations": 0,
    "adapterFailures": 0,
    "adapterWaiting": 0,
    "dateProvenanceWarnings": 0,
}


class FakeEngine:
    def __init__(self):
        self.last_stats = {}
        self.last_run_at = 0
        self.last_error = ""


class FakeDiag:
    def __init__(self, store):
        self.store = store
        self.engine = FakeEngine()


def add_certified_event(store, day, league, canonical_id, event_id, away, home, scheduled):
    event = {
        "competitionId": league,
        "__sbbDate": day,
        "eventId": event_id,
        "scheduledAt": scheduled,
        "status": "SCHEDULED",
        "away": {"name": away, "displayName": away},
        "home": {"name": home, "displayName": home},
    }
    store.upsert_event(canonical_id, league, day, event, "ESPN_DIRECT", "RESOLVED", "INCLUDED", "ALL_LEAGUE_EVENTS")
    store.upsert_mappings(canonical_id, [("ESPN", event_id, "eventId")])
    store.record_schedule(canonical_id, "OFFICIAL", "AUTHORITATIVE", day, event)
    store.record_schedule(canonical_id, "ESPN_INDEPENDENT", "INDEPENDENT", day, event)
    return event


def certify_day(store, day, league):
    store.record_source_coverage(day, league, "OFFICIAL", "AUTHORITATIVE", True, len(store.events_for_day(day, league)), "")
    store.record_source_coverage(day, league, "ESPN_INDEPENDENT", "INDEPENDENT", True, len(store.events_for_day(day, league)), "")
    slate, _ = store.compile_slate(day, league, force_version=True)
    assert slate["certification_status"] == "CERTIFIED", slate


def make_snapshot(day, canonical_id, clean=True):
    summary = dict(CLEAN_SUMMARY)
    if not clean:
        summary["certified"] = 104
        summary["cutoverReady"] = 104
        summary["reconciling"] = 1
    return {
        "capturedAt": 1,
        "window": {"from": day, "to": day, "today": day},
        "summary": summary,
        "days": {day: {"leagues": {"MLB": {"cutoverReady": clean}}}},
        "discrepancies": [{
            "kind": "SHADOW_ONLY",
            "date": day,
            "league": "MLB",
            "event": {
                "canonical_event_id": canonical_id,
                "competition_id": "MLB",
                "slate_date": day,
                "away_name": "Away Club",
                "home_name": "Home Club",
                "scheduled_at": day + "T23:00:00Z",
                "active": 1,
                "identity_state": "RESOLVED",
                "inclusion_state": "INCLUDED",
                "inclusion_reason": "ALL_LEAGUE_EVENTS",
                "dateProvenance": {"flags": []},
            },
        }],
    }


def verify_shadow_only_audit_and_stability_gate():
    with tempfile.TemporaryDirectory() as td:
        store = shadow.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        day = "2026-09-14"
        add_certified_event(store, day, "MLB", "cev_expected", "123", "Away Club", "Home Club", day + "T23:00:00Z")
        diag = FakeDiag(store)
        manager = cutover.CutoverQualification(diag)
        snapshot = make_snapshot(day, "cev_expected")

        audit = cutover.classify_shadow_only(snapshot, store)
        assert audit["total"] == 1, audit
        assert audit["expectedCanonicalAdditions"] == 1, audit
        assert audit["overIncluded"] == 0, audit
        assert audit["events"][0]["classification"] == "EXPECTED_CANONICAL_ADDITION", audit

        for index in range(1, cutover.REQUIRED_CYCLES + 1):
            completed = 1000.0 + index
            diag.engine.last_stats = {
                "completedAt": completed,
                "dayFrom": day,
                "dayTo": day,
                "authoritativeEvents": 1,
                "independentEvents": 1,
                "errors": [],
            }
            diag.engine.last_run_at = completed
            manager.process_snapshot(snapshot)
            assert manager.consecutive_clean_cycles() == index

        old = os.environ.get(cutover.FLAG_ENV)
        try:
            os.environ[cutover.FLAG_ENV] = "0"
            assert manager.status()["enabled"] is False
            os.environ[cutover.FLAG_ENV] = "1"
            status = manager.status()
            assert status["qualified"] is True, status
            assert status["enabled"] is True, status
        finally:
            if old is None:
                os.environ.pop(cutover.FLAG_ENV, None)
            else:
                os.environ[cutover.FLAG_ENV] = old

        dirty = make_snapshot(day, "cev_expected", clean=False)
        diag.engine.last_stats = {
            "completedAt": 2000.0,
            "dayFrom": day,
            "dayTo": day,
            "errors": [],
        }
        diag.engine.last_run_at = 2000.0
        manager.process_snapshot(dirty)
        assert manager.consecutive_clean_cycles() == 0
        assert manager.status()["qualified"] is False


def verify_overincluded_blocks_cycle():
    with tempfile.TemporaryDirectory() as td:
        store = shadow.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        day = "2026-09-14"
        event = {
            "competitionId": "MLB", "__sbbDate": day, "eventId": "bad",
            "scheduledAt": day + "T23:00:00Z", "status": "SCHEDULED",
            "away": {"displayName": "Away Club"}, "home": {"displayName": "Home Club"},
        }
        store.upsert_event("cev_bad", "MLB", day, event, "ESPN_DIRECT", "RESOLVED", "UNKNOWN", "UNSUPPORTED_POLICY")
        store.record_schedule("cev_bad", "OFFICIAL", "AUTHORITATIVE", day, event)
        store.record_schedule("cev_bad", "ESPN_INDEPENDENT", "INDEPENDENT", day, event)
        snapshot = make_snapshot(day, "cev_bad")
        snapshot["discrepancies"][0]["event"]["inclusion_state"] = "UNKNOWN"
        snapshot["discrepancies"][0]["event"]["inclusion_reason"] = "UNSUPPORTED_POLICY"
        audit = cutover.classify_shadow_only(snapshot, store)
        assert audit["overIncluded"] == 1, audit
        assert "includedByPolicy" in audit["events"][0]["failedChecks"], audit


def verify_inventory_projection_preserves_legacy_scores_and_adds_canonical_only():
    with tempfile.TemporaryDirectory() as td:
        store = shadow.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        day = "2026-09-14"
        add_certified_event(store, day, "MLB", "cev_match", "123", "Away Club", "Home Club", day + "T23:00:00Z")
        add_certified_event(store, day, "MLB", "cev_added", "456", "Second Away", "Second Home", day + "T20:00:00Z")
        for league in shadow.SUPPORTED_LEAGUES:
            certify_day(store, day, league)

        diag = FakeDiag(store)
        manager = cutover.CutoverQualification(diag)
        manager.current = {
            "clean": True,
            "window": {"from": day, "to": day, "today": day},
            "audit": {"total": 0, "expectedCanonicalAdditions": 0, "overIncluded": 0, "events": []},
            "auditSummary": {"total": 0, "expectedCanonicalAdditions": 0, "overIncluded": 0, "clean": True},
            "summary": dict(CLEAN_SUMMARY),
        }
        with store._lock, closing(store._connect()) as conn:
            for idx in range(cutover.REQUIRED_CYCLES):
                conn.execute(
                    """INSERT INTO canonical_cutover_qualification_cycle(
                        run_key,completed_at,clean,summary_hash,league_days,cutover_ready,
                        shadow_only,expected_additions,over_included,reason,snapshot_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (f"run-{idx}", 1000 + idx, 1, f"hash-{idx}", 105, 105, 0, 0, 0, "QUALIFIED_CLEAN_CYCLE", "{}"),
                )
            conn.commit()

        legacy = {
            "MLB": [{
                "eventId": "123", "competitionId": "MLB", "__sbbDate": day,
                "scheduledAt": day + "T23:00:00Z", "status": "LIVE",
                "awayScore": "4", "homeScore": "3",
                "away": {"displayName": "Away Club"}, "home": {"displayName": "Home Club"},
            }],
            "USOPEN": [{"eventId": "special-1", "competitionId": "USOPEN", "__sbbDate": day}],
        }
        old = os.environ.get(cutover.FLAG_ENV)
        try:
            os.environ[cutover.FLAG_ENV] = "1"
            projected, meta = manager.project_day(day, legacy)
        finally:
            if old is None:
                os.environ.pop(cutover.FLAG_ENV, None)
            else:
                os.environ[cutover.FLAG_ENV] = old

        assert meta["used"] is True, meta
        assert len(projected["MLB"]) == 2, projected
        matched = next(x for x in projected["MLB"] if x.get("eventId") == "123")
        assert matched["awayScore"] == "4" and matched["homeScore"] == "3", matched
        assert matched["canonicalEventId"] == "cev_match", matched
        added = next(x for x in projected["MLB"] if x.get("canonicalEventId") == "cev_added")
        assert added["__sbbDate"] == day, added
        assert projected["USOPEN"][0]["eventId"] == "special-1", projected


def main():
    verify_shadow_only_audit_and_stability_gate()
    verify_overincluded_blocks_cycle()
    verify_inventory_projection_preserves_legacy_scores_and_adds_canonical_only()
    print("PASS: v6.1.16 canonical shadow-only audit + consecutive stability gate + reversible Day Slate authority")


if __name__ == "__main__":
    main()

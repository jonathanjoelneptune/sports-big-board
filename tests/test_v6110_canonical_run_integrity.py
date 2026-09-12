#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbb import canonical_shadow_v600 as shadow
from sbb import canonical_certification_v610 as v610
from sbb import canonical_validation_v612 as v612
from sbb import canonical_identity_ingestion_v619 as v619
from sbb import canonical_run_integrity_v6110 as repair


class DummyServer:
    pass


class DummyHealthEngine:
    def __init__(self, store, completed=None):
        self.store = store
        self.completed = list(completed or [])

    def health(self):
        return {
            "runInProgress": True,
            "currentRunStartedAt": time.time() - 120,
            "currentRunAgeSeconds": 120.0,
            "currentRunCompletedLeagues": list(self.completed),
        }


def team(name, abbreviation=""):
    return {"name": name, "displayName": name, "abbreviation": abbreviation}


def event(league, away, home, scheduled, event_id=""):
    row = {
        "competitionId": league,
        "scheduledAt": scheduled,
        "status": "SCHEDULED",
        "away": team(away),
        "home": team(home),
    }
    if event_id:
        row["eventId"] = event_id
    return row


def new_store(td):
    return shadow.CanonicalShadowStore(Path(td) / "canonical.sqlite3")


def install_patches():
    v619._install_alias_resolver()
    v619._install_ingestion_date_ownership()
    v619._install_policy_aware_validation()
    repair._install_alias_expansion()
    repair._install_batch_persistence()
    repair._install_transactional_bulk_read()
    repair._install_live_validation_decisions()


def verify_merged_rows_are_audit_only():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        now = time.time()
        day = "2026-09-12"
        survivor_event = event("MLS", "LAFC", "Sporting Kansas City", "2026-09-13T00:30:00Z", "ESPN-MLS-1")
        merged_event = event("MLS", "Los Angeles Football Club", "Sporting Kansas City", "2026-09-13T00:30:00Z", "MLS-1")

        store.upsert_event("cev_survivor", "MLS", day, survivor_event, "ESPN_INDEPENDENT", "RESOLVED", "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.record_schedule("cev_survivor", "ESPN_INDEPENDENT", "INDEPENDENT", day, survivor_event)
        store.record_schedule("cev_survivor", "MLS_STATS_API", "AUTHORITATIVE", day, survivor_event)
        store.upsert_event("cev_merged", "MLS", day, merged_event, "MLS_STATS_API", "MERGED", "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.record_schedule("cev_merged", "MLS_STATS_API", "AUTHORITATIVE", day, merged_event)
        with store._lock, store._connect() as conn:
            conn.execute("UPDATE canonical_event SET active=0,identity_state='MERGED',removal_state='MERGED_ALIAS' WHERE canonical_event_id='cev_merged'")
            conn.commit()

        coverage = {
            (day, "MLS", "MLS_STATS_API"): {"success": 1, "result_count": 1, "last_observed_at": now},
            (day, "MLS", "ESPN_INDEPENDENT"): {"success": 1, "result_count": 1, "last_observed_at": now},
        }
        events = []
        obs = {}
        event_by_id = {}
        with store._connect(readonly=True) as conn:
            events = [dict(x) for x in conn.execute("SELECT * FROM canonical_event WHERE slate_date=? AND competition_id='MLS'", (day,)).fetchall()]
            for row in events:
                event_by_id[row["canonical_event_id"]] = row
                obs[row["canonical_event_id"]] = [dict(x) for x in conn.execute(
                    "SELECT * FROM schedule_observation WHERE canonical_event_id=?",
                    (row["canonical_event_id"],),
                ).fetchall()]

        slate = {
            "version": 1, "certification_status": "CERTIFIED",
            "certification_reason": "complete", "universe_count": 1,
            "included_count": 1, "excluded_count": 0, "unknown_count": 0,
            "unresolved_count": 0,
        }
        diag = v612.ValidationDiagnostics(DummyServer(), DummyHealthEngine(store, completed=["MLS"]))
        result = diag._decision(day, "MLS", slate, {}, coverage, events, obs, event_by_id, {day: events})
        assert result["effectiveStatus"] == "CERTIFIED", result
        assert result["cutoverReady"] is True, result
        assert result["evidenceGaps"] == [], result
        assert result["mergedAuditRowCount"] == 1, result
        assert result["mergedAuditRows"][0]["canonicalEventId"] == "cev_merged", result


def verify_remaining_ncaaf_aliases():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        engine = shadow.CanonicalShadowEngine(DummyServer(), store=store)

        official = event("NCAAF", "Southern U.", "Houston", "2026-09-12T23:00:00Z", "NCAA-SOU-HOU")
        espn = event("NCAAF", "Southern Jaguars", "Houston Cougars", "2026-09-12T23:00:00Z", "401856787")
        a = engine.observe_event(official, "NCAAF", "2026-09-12", "NCAA_SD_DATA", "AUTHORITATIVE", "INCLUDED", "NCAAF_TOP25")
        b = engine.observe_event(espn, "NCAAF", "2026-09-12", "ESPN_INDEPENDENT", "INDEPENDENT", "INCLUDED", "NCAAF_TOP25")
        assert a == b, (a, b)
        assert set(store.evidence_classes(a)) >= {"AUTHORITATIVE", "INDEPENDENT"}

        official2 = event("NCAAF", "Western Ky.", "Georgia", "2026-09-12T16:45:00Z", "NCAA-WKU-UGA")
        espn2 = event("NCAAF", "Western Kentucky Hilltoppers", "#2 Georgia Bulldogs", "2026-09-12T16:45:00Z", "401856788")
        c = engine.observe_event(official2, "NCAAF", "2026-09-12", "NCAA_SD_DATA", "AUTHORITATIVE", "INCLUDED", "NCAAF_TOP25")
        d = engine.observe_event(espn2, "NCAAF", "2026-09-12", "ESPN_INDEPENDENT", "INDEPENDENT", "INCLUDED", "NCAAF_TOP25")
        assert c == d, (c, d)
        assert set(store.evidence_classes(c)) >= {"AUTHORITATIVE", "INDEPENDENT"}


def verify_existing_alias_rows_repair():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        official = event("NCAAF", "Southern U.", "Houston", "2026-09-12T23:00:00Z", "NCAA-SOU-HOU-2")
        espn = event("NCAAF", "Southern Jaguars", "Houston Cougars", "2026-09-12T23:00:00Z", "ESPN-SOU-HOU-2")
        store.upsert_event("cev_official", "NCAAF", "2026-09-12", official, "NCAA_SD_DATA", "RESOLVED", "INCLUDED", "NCAAF_TOP25")
        store.record_schedule("cev_official", "NCAA_SD_DATA", "AUTHORITATIVE", "2026-09-12", official)
        store.upsert_event("cev_espn", "NCAAF", "2026-09-12", espn, "ESPN_INDEPENDENT", "RESOLVED", "INCLUDED", "NCAAF_TOP25")
        store.record_schedule("cev_espn", "ESPN_INDEPENDENT", "INDEPENDENT", "2026-09-12", espn)
        result = v619._repair_duplicate_identities(store)
        assert result["merged"] == 1, result
        active = store.events_for_day("2026-09-12", "NCAAF")
        assert len(active) == 1, active
        assert set(store.evidence_classes(active[0]["canonical_event_id"])) >= {"AUTHORITATIVE", "INDEPENDENT"}


def verify_source_window_batching():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        shadow_engine = shadow.CanonicalShadowEngine(DummyServer(), store=store)
        writer = v610.CertificationEvidenceWriter(shadow_engine)
        day = "2026-09-12"
        rows = [
            event("MLB", f"Away {idx}", f"Home {idx}", f"2026-09-12T{12 + idx:02d}:00:00Z", f"MLB-{idx}")
            for idx in range(8)
        ]
        total = writer.snapshot({day: rows}, [day], "MLB", "MLB_STATS_API", "AUTHORITATIVE")
        assert total == 8, total
        stats = getattr(store, "__sbbV6110LastBatch", {})
        assert stats.get("commits") == 1, stats
        # Each event normally commits event + mapping + schedule + score, followed
        # by source coverage. Those calls should now be suppressed inside one batch.
        assert int(stats.get("suppressedCommitCalls") or 0) >= 33, stats
        with store._connect(readonly=True) as conn:
            assert conn.execute("SELECT COUNT(*) FROM canonical_event").fetchone()[0] == 8
            assert conn.execute("SELECT COUNT(*) FROM source_coverage").fetchone()[0] == 1


def verify_refresh_grace_is_stage_bounded():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        day = "2026-09-12"
        stale = time.time() - float(v610.FRESH_SECONDS) - 60.0
        game = {
            "canonical_event_id": "cev_mlb_grace", "competition_id": "MLB",
            "slate_date": day, "active": 1, "identity_state": "RESOLVED",
            "inclusion_state": "INCLUDED", "away_name": "A", "home_name": "B",
            "scheduled_at": "2026-09-12T20:00:00Z",
        }
        obs = {
            "cev_mlb_grace": [
                {"source_class": "AUTHORITATIVE", "last_observed_at": stale},
                {"source_class": "INDEPENDENT", "last_observed_at": stale},
            ]
        }
        coverage = {
            (day, "MLB", "MLB_STATS_API"): {"success": 1, "result_count": 1, "last_observed_at": stale},
            (day, "MLB", "ESPN_INDEPENDENT"): {"success": 1, "result_count": 1, "last_observed_at": stale},
        }
        slate = {
            "version": 1, "certification_status": "CERTIFIED", "certification_reason": "complete",
            "universe_count": 1, "included_count": 1, "excluded_count": 0,
            "unknown_count": 0, "unresolved_count": 0,
        }

        pending_engine = DummyHealthEngine(store, completed=[])
        diag = v612.ValidationDiagnostics(DummyServer(), pending_engine)
        pending = diag._decision(day, "MLB", slate, {}, coverage, [game], obs, {"cev_mlb_grace": game}, {day: [game]})
        assert pending["effectiveStatus"] == "CERTIFIED", pending
        assert pending["refreshInProgressGrace"] is True, pending
        assert pending["stateConsistencyViolation"] is False, pending

        completed_engine = DummyHealthEngine(store, completed=["MLB"])
        diag2 = v612.ValidationDiagnostics(DummyServer(), completed_engine)
        completed = diag2._decision(day, "MLB", slate, {}, coverage, [game], obs, {"cev_mlb_grace": game}, {day: [game]})
        assert completed["effectiveStatus"] == "SHADOW_BASELINE", completed
        assert completed["refreshInProgressGrace"] is False, completed


def verify_worker_stage_health_surface():
    repair._install_worker_stage_observability()
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        shadow_engine = shadow.CanonicalShadowEngine(DummyServer(), store=store)
        engine = v610.CertificationEngine(DummyServer(), shadow_engine)
        engine.__sbbV6110RunStartedAt = time.time() - 5
        engine.__sbbV6110Stage = "AUTHORITATIVE_COLLECT"
        engine.__sbbV6110League = "MLS"
        engine.__sbbV6110Source = "MLS_STATS_API"
        engine.__sbbV6110SourceClass = "AUTHORITATIVE"
        engine.__sbbV6110StageStartedAt = time.time() - 2
        engine.__sbbV6110CompletedLeagues = {"MLB", "NFL"}
        health = engine.health()
        assert health["runInProgress"] is True, health
        assert health["currentRunStage"] == "AUTHORITATIVE_COLLECT", health
        assert health["currentRunLeague"] == "MLS", health
        assert health["currentRunCompletedLeagues"] == ["MLB", "NFL"], health


def main():
    install_patches()
    verify_merged_rows_are_audit_only()
    verify_remaining_ncaaf_aliases()
    verify_existing_alias_rows_repair()
    verify_source_window_batching()
    verify_refresh_grace_is_stage_bounded()
    verify_worker_stage_health_surface()
    print("PASS: v6.1.10 canonical live-row filtering, aliases, atomic batching, refresh grace, and worker stages")


if __name__ == "__main__":
    main()

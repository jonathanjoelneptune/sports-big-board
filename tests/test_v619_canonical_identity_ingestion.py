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
from sbb import canonical_validation_v612 as v612
from sbb import canonical_identity_ingestion_v619 as repair


class DummyServer:
    pass


class DummyEngine:
    def __init__(self, store):
        self.store = store

    def health(self):
        return {
            "runInProgress": True,
            "currentRunStartedAt": 123.0,
            "currentRunAgeSeconds": 45.0,
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


def verify_future_alias_resolution():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        engine = shadow.CanonicalShadowEngine(DummyServer(), store=store)

        official = event("MLS", "Nashville SC", "New York City Football Club", "2026-09-04T23:30:00Z", "MLS-1")
        espn = event("MLS", "Nashville SC", "New York City FC", "2026-09-04T23:30:00Z", "401000001")
        a = engine.observe_event(official, "MLS", "2026-09-04", "MLS_STATS_API", "AUTHORITATIVE", "INCLUDED", "ALL_LEAGUE_EVENTS")
        b = engine.observe_event(espn, "MLS", "2026-09-04", "ESPN_INDEPENDENT", "INDEPENDENT", "INCLUDED", "ALL_LEAGUE_EVENTS")
        assert a == b, (a, b)
        assert set(store.evidence_classes(a)) >= {"AUTHORITATIVE", "INDEPENDENT"}

        ncaa = event("NCAAF", "Western Ky.", "Georgia", "2026-09-12T16:45:00Z", "NCAA-1")
        espn2 = event("NCAAF", "Western Kentucky Hilltoppers", "Georgia Bulldogs", "2026-09-12T16:45:00Z", "401000002")
        # Home alias is not needed here: exact normalized Georgia/Georgia Bulldogs is
        # intentionally not guessed. Make both providers use the same home display.
        espn2["home"] = team("Georgia")
        c = engine.observe_event(ncaa, "NCAAF", "2026-09-12", "NCAA_SD_DATA", "AUTHORITATIVE", "INCLUDED", "NCAAF_TOP25")
        d = engine.observe_event(espn2, "NCAAF", "2026-09-12", "ESPN_INDEPENDENT", "INDEPENDENT", "INCLUDED", "NCAAF_TOP25")
        assert c == d, (c, d)


def verify_eastern_ingestion_ownership():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        engine = shadow.CanonicalShadowEngine(DummyServer(), store=store)
        game = event("MLB", "Boston Red Sox", "Texas Rangers", "2026-09-18T00:05:00Z", "401000003")
        event_id = engine.observe_event(game, "MLB", "2026-09-18", "ESPN_DIRECT", "DIRECT", "INCLUDED", "ALL_LEAGUE_EVENTS")
        assert not store.events_for_day("2026-09-18", "MLB")
        rows = store.events_for_day("2026-09-17", "MLB")
        assert [x["canonical_event_id"] for x in rows] == [event_id], rows


def verify_existing_duplicate_merge():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        official_id = "cev_official"
        espn_id = "cev_espn"
        official = event("NCAAF", "Southern U.", "Houston", "2026-09-12T23:00:00Z", "NCAA-SOU-HOU")
        espn = event("NCAAF", "Southern Jaguars", "Houston", "2026-09-12T23:00:00Z", "401856787")
        store.upsert_event(official_id, "NCAAF", "2026-09-12", official, "NCAA_SD_DATA", "RESOLVED", "INCLUDED", "NCAAF_TOP25")
        store.upsert_mappings(official_id, shadow._provider_ids(official, "NCAA_SD_DATA"))
        store.record_schedule(official_id, "NCAA_SD_DATA", "AUTHORITATIVE", "2026-09-12", official)
        store.upsert_event(espn_id, "NCAAF", "2026-09-12", espn, "ESPN_INDEPENDENT", "RESOLVED", "INCLUDED", "NCAAF_TOP25")
        store.upsert_mappings(espn_id, shadow._provider_ids(espn, "ESPN_INDEPENDENT"))
        store.record_schedule(espn_id, "ESPN_INDEPENDENT", "INDEPENDENT", "2026-09-12", espn)

        result = repair._repair_duplicate_identities(store)
        assert result["merged"] == 1, result
        active = store.events_for_day("2026-09-12", "NCAAF")
        assert len(active) == 1, active
        survivor = active[0]["canonical_event_id"]
        assert set(store.evidence_classes(survivor)) >= {"AUTHORITATIVE", "INDEPENDENT"}
        mappings = store.mappings_for_event(survivor)
        assert len(mappings) >= 2, mappings
        with store._connect(readonly=True) as conn:
            loser = conn.execute(
                "SELECT active,removal_state,identity_state FROM canonical_event WHERE canonical_event_id<>?",
                (survivor,),
            ).fetchone()
        assert loser["active"] == 0 and loser["removal_state"] == "MERGED_ALIAS", dict(loser)


def verify_existing_wrong_day_merge():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        correct = event("MLB", "Boston Red Sox", "Texas Rangers", "2026-09-18T00:05:00Z", "MLB-1")
        stale = event("MLB", "Boston Red Sox", "Texas Rangers", "2026-09-18T00:05:00Z", "ESPN-1")
        store.upsert_event("cev_correct", "MLB", "2026-09-17", correct, "MLB_STATS_API", "RESOLVED", "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.record_schedule("cev_correct", "MLB_STATS_API", "AUTHORITATIVE", "2026-09-17", correct)
        store.upsert_event("cev_stale", "MLB", "2026-09-18", stale, "ESPN_DIRECT", "RESOLVED", "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.record_schedule("cev_stale", "ESPN_INDEPENDENT", "INDEPENDENT", "2026-09-18", stale)
        result = repair._repair_duplicate_identities(store)
        assert result["merged"] == 1, result
        assert len(store.events_for_day("2026-09-17", "MLB")) == 1
        assert not store.events_for_day("2026-09-18", "MLB")
        survivor = store.events_for_day("2026-09-17", "MLB")[0]["canonical_event_id"]
        assert set(store.evidence_classes(survivor)) >= {"AUTHORITATIVE", "INDEPENDENT"}


def verify_ncaaf_excluded_count_variance():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        diag = v612.ValidationDiagnostics(DummyServer(), DummyEngine(store))
        now = time.time()
        coverage = {
            ("2026-09-13", "NCAAF", "NCAA_SD_DATA"): {
                "success": 1, "result_count": 1, "last_observed_at": now,
            },
            ("2026-09-13", "NCAAF", "ESPN_INDEPENDENT"): {
                "success": 1, "result_count": 0, "last_observed_at": now,
            },
        }
        slate = {
            "version": 1, "certification_status": "CERTIFIED",
            "certification_reason": "Authoritative + independent date coverage is complete",
            "universe_count": 1, "included_count": 0, "excluded_count": 1,
            "unknown_count": 0, "unresolved_count": 0,
        }
        result = diag._decision(
            "2026-09-13", "NCAAF", slate, {}, coverage, [], {}, {}, {},
        )
        assert result["effectiveStatus"] == "CERTIFIED", result
        assert result["cutoverReady"] is True, result
        assert result["sourceCountConflict"] is False, result
        assert result["sourceCountWarning"] is True, result
        step = next(x for x in result["decisionTrace"] if x["code"] == "SOURCE_COUNT_AGREEMENT")
        assert step["status"] == "WARN", step


def main():
    repair._install_alias_resolver()
    repair._install_ingestion_date_ownership()
    repair._install_policy_aware_validation()
    repair._install_validation_worker_observability()
    verify_future_alias_resolution()
    verify_eastern_ingestion_ownership()
    verify_existing_duplicate_merge()
    verify_existing_wrong_day_merge()
    verify_ncaaf_excluded_count_variance()
    print("PASS: v6.1.9 canonical identity, Eastern ingestion, duplicate repair, and NCAAF policy-aware validation")


if __name__ == "__main__":
    main()

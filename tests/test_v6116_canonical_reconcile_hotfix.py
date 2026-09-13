#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbb import canonical_shadow_v600 as shadow
from sbb import canonical_identity_ingestion_v619 as v619
from sbb import canonical_reconciliation_hotfix_v6116 as hotfix


def team(name):
    return {"name": name, "displayName": name}


def event(away, home, scheduled, event_id):
    return {
        "competitionId": "NCAAF",
        "__sbbDate": "2026-09-12",
        "eventId": event_id,
        "scheduledAt": scheduled,
        "status": "SCHEDULED",
        "away": team(away),
        "home": team(home),
    }


def new_store(td):
    return shadow.CanonicalShadowStore(Path(td) / "canonical.sqlite3")


def add_row(store, canonical_id, row, source, source_class, day):
    store.upsert_event(
        canonical_id, "NCAAF", day, row, source, "RESOLVED",
        "INCLUDED" if source_class != "AUTHORITATIVE" else "EXCLUDED",
        "TEST",
    )
    store.upsert_mappings(canonical_id, shadow._provider_ids(row, source))
    store.record_schedule(canonical_id, source, source_class, day, row)


def verify_nfl_completed_parser():
    html = """
    <div>Patriots 10, Seahawks 13, FINAL, Wednesday, September 9th</div>
    <div>49ers 27, Rams 7, FINAL, Thursday, September 10th</div>
    """
    rows = hotfix._nfl_final_events_from_html(html, 2026)
    assert [(x["__sbbDate"], x["away"]["displayName"], x["home"]["displayName"]) for x in rows] == [
        ("2026-09-09", "New England Patriots", "Seattle Seahawks"),
        ("2026-09-10", "San Francisco 49ers", "Los Angeles Rams"),
    ], rows
    assert all(x["status"] == "FINAL" and x["scheduledAt"] == "" for x in rows)


def verify_exact_week_proof():
    class Fake:
        _labor_day = staticmethod(lambda season: __import__("datetime").date(season, 9, 7))

    pages, required = hotfix._nfl_pages_strict(Fake(), ["2026-09-17", "2026-09-20"])
    assert required["2026-09-17"] == {(2026, "REG", 2)}, required
    assert required["2026-09-20"] == {(2026, "REG", 2)}, required
    assert any(x[:3] == (2026, "REG", 2) and "/by-week/week-2" in x[3] for x in pages), pages
    assert hotfix._nfl_requirement_satisfied((2026, "REG", 2), {(2026, "REG", 1)}, {(2026, "REG")}) is False
    assert hotfix._nfl_requirement_satisfied((2026, "REG", 2), {(2026, "REG", 2)}, {(2026, "REG")}) is True


def verify_live_ncaaf_aliases():
    hotfix._install_ncaaf_aliases()
    assert v619._canonical_team_key("NCAAF", "Ga. Southern") == v619._canonical_team_key("NCAAF", "Georgia Southern Eagles")
    assert v619._canonical_team_key("NCAAF", "New Mexico St.") == v619._canonical_team_key("NCAAF", "New Mexico State Aggies")
    assert v619._canonical_team_key("NCAAF", "Hawaii") == v619._canonical_team_key("NCAAF", "Hawai'i Rainbow Warriors")


def verify_clemson_two_hour_duplicate_merge():
    hotfix._install_ncaaf_aliases()
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        official = event("Ga. Southern", "Clemson", "2026-09-12T23:30:00Z", "6603779")
        espn = event("Georgia Southern Eagles", "Clemson", "2026-09-13T01:30:00Z", "401858219")
        add_row(store, "cev_official", official, "NCAA_SD_DATA", "AUTHORITATIVE", "2026-09-12")
        add_row(store, "cev_espn", espn, "ESPN_INDEPENDENT", "INDEPENDENT", "2026-09-12")
        store.record_schedule("cev_espn", "ESPN_DIRECT", "DIRECT", "2026-09-12", espn)
        result = hotfix._repair_ncaaf_alias_duplicates(store)
        assert result["merged"] == 1, result
        active = store.events_for_day("2026-09-12", "NCAAF")
        assert len(active) == 1, active
        assert set(store.evidence_classes(active[0]["canonical_event_id"])) >= {"AUTHORITATIVE", "INDEPENDENT"}


def verify_hawaii_adjacent_day_duplicate_merge():
    hotfix._install_ncaaf_aliases()
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        official = event("New Mexico St.", "Hawaii", "2026-09-14T03:59:00Z", "6604207")
        official["__sbbDate"] = "2026-09-13"
        espn = event("New Mexico State Aggies", "Hawai'i Rainbow Warriors", "2026-09-13T03:59:00Z", "401864578")
        add_row(store, "cev_official", official, "NCAA_SD_DATA", "AUTHORITATIVE", "2026-09-13")
        add_row(store, "cev_espn", espn, "ESPN_INDEPENDENT", "INDEPENDENT", "2026-09-12")
        store.record_schedule("cev_espn", "ESPN_DIRECT", "DIRECT", "2026-09-12", espn)
        result = hotfix._repair_ncaaf_alias_duplicates(store)
        assert result["merged"] == 1, result
        active = store.events_for_day("2026-09-12", "NCAAF")
        assert len(active) == 1, active
        survivor = active[0]
        assert survivor["canonical_event_id"] == "cev_espn", survivor
        assert survivor["scheduled_at"] == "2026-09-13T03:59:00Z", survivor
        assert not store.events_for_day("2026-09-13", "NCAAF")


def verify_authoritative_schedule_drift_guard():
    hotfix._install_ncaaf_schedule_drift_guard()
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        espn = event("Georgia Southern Eagles", "Clemson", "2026-09-13T01:30:00Z", "401858219")
        add_row(store, "cev_game", espn, "ESPN_INDEPENDENT", "INDEPENDENT", "2026-09-12")
        store.record_schedule("cev_game", "ESPN_DIRECT", "DIRECT", "2026-09-12", espn)
        official = event("Ga. Southern", "Clemson", "2026-09-12T23:30:00Z", "6603779")
        store.upsert_event(
            "cev_game", "NCAAF", "2026-09-12", official, "NCAA_SD_DATA",
            "RESOLVED", "INCLUDED", "TEST",
        )
        row = store.events_for_day("2026-09-12", "NCAAF")[0]
        assert row["scheduled_at"] == "2026-09-13T01:30:00Z", row


def main():
    verify_nfl_completed_parser()
    verify_exact_week_proof()
    verify_live_ncaaf_aliases()
    verify_clemson_two_hour_duplicate_merge()
    verify_hawaii_adjacent_day_duplicate_merge()
    verify_authoritative_schedule_drift_guard()
    print("PASS: v6.1.16 canonical NFL exact-week/final parser + guarded NCAAF reconciliation hotfix")


if __name__ == "__main__":
    main()

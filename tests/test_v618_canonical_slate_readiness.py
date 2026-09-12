#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbb import canonical_shadow_v600 as shadow
from sbb import canonical_slate_readiness_v618 as readiness


def event(away, home, scheduled, *, rank=0):
    away_team = {"name": away, "displayName": away, "abbreviation": away[:4].upper()}
    home_team = {"name": home, "displayName": home, "abbreviation": home[:4].upper()}
    if rank:
        home_team["rank"] = rank
    return {
        "competitionId": "NCAAF",
        "scheduledAt": scheduled,
        "status": "SCHEDULED",
        "away": away_team,
        "home": home_team,
    }


def new_store(td):
    return shadow.CanonicalShadowStore(Path(td) / "canonical.sqlite3")


def verify_storage():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        with store._connect() as conn:
            synchronous = int(conn.execute("PRAGMA synchronous").fetchone()[0])
        assert synchronous == 1, synchronous


def verify_ncaaf_precedence():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        eid = "cev_ncaaf_resolved"
        base = event("Alpha", "Beta", "2026-09-12T17:00:00Z")
        store.upsert_event(eid, "NCAAF", "2026-09-12", base, "NCAA_SD_DATA", "RESOLVED", "EXCLUDED", "NCAAF_OUTSIDE_TOP25")
        store.upsert_event(eid, "NCAAF", "2026-09-12", base, "ESPN_DIRECT", "RESOLVED", "UNKNOWN", "DIRECT_ESPN_TOP25_NOT_PROVEN")
        row = next(x for x in store.events_for_day("2026-09-12", "NCAAF") if x["canonical_event_id"] == eid)
        assert row["inclusion_state"] == "EXCLUDED", row
        assert row["inclusion_reason"] == "NCAAF_OUTSIDE_TOP25", row


def verify_ncaaf_repair():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        ranked_id = "cev_ncaaf_ranked"
        ranked = event("Gamma", "Delta", "2026-09-12T19:00:00Z", rank=12)
        store.upsert_event(ranked_id, "NCAAF", "2026-09-12", ranked, "ESPN_DIRECT", "RESOLVED", "UNKNOWN", "DIRECT_ESPN_TOP25_NOT_PROVEN")
        store.record_schedule(ranked_id, "NCAA_SD_DATA", "AUTHORITATIVE", "2026-09-12", ranked)
        store.record_schedule(ranked_id, "ESPN_INDEPENDENT", "INDEPENDENT", "2026-09-12", ranked)

        unranked_id = "cev_ncaaf_unranked"
        unranked = event("Epsilon", "Zeta", "2026-09-12T20:00:00Z")
        store.upsert_event(unranked_id, "NCAAF", "2026-09-12", unranked, "ESPN_DIRECT", "RESOLVED", "UNKNOWN", "DIRECT_ESPN_TOP25_NOT_PROVEN")
        store.record_schedule(unranked_id, "NCAA_SD_DATA", "AUTHORITATIVE", "2026-09-12", unranked)
        store.record_schedule(unranked_id, "ESPN_INDEPENDENT", "INDEPENDENT", "2026-09-12", unranked)

        repair = readiness._repair_ncaaf_policy_states(store)
        rows = {x["canonical_event_id"]: x for x in store.events_for_day("2026-09-12", "NCAAF")}
        assert rows[ranked_id]["inclusion_state"] == "INCLUDED", rows[ranked_id]
        assert rows[unranked_id]["inclusion_state"] == "EXCLUDED", rows[unranked_id]
        assert repair["repaired"] == 2, repair


def verify_date_rebucketing():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        mls_id = "cev_mls_boundary"
        mls = {
            "competitionId": "MLS",
            "scheduledAt": "2026-09-14T01:00:00Z",
            "status": "SCHEDULED",
            "away": {"name": "Philadelphia Union", "displayName": "Philadelphia Union", "abbreviation": "PHI"},
            "home": {"name": "San Diego FC", "displayName": "San Diego FC", "abbreviation": "SD"},
        }
        store.upsert_event(mls_id, "MLS", "2026-09-13", mls, "MLS_STATS_API", "RESOLVED", "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.record_schedule(mls_id, "MLS_STATS_API", "AUTHORITATIVE", "2026-09-13", mls)
        store.record_schedule(mls_id, "ESPN_DIRECT", "DIRECT", "2026-09-13", mls)
        store.record_schedule(mls_id, "DAY_STATE", "LEGACY", "2026-09-14", mls)

        canonical_day = store.record_comparison("2026-09-13", "MLS", set())
        assert canonical_day["matched"] == 1, json.dumps(canonical_day, indent=2)
        assert canonical_day["canonicalOnly"] == [], json.dumps(canonical_day, indent=2)
        assert canonical_day["legacyOnly"] == [], json.dumps(canonical_day, indent=2)
        assert canonical_day.get("legacyDateBucketMoves"), canonical_day

        legacy_day = store.record_comparison("2026-09-14", "MLS", {mls_id})
        assert legacy_day["legacyOnly"] == [], json.dumps(legacy_day, indent=2)
        assert legacy_day["matched"] == 0, json.dumps(legacy_day, indent=2)
        assert legacy_day.get("legacyDateBucketMoves"), legacy_day


def main():
    readiness._install_connection_tuning()
    readiness._install_ncaaf_state_precedence()
    readiness._install_canonical_date_comparisons()
    verify_storage()
    verify_ncaaf_precedence()
    verify_ncaaf_repair()
    verify_date_rebucketing()
    print("PASS: v6.1.8 canonical storage, NCAAF policy, and date ownership repairs")


if __name__ == "__main__":
    main()

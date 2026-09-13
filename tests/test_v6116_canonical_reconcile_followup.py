#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbb import canonical_shadow_v600 as shadow
from sbb import canonical_certification_v610 as v610
from sbb import canonical_reconciliation_followup_v6116 as followup


def team(name, abbreviation=""):
    return {"name": name, "displayName": name, "abbreviation": abbreviation}


def new_store(td):
    return shadow.CanonicalShadowStore(Path(td) / "canonical.sqlite3")


def add_event(store, canonical_id, league, day, event, source, source_class, inclusion="INCLUDED"):
    store.upsert_event(canonical_id, league, day, event, source, "RESOLVED", inclusion, "TEST")
    store.upsert_mappings(canonical_id, shadow._provider_ids(event, source))
    store.record_schedule(canonical_id, source, source_class, day, event)


def verify_nfl_live_parser_binds_existing_matchups():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        games = [
            ("cev_bears", "Chicago Bears", "Carolina Panthers", "nfl:bears-panthers", "2026-09-13T17:00Z"),
            ("cev_saints", "New Orleans Saints", "Detroit Lions", "nfl:saints-lions", "2026-09-13T17:00Z"),
        ]
        for canonical_id, away, home, source_id, scheduled in games:
            event = {
                "competitionId": "NFL", "__sbbDate": "2026-09-13", "eventId": source_id,
                "scheduledAt": scheduled, "status": "SCHEDULED",
                "away": team(away), "home": team(home),
            }
            add_event(store, canonical_id, "NFL", "2026-09-13", event, "NFL_COM_SCHEDULE", "AUTHORITATIVE")

        html = """
        <div aria-label="Bears 21, Panthers 14, Q2, FOX"></div>
        <div aria-label="Saints 0, Lions 7, Q2, FOX"></div>
        """
        rows = followup._nfl_live_events_from_html(html, 2026, store, ["2026-09-13"])
        assert len(rows) == 2, rows
        by_name = {x["name"]: x for x in rows}
        bears = by_name["Chicago Bears @ Carolina Panthers"]
        saints = by_name["New Orleans Saints @ Detroit Lions"]
        assert bears["status"] == "LIVE"
        assert bears["eventId"] == "nfl:bears-panthers"
        assert bears["scheduledAt"] == "2026-09-13T17:00Z"
        assert (bears["awayScore"], bears["homeScore"]) == ("21", "14")
        assert saints["eventId"] == "nfl:saints-lions"
        assert (saints["awayScore"], saints["homeScore"]) == ("0", "7")


def verify_strong_provider_guard_beats_game_number_sequence():
    followup._install_strong_provider_identity_guard()
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        existing = {
            "competitionId": "MLB", "__sbbDate": "2026-09-16",
            "eventId": "825031", "gamePk": "825031", "gameNumber": 1,
            "scheduledAt": "2026-09-17T01:40:00Z", "status": "Scheduled",
            "away": team("Miami Marlins", "MIA"),
            "home": team("Arizona Diamondbacks", "AZ"),
        }
        add_event(store, "cev_existing", "MLB", "2026-09-16", existing, "MLB_STATS_API", "AUTHORITATIVE")

        incoming = {
            "competitionId": "MLB", "__sbbDate": "2026-09-16",
            "eventId": "825030", "gamePk": "825030", "gameNumber": 1,
            "scheduledAt": "2026-09-16T01:40:00Z", "status": "Scheduled",
            "away": team("Miami Marlins", "MIA"),
            "home": team("Arizona Diamondbacks", "AZ"),
        }
        resolver = shadow.CanonicalIdentityResolver(store)
        event_id, state, method = resolver.resolve("MLB", "2026-09-16", incoming, "MLB_STATS_API")
        assert event_id != "cev_existing", (event_id, state, method)
        assert state == "RESOLVED", (event_id, state, method)
        assert method == "STRONG_PROVIDER_DISTINCT_EVENT", method

        fake_engine = SimpleNamespace(store=store)
        writer = v610.CertificationEvidenceWriter(fake_engine)
        assert writer._match_existing("MLB", "2026-09-16", incoming) == ""


def verify_mlb_adjacent_day_collapsed_row_splits_on_gamepk():
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        canonical_id = "cev_collapsed"
        sep15_mlb = {
            "competitionId": "MLB", "__sbbDate": "2026-09-15", "eventId": "825030",
            "gamePk": "825030", "gameNumber": 1, "scheduledAt": "2026-09-16T01:40:00Z",
            "status": "Scheduled", "away": team("Miami Marlins", "MIA"),
            "home": team("Arizona Diamondbacks", "AZ"),
        }
        sep16_mlb = {
            "competitionId": "MLB", "__sbbDate": "2026-09-16", "eventId": "825031",
            "gamePk": "825031", "gameNumber": 1, "scheduledAt": "2026-09-17T01:40:00Z",
            "status": "Scheduled", "away": team("Miami Marlins", "MIA"),
            "home": team("Arizona Diamondbacks", "AZ"),
        }
        sep15_espn = {
            "competitionId": "MLB", "__sbbDate": "2026-09-15", "eventId": "401816956",
            "espnEventId": "401816956", "scheduledAt": "2026-09-16T01:40Z",
            "status": "SCHEDULED", "away": team("Miami Marlins", "MIA"),
            "home": team("Arizona Diamondbacks", "ARI"),
        }
        sep16_espn = {
            "competitionId": "MLB", "__sbbDate": "2026-09-16", "eventId": "401816971",
            "espnEventId": "401816971", "scheduledAt": "2026-09-17T01:40Z",
            "status": "SCHEDULED", "away": team("Miami Marlins", "MIA"),
            "home": team("Arizona Diamondbacks", "ARI"),
        }

        store.upsert_event(canonical_id, "MLB", "2026-09-16", sep16_mlb, "MLB_STATS_API", "RESOLVED", "INCLUDED", "TEST")
        for row, source, source_class, observed_day in (
            (sep15_mlb, "MLB_STATS_API", "AUTHORITATIVE", "2026-09-15"),
            (sep16_mlb, "MLB_STATS_API", "AUTHORITATIVE", "2026-09-16"),
            (sep15_espn, "ESPN_INDEPENDENT", "INDEPENDENT", "2026-09-15"),
            (sep16_espn, "ESPN_INDEPENDENT", "INDEPENDENT", "2026-09-16"),
        ):
            store.upsert_mappings(canonical_id, shadow._provider_ids(row, source))
            store.record_schedule(canonical_id, source, source_class, observed_day, row)

        engine = SimpleNamespace(store=store)
        result = followup._repair_mlb_cross_day_collapses(engine)
        assert result["split"] == 1, result
        sep15_rows = store.events_for_day("2026-09-15", "MLB")
        sep16_rows = store.events_for_day("2026-09-16", "MLB")
        assert len(sep15_rows) == 1, sep15_rows
        assert len(sep16_rows) == 1, sep16_rows
        split_id = sep15_rows[0]["canonical_event_id"]
        assert split_id != canonical_id
        assert sep16_rows[0]["canonical_event_id"] == canonical_id
        assert store.mapping_lookup([("MLB", "825030", "MLB_GAME_PK")]) == split_id
        assert store.mapping_lookup([("MLB", "825031", "MLB_GAME_PK")]) == canonical_id
        assert set(store.evidence_classes(split_id)) >= {"AUTHORITATIVE", "INDEPENDENT"}


def verify_post_collection_western_kentucky_merge():
    followup._install_followup_aliases()
    with tempfile.TemporaryDirectory() as td:
        store = new_store(td)
        official = {
            "competitionId": "NCAAF", "__sbbDate": "2026-09-19", "eventId": "6603947",
            "scheduledAt": "2026-09-19T20:00:00Z", "status": "SCHEDULED",
            "away": team("Western Ky."), "home": team("Indiana"),
        }
        espn = {
            "competitionId": "NCAAF", "__sbbDate": "2026-09-19", "eventId": "401858449",
            "espnEventId": "401858449", "scheduledAt": "2026-09-19T20:00Z",
            "status": "SCHEDULED", "away": team("Western Kentucky Hilltoppers"),
            "home": team("Indiana Hoosiers"),
        }
        add_event(store, "cev_official", "NCAAF", "2026-09-19", official, "NCAA_SD_DATA", "AUTHORITATIVE", "INCLUDED")
        add_event(store, "cev_espn", "NCAAF", "2026-09-19", espn, "ESPN_INDEPENDENT", "INDEPENDENT", "INCLUDED")
        store.record_schedule("cev_espn", "ESPN_DIRECT", "DIRECT", "2026-09-19", espn)

        engine = SimpleNamespace(store=store)
        repair = followup._post_collection_repairs(engine)
        assert repair["ncaaf"]["merged"] == 1, repair
        active = store.events_for_day("2026-09-19", "NCAAF")
        assert len(active) == 1, active
        assert set(store.evidence_classes(active[0]["canonical_event_id"])) >= {"AUTHORITATIVE", "INDEPENDENT"}


def main():
    verify_nfl_live_parser_binds_existing_matchups()
    verify_strong_provider_guard_beats_game_number_sequence()
    verify_mlb_adjacent_day_collapsed_row_splits_on_gamepk()
    verify_post_collection_western_kentucky_merge()
    print("PASS: v6.1.16 NFL LIVE continuity + post-collection NCAAF reconciliation + MLB strong-provider identity repair")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbb import canonical_shadow_v600 as shadow
from sbb import canonical_certification_v611 as v611
from sbb import canonical_identity_ingestion_v619 as v619
from sbb import canonical_epl_fpl_state_followup_v6116 as followup


def team(name, abbreviation=""):
    return {"name": name, "displayName": name, "abbreviation": abbreviation}


class CaptureWriter:
    def __init__(self):
        self.calls = []

    def snapshot(self, groups, days, league, source, source_class, success_days=None, errors=None):
        self.calls.append({
            "groups": groups,
            "days": list(days),
            "league": league,
            "source": source,
            "sourceClass": source_class,
        })
        return sum(len(groups.get(day) or []) for day in days)


class FakeEngine:
    def __init__(self, bootstrap=None, fixtures=None, store=None):
        self.writer = CaptureWriter()
        self.bootstrap = bootstrap
        self.fixtures = fixtures
        self.health = []
        self.store = store
        self.shadow = None

    def _http(self, url, headers=None, as_text=False, cache_seconds=0):
        if url == followup.FPL_BOOTSTRAP_URL:
            return self.bootstrap
        if url == followup.FPL_FIXTURES_URL:
            return self.fixtures
        raise AssertionError(url)

    def _mark_health(self, *args):
        self.health.append(args)

    def _failed_range(self, *args, **kwargs):
        raise AssertionError(("unexpected failed range", args, kwargs))


def epl_event(day, away, home, scheduled, event_id):
    return {
        "competitionId": "EPL",
        "__sbbDate": day,
        "eventId": event_id,
        "scheduledAt": scheduled,
        "status": "SCHEDULED",
        "away": team(away),
        "home": team(home),
    }


def add_epl_evidence(store, canonical_id, event, source, source_class, day):
    store.upsert_event(
        canonical_id,
        "EPL",
        day,
        event,
        source,
        "RESOLVED",
        "INCLUDED",
        "ALL_LEAGUE_EVENTS",
    )
    store.upsert_mappings(canonical_id, shadow._provider_ids(event, source))
    store.record_schedule(canonical_id, source, source_class, day, event)


def verify_fpl_official_collector():
    teams = []
    for team_id in range(1, 21):
        name = {
            1: "Manchester United",
            2: "Manchester City",
            3: "Arsenal",
            4: "Sunderland",
        }.get(team_id, f"Premier League Team {team_id}")
        short = {
            1: "MUN", 2: "MCI", 3: "ARS", 4: "SUN"
        }.get(team_id, f"T{team_id:02d}")
        teams.append({"id": team_id, "name": name, "short_name": short})

    fixtures = []
    for fixture_id in range(1, 379):
        fixtures.append({
            "id": fixture_id,
            "kickoff_time": "2026-12-01T20:00:00Z",
            "team_h": 5,
            "team_a": 6,
            "started": False,
            "finished": False,
            "finished_provisional": False,
            "team_h_score": None,
            "team_a_score": None,
        })
    fixtures.extend([
        {
            "id": 9001,
            "kickoff_time": "2026-09-13T15:30:00Z",
            "team_h": 2,
            "team_a": 1,
            "started": True,
            "finished": False,
            "finished_provisional": False,
            "team_h_score": 2,
            "team_a_score": 1,
        },
        {
            "id": 9002,
            "kickoff_time": "2026-09-14T19:00:00Z",
            "team_h": 4,
            "team_a": 3,
            "started": False,
            "finished": False,
            "finished_provisional": False,
            "team_h_score": None,
            "team_a_score": None,
        },
    ])

    fake = FakeEngine({"teams": teams}, fixtures)
    count = followup._collect_epl_official_fpl(fake, "2026-09-13", "2026-09-14")
    assert count == 2, count
    assert len(fake.writer.calls) == 1
    call = fake.writer.calls[0]
    assert call["league"] == "EPL"
    assert call["source"] == followup.EPL_SOURCE
    assert call["sourceClass"] == "AUTHORITATIVE"

    sep13 = call["groups"]["2026-09-13"]
    assert len(sep13) == 1, sep13
    live = sep13[0]
    assert live["away"]["displayName"] == "Manchester United"
    assert live["home"]["displayName"] == "Manchester City"
    assert live["status"] == "LIVE"
    assert (live["awayScore"], live["homeScore"]) == (1, 2)

    sep14 = call["groups"]["2026-09-14"]
    assert len(sep14) == 1, sep14
    scheduled = sep14[0]
    assert scheduled["away"]["displayName"] == "Arsenal"
    assert scheduled["home"]["displayName"] == "Sunderland"
    assert scheduled["status"] == "SCHEDULED"
    assert fake.health and fake.health[-1][0:3] == (
        "EPL", followup.EPL_SOURCE, "AUTHORITATIVE"
    )


def verify_incomplete_fpl_schedule_fails_closed():
    teams = [
        {"id": team_id, "name": f"Team {team_id}", "short_name": f"T{team_id:02d}"}
        for team_id in range(1, 21)
    ]
    mapped = followup._fpl_team_map({"teams": teams})
    try:
        followup._fpl_fixture_groups([], mapped, ["2026-09-13"])
    except RuntimeError as exc:
        assert "incomplete" in str(exc).lower(), exc
    else:
        raise AssertionError("partial/empty FPL response must fail closed")


def verify_explicit_epl_aliases_only():
    followup._install_epl_aliases()
    assert v619._canonical_team_key("EPL", "Man Utd") == v619._canonical_team_key("EPL", "Manchester United")
    assert v619._canonical_team_key("EPL", "Man City") == v619._canonical_team_key("EPL", "Manchester City")
    # Do not turn this into a fuzzy/global abbreviation rule.
    assert v619._canonical_team_key("EPL", "Manchester Utd") != v619._canonical_team_key("EPL", "Manchester United")


def verify_live_console_epl_alias_reconciliation():
    v611._install_certification_gate()
    followup._install_epl_aliases()
    with tempfile.TemporaryDirectory() as td:
        store = shadow.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        fake = FakeEngine(store=store)

        cases = {
            "2026-09-06": [
                (
                    epl_event("2026-09-06", "Man Utd", "Everton", "2026-09-06T13:00:00Z", "30"),
                    epl_event("2026-09-06", "Manchester United", "Everton", "2026-09-06T13:00:00Z", "espn-30"),
                ),
            ],
            "2026-09-13": [
                (
                    epl_event("2026-09-13", "Man City", "Man Utd", "2026-09-13T15:30:00Z", "39"),
                    epl_event("2026-09-13", "Manchester City", "Manchester United", "2026-09-13T15:30:00Z", "espn-39"),
                ),
            ],
            "2026-09-20": [
                (
                    epl_event("2026-09-20", "Sunderland", "Man City", "2026-09-20T13:00:00Z", "45"),
                    epl_event("2026-09-20", "Sunderland", "Manchester City", "2026-09-20T13:00:00Z", "espn-45"),
                ),
                (
                    epl_event("2026-09-20", "Man Utd", "Fulham", "2026-09-20T15:30:00Z", "46"),
                    epl_event("2026-09-20", "Manchester United", "Fulham", "2026-09-20T15:30:00Z", "espn-46"),
                ),
            ],
        }

        expected_live = {}
        serial = 0
        for day, pairs in cases.items():
            expected_live[day] = len(pairs)
            for official, independent in pairs:
                serial += 1
                official_id = f"cev_official_{serial}"
                broad_id = f"cev_broad_{serial}"
                add_epl_evidence(store, official_id, official, followup.EPL_SOURCE, "AUTHORITATIVE", day)
                add_epl_evidence(store, broad_id, independent, "ESPN_INDEPENDENT", "INDEPENDENT", day)
                store.record_schedule(broad_id, "ESPN_DIRECT", "DIRECT", day, independent)
                store.record_schedule(broad_id, "HISTORY_CATALOG", "LEGACY", day, independent)

            count = len(pairs)
            store.record_source_coverage(day, "EPL", followup.EPL_SOURCE, "AUTHORITATIVE", True, count, "")
            store.record_source_coverage(day, "EPL", "ESPN_INDEPENDENT", "INDEPENDENT", True, count, "")
            # Legacy/production knows the broader ESPN identities on the played
            # dates; future Sep 20 legitimately has no production snapshot yet.
            if day != "2026-09-20":
                broad_ids = {
                    row["canonical_event_id"]
                    for row in store.events_for_day(day, "EPL")
                    if "INDEPENDENT" in set(store.evidence_classes(row["canonical_event_id"]))
                }
                store.record_comparison(day, "EPL", broad_ids)
            else:
                store.record_comparison(day, "EPL", set())

        repair = followup._repair_epl_alias_duplicates(fake)
        assert repair["merged"] == 4, repair
        assert repair["touched"] == ["2026-09-06", "2026-09-13", "2026-09-20"], repair

        for day, expected in expected_live.items():
            rows = store.events_for_day(day, "EPL")
            assert len(rows) == expected, (day, rows)
            for row in rows:
                classes = set(store.evidence_classes(row["canonical_event_id"]))
                assert "AUTHORITATIVE" in classes and "INDEPENDENT" in classes, (day, row, classes)
            latest = store.latest_slates(day, "EPL")[0]
            assert latest["certification_status"] == "CERTIFIED", (day, latest)
            assert latest["conflict_count"] == 0, (day, latest)


def verify_stale_known_conflict_normalization():
    v611._install_certification_gate()
    with tempfile.TemporaryDirectory() as td:
        store = shadow.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        day = "2026-09-15"
        canonical_id = "cev_state_cleanup"
        event = {
            "competitionId": "MLB",
            "__sbbDate": day,
            "eventId": "825030",
            "gamePk": "825030",
            "scheduledAt": "2026-09-16T01:40:00Z",
            "status": "SCHEDULED",
            "away": team("Miami Marlins", "MIA"),
            "home": team("Arizona Diamondbacks", "ARI"),
        }
        store.upsert_event(
            canonical_id,
            "MLB",
            day,
            event,
            "MLB_STATS_API",
            "RESOLVED",
            "INCLUDED",
            "ALL_LEAGUE_EVENTS",
        )
        store.record_schedule(canonical_id, "MLB_STATS_API", "AUTHORITATIVE", day, event)
        espn = dict(event)
        espn["eventId"] = "401816956"
        espn["espnEventId"] = "401816956"
        store.record_schedule(canonical_id, "ESPN_INDEPENDENT", "INDEPENDENT", day, espn)
        store.record_source_coverage(day, "MLB", "MLB_STATS_API", "AUTHORITATIVE", True, 1, "")
        store.record_source_coverage(day, "MLB", "ESPN_INDEPENDENT", "INDEPENDENT", True, 1, "")
        store.record_comparison(day, "MLB", {canonical_id})

        base, _ = store.compile_slate(day, "MLB", "TEST_CERTIFIED_BASE", force_version=True)
        assert base["certification_status"] == "CERTIFIED", base

        stale, _ = v611._clone_slate_status(
            store,
            base,
            "RECONCILING",
            "KNOWN_EVENT_UNIVERSE_CONFLICT:5_PRODUCTION_ONLY",
            5,
        )
        assert stale["certification_status"] == "RECONCILING"

        repair = followup._normalize_stale_known_conflicts(store)
        assert repair["repaired"] == 1, repair
        latest = store.latest_slates(day, "MLB")[0]
        assert latest["certification_status"] == "CERTIFIED", latest
        assert latest["conflict_count"] == 0, latest


def verify_release_wiring():
    startup = (ROOT / "sbb" / "startup.py").read_text(encoding="utf-8")
    verify = (ROOT / "VERIFY.sh").read_text(encoding="utf-8")
    init = (ROOT / "sbb" / "__init__.py").read_text(encoding="utf-8")
    if "from .startup import" in init and "bootstrap()" in init:
        assert 'StartupRegistration("canonical-epl-fpl-state-v6116", "canonical_epl_fpl_state_followup_v6116")' in startup
        assert 'StartupPhase("canonical-epl-fpl-state-v6116"' in startup
    else:
        assert "canonical_epl_fpl_state_followup_v6116 import install" in init
    assert "python3 -m py_compile sbb/canonical_epl_fpl_state_followup_v6116.py" in verify
    assert "python3 tests/test_v6116_epl_fpl_state_followup.py" in verify


def main():
    verify_fpl_official_collector()
    verify_incomplete_fpl_schedule_fails_closed()
    verify_explicit_epl_aliases_only()
    verify_live_console_epl_alias_reconciliation()
    verify_stale_known_conflict_normalization()
    verify_release_wiring()
    print("PASS: v6.1.16 EPL FPL adapter + explicit alias reconciliation + stale state normalization")


if __name__ == "__main__":
    main()

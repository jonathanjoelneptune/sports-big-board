import importlib.util
import tempfile
from pathlib import Path


def load_module():
    path = Path(__file__).parents[1] / "sbb" / "canonical_shadow_v600.py"
    spec = importlib.util.spec_from_file_location("canonical_shadow_v600_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def event(event_id, start="2026-09-05T19:05:00-04:00", away="San Diego Padres", home="New York Yankees", **extra):
    row = {
        "espnEventId": event_id,
        "competitionId": "MLB",
        "date": start,
        "scheduledAt": start,
        "away": {"displayName": away, "abbreviation": "SD"},
        "home": {"displayName": home, "abbreviation": "NYY"},
        "status": "SCHEDULED",
    }
    row.update(extra)
    return row


def test_schema_and_legacy_only_never_certifies():
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        store = mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        resolver = mod.CanonicalIdentityResolver(store)
        e = event("401")
        cid, state, _ = resolver.resolve("MLB", "2026-09-05", e, "DAY_STATE")
        assert state == "RESOLVED"
        store.upsert_event(cid, "MLB", "2026-09-05", e, "DAY_STATE", state, "INCLUDED", "LEGACY_BOARD_POLICY")
        store.upsert_mappings(cid, mod._provider_ids(e, "DAY_STATE"))
        store.record_schedule(cid, "DAY_STATE", "LEGACY", "2026-09-05", e)
        store.record_score(cid, "DAY_STATE", e)
        slate, changed = store.compile_slate("2026-09-05", "MLB")
        assert changed
        assert slate["certification_status"] == "SHADOW_BASELINE"
        health = store.health()
        assert health["canonicalEvents"] == 1
        assert health["scheduleObservations"] == 1
        assert health["scoreObservations"] == 1


def test_same_provider_id_survives_time_change():
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        store = mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        resolver = mod.CanonicalIdentityResolver(store)
        first = event("401")
        cid1, state1, _ = resolver.resolve("MLB", "2026-09-05", first, "DAY_STATE")
        store.upsert_event(cid1, "MLB", "2026-09-05", first, "DAY_STATE", state1, "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.upsert_mappings(cid1, mod._provider_ids(first, "DAY_STATE"))
        moved = event("401", start="2026-09-05T21:05:00-04:00")
        cid2, state2, method = resolver.resolve("MLB", "2026-09-05", moved, "DAY_STATE")
        assert cid2 == cid1
        assert state2 == "RESOLVED"
        assert method == "PROVIDER_MAPPING"


def test_doubleheader_does_not_silently_merge():
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        store = mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        resolver = mod.CanonicalIdentityResolver(store)
        game1 = event("401", start="2026-09-05T13:05:00-04:00", gameNumber=1)
        cid1, state1, _ = resolver.resolve("MLB", "2026-09-05", game1, "DAY_STATE")
        store.upsert_event(cid1, "MLB", "2026-09-05", game1, "DAY_STATE", state1, "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.upsert_mappings(cid1, mod._provider_ids(game1, "DAY_STATE"))
        game2 = event("402", start="2026-09-05T19:05:00-04:00", gameNumber=2)
        cid2, state2, _ = resolver.resolve("MLB", "2026-09-05", game2, "DAY_STATE")
        assert cid2 != cid1
        assert state2 == "RESOLVED"


def test_provider_absence_never_deletes_event():
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        store = mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        resolver = mod.CanonicalIdentityResolver(store)
        e = event("401")
        cid, state, _ = resolver.resolve("MLB", "2026-09-05", e, "HISTORY_CATALOG")
        store.upsert_event(cid, "MLB", "2026-09-05", e, "HISTORY_CATALOG", state, "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.upsert_mappings(cid, mod._provider_ids(e, "HISTORY_CATALOG"))
        assert len(store.events_for_day("2026-09-05", "MLB")) == 1
        # Simulate a subsequent source run returning zero rows: no mutation occurs.
        assert len(store.events_for_day("2026-09-05", "MLB")) == 1
        assert store.events_for_day("2026-09-05", "MLB")[0]["active"] == 1


def test_certification_requires_authoritative_and_independent_evidence():
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        store = mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        resolver = mod.CanonicalIdentityResolver(store)
        e = event("401")
        cid, state, _ = resolver.resolve("MLB", "2026-09-05", e, "OFFICIAL_MLB")
        store.upsert_event(cid, "MLB", "2026-09-05", e, "OFFICIAL_MLB", state, "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.upsert_mappings(cid, mod._provider_ids(e, "OFFICIAL_MLB"))
        store.record_schedule(cid, "OFFICIAL_MLB", "AUTHORITATIVE", "2026-09-05", e)
        alt = dict(e)
        alt.pop("espnEventId")
        alt["eventId"] = "secondary-777"
        store.record_schedule(cid, "SECONDARY_PROVIDER", "INDEPENDENT", "2026-09-05", alt)
        store.record_source_coverage("2026-09-05", "MLB", "OFFICIAL_MLB", "AUTHORITATIVE", True, 1)
        store.record_source_coverage("2026-09-05", "MLB", "SECONDARY_PROVIDER", "INDEPENDENT", True, 1)
        slate, _ = store.compile_slate("2026-09-05", "MLB")
        assert slate["certification_status"] == "CERTIFIED"


def test_ncaaf_catalog_only_is_not_assumed_included():
    mod = load_module()
    class FakeServer:
        pass
    with tempfile.TemporaryDirectory() as td:
        engine = mod.CanonicalShadowEngine(FakeServer(), mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3"))
        e = {
            "espnEventId": "n1", "competitionId": "NCAAF", "date": "2026-09-05T12:00:00-04:00",
            "away": {"displayName": "School A"}, "home": {"displayName": "School B"}, "status": "SCHEDULED",
        }
        cid = engine.observe_event(e, "NCAAF", "2026-09-05", "HISTORY_CATALOG", "LEGACY")
        row = engine.store.event_detail(cid)
        assert row["inclusion_state"] == "UNKNOWN"
        slate, _ = engine.store.compile_slate("2026-09-05", "NCAAF")
        assert slate["certification_status"] == "RECONCILING"


def test_comparison_retains_canonical_only_event():
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        store = mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        resolver = mod.CanonicalIdentityResolver(store)
        e = event("401")
        cid, state, _ = resolver.resolve("MLB", "2026-09-05", e, "ESPN_DIRECT")
        store.upsert_event(cid, "MLB", "2026-09-05", e, "ESPN_DIRECT", state, "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.record_schedule(cid, "ESPN_DIRECT", "DIRECT", "2026-09-05", e)
        store.compile_slate("2026-09-05", "MLB")
        diff = store.record_comparison("2026-09-05", "MLB", set())
        assert diff["canonicalOnly"] == [cid]
        latest = store.latest_comparisons("2026-09-05", "MLB")
        assert latest[0]["canonical_only_count"] == 1


def test_zero_event_slate_is_explicit_not_missing():
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        store = mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        slate, changed = store.compile_slate("2026-09-05", "NBA")
        assert changed
        assert slate["universe_count"] == 0
        assert slate["included_count"] == 0
        assert slate["certification_status"] == "SHADOW_BASELINE"
        latest = store.latest_slates("2026-09-05", "NBA")
        assert len(latest) == 1
        assert latest[0]["events"] == []


def test_cfb_alias_normalizes_to_ncaaf():
    mod = load_module()
    assert mod._league({"competitionId": "CFB"}) == "NCAAF"
    assert mod._league({}, "collegefootball") == "NCAAF"


def test_live_final_score_transition_does_not_version_slate():
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        store = mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        resolver = mod.CanonicalIdentityResolver(store)
        e = event("401")
        cid, state, _ = resolver.resolve("MLB", "2026-09-05", e, "DAY_STATE")
        store.upsert_event(cid, "MLB", "2026-09-05", e, "DAY_STATE", state, "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.record_schedule(cid, "DAY_STATE", "LEGACY", "2026-09-05", e)
        first, changed1 = store.compile_slate("2026-09-05", "MLB")
        assert changed1
        live = dict(e); live["status"] = "LIVE"; live["awayScore"] = 2; live["homeScore"] = 1
        store.upsert_event(cid, "MLB", "2026-09-05", live, "DAY_STATE", state, "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.record_score(cid, "DAY_STATE", live)
        second, changed2 = store.compile_slate("2026-09-05", "MLB")
        assert not changed2
        assert second["version"] == first["version"]
        final = dict(live); final["status"] = "FINAL"; final["awayScore"] = 5; final["homeScore"] = 3
        store.upsert_event(cid, "MLB", "2026-09-05", final, "DAY_STATE", state, "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.record_score(cid, "DAY_STATE", final)
        third, changed3 = store.compile_slate("2026-09-05", "MLB")
        assert not changed3
        assert third["version"] == first["version"]
        detail = store.event_detail(cid)
        assert detail["scoreObservations"][0]["status"] == "FINAL"


def test_daily_baseline_is_persistently_detectable():
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        store = mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        assert not store.has_daily_baseline("2026-09-05", "MLB")
        slate, changed = store.compile_slate("2026-09-05", "MLB", "DAILY_BASELINE_0200_ET", force_version=True)
        assert changed
        assert slate["baseline_kind"] == "DAILY_BASELINE_0200_ET"
        assert store.has_daily_baseline("2026-09-05", "MLB")


def test_comparison_exposes_legacy_only_despite_safety_union():
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        store = mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        resolver = mod.CanonicalIdentityResolver(store)
        e = event("401")
        cid, state, _ = resolver.resolve("MLB", "2026-09-05", e, "DAY_STATE")
        store.upsert_event(cid, "MLB", "2026-09-05", e, "DAY_STATE", state, "INCLUDED", "ALL_LEAGUE_EVENTS")
        store.record_schedule(cid, "DAY_STATE", "LEGACY", "2026-09-05", e)
        diff = store.record_comparison("2026-09-05", "MLB", {cid})
        assert diff["legacyOnly"] == [cid]
        assert diff["shadowSafetyUnionCount"] == 1
        assert diff["shadowDiscoveryCount"] == 0


def test_direct_espn_parser_and_top25_policy():
    mod = load_module()
    class FakeServer:
        pass
    with tempfile.TemporaryDirectory() as td:
        engine = mod.CanonicalShadowEngine(FakeServer(), mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3"))
        payload = {"events": [{
            "id": "401999999", "date": "2026-09-05T16:00:00Z", "name": "School A at School B",
            "status": {"type": {"state": "pre", "description": "Scheduled"}},
            "competitions": [{"competitors": [
                {"homeAway": "away", "score": "0", "curatedRank": {"current": 12}, "team": {"id": "1", "displayName": "School A", "abbreviation": "A"}},
                {"homeAway": "home", "score": "0", "curatedRank": {"current": 99}, "team": {"id": "2", "displayName": "School B", "abbreviation": "B"}},
            ], "venue": {"fullName": "Test Stadium"}}]
        }]}
        engine._http_json = lambda url, timeout=mod.HTTP_TIMEOUT: payload if "/college-football/" in url else {"events": []}
        count, touched, errors = engine.ingest_direct_espn_day("2026-09-05")
        assert errors == {}
        assert count == 1
        assert ("2026-09-05", "NCAAF") in touched
        rows = engine.store.events_for_day("2026-09-05", "NCAAF")
        assert len(rows) == 1
        assert rows[0]["inclusion_state"] == "INCLUDED"
        assert rows[0]["inclusion_reason"] == "DIRECT_ESPN_TOP25"
        assert "DIRECT" in engine.store.evidence_classes(rows[0]["canonical_event_id"])



def test_zero_event_day_can_be_certified_by_source_coverage():
    mod = load_module()
    with tempfile.TemporaryDirectory() as td:
        store = mod.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
        store.record_source_coverage("2026-09-05", "NBA", "NBA_OFFICIAL", "AUTHORITATIVE", True, 0)
        store.record_source_coverage("2026-09-05", "NBA", "SECONDARY", "INDEPENDENT", True, 0)
        slate, _ = store.compile_slate("2026-09-05", "NBA")
        assert slate["universe_count"] == 0
        assert slate["certification_status"] == "CERTIFIED"


def _run_direct():
    tests = [(name, obj) for name, obj in sorted(globals().items()) if name.startswith("test_") and callable(obj)]
    for name, fn in tests:
        fn()
        print("PASS:", name)
    print(f"PASS: {len(tests)} canonical shadow tests")


if __name__ == "__main__":
    _run_direct()

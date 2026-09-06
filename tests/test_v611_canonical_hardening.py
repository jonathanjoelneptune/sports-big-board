import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_stack():
    pkg = types.ModuleType("sbb")
    pkg.__path__ = [str(ROOT / "sbb")]
    sys.modules["sbb"] = pkg

    def load(name, rel):
        spec = importlib.util.spec_from_file_location(name, ROOT / rel)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    shadow = load("sbb.canonical_shadow_v600", "sbb/canonical_shadow_v600.py")
    v610 = load("sbb.canonical_certification_v610", "sbb/canonical_certification_v610.py")
    v611 = load("sbb.canonical_certification_v611", "sbb/canonical_certification_v611.py")
    return shadow, v610, v611


def event(event_id, away="San Diego Padres", home="New York Yankees", day="2026-09-06", start="2026-09-06T20:10:00Z", league="MLB"):
    return {
        "competitionId": league,
        "__sbbDate": day,
        "eventId": event_id,
        "scheduledAt": start,
        "status": "SCHEDULED",
        "away": {"displayName": away, "abbreviation": "".join(x[0] for x in away.split() if x)[:4].upper()},
        "home": {"displayName": home, "abbreviation": "".join(x[0] for x in home.split() if x)[:4].upper()},
    }


def add_observed(shadow, store, e, league, day, source, source_class, included=True):
    resolver = shadow.CanonicalIdentityResolver(store)
    cid, state, _ = resolver.resolve(league, day, e, source)
    store.upsert_event(cid, league, day, e, source, state, "INCLUDED" if included else "EXCLUDED", "TEST")
    store.upsert_mappings(cid, shadow._provider_ids(e, source))
    store.record_schedule(cid, source, source_class, day, e)
    store.record_score(cid, source, e)
    return cid


def test_production_only_contradiction_revokes_certified():
    shadow, _v610, v611 = load_stack()
    with tempfile.TemporaryDirectory() as td:
        store = shadow.CanonicalShadowStore(Path(td) / "c.sqlite3")
        main = event("official-main")
        cid = add_observed(shadow, store, main, "MLB", "2026-09-06", "OFFICIAL", "AUTHORITATIVE")
        store.record_schedule(cid, "INDEP", "INDEPENDENT", "2026-09-06", dict(main, eventId="indep-main"))
        store.record_source_coverage("2026-09-06", "MLB", "OFFICIAL", "AUTHORITATIVE", True, 1)
        store.record_source_coverage("2026-09-06", "MLB", "INDEP", "INDEPENDENT", True, 1)
        slate, _ = store.compile_slate("2026-09-06", "MLB")
        assert slate["certification_status"] == "CERTIFIED"

        prod = event("legacy-only", away="LA Galaxy", home="Seattle Sounders", league="MLB", start="2026-09-06T22:00:00Z")
        prod_id = add_observed(shadow, store, prod, "MLB", "2026-09-06", "DAY_STATE", "LEGACY")
        store.record_comparison("2026-09-06", "MLB", {cid, prod_id})

        v611._install_certification_gate()
        hardened, _ = store.compile_slate("2026-09-06", "MLB")
        assert hardened["certification_status"] == "RECONCILING"
        assert "KNOWN_EVENT_UNIVERSE_CONFLICT:1_PRODUCTION_ONLY" in hardened["certification_reason"]
        hard = v611._hardening_state(store, "2026-09-06", "MLB", hardened)
        assert hard["productionOnlyEvents"][0]["canonical_event_id"] == prod_id


def test_source_count_disagreement_is_reconciling():
    shadow, _v610, v611 = load_stack()
    with tempfile.TemporaryDirectory() as td:
        store = shadow.CanonicalShadowStore(Path(td) / "c.sqlite3")
        e = event("a")
        cid = add_observed(shadow, store, e, "MLB", "2026-09-06", "AUTH", "AUTHORITATIVE")
        store.record_schedule(cid, "IND", "INDEPENDENT", "2026-09-06", dict(e, eventId="b"))
        store.record_source_coverage("2026-09-06", "MLB", "AUTH", "AUTHORITATIVE", True, 2)
        store.record_source_coverage("2026-09-06", "MLB", "IND", "INDEPENDENT", True, 1)
        v611._install_certification_gate()
        slate, _ = store.compile_slate("2026-09-06", "MLB")
        assert slate["certification_status"] == "RECONCILING"
        assert "SOURCE_COUNT_CONFLICT" in slate["certification_reason"]


def test_nfl_server_rendered_aria_label_parser():
    _shadow, _v610, v611 = load_stack()
    html = '<a aria-label="Patriots at Seahawks, Wednesday, September 9th, 8:20 PM, NBC">game</a>'
    rows = v611._nfl_events_from_html(html, 2026)
    assert len(rows) == 1
    assert rows[0]["away"]["displayName"] == "New England Patriots"
    assert rows[0]["home"]["displayName"] == "Seattle Seahawks"
    assert rows[0]["__sbbDate"] == "2026-09-09"


def test_nfl_preseason_pages_do_not_probe_pre4():
    _shadow, v610, v611 = load_stack()
    dummy = types.SimpleNamespace(_labor_day=v610.CertificationEngine._labor_day)
    pages, required = v611._nfl_pages_v611(dummy, ["2026-09-06"])
    urls = [x[3] for x in pages]
    assert any("PRE1" in x for x in urls)
    assert any("PRE3" in x for x in urls)
    assert not any("PRE4" in x or "PRE0" in x for x in urls)
    assert any("REG1" in x for x in urls)
    assert (2026, "PRE") in required["2026-09-06"]


def test_mls_match_date_is_canonical_over_utc_boundary():
    _shadow, _v610, v611 = load_stack()
    rows = [{
        "match_id": "m1",
        "match_date": "2026-09-06",
        "planned_kickoff_time": "2026-09-07T02:30:00Z",
        "away_team_name": "LA Galaxy",
        "home_team_name": "Seattle Sounders FC",
        "competition_id": "MLS-COM-000001",
    }]
    groups = v611._mls_groups(rows, {"2026-09-06", "2026-09-07"})
    assert len(groups["2026-09-06"]) == 1
    assert len(groups["2026-09-07"]) == 0


def test_mls_broad_fallback_rejects_next_pro():
    _shadow, _v610, v611 = load_stack()
    assert v611._mls_competition_ok({"competition_id": "MLS-COM-000001"}) is True
    assert v611._mls_competition_ok({"competition_id": "other", "competition_name": "MLS NEXT Pro"}) is False
    assert v611._mls_competition_ok({"competition_name": "Major League Soccer Regular Season"}) is True


def test_ncaaf_readiness_exposes_full_universe_counts():
    shadow, _v610, v611 = load_stack()
    with tempfile.TemporaryDirectory() as td:
        store = shadow.CanonicalShadowStore(Path(td) / "c.sqlite3")
        inc = event("n1", away="#4 Notre Dame", home="Wisconsin", league="NCAAF")
        exc = event("n2", away="Nevada", home="San Jose State", league="NCAAF", start="2026-09-06T21:00:00Z")
        cid1 = add_observed(shadow, store, inc, "NCAAF", "2026-09-06", "AUTH", "AUTHORITATIVE", True)
        cid2 = add_observed(shadow, store, exc, "NCAAF", "2026-09-06", "AUTH", "AUTHORITATIVE", False)
        store.record_schedule(cid1, "IND", "INDEPENDENT", "2026-09-06", inc)
        store.record_source_coverage("2026-09-06", "NCAAF", "AUTH", "AUTHORITATIVE", True, 64)
        store.record_source_coverage("2026-09-06", "NCAAF", "IND", "INDEPENDENT", True, 64)
        v611._install_certification_gate()
        store.compile_slate("2026-09-06", "NCAAF")
        engine = types.SimpleNamespace(store=store)
        rows = v611._readiness_for_day(engine, "2026-09-06")
        metrics = rows["NCAAF"]["ncaafUniverse"]
        assert metrics["authoritativeUniverse"] == 64
        assert metrics["included"] == 1
        assert metrics["excluded"] == 1


def test_v611_source_keeps_production_authority_off():
    text = (ROOT / "sbb" / "canonical_certification_v611.py").read_text(encoding="utf-8")
    assert '"productionAuthority": False' in text
    assert "KNOWN_EVENT_UNIVERSE_CONFLICT" in text
    assert "/api/canonical/certification/readiness" in text
    assert "mlsCanonicalMatchDate" in text


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print(f"PASS: {len(tests)}/{len(tests)} v6.1.1 canonical hardening tests")


if __name__ == "__main__":
    main()

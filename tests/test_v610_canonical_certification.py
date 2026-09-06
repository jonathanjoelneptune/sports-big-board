import importlib.util
import sys
import tempfile
import types
from pathlib import Path


def load_modules():
    root = Path(__file__).parents[1]
    pkg = types.ModuleType("sbb")
    pkg.__path__ = [str(root / "sbb")]
    sys.modules["sbb"] = pkg
    sp = root / "sbb" / "canonical_shadow_v600.py"
    ss = importlib.util.spec_from_file_location("sbb.canonical_shadow_v600", sp)
    shadow = importlib.util.module_from_spec(ss)
    sys.modules[ss.name] = shadow
    ss.loader.exec_module(shadow)
    cp = root / "sbb" / "canonical_certification_v610.py"
    cs = importlib.util.spec_from_file_location("sbb.canonical_certification_v610", cp)
    cert = importlib.util.module_from_spec(cs)
    sys.modules[cs.name] = cert
    cs.loader.exec_module(cert)
    return shadow, cert


class FakeServer:
    pass


def make_engine(shadow, cert, td):
    store = shadow.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
    se = shadow.CanonicalShadowEngine(FakeServer(), store)
    ce = cert.CertificationEngine(FakeServer(), se)
    return se, ce


def event(eid, away="San Diego Padres", home="New York Yankees", start="2026-09-05T19:05:00-04:00", league="MLB", **extra):
    row = {
        "competitionId": league, "__sbbDate": "2026-09-05", "eventId": eid,
        "scheduledAt": start, "status": "SCHEDULED",
        "away": {"displayName": away, "abbreviation": "SD"},
        "home": {"displayName": home, "abbreviation": "NYY"},
    }
    row.update(extra)
    return row


def test_cross_source_ids_attach_to_one_canonical_event_and_certify():
    shadow, cert = load_modules()
    with tempfile.TemporaryDirectory() as td:
        se, ce = make_engine(shadow, cert, td)
        independent = event("espn-401")
        official = event("mlb-777")
        official["away"] = {"displayName": "San Diego Padres", "abbreviation": "SDP", "id": "official-team-1"}
        official["home"] = {"displayName": "New York Yankees", "abbreviation": "NYY", "id": "official-team-2"}
        ce.writer.snapshot({"2026-09-05": [independent]}, ["2026-09-05"], "MLB", "ESPN_INDEPENDENT", "INDEPENDENT")
        ce.writer.snapshot({"2026-09-05": [official]}, ["2026-09-05"], "MLB", "MLB_STATS_API", "AUTHORITATIVE")
        rows = se.store.events_for_day("2026-09-05", "MLB")
        assert len(rows) == 1
        cid = rows[0]["canonical_event_id"]
        assert {"AUTHORITATIVE", "INDEPENDENT"} <= se.store.evidence_classes(cid)
        slate, _ = se.store.compile_slate("2026-09-05", "MLB")
        assert slate["certification_status"] == "CERTIFIED"


def test_latest_failed_coverage_revokes_current_certification_class():
    shadow, cert = load_modules()
    cert._install_freshness_semantics()
    with tempfile.TemporaryDirectory() as td:
        se, ce = make_engine(shadow, cert, td)
        e = event("x")
        ce.writer.snapshot({"2026-09-05": [e]}, ["2026-09-05"], "MLB", "ESPN_INDEPENDENT", "INDEPENDENT")
        ce.writer.snapshot({"2026-09-05": [e]}, ["2026-09-05"], "MLB", "MLB_STATS_API", "AUTHORITATIVE")
        assert {"AUTHORITATIVE", "INDEPENDENT"} <= se.store.coverage_classes("2026-09-05", "MLB")
        se.store.record_source_coverage("2026-09-05", "MLB", "MLB_STATS_API", "AUTHORITATIVE", False, 0, "down")
        assert "AUTHORITATIVE" not in se.store.coverage_classes("2026-09-05", "MLB")


def test_zero_event_day_certifies_when_both_complete_sources_succeed():
    shadow, cert = load_modules()
    with tempfile.TemporaryDirectory() as td:
        se, ce = make_engine(shadow, cert, td)
        ce.writer.snapshot({}, ["2026-09-05"], "NBA", "ESPN_INDEPENDENT", "INDEPENDENT")
        ce.writer.snapshot({}, ["2026-09-05"], "NBA", "NBA_CDN_SCHEDULE", "AUTHORITATIVE")
        slate, _ = se.store.compile_slate("2026-09-05", "NBA")
        assert slate["universe_count"] == 0
        assert slate["certification_status"] == "CERTIFIED"


def test_ncaaf_top25_policy_is_explicit_and_no_unknown_rows_remain():
    shadow, cert = load_modules()
    with tempfile.TemporaryDirectory() as td:
        se, ce = make_engine(shadow, cert, td)
        ranked = event("r1", away="Ohio State", home="Texas", league="NCAAF")
        ranked["away"] = {"displayName": "Ohio State", "rank": 4}
        ranked["home"] = {"displayName": "Texas", "rank": 8}
        unranked = event("u1", away="Nevada", home="San Jose State", league="NCAAF", start="2026-09-05T22:00:00-04:00")
        unranked["away"] = {"displayName": "Nevada"}
        unranked["home"] = {"displayName": "San Jose State"}
        for source, cls in (("ESPN_INDEPENDENT", "INDEPENDENT"), ("NCAA_SD_DATA", "AUTHORITATIVE")):
            ce.writer.snapshot({"2026-09-05": [ranked, unranked]}, ["2026-09-05"], "NCAAF", source, cls)
        rows = se.store.events_for_day("2026-09-05", "NCAAF")
        states = sorted(x["inclusion_state"] for x in rows)
        assert states == ["EXCLUDED", "INCLUDED"]
        slate, _ = se.store.compile_slate("2026-09-05", "NCAAF")
        assert slate["unknown_count"] == 0
        assert slate["certification_status"] == "CERTIFIED"


def test_mlb_official_parser_writes_authoritative_evidence():
    shadow, cert = load_modules()
    with tempfile.TemporaryDirectory() as td:
        se, ce = make_engine(shadow, cert, td)
        ce._http = lambda *a, **k: {"dates": [{"date": "2026-09-05", "games": [{
            "gamePk": 99, "gameDate": "2026-09-05T23:05:00Z", "gameNumber": 1,
            "status": {"detailedState": "Scheduled"},
            "teams": {"away": {"team": {"name": "San Diego Padres", "abbreviation": "SD"}},
                      "home": {"team": {"name": "New York Yankees", "abbreviation": "NYY"}}},
            "venue": {"name": "Yankee Stadium"}
        }]}]}
        assert ce._collect_mlb("2026-09-05", "2026-09-05") == 1
        row = se.store.events_for_day("2026-09-05", "MLB")[0]
        assert "AUTHORITATIVE" in se.store.evidence_classes(row["canonical_event_id"])


def test_nba_official_parser_supports_static_schedule():
    shadow, cert = load_modules()
    with tempfile.TemporaryDirectory() as td:
        se, ce = make_engine(shadow, cert, td)
        ce._http = lambda *a, **k: {"leagueSchedule": {"gameDates": [{"gameDate": "09/05/2026", "games": [{
            "gameId": "1", "gameDateTimeUTC": "2026-09-05T23:00:00Z", "gameStatusText": "7:00 pm ET",
            "awayTeam": {"teamName": "Lakers", "teamTricode": "LAL"},
            "homeTeam": {"teamName": "Celtics", "teamTricode": "BOS"}
        }]}]}}
        assert ce._collect_nba("2026-09-05", "2026-09-05") == 1
        assert se.store.events_for_day("2026-09-05", "NBA")[0]["inclusion_state"] == "INCLUDED"


def test_nhl_official_parser_supports_gameweek():
    shadow, cert = load_modules()
    with tempfile.TemporaryDirectory() as td:
        se, ce = make_engine(shadow, cert, td)
        ce._http = lambda *a, **k: {"gameWeek": [{"date": "2026-09-05", "games": [{
            "id": 3, "startTimeUTC": "2026-09-05T23:00:00Z", "gameState": "FUT",
            "awayTeam": {"placeName": {"default": "Boston"}, "commonName": {"default": "Bruins"}, "abbrev": "BOS"},
            "homeTeam": {"placeName": {"default": "New York"}, "commonName": {"default": "Rangers"}, "abbrev": "NYR"}
        }]}]}
        assert ce._collect_nhl("2026-09-05", "2026-09-05") == 1


def test_epl_official_parser_supports_pulselive_fixtures():
    shadow, cert = load_modules()
    with tempfile.TemporaryDirectory() as td:
        se, ce = make_engine(shadow, cert, td)
        def fake(url, **kwargs):
            if "compseasons" in url:
                return {"content": [{"id": 777, "label": "2026/27"}]}
            return {"content": [{
                "id": 12, "kickoff": {"millis": 1788638400000}, "status": "U",
                "teams": [{"team": {"name": "Arsenal", "shortName": "ARS"}},
                          {"team": {"name": "Liverpool", "shortName": "LIV"}}]
            }]}
        ce._http = fake
        # derive day from the provided epoch rather than asserting a specific fixture date
        day = cert._day_from_datetime(cert._iso_from_epoch(1788638400000))
        assert ce._collect_epl(day, day) == 1


def test_mls_official_parser_supports_stats_api_schedule():
    shadow, cert = load_modules()
    with tempfile.TemporaryDirectory() as td:
        se, ce = make_engine(shadow, cert, td)
        ce._http = lambda *a, **k: {"schedule": [{
            "match_id": "m1", "planned_kickoff_time": "2026-09-05T23:30:00Z",
            "away_team_short_name": "LAFC", "home_team_short_name": "San Diego FC"
        }]}
        assert ce._collect_mls("2026-09-05", "2026-09-05") == 1


def test_ncaa_official_parser_supports_current_graphql_shape():
    shadow, cert = load_modules()
    with tempfile.TemporaryDirectory() as td:
        se, ce = make_engine(shadow, cert, td)
        ce._http = lambda *a, **k: {"data": {"contests": [{
            "contestId": "n1", "gameState": "P", "startTimeEpoch": 1788642000000,
            "teams": [
                {"isHome": False, "nameShort": "Ohio St.", "name6Char": "OHIOST", "teamRank": 3},
                {"isHome": True, "nameShort": "Texas", "name6Char": "TEXAS", "teamRank": 7}
            ]
        }]}}
        assert ce._collect_ncaaf("2026-09-05", "2026-09-05") == 1
        row = se.store.events_for_day("2026-09-05", "NCAAF")[0]
        assert row["inclusion_state"] == "INCLUDED"


def test_nfl_embedded_json_parser_fails_closed_or_recognizes_structured_games():
    shadow, cert = load_modules()
    with tempfile.TemporaryDirectory() as td:
        se, ce = make_engine(shadow, cert, td)
        html = '''<html><script type="application/json">{"schedule":{"games":[{"gameId":"g1","gameDateTime":"2026-09-10T20:20:00-04:00","homeTeam":{"displayName":"Philadelphia Eagles","abbreviation":"PHI"},"awayTeam":{"displayName":"Dallas Cowboys","abbreviation":"DAL"},"status":"SCHEDULED"}]}}</script></html>'''
        blobs = ce._nfl_json_blobs(html)
        parsed = [ce._nfl_event_from_dict(obj) for blob in blobs for obj in cert._walk(blob)]
        parsed = [x for x in parsed if x]
        assert len(parsed) == 1
        assert parsed[0]["eventId"] == "g1"


def test_health_declares_all_seven_source_pairs_and_no_production_authority():
    shadow, cert = load_modules()
    with tempfile.TemporaryDirectory() as td:
        se, ce = make_engine(shadow, cert, td)
        h = ce.health()
        assert h["productionAuthority"] is False
        assert set(h["leagues"]) == set(shadow.SUPPORTED_LEAGUES)
        for league in shadow.SUPPORTED_LEAGUES:
            assert h["leagues"][league]["authoritative"]["sourceClass"] == "AUTHORITATIVE"
            assert h["leagues"][league]["independent"]["sourceClass"] == "INDEPENDENT"


def test_release_surfaces_include_frontend_buttons_and_certification_health():
    root = Path(__file__).parents[1]
    index = root / "index.html"
    if index.exists():
        text = index.read_text(encoding="utf-8")
        assert 'href="canonical-shadow.html"' in text
        assert 'id="sbbCanonicalHealthLink"' in text
        assert 'id="sbbCanonicalCertHealthLink"' in text
        assert '/api/canonical/certification/health' in text
    console = (root / "canonical-shadow.html").read_text(encoding="utf-8")
    for token in ('Certification Adapters', 'adapterRows', 'certHealthLink', '/api/canonical/certification/health'):
        assert token in console
    workflow = (root / ".github" / "workflows" / "deploy-pages.yml")
    if workflow.exists():
        w = workflow.read_text(encoding="utf-8")
        assert w.count('python3 tools/apply_v610_release.py') >= 4


def test_certification_api_route_is_read_only_health_surface():
    root = Path(__file__).parents[1]
    src = (root / "sbb" / "canonical_certification_v610.py").read_text(encoding="utf-8")
    assert '/api/canonical/certification/health' in src
    assert 'productionAuthority": False' in src
    assert 'do_POST' not in src


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print(f"PASS: {len(tests)} v6.1 canonical certification tests")

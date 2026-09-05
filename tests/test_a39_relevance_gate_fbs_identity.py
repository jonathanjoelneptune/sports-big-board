#!/usr/bin/env python3
"""A3.9 relevance-gate + FBS identity regression coverage."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "refresh_sports_ticker.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a39", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def run_log():
    return mod.initial_run_log(
        mod.parse_datetime("2026-09-05T03:05:00Z"),
        mod.parse_datetime("2026-09-04T03:05:00Z"),
        "gpt-4o-mini",
    )


def fbs_context():
    return {
        "mode": "authoritative-2026-roster",
        "teamNames": list(mod.FBS_TEAMS_2026),
        "aliasIndex": mod.build_fbs_alias_index(mod.FBS_TEAMS_2026),
        "rankByName": {},
        "espnTeamIdByCanonical": {},
    }


def result_candidate(
    cid: str,
    league: str,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    *,
    promotion=None,
    enrichment=None,
    home_fbs=None,
    away_fbs=None,
):
    meta = {
        "matchId": cid,
        "homeTeam": home,
        "awayTeam": away,
        "homeScore": home_score,
        "awayScore": away_score,
    }
    if promotion:
        meta["storyPromotion"] = promotion
    if enrichment:
        meta["resultEnrichment"] = enrichment
    if league == "NCAAF":
        meta.update({
            "fbsIdentityPolicy": "authoritative-2026-roster",
            "homeFbs": home_fbs,
            "awayFbs": away_fbs,
            "fbsVsFbs": bool(home_fbs and away_fbs),
        })
    return {
        "candidateId": cid,
        "leagueHint": league,
        "sportHint": "american football" if league == "NCAAF" else "baseball",
        "typeHint": "RESULT",
        "title": f"{home} beat {away} {home_score}-{away_score}",
        "summary": f"Highlightly final: {away} {away_score}, {home} {home_score}.",
        "occurredAt": "2026-09-05T00:00:00Z",
        "timePrecision": "exact",
        "ageHours": 3.0,
        "quality": 100,
        "sourceRecords": [{
            "sourceId": "highlightly-fixture",
            "provider": "Highlightly",
            "url": "https://highlightly.net",
            "rawRef": "fixture",
        }],
        "metadata": meta,
    }


def final_item(candidate, priority=65, item_type="RESULT"):
    return {
        "rank": 1,
        "candidateIds": [candidate["candidateId"]],
        "type": item_type,
        "priority": priority,
        "headline": candidate["title"],
        "text": mod._natural_result_summary_for_candidates(
            [candidate["candidateId"]], {candidate["candidateId"]: candidate}
        ),
        "entities": [],
        "occurredAt": candidate["occurredAt"],
        "timePrecision": "exact",
        "ageHours": candidate["ageHours"],
        "freshnessBasis": candidate["title"],
        "status": "active",
        "sourceUrls": ["https://highlightly.net"],
        "sources": candidate["sourceRecords"],
    }


def test_authoritative_roster_rejects_fcs_false_positives():
    ctx = fbs_context()
    for fcs in (
        "North Carolina A&T Aggies",
        "Indiana State Sycamores",
        "Eastern Illinois Panthers",
        "Bethune-Cookman Wildcats",
        "Idaho Vandals",
        "Harding University Bisons",
    ):
        assert mod.match_fbs_team(fcs, ctx) is None, (fcs, mod.match_fbs_team(fcs, ctx))

    assert mod.match_fbs_team("Georgia State Panthers", ctx) == "Georgia State Panthers"
    assert mod.match_fbs_team("Purdue Boilermakers", ctx) == "Purdue Boilermakers"
    assert mod.match_fbs_team("San José State Spartans", ctx) == "San Jose State Spartans"
    assert mod.match_fbs_team("Eastern Michigan Eagles", ctx) == "Eastern Michigan Eagles"
    assert mod.match_fbs_team("Massachusetts Minutemen", ctx) == "UMass Minutemen"


def test_espn_group80_can_validate_but_not_expand_fbs_membership():
    payload = {
        "events": [
            {
                "competitions": [{
                    "competitors": [
                        {
                            "team": {"id": "2247", "displayName": "Georgia State Panthers"},
                            "curatedRank": {"current": 99},
                        },
                        {
                            "team": {"id": "2428", "displayName": "North Carolina A&T Aggies"},
                            "curatedRank": {"current": 99},
                        },
                    ]
                }]
            },
            {
                "competitions": [{
                    "competitors": [
                        {
                            "team": {"id": "2509", "displayName": "Purdue Boilermakers"},
                            "curatedRank": {"current": 22},
                        },
                        {
                            "team": {"id": "282", "displayName": "Indiana State Sycamores"},
                            "curatedRank": {"current": 99},
                        },
                    ]
                }]
            },
        ]
    }
    old_fetch = mod.fetch_bytes
    mod.fetch_bytes = lambda *a, **k: (
        200,
        {"content-type": "application/json"},
        json.dumps(payload).encode("utf-8"),
    )
    try:
        log = run_log()
        ctx = mod.fetch_espn_fbs_context(mod.parse_datetime("2026-09-05T03:05:00Z"), log)
    finally:
        mod.fetch_bytes = old_fetch

    assert ctx["teamCount"] == 138, ctx["teamCount"]
    assert "North Carolina A&T Aggies" not in ctx["teamNames"]
    assert "Indiana State Sycamores" not in ctx["teamNames"]
    assert mod.match_fbs_team("North Carolina A&T Aggies", ctx) is None
    assert mod.match_fbs_team("Indiana State Sycamores", ctx) is None
    assert ctx["espnTeamIdByCanonical"]["Georgia State Panthers"] == "2247"
    assert ctx["espnTeamIdByCanonical"]["Purdue Boilermakers"] == "2509"
    assert ctx["rankByName"]["Purdue Boilermakers"] == 22
    assert "North Carolina A&T Aggies" in ctx["scoreboardNonFbsOpponents"]
    assert "Indiana State Sycamores" in ctx["scoreboardNonFbsOpponents"]


def test_highlightly_routine_fbs_over_fcs_is_rejected():
    ctx = fbs_context()
    cfg = next(c for c in mod.HIGHLIGHTLY_SPORTS if c["id"] == "highlightly-american-football")
    payload = {
        "data": [{
            "id": 999001,
            "date": "2026-09-05T00:00:00Z",
            "league": {"name": "NCAA"},
            "state": {"description": "Finished", "score": {"current": "59 - 10"}},
            "homeTeam": {"displayName": "Georgia State Panthers"},
            "awayTeam": {"displayName": "North Carolina A&T Aggies"},
        }]
    }
    old_fetch = mod.fetch_bytes
    mod.fetch_bytes = lambda *a, **k: (
        200,
        {"content-type": "application/json"},
        json.dumps(payload).encode("utf-8"),
    )
    try:
        log = run_log()
        candidates = mod.parse_highlightly_sport(
            cfg,
            mod.parse_datetime("2026-09-05T03:05:00Z"),
            mod.parse_datetime("2026-09-04T03:05:00Z"),
            log,
            "fake-key",
            fbs_context=ctx,
        )
    finally:
        mod.fetch_bytes = old_fetch
    assert candidates == [], candidates
    reasons = [
        r.get("reason", "")
        for source in log["sourceFetches"]
        for r in source.get("rejectedItems", [])
    ]
    assert any("routine FBS-v-non-FBS win excluded" in reason for reason in reasons), reasons


def test_highlightly_fbs_v_fbs_is_retained():
    ctx = fbs_context()
    cfg = next(c for c in mod.HIGHLIGHTLY_SPORTS if c["id"] == "highlightly-american-football")
    payload = {
        "data": [{
            "id": 999002,
            "date": "2026-09-05T00:00:00Z",
            "league": {"name": "NCAA"},
            "state": {"description": "Finished", "score": {"current": "27 - 21"}},
            "homeTeam": {"displayName": "San José State Spartans"},
            "awayTeam": {"displayName": "Eastern Michigan Eagles"},
        }]
    }
    old_fetch = mod.fetch_bytes
    mod.fetch_bytes = lambda *a, **k: (
        200,
        {"content-type": "application/json"},
        json.dumps(payload).encode("utf-8"),
    )
    try:
        log = run_log()
        candidates = mod.parse_highlightly_sport(
            cfg,
            mod.parse_datetime("2026-09-05T03:05:00Z"),
            mod.parse_datetime("2026-09-04T03:05:00Z"),
            log,
            "fake-key",
            fbs_context=ctx,
        )
    finally:
        mod.fetch_bytes = old_fetch
    assert candidates, candidates
    assert all(c["metadata"]["fbsVsFbs"] for c in candidates)
    assert all(c["metadata"]["homeFbs"] == "San Jose State Spartans" for c in candidates)
    assert all(c["metadata"]["awayFbs"] == "Eastern Michigan Eagles" for c in candidates)


def test_strong_mlb_stories_suppress_generic_filler():
    strong_candidates = []
    items = []
    for idx, player in enumerate(("Bazzana", "Rocchio", "Alvarez", "Pratt"), 1):
        promotion = {
            "kind": "fixture",
            "storyScore": 74 + idx,
            "priorityFloor": 72,
            "signals": ["PERFORMANCE"],
            "headlineSeed": f"{player} powers a notable win",
            "summarySeed": f"{player} supplied the key story.",
        }
        c = result_candidate(
            f"strong-{idx}", "MLB", f"Home {idx}", f"Away {idx}", 5, 3,
            promotion=promotion,
        )
        strong_candidates.append(c)
        items.append(final_item(c, priority=72 + idx))

    generic = result_candidate(
        "generic-pirates", "MLB", "Pittsburgh Pirates", "Los Angeles Angels", 1, 0
    )
    items.append(final_item(generic, priority=63))
    by_id = {c["candidateId"]: c for c in strong_candidates + [generic]}
    log = run_log()
    kept = mod.apply_final_result_relevance_gate(items, "MLB", by_id, log)
    headlines = [x["headline"] for x in kept]
    assert generic["title"] not in headlines, headlines
    assert len(kept) == 4, headlines
    assert any(
        d["candidateIds"] == ["generic-pirates"]
        for d in log["pipeline"]["relevanceGate"]["dropped"]
    )


def test_generic_draw_is_omitted_even_when_league_is_otherwise_empty():
    draw = result_candidate(
        "mls-draw", "MLS", "New York City FC", "Nashville SC", 0, 0
    )
    item = final_item(draw, priority=60)
    log = run_log()
    kept = mod.apply_final_result_relevance_gate(
        [item], "MLS", {draw["candidateId"]: draw}, log
    )
    assert kept == [], kept
    assert "draw/tie" in log["pipeline"]["relevanceGate"]["dropped"][0]["reason"]


def test_generic_fbs_result_can_fill_when_stronger_stories_are_sparse():
    candidate = result_candidate(
        "sjsu-emu",
        "NCAAF",
        "San Jose State Spartans",
        "Eastern Michigan Eagles",
        27,
        21,
        home_fbs="San Jose State Spartans",
        away_fbs="Eastern Michigan Eagles",
    )
    item = final_item(candidate, priority=63)
    log = run_log()
    kept = mod.apply_final_result_relevance_gate(
        [item], "NCAAF", {candidate["candidateId"]: candidate}, log
    )
    assert len(kept) == 1, kept
    assert log["pipeline"]["relevanceGate"]["keptFillers"], log


def test_standalone_unverified_ncaaf_recap_cannot_reintroduce_fcs_noise():
    candidate = {
        "candidateId": "espn-routine-fcs",
        "leagueHint": "NCAAF",
        "sportHint": "college football",
        "typeHint": "RESULT",
        "title": "Georgia State beats North Carolina A&T 59-10",
        "summary": "A routine FBS-over-FCS result.",
        "occurredAt": "2026-09-05T00:00:00Z",
        "timePrecision": "exact",
        "ageHours": 3.0,
        "quality": 90,
        "sourceRecords": [{
            "sourceId": "espn-ncaaf", "provider": "ESPN",
            "url": "https://www.espn.com/example", "rawRef": "x",
        }],
        "metadata": {},
    }
    item = final_item(candidate, priority=65)
    log = run_log()
    kept = mod.apply_final_result_relevance_gate(
        [item], "NCAAF", {candidate["candidateId"]: candidate}, log
    )
    assert kept == [], kept


if __name__ == "__main__":
    test_authoritative_roster_rejects_fcs_false_positives()
    test_espn_group80_can_validate_but_not_expand_fbs_membership()
    test_highlightly_routine_fbs_over_fcs_is_rejected()
    test_highlightly_fbs_v_fbs_is_retained()
    test_strong_mlb_stories_suppress_generic_filler()
    test_generic_draw_is_omitted_even_when_league_is_otherwise_empty()
    test_generic_fbs_result_can_fill_when_stronger_stories_are_sparse()
    test_standalone_unverified_ncaaf_recap_cannot_reintroduce_fcs_noise()
    print("PASS: A3.9 relevance gate + FBS identity regressions")

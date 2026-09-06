#!/usr/bin/env python3
"""A4.7 cross-game isolation + named Special Event affinity regressions."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "refresh_sports_ticker_a47.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a47", PATH)
a47 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(a47)


def candidate(
    cid: str,
    *,
    title: str,
    summary: str = "",
    home: str | None = None,
    away: str | None = None,
    home_score: int | None = None,
    away_score: int | None = None,
    match_id: str | None = None,
    urls: list[str] | None = None,
):
    metadata = {}
    if home and away and home_score is not None and away_score is not None:
        metadata.update({
            "homeTeam": home,
            "awayTeam": away,
            "homeScore": home_score,
            "awayScore": away_score,
        })
    if match_id:
        metadata["matchId"] = match_id
    return {
        "candidateId": cid,
        "title": title,
        "summary": summary,
        "sourceRecords": [
            {"sourceId": f"src-{i}", "provider": "ESPN", "url": url}
            for i, url in enumerate(urls or [])
        ],
        "metadata": metadata,
    }


def item(
    cid: str,
    headline: str,
    text: str,
    entities: list[str],
    *,
    kind: str = "RESULT",
    freshness: str | None = None,
    source_urls: list[str] | None = None,
):
    return {
        "candidateIds": [cid],
        "type": kind,
        "priority": 75,
        "headline": headline,
        "text": text,
        "entities": entities,
        "freshnessBasis": freshness or text,
        "sourceUrls": list(source_urls or []),
        "sources": [{"url": url} for url in source_urls or []],
        "status": "active",
    }


def normalized_with(league_item=None, special_events=None):
    return {
        "leagues": [
            {"league": "MLB", "seasonState": "active", "items": [league_item] if league_item else []},
            {"league": "EPL", "seasonState": "active", "items": []},
        ],
        "specialEvents": list(special_events or []),
    }


def test_multiple_espn_game_ids_fail_closed():
    c = candidate(
        "cand-giants",
        title="Devers and Koss homer twice as Giants beat Mets 9-5",
        home="San Francisco Giants",
        away="New York Mets",
        home_score=9,
        away_score=5,
        match_id="highlightly-giants-mets",
        urls=[
            "http://www.espn.com/mlb/recap?gameId=401816818",
            "http://www.espn.com/mlb/recap?gameId=401816803",
        ],
    )
    it = item(
        "cand-giants",
        "Alvarez hits 2 homers as Mets beat Giants 10-6",
        "Francisco Alvarez led New York to a 10-6 win over San Francisco.",
        ["New York Mets", "San Francisco Giants", "Francisco Alvarez"],
        source_urls=[
            "http://www.espn.com/mlb/recap?gameId=401816818",
            "http://www.espn.com/mlb/recap?gameId=401816803",
        ],
    )
    failure = a47._result_identity_failure(it, [c])
    assert failure and "multiple distinct ESPN game IDs" in failure, failure


def test_structured_score_mismatch_fails_closed_even_with_one_game_id():
    c = candidate(
        "cand-giants",
        title="Giants beat Mets 9-5",
        home="San Francisco Giants",
        away="New York Mets",
        home_score=9,
        away_score=5,
        match_id="one",
        urls=["http://www.espn.com/mlb/recap?gameId=401816818"],
    )
    it = item(
        "cand-giants",
        "Mets beat Giants 10-6",
        "New York beat San Francisco 10-6.",
        ["New York Mets", "San Francisco Giants"],
        source_urls=["http://www.espn.com/mlb/recap?gameId=401816818"],
    )
    failure = a47._result_identity_failure(it, [c])
    assert failure and "rendered score does not match" in failure, failure


def test_valid_structured_result_passes():
    c = candidate(
        "cand-padres",
        title="Padres beat Yankees 3-2 on Campusano walk-off",
        home="San Diego Padres",
        away="New York Yankees",
        home_score=3,
        away_score=2,
        match_id="padres-yankees",
        urls=["http://www.espn.com/mlb/recap?gameId=401816810"],
    )
    it = item(
        "cand-padres",
        "Campusano's walk-off lifts Padres past Yankees 3-2",
        "Luis Campusano hit a two-run walk-off homer in the 10th.",
        ["San Diego Padres", "New York Yankees", "Luis Campusano"],
        source_urls=["http://www.espn.com/mlb/recap?gameId=401816810"],
    )
    assert a47._result_identity_failure(it, [c]) is None


def test_source_winner_reversal_is_rejected():
    c = candidate(
        "cand-palace",
        title="Chilwell scores late winner as Crystal Palace beat Fulham 3-2",
        summary="Crystal Palace completed a 3-2 comeback win over Fulham.",
    )
    it = item(
        "cand-palace",
        "Chilwell scores late winner as Fulham beat Palace 3-2",
        "Ben Chilwell marked his return to Crystal Palace with the decisive goal.",
        ["Crystal Palace", "Fulham", "Ben Chilwell"],
    )
    failure = a47._result_identity_failure(it, [c])
    assert failure and "rendered winner contradicts" in failure, failure


def test_italian_gp_rejects_monaco_story_but_keeps_italian_story():
    monaco = item(
        "f1-monaco",
        "Gasly loses Monaco GP podium after appeal reinstates penalty",
        "The appeal reinstated Pierre Gasly's Monaco Grand Prix penalties.",
        ["Pierre Gasly", "Isack Hadjar"],
        kind="LEGAL",
    )
    italian = item(
        "f1-italy",
        "Pierre Gasly takes first career pole for Italian Grand Prix",
        "The Alpine driver secured pole at Monza.",
        ["Pierre Gasly", "Alpine"],
        kind="QUALIFYING",
    )
    assert not a47._special_event_affinity(monaco, "Italian Grand Prix", "Formula 1")
    assert a47._special_event_affinity(italian, "Italian Grand Prix", "Formula 1")


def test_us_open_and_ufc_number_affinity_survive():
    us = item(
        "us-open",
        "Gauff reaches US Open fourth round without dropping a set",
        "Coco Gauff advanced at the US Open.",
        ["Coco Gauff"],
        kind="ADVANCEMENT",
    )
    ufc = item(
        "ufc332",
        "Shevchenko vacates UFC flyweight title after injury",
        "Natalia Silva and Wang Cong will fight for the vacant belt at UFC 332.",
        ["Valentina Shevchenko", "Natalia Silva", "Wang Cong"],
        kind="INJURY",
    )
    assert a47._special_event_affinity(us, "US Open", "tennis")
    assert a47._special_event_affinity(ufc, "UFC 332", "MMA")


def test_enforcement_drops_bad_rows_before_global_selector():
    bad_result_candidate = candidate(
        "bad-result",
        title="Giants beat Mets 9-5",
        home="San Francisco Giants",
        away="New York Mets",
        home_score=9,
        away_score=5,
        match_id="g1",
    )
    bad_result = item(
        "bad-result",
        "Mets beat Giants 10-6",
        "New York beat San Francisco 10-6.",
        ["New York Mets", "San Francisco Giants"],
    )
    monaco = item(
        "monaco",
        "Gasly loses Monaco GP podium after appeal",
        "The Monaco Grand Prix result changed after appeal.",
        ["Pierre Gasly"],
        kind="LEGAL",
    )
    italian = item(
        "italy",
        "Gasly takes first career pole for Italian Grand Prix",
        "Gasly secured pole at Monza.",
        ["Pierre Gasly"],
        kind="QUALIFYING",
    )
    normalized = normalized_with(
        bad_result,
        [{"name": "Italian Grand Prix", "sport": "Formula 1", "items": [monaco, italian]}],
    )
    log = {"pipeline": {}}
    out = a47.enforce_output_identity(normalized, [bad_result_candidate], log)
    mlb = next(g for g in out["leagues"] if g["league"] == "MLB")
    assert mlb["items"] == []
    assert len(out["specialEvents"]) == 1
    assert out["specialEvents"][0]["items"] == [italian]
    assert len(log["pipeline"]["a47GameIdentityDrops"]) == 1
    assert len(log["pipeline"]["a47SpecialEventAffinityDrops"]) == 1


def test_patch_chain_keeps_a46_and_adds_a47_core_normalization_hook():
    class FakeA42:
        PIPELINE_VERSION = "old"
        def __init__(self):
            self._configure_core = lambda core: None

    fake_a42 = FakeA42()

    class FakeA43:
        PIPELINE_VERSION = "old"
        def __init__(self):
            self._patch_a42 = lambda a42: None

    fake_a43 = FakeA43()

    class FakeA44:
        PIPELINE_VERSION = "old"
        def __init__(self):
            self._patch_a43 = lambda a43: None
            self._load_a43 = lambda: fake_a43

    fake_a44 = FakeA44()

    class FakeA45:
        PIPELINE_VERSION = "old"
        A45_EDITOR_ADDENDUM = "base"
        def __init__(self):
            self._load_a44 = lambda: fake_a44

    class FakeA46:
        @staticmethod
        def _patch_a45(a45):
            # Minimal stand-in for the already-tested A4.6 layer.
            a45.PIPELINE_VERSION = "A4.6"

    fake_a45 = FakeA45()
    a47._patch_a45(fake_a45, FakeA46())
    assert fake_a45.PIPELINE_VERSION == a47.PIPELINE_VERSION
    assert "EVENT AFFINITY" in fake_a45.A45_EDITOR_ADDENDUM
    loaded_a44 = fake_a45._load_a44()
    loaded_a44._patch_a43(fake_a43)
    fake_a43._patch_a42(fake_a42)
    assert fake_a42.PIPELINE_VERSION == a47.PIPELINE_VERSION


if __name__ == "__main__":
    test_multiple_espn_game_ids_fail_closed()
    test_structured_score_mismatch_fails_closed_even_with_one_game_id()
    test_valid_structured_result_passes()
    test_source_winner_reversal_is_rejected()
    test_italian_gp_rejects_monaco_story_but_keeps_italian_story()
    test_us_open_and_ufc_number_affinity_survive()
    test_enforcement_drops_bad_rows_before_global_selector()
    test_patch_chain_keeps_a46_and_adds_a47_core_normalization_hook()
    print("PASS: A4.7 event affinity + cross-game identity")

#!/usr/bin/env python3
"""A3.10 final-relevance, same-game fusion, and Special Event regressions."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "refresh_sports_ticker.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a310", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def run_log():
    return mod.initial_run_log(
        mod.parse_datetime("2026-09-05T06:20:00Z"),
        mod.parse_datetime("2026-09-04T06:20:00Z"),
        "gpt-5.6-luna",
    )


def source(source_id, provider, url):
    return {
        "sourceId": source_id,
        "provider": provider,
        "url": url,
        "rawRef": source_id,
    }


def structured_game():
    return {
        "candidateId": "game-miami-stanford",
        "leagueHint": "NCAAF",
        "sportHint": "american football",
        "typeHint": "RESULT",
        "title": "Miami Hurricanes beat Stanford Cardinal 45-6",
        "summary": "Highlightly final: Stanford Cardinal 6, Miami Hurricanes 45.",
        "occurredAt": "2026-09-05T01:00:00Z",
        "timePrecision": "exact",
        "ageHours": 5.2,
        "quality": 100,
        "sourceRecords": [
            source("highlightly-ncaaf", "Highlightly", "https://highlightly.net"),
        ],
        "metadata": {
            "matchId": "401858206",
            "homeTeam": "Miami Hurricanes",
            "awayTeam": "Stanford Cardinal",
            "homeScore": 45,
            "awayScore": 6,
            "homeFbs": "Miami Hurricanes",
            "awayFbs": "Stanford Cardinal",
            "fbsVsFbs": True,
        },
    }


def record_article():
    return {
        "candidateId": "news-miami-record",
        "leagueHint": "NCAAF",
        "sportHint": "college football",
        "typeHint": "RECORD",
        "title": "Mensah and Toney set Miami records in 45-6 win over Stanford",
        "summary": (
            "Darian Mensah threw for a Miami debut-record 401 yards and five touchdowns, "
            "while Malachi Toney set the school record with 234 receiving yards."
        ),
        "occurredAt": "2026-09-05T05:51:54Z",
        "timePrecision": "exact",
        "ageHours": 0.5,
        "quality": 90,
        "sourceRecords": [
            source(
                "espn-ncaaf",
                "ESPN",
                "https://www.espn.com/college-football/story/_/id/49832250/"
                "mensah-toney-shatter-miami-records-blowout-stanford",
            ),
        ],
        "metadata": {"categories": ["Miami Hurricanes", "Stanford Cardinal"]},
    }


def injury_article():
    return {
        "candidateId": "news-miami-injury",
        "leagueHint": "NCAAF",
        "sportHint": "college football",
        "typeHint": "INJURY",
        "title": "Miami defender injured after 45-6 win over Stanford",
        "summary": "Miami Hurricanes defender left the Stanford Cardinal game with an injury.",
        "occurredAt": "2026-09-05T03:00:00Z",
        "timePrecision": "exact",
        "ageHours": 3.0,
        "quality": 90,
        "sourceRecords": [
            source("espn-injury", "ESPN", "https://www.espn.com/injury-example"),
        ],
        "metadata": {"categories": ["Miami Hurricanes", "Stanford Cardinal"]},
    }


def special_candidate(cid, title, summary, sport_hint, url):
    return {
        "candidateId": cid,
        "leagueHint": "SPECIAL",
        "sportHint": sport_hint,
        "typeHint": "LEGAL" if sport_hint == "Formula 1" else "RESULT",
        "title": title,
        "summary": summary,
        "occurredAt": "2026-09-05T00:00:00Z",
        "timePrecision": "exact",
        "ageHours": 6.0,
        "quality": 90,
        "sourceRecords": [source("espn-special", "ESPN", url)],
        "metadata": {},
    }


def empty_leagues():
    return {league: {"items": []} for league in mod.BASE_LEAGUES}


def test_record_news_fuses_into_structured_same_game():
    log = run_log()
    kept = mod.dedupe_candidates([structured_game(), record_article()], log)
    assert len(kept) == 1, log["pipeline"]["dedupeActions"]
    candidate = kept[0]
    assert candidate["candidateId"] == "game-miami-stanford"
    assert candidate["typeHint"] == "RECORD", candidate["typeHint"]
    providers = {r["provider"] for r in candidate["sourceRecords"]}
    assert providers == {"Highlightly", "ESPN"}, providers
    fused = candidate["metadata"].get("fusedContext", [])
    assert fused and fused[0]["candidateId"] == "news-miami-record", fused
    assert any(
        "same game news fusion: RECORD" in action.get("reason", "")
        for action in log["pipeline"]["dedupeActions"]
        if action.get("action") == "merge"
    ), log["pipeline"]["dedupeActions"]


def test_non_game_injury_does_not_fuse_even_if_teams_and_score_appear():
    log = run_log()
    kept = mod.dedupe_candidates([structured_game(), injury_article()], log)
    assert len(kept) == 2, log["pipeline"]["dedupeActions"]


def test_model_selected_generic_mls_draw_is_removed_by_final_gate():
    draw = {
        "candidateId": "mls-0-0",
        "leagueHint": "MLS",
        "sportHint": "soccer",
        "typeHint": "RESULT",
        "title": "New York City FC and Nashville SC finished tied 0-0",
        "summary": "Highlightly final: Nashville SC 0, New York City FC 0.",
        "occurredAt": "2026-09-04T23:30:00Z",
        "timePrecision": "exact",
        "ageHours": 6.7,
        "quality": 100,
        "sourceRecords": [source("highlightly-mls", "Highlightly", "https://highlightly.net")],
        "metadata": {
            "matchId": "mls-draw",
            "homeTeam": "New York City FC",
            "awayTeam": "Nashville SC",
            "homeScore": 0,
            "awayScore": 0,
        },
    }
    output = {
        "leagues": empty_leagues(),
        "specialEvents": [],
    }
    output["leagues"]["MLS"]["items"] = [{
        "candidateIds": ["mls-0-0"],
        "type": "RESULT",
        "priority": 60,
        "headline": "NYCFC and Nashville play to scoreless draw",
        "text": "New York City FC and Nashville SC finished 0-0.",
        "entities": ["New York City FC", "Nashville SC"],
        "freshnessBasis": "New York City FC and Nashville SC finished 0-0 Friday.",
        "status": "active",
    }]
    log = run_log()
    normalized = mod.normalize_model_output(
        output,
        [draw],
        mod.parse_datetime("2026-09-05T06:20:00Z"),
        log,
    )
    mls = next(g for g in normalized["leagues"] if g["league"] == "MLS")
    assert mls["items"] == [], mls
    assert any(
        "draw/tie" in row.get("reason", "")
        for row in log["pipeline"]["relevanceGate"]["dropped"]
    )


def test_monaco_story_is_rehomed_from_italian_grand_prix():
    gasly = special_candidate(
        "f1-monaco",
        "Gasly loses Monaco podium after appeal reinstates penalties",
        "Pierre Gasly was stripped of his Monaco Grand Prix podium after an appeal.",
        "Formula 1",
        "https://www.espn.com/f1/story/_/id/49813150/"
        "alpine-pierre-gasly-stripped-monaco-gp-podium",
    )
    output = {
        "leagues": empty_leagues(),
        "specialEvents": [{
            "name": "Italian Grand Prix (Formula 1)",
            "sport": "Formula 1",
            "items": [{
                "candidateIds": ["f1-monaco"],
                "type": "LEGAL",
                "priority": 78,
                "headline": "Gasly loses Monaco podium after appeal reinstates penalties",
                "text": "An appeal reinstated penalties and stripped Gasly of the Monaco podium.",
                "entities": ["Pierre Gasly"],
                "freshnessBasis": "The appeal changed the Monaco Grand Prix result Friday.",
                "status": "active",
            }],
        }],
    }
    log = run_log()
    normalized = mod.normalize_model_output(
        output,
        [gasly],
        mod.parse_datetime("2026-09-05T06:20:00Z"),
        log,
    )
    assert len(normalized["specialEvents"]) == 1, normalized["specialEvents"]
    event = normalized["specialEvents"][0]
    assert event["name"] == "Monaco Grand Prix (Formula 1)", event
    assert log["pipeline"]["specialEventValidation"]["rehomed"], log["pipeline"]["specialEventValidation"]


def test_us_open_stage_group_remains_us_open():
    tennis = special_candidate(
        "tennis-us-open",
        "Alcaraz reaches US Open round of 16",
        "Carlos Alcaraz advanced at the US Open.",
        "tennis",
        "https://www.espn.com/tennis/story/us-open-example",
    )
    output = {
        "leagues": empty_leagues(),
        "specialEvents": [{
            "name": "US Open Round of 16",
            "sport": "tennis",
            "items": [{
                "candidateIds": ["tennis-us-open"],
                "type": "PLAYOFF",
                "priority": 80,
                "headline": "Alcaraz reaches US Open round of 16",
                "text": "Carlos Alcaraz advanced to the US Open round of 16.",
                "entities": ["Carlos Alcaraz"],
                "freshnessBasis": "Alcaraz advanced at the US Open Friday.",
                "status": "active",
            }],
        }],
    }
    log = run_log()
    normalized = mod.normalize_model_output(
        output,
        [tennis],
        mod.parse_datetime("2026-09-05T06:20:00Z"),
        log,
    )
    assert normalized["specialEvents"][0]["name"] == "US Open Round of 16"
    assert log["pipeline"]["specialEventValidation"]["verified"]


if __name__ == "__main__":
    test_record_news_fuses_into_structured_same_game()
    test_non_game_injury_does_not_fuse_even_if_teams_and_score_appear()
    test_model_selected_generic_mls_draw_is_removed_by_final_gate()
    test_monaco_story_is_rehomed_from_italian_grand_prix()
    test_us_open_stage_group_remains_us_open()
    print("PASS: A3.10 final relevance + event fusion regressions")

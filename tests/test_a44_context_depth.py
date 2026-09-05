#!/usr/bin/env python3
"""A4.4 source depth, sparse dedupe, and grounded result-context tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A44_PATH = ROOT / "tools" / "refresh_sports_ticker_a44.py"
A43_PATH = ROOT / "tools" / "refresh_sports_ticker_a43.py"

spec44 = importlib.util.spec_from_file_location("refresh_sports_ticker_a44", A44_PATH)
a44 = importlib.util.module_from_spec(spec44)
assert spec44 and spec44.loader
spec44.loader.exec_module(a44)

spec43 = importlib.util.spec_from_file_location("refresh_sports_ticker_a43_for_a44_test", A43_PATH)
a43 = importlib.util.module_from_spec(spec43)
assert spec43 and spec43.loader
spec43.loader.exec_module(a43)


def item(n, headline, text, entities, kind="RESULT", priority=65):
    return {
        "rank": n,
        "candidateIds": [f"cand-{n}"],
        "type": kind,
        "priority": priority,
        "headline": headline,
        "text": text,
        "entities": entities,
        "occurredAt": "2026-09-05T12:00:00Z",
        "timePrecision": "exact",
        "ageHours": 2.0,
        "freshnessBasis": headline,
        "status": "active",
        "sourceUrls": [],
        "sources": [],
    }


def row(obj, context="US Open"):
    return {
        "kind": "special",
        "context": context,
        "event": context,
        "sport": "tennis",
        "seasonState": "special",
        "item": obj,
    }


def test_sparse_serena_duplicate_collapses():
    newer = row(item(
        1,
        "Serena and Venus Williams lose in US Open doubles return",
        "The Williams sisters lost to Hao-Ching Chan and Maya Joint in a third-set tiebreaker.",
        ["Serena Williams", "Venus Williams", "Hao-Ching Chan", "Maya Joint"],
    ))
    older = row(item(
        2,
        "Serena and Venus Williams lose US Open doubles opener",
        "Serena and Venus Williams were defeated in their first-round US Open doubles match.",
        ["Serena Williams", "Venus Williams"],
    ))
    assert a44._semantic_duplicate_a44(a43, newer, older)


def test_same_pair_different_rounds_are_not_forced_duplicate():
    qf = row(item(
        1, "Example pair wins US Open quarterfinal",
        "Example One and Example Two beat Pair A in the quarterfinal.",
        ["Example One", "Example Two", "Pair A"],
    ))
    sf = row(item(
        2, "Example pair wins US Open semifinal",
        "Example One and Example Two beat Pair B in the semifinal.",
        ["Example One", "Example Two", "Pair B"],
    ))
    assert not a44._semantic_duplicate_a44(a43, qf, sf)


def test_go_ahead_play_context():
    summary = {
        "plays": [
            {"text": "Seattle scored on a sacrifice fly.", "homeScore": 0, "awayScore": 1, "period": {"number": 2}},
            {"text": "Oakland tied it on a solo homer.", "homeScore": 1, "awayScore": 1, "period": {"number": 4}},
            {"text": "Jacob Wilson singled to center, Lawrence Butler scored.", "homeScore": 7, "awayScore": 6, "period": {"number": 8}},
        ]
    }
    score_ctx = {"winnerSide": "home", "winner": "Oakland Athletics"}
    context = a44._go_ahead_context(summary, score_ctx)
    assert context is not None
    assert "Jacob Wilson" in context
    assert "ahead for good" in context
    assert "8th" in context


def test_combined_shutout_pitching_context():
    summary = {
        "boxscore": {
            "players": [
                {
                    "team": {"displayName": "Boston Red Sox", "abbreviation": "BOS"},
                    "statistics": [
                        {
                            "name": "pitching",
                            "labels": ["IP", "H", "R", "ER", "BB", "K"],
                            "athletes": [
                                {"athlete": {"displayName": "Starter Ace"}, "stats": ["6.0", "4", "0", "0", "1", "8"]},
                                {"athlete": {"displayName": "Setup Arm"}, "stats": ["2.0", "0", "0", "0", "0", "2"]},
                                {"athlete": {"displayName": "Closer Arm"}, "stats": ["1.0", "0", "0", "0", "0", "1"]},
                            ],
                        }
                    ],
                }
            ]
        }
    }
    context = a44._shutout_context(summary, {"winner": "Boston Red Sox", "loserScore": 0})
    assert context is not None
    assert "Starter Ace" in context
    assert "6.0 scoreless innings" in context
    assert "Setup Arm" in context and "Closer Arm" in context
    assert "finished the shutout" in context


def test_candidate_story_seed_prefers_decisive_context():
    candidate = {
        "metadata": {
            "storyPromotion": {
                "summarySeed": "Luis Campusano homered in the bottom of the 10th to give San Diego the win."
            },
            "fusedContext": "San Diego beat New York 3-2.",
        }
    }
    assert "Campusano" in a44._candidate_rich_seed(candidate)


def test_espn_news_depth_patch_is_explicit_and_idempotent():
    class Core:
        ESPN_SOURCES = [
            {"url": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/news"},
            {"url": "https://example.com/not-news"},
        ]
    core = Core()
    a44._patch_espn_news_depth(core)
    a44._patch_espn_news_depth(core)
    assert core.ESPN_SOURCES[0]["url"].endswith("?limit=50")
    assert core.ESPN_SOURCES[0]["url"].count("limit=50") == 1
    assert core.ESPN_SOURCES[1]["url"] == "https://example.com/not-news"


def test_raw_buffer_is_larger_than_a43():
    assert a44.REFILL_RAW_FLOOR == 40
    assert a44.REFILL_RAW_TARGET == 42


if __name__ == "__main__":
    test_sparse_serena_duplicate_collapses()
    test_same_pair_different_rounds_are_not_forced_duplicate()
    test_go_ahead_play_context()
    test_combined_shutout_pitching_context()
    test_candidate_story_seed_prefers_decisive_context()
    test_espn_news_depth_patch_is_explicit_and_idempotent()
    test_raw_buffer_is_larger_than_a43()
    print("PASS: A4.4 source depth + sparse dedupe + grounded result context")

#!/usr/bin/env python3
"""A4.5 supporting-copy polish and significance-floor regression tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "refresh_sports_ticker_a45.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a45", PATH)
a45 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(a45)


def _item(kind="RESULT", priority=65, text="", freshness=""):
    return {
        "type": kind,
        "priority": priority,
        "headline": "Example headline",
        "text": text,
        "freshnessBasis": freshness,
        "candidateIds": ["cand-1"],
        "entities": [],
    }


def test_raw_baseball_play_is_penalized():
    raw = "Campusano homered to left (394 feet), Harris scored."
    natural = "Luis Campusano hit a two-run walk-off homer in the 10th inning for San Diego."
    assert a45._looks_like_raw_play(raw)
    assert not a45._looks_like_raw_play(natural)
    assert a45._detail_quality(natural) > a45._detail_quality(raw)


def test_freshness_basis_can_replace_raw_play_copy():
    item = _item(
        text="Campusano homered to left (394 feet), Harris scored.",
        freshness="Luis Campusano delivered a two-run walk-off homer in the 10th inning for San Diego.",
    )
    candidate = {"metadata": {}}
    source, text = a45._best_grounded_detail(item, candidate)
    assert source == "freshness-basis"
    assert "two-run walk-off homer" in text


def test_strong_existing_context_is_preserved():
    item = _item(
        text="Ben Chilwell scored the deciding goal in a comeback victory over Fulham on his return to Crystal Palace.",
        freshness="Crystal Palace beat Fulham 3-2.",
    )
    source, text = a45._best_grounded_detail(item, {"metadata": {}})
    assert source == "current"
    assert "Chilwell" in text


def test_legal_floor_drops_procedural_story_below_75():
    low = _item(kind="LEGAL", priority=72, text="Court update.", freshness="Court update.")
    high = _item(kind="LEGAL", priority=78, text="Major legal development.", freshness="Major legal development.")
    ds = {
        "leagues": [],
        "specialEvents": [{"name": "Golf", "sport": "golf", "items": [low, high]}],
    }
    a45._drop_low_significance_legal(ds)
    assert ds["specialEvents"][0]["items"] == [high]


class _A44Stub:
    @staticmethod
    def _team_matches(team, wanted):
        name = str(team.get("displayName") or "").lower()
        return str(wanted).lower() in name or name in str(wanted).lower()


def test_football_standout_prefers_grounded_passing_line():
    summary = {
        "boxscore": {
            "players": [{
                "team": {"displayName": "Texas Longhorns"},
                "statistics": [{
                    "name": "passing",
                    "labels": ["C/ATT", "YDS", "AVG", "TD", "INT"],
                    "athletes": [{
                        "athlete": {"displayName": "Example QB"},
                        "stats": ["20/28", "275", "9.8", "4", "0"],
                    }],
                }],
            }]
        }
    }
    ctx = {
        "winner": "Texas Longhorns", "loser": "Texas State Bobcats",
        "winnerSide": "home", "homeScore": 59, "awayScore": 7, "loserScore": 7,
    }
    text = a45._football_standout_context(_A44Stub, summary, ctx)
    assert text == "Example QB threw for 275 yards and 4 TDs as Texas Longhorns beat Texas State Bobcats 59-7."


def test_a45_is_polish_only_contract():
    assert a45.PIPELINE_VERSION == "A4.5-copy-polish"
    assert a45.LEGAL_PRIORITY_FLOOR == 75
    assert a45.MAX_NCAAF_CONTEXT_SUMMARIES == 8
    assert "DO NOT CHANGE THE 30-35 HEADLINE MIX" in a45.A45_EDITOR_ADDENDUM


if __name__ == "__main__":
    test_raw_baseball_play_is_penalized()
    test_freshness_basis_can_replace_raw_play_copy()
    test_strong_existing_context_is_preserved()
    test_legal_floor_drops_procedural_story_below_75()
    test_football_standout_prefers_grounded_passing_line()
    test_a45_is_polish_only_contract()
    print("PASS: A4.5 result copy polish + legal significance floor")

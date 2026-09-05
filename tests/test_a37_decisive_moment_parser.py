#!/usr/bin/env python3
"""A3.7 decisive-parser regressions retained under the A3.8 priority policy."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "refresh_sports_ticker.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a37", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def mlb_candidate():
    return {
        "candidateId": "cand-dodgers",
        "leagueHint": "MLB",
        "sportHint": "baseball",
        "typeHint": "RESULT",
        "occurredAt": "2026-09-04T02:10:00Z",
        "quality": 100,
        "metadata": {
            "matchId": 1614048,
            "homeTeam": "Los Angeles Dodgers",
            "awayTeam": "St. Louis Cardinals",
            "homeScore": 3,
            "awayScore": 2,
            "rawScore": {
                "away": {"innings": [1, 0, 1, 0, 0, 0, 0, 0, 0]},
                "home": {"innings": [0, 0, 0, 0, 1, 0, 0, 0, 2]},
                "current": "3 - 2",
            },
        },
    }


def test_mlb_walkoff_uses_inning_lines_and_real_play_result_despite_reset():
    candidate = mlb_candidate()
    detail = {
        "plays": [
            {
                "type": "Start Inning",
                "period": "Bottom 9th Inning",
                "score": {"away": 2, "home": 1},
                "description": "Bottom of the 9th inning",
            },
            {
                "type": "Play Result",
                "period": "Bottom 9th Inning",
                "score": {"away": 2, "home": 1},
                "batter": {"fullName": "Mookie Betts"},
                "description": "Betts walked.",
            },
            {
                "type": "Play Result",
                "period": "Bottom 9th Inning",
                "score": {"away": 2, "home": 3},
                "batter": {"fullName": "Teoscar Hernandez"},
                "description": "T. Hernández doubled to center, Betts scored and Edman scored.",
            },
            # Highlightly then starts another representation from the beginning.
            {
                "type": "Strike Looking",
                "period": "Top 1st Inning",
                "score": {"away": 0, "home": 0},
                "batter": {"fullName": "Jose Fermin"},
                "description": "Pitch 1 : Strike 1 Looking",
            },
        ]
    }
    result = mod._derive_baseball_decisive(candidate, detail)
    assert "WALK_OFF" in result["flags"], result
    assert result["decisivePlayer"] == "Teoscar Hernandez", result
    assert "walk-off" in result["headlineSeed"].lower(), result
    assert "doubled to center" in result["summarySeed"], result
    assert result["parserMode"] == "inning-lines", result


def test_mlb_segmented_stream_ignores_second_representation_reset():
    candidate = mlb_candidate()
    candidate["metadata"].pop("rawScore")
    detail = {
        "plays": [
            {
                "type": "Start Batter/Pitcher",
                "period": "Bottom 9th Inning",
                "score": {"away": 2, "home": 1},
                "batter": {"fullName": "Teoscar Hernandez"},
                "description": "Riley O'Brien pitches to Teoscar Hernandez",
            },
            {
                "type": "Play Result",
                "period": "Bottom 9th Inning",
                "score": {"away": 2, "home": 3},
                "batter": {"fullName": "Teoscar Hernandez"},
                "description": "T. Hernández doubled to center, Betts scored and Edman scored.",
            },
            {
                "type": "Strike Looking",
                "period": "Top 1st Inning",
                "score": {"away": 0, "home": 0},
                "description": "Pitch 1 : Strike 1 Looking",
            },
        ]
    }
    result = mod._derive_baseball_decisive(candidate, detail)
    assert "WALK_OFF" in result["flags"], result
    assert result["parserMode"] == "segmented-play-stream", result


def football_candidate(*, ranked=False, margin=1):
    return {
        "candidateId": "cand-colorado",
        "leagueHint": "NCAAF",
        "sportHint": "american football",
        "typeHint": "RESULT",
        "occurredAt": "2026-09-04T00:00:00Z",
        "quality": 96,
        "metadata": {
            "matchId": 567571,
            "scheduledAt": "2026-09-04T00:00:00.000Z",
            "homeTeam": "Georgia Tech Yellow Jackets",
            "awayTeam": "Colorado Buffaloes",
            "homeScore": 13,
            "awayScore": 14 if margin == 1 else 40,
            "rankedTeamInvolved": ranked,
        },
    }


def test_football_reads_event_plays_even_when_playdetails_exist():
    candidate = football_candidate()
    detail = {
        "events": [
            {
                "result": "Touchdown",
                "end": {"period": "4th Quarter", "clock": "0:37"},
                "description": "8 plays, 75 yards, 1:03",
                "playDetails": [
                    {
                        "period": 4,
                        "clock": "0:42",
                        "text": "(00:42) Julian Lewis pass complete to Charlie Williams for 20 yards, TOUCHDOWN",
                    }
                ],
                "plays": [
                    "(00:42) Julian Lewis pass complete to Charlie Williams for 20 yards, TOUCHDOWN",
                ],
            },
            {
                "result": "Blocked Field Goal",
                "end": {"period": "4th Quarter", "clock": "0:00"},
                "description": "4 plays, 48 yards, 0:37",
                # A3.6 only looked here and would miss the decisive simple play.
                "playDetails": [
                    {"period": 4, "clock": "0:03", "text": "Georgia Tech lines up for a 45-yard field goal"},
                ],
                "plays": [
                    "(00:03) Aidan Birr 45 yard field goal BLOCKED by Boo Carter as time expired",
                ],
            },
        ]
    }
    result = mod._derive_american_football_decisive(candidate, detail)
    assert "BLOCKED_KICK" in result["flags"], result
    assert "LAST_SECOND" in result["flags"], result
    assert "GAME_WINNER" in result["flags"], result
    assert "blocked" in result["headlineSeed"].lower(), result
    assert result["priorityFloor"] >= 82, result


def test_espn_summary_normalizes_drives_for_same_parser():
    summary = {
        "drives": {
            "previous": [
                {
                    "displayResult": "Touchdown",
                    "plays": [
                        {"text": "Julian Lewis pass complete to Charlie Williams for 20 yard touchdown", "period": {"number": 4}, "clock": {"displayValue": "0:42"}},
                    ],
                },
                {
                    "displayResult": "Blocked Field Goal",
                    "plays": [
                        {"text": "Aidan Birr 45 yard field goal blocked by Boo Carter as time expired", "period": {"number": 4}, "clock": {"displayValue": "0:00"}},
                    ],
                },
            ]
        }
    }
    detail = mod._espn_summary_to_detail(summary)
    result = mod._derive_american_football_decisive(football_candidate(), detail)
    assert "BLOCKED_KICK" in result["flags"], result
    assert "time expired" in result["summarySeed"].lower(), result


def test_close_score_alone_stays_below_story_driven_70s():
    close = football_candidate(ranked=False)
    close_enrichment = mod.derive_decisive_context(close, {}, [])
    assert close_enrichment["priorityFloor"] == 63, close_enrichment

    blowout = football_candidate(ranked=True, margin=27)
    # Ranked involvement alone gets only a small floor; it does not become a
    # top-tier result without a real story/decisive context.
    blowout["metadata"]["homeScore"] = 14
    blowout["metadata"]["awayScore"] = 41
    ranked_enrichment = mod.derive_decisive_context(blowout, {}, [])
    assert ranked_enrichment["priorityFloor"] == 66, ranked_enrichment
    assert close_enrichment["priorityFloor"] < 70
    assert ranked_enrichment["priorityFloor"] < 70


if __name__ == "__main__":
    test_mlb_walkoff_uses_inning_lines_and_real_play_result_despite_reset()
    test_mlb_segmented_stream_ignores_second_representation_reset()
    test_football_reads_event_plays_even_when_playdetails_exist()
    test_espn_summary_normalizes_drives_for_same_parser()
    test_close_score_alone_stays_below_story_driven_70s()
    print("PASS: A3.7 parser regressions under A3.8 priority policy")

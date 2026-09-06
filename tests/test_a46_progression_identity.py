#!/usr/bin/env python3
"""A4.6 progression dedupe, procedural legal, and strict event identity tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "refresh_sports_ticker_a46.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a46", PATH)
a46 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(a46)


def item(headline, text, entities, occurred, priority=75, kind="INJURY", freshness=""):
    return {
        "type": kind,
        "priority": priority,
        "headline": headline,
        "text": text,
        "freshnessBasis": freshness or text,
        "entities": entities,
        "occurredAt": occurred,
        "candidateIds": ["cand-" + str(abs(hash(headline)))],
    }


def row(obj, context="MLB"):
    return {"kind": "league", "context": context, "league": context, "item": obj}


def test_taillon_exit_is_superseded_by_il_update():
    old = row(item(
        "Jameson Taillon exits Blue Jays start with elbow discomfort",
        "Taillon left after two innings with right elbow discomfort.",
        ["Toronto Blue Jays", "Jameson Taillon"],
        "2026-09-05T16:18:54Z",
        82,
    ))
    new = row(item(
        "Jameson Taillon returns to IL with elbow inflammation",
        "Toronto placed Taillon on the 15-day injured list with elbow inflammation.",
        ["Jameson Taillon", "Toronto Blue Jays"],
        "2026-09-05T22:52:39Z",
        84,
    ))
    kept, drops = a46.collapse_progression_rows([old, new])
    assert len(kept) == 1
    assert kept[0]["item"]["headline"] == new["item"]["headline"]
    assert drops and "superseded" in drops[0]["reason"]


def test_ohtani_third_game_supersedes_second_game():
    second = row(item(
        "Shohei Ohtani misses another game with biceps, neck issues",
        "Ohtani missed a second straight game with biceps and neck issues.",
        ["Los Angeles Dodgers", "Shohei Ohtani"],
        "2026-09-05T13:48:34Z",
        78,
    ))
    third = row(item(
        "Dodgers hold Shohei Ohtani out for third straight game",
        "Ohtani remains out with neck and right-arm soreness for a third straight game.",
        ["Shohei Ohtani", "Los Angeles Dodgers"],
        "2026-09-05T22:12:37Z",
        78,
    ))
    kept, _ = a46.collapse_progression_rows([second, third])
    assert len(kept) == 1
    assert "third straight" in kept[0]["item"]["headline"].lower()


def test_same_team_different_players_do_not_collapse():
    a = row(item(
        "Yankees place Trent Grisham on IL with hamstring strain",
        "Grisham went on the IL with a hamstring strain.",
        ["New York Yankees", "Trent Grisham"],
        "2026-09-05T20:00:00Z",
    ))
    b = row(item(
        "Yankees rule Aaron Judge out with hamstring strain",
        "Judge was ruled out with a hamstring strain.",
        ["New York Yankees", "Aaron Judge"],
        "2026-09-05T21:00:00Z",
    ))
    kept, drops = a46.collapse_progression_rows([a, b])
    assert len(kept) == 2
    assert not drops


def test_same_player_distinct_injury_threads_do_not_collapse_without_cue_overlap():
    a = row(item(
        "Example Player exits with ankle injury",
        "Example Player left with an ankle sprain.",
        ["Example Team", "Example Player"],
        "2026-09-05T12:00:00Z",
    ))
    b = row(item(
        "Example Player evaluated for concussion",
        "Example Player entered concussion protocol.",
        ["Example Player", "Example Team"],
        "2026-09-05T18:00:00Z",
    ))
    kept, _ = a46.collapse_progression_rows([a, b])
    assert len(kept) == 2


def test_procedural_legal_is_dropped_even_above_priority_floor():
    procedural = item(
        "Tiger Woods plans to change not-guilty plea in DUI case",
        "Court documents say Woods plans to change his not-guilty plea.",
        ["Tiger Woods"],
        "2026-09-05T11:00:00Z",
        priority=77,
        kind="LEGAL",
    )
    material = item(
        "Example athlete acquitted in criminal case",
        "A jury acquitted the athlete Friday.",
        ["Example Athlete"],
        "2026-09-05T11:00:00Z",
        priority=80,
        kind="LEGAL",
    )
    ds = {
        "leagues": [],
        "specialEvents": [{"name": "Golf", "sport": "golf", "items": [procedural, material]}],
    }
    a46.drop_procedural_legal(ds)
    assert ds["specialEvents"][0]["items"] == [material]


def competitor(side, name, score, short=None, abbrev=None):
    team = {"displayName": name}
    if short:
        team["shortDisplayName"] = short
    if abbrev:
        team["abbreviation"] = abbrev
    return {"homeAway": side, "team": team, "score": str(score)}


def event(eid, home, away, hs, as_):
    return {
        "id": eid,
        "competitions": [{
            "competitors": [
                competitor("home", home, hs),
                competitor("away", away, as_),
            ]
        }],
    }


def candidate(home="Penn State Nittany Lions", away="Marshall Thundering Herd", hs=45, as_=0):
    return {
        "candidateId": "cand-pennstate",
        "metadata": {
            "homeTeam": home,
            "awayTeam": away,
            "homeScore": hs,
            "awayScore": as_,
        },
    }


def test_strict_event_match_rejects_wrong_game_and_selects_exact_game():
    wrong = event("wrong", "Iowa State Cyclones", "Kansas Jayhawks", 45, 0)
    right = event("right", "Penn State Nittany Lions", "Marshall Thundering Herd", 45, 0)
    sb = {"events": [wrong, right]}
    matched = a46._strict_match_espn_event(candidate(), sb)
    assert matched and matched["id"] == "right"


def test_strict_event_match_requires_score_when_candidate_has_score():
    wrong_score = event("wrong-score", "Penn State Nittany Lions", "Marshall Thundering Herd", 42, 0)
    assert a46._strict_match_espn_event(candidate(), {"events": [wrong_score]}) is None


def test_texas_does_not_match_texas_state_identity():
    cand = candidate("Texas Longhorns", "Texas State Bobcats", 59, 7)
    bad = event("bad", "Texas A&M Aggies", "Texas State Bobcats", 59, 7)
    good = event("good", "Texas Longhorns", "Texas State Bobcats", 59, 7)
    matched = a46._strict_match_espn_event(cand, {"events": [bad, good]})
    assert matched and matched["id"] == "good"


def test_summary_header_must_match_candidate():
    good_summary = {"header": {"competitions": event("x", "Penn State Nittany Lions", "Marshall Thundering Herd", 45, 0)["competitions"]}}
    bad_summary = {"header": {"competitions": event("x", "Iowa State Cyclones", "Kansas Jayhawks", 45, 0)["competitions"]}}
    assert a46._summary_matches_candidate(candidate(), good_summary)
    assert not a46._summary_matches_candidate(candidate(), bad_summary)



def test_patch_chain_injects_progression_dedupe_before_selector():
    class FakeA43:
        def __init__(self):
            self._dedupe_rows = lambda rows: (list(rows), [])

    fake_a43 = FakeA43()

    class FakeA44:
        def __init__(self):
            self._load_a43 = lambda: fake_a43

    fake_a44 = FakeA44()

    class FakeA45:
        PIPELINE_VERSION = "old"
        A45_EDITOR_ADDENDUM = "base"
        _fetch_ncaaf_summary = staticmethod(lambda *a, **k: (None, None, None))
        _drop_low_significance_legal = staticmethod(lambda normalized, run_log=None: normalized)
        _load_a44 = staticmethod(lambda: fake_a44)

    fake_a45 = FakeA45()
    a46._patch_a45(fake_a45)
    assert fake_a45.PIPELINE_VERSION == a46.PIPELINE_VERSION
    assert "STORY PROGRESSION" in fake_a45.A45_EDITOR_ADDENDUM
    loaded_a44 = fake_a45._load_a44()
    loaded_a43 = loaded_a44._load_a43()

    old = row(item(
        "Trent Grisham leaves game with hamstring discomfort",
        "Grisham left with hamstring discomfort.",
        ["New York Yankees", "Trent Grisham"],
        "2026-09-05T16:00:00Z",
        72,
    ))
    new = row(item(
        "Yankees place Trent Grisham on IL with hamstring strain",
        "New York placed Grisham on the injured list with a hamstring strain.",
        ["Trent Grisham", "New York Yankees"],
        "2026-09-05T20:00:00Z",
        75,
    ))
    kept, drops = loaded_a43._dedupe_rows([old, new])
    assert len(kept) == 1 and "place Trent Grisham on IL" in kept[0]["item"]["headline"]
    assert drops and "superseded" in drops[0]["reason"]

def test_a46_contract():
    assert a46.PIPELINE_VERSION == "A4.6-progression-identity"
    assert a46.PROGRESSION_WINDOW_HOURS == 18.0
    assert "BOTH teams" in a46.A46_EDITOR_ADDENDUM
    assert "30-35" in a46.A46_EDITOR_ADDENDUM


if __name__ == "__main__":
    test_taillon_exit_is_superseded_by_il_update()
    test_ohtani_third_game_supersedes_second_game()
    test_same_team_different_players_do_not_collapse()
    test_same_player_distinct_injury_threads_do_not_collapse_without_cue_overlap()
    test_procedural_legal_is_dropped_even_above_priority_floor()
    test_strict_event_match_rejects_wrong_game_and_selects_exact_game()
    test_strict_event_match_requires_score_when_candidate_has_score()
    test_texas_does_not_match_texas_state_identity()
    test_summary_header_must_match_candidate()
    test_patch_chain_injects_progression_dedupe_before_selector()
    test_a46_contract()
    print("PASS: A4.6 progression dedupe + strict NCAAF event identity")

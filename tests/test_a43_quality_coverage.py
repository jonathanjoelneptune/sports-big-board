#!/usr/bin/env python3
"""A4.3 semantic dedupe, coverage balance and live-card headline tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "refresh_sports_ticker_a43.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a43", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def item(n, headline, kind="RESULT", priority=65, entities=None, text=None, age=2.0):
    return {
        "rank": n,
        "candidateIds": [f"cand-{n:03d}"],
        "type": kind,
        "priority": priority,
        "headline": headline,
        "text": text or headline,
        "entities": entities or [],
        "occurredAt": "2026-09-05T12:00:00Z",
        "timePrecision": "exact",
        "ageHours": age,
        "freshnessBasis": f"{headline} on Sept. 5.",
        "status": "active",
        "sourceUrls": ["https://example.com"],
        "sources": [{"url": "https://example.com"}],
    }


def row(item_obj, context, kind="special", sport="Formula 1", state="special"):
    return {
        "kind": kind,
        "context": context,
        "event": context if kind == "special" else None,
        "league": context if kind == "league" else None,
        "sport": sport,
        "seasonState": state,
        "item": item_obj,
    }


def empty_dataset():
    return {
        "leagues": [
            {"league": league, "seasonState": state, "items": []}
            for league, state in [
                ("MLB", "active"), ("NFL", "preseason"), ("NBA", "offseason"),
                ("NHL", "offseason"), ("EPL", "active"), ("MLS", "active"),
                ("NCAAF", "active"),
            ]
        ],
        "specialEvents": [],
    }


def total(ds):
    return sum(len(g["items"]) for g in ds["leagues"]) + sum(
        len(e["items"]) for e in ds["specialEvents"]
    )


def test_gasly_duplicate_articles_collapse():
    a = row(item(
        1, "Gasly takes first career pole for Italian GP", kind="QUALIFYING", priority=82,
        entities=["Pierre Gasly", "Alpine", "Italian Grand Prix"],
        text="Pierre Gasly qualified first for the Italian Grand Prix."
    ), "Italian Grand Prix")
    b = row(item(
        2, "Gasly beats Russell to Italian GP pole", kind="QUALIFYING", priority=75,
        entities=["Pierre Gasly", "George Russell", "Italian Grand Prix"],
        text="Pierre Gasly took pole position ahead of George Russell."
    ), "Italian Grand Prix")
    assert mod._is_semantic_duplicate(a, b)
    kept, dropped = mod._dedupe_rows([a, b])
    assert len(kept) == 1 and len(dropped) == 1
    assert kept[0]["item"]["priority"] == 82



def test_distinct_mlb_doubleheader_games_do_not_collapse():
    a_item = item(
        1, "Cubs beat Cardinals 4-3 in opener", priority=63,
        entities=["Chicago Cubs", "St. Louis Cardinals"],
        text="Chicago beat St. Louis 4-3 in the first game."
    )
    a_item["occurredAt"] = "2026-09-05T16:00:00Z"
    b_item = item(
        2, "Cubs beat Cardinals 4-3 in nightcap", priority=63,
        entities=["Chicago Cubs", "St. Louis Cardinals"],
        text="Chicago beat St. Louis 4-3 in the second game."
    )
    b_item["occurredAt"] = "2026-09-05T21:00:00Z"
    a = row(a_item, "MLB", kind="league", sport="baseball", state="active")
    b = row(b_item, "MLB", kind="league", sport="baseball", state="active")
    assert not mod._is_semantic_duplicate(a, b)

def test_different_f1_story_is_not_duplicate():
    gasly = row(item(
        1, "Gasly takes first career pole for Italian GP", kind="QUALIFYING", priority=82,
        entities=["Pierre Gasly", "Italian Grand Prix"]
    ), "Italian Grand Prix")
    piastri = row(item(
        2, "Piastri gets three-place grid penalty at Italian GP", kind="DISCIPLINE", priority=72,
        entities=["Oscar Piastri", "Liam Lawson", "Italian Grand Prix"]
    ), "Italian Grand Prix")
    assert not mod._is_semantic_duplicate(gasly, piastri)


def test_serena_duplicate_result_collapses():
    a = row(item(
        1, "Serena and Venus Williams lose US Open return", priority=65,
        entities=["Serena Williams", "Venus Williams", "Hao-Ching Chan", "Maya Joint"],
        text="The Williams sisters lost a third-set tiebreak in women's doubles."
    ), "US Open", sport="tennis")
    b = row(item(
        2, "Serena and Venus Williams lose US Open opener", priority=65,
        entities=["Serena Williams", "Venus Williams", "Hao-Ching Chan", "Maya Joint"],
        text="Serena and Venus Williams were defeated in their first-round doubles match.", age=12
    ), "US Open", sport="tennis")
    assert mod._is_semantic_duplicate(a, b)


def test_generic_tennis_other_is_weak():
    r = row(item(
        1, "Alcaraz plans more breaks during tennis season", kind="OTHER", priority=65,
        entities=["Carlos Alcaraz"]
    ), "Tennis", sport="Tennis")
    assert mod._is_weak_generic_special(r)


def test_major_generic_tennis_injury_can_survive():
    r = row(item(
        1, "World No. 1 ruled out for season after knee surgery", kind="INJURY", priority=88,
        entities=["Example Player"]
    ), "Tennis", sport="Tennis")
    assert not mod._is_weak_generic_special(r)


def test_story_driven_draw_hook():
    assert mod._draw_has_story_hook({
        "headline": "Goalkeepers duel as NYCFC and Nashville draw 0-0",
        "text": "Brian Schwake and Matt Freese each kept the match scoreless.",
    })
    assert not mod._draw_has_story_hook({
        "headline": "Team A and Team B draw 0-0",
        "text": "The match ended scoreless.",
    })


def test_coverage_seed_prevents_mlb_monopoly():
    ds = empty_dataset()
    mlb = next(g for g in ds["leagues"] if g["league"] == "MLB")
    mls = next(g for g in ds["leagues"] if g["league"] == "MLS")
    epl = next(g for g in ds["leagues"] if g["league"] == "EPL")
    mlb["items"] = [
        item(i, f"MLB result {i} has useful grounded final score", priority=80 - i)
        for i in range(1, 13)
    ]
    mls["items"] = [item(100, "MLS goalkeeper duel produces scoreless draw", priority=62)]
    epl["items"] = [item(101, "Brighton first goal rescues late league draw", priority=64)]
    out = mod.apply_quality_budget(ds)
    assert mls["items"], "MLS coverage should survive abundant MLB supply"
    assert epl["items"], "EPL coverage should survive abundant MLB supply"
    assert len(mlb["items"]) <= mod.HARD_BASE_CONTEXT_CAP


def test_refill_builds_normalization_buffer():
    minimum, desired = mod._refill_targets(16, 25)
    assert minimum == 18, (minimum, desired)
    assert desired == 19, (minimum, desired)


def test_live_card_headline_contract_is_longer():
    assert mod.HEADLINE_TARGET_CHARS == 80
    assert mod.HEADLINE_MAX_CHARS == 96
    natural = "Travis Bazzana delivers walk-off as Cleveland Guardians beat Detroit 4-3"
    assert mod._compact_headline(natural) == natural
    very_long = (
        "A very long sports headline containing too much secondary context for even the larger "
        "two-line live Sports Big Board ticker card display area"
    )
    compact = mod._compact_headline(very_long)
    assert len(compact) <= 96


def test_budget_contract_unchanged():
    assert (mod.GLOBAL_HEADLINE_MIN, mod.GLOBAL_HEADLINE_TARGET, mod.GLOBAL_HEADLINE_MAX) == (30, 32, 35)


if __name__ == "__main__":
    test_gasly_duplicate_articles_collapse()
    test_distinct_mlb_doubleheader_games_do_not_collapse()
    test_different_f1_story_is_not_duplicate()
    test_serena_duplicate_result_collapses()
    test_generic_tennis_other_is_weak()
    test_major_generic_tennis_injury_can_survive()
    test_story_driven_draw_hook()
    test_coverage_seed_prevents_mlb_monopoly()
    test_refill_builds_normalization_buffer()
    test_live_card_headline_contract_is_longer()
    test_budget_contract_unchanged()
    print("PASS: A4.3 semantic dedupe + coverage balance + live-card headlines")

#!/usr/bin/env python3
"""A4 global 15-20 headline budget regression coverage."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "refresh_sports_ticker_a4.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a4", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def item(n, kind="RESULT", priority=65, age=2.0):
    return {
        "rank": n,
        "candidateIds": [f"cand-{n:03d}"],
        "type": kind,
        "priority": priority,
        "headline": f"Headline {n}",
        "text": f"Useful grounded detail for headline {n}.",
        "entities": [],
        "occurredAt": "2026-09-05T12:00:00Z",
        "timePrecision": "exact",
        "ageHours": age,
        "freshnessBasis": f"Headline {n} happened on Sept. 5.",
        "status": "active",
        "sourceUrls": ["https://example.com"],
        "sources": [],
    }


def empty_dataset():
    return {
        "leagues": [
            {"league": league, "seasonState": state, "items": []}
            for league, state in [
                ("MLB", "active"),
                ("NFL", "preseason"),
                ("NBA", "offseason"),
                ("NHL", "offseason"),
                ("EPL", "active"),
                ("MLS", "active"),
                ("NCAAF", "active"),
            ]
        ],
        "specialEvents": [],
    }


def total(dataset):
    return sum(len(g["items"]) for g in dataset["leagues"]) + sum(
        len(e["items"]) for e in dataset["specialEvents"]
    )


def test_budget_is_global_and_hard_caps_at_20():
    ds = empty_dataset()
    n = 1
    for group in ds["leagues"]:
        for _ in range(6):
            group["items"].append(item(n, priority=80 - (n % 9)))
            n += 1
    out = mod.apply_global_headline_budget(ds)
    assert total(out) == mod.GLOBAL_HEADLINE_TARGET, total(out)
    assert total(out) <= mod.GLOBAL_HEADLINE_MAX
    assert all(
        sum(1 for x in g["items"] if x["type"] == "RESULT") <= mod.GLOBAL_BASE_CONTEXT_CAP
        for g in out["leagues"]
    )


def test_budget_relaxes_context_caps_to_reach_15_when_only_one_league_has_supply():
    ds = empty_dataset()
    mlb = next(g for g in ds["leagues"] if g["league"] == "MLB")
    mlb["items"] = [item(i, priority=70 - (i % 5)) for i in range(1, 18)]
    out = mod.apply_global_headline_budget(ds)
    assert total(out) == mod.GLOBAL_HEADLINE_MIN, total(out)


def test_budget_never_pads_when_fewer_than_15_legitimate_items_exist():
    ds = empty_dataset()
    mlb = next(g for g in ds["leagues"] if g["league"] == "MLB")
    mlb["items"] = [item(i, priority=70) for i in range(1, 9)]
    out = mod.apply_global_headline_budget(ds)
    assert total(out) == 8


def test_low_significance_legal_story_is_removed():
    ds = empty_dataset()
    nhl = next(g for g in ds["leagues"] if g["league"] == "NHL")
    nhl["items"] = [
        item(1, kind="LEGAL", priority=70),
        item(2, kind="SIGNING", priority=78),
    ]
    out = mod.apply_global_headline_budget(ds)
    headlines = [x["headline"] for g in out["leagues"] for x in g["items"]]
    assert "Headline 1" not in headlines
    assert "Headline 2" in headlines


def test_special_events_share_same_global_budget():
    ds = empty_dataset()
    mlb = next(g for g in ds["leagues"] if g["league"] == "MLB")
    mlb["items"] = [item(i, priority=68) for i in range(1, 11)]
    ds["specialEvents"] = [
        {
            "name": "US Open (tennis)",
            "sport": "tennis",
            "items": [item(100 + i, kind="ADVANCEMENT", priority=75) for i in range(5)],
        },
        {
            "name": "Italian Grand Prix (Formula 1)",
            "sport": "Formula 1",
            "items": [item(200 + i, kind="QUALIFYING", priority=72) for i in range(5)],
        },
    ]
    out = mod.apply_global_headline_budget(ds)
    assert total(out) <= mod.GLOBAL_HEADLINE_MAX
    special_count = sum(len(e["items"]) for e in out["specialEvents"])
    assert special_count <= mod.GLOBAL_SPECIAL_TOTAL_CAP
    assert special_count > 0


def test_feed_rank_is_unique_and_global():
    ds = empty_dataset()
    for idx, group in enumerate(ds["leagues"][:4]):
        group["items"] = [item(idx * 10 + j, priority=75 - j) for j in range(1, 6)]
    out = mod.apply_global_headline_budget(ds)
    ranks = [
        x["feedRank"]
        for g in out["leagues"] for x in g["items"]
    ] + [
        x["feedRank"]
        for e in out["specialEvents"] for x in e["items"]
    ]
    assert sorted(ranks) == list(range(1, len(ranks) + 1)), ranks


if __name__ == "__main__":
    test_budget_is_global_and_hard_caps_at_20()
    test_budget_relaxes_context_caps_to_reach_15_when_only_one_league_has_supply()
    test_budget_never_pads_when_fewer_than_15_legitimate_items_exist()
    test_low_significance_legal_story_is_removed()
    test_special_events_share_same_global_budget()
    test_feed_rank_is_unique_and_global()
    print("PASS: A4 global Sports Ticker headline budget")

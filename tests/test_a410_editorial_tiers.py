#!/usr/bin/env python3
"""A4.10 sport-aware editorial tiers + same-outcome regressions."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "refresh_sports_ticker_a410.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a410", PATH)
a410 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(a410)


def item(kind, headline, text, entities, cid, priority=75):
    return {
        "candidateIds": [cid],
        "type": kind,
        "priority": priority,
        "headline": headline,
        "text": text,
        "freshnessBasis": text,
        "entities": entities,
        "status": "active",
    }


def test_editorial_tier_prompt_has_global_density_philosophy():
    prompt = a410.A410_EDITOR_ADDENDUM
    assert "TIER 1" in prompt and "TIER 2" in prompt and "TIER 3" in prompt and "TIER 4" in prompt
    assert "There is NO type-count penalty" in prompt
    assert "Seven genuinely great walk-offs/upsets/records" in prompt
    assert "routine IL/day-to-day injury update" in prompt
    assert "Do not use category quotas as a substitute for judgment" in prompt


def test_editorial_tier_prompt_covers_every_supported_sport_family():
    prompt = a410.A410_EDITOR_ADDENDUM
    for heading in [
        "MLB", "NFL", "NBA", "NHL", "EPL / MLS / SOCCER", "NCAAF",
        "TENNIS / GRAND SLAMS", "FORMULA 1", "UFC / MMA", "GOLF / MAJORS",
    ]:
        assert heading in prompt, heading


def test_tier_priority_bands_are_explicit():
    prompt = a410.A410_EDITOR_ADDENDUM
    assert "82-95" in prompt
    assert "72-81" in prompt
    assert "60-71" in prompt


def test_duplicate_gasly_pole_articles_still_collapse():
    first = item(
        "QUALIFYING",
        "Gasly takes first career pole for Italian Grand Prix",
        "Pierre Gasly delivered a major qualifying upset for Alpine at Monza.",
        ["Pierre Gasly", "Alpine"],
        "gasly-first",
        82,
    )
    second = item(
        "QUALIFYING",
        "Gasly beats Russell to pole for Italian Grand Prix",
        "Pierre Gasly secured pole after previously beating George Russell in an online chess game.",
        ["Pierre Gasly", "George Russell"],
        "gasly-second",
        82,
    )
    piastri = item(
        "DISCIPLINE",
        "Piastri drops three places on Italian GP grid",
        "Oscar Piastri received a three-place penalty for impeding Liam Lawson.",
        ["Oscar Piastri", "Liam Lawson"],
        "piastri",
        76,
    )
    normalized = {
        "leagues": [],
        "specialEvents": [{
            "name": "Italian Grand Prix (Formula 1)",
            "sport": "Formula 1",
            "items": [first, second, piastri],
        }],
    }
    log = {"pipeline": {}}
    out = a410.collapse_special_event_outcomes(normalized, log)
    ids = [x["candidateIds"][0] for x in out["specialEvents"][0]["items"]]
    assert ids == ["gasly-first", "piastri"], ids
    assert len(log["pipeline"]["a410SpecialOutcomeDrops"]) == 1


def test_different_special_event_development_is_not_collapsed():
    pole = item(
        "QUALIFYING", "Gasly takes pole at Monza",
        "Pierre Gasly qualified first for the Italian Grand Prix.",
        ["Pierre Gasly"], "pole", 82,
    )
    penalty = item(
        "DISCIPLINE", "Gasly receives post-qualifying penalty",
        "Pierre Gasly was penalized after qualifying.",
        ["Pierre Gasly"], "penalty", 82,
    )
    normalized = {
        "leagues": [],
        "specialEvents": [{
            "name": "Italian Grand Prix",
            "sport": "Formula 1",
            "items": [pole, penalty],
        }],
    }
    out = a410.collapse_special_event_outcomes(normalized)
    assert len(out["specialEvents"][0]["items"]) == 2


def test_no_deterministic_injury_type_cap_exists():
    # A4.10 deliberately leaves type density to the tier-aware editor. The only
    # deterministic selector addition is duplicate same-event outcome isolation.
    assert not hasattr(a410, "enforce_injury_diversity")
    assert "MAX_ROUTINE_INJURIES_PER_LEAGUE" not in vars(a410)


def test_stable_launcher_discovers_a410_or_newer_and_yaml_is_unchanged():
    launcher_path = ROOT / "tools" / "refresh_sports_ticker_current.py"
    spec2 = importlib.util.spec_from_file_location("ticker_current_launcher_a410", launcher_path)
    launcher = importlib.util.module_from_spec(spec2)
    assert spec2 and spec2.loader
    spec2.loader.exec_module(launcher)

    name = launcher.discover_latest().name
    assert name.startswith("refresh_sports_ticker_a") and name.endswith(".py"), name
    version = int(name.removeprefix("refresh_sports_ticker_a").removesuffix(".py"))
    assert version >= 410, name

    workflow = (ROOT / ".github" / "workflows" / "sports-ticker-refresh.yml").read_text()
    assert "python3 tests/test_sports_ticker_current.py" in workflow
    assert "python3 tools/refresh_sports_ticker_current.py" in workflow
    assert "a410" not in workflow.lower()


if __name__ == "__main__":
    test_editorial_tier_prompt_has_global_density_philosophy()
    test_editorial_tier_prompt_covers_every_supported_sport_family()
    test_tier_priority_bands_are_explicit()
    test_duplicate_gasly_pole_articles_still_collapse()
    test_different_special_event_development_is_not_collapsed()
    test_no_deterministic_injury_type_cap_exists()
    test_stable_launcher_discovers_a410_or_newer_and_yaml_is_unchanged()
    print("PASS: A4.10 sport-aware editorial tiers + same-outcome dedupe + no YAML")

#!/usr/bin/env python3
"""A4.11 tier calibration + surface copy regressions."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "refresh_sports_ticker_a411.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a411", PATH)
a411 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(a411)


def test_tier_assignment_is_mandatory_before_priority():
    prompt = a411.A411_EDITOR_ADDENDUM
    assert "Assign Tier 1, Tier 2, Tier 3, or Tier 4" in prompt
    assert "Assign priority ONLY inside that tier's band" in prompt
    assert "Freshness determines eligibility, not importance" in prompt
    assert "refill pass MUST use the same tier classification" in prompt


def test_routine_injury_and_practice_ceiling_is_explicit():
    prompt = a411.A411_EDITOR_ADDENDUM
    assert "routine 10/15-day IL move" in prompt
    assert "priority <=71" in prompt
    assert "missing games with day-to-day soreness" in prompt
    assert "Routine practice contact" in prompt
    assert "no damage" in prompt and "grid effect" in prompt


def test_generic_result_cannot_float_to_tier2_without_hook():
    prompt = a411.A411_EDITOR_ADDENDUM
    assert "generic final score" in prompt
    assert "Close game" in prompt
    assert "Identify the hero/decisive play" in prompt


def test_status_only_freshness_is_detected():
    for value in [
        "End of 4th quarter.",
        "End of OT.",
        "Final.",
        "Full time.",
        "Game ended.",
    ]:
        assert a411._generic_freshness(value), value
    assert not a411._generic_freshness(
        "Michigan beat Western Michigan 13-12 after a late score."
    )


def test_surface_copy_repairs_michigan_style_freshness_and_leading_dash():
    item = {
        "candidateIds": ["michigan"],
        "type": "RESULT",
        "priority": 78,
        "headline": "Late score lifts Michigan past Western Michigan 13-12",
        "text": "— Bryce Underwood threw for 170 yards and 1 TD as Michigan beat Western Michigan 13-12.",
        "freshnessBasis": "End of 4th quarter.",
        "entities": ["Michigan Wolverines", "Western Michigan Broncos", "Bryce Underwood"],
    }
    normalized = {
        "leagues": [{"league": "NCAAF", "seasonState": "active", "items": [item]}],
        "specialEvents": [],
    }
    log = {"pipeline": {}}
    out = a411.polish_surface_copy(normalized, log)
    fixed = out["leagues"][0]["items"][0]
    assert not fixed["text"].startswith("—")
    assert fixed["freshnessBasis"] == fixed["text"]
    assert log["pipeline"]["a411SurfaceCopyPolish"]["updatedCount"] == 1


def test_clean_freshness_is_preserved():
    item = {
        "candidateIds": ["citadel"],
        "type": "UPSET",
        "headline": "The Citadel beats Charlotte in 3OT",
        "text": "Gavin Garcia ran for 137 yards and three touchdowns.",
        "freshnessBasis": "The Citadel beat Charlotte 43-41 in triple overtime.",
    }
    normalized = {
        "leagues": [{"league": "NCAAF", "seasonState": "active", "items": [item]}],
        "specialEvents": [],
    }
    out = a411.polish_surface_copy(normalized)
    fixed = out["leagues"][0]["items"][0]
    assert fixed["freshnessBasis"] == "The Citadel beat Charlotte 43-41 in triple overtime."


def test_stable_launcher_discovers_a411_or_newer_without_yaml_change():
    launcher_path = ROOT / "tools" / "refresh_sports_ticker_current.py"
    spec2 = importlib.util.spec_from_file_location("ticker_current_launcher_a411", launcher_path)
    launcher = importlib.util.module_from_spec(spec2)
    assert spec2 and spec2.loader
    spec2.loader.exec_module(launcher)

    name = launcher.discover_latest().name
    assert name.startswith("refresh_sports_ticker_a") and name.endswith(".py"), name
    version = int(name.removeprefix("refresh_sports_ticker_a").removesuffix(".py"))
    assert version >= 411, name

    workflow = (ROOT / ".github" / "workflows" / "sports-ticker-refresh.yml").read_text()
    assert "python3 tests/test_sports_ticker_current.py" in workflow
    assert "python3 tools/refresh_sports_ticker_current.py" in workflow
    assert "a411" not in workflow.lower()


if __name__ == "__main__":
    test_tier_assignment_is_mandatory_before_priority()
    test_routine_injury_and_practice_ceiling_is_explicit()
    test_generic_result_cannot_float_to_tier2_without_hook()
    test_status_only_freshness_is_detected()
    test_surface_copy_repairs_michigan_style_freshness_and_leading_dash()
    test_clean_freshness_is_preserved()
    test_stable_launcher_discovers_a411_or_newer_without_yaml_change()
    print("PASS: A4.11 mandatory tier calibration + surface copy hygiene + no YAML")

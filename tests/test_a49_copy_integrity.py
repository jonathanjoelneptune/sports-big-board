#!/usr/bin/env python3
"""A4.9 grounded result-copy integrity regressions."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "refresh_sports_ticker_a49.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a49", PATH)
a49 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(a49)

RAW_CITADEL = (
    "(00:00) Shotgun #8 N.Billoups rush left for 2 yards gain to the CLT00 "
    "TOUCHDOWN, clock 00:00 #8 N.Billoups rush attempt failed Timeout Charlotte, "
    "clock 15:00 #89 W.Hobgood pass attempt Successful"
)

FUSED_SUMMARY = (
    "Gavin Garcia rushed for 137 yards and three touchdowns as The Citadel beat "
    "Charlotte 43-41 in triple overtime on Saturday in the 49ers' season opener."
)


def test_raw_football_play_by_play_is_detected():
    assert a49._looks_like_raw_structured_play(RAW_CITADEL)
    assert not a49._looks_like_raw_structured_play(
        "Gavin Garcia rushed for 137 yards and three touchdowns as The Citadel won 43-41."
    )


def test_fused_summary_is_unpacked_and_raw_metadata_choice_removed():
    class FakeA45:
        @staticmethod
        def _looks_like_raw_play(value):
            return a49._looks_like_raw_structured_play(value)

    candidate = {
        "candidateId": "citadel",
        "title": "The Citadel Bulldogs beat Charlotte 49ers 43-41",
        "summary": "Highlightly final: The Citadel Bulldogs 43, Charlotte 49ers 41.",
        "metadata": {
            "fusedContext": [{
                "candidateId": "espn-citadel",
                "providers": ["ESPN"],
                "title": "Gavin Garcia rushes for 3 TDs to lead The Citadel past Charlotte 43-41 in 3OT",
                "summary": "— " + FUSED_SUMMARY,
            }]
        },
    }
    base = [
        ("decisive-moment", RAW_CITADEL),
        ("fused-context", "{'candidateId': 'espn-citadel', 'summary': 'bad dict repr'}"),
    ]
    choices = a49.augment_candidate_detail_choices(FakeA45, {}, candidate, base)
    texts = [text for _, text in choices]
    assert FUSED_SUMMARY in texts, choices
    assert all("Highlightly final:" not in text for text in texts)
    assert all("candidateId" not in text for text in texts)
    assert all(not a49._looks_like_raw_structured_play(text) for text in texts)


def test_raw_citadel_text_and_freshness_are_replaced_with_grounded_summary():
    class FakeA45:
        @staticmethod
        def _looks_like_raw_play(value):
            return a49._looks_like_raw_structured_play(value)

        @staticmethod
        def _best_grounded_detail(item, candidate):
            return "espn-fused-summary", FUSED_SUMMARY

    item = {
        "candidateIds": ["citadel"],
        "type": "UPSET",
        "priority": 90,
        "headline": "Late score lifts The Citadel past Charlotte 43-41 in 3OT",
        "text": RAW_CITADEL,
        "freshnessBasis": RAW_CITADEL,
        "entities": ["The Citadel Bulldogs", "Charlotte 49ers", "Gavin Garcia"],
    }
    normalized = {
        "leagues": [{"league": "NCAAF", "seasonState": "active", "items": [item]}],
        "specialEvents": [],
    }
    candidate = {
        "candidateId": "citadel",
        "metadata": {"fusedContext": [{"providers": ["ESPN"], "summary": FUSED_SUMMARY}]},
    }
    log = {"pipeline": {}}
    out = a49.sanitize_grounded_copy(FakeA45, normalized, [candidate], log)
    fixed = out["leagues"][0]["items"][0]
    assert fixed["text"] == FUSED_SUMMARY
    assert fixed["freshnessBasis"] == FUSED_SUMMARY
    assert "Shotgun" not in fixed["text"]
    assert log["pipeline"]["a49CopyIntegrity"]["updatedCount"] == 1


def test_clean_result_copy_is_left_unchanged():
    class FakeA45:
        @staticmethod
        def _looks_like_raw_play(value):
            return False

    text = "Kamari Moulton ran for 183 yards and two touchdowns in Iowa's 40-0 win."
    item = {
        "candidateIds": ["iowa"],
        "type": "RESULT",
        "headline": "No. 22 Iowa blanks Northern Illinois behind Moulton",
        "text": text,
        "freshnessBasis": text,
    }
    normalized = {
        "leagues": [{"league": "NCAAF", "seasonState": "active", "items": [item]}],
        "specialEvents": [],
    }
    out = a49.sanitize_grounded_copy(FakeA45, normalized, [{"candidateId": "iowa"}])
    fixed = out["leagues"][0]["items"][0]
    assert fixed["text"] == text
    assert fixed["freshnessBasis"] == text


def test_stable_launcher_auto_discovers_a49_without_yaml_change():
    launcher_path = ROOT / "tools" / "refresh_sports_ticker_current.py"
    spec2 = importlib.util.spec_from_file_location("ticker_current_launcher_a49", launcher_path)
    launcher = importlib.util.module_from_spec(spec2)
    assert spec2 and spec2.loader
    spec2.loader.exec_module(launcher)
    assert launcher.discover_latest().name == "refresh_sports_ticker_a49.py"

    workflow = (ROOT / ".github" / "workflows" / "sports-ticker-refresh.yml").read_text()
    assert "python3 tests/test_sports_ticker_current.py" in workflow
    assert "python3 tools/refresh_sports_ticker_current.py" in workflow
    assert "a49" not in workflow.lower()


def test_stable_test_runner_discovers_a49_regression():
    runner_path = ROOT / "tests" / "test_sports_ticker_current.py"
    spec3 = importlib.util.spec_from_file_location("ticker_current_tests_a49", runner_path)
    runner = importlib.util.module_from_spec(spec3)
    assert spec3 and spec3.loader
    spec3.loader.exec_module(runner)
    names = [path.name for path in runner.discover_tests()]
    assert "test_a49_copy_integrity.py" in names, names


if __name__ == "__main__":
    test_raw_football_play_by_play_is_detected()
    test_fused_summary_is_unpacked_and_raw_metadata_choice_removed()
    test_raw_citadel_text_and_freshness_are_replaced_with_grounded_summary()
    test_clean_result_copy_is_left_unchanged()
    test_stable_launcher_auto_discovers_a49_without_yaml_change()
    test_stable_test_runner_discovers_a49_regression()
    print("PASS: A4.9 grounded copy integrity + stable no-YAML entrypoints")

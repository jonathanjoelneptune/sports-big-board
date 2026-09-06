#!/usr/bin/env python3
"""A4.8 pre-budget identity + editorial progression regressions."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "refresh_sports_ticker_a48.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a48", PATH)
a48 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(a48)


def ticker_item(
    *,
    kind: str,
    headline: str,
    text: str,
    entities: list[str],
    occurred: str,
    priority: int,
    cid: str,
    feed_rank: int | None = None,
):
    item = {
        "candidateIds": [cid],
        "type": kind,
        "priority": priority,
        "headline": headline,
        "text": text,
        "freshnessBasis": text,
        "entities": entities,
        "occurredAt": occurred,
        "status": "active",
    }
    if feed_rank is not None:
        item["feedRank"] = feed_rank
    return item


def normalized(items, special=None):
    return {
        "leagues": [{"league": "MLB", "seasonState": "active", "items": items}],
        "specialEvents": list(special or []),
    }


def test_same_game_milestone_beats_streak_duplicate():
    milestone = ticker_item(
        kind="MILESTONE",
        headline="Haaland reaches 300 club goals as City stay perfect",
        text="Erling Haaland scored his 300th club goal in Manchester City's 1-0 win over Coventry.",
        entities=["Manchester City", "Coventry City", "Erling Haaland"],
        occurred="2026-09-05T21:58:59Z",
        priority=82,
        cid="haaland-milestone",
    )
    streak = ticker_item(
        kind="STREAK",
        headline="Haaland header keeps Man City perfect after 1-0 win",
        text="Erling Haaland scored the only goal as Manchester City beat Coventry City 1-0.",
        entities=["Manchester City", "Coventry City", "Erling Haaland"],
        occurred="2026-09-05T16:12:48Z",
        priority=73,
        cid="haaland-result",
    )
    log = {"pipeline": {}}
    out = a48.collapse_editorial_progressions(normalized([milestone, streak]), log)
    kept = out["leagues"][0]["items"]
    assert kept == [milestone], kept
    drops = log["pipeline"]["a48EditorialProgressionDrops"]
    assert len(drops) == 1 and "same-game cross-type" in drops[0]["reason"], drops


def test_independent_injury_from_same_game_is_not_collapsed():
    record = ticker_item(
        kind="RECORD",
        headline="Haaland reaches scoring record in City's 1-0 win",
        text="Erling Haaland set a record in Manchester City's 1-0 win over Coventry City.",
        entities=["Manchester City", "Coventry City", "Erling Haaland"],
        occurred="2026-09-05T21:58:59Z",
        priority=82,
        cid="record",
    )
    injury = ticker_item(
        kind="INJURY",
        headline="Haaland suffers ankle injury in City's 1-0 win",
        text="Erling Haaland left Manchester City's 1-0 win over Coventry City with an ankle injury.",
        entities=["Manchester City", "Coventry City", "Erling Haaland"],
        occurred="2026-09-05T21:59:30Z",
        priority=82,
        cid="injury",
    )
    out = a48.collapse_editorial_progressions(normalized([record, injury]))
    assert len(out["leagues"][0]["items"]) == 2


def test_newer_standings_state_supersedes_old_same_race_state():
    old = ticker_item(
        kind="STANDINGS",
        headline="Braves extend NL East lead to five games with 5-2 win",
        text="Atlanta beat Philadelphia 5-2 to extend its NL East lead to five games.",
        entities=["Atlanta Braves", "Philadelphia Phillies", "Chris Sale"],
        occurred="2026-09-05T01:27:29Z",
        priority=78,
        cid="old-standings",
    )
    new = ticker_item(
        kind="STANDINGS",
        headline="Phillies close NL East gap with 4-2 win over Braves",
        text="Philadelphia beat Atlanta 4-2 to move within four games in the NL East.",
        entities=["Philadelphia Phillies", "Atlanta Braves", "Zack Wheeler", "Kyle Schwarber"],
        occurred="2026-09-06T00:38:30Z",
        priority=76,
        cid="new-standings",
    )
    out = a48.collapse_editorial_progressions(normalized([old, new]))
    kept = out["leagues"][0]["items"]
    assert kept == [new], kept


def test_different_standings_races_are_not_collapsed():
    east = ticker_item(
        kind="STANDINGS",
        headline="Phillies close NL East gap",
        text="Philadelphia moved within four games in the NL East.",
        entities=["Philadelphia Phillies", "Atlanta Braves"],
        occurred="2026-09-06T00:38:30Z",
        priority=76,
        cid="east",
    )
    wild = ticker_item(
        kind="STANDINGS",
        headline="Phillies strengthen wild card position",
        text="Philadelphia strengthened its wild card position against Atlanta.",
        entities=["Philadelphia Phillies", "Atlanta Braves"],
        occurred="2026-09-06T00:40:00Z",
        priority=76,
        cid="wild",
    )
    out = a48.collapse_editorial_progressions(normalized([east, wild]))
    assert len(out["leagues"][0]["items"]) == 2


def test_reindex_closes_section_and_feed_rank_gaps():
    a = ticker_item(
        kind="RESULT", headline="A", text="A result.", entities=["A", "B"],
        occurred="2026-09-06T00:00:00Z", priority=70, cid="a", feed_rank=1,
    )
    b = ticker_item(
        kind="RESULT", headline="B", text="B result.", entities=["C", "D"],
        occurred="2026-09-06T00:01:00Z", priority=69, cid="b", feed_rank=3,
    )
    a["rank"] = 1
    b["rank"] = 3
    sp1 = ticker_item(
        kind="QUALIFYING", headline="Pole", text="Pole at Monza.", entities=["Driver"],
        occurred="2026-09-06T00:02:00Z", priority=80, cid="sp1", feed_rank=5,
    )
    sp2 = ticker_item(
        kind="QUALIFYING", headline="Penalty", text="Penalty at Monza.", entities=["Driver 2"],
        occurred="2026-09-06T00:03:00Z", priority=75, cid="sp2", feed_rank=7,
    )
    sp1["rank"] = 1
    sp2["rank"] = 3
    out = a48.reindex_output(normalized([a, b], [{"name": "Italian Grand Prix", "sport": "Formula 1", "items": [sp1, sp2]}]))
    assert [x["rank"] for x in out["leagues"][0]["items"]] == [1, 2]
    assert [x["rank"] for x in out["specialEvents"][0]["items"]] == [1, 2]
    feed = sorted(x["feedRank"] for x in [a, b, sp1, sp2])
    assert feed == [1, 2, 3, 4], feed


def test_stable_launcher_auto_discovers_a48():
    launcher_path = ROOT / "tools" / "refresh_sports_ticker_current.py"
    spec2 = importlib.util.spec_from_file_location("ticker_current_launcher", launcher_path)
    launcher = importlib.util.module_from_spec(spec2)
    assert spec2 and spec2.loader
    spec2.loader.exec_module(launcher)
    assert launcher.discover_latest().name == "refresh_sports_ticker_a48.py"


def test_a48_identity_gate_runs_before_global_budget_with_current_candidates():
    calls = []

    class FakeA47:
        @staticmethod
        def _patch_a45(a45, a46):
            return None

        @staticmethod
        def enforce_output_identity(normalized, candidates, run_log=None):
            calls.append(("identity", [c.get("candidateId") for c in candidates]))
            # Remove a sentinel bad item before the budget sees it.
            normalized["leagues"][0]["items"] = [
                x for x in normalized["leagues"][0]["items"]
                if x.get("headline") != "BAD"
            ]
            return normalized

    class FakeA42:
        PIPELINE_VERSION = "old"

        def __init__(self):
            self.apply_global_headline_budget = self._budget
            self._configure_core = self._configure

        @staticmethod
        def _budget(normalized, run_log=None):
            calls.append(("budget", [x.get("headline") for x in normalized["leagues"][0]["items"]]))
            return normalized

        def _configure(self, core):
            # Model the real A4.2 normalize closure: normalized data is passed
            # through the module-global budget during normalize_model_output.
            core.normalize_model_output = lambda model_output, candidates, generated_at, run_log: self.apply_global_headline_budget(model_output, run_log)

    class FakeA43:
        PIPELINE_VERSION = "old"

        def __init__(self, a42):
            self.a42 = a42
            self._patch_a42 = lambda a42_obj: None

    class FakeA44:
        PIPELINE_VERSION = "old"

        def __init__(self, a43):
            self.a43 = a43
            self._patch_a43 = lambda a43_obj: a43_obj._patch_a42(a43_obj.a42)

    class FakeA45:
        PIPELINE_VERSION = "old"
        A45_EDITOR_ADDENDUM = ""

        def __init__(self, a44):
            self.a44 = a44
            self._load_a44 = lambda: self.a44

    class Core:
        EDITOR_INSTRUCTIONS = ""

        @staticmethod
        def initial_run_log(generated_at, cutoff, model):
            return {"pipeline": {}, "configuration": {}}

    a42 = FakeA42()
    a43 = FakeA43(a42)
    a44 = FakeA44(a43)
    a45 = FakeA45(a44)
    a47 = FakeA47()
    a48._patch_a45(a45, object(), a47)
    loaded_a44 = a45._load_a44()
    loaded_a44._patch_a43(a43)
    a43._patch_a42(a42)
    core = Core()
    a42._configure_core(core)

    good = ticker_item(
        kind="RESULT", headline="GOOD", text="Good result.", entities=["A", "B"],
        occurred="2026-09-06T00:00:00Z", priority=70, cid="good",
    )
    bad = ticker_item(
        kind="RESULT", headline="BAD", text="Bad result.", entities=["A", "B"],
        occurred="2026-09-06T00:01:00Z", priority=70, cid="bad",
    )
    payload = normalized([good, bad])
    candidates = [{"candidateId": "good"}, {"candidateId": "bad"}]
    core.normalize_model_output(payload, candidates, "now", {"pipeline": {}})
    assert calls[0] == ("identity", ["good", "bad"]), calls
    assert calls[1] == ("budget", ["GOOD"]), calls


def test_workflow_is_now_version_agnostic():
    workflow = (ROOT / ".github" / "workflows" / "sports-ticker-refresh.yml").read_text()
    assert "python3 tests/test_sports_ticker_current.py" in workflow
    assert "python3 tools/refresh_sports_ticker_current.py" in workflow
    assert "refresh_sports_ticker_a48.py" not in workflow
    assert "test_a48_editorial_progression.py" not in workflow


if __name__ == "__main__":
    test_same_game_milestone_beats_streak_duplicate()
    test_independent_injury_from_same_game_is_not_collapsed()
    test_newer_standings_state_supersedes_old_same_race_state()
    test_different_standings_races_are_not_collapsed()
    test_reindex_closes_section_and_feed_rank_gaps()
    test_stable_launcher_auto_discovers_a48()
    test_a48_identity_gate_runs_before_global_budget_with_current_candidates()
    test_workflow_is_now_version_agnostic()
    print("PASS: A4.8 pre-budget identity + editorial progression + stable launcher")

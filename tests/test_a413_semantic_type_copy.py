#!/usr/bin/env python3
"""A4.13 semantic type + copy-integrity regressions."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "refresh_sports_ticker_a413.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a413", PATH)
a413 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(a413)

a412 = a413._load_a412()


def item(kind, headline, text, cid="x", freshness=None):
    return {
        "candidateIds": [cid],
        "type": kind,
        "priority": 80,
        "headline": headline,
        "text": text,
        "freshnessBasis": freshness or text,
        "entities": [],
        "status": "active",
    }


def test_cerundolo_rank_order_restores_upset():
    row = item(
        "RESULT",
        "No. 24 Cerundolo rallies from two sets down to stun Fritz",
        "No. 24 seed Francisco Cerundolo defeated No. 9 seed Taylor Fritz in five sets.",
        "cerundolo",
    )
    # Source intentionally mentions the higher-ranked loser first, reproducing
    # the A4.12 ordering bug.
    candidate = {
        "candidateId": "cerundolo",
        "title": "Taylor Fritz loses to Francisco Cerundolo",
        "summary": "No. 9 seed Taylor Fritz fell to No. 24 seed Francisco Cerundolo.",
    }
    grounded, reason = a413.objective_upset_evidence(a412, row, [candidate])
    assert grounded, reason
    normalized = {"leagues": [], "specialEvents": [{"name": "US Open", "items": [row]}]}
    out = a413.normalize_semantic_types(a412, normalized, [candidate])
    assert out["specialEvents"][0]["items"][0]["type"] == "UPSET"


def test_ranked_favorite_surviving_unranked_team_stays_result():
    row = item(
        "RESULT",
        "Michigan wins on second-chance Hail Mary, 13-12",
        "No. 16 Michigan beat Western Michigan on a 47-yard touchdown pass.",
        "michigan",
    )
    candidate = {
        "candidateId": "michigan",
        "metadata": {
            "homeScore": 13,
            "awayScore": 12,
            "homeRank": 16,
            "awayRank": None,
            "homeFbs": "Michigan Wolverines",
            "awayFbs": "Western Michigan Broncos",
        },
    }
    grounded, _ = a413.objective_upset_evidence(a412, row, [candidate])
    assert not grounded
    normalized = {"leagues": [{"league": "NCAAF", "items": [row]}], "specialEvents": []}
    out = a413.normalize_semantic_types(a412, normalized, [candidate])
    assert out["leagues"][0]["items"][0]["type"] == "RESULT"


def test_structured_non_fbs_winner_over_fbs_promotes_to_upset():
    row = item("RESULT", "The Citadel edges Charlotte 43-41 in 3OT", "The Citadel won in triple overtime.", "citadel")
    candidate = {
        "candidateId": "citadel",
        "metadata": {
            "homeScore": 43,
            "awayScore": 41,
            "homeRank": None,
            "awayRank": None,
            "homeFbs": None,
            "awayFbs": "Charlotte 49ers",
        },
    }
    grounded, reason = a413.objective_upset_evidence(a412, row, [candidate])
    assert grounded, reason


def test_piastri_grid_penalty_becomes_discipline():
    row = item(
        "QUALIFYING",
        "Piastri drops to sixth after Italian GP grid penalty",
        "Oscar Piastri was penalized three places for impeding Liam Lawson during Q2.",
        "piastri",
    )
    normalized = {"leagues": [], "specialEvents": [{"name": "Italian Grand Prix", "items": [row]}]}
    out = a413.normalize_semantic_types(a412, normalized, [])
    assert out["specialEvents"][0]["items"][0]["type"] == "DISCIPLINE"


def test_gasly_pole_remains_qualifying():
    row = item(
        "QUALIFYING",
        "Gasly takes first career pole at Italian Grand Prix",
        "Pierre Gasly claimed pole at Monza.",
        "gasly",
    )
    normalized = {"leagues": [], "specialEvents": [{"name": "Italian Grand Prix", "items": [row]}]}
    out = a413.normalize_semantic_types(a412, normalized, [])
    assert out["specialEvents"][0]["items"][0]["type"] == "QUALIFYING"


def test_raw_pitch_feed_is_replaced_by_natural_freshness():
    row = item(
        "RESULT",
        "McLain's homer lifts Reds past Brewers, 5-3",
        "Pitch 3 : Ball In Play to put Cincinnati Reds ahead for good in the 7th.",
        "mclain",
        "Cincinnati beat Milwaukee 5-3 after Matt McLain's seventh-inning homer broke the tie.",
    )
    normalized = {"leagues": [{"league": "MLB", "items": [row]}], "specialEvents": []}
    log = {"pipeline": {}}
    out = a413.sanitize_baseball_pitch_copy(normalized, log)
    fixed = out["leagues"][0]["items"][0]
    assert fixed["text"].startswith("Cincinnati beat Milwaukee 5-3")
    assert "Pitch 3" not in fixed["text"]
    assert log["pipeline"]["a413CopyCorrections"]


def test_clean_copy_is_unchanged():
    text = "Riley Greene had four hits and four RBIs in Detroit's 6-0 win."
    row = item("RESULT", "Greene powers Tigers past Guardians", text)
    normalized = {"leagues": [{"league": "MLB", "items": [row]}], "specialEvents": []}
    out = a413.sanitize_baseball_pitch_copy(normalized)
    assert out["leagues"][0]["items"][0]["text"] == text



def test_text_is_primary_display_copy_and_headline_is_preserved():
    row = item(
        "RESULT",
        "Short compact headline",
        "Matt McLain broke a seventh-inning tie with a home run as Cincinnati beat Milwaukee 5-3.",
        "display",
    )
    normalized = {"leagues": [{"league": "MLB", "items": [row]}], "specialEvents": []}
    out = a413.promote_primary_display_copy(normalized)
    fixed = out["leagues"][0]["items"][0]
    assert fixed["text"].startswith("Matt McLain broke")
    assert fixed["headline"] == "Short compact headline"


def test_headline_dependent_second_line_falls_back_to_standalone_freshness():
    row = item(
        "SIGNING",
        "Harrison Smith returns to Vikings for a 15th season",
        "The veteran safety agreed to a one-year deal worth $12.25 million.",
        "smith",
        "Harrison Smith agreed to a one-year, $12.25 million deal with Minnesota Saturday.",
    )
    normalized = {"leagues": [{"league": "NFL", "items": [row]}], "specialEvents": []}
    log = {"pipeline": {}}
    out = a413.promote_primary_display_copy(normalized, log)
    fixed = out["leagues"][0]["items"][0]
    assert fixed["text"].startswith("Harrison Smith agreed")
    assert log["pipeline"]["a413PrimaryDisplayCopy"]["field"] == "text"


def test_source_process_wording_is_not_primary_display_copy():
    row = item(
        "SIGNING",
        "Smith returns",
        "Harrison Smith agreed to a one-year deal, according to the supplied report.",
        "smith2",
        "Harrison Smith agreed to a one-year deal with Minnesota Saturday.",
    )
    normalized = {"leagues": [{"league": "NFL", "items": [row]}], "specialEvents": []}
    out = a413.promote_primary_display_copy(normalized)
    fixed = out["leagues"][0]["items"][0]
    assert "supplied report" not in fixed["text"].lower()


def test_primary_display_contract_marks_json_and_txt_review():
    writes = {}

    class FakeCore:
        @staticmethod
        def render_text(dataset):
            item0 = dataset["leagues"][0]["items"][0]
            return (
                "SPORTS BIG BOARD — SPORTS TICKER A4\n"
                "Updated: now\n"
                "Global headline budget: 1/30-35 total\n"
                "Headline length: target <= 80 chars; hard max 96\n"
                f" 1. [RESULT] {item0['headline']} (priority 75, age 1h)\n"
                f"    {item0['text']}\n"
            )

        @staticmethod
        def atomic_write(path, content):
            writes[path.name] = content

    a413.install_primary_display_contract(FakeCore)
    dataset = {
        "leagues": [{
            "league": "MLB",
            "items": [{
                "headline": "Compact headline",
                "text": "The polished actual update is shown to the user.",
                "type": "RESULT",
                "priority": 75,
            }],
        }],
        "specialEvents": [],
    }

    rendered = FakeCore.render_text(dataset)
    assert "[RESULT] The polished actual update is shown to the user." in rendered
    assert "Compact headline: Compact headline" in rendered
    assert "Primary display copy: item.text" in rendered
    assert "Compact headline length:" in rendered

    import json as _json
    from pathlib import Path as _Path
    FakeCore.atomic_write(_Path("sports-ticker.json"), _json.dumps(dataset))
    payload = _json.loads(writes["sports-ticker.json"])
    assert payload["displayCopyField"] == "text"
    assert payload["headlineRole"] == "compact-metadata"

def test_stable_launcher_discovers_a413_without_yaml_change():
    launcher_path = ROOT / "tools" / "refresh_sports_ticker_current.py"
    spec2 = importlib.util.spec_from_file_location("ticker_current_launcher_a413", launcher_path)
    launcher = importlib.util.module_from_spec(spec2)
    assert spec2 and spec2.loader
    spec2.loader.exec_module(launcher)
    assert launcher.discover_latest().name == "refresh_sports_ticker_a413.py"

    workflow = (ROOT / ".github" / "workflows" / "sports-ticker-refresh.yml").read_text()
    assert "python3 tests/test_sports_ticker_current.py" in workflow
    assert "python3 tools/refresh_sports_ticker_current.py" in workflow
    assert "a413" not in workflow.lower()


if __name__ == "__main__":
    test_cerundolo_rank_order_restores_upset()
    test_ranked_favorite_surviving_unranked_team_stays_result()
    test_structured_non_fbs_winner_over_fbs_promotes_to_upset()
    test_piastri_grid_penalty_becomes_discipline()
    test_gasly_pole_remains_qualifying()
    test_raw_pitch_feed_is_replaced_by_natural_freshness()
    test_clean_copy_is_unchanged()
    test_text_is_primary_display_copy_and_headline_is_preserved()
    test_headline_dependent_second_line_falls_back_to_standalone_freshness()
    test_source_process_wording_is_not_primary_display_copy()
    test_primary_display_contract_marks_json_and_txt_review()
    test_stable_launcher_discovers_a413_without_yaml_change()
    print("PASS: A4.13 semantic type + primary display copy + no YAML")

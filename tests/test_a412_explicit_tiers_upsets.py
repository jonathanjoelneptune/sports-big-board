#!/usr/bin/env python3
"""A4.12 explicit editorial tier + grounded UPSET regressions."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "refresh_sports_ticker_a412.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a412", PATH)
a412 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(a412)


def _item(kind="RESULT", priority=75, headline="Story", text="Useful context.", ids=None, entities=None):
    return {
        "candidateIds": ids or ["cand-1"],
        "type": kind,
        "priority": priority,
        "headline": headline,
        "text": text,
        "freshnessBasis": text,
        "entities": entities or [],
        "status": "active",
    }


def test_schema_requires_editorial_tier():
    class Core:
        MODEL_ITEM_SCHEMA = {
            "type": "object",
            "required": ["candidateIds", "priority"],
            "properties": {"candidateIds": {}, "priority": {}},
        }
        MODEL_SCHEMA = {
            "$defs": {
                "item": {
                    "type": "object",
                    "required": ["candidateIds", "priority"],
                    "properties": {"candidateIds": {}, "priority": {}},
                }
            }
        }

    a412.install_editorial_tier_schema(Core)
    assert Core.MODEL_ITEM_SCHEMA["properties"]["editorialTier"]["enum"] == [1, 2, 3]
    assert "editorialTier" in Core.MODEL_ITEM_SCHEMA["required"]
    assert "editorialTier" in Core.MODEL_SCHEMA["$defs"]["item"]["required"]


def test_tier_priority_is_clamped_before_selection():
    item = _item(priority=92, headline="Routine item")
    model = {
        "leagues": {
            "MLB": {"items": [{
                **item,
                "editorialTier": 3,
            }]}
        },
        "specialEvents": [],
    }
    records = a412.extract_tier_records(model)
    normalized = {
        "leagues": [{"league": "MLB", "items": [dict(item)]}],
        "specialEvents": [],
    }
    log = {"pipeline": {}}
    out = a412.enforce_tiers_and_upsets(normalized, records, [], log)
    fixed = out["leagues"][0]["items"][0]
    assert fixed["editorialTier"] == 3
    assert fixed["priority"] == 71
    assert log["pipeline"]["a412TierAudit"][0]["priorityBefore"] == 92
    assert log["pipeline"]["a412TierAudit"][0]["priorityAfter"] == 71


def test_routine_15_day_il_cannot_remain_tier1():
    item = _item(
        kind="INJURY",
        priority=88,
        headline="Taillon returns to IL as Jays seek elbow opinion",
        text="Toronto placed Jameson Taillon on the 15-day injured list with elbow inflammation.",
        ids=["taillon"],
    )
    model = {
        "leagues": {
            "MLB": {"items": [{**item, "editorialTier": 1}]}
        },
        "specialEvents": [],
    }
    candidate = {
        "candidateId": "taillon",
        "title": "Taillon goes back on 15-day IL; Jays seek second elbow opinion",
        "summary": "Toronto placed Taillon on the 15-day injured list with elbow inflammation.",
    }
    normalized = {"leagues": [{"league": "MLB", "items": [dict(item)]}], "specialEvents": []}
    out = a412.enforce_tiers_and_upsets(
        normalized, a412.extract_tier_records(model), [candidate]
    )
    fixed = out["leagues"][0]["items"][0]
    assert fixed["editorialTier"] == 3
    assert fixed["priority"] == 71


def test_day_to_day_marquee_absence_is_capped_at_tier2_not_tier3():
    item = _item(
        kind="INJURY",
        priority=88,
        headline="Ohtani misses third straight game with soreness",
        text="Shohei Ohtani was held out again with neck and arm soreness.",
        ids=["ohtani"],
    )
    model = {
        "leagues": {"MLB": {"items": [{**item, "editorialTier": 1}]}},
        "specialEvents": [],
    }
    candidate = {
        "candidateId": "ohtani",
        "title": "Dodgers hold Ohtani out again",
        "summary": "Ohtani was held out for a third straight game with neck soreness.",
    }
    normalized = {"leagues": [{"league": "MLB", "items": [dict(item)]}], "specialEvents": []}
    out = a412.enforce_tiers_and_upsets(
        normalized, a412.extract_tier_records(model), [candidate]
    )
    fixed = out["leagues"][0]["items"][0]
    assert fixed["editorialTier"] == 2
    assert fixed["priority"] == 81


def test_hospitalization_can_remain_tier1():
    item = _item(
        kind="INJURY",
        priority=84,
        headline="Northwestern center hospitalized after neck injury",
        text="Jackson Carsello was transported to a hospital after a neck injury.",
        ids=["carsello"],
    )
    model = {
        "leagues": {"NCAAF": {"items": [{**item, "editorialTier": 1}]}},
        "specialEvents": [],
    }
    candidate = {
        "candidateId": "carsello",
        "title": "Northwestern center taken to hospital",
        "summary": "Carsello was hospitalized after suffering a neck injury.",
    }
    normalized = {"leagues": [{"league": "NCAAF", "items": [dict(item)]}], "specialEvents": []}
    out = a412.enforce_tiers_and_upsets(
        normalized, a412.extract_tier_records(model), [candidate]
    )
    fixed = out["leagues"][0]["items"][0]
    assert fixed["editorialTier"] == 1
    assert fixed["priority"] == 84


def test_michigan_hail_mary_is_not_automatically_an_upset():
    item = _item(
        kind="UPSET",
        priority=90,
        headline="Michigan wins on second-chance Hail Mary amid clock controversy",
        text="Bryce Underwood lifted No. 16 Michigan past Western Michigan 13-12.",
        ids=["mich"],
        entities=["Michigan Wolverines", "Western Michigan Broncos"],
    )
    model = {
        "leagues": {"NCAAF": {"items": [{**item, "editorialTier": 1}]}},
        "specialEvents": [],
    }
    candidate = {
        "candidateId": "mich",
        "title": "Michigan stuns Western Michigan on Hail Mary amid clock controversy",
        "summary": "No. 16 Michigan beat Western Michigan 13-12 on a Hail Mary.",
    }
    normalized = {"leagues": [{"league": "NCAAF", "items": [dict(item)]}], "specialEvents": []}
    log = {"pipeline": {}}
    out = a412.enforce_tiers_and_upsets(
        normalized, a412.extract_tier_records(model), [candidate], log
    )
    fixed = out["leagues"][0]["items"][0]
    assert fixed["type"] == "RESULT"
    assert fixed["priority"] == 90  # dramatic Tier-1 finish remains Tier 1
    assert len(log["pipeline"]["a412UpsetCorrections"]) == 1


def test_fcs_over_fbs_remains_upset():
    item = _item(
        kind="UPSET",
        priority=84,
        headline="No. 23 Idaho State beats FBS Utah State 29-17",
        text="FCS No. 23 Idaho State beat FBS-member Utah State 29-17.",
        ids=["isu"],
        entities=["Idaho State Bengals", "Utah State Aggies"],
    )
    candidate = {
        "candidateId": "isu",
        "title": "Idaho State beats FBS-member Utah State",
        "summary": "The FCS Bengals defeated FBS-member Utah State 29-17.",
    }
    grounded, reason = a412.upset_is_grounded(item, [candidate])
    assert grounded, reason


def test_lower_seed_beating_higher_seed_remains_upset():
    item = _item(
        kind="UPSET",
        priority=84,
        headline="No. 24 Cerundolo rallies to stun No. 9 Fritz",
        text="No. 24 Francisco Cerundolo beat No. 9 Taylor Fritz in five sets.",
        ids=["tennis"],
    )
    candidate = {
        "candidateId": "tennis",
        "title": "No. 24 Cerundolo beats No. 9 Fritz",
        "summary": "Cerundolo rallied from two sets down to eliminate Fritz.",
    }
    grounded, reason = a412.upset_is_grounded(item, [candidate])
    assert grounded, reason


def test_editorial_tier_is_internal_only():
    item = _item(priority=84)
    item["editorialTier"] = 1
    item["feedRank"] = 1
    normalized = {
        "leagues": [{"league": "MLB", "items": [item]}],
        "specialEvents": [],
    }
    log = {"pipeline": {}}
    out = a412.strip_public_editorial_tiers(normalized, log)
    fixed = out["leagues"][0]["items"][0]
    assert "editorialTier" not in fixed
    assert log["pipeline"]["a412SelectedTierAudit"][0]["editorialTier"] == 1


def test_stable_launcher_discovers_a412_without_yaml_change():
    launcher_path = ROOT / "tools" / "refresh_sports_ticker_current.py"
    spec2 = importlib.util.spec_from_file_location("ticker_current_launcher_a412", launcher_path)
    launcher = importlib.util.module_from_spec(spec2)
    assert spec2 and spec2.loader
    spec2.loader.exec_module(launcher)

    assert launcher.discover_latest().name == "refresh_sports_ticker_a412.py"

    workflow_path = ROOT / ".github" / "workflows" / "sports-ticker-refresh.yml"
    if workflow_path.exists():
        workflow = workflow_path.read_text()
        assert "python3 tests/test_sports_ticker_current.py" in workflow
        assert "python3 tools/refresh_sports_ticker_current.py" in workflow
        assert "a412" not in workflow.lower()


if __name__ == "__main__":
    test_schema_requires_editorial_tier()
    test_tier_priority_is_clamped_before_selection()
    test_routine_15_day_il_cannot_remain_tier1()
    test_day_to_day_marquee_absence_is_capped_at_tier2_not_tier3()
    test_hospitalization_can_remain_tier1()
    test_michigan_hail_mary_is_not_automatically_an_upset()
    test_fcs_over_fbs_remains_upset()
    test_lower_seed_beating_higher_seed_remains_upset()
    test_editorial_tier_is_internal_only()
    test_stable_launcher_discovers_a412_without_yaml_change()
    print("PASS: A4.12 explicit editorial tiers + grounded UPSET + no YAML")

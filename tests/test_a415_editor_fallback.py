#!/usr/bin/env python3
"""A4.15 resilient editor-outage fallback regressions."""
from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "refresh_sports_ticker_a415.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a415", PATH)
a415 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(a415)

NOW = datetime(2026, 9, 13, 14, 0, tzinfo=timezone.utc)


def candidate(index: int, league: str, type_hint: str = "NEWS"):
    return {
        "candidateId": f"cand-{index}",
        "leagueHint": league,
        "typeHint": type_hint,
        "title": f"{league} consequential update {index}",
        "summary": f"Grounded {league} update {index} with a concrete result and context.",
        "occurredAt": f"2026-09-13T{10 + (index % 4):02d}:00:00Z",
        "timePrecision": "exact",
        "ageHours": float(index % 4),
        "quality": 80 - index,
        "sources": [{
            "provider": "Official source",
            "sourceId": f"source-{index}",
            "url": f"https://example.com/{league.lower()}/{index}",
        }],
        "metadata": {
            "storyPromotion": {
                "headlineSeed": f"{league} headline {index}",
                "summarySeed": f"Grounded {league} update {index} with a concrete result and context.",
                "priorityFloor": 72,
                "storyScore": 82,
            }
        },
    }


def quota_run_log():
    rows = [
        candidate(1, "MLB", "MILESTONE"),
        candidate(2, "MLB", "INJURY"),
        candidate(3, "NFL", "SIGNING"),
        candidate(4, "NFL", "INJURY"),
        candidate(5, "NBA", "TRADE"),
        candidate(6, "NHL", "STREAK"),
        candidate(7, "EPL", "RANKING"),
        candidate(8, "MLS", "NEWS"),
        candidate(9, "NCAAF", "RANKING"),
    ]
    return {
        "pipeline": {
            "status": "source_error",
            "editorCalled": False,
            "sourceError": (
                "OpenAI HTTP 429: insufficient_quota / credit_balance_exhausted: "
                "Credit balance too low."
            ),
            "modelCandidates": rows,
        }
    }


def previous_payload():
    return {
        "schemaVersion": 11,
        "pipelineVersion": "A4.14-test",
        "generatedAt": "2026-09-13T12:00:00Z",
        "leagues": [
            {"league": league, "seasonState": "active", "items": []}
            for league in a415.BASE_LEAGUES
        ],
        "specialEvents": [],
    }


def test_quota_outage_is_the_only_reason_that_activates_fallback():
    assert a415._editor_outage_reason(quota_run_log()) == "openai_credit_balance_exhausted"
    assert a415._editor_outage_reason({"pipeline": {"sourceError": "ESPN source timeout"}}) is None
    assert a415._editor_outage_reason({"pipeline": {"sourceError": "OpenAI HTTP 401 invalid_api_key"}}) is None


def test_fallback_publishes_only_grounded_fresh_candidates():
    payload = a415.build_fallback_payload(quota_run_log(), previous_payload(), now=NOW)
    assert payload["schemaVersion"] == 11
    assert payload["pipelineVersion"] == a415.PIPELINE_VERSION
    assert payload["model"] == "deterministic-source-fallback"
    assert payload["editorFallback"]["active"] is True
    assert payload["editorFallback"]["reason"] == "openai_credit_balance_exhausted"
    assert payload["displayCopyField"] == "text"
    assert payload["browserDisplayCompatibilityField"] == "headline"

    items = [item for group in payload["leagues"] for item in group["items"]]
    assert len(items) >= 4
    assert all(item["candidateIds"] for item in items)
    assert all(item["sources"] for item in items)
    assert all(item["sourceUrls"] for item in items)
    assert all(item["headline"] == item["text"] for item in items)
    assert all(item["status"] == "active" for item in items)


def test_run_log_preserves_editor_failure_but_reports_fallback_success():
    run_log = quota_run_log()
    payload = a415.build_fallback_payload(run_log, previous_payload(), now=NOW)
    updated = a415._mark_run_log_fallback(run_log, "openai_credit_balance_exhausted", payload)
    pipeline = updated["pipeline"]
    assert pipeline["status"] == "ok"
    assert pipeline["sourceError"] is None
    assert "credit_balance_exhausted" in pipeline["editorError"]
    assert pipeline["editorFallback"]["active"] is True
    assert pipeline["editorFallback"]["publishedItemCount"] >= 4


def test_stable_launcher_discovers_a415_or_newer_without_yaml_edit():
    launcher_path = ROOT / "tools" / "refresh_sports_ticker_current.py"
    spec2 = importlib.util.spec_from_file_location("ticker_current_launcher_a415", launcher_path)
    launcher = importlib.util.module_from_spec(spec2)
    assert spec2 and spec2.loader
    spec2.loader.exec_module(launcher)

    latest_name = launcher.discover_latest().name
    match = re.fullmatch(r"refresh_sports_ticker_a(\d+)\.py", latest_name)
    assert match, latest_name
    assert int(match.group(1)) >= 415, latest_name

    workflow = (ROOT / ".github" / "workflows" / "sports-ticker-refresh.yml").read_text()
    assert "python3 tests/test_sports_ticker_current.py" in workflow
    assert "python3 tools/refresh_sports_ticker_current.py" in workflow
    assert "a415" not in workflow.lower()


if __name__ == "__main__":
    test_quota_outage_is_the_only_reason_that_activates_fallback()
    test_fallback_publishes_only_grounded_fresh_candidates()
    test_run_log_preserves_editor_failure_but_reports_fallback_success()
    test_stable_launcher_discovers_a415_or_newer_without_yaml_edit()
    print("PASS: A4.15 resilient editor quota fallback + forward-compatible launcher")

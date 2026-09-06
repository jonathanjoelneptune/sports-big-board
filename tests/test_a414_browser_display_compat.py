#!/usr/bin/env python3
"""A4.14 legacy-browser display compatibility regressions."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "refresh_sports_ticker_a414.py"
spec = importlib.util.spec_from_file_location("refresh_sports_ticker_a414", PATH)
a414 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(a414)

a413 = a414._load_a413()


def sample_dataset():
    return {
        "schemaVersion": 11,
        "pipelineVersion": "A4.14-test",
        "generatedAt": "2026-09-06T05:05:47Z",
        "leagues": [{
            "league": "MLB",
            "items": [{
                "id": "story-1",
                "candidateIds": ["cand-1"],
                "type": "STANDINGS",
                "priority": 80,
                "headline": "Blue Jays pull even for final AL wild card",
                "text": (
                    "Toronto beat Kansas City 4-3 as Kazuma Okamoto collected four "
                    "hits and drove in two, pulling the Blue Jays even with Cleveland "
                    "for the final AL wild card."
                ),
                "freshnessBasis": "Toronto beat Kansas City 4-3 to pull even with Cleveland.",
                "status": "active",
            }],
        }],
        "specialEvents": [],
    }


def test_wire_json_mirrors_text_to_headline_and_preserves_compact_label():
    payload = a414.apply_browser_wire_compat(sample_dataset())
    row = payload["leagues"][0]["items"][0]
    assert row["headline"] == row["text"]
    assert row["compactHeadline"] == "Blue Jays pull even for final AL wild card"
    assert "shortHeadline" not in row
    assert payload["displayCopyField"] == "text"
    assert payload["browserDisplayCompatibilityField"] == "headline"
    assert payload["compactHeadlineField"] == "compactHeadline"


def test_existing_v550_browser_normalization_now_displays_full_update():
    payload = a414.apply_browser_wire_compat(sample_dataset())
    item = payload["leagues"][0]["items"][0]

    # Mirrors architecture/key-info-current-v520.js normalizeA4Item + rowTitle.
    normalized_headline = str(
        item.get("headline") or item.get("shortHeadline") or item.get("title") or ""
    ).strip()
    browser_row = {
        "headline": normalized_headline,
        "shortHeadline": normalized_headline,
        "text": str(item.get("text") or "").strip(),
    }
    row_title = (
        browser_row.get("shortHeadline")
        or browser_row.get("headline")
        or browser_row.get("title")
        or "Sports update"
    )

    assert row_title == item["text"]
    assert "Kazuma Okamoto collected four hits" in row_title
    assert row_title != item["compactHeadline"]


def test_special_event_rows_receive_same_wire_bridge():
    payload = {
        "leagues": [],
        "specialEvents": [{
            "name": "Italian Grand Prix",
            "sport": "Formula 1",
            "items": [{
                "candidateIds": ["piastri"],
                "type": "DISCIPLINE",
                "priority": 75,
                "headline": "Piastri drops to sixth after Italian GP grid penalty",
                "text": (
                    "Oscar Piastri was handed a three-place grid penalty for impeding "
                    "Liam Lawson in qualifying and will start the Italian Grand Prix from sixth."
                ),
                "status": "active",
            }],
        }],
    }
    out = a414.apply_browser_wire_compat(payload)
    row = out["specialEvents"][0]["items"][0]
    assert row["headline"].startswith("Oscar Piastri was handed")
    assert row["compactHeadline"].startswith("Piastri drops to sixth")


def test_writer_bridge_preserves_a413_metadata_and_fixes_wire_headline():
    writes = {}

    class FakeCore:
        @staticmethod
        def render_text(dataset):
            item = dataset["leagues"][0]["items"][0]
            return (
                "SPORTS BIG BOARD — SPORTS TICKER A4\n"
                "Global headline budget: 1/30-35 total\n"
                "Headline length: target <= 80 chars; hard max 96\n"
                f" 1. [STANDINGS] {item['headline']} (priority 80, age 1h)\n"
                f"    {item['text']}\n"
            )

        @staticmethod
        def atomic_write(path, content):
            writes[path.name] = content

    a414.install_browser_wire_compat(FakeCore, a413.install_primary_display_contract)
    dataset = sample_dataset()
    FakeCore.atomic_write(Path("sports-ticker.json"), json.dumps(dataset))
    payload = json.loads(writes["sports-ticker.json"])
    row = payload["leagues"][0]["items"][0]
    assert row["headline"] == row["text"]
    assert row["compactHeadline"] == "Blue Jays pull even for final AL wild card"
    assert payload["headlineRole"] == "legacy-browser-mirror-of-text"
    assert payload["displayCopyField"] == "text"


def test_stable_launcher_discovers_a414_without_yaml_change():
    launcher_path = ROOT / "tools" / "refresh_sports_ticker_current.py"
    spec2 = importlib.util.spec_from_file_location("ticker_current_launcher_a414", launcher_path)
    launcher = importlib.util.module_from_spec(spec2)
    assert spec2 and spec2.loader
    spec2.loader.exec_module(launcher)

    assert launcher.discover_latest().name == "refresh_sports_ticker_a414.py"

    workflow = (ROOT / ".github" / "workflows" / "sports-ticker-refresh.yml").read_text()
    assert "python3 tests/test_sports_ticker_current.py" in workflow
    assert "python3 tools/refresh_sports_ticker_current.py" in workflow
    assert "a414" not in workflow.lower()


if __name__ == "__main__":
    test_wire_json_mirrors_text_to_headline_and_preserves_compact_label()
    test_existing_v550_browser_normalization_now_displays_full_update()
    test_special_event_rows_receive_same_wire_bridge()
    test_writer_bridge_preserves_a413_metadata_and_fixes_wire_headline()
    test_stable_launcher_discovers_a414_without_yaml_change()
    print("PASS: A4.14 legacy-browser display compatibility + no frontend/YAML change")

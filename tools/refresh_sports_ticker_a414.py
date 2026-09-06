#!/usr/bin/env python3
"""Sports Big Board A4.14 legacy-browser display compatibility overlay on A4.13.

A4.13 established the correct editorial contract:
  item.text     = polished standalone user-facing ticker update
  item.headline = compact editorial label / metadata

The existing v5.5.0 browser consumer predates that contract. It normalizes
item.headline into both `headline` and `shortHeadline`, and the ribbon renders
`shortHeadline || headline || title`. As a result, the live website still shows
the compact label even though A4.13 generated better `text`.

A4.14 fixes only that serialization boundary. Internally the editor continues to
use the compact headline exactly as before. When writing sports-ticker.json:
  - compactHeadline preserves the original compact label;
  - text remains the canonical polished display update;
  - headline is mirrored from text for compatibility with the existing browser;
  - legacy shortHeadline is removed if present.

This is deliberately a producer-side wire bridge so the live website can display
the richer update without a frontend release. No editorial selection, budget,
tier, refill, source, league-cap, headline-generation, workflow, or YAML change.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.14-legacy-browser-display-compat"


def _load_a413():
    path = Path(__file__).with_name("refresh_sports_ticker_a413.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a413", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.13 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def apply_browser_wire_compat(payload: dict[str, Any]) -> dict[str, Any]:
    """Mirror canonical text into legacy headline only in the serialized JSON."""
    changed: list[dict[str, Any]] = []

    def visit(items: list[dict[str, Any]], context: str) -> None:
        for item in items:
            compact = _clean(item.get("compactHeadline") or item.get("headline"))
            display = _clean(item.get("text") or item.get("headline"))
            if not display:
                continue

            before = _clean(item.get("headline"))
            if compact:
                item["compactHeadline"] = compact
            item["headline"] = display
            item.pop("shortHeadline", None)

            if before != display:
                changed.append({
                    "context": context,
                    "candidateIds": item.get("candidateIds", []),
                    "compactHeadline": compact,
                    "displayHeadline": display,
                })

    for group in payload.get("leagues", []):
        if not isinstance(group, dict):
            continue
        visit(
            group.get("items", []) if isinstance(group.get("items"), list) else [],
            _clean(group.get("league")),
        )

    for event in payload.get("specialEvents", []):
        if not isinstance(event, dict):
            continue
        visit(
            event.get("items", []) if isinstance(event.get("items"), list) else [],
            _clean(event.get("name")) or _clean(event.get("sport")),
        )

    payload["displayCopyField"] = "text"
    payload["browserDisplayCompatibilityField"] = "headline"
    payload["compactHeadlineField"] = "compactHeadline"
    payload["headlineRole"] = "legacy-browser-mirror-of-text"
    payload["compactHeadlineRole"] = "compact-editorial-metadata"
    payload["displayCopyPolicy"] = (
        "item.text is canonical display copy; item.headline mirrors text only for "
        "the existing v5.5.0 browser consumer; item.compactHeadline preserves the "
        "short editorial label"
    )
    payload["browserWireCompat"] = {
        "version": "A4.14",
        "changedCount": len(changed),
        "policy": "mirror text -> headline at JSON serialization only",
    }
    return payload


def install_browser_wire_compat(core, install_a413_contract) -> None:
    """Install underneath A4.13's writer so this becomes the final disk transform."""
    original_atomic_write = core.atomic_write

    def atomic_write_a414(path, content):
        if path.name == "sports-ticker.json":
            try:
                payload = json.loads(content)
                if isinstance(payload, dict):
                    payload = apply_browser_wire_compat(payload)
                    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            except Exception:
                pass
        original_atomic_write(path, content)

    # A4.13 captures the current writer and then wraps it. Installing this bridge
    # first means A4.13 adds canonical metadata, then A4.14 performs the last JSON
    # compatibility transform immediately before disk write.
    core.atomic_write = atomic_write_a414
    install_a413_contract(core)


def main() -> int:
    a413 = _load_a413()
    a413.PIPELINE_VERSION = PIPELINE_VERSION

    original_install = a413.install_primary_display_contract

    def install_a414(core):
        install_browser_wire_compat(core, original_install)

    a413.install_primary_display_contract = install_a414
    return a413.main()


if __name__ == "__main__":
    raise SystemExit(main())

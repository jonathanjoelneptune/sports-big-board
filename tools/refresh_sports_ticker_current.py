#!/usr/bin/env python3
"""Stable Sports Ticker workflow entrypoint.

The GitHub Actions workflow calls this file permanently. It auto-discovers the
highest versioned A4.x sidecar module (a48, a49, a410, ...), so ordinary Sports
Ticker revisions no longer require workflow YAML edits.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATTERN = re.compile(r"^refresh_sports_ticker_a(\d+)\.py$")


def discover_latest() -> Path:
    candidates: list[tuple[int, Path]] = []
    for path in HERE.glob("refresh_sports_ticker_a*.py"):
        match = PATTERN.match(path.name)
        if not match:
            continue
        candidates.append((int(match.group(1)), path))
    if not candidates:
        raise RuntimeError("No versioned Sports Ticker sidecar found")
    return max(candidates, key=lambda row: row[0])[1]


def main() -> int:
    path = discover_latest()
    print(f"Sports Ticker current entrypoint -> {path.name}")
    spec = importlib.util.spec_from_file_location("sports_ticker_current_impl", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load Sports Ticker implementation from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "main"):
        raise RuntimeError(f"Sports Ticker implementation has no main(): {path}")
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())

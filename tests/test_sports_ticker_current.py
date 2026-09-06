#!/usr/bin/env python3
"""Stable regression runner for the current Sports Ticker sidecar chain.

The workflow calls this file permanently. New A4.x regression files matching
``test_a4*.py`` are discovered automatically, so the workflow YAML does not need
version-by-version edits.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SELF = Path(__file__).resolve()


def order_key(path: Path) -> tuple[int, str]:
    name = path.name
    if name == "test_a4_global_headline_budget.py":
        return (42, name)
    match = re.match(r"test_a4(\d+)_", name)
    if match:
        return (int("4" + match.group(1)), name)
    return (999999, name)


def discover_tests() -> list[Path]:
    tests = [
        path for path in HERE.glob("test_a4*.py")
        if path.resolve() != SELF
    ]
    return sorted(tests, key=order_key)


def main() -> int:
    tests = discover_tests()
    if not tests:
        raise RuntimeError("No Sports Ticker A4 regression files found")
    print("Sports Ticker stable regression runner:")
    for path in tests:
        print(f"  - {path.name}")
    for path in tests:
        completed = subprocess.run([sys.executable, str(path)], cwd=str(HERE.parent))
        if completed.returncode:
            return completed.returncode
    print(f"PASS: {len(tests)} Sports Ticker regression files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

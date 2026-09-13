#!/usr/bin/env python3
"""Regression coverage for EPL canonical scoreboard date transport semantics."""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SBB_STATE_DIR", tempfile.mkdtemp(prefix="sbb-epl-scoreboard-"))

import server


def _capture_urls(league: str) -> list[str]:
    urls: list[str] = []

    def fake_fetch(url: str, *args, **kwargs):
        urls.append(url)
        return {"events": []}

    with patch.object(server, "_read_scoreboard_cache", return_value=(None, None)), patch.object(server, "_espn_fetch_json", side_effect=fake_fetch):
        rows = server._espn_scoreboard(league, "2026-09-13", "America/New_York")

    if rows != []:
        raise AssertionError(f"expected no rows from mocked ESPN fetches, got {rows!r}")
    return urls


class EplScoreboardExactDateTests(unittest.TestCase):
    def test_epl_uses_exact_date_transports_not_range_tokens(self):
        urls = _capture_urls("EPL")
        self.assertTrue(urls)
        self.assertFalse(any(re.search(r"dates=\d{8}-\d{8}", url) for url in urls), urls)
        self.assertTrue(any("dates=20260913" in url for url in urls), urls)
        self.assertTrue(any("dates=20260912" in url for url in urls), urls)
        self.assertTrue(any("dates=20260914" in url for url in urls), urls)

    def test_nfl_keeps_existing_range_window_behavior(self):
        urls = _capture_urls("NFL")
        self.assertTrue(any("dates=20260912-20260914" in url for url in urls), urls)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
from pathlib import Path

path = Path('server.py')
text = path.read_text(encoding='utf-8')

old_date = """    if sport=='soccer' or league_key=='NFL':
        start_day=(target-timedelta(days=1)).strftime('%Y%m%d')
        end_day=(target+timedelta(days=1)).strftime('%Y%m%d')
        date_token=f'{start_day}-{end_day}'
    else:
        date_token=target.strftime('%Y%m%d')
"""
new_date = """    # ESPN's soccer scoreboards do not consistently accept date-range tokens
    # across transports (the EPL path can return HTTP 400). Soccer already has
    # exact neighboring-day probes below, so keep its primary requests exact-date.
    # NFL retains the range window because its preseason/date-board behavior needs it.
    if league_key=='NFL':
        start_day=(target-timedelta(days=1)).strftime('%Y%m%d')
        end_day=(target+timedelta(days=1)).strftime('%Y%m%d')
        date_token=f'{start_day}-{end_day}'
    else:
        date_token=target.strftime('%Y%m%d')
"""

old_neighbors = """    # Range semantics differ across ESPN transports. Exact neighboring date reads
    # are cheap, keyless, and catch evening games stamped on the next UTC date.
    if sport=='soccer' or league_key=='NFL':
        for delta in (-1,0,1):
            exact=(target+timedelta(days=delta)).strftime('%Y%m%d')
            specs.append((f'{ESPN_SITE_API}/{sport}/{slug}/scoreboard?'+urlencode({'dates':exact,'limit':100}),False,f'site-exact-{delta:+d}'))
"""
new_neighbors = """    # Exact neighboring-date reads catch evening games stamped on the adjacent
    # UTC date. Soccer's target date is already covered by the primary exact-date
    # transports, so only probe -1/+1 there; NFL keeps its existing -1/0/+1 probes.
    if sport=='soccer':
        exact_deltas=(-1,1)
    elif league_key=='NFL':
        exact_deltas=(-1,0,1)
    else:
        exact_deltas=()
    for delta in exact_deltas:
        exact=(target+timedelta(days=delta)).strftime('%Y%m%d')
        specs.append((f'{ESPN_SITE_API}/{sport}/{slug}/scoreboard?'+urlencode({'dates':exact,'limit':100}),False,f'site-exact-{delta:+d}'))
"""

if text.count(old_date) != 1:
    raise SystemExit(f'date-token block count={text.count(old_date)}; refusing broad patch')
if text.count(old_neighbors) != 1:
    raise SystemExit(f'neighbor-probe block count={text.count(old_neighbors)}; refusing broad patch')

path.write_text(text.replace(old_date, new_date, 1).replace(old_neighbors, new_neighbors, 1), encoding='utf-8')

Path('tests/test_epl_scoreboard_exact_dates.py').write_text('''#!/usr/bin/env python3
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
        self.assertFalse(any(re.search(r"dates=\\d{8}-\\d{8}", url) for url in urls), urls)
        self.assertTrue(any("dates=20260913" in url for url in urls), urls)
        self.assertTrue(any("dates=20260912" in url for url in urls), urls)
        self.assertTrue(any("dates=20260914" in url for url in urls), urls)

    def test_nfl_keeps_existing_range_window_behavior(self):
        urls = _capture_urls("NFL")
        self.assertTrue(any("dates=20260912-20260914" in url for url in urls), urls)


if __name__ == "__main__":
    unittest.main()
''', encoding='utf-8')

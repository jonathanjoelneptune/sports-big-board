#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = (root / "VERSION").read_text(encoding="utf-8").strip()
init = (root / "sbb" / "__init__.py").read_text(encoding="utf-8")
module = (root / "sbb" / "canonical_schedule_watchdogs_v6116.py").read_text(encoding="utf-8")
verify = (root / "VERIFY.sh").read_text(encoding="utf-8")

expected = ".".join(("6", "1", "16"))
assert version == expected, version
assert "from .canonical_schedule_watchdogs_v6116 import install" in init
assert "_install_canonical_schedule_watchdogs_v6116()" in init

for token in (
    "OFFICIAL_SCHEDULE_PAGES",
    "https://www.premierleague.com/en/matches/premier-league/2026-27/matchweek-4",
    "https://www.nfl.com/schedules",
    "https://www.mlb.com/schedule",
    "https://www.nba.com/schedule",
    "https://www.mlssoccer.com/schedule/scores",
    "https://www.nhl.com/schedule",
    "https://fbschedules.com/college-football-schedule/",
    "PREMIER_LEAGUE_OFFICIAL_SCHEDULE",
    "nflCurrentByWeekScheduleRoute",
    "trustedExplicitSlateDateRehome",
    "ncaafFbschedulesSecondaryOnly",
):
    assert token in module, token

assert "python3 -m py_compile sbb/canonical_schedule_watchdogs_v6116.py" in verify
assert "python3 tests/test_v6116_official_schedule_watchdogs.py" in verify
assert "python3 tests/test_v6116_official_schedule_release.py" in verify

print("PASS v6.1.16 official schedule resiliency release contract")

#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = (root / "VERSION").read_text(encoding="utf-8").strip()
init = (root / "sbb" / "__init__.py").read_text(encoding="utf-8")
helper = (root / "sbb" / "canonical_schedule_watchdog_v6116.py").read_text(encoding="utf-8")
verify = (root / "VERIFY.sh").read_text(encoding="utf-8")
materializer = (root / "tools" / "apply_v6116_release.py").read_text(encoding="utf-8")

expected = ".".join(("6", "1", "16"))
base = ".".join(("6", "1", "15"))
assert version == expected, version
assert "from .canonical_schedule_watchdog_v6116 import install as _install_canonical_schedule_watchdog_v6116" in init
assert "_install_canonical_schedule_watchdog_v6116()" in init

for token in (
    "sdp-prem-prod.premier-league-prod.pulselive.com",
    "/api/v2/matches",
    "https://www.nfl.com/schedules/{season}/by-week/week-{week}",
    "https://www.mlb.com/schedule",
    "https://www.nba.com/schedule",
    "https://www.mlssoccer.com/schedule/scores",
    "https://www.nhl.com/schedule",
    "https://fbschedules.com/college-football-schedule/",
    "SECONDARY_INDEPENDENT_REFERENCE",
    "def _safe_rehome_rows(",
    "officialScheduleWatchdogs",
    "sportsDayTimezone",
):
    assert token in helper, token

assert "python3 -m py_compile sbb/canonical_schedule_watchdog_v6116.py" in verify
assert "python3 tests/test_v6116_schedule_watchdogs.py" in verify
assert "python3 tests/test_v6116_schedule_watchdog_release.py" in verify
assert f'BASE = "{base}"' in materializer
assert f'NEW = "{expected}"' in materializer

print("PASS official schedule watchdog release contract", expected)

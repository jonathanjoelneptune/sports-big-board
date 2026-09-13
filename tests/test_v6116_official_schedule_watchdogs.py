#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sbb import canonical_schedule_watchdogs_v6116 as mod

assert set(mod.OFFICIAL_SCHEDULE_PAGES) == {"EPL","NFL","MLB","NBA","MLS","NHL","NCAAF"}
assert mod.OFFICIAL_SCHEDULE_PAGES["NFL"] == "https://www.nfl.com/schedules"
assert mod.OFFICIAL_SCHEDULE_PAGES["MLB"] == "https://www.mlb.com/schedule"
assert "fbschedules.com" in mod.OFFICIAL_SCHEDULE_PAGES["NCAAF"]
assert mod._fetch_watchdog.__name__ == "_fetch_watchdog"

# Regular-season NFL schedule URLs must use the current official route.  This is
# deliberately checked without network I/O.
class Fake:
    _labor_day = staticmethod(lambda season: __import__('datetime').date(season, 9, 7))

pages, required = mod._nfl_pages_v6116(Fake(), ["2026-09-20"])
reg = [x for x in pages if x[1] == "REG"]
assert reg, pages
assert all("/by-week/week-" in x[3] for x in reg), reg
assert all("/REG" not in x[3] for x in reg), reg
assert required["2026-09-20"] == {(2026, "REG")}

# EPL's repaired structured schedule query must never reintroduce the obsolete
# sort=asc token that generated the live HTTP 400 failures.
source = (ROOT / "sbb" / "canonical_schedule_watchdogs_v6116.py").read_text(encoding="utf-8")
epl_start = source.index("def _collect_epl_v6116")
epl_end = source.index("def _fetch_watchdog", epl_start)
epl_body = source[epl_start:epl_end]
assert '"sort": "asc"' not in epl_body
assert '"compSeasons": season_id' in epl_body
assert "PREMIER_LEAGUE_OFFICIAL_SCHEDULE" in epl_body

# Re-homing must be explicit-date-only and must not infer the slate date from the
# UTC kickoff timestamp. This protects legitimate UTC boundary games.
assert '"__sbbDate", "canonicalSlateDate", "gameDate", "slateDate", "eventDate"' in source
assert "TRUSTED_SLATE_DATE_SOURCES" in source
assert "UPDATE canonical_event SET slate_date=?" in source
assert "scheduledAt alone" in source

print("PASS v6.1.16 official schedule watchdog + adapter repair contract")

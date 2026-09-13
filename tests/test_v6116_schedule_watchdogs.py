#!/usr/bin/env python3
import sys
import tempfile
from datetime import date
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from sbb import canonical_shadow_v600 as shadow
from sbb import canonical_schedule_watchdog_v6116 as v6116

# A UTC timestamp after midnight must stay on the Big Board's Eastern sports day.
assert v6116._sports_day({"date": "2026-09-16T01:40:00Z"}) == "2026-09-15"
assert v6116._sports_day({"__sbbDate": "2026-09-15", "date": "2026-09-16T01:40:00Z"}) == "2026-09-15"
assert v6116._sports_day({"canonicalSlateDate": "2026-09-15", "scheduledAt": "2026-09-16T01:40:00Z"}) == "2026-09-15"

# Current NFL schedule URLs are /by-week/week-N. The September 20 slate belongs
# to week 2 and may not be certified merely because a different REG page parsed.
class FakeNFL:
    @staticmethod
    def _labor_day(season):
        assert season == 2026
        return date(2026, 9, 7)

pages, required = v6116._nfl_pages_v6116(FakeNFL(), ["2026-09-20"])
urls = [x[3] for x in pages]
assert "https://www.nfl.com/schedules/2026/by-week/week-2" in urls
assert (2026, "REG", 2) in required["2026-09-20"]
assert not any("/REG2/" in x for x in urls)

# The current Premier League SDP list response exposes homeTeam/awayTeam and a
# kickoff instant. The adapter must normalize it into authoritative SBB evidence.
epl = v6116._epl_fixture({
    "matchId": 72221276,
    "kickoff": "2026-09-19T14:00:00Z",
    "period": "PreMatch",
    "homeTeam": {"id": 36, "name": "Brighton & Hove Albion", "shortName": "Brighton", "abbr": "BRI", "score": 0},
    "awayTeam": {"id": 3, "name": "Arsenal FC", "shortName": "Arsenal", "abbr": "ARS", "score": 0},
    "ground": {"name": "Amex Stadium"},
}, {"2026-09-19"})
assert epl and epl["eventId"] == "72221276"
assert epl["__sbbDate"] == "2026-09-19"
assert epl["home"]["displayName"] == "Brighton & Hove Albion"
assert epl["away"]["displayName"] == "Arsenal FC"

# Existing UTC-day leaks are repaired in place, preserving the canonical ID.
with tempfile.TemporaryDirectory() as td:
    store = shadow.CanonicalShadowStore(Path(td) / "canonical.sqlite3")
    event_id = "cev_test_mlb_et_date"
    event = {
        "competitionId": "MLB",
        "__sbbDate": "2026-09-15",
        "canonicalSlateDate": "2026-09-15",
        "eventId": "401816956",
        "scheduledAt": "2026-09-16T01:40:00Z",
        "away": {"id": "28", "displayName": "Miami Marlins"},
        "home": {"id": "29", "displayName": "Arizona Diamondbacks"},
        "status": "SCHEDULED",
    }
    store.upsert_event(event_id, "MLB", "2026-09-16", event, "DAY_STATE", "RESOLVED", "INCLUDED", "ALL_LEAGUE_EVENTS")
    fake = type("FakeEngine", (), {"store": store})()
    result = v6116._safe_rehome_rows(fake)
    assert result["count"] == 1, result
    rows = store.events_for_day("2026-09-15", "MLB")
    assert [x["canonical_event_id"] for x in rows] == [event_id]
    assert not store.events_for_day("2026-09-16", "MLB")

# FBSchedules is intentionally never elevated to authoritative evidence.
assert v6116.OFFICIAL_SCHEDULE_CONTRACTS["NCAAF"]["role"] == "SECONDARY_INDEPENDENT_REFERENCE"
assert v6116.OFFICIAL_SCHEDULE_CONTRACTS["EPL"]["role"] == "AUTHORITATIVE_FALLBACK"
assert v6116.OFFICIAL_SCHEDULE_CONTRACTS["MLB"]["role"] == "WATCHDOG_DATE_CONTRACT"

print("PASS v6.1.16 official schedule watchdog behavior")

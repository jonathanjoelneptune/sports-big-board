"""Sports Big Board v6.1.16 official schedule-page watchdogs and adapter repairs.

Shadow/certification only. This layer does not change production event authority.
It repairs three defects exposed by the v6.1.15 validation console:

* NFL official schedule collection follows the current /by-week/week-N route.
* Premier League fixture collection retries the current PulseLive season query
  without the obsolete sort argument that returns HTTP 400.
* trusted explicit SBB/ET slate dates are allowed to correct an existing canonical
  event that was previously persisted under its UTC calendar date.

It also continuously watches the public schedule pages supplied by the operator so
an adapter can be diagnosed as suspect when the league's public schedule remains
reachable. Page reachability is diagnostics only; it never creates certification
evidence unless an official structured parser actually returns events.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import canonical_shadow_v600 as shadow
from . import canonical_certification_v610 as v610
from . import canonical_certification_v611 as v611

VERSION = "6.1.16-official-schedule-watchdogs-1"
ENABLED = str(os.environ.get("SBB_CANONICAL_OFFICIAL_SCHEDULE_WATCHDOGS_ENABLED") or "1").strip().lower() not in {"0", "false", "no", "off"}
WATCHDOG_SECONDS = max(300, int(os.environ.get("SBB_CANONICAL_OFFICIAL_SCHEDULE_WATCHDOG_SECONDS") or 900))
WATCHDOG_TIMEOUT = max(4, min(20, int(os.environ.get("SBB_CANONICAL_OFFICIAL_SCHEDULE_WATCHDOG_TIMEOUT") or 10)))

OFFICIAL_SCHEDULE_PAGES = {
    "EPL": "https://www.premierleague.com/en/matches/premier-league/2026-27/matchweek-4",
    "NFL": "https://www.nfl.com/schedules",
    "MLB": "https://www.mlb.com/schedule",
    "NBA": "https://www.nba.com/schedule",
    "MLS": "https://www.mlssoccer.com/schedule/scores",
    "NHL": "https://www.nhl.com/schedule",
    "NCAAF": "https://fbschedules.com/college-football-schedule/",
}
PAGE_MARKERS = {
    "EPL": ("premier league", "matches"),
    "NFL": ("nfl", "schedule"),
    "MLB": ("mlb", "schedule"),
    "NBA": ("nba", "schedule"),
    "MLS": ("mls", "schedule"),
    "NHL": ("nhl", "schedule"),
    "NCAAF": ("college football", "schedule"),
}
TRUSTED_SLATE_DATE_SOURCES = {
    "MLB_STATS_API", "ESPN_DIRECT", "ESPN_INDEPENDENT", "DAY_STATE",
    "NFL_COM_SCHEDULE", "NBA_CDN_SCHEDULE", "NHL_WEB_API",
    "PREMIER_LEAGUE_PULSE", "PREMIER_LEAGUE_OFFICIAL_SCHEDULE",
    "MLS_STATS_API", "NCAA_SD_DATA",
}

_PATCH_LOCK = threading.Lock()
_PATCHED = False
_INSTALLED = False
_ENGINE = None


def _clean(value):
    return str(value or "").strip()


def _now():
    return time.time()


def _explicit_slate_date(event, fallback=""):
    """Return only an explicit league/SBB calendar date, never UTC timestamp[:10]."""
    event = event or {}
    for key in ("__sbbDate", "canonicalSlateDate", "gameDate", "slateDate", "eventDate"):
        value = shadow._day(event.get(key))
        if value:
            return value
    return shadow._day(fallback)


def _install_slate_date_rehome():
    """Permit trusted observations to repair a stale UTC-day canonical row.

    CanonicalShadowStore.upsert_event deliberately treated slate_date as immutable.
    That is safe for ordinary facts but prevents correction of rows originally
    created from a UTC date. The correction is narrowly gated to trusted sources and
    explicit SBB/organizer calendar dates. No row is moved based on scheduledAt alone.
    """
    cls = shadow.CanonicalShadowStore
    if getattr(cls, "__sbbV6116SlateDateRehome", False):
        return
    original = cls.upsert_event

    def upsert_event(self, canonical_event_id, league, slate_date, event, source, identity_state, inclusion_state, inclusion_reason):
        original(self, canonical_event_id, league, slate_date, event, source, identity_state, inclusion_state, inclusion_reason)
        source_name = _clean(source).upper()
        explicit = _explicit_slate_date(event, slate_date)
        if source_name not in TRUSTED_SLATE_DATE_SOURCES or not explicit:
            return
        # The passed day must itself agree with the explicit event calendar date.
        # This prevents a boundary fetch from moving an event merely because it was
        # observed while processing an adjacent day.
        if shadow._day(slate_date) != explicit:
            return
        with self._lock, shadow.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT slate_date FROM canonical_event WHERE canonical_event_id=?",
                (canonical_event_id,),
            ).fetchone()
            if not row or str(row[0] or "") == explicit:
                return
            old_day = str(row[0] or "")
            conn.execute(
                "UPDATE canonical_event SET slate_date=?,updated_at=? WHERE canonical_event_id=?",
                (explicit, _now(), canonical_event_id),
            )
            conn.commit()
            # Preserve an operator-visible breadcrumb in schedule evidence. Existing
            # schedule observations remain immutable evidence of what each source saw.
            try:
                self.record_source_coverage(
                    explicit, league, "CANONICAL_DATE_REHOME", "DIRECT", True, 1,
                    f"re-homed {canonical_event_id} from {old_day} using {source_name}",
                )
            except Exception:
                pass

    cls.upsert_event = upsert_event
    cls.__sbbV6116SlateDateRehome = True


def _nfl_pages_v6116(self, days):
    """Current NFL schedule routes for regular-season horizon dates.

    NFL.com moved from /REGN/ to /by-week/week-N. Keep the v6.1.1 planner for
    preseason/postseason where route semantics may differ, but replace every regular
    season URL with the current official route.
    """
    pages, required_by_day = v611._nfl_pages_v611(self, days)
    repaired = []
    seen = set()
    for season, stage, week, url in pages:
        if stage == "REG":
            url = f"https://www.nfl.com/schedules/{season}/by-week/week-{week}"
        key = (season, stage, week, url)
        if key not in seen:
            seen.add(key)
            repaired.append(key)
    return sorted(repaired), required_by_day


def _epl_fixture_groups(rows, days):
    groups = defaultdict(list)
    wanted = set(days)
    for fixture in rows or []:
        if not isinstance(fixture, dict):
            continue
        kickoff = fixture.get("kickoff") or {}
        scheduled = v610._iso_from_epoch(kickoff.get("millis")) or _clean(kickoff.get("label") or fixture.get("kickoffTime"))
        day = v610._day_from_datetime(scheduled)
        if day not in wanted:
            continue
        teams = fixture.get("teams") or []
        if not isinstance(teams, list) or len(teams) < 2:
            continue
        home_entry, away_entry = teams[0], teams[1]
        for entry in teams:
            if not isinstance(entry, dict):
                continue
            loc = _clean(entry.get("location") or entry.get("side")).lower()
            if loc == "home":
                home_entry = entry
            elif loc in {"away", "visitor"}:
                away_entry = entry
        home_raw = (home_entry.get("team") if isinstance(home_entry, dict) else {}) or {}
        away_raw = (away_entry.get("team") if isinstance(away_entry, dict) else {}) or {}
        home_name = _clean(home_raw.get("name") or home_raw.get("shortName"))
        away_name = _clean(away_raw.get("name") or away_raw.get("shortName"))
        if not home_name or not away_name:
            continue
        groups[day].append({
            "competitionId": "EPL", "__sbbDate": day,
            "eventId": _clean(fixture.get("id")), "scheduledAt": scheduled,
            "status": _clean(fixture.get("status") or fixture.get("phase") or "SCHEDULED"),
            "away": v610._team(away_name, away_raw.get("shortName")),
            "home": v610._team(home_name, home_raw.get("shortName")),
            "venue": fixture.get("ground") or {},
        })
    return groups


def _collect_epl_v6116(self, day_from, day_to):
    """Repair PulseLive and fail over to the official current season query.

    The v6.1.1 collector removed sort from season discovery after observing HTTP 400,
    but accidentally kept sort=asc on fixtures. Current PulseLive accepts the
    season-scoped fixture query without that obsolete sort. We try the least coupled
    official query first and retain a comps-filter variant as a second attempt.
    """
    league = "EPL"
    primary_source = v610.SOURCE_DEFS[league]["authoritative"]
    fallback_source = "PREMIER_LEAGUE_OFFICIAL_SCHEDULE"
    days = v610._date_range(day_from, day_to)
    headers = {
        "Origin": "https://www.premierleague.com",
        "Referer": "https://www.premierleague.com/en/matches",
        "Accept": "application/json,text/plain,*/*",
    }
    season_url = "https://footballapi.pulselive.com/football/competitions/1/compseasons?page=0&pageSize=100"
    try:
        season_payload = self._http(season_url, headers=headers, cache_seconds=3600)
        seasons = season_payload.get("content") if isinstance(season_payload, dict) else season_payload
        if not isinstance(seasons, list) or not seasons:
            raise RuntimeError("Premier League season response missing season list")
        midpoint = date.fromisoformat(days[len(days)//2])
        start_year = midpoint.year if midpoint.month >= 7 else midpoint.year - 1
        chosen = None
        for season in seasons:
            label = _clean((season or {}).get("label") or (season or {}).get("name"))
            if str(start_year) in label and (str(start_year + 1) in label or str(start_year + 1)[-2:] in label):
                chosen = season
                break
        if not chosen:
            raise RuntimeError(f"Premier League season {start_year}/{start_year+1} not found")
        season_id = _clean((chosen or {}).get("id"))
        if not season_id:
            raise RuntimeError("Premier League season ID unavailable")

        query_shapes = (
            {"compSeasons": season_id, "pageSize": 100},
            {"comps": 1, "compSeasons": season_id, "pageSize": 100},
        )
        rows = None
        chosen_shape = None
        last_error = ""
        last_url = season_url
        for shape in query_shapes:
            try:
                collected = []
                for page in range(0, 10):
                    fixture_url = "https://footballapi.pulselive.com/football/fixtures?" + urlencode({**shape, "page": page})
                    last_url = fixture_url
                    payload = self._http(fixture_url, headers=headers, cache_seconds=900)
                    content = payload.get("content") if isinstance(payload, dict) else payload
                    if not isinstance(content, list):
                        raise RuntimeError(f"Premier League fixtures response missing content[] on page {page}")
                    collected.extend(content)
                    if len(content) < int(shape.get("pageSize") or 100):
                        break
                if collected:
                    rows = collected
                    chosen_shape = shape
                    break
                last_error = "official fixture query returned zero rows"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
        if not rows:
            raise RuntimeError(last_error or "Premier League official fixture query returned zero rows")

        groups = _epl_fixture_groups(rows, days)
        # This data is still league-operated structured schedule data. Record a
        # distinct source name so the console makes the fallback visible rather
        # than pretending the old request shape recovered.
        count = self.writer.snapshot(groups, days, league, fallback_source, "AUTHORITATIVE")
        self._mark_health(
            league, fallback_source, "AUTHORITATIVE", day_from, day_to, True, count, "",
            f"{OFFICIAL_SCHEDULE_PAGES['EPL']} -> PulseLive compSeasons={season_id} shape={json.dumps(chosen_shape,sort_keys=True)}",
        )
        # Also mark the legacy adapter healthy only when its official successor
        # returned structured events; diagnostics retain the explicit fallback row.
        self._mark_health(league, primary_source, "AUTHORITATIVE", day_from, day_to, True, count, "official schedule fallback active", last_url)
        return count
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        return self._failed_range(league, primary_source, "AUTHORITATIVE", days, error, OFFICIAL_SCHEDULE_PAGES["EPL"])


def _fetch_watchdog(league, url):
    started = _now()
    headers = {
        "User-Agent": "Mozilla/5.0 (SportsBigBoard/6.1.16 official schedule watchdog)",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    }
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=WATCHDOG_TIMEOUT) as response:
            raw = response.read(768 * 1024).decode("utf-8", "replace")
            status = int(getattr(response, "status", 200) or 200)
            final_url = str(getattr(response, "url", url) or url)
        lowered = re.sub(r"\s+", " ", raw.lower())
        markers = PAGE_MARKERS.get(league, ())
        marker_hits = sum(1 for marker in markers if marker.lower() in lowered)
        return {
            "league": league, "url": url, "finalUrl": final_url, "success": 200 <= status < 400,
            "httpStatus": status, "bytesSampled": len(raw.encode("utf-8", "ignore")),
            "markerHits": marker_hits, "markersExpected": len(markers), "error": "",
            "checkedAt": _now(), "durationMs": round((_now() - started) * 1000, 2),
            "role": "SECONDARY_INDEPENDENT" if league == "NCAAF" else "OFFICIAL_WATCHDOG",
        }
    except Exception as exc:
        return {
            "league": league, "url": url, "success": False, "httpStatus": 0,
            "bytesSampled": 0, "markerHits": 0, "markersExpected": len(PAGE_MARKERS.get(league, ())),
            "error": f"{type(exc).__name__}: {exc}", "checkedAt": _now(),
            "durationMs": round((_now() - started) * 1000, 2),
            "role": "SECONDARY_INDEPENDENT" if league == "NCAAF" else "OFFICIAL_WATCHDOG",
        }


def _refresh_watchdogs(engine):
    results = {}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="sbb-schedule-watchdog") as pool:
        futures = {pool.submit(_fetch_watchdog, league, url): league for league, url in OFFICIAL_SCHEDULE_PAGES.items()}
        for future in as_completed(futures):
            league = futures[future]
            try:
                results[league] = future.result()
            except Exception as exc:
                results[league] = {"league": league, "url": OFFICIAL_SCHEDULE_PAGES[league], "success": False, "error": f"{type(exc).__name__}: {exc}", "checkedAt": _now()}
    engine.__sbbV6116ScheduleWatchdogs = results
    engine.__sbbV6116ScheduleWatchdogsAt = _now()
    return results


def _watchdog_loop(engine):
    while getattr(engine, "running", True):
        try:
            _refresh_watchdogs(engine)
        except Exception:
            pass
        for _ in range(max(1, WATCHDOG_SECONDS // 5)):
            if not getattr(engine, "running", True):
                return
            time.sleep(5)


def _install_engine_patches(engine):
    cls = v610.CertificationEngine
    if getattr(cls, "__sbbV6116OfficialScheduleWatchdogs", False):
        return
    # v6.1.1 has already installed its hardened collectors before this layer starts.
    cls._nfl_pages = _nfl_pages_v6116
    cls._collect_epl = _collect_epl_v6116

    if not hasattr(cls, "__sbbV6116OriginalHealth"):
        cls.__sbbV6116OriginalHealth = cls.health
    original_health = cls.__sbbV6116OriginalHealth

    def health(self):
        payload = original_health(self)
        payload["officialScheduleWatchdogsVersion"] = VERSION
        payload["officialScheduleWatchdogs"] = dict(getattr(self, "__sbbV6116ScheduleWatchdogs", {}) or {})
        payload["officialScheduleWatchdogsCheckedAt"] = float(getattr(self, "__sbbV6116ScheduleWatchdogsAt", 0.0) or 0.0)
        payload.setdefault("hardening", {}).update({
            "nflCurrentByWeekScheduleRoute": True,
            "eplOfficialScheduleFallback": True,
            "trustedExplicitSlateDateRehome": True,
            "officialSchedulePageWatchdogs": True,
            "ncaafFbschedulesSecondaryOnly": True,
        })
        return payload

    cls.health = health
    cls.__sbbV6116OfficialScheduleWatchdogs = True


def engine():
    return _ENGINE


def _install_into_server():
    global _ENGINE
    deadline = _now() + 180
    while _now() < deadline:
        base_engine = v611.engine()
        if base_engine is not None:
            break
        time.sleep(0.25)
    else:
        return
    _install_slate_date_rehome()
    _install_engine_patches(base_engine)
    _ENGINE = base_engine
    try:
        import sys
        server = sys.modules.get("__main__")
        if server is not None:
            server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update({
                "officialScheduleWatchdogsVersion": VERSION,
                "nflCurrentScheduleRoute": True,
                "eplOfficialScheduleFallback": True,
                "trustedSlateDateRehome": True,
                "productionAuthority": False,
            })
    except Exception:
        pass
    threading.Thread(target=_watchdog_loop, args=(base_engine,), daemon=True, name="sbb-canonical-official-schedule-watchdogs").start()
    # Force one reconciliation soon so repaired NFL/EPL collectors and MLB date
    # re-homing are exercised without waiting for the normal full-cycle interval.
    def reconcile_once():
        time.sleep(2)
        try:
            base_engine.run_horizon()
        except Exception as exc:
            base_engine.last_error = f"v6.1.16 official schedule reconcile: {type(exc).__name__}: {exc}"
    threading.Thread(target=reconcile_once, daemon=True, name="sbb-canonical-v6116-reconcile").start()


def install():
    global _INSTALLED
    with _PATCH_LOCK:
        if _INSTALLED or not ENABLED:
            return
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-canonical-official-schedule-install-v6116").start()

"""Sports Big Board v6.1.16 official schedule watchdogs and canonical date repair.

Shadow-only canonical certification hardening:
* Premier League: use the current Premier League SDP matches feed first and retain
  the legacy PulseLive collector only as a compatibility fallback.
* NFL: use the current nfl.com /by-week/week-N schedule URLs and require the
  exact requested week page to parse before zero-event dates can be trusted.
* MLB/all leagues: canonical sports-day bucketing is explicit-date first and then
  America/New_York kickoff date, never the UTC calendar date of an ISO timestamp.
  Existing clear UTC-day leaks are re-homed in-place without changing event IDs.
* All seven configured schedule pages are surfaced as watchdog contracts. Healthy
  structured adapters remain primary; NCAAF FBSchedules is secondary-independent
  evidence only and can never become authoritative by this layer.

This module never changes production slate authority.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from . import canonical_shadow_v600 as shadow
from . import canonical_certification_v610 as v610
from . import canonical_certification_v611 as v611

VERSION = "6.1.16-official-schedule-watchdogs-1"
ENABLED = str(os.environ.get("SBB_CANONICAL_SCHEDULE_WATCHDOG_ENABLED") or "1").strip().lower() not in {"0", "false", "no", "off"}
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_PATCHED = False
_ENGINE = None

EPL_SDP_BASE = str(os.environ.get("SBB_CANONICAL_EPL_SDP_BASE") or "https://sdp-prem-prod.premier-league-prod.pulselive.com").rstrip("/")

OFFICIAL_SCHEDULE_CONTRACTS = {
    "EPL": {
        "page": "https://www.premierleague.com/en/matches/premier-league/2026-27/matchweek-4",
        "role": "AUTHORITATIVE_FALLBACK",
        "primary": "PREMIER_LEAGUE_PULSE",
        "structured": f"{EPL_SDP_BASE}/api/v2/matches",
    },
    "NFL": {
        "page": "https://www.nfl.com/schedules",
        "role": "AUTHORITATIVE_PAGE",
        "primary": "NFL_COM_SCHEDULE",
        "structured": "https://www.nfl.com/schedules/{season}/by-week/week-{week}",
    },
    "MLB": {
        "page": "https://www.mlb.com/schedule",
        "role": "WATCHDOG_DATE_CONTRACT",
        "primary": "MLB_STATS_API",
        "structured": "https://statsapi.mlb.com/api/v1/schedule",
    },
    "NBA": {
        "page": "https://www.nba.com/schedule",
        "role": "WATCHDOG",
        "primary": "NBA_CDN_SCHEDULE",
        "structured": v610.NBA_SCHEDULE_URL,
    },
    "MLS": {
        "page": "https://www.mlssoccer.com/schedule/scores",
        "role": "WATCHDOG",
        "primary": "MLS_STATS_API",
        "structured": "https://stats-api.mlssoccer.com",
    },
    "NHL": {
        "page": "https://www.nhl.com/schedule",
        "role": "WATCHDOG",
        "primary": "NHL_WEB_API",
        "structured": "https://api-web.nhle.com",
    },
    "NCAAF": {
        "page": "https://fbschedules.com/college-football-schedule/",
        "role": "SECONDARY_INDEPENDENT_REFERENCE",
        "primary": "NCAA_SD_DATA",
        "structured": "https://sdataprod.ncaa.com/",
    },
}


def _now():
    return time.time()


def _clean(value):
    return str(value or "").strip()


def _parse_dt(value):
    raw = _clean(value)
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _sports_day(event, fallback=""):
    """Return the SBB sports day, explicitly preferring the ET/local slate date."""
    event = event or {}
    for key in ("__sbbDate", "canonicalSlateDate", "gameDate", "slateDate", "eventDate", "match_date"):
        value = shadow._day(event.get(key))
        if value:
            return value
    # A full timestamp in `date` is an instant, not a slate-day declaration.
    for key in ("scheduledAt", "startTime", "startDate", "dateTime", "datetime", "date"):
        raw = event.get(key)
        if isinstance(raw, str) and ("T" in raw or ":" in raw):
            dt = _parse_dt(raw)
            if dt is not None:
                return dt.astimezone(shadow.ET).date().isoformat()
    raw_day = shadow._day(event.get("date"))
    if raw_day:
        return raw_day
    return shadow._day(fallback)


def _epl_season(day_from, day_to):
    midpoint = date.fromisoformat(day_from) + (date.fromisoformat(day_to) - date.fromisoformat(day_from)) / 2
    return midpoint.year if midpoint.month >= 7 else midpoint.year - 1


def _epl_team(raw):
    raw = raw if isinstance(raw, dict) else {}
    return v610._team(
        raw.get("name") or raw.get("shortName") or raw.get("abbr"),
        raw.get("abbr") or raw.get("shortName"),
    )


def _epl_fixture(raw, wanted_days):
    if not isinstance(raw, dict):
        return None
    kickoff = raw.get("kickoff")
    if isinstance(kickoff, dict):
        scheduled = v610._iso_from_epoch(kickoff.get("millis")) or _clean(kickoff.get("label") or kickoff.get("date"))
    else:
        scheduled = _clean(kickoff)
    day = v610._day_from_datetime(scheduled)
    if day not in wanted_days:
        return None
    home = raw.get("homeTeam") if isinstance(raw.get("homeTeam"), dict) else {}
    away = raw.get("awayTeam") if isinstance(raw.get("awayTeam"), dict) else {}
    if not home or not away:
        return None
    home_team, away_team = _epl_team(home), _epl_team(away)
    if not home_team.get("displayName") or not away_team.get("displayName"):
        return None
    return {
        "competitionId": "EPL",
        "__sbbDate": day,
        "canonicalSlateDate": day,
        "eventId": _clean(raw.get("matchId") or raw.get("id")),
        "scheduledAt": scheduled,
        "status": _clean(raw.get("period") or raw.get("status") or "SCHEDULED"),
        "away": away_team,
        "home": home_team,
        "awayScore": away.get("score"),
        "homeScore": home.get("score"),
        "venue": raw.get("ground") or {},
        "name": f"{away_team.get('displayName')} @ {home_team.get('displayName')}",
    }


def _collect_epl_v6116(self, day_from, day_to):
    league = "EPL"
    source = v610.SOURCE_DEFS[league]["authoritative"]
    days = v610._date_range(day_from, day_to)
    season = _epl_season(day_from, day_to)
    params = {"competition": 8, "season": season, "_limit": 500, "_sort": "kickoff:asc"}
    url = f"{EPL_SDP_BASE}/api/v2/matches?{urlencode(params)}"
    try:
        payload = self._http(url, headers={"Accept": "application/json", "Referer": OFFICIAL_SCHEDULE_CONTRACTS["EPL"]["page"]}, cache_seconds=900)
        rows = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise RuntimeError("Premier League SDP response missing data[]")
        # A Premier League season must contain fixtures. Treat an empty season as
        # unproven so it cannot manufacture 15 successful zero slates.
        if not rows:
            raise RuntimeError("Premier League SDP returned zero season fixtures")
        wanted = set(days)
        groups = defaultdict(list)
        for row in rows:
            event = _epl_fixture(row, wanted)
            if event:
                groups[event["__sbbDate"]].append(event)
        count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE")
        self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, True, count, "", url)
        self.__sbbV6116EplPath = "SDP_V2_MATCHES"
        return count
    except Exception as exc:
        self.__sbbV6116EplPrimaryError = f"{type(exc).__name__}: {exc}"
        # Keep the v6.1.1 PulseLive adapter as a compatibility fallback. It remains
        # fail-closed and records its own coverage/health if it also fails.
        result = self.__sbbV6116OriginalEpl(day_from, day_to)
        self.__sbbV6116EplPath = "LEGACY_PULSE_FALLBACK"
        return result


def _nfl_pages_v6116(self, days):
    pages = set()
    required_by_day = {}
    for day_str in days:
        d = date.fromisoformat(day_str)
        season = d.year if d.month >= 7 else d.year - 1
        kickoff = self._labor_day(season) + timedelta(days=3)
        regular_end = kickoff + timedelta(days=7 * 18)
        required = set()
        if kickoff <= d < regular_end:
            week = max(1, min(18, ((d - kickoff).days // 7) + 1))
            required.add((season, "REG", week))
            for w in {max(1, week - 1), week, min(18, week + 1)}:
                pages.add((season, "REG", w, f"https://www.nfl.com/schedules/{season}/by-week/week-{w}"))
        elif d < kickoff:
            # Preseason remains a compatibility path. Do not let an unverified
            # generic page certify a requested date.
            for week in range(1, 4):
                required.add((season, "PRE", week))
                pages.add((season, "PRE", week, f"https://www.nfl.com/schedules/{season}/preseason/week-{week}"))
        else:
            for week in range(1, 5):
                required.add((season, "POST", week))
                pages.add((season, "POST", week, f"https://www.nfl.com/schedules/{season}/postseason/week-{week}"))
        required_by_day[day_str] = required
    return sorted(pages), required_by_day


def _collect_nfl_v6116(self, day_from, day_to):
    league, source = "NFL", v610.SOURCE_DEFS["NFL"]["authoritative"]
    days = v610._date_range(day_from, day_to)
    pages, required_by_day = _nfl_pages_v6116(self, days)
    groups = defaultdict(list)
    recognized_pages = set()
    errors, seen = [], set()
    for season, stage, week, url in pages:
        try:
            text = self._http(url, headers={"Accept": "text/html,*/*", "Referer": OFFICIAL_SCHEDULE_CONTRACTS["NFL"]["page"]}, as_text=True, cache_seconds=900)
            page_events = []
            for blob in self._nfl_json_blobs(text):
                for obj in v610._walk(blob):
                    event = self._nfl_event_from_dict(obj)
                    if event:
                        page_events.append(event)
            page_events.extend(v611._nfl_events_from_html(text, season))
            deduped, page_seen = [], set()
            for event in page_events:
                key = (event.get("eventId"), event.get("__sbbDate"), v610._norm((event.get("away") or {}).get("displayName")), v610._norm((event.get("home") or {}).get("displayName")))
                if key in page_seen:
                    continue
                page_seen.add(key)
                deduped.append(event)
            if not deduped:
                raise RuntimeError(f"NFL official week page contained no recognized schedule events ({stage}{week})")
            recognized_pages.add((season, stage, week))
            for event in deduped:
                key = (event.get("eventId"), event.get("__sbbDate"))
                if key in seen:
                    continue
                seen.add(key)
                if event.get("__sbbDate") in days:
                    groups[event["__sbbDate"]].append(event)
        except Exception as exc:
            errors.append(f"{stage}{week}: {type(exc).__name__}: {exc}")
    # A date is proven only when every official page required for that date was
    # successfully parsed. This prevents a different week page from legitimizing
    # an incorrect zero-game result.
    success_days = {day for day in days if required_by_day.get(day) and required_by_day[day] <= recognized_pages}
    day_errors = {day: "NFL official schedule page for requested week was not successfully recognized" for day in days if day not in success_days}
    count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE", success_days, day_errors)
    success = len(success_days) == len(days)
    error = "" if success else "; ".join(errors[-4:]) or f"{len(days)-len(success_days)} day(s) unproven"
    self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, success, count, error, OFFICIAL_SCHEDULE_CONTRACTS["NFL"]["structured"])
    self.__sbbV6116NflRecognizedPages = sorted(f"{a}:{b}:{c}" for a, b, c in recognized_pages)
    return count


def _patch_sports_day():
    shadow._event_day = _sports_day


def _safe_rehome_rows(engine):
    """Repair persisted UTC-day leaks when explicit/ET evidence proves the target day."""
    repaired = []
    try:
        with engine.store._lock, shadow.closing(engine.store._connect()) as conn:
            rows = conn.execute("SELECT canonical_event_id,competition_id,slate_date,scheduled_at,raw_json FROM canonical_event WHERE active=1").fetchall()
            for row in rows:
                item = dict(row)
                dt = _parse_dt(item.get("scheduled_at"))
                if dt is None:
                    continue
                et_day = dt.astimezone(shadow.ET).date().isoformat()
                stored = _clean(item.get("slate_date"))
                if not stored or stored == et_day:
                    continue
                try:
                    raw = json.loads(item.get("raw_json") or "{}")
                except Exception:
                    raw = {}
                explicit = ""
                for key in ("__sbbDate", "canonicalSlateDate", "gameDate", "slateDate", "eventDate", "match_date"):
                    explicit = shadow._day(raw.get(key))
                    if explicit:
                        break
                # Only mutate when the event's own explicit sports-day agrees with
                # the ET kickoff date. A one-day UTC offset is the intended repair;
                # larger discrepancies remain visible for operator review.
                if not explicit or explicit != et_day:
                    continue
                try:
                    delta = abs((date.fromisoformat(stored) - date.fromisoformat(et_day)).days)
                except Exception:
                    continue
                if delta != 1:
                    continue
                conn.execute("UPDATE canonical_event SET slate_date=?, updated_at=? WHERE canonical_event_id=?", (et_day, _now(), item["canonical_event_id"]))
                repaired.append({"canonicalEventId": item["canonical_event_id"], "league": item["competition_id"], "from": stored, "to": et_day})
            if repaired:
                conn.commit()
    except Exception as exc:
        return {"count": 0, "events": [], "error": f"{type(exc).__name__}: {exc}"}
    return {"count": len(repaired), "events": repaired[:50], "error": ""}


def _watchdogs(self):
    rows = {}
    for league, cfg in OFFICIAL_SCHEDULE_CONTRACTS.items():
        source = v610.SOURCE_DEFS.get(league, {}).get("authoritative") or cfg.get("primary")
        auth = self.source_health.get(f"{league}:{source}") or {}
        indep = self.source_health.get(f"{league}:{v610.INDEPENDENT_SOURCE}") or {}
        auth_success = auth.get("success") if auth else None
        indep_success = indep.get("success") if indep else None
        auth_count = int(auth.get("eventCount") or 0) if auth else None
        indep_count = int(indep.get("eventCount") or 0) if indep else None
        if auth_success is False:
            state = "AUTHORITATIVE_FAILED"
        elif auth_success and indep_success and auth_count != indep_count and league != "NCAAF":
            state = "COUNT_MISMATCH"
        elif auth_success is True:
            state = "OK"
        else:
            state = "WAITING"
        rows[league] = {
            **cfg,
            "state": state,
            "authoritativeSuccess": auth_success,
            "authoritativeCount": auth_count,
            "independentSuccess": indep_success,
            "independentCount": indep_count,
            "authoritativeEndpoint": _clean(auth.get("endpoint")),
            "authoritativeError": _clean(auth.get("error")),
        }
    rows["EPL"]["collectorPath"] = getattr(self, "__sbbV6116EplPath", "WAITING")
    rows["EPL"]["primaryError"] = getattr(self, "__sbbV6116EplPrimaryError", "")
    rows["NFL"]["recognizedPages"] = list(getattr(self, "__sbbV6116NflRecognizedPages", []))
    return rows


def _run_horizon_v6116(self):
    stats = self.__sbbV6116OriginalRunHorizon()
    repair = _safe_rehome_rows(self)
    if repair.get("count"):
        today = datetime.now(shadow.ET).date()
        days = [(today + timedelta(days=o)).isoformat() for o in range(-shadow.LOOKBACK_DAYS, shadow.LOOKAHEAD_DAYS + 1)]
        refreshed = v611._refresh_production_comparisons(self, days)
        changes = 0
        for day in days:
            for league in shadow.SUPPORTED_LEAGUES:
                _slate, changed = self.store.compile_slate(day, league, "OFFICIAL_SCHEDULE_WATCHDOG_REPAIR")
                changes += int(bool(changed))
        try:
            v611._rebuild_readiness_cache(self)
        except Exception:
            pass
        stats["scheduleDateRepairComparisonRefreshes"] = refreshed
        stats["scheduleDateRepairSlateChanges"] = changes
    stats["officialScheduleWatchdogVersion"] = VERSION
    stats["slateDateRepairs"] = repair
    stats["officialScheduleWatchdogs"] = _watchdogs(self)
    self.last_stats = stats
    return stats


def _health_v6116(self):
    payload = self.__sbbV6116OriginalHealth()
    payload["version"] = VERSION
    payload["officialScheduleWatchdogs"] = _watchdogs(self)
    payload["officialScheduleWatchdogPolicy"] = {
        "productionAuthority": False,
        "structuredAdaptersRemainPrimary": True,
        "eplOfficialSdpFallback": True,
        "nflCurrentOfficialWeekPages": True,
        "sportsDayTimezone": "America/New_York",
        "ncaafFbschedulesAuthoritative": False,
    }
    payload["lastSlateDateRepair"] = (self.last_stats or {}).get("slateDateRepairs") or {"count": 0, "events": [], "error": ""}
    return payload


def _install_engine_patches():
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    _patch_sports_day()
    cls = v610.CertificationEngine
    if not hasattr(cls, "__sbbV6116OriginalEpl"):
        cls.__sbbV6116OriginalEpl = cls._collect_epl
    if not hasattr(cls, "__sbbV6116OriginalRunHorizon"):
        cls.__sbbV6116OriginalRunHorizon = cls.run_horizon
    if not hasattr(cls, "__sbbV6116OriginalHealth"):
        cls.__sbbV6116OriginalHealth = cls.health
    cls._collect_epl = _collect_epl_v6116
    cls._nfl_pages = _nfl_pages_v6116
    cls._collect_nfl = _collect_nfl_v6116
    cls.run_horizon = _run_horizon_v6116
    cls.health = _health_v6116


def engine():
    return _ENGINE


def _install_into_server():
    global _ENGINE
    server = None
    base_engine = None
    # v6.1.4+ startup can take longer than the old 120 s install window on a cold VM.
    while True:
        server = sys.modules.get("__main__")
        base_engine = v611.engine()
        if server and base_engine and hasattr(server, "Handler") and hasattr(server, "send_json"):
            break
        time.sleep(0.5)
    _install_engine_patches()
    _ENGINE = base_engine
    try:
        server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update({
            "officialScheduleWatchdogVersion": VERSION,
            "officialSchedulePages": {k: v["page"] for k, v in OFFICIAL_SCHEDULE_CONTRACTS.items()},
            "productionAuthority": False,
        })
    except Exception:
        pass

    # Trigger one reconciliation using the repaired adapters/date semantics. The
    # existing certification worker continues to own all later cycles.
    def initial_reconcile():
        time.sleep(2)
        try:
            _ENGINE.run_horizon()
        except Exception as exc:
            _ENGINE.last_error = f"v6.1.16 official schedule reconcile: {type(exc).__name__}: {exc}"
    threading.Thread(target=initial_reconcile, daemon=True, name="sbb-canonical-schedule-watchdog-v6116-reconcile").start()


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED or not ENABLED:
            return
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-canonical-schedule-watchdog-install-v6116").start()

"""Sports Big Board v6.1 canonical schedule certification adapters.

Adds certification evidence to the v6 canonical shadow database without becoming
production event authority. Every supported league is checked through:
  * AUTHORITATIVE: a league/organizer-operated schedule source
  * INDEPENDENT: a separate direct ESPN raw schedule path

The module is deliberately fail-closed. A parser/source error records failed
coverage and cannot certify a slate. For today/future dates the latest coverage
result must also be fresh, so one old success cannot certify forever.
"""
from __future__ import annotations

import difflib
import html as html_lib
import json
import os
import re
import sys
import threading
import time
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import canonical_shadow_v600 as shadow

VERSION = "6.1.0-certification-1"
ENABLED = str(os.environ.get("SBB_CANONICAL_CERTIFICATION_ENABLED") or "1").strip().lower() not in {"0", "false", "no", "off"}
HTTP_TIMEOUT = max(3, int(os.environ.get("SBB_CANONICAL_CERT_HTTP_TIMEOUT") or 12))
FULL_SECONDS = max(300, int(os.environ.get("SBB_CANONICAL_CERT_FULL_SECONDS") or 900))
FRESH_SECONDS = max(FULL_SECONDS * 2, int(os.environ.get("SBB_CANONICAL_CERT_FRESH_SECONDS") or 3600))
NBA_SCHEDULE_URL = str(os.environ.get("SBB_CANONICAL_NBA_SCHEDULE_URL") or "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json").strip()
NBA_SCHEDULE_FALLBACK_URL = str(os.environ.get("SBB_CANONICAL_NBA_SCHEDULE_FALLBACK_URL") or "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json").strip()
MLS_SEASON_ID = str(os.environ.get("SBB_CANONICAL_MLS_SEASON_ID") or "MLS-SEA-0001KA").strip()
MLS_COMPETITION_ID = str(os.environ.get("SBB_CANONICAL_MLS_COMPETITION_ID") or "MLS-COM-000001").strip()
NCAA_SCOREBOARD_HASH = "7287cda610a9326931931080cb3a604828febe6fe3c9016a7e4a36db99efdb7c"

SOURCE_DEFS = {
    "MLB": {"authoritative": "MLB_STATS_API", "host": "statsapi.mlb.com"},
    "NFL": {"authoritative": "NFL_COM_SCHEDULE", "host": "nfl.com"},
    "NBA": {"authoritative": "NBA_CDN_SCHEDULE", "host": "cdn.nba.com"},
    "NHL": {"authoritative": "NHL_WEB_API", "host": "api-web.nhle.com"},
    "EPL": {"authoritative": "PREMIER_LEAGUE_PULSE", "host": "footballapi.pulselive.com"},
    "MLS": {"authoritative": "MLS_STATS_API", "host": "stats-api.mlssoccer.com"},
    "NCAAF": {"authoritative": "NCAA_SD_DATA", "host": "sdataprod.ncaa.com"},
}
INDEPENDENT_SOURCE = "ESPN_INDEPENDENT"

_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ENGINE = None


def _now():
    return time.time()


def _clean(v):
    return str(v or "").strip()


def _norm(v):
    return re.sub(r"[^a-z0-9]+", "", _clean(v).lower().replace("&", "and"))


def _date_range(day_from, day_to):
    start = date.fromisoformat(day_from)
    end = date.fromisoformat(day_to)
    out = []
    while start <= end:
        out.append(start.isoformat())
        start += timedelta(days=1)
    return out


def _iso_from_epoch(value):
    try:
        n = float(value)
    except Exception:
        return ""
    if n > 10_000_000_000:
        n /= 1000.0
    try:
        return datetime.fromtimestamp(n, timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return ""


def _day_from_datetime(value):
    raw = _clean(value)
    if not raw:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            return dt.date().isoformat()
        return dt.astimezone(shadow.ET).date().isoformat()
    except Exception:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%Y %I:%M:%S %p", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except Exception:
            continue
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except Exception:
            return ""
    return ""


def _team(name="", abbreviation="", **extra):
    out = {
        "name": _clean(name),
        "displayName": _clean(name),
        "abbreviation": _clean(abbreviation),
    }
    for k, v in extra.items():
        if v not in (None, ""):
            out[k] = v
    return out


def _dict_text(value):
    if isinstance(value, dict):
        return _clean(value.get("default") or value.get("name") or value.get("fullName") or value.get("label"))
    return _clean(value)


def _status_text(value):
    if isinstance(value, dict):
        value = value.get("detailedState") or value.get("abstractGameState") or value.get("state") or value.get("name") or value.get("status")
    return _clean(value or "SCHEDULED")


def _ncaaf_inclusion(event):
    ranks = []
    for side in ("away", "home"):
        team = event.get(side) if isinstance(event.get(side), dict) else {}
        for key in ("rank", "teamRank", "curatedRank"):
            value = team.get(key)
            if isinstance(value, dict):
                value = value.get("current")
            try:
                rank = int(value)
            except Exception:
                rank = 0
            if 1 <= rank <= 25:
                ranks.append(rank)
                break
    if event.get("__sbbNcaafTop25") or ranks:
        return "INCLUDED", "NCAAF_TOP25"
    return "EXCLUDED", "NCAAF_OUTSIDE_TOP25"


class _ScriptCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_script = False
        self.current = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self.in_script = True
            self.current = []

    def handle_data(self, data):
        if self.in_script:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self.in_script:
            self.scripts.append("".join(self.current))
            self.current = []
            self.in_script = False


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _team_aliases(event, side):
    team = event.get(side) if isinstance(event.get(side), dict) else {}
    vals = []
    for k in ("abbreviation", "displayName", "name", "shortName", "teamName"):
        if team.get(k):
            vals.append(_norm(team.get(k)))
    return {x for x in vals if x}


def _row_aliases(row, side):
    vals = {_norm(row.get(f"{side}_name"))}
    try:
        raw = json.loads(row.get("raw_json") or "{}")
    except Exception:
        raw = {}
    vals.update(_team_aliases(raw, side))
    return {x for x in vals if x}


class CertificationEvidenceWriter:
    """Attach source evidence to the existing canonical identity when possible."""

    def __init__(self, shadow_engine):
        self.engine = shadow_engine
        self.store = shadow_engine.store

    def _match_existing(self, league, day, event):
        rows = self.store.events_for_day(day, league)
        incoming_away = _team_aliases(event, "away")
        incoming_home = _team_aliases(event, "home")
        if not incoming_away or not incoming_home:
            return ""
        def side_matches(incoming, existing):
            if incoming & existing:
                return True
            # Official NCAA/NFL/league feeds often spell teams differently from ESPN
            # (Ohio St vs Ohio State, Man Utd vs Manchester United). Allow a guarded
            # fuzzy alias match, but only when both matchup sides independently match.
            for a in incoming:
                for b in existing:
                    if min(len(a), len(b)) < 5:
                        continue
                    if a.startswith(b) or b.startswith(a):
                        return True
                    if difflib.SequenceMatcher(None, a, b).ratio() >= 0.82:
                        return True
            return False

        candidates = []
        for row in rows:
            if not side_matches(incoming_away, _row_aliases(row, "away")):
                continue
            if not side_matches(incoming_home, _row_aliases(row, "home")):
                continue
            candidates.append(row)
        if not candidates:
            return ""
        seq = shadow._event_sequence(event)
        if seq:
            seq_match = [x for x in candidates if _clean(x.get("event_sequence")) == seq]
            if len(seq_match) == 1:
                return seq_match[0]["canonical_event_id"]
            if len(seq_match) > 1:
                return ""
        if len(candidates) == 1:
            return candidates[0]["canonical_event_id"]
        incoming_time = shadow._epoch(shadow._scheduled_at(event))
        timed = []
        if incoming_time is not None:
            for row in candidates:
                t = shadow._epoch(row.get("scheduled_at"))
                if t is not None:
                    timed.append((abs(t - incoming_time), row))
        timed.sort(key=lambda x: x[0])
        if timed and timed[0][0] <= 2 * 3600 and (len(timed) == 1 or timed[1][0] - timed[0][0] >= 20 * 60):
            return timed[0][1]["canonical_event_id"]
        return ""

    @staticmethod
    def _sanitize(event):
        event = deepcopy(event)
        for side in ("away", "home"):
            team = event.get(side)
            if isinstance(team, dict):
                # Cross-provider team IDs are not identity-compatible. Provider event
                # IDs remain mapped separately; team aliases drive cross-source merge.
                team.pop("id", None)
                team.pop("uid", None)
        return event

    def observe_event(self, event, league, day, source, source_class):
        event = self._sanitize(event)
        if league == "NCAAF":
            inclusion_state, inclusion_reason = _ncaaf_inclusion(event)
        else:
            inclusion_state, inclusion_reason = "INCLUDED", "ALL_LEAGUE_EVENTS"
        existing_id = self._match_existing(league, day, event)
        if not existing_id:
            return self.engine.observe_event(
                event, league, day, source, source_class, inclusion_state, inclusion_reason
            )
        self.store.upsert_event(
            existing_id, league, day, event, source, "RESOLVED", inclusion_state, inclusion_reason
        )
        self.store.upsert_mappings(existing_id, shadow._provider_ids(event, source))
        self.store.record_schedule(existing_id, source, source_class, day, event)
        self.store.record_score(existing_id, source, event)
        self.engine.events_touched += 1
        return existing_id

    def snapshot(self, groups, days, league, source, source_class, success_days=None, errors=None):
        success_days = set(success_days if success_days is not None else days)
        errors = errors or {}
        total = 0
        for day in days:
            rows = list(groups.get(day) or []) if day in success_days else []
            seen = []
            for event in rows:
                event_id = self.observe_event(event, league, day, source, source_class)
                if event_id:
                    seen.append(event_id)
            self.store.record_source_coverage(
                day, league, source, source_class,
                success=(day in success_days), result_count=len(seen), error=errors.get(day, "")
            )
            total += len(seen)
        return total


class CertificationEngine:
    def __init__(self, server, shadow_engine):
        self.server = server
        self.shadow = shadow_engine
        self.store = shadow_engine.store
        self.writer = CertificationEvidenceWriter(shadow_engine)
        self.running = True
        self.last_run_at = 0.0
        self.last_error = ""
        self.last_stats = {}
        self.source_health = {}
        self._http_cache = {}

    def _headers(self, extra=None):
        out = {
            "User-Agent": "Mozilla/5.0 (SportsBigBoard/6.1; canonical certification)",
            "Accept": "application/json,text/plain,*/*",
        }
        if extra:
            out.update(extra)
        return out

    def _http(self, url, headers=None, as_text=False, cache_seconds=0):
        now = _now()
        cached = self._http_cache.get(url)
        if cached and cache_seconds and now - cached[0] <= cache_seconds:
            return cached[1]
        req = Request(url, headers=self._headers(headers))
        with urlopen(req, timeout=HTTP_TIMEOUT) as response:
            raw = response.read().decode("utf-8", "replace")
        value = raw if as_text else json.loads(raw)
        if cache_seconds:
            self._http_cache[url] = (now, value)
        return value

    def _mark_health(self, league, source, source_class, day_from, day_to, success, count=0, error="", endpoint=""):
        key = f"{league}:{source}"
        self.source_health[key] = {
            "league": league, "source": source, "sourceClass": source_class,
            "success": bool(success), "eventCount": int(count), "error": _clean(error),
            "dayFrom": day_from, "dayTo": day_to, "checkedAt": _now(), "endpoint": endpoint,
        }

    def _failed_range(self, league, source, source_class, days, error, endpoint=""):
        errors = {day: error for day in days}
        self.writer.snapshot({}, days, league, source, source_class, success_days=set(), errors=errors)
        self._mark_health(league, source, source_class, days[0], days[-1], False, 0, error, endpoint)
        return 0

    # ------------------------- INDEPENDENT -------------------------
    def _collect_espn_independent(self, league, day_from, day_to):
        days = _date_range(day_from, day_to)
        sport, competition = shadow.ESPN_DIRECT_COMPETITIONS[league]
        token_a, token_b = day_from.replace("-", ""), day_to.replace("-", "")
        params = {"dates": token_a if token_a == token_b else f"{token_a}-{token_b}", "limit": 1000}
        if league == "NCAAF":
            params["groups"] = 80
        url = f"{shadow.ESPN_SITE_API}/{sport}/{competition}/scoreboard?{urlencode(params)}"
        source = INDEPENDENT_SOURCE
        try:
            payload = self._http(url, cache_seconds=120)
            if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
                raise RuntimeError("ESPN scoreboard response missing events[]")
            groups = defaultdict(list)
            for raw in payload["events"]:
                scheduled = _clean(raw.get("date") if isinstance(raw, dict) else "")
                ts = shadow._epoch(scheduled)
                if ts is None:
                    continue
                event_day = datetime.fromtimestamp(ts, shadow.ET).date().isoformat()
                if event_day < day_from or event_day > day_to:
                    continue
                event = self.shadow._espn_event(raw, league, event_day)
                if event:
                    groups[event_day].append(event)
            count = self.writer.snapshot(groups, days, league, source, "INDEPENDENT")
            self._mark_health(league, source, "INDEPENDENT", day_from, day_to, True, count, "", url)
            return count
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            return self._failed_range(league, source, "INDEPENDENT", days, error, url)

    # ------------------------- MLB -------------------------
    def _collect_mlb(self, day_from, day_to):
        league, source = "MLB", SOURCE_DEFS["MLB"]["authoritative"]
        days = _date_range(day_from, day_to)
        url = "https://statsapi.mlb.com/api/v1/schedule?" + urlencode({
            "sportId": 1, "startDate": day_from, "endDate": day_to,
            "hydrate": "team,venue",
        })
        try:
            payload = self._http(url, cache_seconds=120)
            if not isinstance(payload, dict) or not isinstance(payload.get("dates"), list):
                raise RuntimeError("MLB schedule response missing dates[]")
            groups = defaultdict(list)
            for block in payload["dates"]:
                if not isinstance(block, dict):
                    continue
                day = _clean(block.get("date"))[:10]
                if day not in days:
                    continue
                for game in block.get("games") or []:
                    teams = game.get("teams") or {}
                    away_raw = (teams.get("away") or {}).get("team") or {}
                    home_raw = (teams.get("home") or {}).get("team") or {}
                    if not away_raw or not home_raw:
                        continue
                    event = {
                        "competitionId": league, "__sbbDate": day,
                        "eventId": _clean(game.get("gamePk")), "gamePk": _clean(game.get("gamePk")),
                        "scheduledAt": _clean(game.get("gameDate")),
                        "status": _status_text(game.get("status")),
                        "away": _team(away_raw.get("name"), away_raw.get("abbreviation")),
                        "home": _team(home_raw.get("name"), home_raw.get("abbreviation")),
                        "venue": game.get("venue") or {},
                        "gameNumber": game.get("gameNumber") or "",
                        "name": f"{away_raw.get('name','')} @ {home_raw.get('name','')}",
                    }
                    groups[day].append(event)
            count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE")
            self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, True, count, "", url)
            return count
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            return self._failed_range(league, source, "AUTHORITATIVE", days, error, url)

    # ------------------------- NBA -------------------------
    def _collect_nba(self, day_from, day_to):
        league, source = "NBA", SOURCE_DEFS["NBA"]["authoritative"]
        days = _date_range(day_from, day_to)
        url = NBA_SCHEDULE_URL
        headers = {"Referer": "https://www.nba.com/", "Origin": "https://www.nba.com"}
        try:
            payload = None
            last_exc = None
            for candidate in dict.fromkeys((NBA_SCHEDULE_URL, NBA_SCHEDULE_FALLBACK_URL)):
                if not candidate:
                    continue
                try:
                    payload = self._http(candidate, headers=headers, cache_seconds=1800)
                    url = candidate
                    break
                except Exception as exc:
                    last_exc = exc
            if payload is None:
                raise last_exc or RuntimeError("NBA schedule endpoints unavailable")
            schedule = payload.get("leagueSchedule") if isinstance(payload, dict) else None
            blocks = schedule.get("gameDates") if isinstance(schedule, dict) else None
            if not isinstance(blocks, list):
                raise RuntimeError("NBA schedule response missing leagueSchedule.gameDates[]")
            groups = defaultdict(list)
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                day = _day_from_datetime(block.get("gameDate"))
                for game in block.get("games") or []:
                    if not day:
                        day = _day_from_datetime(game.get("gameDateTimeUTC") or game.get("gameDateTimeEst"))
                    if day not in days:
                        continue
                    away_raw, home_raw = game.get("awayTeam") or {}, game.get("homeTeam") or {}
                    if not away_raw or not home_raw:
                        continue
                    event = {
                        "competitionId": league, "__sbbDate": day,
                        "eventId": _clean(game.get("gameId") or game.get("gameCode")),
                        "scheduledAt": _clean(game.get("gameDateTimeUTC") or game.get("gameDateTimeEst") or ""),
                        "status": _clean(game.get("gameStatusText") or game.get("gameStatus") or "SCHEDULED"),
                        "away": _team(away_raw.get("teamName") or away_raw.get("teamCity"), away_raw.get("teamTricode")),
                        "home": _team(home_raw.get("teamName") or home_raw.get("teamCity"), home_raw.get("teamTricode")),
                        "gameNumber": game.get("gameSequence") or "",
                        "name": _clean(game.get("gameLabel") or ""),
                    }
                    groups[day].append(event)
            count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE")
            self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, True, count, "", url)
            return count
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            return self._failed_range(league, source, "AUTHORITATIVE", days, error, url)

    # ------------------------- NHL -------------------------
    def _collect_nhl(self, day_from, day_to):
        league, source = "NHL", SOURCE_DEFS["NHL"]["authoritative"]
        days = _date_range(day_from, day_to)
        groups = defaultdict(list)
        success_days, errors = set(), {}
        for day in days:
            url = f"https://api-web.nhle.com/v1/schedule/{day}"
            try:
                payload = self._http(url, cache_seconds=120)
                weeks = payload.get("gameWeek") if isinstance(payload, dict) else None
                if not isinstance(weeks, list):
                    raise RuntimeError("NHL schedule response missing gameWeek[]")
                success_days.add(day)
                seen_ids = set()
                for block in weeks:
                    if not isinstance(block, dict) or _clean(block.get("date")) != day:
                        continue
                    for game in block.get("games") or []:
                        gid = _clean(game.get("id"))
                        if gid and gid in seen_ids:
                            continue
                        if gid:
                            seen_ids.add(gid)
                        away_raw, home_raw = game.get("awayTeam") or {}, game.get("homeTeam") or {}
                        away_name = " ".join(x for x in (_dict_text(away_raw.get("placeName")), _dict_text(away_raw.get("commonName"))) if x).strip()
                        home_name = " ".join(x for x in (_dict_text(home_raw.get("placeName")), _dict_text(home_raw.get("commonName"))) if x).strip()
                        if not away_name or not home_name:
                            continue
                        groups[day].append({
                            "competitionId": league, "__sbbDate": day,
                            "eventId": gid, "scheduledAt": _clean(game.get("startTimeUTC")),
                            "status": _clean(game.get("gameState") or "SCHEDULED"),
                            "away": _team(away_name, away_raw.get("abbrev")),
                            "home": _team(home_name, home_raw.get("abbrev")),
                            "venue": _dict_text(game.get("venue")),
                        })
            except Exception as exc:
                errors[day] = f"{type(exc).__name__}: {exc}"
        count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE", success_days, errors)
        success = len(success_days) == len(days)
        err = "" if success else f"{len(days)-len(success_days)} day(s) failed"
        self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, success, count, err, "https://api-web.nhle.com/v1/schedule/{date}")
        return count

    # ------------------------- EPL -------------------------
    def _collect_epl(self, day_from, day_to):
        league, source = "EPL", SOURCE_DEFS["EPL"]["authoritative"]
        days = _date_range(day_from, day_to)
        headers = {"Origin": "https://www.premierleague.com", "Referer": "https://www.premierleague.com/"}
        season_url = "https://footballapi.pulselive.com/football/competitions/1/compseasons?page=0&pageSize=100&sort=desc"
        try:
            season_payload = self._http(season_url, headers=headers, cache_seconds=3600)
            seasons = season_payload.get("content") if isinstance(season_payload, dict) else season_payload
            if not isinstance(seasons, list) or not seasons:
                raise RuntimeError("Premier League season response missing season list")
            midpoint = date.fromisoformat(days[len(days)//2])
            start_year = midpoint.year if midpoint.month >= 7 else midpoint.year - 1
            wanted = {f"{start_year}/{str(start_year+1)[-2:]}", f"{start_year}-{str(start_year+1)[-2:]}"}
            chosen = None
            for season in seasons:
                label = _clean((season or {}).get("label") or (season or {}).get("name"))
                if label in wanted or str(start_year) in label:
                    chosen = season
                    break
            chosen = chosen or seasons[0]
            season_id = _clean((chosen or {}).get("id"))
            if not season_id:
                raise RuntimeError("Premier League season ID unavailable")
            fixture_url = "https://footballapi.pulselive.com/football/fixtures?" + urlencode({
                "comps": 1, "compSeasons": season_id, "page": 0, "pageSize": 1000, "sort": "asc",
            })
            payload = self._http(fixture_url, headers=headers, cache_seconds=900)
            rows = payload.get("content") if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise RuntimeError("Premier League fixtures response missing content[]")
            groups = defaultdict(list)
            for fixture in rows:
                if not isinstance(fixture, dict):
                    continue
                kickoff = fixture.get("kickoff") or {}
                scheduled = _iso_from_epoch(kickoff.get("millis")) or _clean(kickoff.get("label"))
                day = _day_from_datetime(scheduled)
                if day not in days:
                    continue
                teams = fixture.get("teams") or []
                if len(teams) < 2:
                    continue
                away_raw = (teams[1].get("team") if isinstance(teams[1], dict) else {}) or {}
                home_raw = (teams[0].get("team") if isinstance(teams[0], dict) else {}) or {}
                away_name = _clean(away_raw.get("name") or away_raw.get("shortName"))
                home_name = _clean(home_raw.get("name") or home_raw.get("shortName"))
                if not away_name or not home_name:
                    continue
                groups[day].append({
                    "competitionId": league, "__sbbDate": day,
                    "eventId": _clean(fixture.get("id")), "scheduledAt": scheduled,
                    "status": _clean(fixture.get("status") or fixture.get("phase") or "SCHEDULED"),
                    "away": _team(away_name, away_raw.get("shortName")),
                    "home": _team(home_name, home_raw.get("shortName")),
                    "venue": fixture.get("ground") or {},
                })
            count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE")
            self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, True, count, "", fixture_url)
            return count
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            return self._failed_range(league, source, "AUTHORITATIVE", days, error, season_url)

    # ------------------------- MLS -------------------------
    def _collect_mls(self, day_from, day_to):
        league, source = "MLS", SOURCE_DEFS["MLS"]["authoritative"]
        days = _date_range(day_from, day_to)
        base = f"https://stats-api.mlssoccer.com/matches/seasons/{MLS_SEASON_ID}"
        params = {
            "match_date[gte]": day_from, "match_date[lte]": day_to,
            "competition_id": MLS_COMPETITION_ID, "per_page": 1000,
            "sort": "planned_kickoff_time:asc,home_team_name:asc",
        }
        url = base + "?" + urlencode(params)
        try:
            payload = self._http(url, headers={"Accept": "application/json", "User-Agent": "curl/8.0 SportsBigBoard/6.1"}, cache_seconds=300)
            rows = payload.get("schedule") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise RuntimeError("MLS schedule response missing schedule[]")
            groups = defaultdict(list)
            for match in rows:
                if not isinstance(match, dict):
                    continue
                scheduled = _clean(match.get("planned_kickoff_time") or match.get("kickoff_time"))
                day = _day_from_datetime(scheduled) or _clean(match.get("match_date"))[:10]
                if day not in days:
                    continue
                away_name = _clean(match.get("away_team_name") or match.get("away_team_short_name"))
                home_name = _clean(match.get("home_team_name") or match.get("home_team_short_name"))
                if not away_name or not home_name:
                    continue
                event_id = _clean(match.get("match_id") or match.get("matchId") or match.get("id"))
                if not event_id:
                    event_id = "mls:" + shadow._payload_hash([day, away_name, home_name, scheduled])[:20]
                groups[day].append({
                    "competitionId": league, "__sbbDate": day,
                    "eventId": event_id, "scheduledAt": scheduled,
                    "status": _clean(match.get("match_status") or match.get("status") or "SCHEDULED"),
                    "away": _team(away_name, match.get("away_team_abbreviation")),
                    "home": _team(home_name, match.get("home_team_abbreviation")),
                    "venue": match.get("venue") or match.get("stadium") or "",
                })
            count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE")
            self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, True, count, "", url)
            return count
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            return self._failed_range(league, source, "AUTHORITATIVE", days, error, url)

    # ------------------------- NCAAF -------------------------
    def _collect_ncaaf(self, day_from, day_to):
        league, source = "NCAAF", SOURCE_DEFS["NCAAF"]["authoritative"]
        days = _date_range(day_from, day_to)
        groups = defaultdict(list)
        success_days, errors = set(), {}
        for day in days:
            variables = {
                "sportCode": "MFB", "division": 11,
                "seasonYear": int(day[:4]), "contestDate": day,
            }
            extensions = {"persistedQuery": {"version": 1, "sha256Hash": NCAA_SCOREBOARD_HASH}}
            url = "https://sdataprod.ncaa.com/?" + urlencode({
                "extensions": json.dumps(extensions, separators=(",", ":")),
                "variables": json.dumps(variables, separators=(",", ":")),
            })
            try:
                payload = self._http(url, cache_seconds=180)
                data = payload.get("data") if isinstance(payload, dict) else None
                contests = data.get("contests") if isinstance(data, dict) else None
                if not isinstance(contests, list):
                    raise RuntimeError("NCAA scoreboard response missing data.contests[]")
                success_days.add(day)
                for contest in contests:
                    teams = contest.get("teams") if isinstance(contest, dict) else None
                    if not isinstance(teams, list):
                        continue
                    home_raw = next((x for x in teams if isinstance(x, dict) and x.get("isHome") is True), None)
                    away_raw = next((x for x in teams if isinstance(x, dict) and x.get("isHome") is False), None)
                    if not home_raw or not away_raw:
                        continue
                    scheduled = _iso_from_epoch(contest.get("startTimeEpoch"))
                    event = {
                        "competitionId": league, "__sbbDate": day,
                        "eventId": _clean(contest.get("contestId")), "scheduledAt": scheduled,
                        "status": _clean(contest.get("gameState") or contest.get("finalMessage") or "SCHEDULED"),
                        "away": _team(away_raw.get("nameShort"), away_raw.get("name6Char"), rank=away_raw.get("teamRank")),
                        "home": _team(home_raw.get("nameShort"), home_raw.get("name6Char"), rank=home_raw.get("teamRank")),
                        "period": contest.get("currentPeriod"), "clock": contest.get("contestClock"),
                    }
                    event["__sbbNcaafTop25"] = _ncaaf_inclusion(event)[0] == "INCLUDED"
                    groups[day].append(event)
            except Exception as exc:
                errors[day] = f"{type(exc).__name__}: {exc}"
        count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE", success_days, errors)
        success = len(success_days) == len(days)
        err = "" if success else f"{len(days)-len(success_days)} day(s) failed"
        self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, success, count, err, "https://sdataprod.ncaa.com/")
        return count

    # ------------------------- NFL -------------------------
    @staticmethod
    def _nfl_team(value):
        if isinstance(value, str):
            return _team(value)
        if not isinstance(value, dict):
            return _team("")
        name = _clean(
            value.get("fullName") or value.get("displayName") or value.get("name") or
            value.get("teamName") or value.get("nickName") or value.get("nickname")
        )
        abbr = _clean(value.get("abbr") or value.get("abbreviation") or value.get("teamAbbr") or value.get("triCode"))
        return _team(name, abbr)

    @staticmethod
    def _nfl_json_blobs(text):
        parser = _ScriptCollector()
        parser.feed(text)
        blobs = []
        decoder = json.JSONDecoder()
        for script in parser.scripts:
            s = html_lib.unescape(script).strip()
            if not s:
                continue
            if s[0] in "[{":
                try:
                    blobs.append(json.loads(s))
                    continue
                except Exception:
                    pass
            # Decode object/array tails from common __NEXT_DATA__/hydration assignments.
            for marker in ("{", "["):
                idx = s.find(marker)
                if idx < 0:
                    continue
                try:
                    obj, _ = decoder.raw_decode(s[idx:])
                    blobs.append(obj)
                    break
                except Exception:
                    continue
        return blobs

    def _nfl_event_from_dict(self, obj):
        if not isinstance(obj, dict):
            return None
        home = obj.get("homeTeam") or obj.get("home") or obj.get("homeTeamInfo")
        away = obj.get("awayTeam") or obj.get("away") or obj.get("visitorTeam") or obj.get("awayTeamInfo")
        teams = obj.get("teams")
        if (not home or not away) and isinstance(teams, dict):
            home = home or teams.get("home")
            away = away or teams.get("away") or teams.get("visitor")
        home_team, away_team = self._nfl_team(home), self._nfl_team(away)
        if not home_team.get("name") or not away_team.get("name"):
            return None
        scheduled = ""
        for key in ("gameDateTime", "startDateTime", "dateTime", "kickoffTime", "startTime", "gameTime", "gameDate", "date"):
            value = obj.get(key)
            if value not in (None, ""):
                if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
                    scheduled = _iso_from_epoch(value)
                else:
                    scheduled = _clean(value)
                if scheduled:
                    break
        day = _day_from_datetime(scheduled)
        if not day:
            return None
        event_id = _clean(obj.get("gameId") or obj.get("gameDetailId") or obj.get("id") or obj.get("uuid"))
        if not event_id:
            event_id = "nfl:" + shadow._payload_hash([day, away_team, home_team, scheduled])[:20]
        return {
            "competitionId": "NFL", "__sbbDate": day, "eventId": event_id,
            "scheduledAt": scheduled, "status": _clean(obj.get("gameStatus") or obj.get("status") or obj.get("state") or "SCHEDULED"),
            "away": away_team, "home": home_team,
            "venue": obj.get("venue") or obj.get("stadium") or {},
        }

    @staticmethod
    def _labor_day(year):
        d = date(year, 9, 1)
        return d + timedelta(days=(7 - d.weekday()) % 7)

    def _nfl_pages(self, days):
        pages = set()
        required_by_day = {}
        for day_str in days:
            d = date.fromisoformat(day_str)
            season = d.year if d.month >= 7 else d.year - 1
            kickoff = self._labor_day(season) + timedelta(days=3)
            regular_end = kickoff + timedelta(days=7 * 18)
            required = set()
            if d < kickoff:
                required.add((season, "PRE"))
                for week in range(0, 5):
                    pages.add((season, "PRE", week, f"https://www.nfl.com/schedules/{season}/PRE{week}/"))
                # During the gap immediately before Week 1, prove both sides of
                # the season boundary: preseason contains no later game and REG1
                # contains no earlier game silently shifted into the date.
                if d >= kickoff - timedelta(days=7):
                    required.add((season, "REG"))
                    pages.add((season, "REG", 1, f"https://www.nfl.com/schedules/{season}/REG1/"))
            elif d < regular_end:
                required.add((season, "REG"))
                week = max(1, min(18, ((d - kickoff).days // 7) + 1))
                for w in {max(1, week - 1), week, min(18, week + 1)}:
                    pages.add((season, "REG", w, f"https://www.nfl.com/schedules/{season}/REG{w}/"))
            else:
                required.add((season, "POST"))
                for week in range(1, 5):
                    pages.add((season, "POST", week, f"https://www.nfl.com/schedules/{season}/POST{week}/"))
                if d <= regular_end + timedelta(days=7):
                    required.add((season, "REG"))
                    pages.add((season, "REG", 18, f"https://www.nfl.com/schedules/{season}/REG18/"))
            required_by_day[day_str] = required
        return sorted(pages), required_by_day

    def _collect_nfl(self, day_from, day_to):
        league, source = "NFL", SOURCE_DEFS["NFL"]["authoritative"]
        days = _date_range(day_from, day_to)
        pages, required_by_day = self._nfl_pages(days)
        groups = defaultdict(list)
        recognized_stages = set()
        errors = []
        seen_ids = set()
        for season, stage, week, url in pages:
            try:
                text = self._http(url, headers={"Accept": "text/html,*/*", "Referer": "https://www.nfl.com/schedules/"}, as_text=True, cache_seconds=900)
                blobs = self._nfl_json_blobs(text)
                page_events = []
                for blob in blobs:
                    for obj in _walk(blob):
                        event = self._nfl_event_from_dict(obj)
                        if event:
                            page_events.append(event)
                # A recognized week page contains at least one structured game.
                # If hydration changes and we cannot recognize it, fail closed.
                if not page_events:
                    raise RuntimeError(f"NFL page parsed but no structured games were recognized ({stage}{week})")
                recognized_stages.add((season, stage))
                for event in page_events:
                    eid = event.get("eventId")
                    dedupe = (eid, event.get("__sbbDate"))
                    if dedupe in seen_ids:
                        continue
                    seen_ids.add(dedupe)
                    if event.get("__sbbDate") in days:
                        groups[event["__sbbDate"]].append(event)
            except Exception as exc:
                errors.append(f"{stage}{week}: {type(exc).__name__}: {exc}")
        success_days = {day for day in days if required_by_day.get(day) and required_by_day[day] <= recognized_stages}
        day_errors = {day: "NFL official schedule page not successfully recognized for this stage" for day in days if day not in success_days}
        count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE", success_days, day_errors)
        success = len(success_days) == len(days)
        error = "" if success else "; ".join(errors[-3:]) or f"{len(days)-len(success_days)} day(s) unproven"
        self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, success, count, error, "https://www.nfl.com/schedules/{season}/{stage}{week}/")
        return count

    def _collect_authoritative(self, league, day_from, day_to):
        return {
            "MLB": self._collect_mlb,
            "NFL": self._collect_nfl,
            "NBA": self._collect_nba,
            "NHL": self._collect_nhl,
            "EPL": self._collect_epl,
            "MLS": self._collect_mls,
            "NCAAF": self._collect_ncaaf,
        }[league](day_from, day_to)

    def run_horizon(self):
        today = datetime.now(shadow.ET).date()
        day_from = (today - timedelta(days=shadow.LOOKBACK_DAYS)).isoformat()
        day_to = (today + timedelta(days=shadow.LOOKAHEAD_DAYS)).isoformat()
        days = _date_range(day_from, day_to)
        started = _now()
        stats = {"dayFrom": day_from, "dayTo": day_to, "authoritativeEvents": 0, "independentEvents": 0, "slatesChanged": 0, "errors": []}
        try:
            # Independent first; official evidence then attaches to the same canonical
            # identities using team aliases/sequence/time rather than provider team IDs.
            for league in shadow.SUPPORTED_LEAGUES:
                stats["independentEvents"] += self._collect_espn_independent(league, day_from, day_to)
            for league in shadow.SUPPORTED_LEAGUES:
                stats["authoritativeEvents"] += self._collect_authoritative(league, day_from, day_to)
            for day in days:
                for league in shadow.SUPPORTED_LEAGUES:
                    _slate, changed = self.store.compile_slate(day, league, "CERTIFICATION_RECONCILIATION")
                    stats["slatesChanged"] += int(bool(changed))
            self.last_error = ""
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            stats["errors"].append(self.last_error)
        stats["durationSeconds"] = round(_now() - started, 3)
        stats["completedAt"] = _now()
        self.last_run_at = stats["completedAt"]
        self.last_stats = stats
        return stats

    def worker(self):
        time.sleep(6)
        while self.running:
            try:
                if not self.last_run_at or _now() - self.last_run_at >= FULL_SECONDS:
                    self.run_horizon()
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(2)

    def health(self):
        leagues = {}
        for league, info in SOURCE_DEFS.items():
            auth = info["authoritative"]
            leagues[league] = {
                "authoritative": {"source": auth, "sourceClass": "AUTHORITATIVE", "host": info["host"], "health": self.source_health.get(f"{league}:{auth}")},
                "independent": {"source": INDEPENDENT_SOURCE, "sourceClass": "INDEPENDENT", "host": "site.api.espn.com", "health": self.source_health.get(f"{league}:{INDEPENDENT_SOURCE}")},
            }
        store_health = self.store.health()
        return {
            "ok": True, "version": VERSION, "enabled": ENABLED,
            "mode": "shadow-certification", "productionAuthority": False,
            "freshnessSeconds": FRESH_SECONDS, "fullCadenceSeconds": FULL_SECONDS,
            "independenceModel": "league/organizer-operated authoritative source + separate raw ESPN direct path",
            "lastRunAt": self.last_run_at, "lastError": self.last_error, "lastRun": self.last_stats,
            "latestCertification": store_health.get("latestCertification", {}),
            "leagues": leagues,
        }


def _install_freshness_semantics():
    """Patch v6 store evidence queries so latest/fresh coverage wins for live/future days."""
    def coverage_classes(self, slate_date, league):
        now = _now()
        today = datetime.now(shadow.ET).date().isoformat()
        with self._lock, shadow.closing(self._connect(readonly=True)) as conn:
            rows = conn.execute("""
                SELECT source,source_class,success,last_observed_at FROM source_coverage
                WHERE slate_date=? AND competition_id=? ORDER BY source,last_observed_at DESC,id DESC
            """, (slate_date, league)).fetchall()
        latest = {}
        for row in rows:
            source = str(row[0])
            if source in latest:
                continue
            latest[source] = row
        out = set()
        for row in latest.values():
            if not int(row[2] or 0):
                continue
            if slate_date >= today and now - float(row[3] or 0) > FRESH_SECONDS:
                continue
            out.add(str(row[1]).upper())
        return out

    def evidence_classes(self, event_id):
        now = _now()
        today = datetime.now(shadow.ET).date().isoformat()
        with self._lock, shadow.closing(self._connect(readonly=True)) as conn:
            event = conn.execute("SELECT slate_date FROM canonical_event WHERE canonical_event_id=?", (event_id,)).fetchone()
            slate_date = str(event[0]) if event else ""
            rows = conn.execute("""
                SELECT source,source_class,MAX(last_observed_at) last_at FROM schedule_observation
                WHERE canonical_event_id=? GROUP BY source,source_class
            """, (event_id,)).fetchall()
        out = set()
        for row in rows:
            if slate_date >= today and now - float(row[2] or 0) > FRESH_SECONDS:
                continue
            out.add(str(row[1]).upper())
        return out

    shadow.CanonicalShadowStore.coverage_classes = coverage_classes
    shadow.CanonicalShadowStore.evidence_classes = evidence_classes


def engine():
    return _ENGINE


def _install_into_server():
    global _ENGINE
    deadline = _now() + 120
    server = None
    shadow_engine = None
    while _now() < deadline:
        server = sys.modules.get("__main__")
        shadow_engine = shadow.engine()
        if server and shadow_engine and hasattr(server, "Handler") and hasattr(server, "send_json"):
            break
        time.sleep(0.25)
    if not server or not shadow_engine:
        return

    _install_freshness_semantics()
    _ENGINE = CertificationEngine(server, shadow_engine)
    server.CANONICAL_CERTIFICATION_ENGINE = _ENGINE
    try:
        server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update({
            "certificationVersion": VERSION,
            "certificationAdapters": {league: info["authoritative"] for league, info in SOURCE_DEFS.items()},
            "independentSource": INDEPENDENT_SOURCE,
            "productionAuthority": False,
        })
    except Exception:
        pass

    Handler = server.Handler
    if not getattr(Handler, "__sbbCanonicalCertificationV610", False):
        old_get = Handler.do_GET
        def do_GET(self):
            parsed = shadow.urlparse(self.path)
            if parsed.path in {"/api/canonical/certification", "/api/canonical/certification/health"}:
                return server.send_json(self, _ENGINE.health(), 200, {"X-SBB-Canonical-Certification": "SHADOW"})
            return old_get(self)
        Handler.do_GET = do_GET
        Handler.__sbbCanonicalCertificationV610 = True

    threading.Thread(target=_ENGINE.worker, daemon=True, name="sbb-canonical-certification-v610").start()


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED or not ENABLED:
            return
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-canonical-certification-install-v610").start()

"""Sports Big Board v6.1.1 canonical certification hardening.

This module layers on top of v6.1 without changing production authority. It fixes
three classes of issues found during the first live shadow run:

* certification safety: known production-only events are contradictory evidence and
  force RECONCILING instead of permitting a false CERTIFIED zero slate;
* adapter resilience: NFL server-rendered schedule HTML, Premier League PulseLive
  pagination/headers, and MLS canonical match-date + broad-season fallback;
* operator diagnostics: per league/date cutover readiness, reason codes, named
  production-only blockers, source-count conflicts, and NCAAF full-universe metrics.

The v6.0 canonical SQLite schema remains the database of record for this shadow
lane. No table is replaced and no code path feeds production event existence.
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import sys
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode

from . import canonical_shadow_v600 as shadow
from . import canonical_certification_v610 as v610

VERSION = "6.1.1-certification-hardening-1"
ENABLED = str(os.environ.get("SBB_CANONICAL_CERT_HARDENING_ENABLED") or "1").strip().lower() not in {"0", "false", "no", "off"}
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_PATCHED = False
_ENGINE = None

NFL_TEAM_MAP = {
    "cardinals": ("Arizona Cardinals", "ARI"), "falcons": ("Atlanta Falcons", "ATL"),
    "ravens": ("Baltimore Ravens", "BAL"), "bills": ("Buffalo Bills", "BUF"),
    "panthers": ("Carolina Panthers", "CAR"), "bears": ("Chicago Bears", "CHI"),
    "bengals": ("Cincinnati Bengals", "CIN"), "browns": ("Cleveland Browns", "CLE"),
    "cowboys": ("Dallas Cowboys", "DAL"), "broncos": ("Denver Broncos", "DEN"),
    "lions": ("Detroit Lions", "DET"), "packers": ("Green Bay Packers", "GB"),
    "texans": ("Houston Texans", "HOU"), "colts": ("Indianapolis Colts", "IND"),
    "jaguars": ("Jacksonville Jaguars", "JAX"), "chiefs": ("Kansas City Chiefs", "KC"),
    "raiders": ("Las Vegas Raiders", "LV"), "chargers": ("Los Angeles Chargers", "LAC"),
    "rams": ("Los Angeles Rams", "LAR"), "dolphins": ("Miami Dolphins", "MIA"),
    "vikings": ("Minnesota Vikings", "MIN"), "patriots": ("New England Patriots", "NE"),
    "saints": ("New Orleans Saints", "NO"), "giants": ("New York Giants", "NYG"),
    "jets": ("New York Jets", "NYJ"), "eagles": ("Philadelphia Eagles", "PHI"),
    "steelers": ("Pittsburgh Steelers", "PIT"), "49ers": ("San Francisco 49ers", "SF"),
    "seahawks": ("Seattle Seahawks", "SEA"), "buccaneers": ("Tampa Bay Buccaneers", "TB"),
    "titans": ("Tennessee Titans", "TEN"), "commanders": ("Washington Commanders", "WAS"),
}
NFL_LABEL_RE = re.compile(
    r"(?P<away>[A-Za-z0-9 .&'\-]+?)\s+at\s+(?P<home>[A-Za-z0-9 .&'\-]+?),\s*"
    r"(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*"
    r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?,\s*(?P<time>\d{1,2}:\d{2})\s*(?P<ampm>AM|PM)", re.I,
)


def _now():
    return time.time()


def _clean(v):
    return str(v or "").strip()


def _load(v, fallback=None):
    try:
        return json.loads(v) if v else (fallback if fallback is not None else {})
    except Exception:
        return fallback if fallback is not None else {}


def _latest_comparison(store, slate_date, league):
    with store._lock, shadow.closing(store._connect(readonly=True)) as conn:
        row = conn.execute(
            """SELECT * FROM slate_comparison WHERE slate_date=? AND competition_id=?
               ORDER BY last_observed_at DESC,id DESC LIMIT 1""",
            (slate_date, league),
        ).fetchone()
    if not row:
        return None
    out = dict(row)
    out["details"] = _load(out.pop("details_json", "{}"), {})
    return out


def _latest_coverage_by_class(store, slate_date, league):
    now = _now()
    today = datetime.now(shadow.ET).date().isoformat()
    with store._lock, shadow.closing(store._connect(readonly=True)) as conn:
        rows = conn.execute(
            """SELECT * FROM source_coverage WHERE slate_date=? AND competition_id=?
               ORDER BY last_observed_at DESC,id DESC""",
            (slate_date, league),
        ).fetchall()
    latest_source = {}
    for row in rows:
        item = dict(row)
        if item["source"] in latest_source:
            continue
        latest_source[item["source"]] = item
    out = {}
    for item in latest_source.values():
        if not int(item.get("success") or 0):
            continue
        if slate_date >= today and now - float(item.get("last_observed_at") or 0) > v610.FRESH_SECONDS:
            continue
        cls = _clean(item.get("source_class")).upper()
        prior = out.get(cls)
        if not prior or float(item.get("last_observed_at") or 0) > float(prior.get("last_observed_at") or 0):
            out[cls] = item
    return out


def _event_summaries(store, event_ids):
    ids = [str(x) for x in (event_ids or []) if x]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with store._lock, shadow.closing(store._connect(readonly=True)) as conn:
        rows = conn.execute(
            f"""SELECT canonical_event_id,competition_id,slate_date,away_name,home_name,
                       scheduled_at,status,inclusion_state,identity_state
                FROM canonical_event WHERE canonical_event_id IN ({placeholders})""", ids,
        ).fetchall()
    by_id = {str(r["canonical_event_id"]): dict(r) for r in rows}
    return [by_id.get(x, {"canonical_event_id": x}) for x in ids]


def _event_evidence_gaps(store, slate_date, league):
    gaps = []
    for event in store.events_for_day(slate_date, league):
        if event.get("inclusion_state") != "INCLUDED":
            continue
        classes = store.evidence_classes(event["canonical_event_id"])
        missing = sorted({"AUTHORITATIVE", "INDEPENDENT"} - set(classes))
        if missing:
            gaps.append({"canonicalEventId": event["canonical_event_id"], "missing": missing})
    return gaps


def _hardening_state(store, slate_date, league, base_slate=None):
    comp = _latest_comparison(store, slate_date, league) or {}
    details = comp.get("details") or {}
    production_only = list(details.get("legacyOnly") or [])
    shadow_only = list(details.get("canonicalOnly") or [])
    coverage = _latest_coverage_by_class(store, slate_date, league)
    auth = coverage.get("AUTHORITATIVE")
    indep = coverage.get("INDEPENDENT")
    source_count_conflict = False
    if auth and indep and league in shadow.ALL_EVENT_LEAGUES:
        source_count_conflict = int(auth.get("result_count") or 0) != int(indep.get("result_count") or 0)
    evidence_gaps = _event_evidence_gaps(store, slate_date, league) if auth and indep else []

    reasons = []
    if production_only:
        reasons.append(f"KNOWN_EVENT_UNIVERSE_CONFLICT:{len(production_only)}_PRODUCTION_ONLY")
    if source_count_conflict:
        reasons.append(
            f"SOURCE_COUNT_CONFLICT:AUTHORITATIVE={int(auth.get('result_count') or 0)}:INDEPENDENT={int(indep.get('result_count') or 0)}"
        )
    if evidence_gaps:
        reasons.append(f"CROSS_SOURCE_EVENT_CONFLICT:{len(evidence_gaps)}_EVENTS")

    ncaaf = None
    if league == "NCAAF":
        slate = base_slate or (store.latest_slates(slate_date, league) or [{}])[0]
        ncaaf = {
            "authoritativeUniverse": int((auth or {}).get("result_count") or 0),
            "independentUniverse": int((indep or {}).get("result_count") or 0),
            "canonicalUniverse": int(slate.get("universe_count") or 0),
            "included": int(slate.get("included_count") or 0),
            "excluded": int(slate.get("excluded_count") or 0),
            "unknown": int(slate.get("unknown_count") or 0),
        }

    return {
        "reasons": reasons,
        "productionOnlyIds": production_only,
        "productionOnlyEvents": _event_summaries(store, production_only),
        "shadowOnlyIds": shadow_only,
        "shadowOnlyEvents": _event_summaries(store, shadow_only),
        "sourceCountConflict": source_count_conflict,
        "evidenceGaps": evidence_gaps,
        "coverage": {
            "authoritative": auth,
            "independent": indep,
        },
        "ncaafUniverse": ncaaf,
    }


def _clone_slate_status(store, prior, status, reason, conflict_count):
    if prior.get("certification_status") == status and prior.get("certification_reason") == reason and int(prior.get("conflict_count") or 0) == int(conflict_count):
        return prior, False
    with store._lock, shadow.closing(store._connect()) as conn:
        latest = conn.execute(
            """SELECT * FROM daily_slate WHERE slate_date=? AND competition_id=? ORDER BY version DESC LIMIT 1""",
            (prior["slate_date"], prior["competition_id"]),
        ).fetchone()
        if latest:
            prior = dict(latest)
        if prior.get("certification_status") == status and prior.get("certification_reason") == reason and int(prior.get("conflict_count") or 0) == int(conflict_count):
            return prior, False
        version = int(prior.get("version") or 0) + 1
        slate_id = f"{prior['slate_date']}:{prior['competition_id']}:v{version}"
        conn.execute(
            """INSERT INTO daily_slate(
                slate_id,slate_date,competition_id,version,certification_status,certification_reason,
                universe_count,included_count,excluded_count,unknown_count,unresolved_count,conflict_count,
                source_class_count,membership_hash,baseline_kind,generated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                slate_id, prior["slate_date"], prior["competition_id"], version, status, reason,
                prior["universe_count"], prior["included_count"], prior["excluded_count"], prior["unknown_count"],
                prior["unresolved_count"], int(conflict_count), prior["source_class_count"], prior["membership_hash"],
                "CERTIFICATION_HARDENING", _now(),
            ),
        )
        conn.execute(
            """INSERT INTO daily_slate_event(slate_id,canonical_event_id,inclusion_state,inclusion_reason,status,scheduled_at)
               SELECT ?,canonical_event_id,inclusion_state,inclusion_reason,status,scheduled_at
               FROM daily_slate_event WHERE slate_id=?""",
            (slate_id, prior["slate_id"]),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM daily_slate WHERE slate_id=?", (slate_id,)).fetchone()
        return dict(row), True


def _current_membership_hash(store, slate_date, league):
    events = store.events_for_day(slate_date, league)
    members = [{
        "id": x["canonical_event_id"], "include": x["inclusion_state"], "reason": x["inclusion_reason"],
        "scheduleStatus": x["status"] if x["status"] in {"POSTPONED", "CANCELLED"} else "ACTIVE",
        "scheduledAt": x["scheduled_at"],
    } for x in events]
    return shadow._payload_hash(members)


def _latest_slate_row(store, slate_date, league):
    with store._lock, shadow.closing(store._connect(readonly=True)) as conn:
        row = conn.execute(
            "SELECT * FROM daily_slate WHERE slate_date=? AND competition_id=? ORDER BY version DESC LIMIT 1",
            (slate_date, league),
        ).fetchone()
    return dict(row) if row else None


def _install_certification_gate():
    cls = shadow.CanonicalShadowStore
    if getattr(cls, "__sbbV611CompileGate", False):
        return
    original = cls.compile_slate

    def compile_slate(self, slate_date, league, baseline_kind="RECONCILIATION", force_version=False):
        # Avoid a CERTIFIED -> RECONCILING two-version churn on every hot cycle.
        # When the hardened contradiction state and membership are unchanged, the
        # latest hardened row is already the correct answer and can be reused.
        prior = _latest_slate_row(self, slate_date, league)
        pre_hard = _hardening_state(self, slate_date, league, prior or {})
        if pre_hard["reasons"] and prior and not force_version:
            reason = " | ".join(pre_hard["reasons"])
            conflicts = len(pre_hard["productionOnlyIds"]) + int(pre_hard["sourceCountConflict"]) + len(pre_hard["evidenceGaps"])
            if (
                prior.get("certification_status") == "RECONCILING"
                and prior.get("certification_reason") == reason
                and int(prior.get("conflict_count") or 0) == int(conflicts)
                and prior.get("membership_hash") == _current_membership_hash(self, slate_date, league)
            ):
                return prior, False

        slate, changed = original(self, slate_date, league, baseline_kind, force_version)
        hard = _hardening_state(self, slate_date, league, slate)
        reasons = hard["reasons"]
        if reasons:
            # Contradictory evidence is stronger than a successful pair of collectors.
            # It must remain visible and can never be labelled CERTIFIED.
            reason = " | ".join(reasons)
            conflict_count = len(hard["productionOnlyIds"]) + int(hard["sourceCountConflict"]) + len(hard["evidenceGaps"])
            slate, extra = _clone_slate_status(self, slate, "RECONCILING", reason, conflict_count)
            return slate, bool(changed or extra)
        return slate, changed

    cls.compile_slate = compile_slate
    cls.__sbbV611CompileGate = True


def _nfl_team(name):
    raw = _clean(name)
    key = re.sub(r"[^a-z0-9]+", "", raw.lower())
    for nickname, (full, abbr) in NFL_TEAM_MAP.items():
        if key == re.sub(r"[^a-z0-9]+", "", nickname) or key.endswith(re.sub(r"[^a-z0-9]+", "", nickname)):
            return v610._team(full, abbr)
    return v610._team(raw)


def _nfl_events_from_html(text, season):
    decoded = html_lib.unescape(_clean(text))
    # aria-label is the most stable server-rendered representation currently used
    # by NFL.com. Falling back to the whole document also covers text-only changes.
    candidates = re.findall(r"aria-label=[\"']([^\"']+)[\"']", decoded, flags=re.I)
    candidates.append(re.sub(r"<[^>]+>", " ", decoded))
    events = []
    seen = set()
    for candidate in candidates:
        for m in NFL_LABEL_RE.finditer(candidate):
            away = _nfl_team(m.group("away"))
            home = _nfl_team(m.group("home"))
            calendar_year = int(season) + (1 if m.group("month").lower() in {"january", "february"} else 0)
            try:
                naive = datetime.strptime(
                    f"{m.group('month')} {m.group('day')} {calendar_year} {m.group('time')} {m.group('ampm').upper()}",
                    "%B %d %Y %I:%M %p",
                )
            except Exception:
                continue
            local = naive.replace(tzinfo=shadow.ET)
            scheduled = local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            day = local.date().isoformat()
            key = (day, away.get("displayName"), home.get("displayName"), scheduled)
            if key in seen:
                continue
            seen.add(key)
            events.append({
                "competitionId": "NFL", "__sbbDate": day,
                "eventId": "nfl:" + shadow._payload_hash(key)[:20],
                "scheduledAt": scheduled, "status": "SCHEDULED",
                "away": away, "home": home,
                "name": f"{away.get('displayName')} @ {home.get('displayName')}",
            })
    return events


def _nfl_pages_v611(self, days):
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
            # NFL.com currently exposes three numbered preseason weeks. PRE0/PRE4
            # were causing false parser failures in v6.1.
            for week in range(1, 4):
                pages.add((season, "PRE", week, f"https://www.nfl.com/schedules/{season}/PRE{week}/"))
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


def _collect_nfl_v611(self, day_from, day_to):
    league, source = "NFL", v610.SOURCE_DEFS["NFL"]["authoritative"]
    days = v610._date_range(day_from, day_to)
    pages, required_by_day = self._nfl_pages(days)
    groups = defaultdict(list)
    recognized_stages = set()
    errors, seen = [], set()
    for season, stage, week, url in pages:
        try:
            text = self._http(url, headers={"Accept": "text/html,*/*", "Referer": "https://www.nfl.com/schedules/"}, as_text=True, cache_seconds=900)
            page_events = []
            for blob in self._nfl_json_blobs(text):
                for obj in v610._walk(blob):
                    event = self._nfl_event_from_dict(obj)
                    if event:
                        page_events.append(event)
            # Current NFL.com pages are server-rendered even when no JSON hydration
            # object matches the old parser. Parse the accessible matchup labels too.
            page_events.extend(_nfl_events_from_html(text, season))
            deduped = []
            page_seen = set()
            for event in page_events:
                key = (event.get("eventId"), event.get("__sbbDate"), v610._norm((event.get("away") or {}).get("displayName")), v610._norm((event.get("home") or {}).get("displayName")))
                if key in page_seen:
                    continue
                page_seen.add(key)
                deduped.append(event)
            if not deduped:
                raise RuntimeError(f"NFL page contained no recognized schedule events ({stage}{week})")
            recognized_stages.add((season, stage))
            for event in deduped:
                key = (event.get("eventId"), event.get("__sbbDate"))
                if key in seen:
                    continue
                seen.add(key)
                if event.get("__sbbDate") in days:
                    groups[event["__sbbDate"]].append(event)
        except Exception as exc:
            errors.append(f"{stage}{week}: {type(exc).__name__}: {exc}")
    success_days = {day for day in days if required_by_day.get(day) and required_by_day[day] <= recognized_stages}
    day_errors = {day: "NFL official schedule stage was not successfully recognized" for day in days if day not in success_days}
    count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE", success_days, day_errors)
    success = len(success_days) == len(days)
    error = "" if success else "; ".join(errors[-4:]) or f"{len(days)-len(success_days)} day(s) unproven"
    self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, success, count, error, "https://www.nfl.com/schedules/{season}/{stage}{week}/ [server-rendered labels]")
    return count


def _collect_epl_v611(self, day_from, day_to):
    league, source = "EPL", v610.SOURCE_DEFS["EPL"]["authoritative"]
    days = v610._date_range(day_from, day_to)
    headers = {
        "Origin": "https://www.premierleague.com",
        "Referer": "https://www.premierleague.com/",
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    # PulseLive rejects some obsolete sort combinations with HTTP 400. Season
    # discovery does not require sort at all.
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
            if str(start_year) in label and str(start_year + 1)[-2:] in label:
                chosen = season
                break
        chosen = chosen or seasons[0]
        season_id = _clean((chosen or {}).get("id"))
        if not season_id:
            raise RuntimeError("Premier League season ID unavailable")

        rows = []
        page_size = 100
        last_url = ""
        for page in range(0, 10):
            fixture_url = "https://footballapi.pulselive.com/football/fixtures?" + urlencode({
                "comps": 1, "compSeasons": season_id, "page": page, "pageSize": page_size, "sort": "asc",
            })
            last_url = fixture_url
            payload = self._http(fixture_url, headers=headers, cache_seconds=900)
            content = payload.get("content") if isinstance(payload, dict) else payload
            if not isinstance(content, list):
                raise RuntimeError(f"Premier League fixtures response missing content[] on page {page}")
            rows.extend(content)
            if len(content) < page_size:
                break
        if not rows:
            # An empty full-season result is not enough evidence to certify the
            # active Premier League season.
            raise RuntimeError("Premier League fixtures returned zero rows")

        groups = defaultdict(list)
        for fixture in rows:
            if not isinstance(fixture, dict):
                continue
            kickoff = fixture.get("kickoff") or {}
            scheduled = v610._iso_from_epoch(kickoff.get("millis")) or _clean(kickoff.get("label"))
            day = v610._day_from_datetime(scheduled)
            if day not in days:
                continue
            teams = fixture.get("teams") or []
            if len(teams) < 2:
                continue
            home_entry, away_entry = teams[0], teams[1]
            # Prefer explicit home/away markers when PulseLive provides them.
            for entry in teams:
                loc = _clean((entry or {}).get("location") or (entry or {}).get("side")).lower() if isinstance(entry, dict) else ""
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
                "competitionId": league, "__sbbDate": day,
                "eventId": _clean(fixture.get("id")), "scheduledAt": scheduled,
                "status": _clean(fixture.get("status") or fixture.get("phase") or "SCHEDULED"),
                "away": v610._team(away_name, away_raw.get("shortName")),
                "home": v610._team(home_name, home_raw.get("shortName")),
                "venue": fixture.get("ground") or {},
            })
        count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE")
        self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, True, count, "", last_url or season_url)
        return count
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        return self._failed_range(league, source, "AUTHORITATIVE", days, error, season_url)


def _mls_competition_ok(match):
    comp = match.get("competition") if isinstance(match.get("competition"), dict) else {}
    cid = _clean(match.get("competition_id") or match.get("competitionId") or comp.get("id"))
    name = _clean(match.get("competition_name") or match.get("competitionName") or comp.get("name") or comp.get("short_name"))
    if cid:
        if cid == v610.MLS_COMPETITION_ID:
            return True
        lname = name.lower()
        return ("major league soccer" in lname or "mls regular" in lname) and "next" not in lname and "leagues cup" not in lname
    # The season endpoint itself is MLS-specific; records without explicit
    # competition metadata are valid candidates.
    return True


def _mls_groups(rows, days):
    groups = defaultdict(list)
    for match in rows or []:
        if not isinstance(match, dict) or not _mls_competition_ok(match):
            continue
        scheduled = _clean(match.get("planned_kickoff_time") or match.get("kickoff_time") or match.get("date_time"))
        # match_date is the organizer's canonical competition date. v6.1 used the
        # UTC kickoff conversion first, which can silently move late matches.
        day = _clean(match.get("match_date") or match.get("date"))[:10]
        if day not in days:
            day = v610._day_from_datetime(scheduled)
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
            "competitionId": "MLS", "__sbbDate": day, "eventId": event_id,
            "scheduledAt": scheduled, "status": _clean(match.get("match_status") or match.get("status") or "SCHEDULED"),
            "away": v610._team(away_name, match.get("away_team_abbreviation")),
            "home": v610._team(home_name, match.get("home_team_abbreviation")),
            "venue": match.get("venue") or match.get("stadium") or "",
        })
    return groups


def _collect_mls_v611(self, day_from, day_to):
    league, source = "MLS", v610.SOURCE_DEFS["MLS"]["authoritative"]
    days = v610._date_range(day_from, day_to)
    base_url = f"https://stats-api.mlssoccer.com/matches/seasons/{v610.MLS_SEASON_ID}"
    common = {
        "match_date[gte]": day_from, "match_date[lte]": day_to,
        "per_page": 1000, "sort": "planned_kickoff_time:asc,home_team_name:asc",
    }
    filtered_url = base_url + "?" + urlencode({**common, "competition_id": v610.MLS_COMPETITION_ID})
    broad_url = base_url + "?" + urlencode(common)
    headers = {"Accept": "application/json", "User-Agent": "curl/8.0 SportsBigBoard/6.1.1"}
    try:
        merged = {}
        endpoints = []
        for url in (filtered_url, broad_url):
            payload = self._http(url, headers=headers, cache_seconds=300)
            rows = payload.get("schedule") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise RuntimeError(f"MLS schedule response missing schedule[]: {url}")
            endpoints.append(f"{url} => {len(rows)} raw")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                key = _clean(row.get("match_id") or row.get("matchId") or row.get("id"))
                if not key:
                    key = shadow._payload_hash(row)
                merged[key] = row
        groups = _mls_groups(list(merged.values()), set(days))
        count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE")
        self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, True, count, "", " | ".join(endpoints))
        return count
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        return self._failed_range(league, source, "AUTHORITATIVE", days, error, filtered_url)


def _collect_espn_independent_v611(self, league, day_from, day_to):
    if league != "MLS":
        return self.__sbbV611OriginalEspnIndependent(league, day_from, day_to)
    days = v610._date_range(day_from, day_to)
    source = v610.INDEPENDENT_SOURCE
    groups = defaultdict(list)
    success_days, errors = set(), {}
    sport, competition = shadow.ESPN_DIRECT_COMPETITIONS[league]
    for day in days:
        token = day.replace("-", "")
        url = f"{shadow.ESPN_SITE_API}/{sport}/{competition}/scoreboard?" + urlencode({"dates": token, "limit": 1000})
        try:
            payload = self._http(url, cache_seconds=120)
            rows = payload.get("events") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise RuntimeError("ESPN MLS scoreboard response missing events[]")
            success_days.add(day)
            for raw in rows:
                event = self.shadow._espn_event(raw, league, day)
                if event:
                    groups[day].append(event)
        except Exception as exc:
            errors[day] = f"{type(exc).__name__}: {exc}"
    count = self.writer.snapshot(groups, days, league, source, "INDEPENDENT", success_days, errors)
    success = len(success_days) == len(days)
    error = "" if success else f"{len(days)-len(success_days)} day-specific ESPN MLS request(s) failed"
    self._mark_health(league, source, "INDEPENDENT", day_from, day_to, success, count, error, "site.api.espn.com MLS per-day scoreboard")
    return count


def _collect_ncaaf_v611(self, day_from, day_to):
    league, source = "NCAAF", v610.SOURCE_DEFS["NCAAF"]["authoritative"]
    days = v610._date_range(day_from, day_to)
    groups = defaultdict(list)
    success_days, errors = set(), {}
    for day in days:
        d = date.fromisoformat(day)
        season_year = d.year if d.month >= 7 else d.year - 1
        variables = {"sportCode": "MFB", "division": 11, "seasonYear": season_year, "contestDate": day}
        extensions = {"persistedQuery": {"version": 1, "sha256Hash": v610.NCAA_SCOREBOARD_HASH}}
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
                scheduled = v610._iso_from_epoch(contest.get("startTimeEpoch"))
                event = {
                    "competitionId": league, "__sbbDate": day,
                    "eventId": _clean(contest.get("contestId")), "scheduledAt": scheduled,
                    "status": _clean(contest.get("gameState") or contest.get("finalMessage") or "SCHEDULED"),
                    "away": v610._team(away_raw.get("nameShort"), away_raw.get("name6Char"), rank=away_raw.get("teamRank")),
                    "home": v610._team(home_raw.get("nameShort"), home_raw.get("name6Char"), rank=home_raw.get("teamRank")),
                    "period": contest.get("currentPeriod"), "clock": contest.get("contestClock"),
                }
                event["__sbbNcaafTop25"] = v610._ncaaf_inclusion(event)[0] == "INCLUDED"
                groups[day].append(event)
        except Exception as exc:
            errors[day] = f"{type(exc).__name__}: {exc}"
    count = self.writer.snapshot(groups, days, league, source, "AUTHORITATIVE", success_days, errors)
    success = len(success_days) == len(days)
    error = "" if success else f"{len(days)-len(success_days)} day(s) failed"
    self._mark_health(league, source, "AUTHORITATIVE", day_from, day_to, success, count, error, "https://sdataprod.ncaa.com/ [full FBS universe]")
    return count


def _refresh_production_comparisons(engine, days):
    refreshed = 0
    for day in days:
        try:
            _count, legacy_ids, _touched, present = engine.shadow.ingest_day_state(day)
        except Exception:
            present = False
            legacy_ids = {}
        if not present:
            continue
        for league in shadow.SUPPORTED_LEAGUES:
            engine.store.record_comparison(day, league, legacy_ids.get(league, set()))
            refreshed += 1
    return refreshed


def _readiness_for_day(engine, day):
    rows = {}
    for league in shadow.SUPPORTED_LEAGUES:
        slates = engine.store.latest_slates(day, league)
        slate = slates[0] if slates else {}
        hard = _hardening_state(engine.store, day, league, slate)
        comp = _latest_comparison(engine.store, day, league) or {}
        production_only = int(comp.get("legacy_only_count") or len(hard["productionOnlyIds"]))
        status = _clean(slate.get("certification_status") or "NO_MANIFEST")
        ready = (
            status == "CERTIFIED" and production_only == 0 and not hard["reasons"]
            and int(slate.get("unresolved_count") or 0) == 0 and int(slate.get("unknown_count") or 0) == 0
        )
        reason = "CUTOVER_READY" if ready else (
            hard["reasons"][0] if hard["reasons"] else _clean(slate.get("certification_reason") or status)
        )
        rows[league] = {
            "league": league, "date": day, "cutoverReady": ready, "reason": reason,
            "certificationStatus": status, "certificationReason": _clean(slate.get("certification_reason")),
            "universe": int(slate.get("universe_count") or 0),
            "included": int(slate.get("included_count") or 0),
            "excluded": int(slate.get("excluded_count") or 0),
            "unknown": int(slate.get("unknown_count") or 0),
            "unresolved": int(slate.get("unresolved_count") or 0),
            "productionOnly": production_only,
            "shadowOnly": int(comp.get("canonical_only_count") or len(hard["shadowOnlyIds"])),
            "productionOnlyEvents": hard["productionOnlyEvents"],
            "shadowOnlyEvents": hard["shadowOnlyEvents"],
            "sourceCountConflict": hard["sourceCountConflict"],
            "evidenceGaps": hard["evidenceGaps"],
            "ncaafUniverse": hard["ncaafUniverse"],
        }
    return rows


def _readiness_window(engine):
    today = datetime.now(shadow.ET).date()
    day_from = today - timedelta(days=shadow.LOOKBACK_DAYS)
    day_to = today + timedelta(days=shadow.LOOKAHEAD_DAYS)
    ready = total = blockers = 0
    by_day = {}
    cursor = day_from
    while cursor <= day_to:
        day = cursor.isoformat()
        rows = _readiness_for_day(engine, day)
        day_ready = sum(1 for x in rows.values() if x["cutoverReady"])
        ready += day_ready
        total += len(rows)
        blockers += sum(int(x["productionOnly"]) for x in rows.values())
        by_day[day] = {"cutoverReady": day_ready, "leagueDays": len(rows), "productionOnlyBlockers": sum(int(x["productionOnly"]) for x in rows.values())}
        cursor += timedelta(days=1)
    return {"cutoverReadyLeagueDays": ready, "totalLeagueDays": total, "productionOnlyBlockers": blockers, "days": by_day}


def _run_horizon_v611(self):
    # Run v6.1 collectors first, using the repaired collector methods installed on
    # the class, then refresh production comparisons before the final gated compile.
    stats = self.__sbbV611OriginalRunHorizon()
    today = datetime.now(shadow.ET).date()
    days = [(today + timedelta(days=offset)).isoformat() for offset in range(-shadow.LOOKBACK_DAYS, shadow.LOOKAHEAD_DAYS + 1)]
    refreshed = _refresh_production_comparisons(self, days)
    changed = 0
    for day in days:
        for league in shadow.SUPPORTED_LEAGUES:
            _slate, did_change = self.store.compile_slate(day, league, "CERTIFICATION_HARDENING")
            changed += int(bool(did_change))
    stats["productionComparisonsRefreshed"] = refreshed
    stats["hardeningSlateChanges"] = changed
    stats["hardeningVersion"] = VERSION
    self.last_stats = stats
    return stats


def _health_v611(self):
    payload = self.__sbbV611OriginalHealth()
    payload["version"] = VERSION
    payload["hardening"] = {
        "productionContradictionGate": True,
        "sourceCountConflictGate": True,
        "eventEvidenceGapGate": True,
        "nflServerRenderedParser": True,
        "eplPulsePagination": True,
        "mlsCanonicalMatchDate": True,
        "mlsBroadSeasonFallback": True,
        "mlsEspnPerDayIndependent": True,
        "productionAuthority": False,
    }
    today = datetime.now(shadow.ET).date().isoformat()
    readiness = _readiness_for_day(self, today)
    window = _readiness_window(self)
    payload["readinessToday"] = readiness
    payload["cutoverReadyLeagueDays"] = window["cutoverReadyLeagueDays"]
    payload["totalLeagueDays"] = window["totalLeagueDays"]
    payload["productionOnlyBlockers"] = window["productionOnlyBlockers"]
    payload["adapterFailures"] = sum(
        1 for league in (payload.get("leagues") or {}).values()
        for side in ("authoritative", "independent")
        if league.get(side, {}).get("health") and not league.get(side, {}).get("health", {}).get("success")
    )
    return payload


def _install_engine_patches():
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True
    cls = v610.CertificationEngine
    if not hasattr(cls, "__sbbV611OriginalEspnIndependent"):
        cls.__sbbV611OriginalEspnIndependent = cls._collect_espn_independent
    if not hasattr(cls, "__sbbV611OriginalRunHorizon"):
        cls.__sbbV611OriginalRunHorizon = cls.run_horizon
    if not hasattr(cls, "__sbbV611OriginalHealth"):
        cls.__sbbV611OriginalHealth = cls.health
    cls._nfl_pages = _nfl_pages_v611
    cls._collect_nfl = _collect_nfl_v611
    cls._collect_epl = _collect_epl_v611
    cls._collect_mls = _collect_mls_v611
    cls._collect_ncaaf = _collect_ncaaf_v611
    cls._collect_espn_independent = _collect_espn_independent_v611
    cls.run_horizon = _run_horizon_v611
    cls.health = _health_v611


def engine():
    return _ENGINE


def _install_into_server():
    global _ENGINE
    deadline = _now() + 120
    server = None
    base_engine = None
    while _now() < deadline:
        server = sys.modules.get("__main__")
        base_engine = v610.engine()
        if server and base_engine and hasattr(server, "Handler") and hasattr(server, "send_json"):
            break
        time.sleep(0.25)
    if not server or not base_engine:
        return
    _install_certification_gate()
    _install_engine_patches()
    _ENGINE = base_engine
    try:
        server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update({
            "certificationHardeningVersion": VERSION,
            "productionContradictionGate": True,
            "productionAuthority": False,
        })
    except Exception:
        pass

    Handler = server.Handler
    if not getattr(Handler, "__sbbCanonicalCertificationV611", False):
        old_get = Handler.do_GET
        def do_GET(self):
            parsed = shadow.urlparse(self.path)
            if parsed.path == "/api/canonical/certification/readiness":
                qs = parse_qs(parsed.query)
                day = shadow._day((qs.get("date") or [""])[-1]) or datetime.now(shadow.ET).date().isoformat()
                rows = _readiness_for_day(_ENGINE, day)
                return server.send_json(self, {
                    "ok": True, "version": VERSION, "date": day, "productionAuthority": False,
                    "cutoverReady": sum(1 for x in rows.values() if x["cutoverReady"]),
                    "leagueCount": len(rows), "leagues": rows,
                }, 200, {"X-SBB-Canonical-Certification": "HARDENED-SHADOW"})
            if parsed.path == "/api/canonical/certification/readiness-window":
                return server.send_json(self, {
                    "ok": True, "version": VERSION, "productionAuthority": False,
                    **_readiness_window(_ENGINE),
                }, 200, {"X-SBB-Canonical-Certification": "HARDENED-SHADOW"})
            return old_get(self)
        Handler.do_GET = do_GET
        Handler.__sbbCanonicalCertificationV611 = True

    # Reconcile immediately instead of waiting for the next 15-minute v6.1 cycle.
    def initial_reconcile():
        time.sleep(1)
        try:
            _ENGINE.run_horizon()
        except Exception as exc:
            _ENGINE.last_error = f"v6.1.1 initial hardening reconcile: {type(exc).__name__}: {exc}"
    threading.Thread(target=initial_reconcile, daemon=True, name="sbb-canonical-certification-v611-reconcile").start()


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED or not ENABLED:
            return
        _INSTALLED = True
    threading.Thread(target=_install_into_server, daemon=True, name="sbb-canonical-certification-install-v611").start()

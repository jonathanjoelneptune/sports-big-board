"""Sports Big Board v6.1.16 canonical reconciliation hotfix.

Shadow/certification only. Production Day State remains the event authority.

This narrow runtime layer repairs two validation defects without changing release
identity or media/UI code:

* NFL official schedule evidence is proven by the exact week page that owns each
  date, and completed NFL.com score rows are parsed after their pregame "at"
  labels disappear.
* NCAAF duplicate identities are reconciled only for explicit, demonstrated NCAA
  team-name aliases and high-confidence schedule-drift shapes. Authoritative
  schedule drift remains recorded as evidence but does not overwrite a broader
  cross-source canonical kickoff.

The patch is intentionally fail-closed: an NFL week page that cannot be parsed
marks the affected dates unproven instead of certifying a successful zero slate.
"""
from __future__ import annotations

import html as html_lib
import re
import sys
import threading
import time
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta

from . import canonical_shadow_v600 as shadow
from . import canonical_certification_v610 as v610
from . import canonical_certification_v611 as v611
from . import canonical_identity_ingestion_v619 as v619
from . import canonical_schedule_watchdogs_v6116 as v6116

VERSION = "6.1.16-canonical-reconcile-hotfix-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_PATCHED = False
_ORIGINAL_ALIAS_CANDIDATES = v619._alias_candidates

# Only aliases observed in the live validation failure are added here. Do not
# lower the global fuzzy threshold; that would increase cross-game merge risk.
_NCAAF_ALIAS_GROUPS = (
    ("Ga. Southern", "Georgia Southern", "Georgia Southern Eagles"),
    ("New Mexico St.", "New Mexico State", "New Mexico State Aggies"),
    ("Hawaii", "Hawai'i", "Hawai'i Rainbow Warriors"),
)

_NFL_NICKNAMES = tuple(sorted(v611.NFL_TEAM_MAP, key=len, reverse=True))
_NFL_TEAM_TOKEN = "|".join(re.escape(x) for x in _NFL_NICKNAMES)
_NFL_FINAL_RE = re.compile(
    rf"(?P<away>{_NFL_TEAM_TOKEN})\s+(?P<away_score>\d+)\s*,\s*"
    rf"(?P<home>{_NFL_TEAM_TOKEN})\s+(?P<home_score>\d+)\s*,\s*FINAL\s*,\s*"
    r"(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*,\s*"
    r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?",
    re.I,
)


def _clean(value):
    return str(value or "").strip()


def _install_ncaaf_aliases():
    bucket = v619._ALIAS_LOOKUP.setdefault("NCAAF", {})
    for group in _NCAAF_ALIAS_GROUPS:
        canonical = shadow._norm(group[0])
        for name in group:
            bucket[shadow._norm(name)] = canonical


def _nfl_final_events_from_html(text, season):
    """Parse completed NFL.com rows whose pregame `away at home` label is gone."""
    decoded = html_lib.unescape(_clean(text))
    candidates = re.findall(r"aria-label=[\"']([^\"']+)[\"']", decoded, flags=re.I)
    candidates.append(re.sub(r"<[^>]+>", " ", decoded))
    events = []
    seen = set()
    for candidate in candidates:
        for match in _NFL_FINAL_RE.finditer(candidate):
            away = v611._nfl_team(match.group("away"))
            home = v611._nfl_team(match.group("home"))
            month = match.group("month")
            calendar_year = int(season) + (1 if month.lower() in {"january", "february"} else 0)
            try:
                local_day = datetime.strptime(
                    f"{month} {match.group('day')} {calendar_year}", "%B %d %Y"
                ).date()
            except Exception:
                continue
            day = local_day.isoformat()
            key = (day, away.get("displayName"), home.get("displayName"))
            if key in seen:
                continue
            seen.add(key)
            events.append({
                "competitionId": "NFL",
                "__sbbDate": day,
                "eventId": "nfl:" + shadow._payload_hash(key)[:20],
                # NFL's completed row no longer exposes kickoff time. Leaving this
                # blank preserves the already-known canonical kickoff on upsert.
                "scheduledAt": "",
                "status": "FINAL",
                "away": away,
                "home": home,
                "awayScore": match.group("away_score"),
                "homeScore": match.group("home_score"),
                "name": f"{away.get('displayName')} @ {home.get('displayName')}",
            })
    return events


def _week1_anchor(season):
    # The 2026 season opens on Wednesday after Labor Day. A Wednesday-Tuesday
    # ownership window also safely contains the traditional Thursday opener.
    return v610.CertificationEngine._labor_day(season) + timedelta(days=2)


def _nfl_pages_strict(self, days):
    """Return current NFL.com pages plus exact page requirements per slate date."""
    base_pages, _base_required = v6116._nfl_pages_v6116(self, days)
    pages = set(base_pages)
    required_by_day = {}

    # Rewrite preseason pages to the current public route too. The old PRE1 form
    # may redirect today but must not be certification-critical.
    rewritten = set()
    for season, stage, week, url in pages:
        if stage == "PRE" and 1 <= int(week) <= 3:
            url = f"https://www.nfl.com/schedules/{season}/by-week/preseason-week-{week}"
        rewritten.add((season, stage, week, url))
    pages = rewritten

    for day_str in days:
        current = date.fromisoformat(day_str)
        season = current.year if current.month >= 7 else current.year - 1
        anchor = _week1_anchor(season)
        regular_end = anchor + timedelta(days=7 * 18)

        if anchor <= current < regular_end:
            week = max(1, min(18, ((current - anchor).days // 7) + 1))
            required_by_day[day_str] = {(season, "REG", week)}
            pages.add((
                season, "REG", week,
                f"https://www.nfl.com/schedules/{season}/by-week/week-{week}",
            ))
            continue

        if anchor - timedelta(days=7) <= current < anchor:
            # Prove the quiet boundary from both sides: PRE3 has ended and REG1
            # has not silently moved an opener onto this date.
            required_by_day[day_str] = {(season, "PRE", 3), (season, "REG", 1)}
            pages.add((
                season, "PRE", 3,
                f"https://www.nfl.com/schedules/{season}/by-week/preseason-week-3",
            ))
            pages.add((
                season, "REG", 1,
                f"https://www.nfl.com/schedules/{season}/by-week/week-1",
            ))
            continue

        # Outside the regular-season boundary use the mature v6.1.1 planning
        # semantics. These stage requirements remain fail-closed while this hotfix
        # only strengthens the dates implicated by the live validation window.
        fallback_pages, fallback_required = v611._nfl_pages_v611(self, [day_str])
        required_by_day[day_str] = set(fallback_required.get(day_str) or set())
        for row in fallback_pages:
            season0, stage0, week0, url0 = row
            if stage0 == "PRE" and 1 <= int(week0) <= 3:
                url0 = f"https://www.nfl.com/schedules/{season0}/by-week/preseason-week-{week0}"
            elif stage0 == "REG":
                url0 = f"https://www.nfl.com/schedules/{season0}/by-week/week-{week0}"
            pages.add((season0, stage0, week0, url0))

    return sorted(pages), required_by_day


def _nfl_requirement_satisfied(requirement, recognized_pages, recognized_stages):
    if len(requirement) >= 3:
        return tuple(requirement[:3]) in recognized_pages
    return tuple(requirement[:2]) in recognized_stages


def _collect_nfl_hotfix(self, day_from, day_to):
    league, source = "NFL", v610.SOURCE_DEFS["NFL"]["authoritative"]
    days = v610._date_range(day_from, day_to)
    pages, required_by_day = self._nfl_pages(days)
    groups = defaultdict(list)
    recognized_pages = set()
    recognized_stages = set()
    errors, seen = [], set()

    for season, stage, week, url in pages:
        try:
            text = self._http(
                url,
                headers={
                    "Accept": "text/html,*/*",
                    "Referer": "https://www.nfl.com/schedules/",
                },
                as_text=True,
                cache_seconds=900,
            )
            page_events = []
            for blob in self._nfl_json_blobs(text):
                for obj in v610._walk(blob):
                    event = self._nfl_event_from_dict(obj)
                    if event:
                        page_events.append(event)
            page_events.extend(v611._nfl_events_from_html(text, season))
            page_events.extend(_nfl_final_events_from_html(text, season))

            deduped = []
            page_seen = set()
            for event in page_events:
                key = (
                    event.get("eventId"),
                    event.get("__sbbDate"),
                    v610._norm((event.get("away") or {}).get("displayName")),
                    v610._norm((event.get("home") or {}).get("displayName")),
                )
                if key in page_seen:
                    continue
                page_seen.add(key)
                deduped.append(event)
            if not deduped:
                raise RuntimeError(f"NFL page contained no recognized schedule events ({stage}{week})")

            recognized_pages.add((season, stage, week))
            recognized_stages.add((season, stage))
            for event in deduped:
                key = (
                    event.get("eventId"),
                    event.get("__sbbDate"),
                    v610._norm((event.get("away") or {}).get("displayName")),
                    v610._norm((event.get("home") or {}).get("displayName")),
                )
                if key in seen:
                    continue
                seen.add(key)
                if event.get("__sbbDate") in days:
                    groups[event["__sbbDate"]].append(event)
        except Exception as exc:
            errors.append(f"{stage}{week}: {type(exc).__name__}: {exc}")

    success_days = set()
    day_errors = {}
    for day in days:
        requirements = set(required_by_day.get(day) or set())
        if requirements and all(
            _nfl_requirement_satisfied(req, recognized_pages, recognized_stages)
            for req in requirements
        ):
            success_days.add(day)
        else:
            needed = ",".join("-".join(map(str, req)) for req in sorted(requirements))
            day_errors[day] = (
                "NFL exact official schedule page was not successfully recognized"
                + (f": {needed}" if needed else "")
            )

    count = self.writer.snapshot(
        groups, days, league, source, "AUTHORITATIVE", success_days, day_errors
    )
    success = len(success_days) == len(days)
    error = "" if success else "; ".join(errors[-6:]) or f"{len(days)-len(success_days)} day(s) unproven"
    self._mark_health(
        league, source, "AUTHORITATIVE", day_from, day_to, success, count, error,
        "https://www.nfl.com/schedules/{season}/by-week/{week} [exact-week + final-row parser]",
    )
    return count


def _alias_candidates_hotfix(store, league, slate_date, event, source, tolerance_seconds=20 * 60):
    candidates = _ORIGINAL_ALIAS_CANDIDATES(
        store, league, slate_date, event, source, tolerance_seconds=tolerance_seconds
    )
    if candidates or _clean(league).upper() != "NCAAF":
        return candidates

    away_key, home_key = v619._event_pair("NCAAF", event)
    if not away_key or not home_key:
        return []
    incoming_time = shadow._epoch(shadow._scheduled_at(event))
    if incoming_time is None:
        return []

    target = date.fromisoformat(slate_date)
    days = [(target + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1)]
    provider_ids = shadow._provider_ids(event, source)
    placeholders = ",".join("?" for _ in days)
    with store._lock, closing(store._connect(readonly=True)) as conn:
        rows = [dict(x) for x in conn.execute(
            f"""SELECT * FROM canonical_event
                WHERE competition_id='NCAAF' AND slate_date IN ({placeholders}) AND active=1
                ORDER BY first_seen_at,canonical_event_id""",
            days,
        ).fetchall()]

    compatible = []
    for row in rows:
        if v619._row_pair("NCAAF", row) != (away_key, home_key):
            continue
        existing_time = shadow._epoch(row.get("scheduled_at"))
        if existing_time is None:
            continue
        delta = abs(incoming_time - existing_time)
        same_day_drift = row.get("slate_date") == slate_date and delta <= 3 * 3600
        adjacent_day_offset = abs(delta - 24 * 3600) <= 10 * 60
        if not (same_day_drift or adjacent_day_offset):
            continue
        if not v619._provider_compatible(store, row["canonical_event_id"], provider_ids):
            continue
        compatible.append(row)
    return compatible


def _row_source_classes(store, row):
    return set(store.evidence_classes(str(row["canonical_event_id"])))


def _repair_ncaaf_alias_duplicates(store):
    """Merge only one-to-one live-proven NCAA alias/drift duplicates."""
    with store._lock, closing(store._connect(readonly=True)) as conn:
        rows = [dict(x) for x in conn.execute(
            """SELECT * FROM canonical_event
               WHERE competition_id='NCAAF' AND active=1 AND scheduled_at<>''
               ORDER BY first_seen_at,canonical_event_id"""
        ).fetchall()]

    by_pair = defaultdict(list)
    for row in rows:
        pair = v619._row_pair("NCAAF", row)
        if all(pair):
            by_pair[pair].append(row)

    merged = []
    touched = set()
    for _pair, candidates in by_pair.items():
        if len(candidates) != 2:
            continue
        first, second = candidates
        t1 = shadow._epoch(first.get("scheduled_at"))
        t2 = shadow._epoch(second.get("scheduled_at"))
        if t1 is None or t2 is None:
            continue
        delta = abs(t1 - t2)
        same_eastern_day = (
            datetime.fromtimestamp(t1, shadow.ET).date()
            == datetime.fromtimestamp(t2, shadow.ET).date()
        )
        acceptable_drift = (same_eastern_day and delta <= 3 * 3600) or abs(delta - 24 * 3600) <= 10 * 60
        if not acceptable_drift:
            continue

        classes1, classes2 = _row_source_classes(store, first), _row_source_classes(store, second)
        auth_only_1 = "AUTHORITATIVE" in classes1 and "INDEPENDENT" not in classes1
        auth_only_2 = "AUTHORITATIVE" in classes2 and "INDEPENDENT" not in classes2
        broader_1 = "INDEPENDENT" in classes1 and ("DIRECT" in classes1 or "LEGACY" in classes1)
        broader_2 = "INDEPENDENT" in classes2 and ("DIRECT" in classes2 or "LEGACY" in classes2)
        if auth_only_1 and broader_2:
            loser, survivor = first, second
        elif auth_only_2 and broader_1:
            loser, survivor = second, first
        else:
            continue

        canonical_day = _clean(survivor.get("slate_date"))
        if not canonical_day:
            canonical_day = datetime.fromtimestamp(
                shadow._epoch(survivor.get("scheduled_at")), shadow.ET
            ).date().isoformat()
        if v619._merge_event(store, survivor, loser, canonical_day):
            merged.append({
                "survivor": survivor["canonical_event_id"],
                "merged": loser["canonical_event_id"],
                "away": survivor.get("away_name"),
                "home": survivor.get("home_name"),
                "canonicalDate": canonical_day,
                "driftSeconds": int(delta),
            })
            touched.add((_clean(first.get("slate_date")), "NCAAF"))
            touched.add((_clean(second.get("slate_date")), "NCAAF"))
            touched.add((canonical_day, "NCAAF"))

    for day, league in sorted(x for x in touched if x[0]):
        try:
            store.compile_slate(day, league, "NCAAF_ALIAS_DRIFT_REPAIR", force_version=True)
        except Exception:
            pass
    return {
        "merged": len(merged),
        "pairs": merged,
        "touched": sorted([list(x) for x in touched if x[0]]),
    }


def _install_ncaaf_schedule_drift_guard():
    cls = shadow.CanonicalShadowStore
    if getattr(cls, "__sbbV6116NcaafScheduleDriftGuard", False):
        return
    original = cls.upsert_event

    def upsert_event(
        self, canonical_event_id, league, slate_date, event, source,
        identity_state, inclusion_state, inclusion_reason,
    ):
        protected_event = event
        if _clean(league).upper() == "NCAAF" and _clean(source).upper() == "NCAA_SD_DATA":
            try:
                with self._lock, closing(self._connect(readonly=True)) as conn:
                    row = conn.execute(
                        "SELECT scheduled_at FROM canonical_event WHERE canonical_event_id=? AND active=1",
                        (canonical_event_id,),
                    ).fetchone()
                if row:
                    existing = shadow._epoch(row["scheduled_at"])
                    incoming = shadow._epoch(shadow._scheduled_at(event))
                    classes = set(self.evidence_classes(canonical_event_id))
                    if (
                        existing is not None and incoming is not None
                        and abs(existing - incoming) > 20 * 60
                        and "INDEPENDENT" in classes
                        and ("DIRECT" in classes or "LEGACY" in classes)
                    ):
                        protected_event = dict(event)
                        protected_event["scheduledAt"] = ""
            except Exception:
                protected_event = event
        return original(
            self, canonical_event_id, league, slate_date, protected_event, source,
            identity_state, inclusion_state, inclusion_reason,
        )

    cls.upsert_event = upsert_event
    cls.__sbbV6116NcaafScheduleDriftGuard = True


def _patch_health():
    cls = v610.CertificationEngine
    if getattr(cls, "__sbbV6116CanonicalReconcileHealth", False):
        return
    original = cls.health

    def health(self):
        payload = original(self)
        payload["canonicalReconcileHotfixVersion"] = VERSION
        payload.setdefault("hardening", {}).update({
            "nflExactWeekCoverageProof": True,
            "nflCompletedFinalRowParser": True,
            "ncaafGuardedAliasDriftReconciliation": True,
            "ncaafAuthoritativeScheduleDriftCanonicalGuard": True,
            "ncaafOfficialExplicitDateRehome": False,
            "productionAuthority": False,
        })
        return payload

    cls.health = health
    cls.__sbbV6116CanonicalReconcileHealth = True


def _runtime_install():
    global _PATCHED
    deadline = time.time() + 180

    # v6.1.16's explicit-date rehome is useful for most trusted sources, but the
    # NCAA contestDate/startTime combination demonstrated a one-day stale drift.
    # Do not allow that single source to re-home an already cross-source-resolved
    # NCAAF identity.
    v6116.TRUSTED_SLATE_DATE_SOURCES.discard("NCAA_SD_DATA")

    v611.install()
    v619.install()
    v6116.install()

    engine = None
    while time.time() < deadline:
        engine = v6116.engine() or v611.engine()
        if v6116.engine() is not None:
            break
        time.sleep(0.1)
    if engine is None:
        return

    _install_ncaaf_aliases()
    v619._alias_candidates = _alias_candidates_hotfix
    _install_ncaaf_schedule_drift_guard()

    cls = v610.CertificationEngine
    cls._nfl_pages = _nfl_pages_strict
    cls._collect_nfl = _collect_nfl_hotfix
    _patch_health()
    _PATCHED = True

    repair = _repair_ncaaf_alias_duplicates(engine.store)
    try:
        server = sys.modules.get("__main__")
        if server is not None:
            server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update({
                "canonicalReconcileHotfixVersion": VERSION,
                "nflExactWeekCoverageProof": True,
                "nflCompletedFinalRowParser": True,
                "ncaafGuardedAliasDriftReconciliation": True,
                "ncaafOfficialExplicitDateRehome": False,
                "identityRepairHotfix": repair,
                "productionAuthority": False,
            })
    except Exception:
        pass

    # Refresh immediately so stale successful-zero coverage is replaced with
    # exact-week evidence (or a visible failed-coverage row) without waiting for
    # the normal full-cycle interval.
    try:
        engine.run_horizon()
    except Exception as exc:
        engine.last_error = f"v6.1.16 canonical reconcile hotfix: {type(exc).__name__}: {exc}"


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    threading.Thread(
        target=_runtime_install,
        daemon=True,
        name="sbb-canonical-reconcile-hotfix-v6116",
    ).start()

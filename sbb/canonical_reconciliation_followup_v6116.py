"""Sports Big Board v6.1.16 canonical reconciliation follow-up.

Shadow/certification only. Production Day State remains the event authority.

This follow-up addresses defects exposed after the first v6.1.16 reconciliation
hotfix reached production:

* NFL.com changes its rendered game label while a game is LIVE. Bind those live
  score rows back to an already-known canonical matchup instead of temporarily
  dropping authoritative membership at kickoff.
* Re-run guarded NCAAF alias reconciliation after every certification collection
  pass, so refreshed official evidence can merge after startup.
* Treat strong MLB/ESPN provider IDs as distinct-event proof before generic
  same-team / gameNumber matching, and repair already-collapsed adjacent-day MLB
  series rows when their observations contain disjoint MLB gamePk values.

Every repair is fail-closed and audit-preserving. No production read model is
modified and no canonical cutover authority is enabled here.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import sys
import threading
import time
import uuid
from collections import defaultdict
from contextlib import closing
from datetime import date

from . import canonical_shadow_v600 as shadow
from . import canonical_certification_v610 as v610
from . import canonical_identity_ingestion_v619 as v619
from . import canonical_certification_v611 as v611
from . import canonical_reconciliation_hotfix_v6116 as base_hotfix
from . import canonical_schedule_watchdogs_v6116 as v6116

VERSION = "6.1.16-canonical-reconcile-followup-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_PATCHED = False

_PRIMARY_EVENT_PROVIDERS = frozenset(("MLB", "ESPN"))

# Explicit aliases remain deliberately narrow and are limited to spellings that
# are demonstrated by the live authoritative/independent reconciliation gaps.
_NCAAF_FOLLOWUP_ALIASES = (
    ("Western Ky.", "Western Kentucky", "Western Kentucky Hilltoppers"),
    ("Indiana", "Indiana Hoosiers"),
    ("Clemson", "Clemson Tigers"),
)

_NFL_NICKNAMES = tuple(sorted(base_hotfix._NFL_NICKNAMES, key=len, reverse=True))
_NFL_TEAM_TOKEN = "|".join(re.escape(x) for x in _NFL_NICKNAMES)
_NFL_LIVE_STATE = r"(?:Q[1-4]|OT|2OT|3OT|HALFTIME|END\s+Q[1-4])"
_NFL_LIVE_RE = re.compile(
    rf"(?P<away>{_NFL_TEAM_TOKEN})\s+(?P<away_score>\d+)\s*,\s*"
    rf"(?P<home>{_NFL_TEAM_TOKEN})\s+(?P<home_score>\d+)\s*,\s*"
    rf"(?P<state>{_NFL_LIVE_STATE})(?:\s*,\s*(?P<network>[A-Z0-9+ ]{{2,20}}))?",
    re.I,
)


def _clean(value):
    return str(value or "").strip()


def _install_followup_aliases():
    bucket = v619._ALIAS_LOOKUP.setdefault("NCAAF", {})
    for group in _NCAAF_FOLLOWUP_ALIASES:
        canonical = shadow._norm(group[0])
        for name in group:
            bucket[shadow._norm(name)] = canonical


def _primary_provider_ids(event, source=""):
    out = defaultdict(set)
    for provider, provider_event_id, _id_type in shadow._provider_ids(event, source):
        provider = _clean(provider).upper()
        provider_event_id = _clean(provider_event_id)
        if provider in _PRIMARY_EVENT_PROVIDERS and provider_event_id:
            out[provider].add(provider_event_id)
    return out


def _primary_mapping_conflict(store, canonical_event_id, event, source=""):
    """True when a candidate already owns a different primary event ID.

    This is intentionally provider-scoped. A source-local synthetic `eventId`
    from a different source does not veto a merge, while MLB gamePk and ESPN
    event IDs do because they identify one concrete game.
    """
    incoming = _primary_provider_ids(event, source)
    if not incoming:
        return False
    existing = defaultdict(set)
    for mapping in store.mappings_for_event(canonical_event_id):
        provider = _clean(mapping.get("provider")).upper()
        provider_event_id = _clean(mapping.get("provider_event_id"))
        if provider in _PRIMARY_EVENT_PROVIDERS and provider_event_id:
            existing[provider].add(provider_event_id)
    for provider, incoming_ids in incoming.items():
        if existing.get(provider) and existing[provider].isdisjoint(incoming_ids):
            return True
    return False


def _install_strong_provider_identity_guard():
    """Put strong MLB/ESPN identity ahead of same-pair sequence shortcuts."""
    writer_cls = v610.CertificationEvidenceWriter
    if not getattr(writer_cls, "__sbbV6116StrongProviderWriterGuard", False):
        original_match = writer_cls._match_existing

        def _match_existing(self, league, day, event):
            existing_id = original_match(self, league, day, event)
            if (
                existing_id
                and _clean(league).upper() == "MLB"
                and _primary_mapping_conflict(self.store, existing_id, event)
            ):
                # Let the canonical resolver create/choose the correct distinct
                # identity rather than attaching a second game to this row.
                return ""
            return existing_id

        writer_cls._match_existing = _match_existing
        writer_cls.__sbbV6116StrongProviderWriterGuard = True

    resolver_cls = shadow.CanonicalIdentityResolver
    if not getattr(resolver_cls, "__sbbV6116StrongProviderResolverGuard", False):
        original_resolve = resolver_cls.resolve

        def resolve(self, league, slate_date, event, source):
            result = original_resolve(self, league, slate_date, event, source)
            if _clean(league).upper() != "MLB":
                return result

            selected = result[0] if len(result) >= 1 else ""
            method = result[2] if len(result) >= 3 else ""
            # A mapped strong provider ID is definitive and must remain untouched.
            if method == "PROVIDER_MAPPING":
                return result

            if selected:
                with self.store._lock, closing(self.store._connect(readonly=True)) as conn:
                    row = conn.execute(
                        "SELECT canonical_event_id FROM canonical_event "
                        "WHERE canonical_event_id=? AND active=1",
                        (selected,),
                    ).fetchone()
                if row and _primary_mapping_conflict(self.store, selected, event, source):
                    return self._new_id(), "RESOLVED", "STRONG_PROVIDER_DISTINCT_EVENT"

            # If the old resolver declared a same-pair collision, but every
            # candidate has a strong provider conflict, this is not ambiguous:
            # the incoming event is a distinct game.
            if len(result) >= 2 and _clean(result[1]).startswith("UNRESOLVED"):
                away_key = shadow._team_key(event, "away")
                home_key = shadow._team_key(event, "home")
                candidates = self.store.pair_candidates(
                    _clean(league).upper(), slate_date, away_key, home_key
                )
                if candidates and all(
                    _primary_mapping_conflict(
                        self.store, row["canonical_event_id"], event, source
                    )
                    for row in candidates
                ):
                    return self._new_id(), "RESOLVED", "STRONG_PROVIDER_DISTINCT_EVENT"
            return result

        resolver_cls.resolve = resolve
        resolver_cls.__sbbV6116StrongProviderResolverGuard = True


def _nfl_candidate_rows(store, away_name, home_name, allowed_days):
    away_key = shadow._norm(away_name)
    home_key = shadow._norm(home_name)
    allowed_days = sorted(set(allowed_days or ()))
    if not away_key or not home_key or not allowed_days:
        return []
    placeholders = ",".join("?" for _ in allowed_days)
    with store._lock, closing(store._connect(readonly=True)) as conn:
        rows = [
            dict(x)
            for x in conn.execute(
                f"""SELECT * FROM canonical_event
                    WHERE competition_id='NFL' AND active=1
                      AND slate_date IN ({placeholders})
                    ORDER BY slate_date,scheduled_at,canonical_event_id""",
                allowed_days,
            ).fetchall()
        ]
    matches = []
    for row in rows:
        if (
            shadow._norm(row.get("away_name")) == away_key
            and shadow._norm(row.get("home_name")) == home_key
        ):
            matches.append(row)
    return matches


def _existing_nfl_source_event_id(store, canonical_event_id):
    for mapping in store.mappings_for_event(canonical_event_id):
        if _clean(mapping.get("provider")).upper() == "NFL_COM_SCHEDULE":
            value = _clean(mapping.get("provider_event_id"))
            if value:
                return value
    return ""


def _nfl_live_events_from_html(text, season, store, allowed_days):
    """Parse NFL.com LIVE rows and bind them only to one known canonical game.

    NFL.com's live label does not expose the game date/kickoff. The independent
    collector runs first, so an exact away/home canonical matchup should already
    exist. We accept the live row only when exactly one active candidate exists
    inside the requested official week/date window.
    """
    decoded = html_lib.unescape(_clean(text))
    candidates = re.findall(r"aria-label=[\"']([^\"']+)[\"']", decoded, flags=re.I)
    candidates.append(re.sub(r"<[^>]+>", " ", decoded))
    events = []
    seen = set()
    for candidate in candidates:
        for match in _NFL_LIVE_RE.finditer(candidate):
            away = v611._nfl_team(match.group("away"))
            home = v611._nfl_team(match.group("home"))
            rows = _nfl_candidate_rows(
                store,
                away.get("displayName"),
                home.get("displayName"),
                allowed_days,
            )
            if len(rows) != 1:
                continue
            row = rows[0]
            key = (
                row["canonical_event_id"],
                match.group("away_score"),
                match.group("home_score"),
                match.group("state").upper(),
            )
            if key in seen:
                continue
            seen.add(key)
            event_id = _existing_nfl_source_event_id(
                store, row["canonical_event_id"]
            ) or ("nfl:" + shadow._payload_hash([
                row.get("slate_date"),
                away.get("displayName"),
                home.get("displayName"),
            ])[:20])
            events.append({
                "competitionId": "NFL",
                "__sbbDate": row.get("slate_date"),
                "eventId": event_id,
                "scheduledAt": row.get("scheduled_at") or "",
                "status": "LIVE",
                "away": away,
                "home": home,
                "awayScore": match.group("away_score"),
                "homeScore": match.group("home_score"),
                "name": f"{away.get('displayName')} @ {home.get('displayName')}",
            })
    return events


def _collect_nfl_followup(self, day_from, day_to):
    league, source = "NFL", v610.SOURCE_DEFS["NFL"]["authoritative"]
    days = v610._date_range(day_from, day_to)
    pages, required_by_day = self._nfl_pages(days)
    groups = defaultdict(list)
    recognized_pages = set()
    recognized_stages = set()
    errors = []

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
            page_events.extend(base_hotfix._nfl_final_events_from_html(text, season))
            # The current requested horizon is the only safe date binding space
            # for date-less live labels.
            page_events.extend(
                _nfl_live_events_from_html(text, season, self.store, days)
            )

            # One matchup may appear simultaneously in hydration + accessibility
            # markup. Dedupe on canonical game shape rather than transient label ID.
            deduped = {}
            for event in page_events:
                day = _clean(event.get("__sbbDate"))
                away = shadow._norm((event.get("away") or {}).get("displayName"))
                home = shadow._norm((event.get("home") or {}).get("displayName"))
                if not day or not away or not home:
                    continue
                key = (day, away, home)
                prior = deduped.get(key)
                if prior is None:
                    deduped[key] = event
                    continue
                # Prefer LIVE/FINAL over a stale SCHEDULED representation.
                rank = {"SCHEDULED": 0, "LIVE": 1, "FINAL": 2}
                if rank.get(shadow._status(event), 0) > rank.get(shadow._status(prior), 0):
                    deduped[key] = event

            if not deduped:
                raise RuntimeError(
                    f"NFL page contained no recognized schedule events ({stage}{week})"
                )

            recognized_pages.add((season, stage, week))
            recognized_stages.add((season, stage))
            for event in deduped.values():
                if event.get("__sbbDate") in days:
                    groups[event["__sbbDate"]].append(event)
        except Exception as exc:
            errors.append(f"{stage}{week}: {type(exc).__name__}: {exc}")

    success_days = set()
    day_errors = {}
    for day in days:
        requirements = set(required_by_day.get(day) or set())
        if requirements and all(
            base_hotfix._nfl_requirement_satisfied(
                req, recognized_pages, recognized_stages
            )
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
    error = (
        ""
        if success
        else "; ".join(errors[-6:])
        or f"{len(days)-len(success_days)} day(s) unproven"
    )
    self._mark_health(
        league,
        source,
        "AUTHORITATIVE",
        day_from,
        day_to,
        success,
        count,
        error,
        "https://www.nfl.com/schedules/{season}/by-week/{week} "
        "[exact-week + pre/live/final parser]",
    )
    return count


def _observation_raw(row):
    try:
        value = json.loads(row.get("raw_json") or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _observation_day(row):
    raw = _observation_raw(row)
    fallback = _clean(row.get("observed_day"))
    return v619._scheduled_et_day(raw, fallback)


def _observation_primary_pairs(row):
    raw = _observation_raw(row)
    source = _clean(row.get("source"))
    pairs = set()
    for provider, provider_event_id, _id_type in shadow._provider_ids(raw, source):
        provider = _clean(provider).upper()
        provider_event_id = _clean(provider_event_id)
        if provider in _PRIMARY_EVENT_PROVIDERS and provider_event_id:
            pairs.add((provider, provider_event_id))
    return pairs


def _best_split_observation(rows):
    priority = {
        "MLB_STATS_API": 0,
        "ESPN_INDEPENDENT": 1,
        "ESPN_DIRECT": 2,
        "DAY_STATE": 3,
        "HISTORY_CATALOG": 4,
    }
    return min(
        rows,
        key=lambda row: (
            priority.get(_clean(row.get("source")).upper(), 50),
            -float(row.get("last_observed_at") or 0),
        ),
    )


def _repair_mlb_cross_day_collapses(engine):
    """Split future MLB rows that contain hard proof of two adjacent-day games.

    A split requires:
      * one active SCHEDULED MLB canonical row;
      * schedule observations on adjacent Eastern slate dates;
      * an MLB gamePk on both date groups; and
      * disjoint gamePk values between keeper and split groups.

    This intentionally does not infer from team names or times alone.
    """
    store = engine.store
    with store._lock, closing(store._connect(readonly=True)) as conn:
        canonical_rows = [
            dict(x)
            for x in conn.execute(
                """SELECT * FROM canonical_event
                   WHERE competition_id='MLB' AND active=1 AND status='SCHEDULED'
                   ORDER BY slate_date,canonical_event_id"""
            ).fetchall()
        ]

    splits = []
    touched = set()
    for canonical in canonical_rows:
        canonical_id = str(canonical["canonical_event_id"])
        with store._lock, closing(store._connect(readonly=True)) as conn:
            observations = [
                dict(x)
                for x in conn.execute(
                    """SELECT * FROM schedule_observation
                       WHERE canonical_event_id=?
                       ORDER BY last_observed_at DESC,id DESC""",
                    (canonical_id,),
                ).fetchall()
            ]
        by_day = defaultdict(list)
        for observation in observations:
            day = _observation_day(observation)
            if day:
                by_day[day].append(observation)
        if len(by_day) < 2:
            continue

        keeper_day = _clean(canonical.get("slate_date"))
        if keeper_day not in by_day:
            keeper_day = v619._scheduled_et_day(
                _observation_raw(_best_split_observation(observations)),
                keeper_day,
            )
        if keeper_day not in by_day:
            continue

        keeper_game_pks = {
            pid
            for row in by_day[keeper_day]
            for provider, pid in _observation_primary_pairs(row)
            if provider == "MLB"
        }
        if not keeper_game_pks:
            continue

        for target_day, target_rows in sorted(by_day.items()):
            if target_day == keeper_day:
                continue
            try:
                gap = abs(
                    (date.fromisoformat(target_day) - date.fromisoformat(keeper_day)).days
                )
            except Exception:
                continue
            if gap != 1:
                continue

            target_game_pks = {
                pid
                for row in target_rows
                for provider, pid in _observation_primary_pairs(row)
                if provider == "MLB"
            }
            if not target_game_pks or not keeper_game_pks.isdisjoint(target_game_pks):
                continue

            # Do not split twice if the target hard provider ID already owns a
            # different active canonical row.
            existing_target = ""
            with store._lock, closing(store._connect(readonly=True)) as conn:
                for game_pk in sorted(target_game_pks):
                    row = conn.execute(
                        """SELECT p.canonical_event_id
                           FROM provider_event_mapping p
                           JOIN canonical_event c
                             ON c.canonical_event_id=p.canonical_event_id
                          WHERE p.provider='MLB' AND p.provider_event_id=?
                            AND c.active=1""",
                        (game_pk,),
                    ).fetchone()
                    if row and str(row[0]) != canonical_id:
                        existing_target = str(row[0])
                        break
            if existing_target:
                continue

            best = _best_split_observation(target_rows)
            raw = _observation_raw(best)
            if not raw:
                continue
            new_id = "cev_" + uuid.uuid4().hex[:24]
            inclusion = _clean(canonical.get("inclusion_state")) or "INCLUDED"
            inclusion_reason = (
                _clean(canonical.get("inclusion_reason"))
                or "MLB_ADJACENT_DAY_PROVIDER_SPLIT"
            )
            store.upsert_event(
                new_id,
                "MLB",
                target_day,
                raw,
                _clean(best.get("source")) or "MLB_STATS_API",
                "RESOLVED",
                inclusion,
                inclusion_reason,
            )

            target_obs_ids = [int(row["id"]) for row in target_rows]
            placeholders = ",".join("?" for _ in target_obs_ids)
            keeper_pairs = {
                pair
                for row in by_day[keeper_day]
                for pair in _observation_primary_pairs(row)
            }
            target_pairs = {
                pair
                for row in target_rows
                for pair in _observation_primary_pairs(row)
            }
            move_pairs = target_pairs - keeper_pairs

            with store._lock, closing(store._connect()) as conn:
                conn.execute(
                    f"""UPDATE schedule_observation
                        SET canonical_event_id=?
                        WHERE canonical_event_id=? AND id IN ({placeholders})""",
                    [new_id, canonical_id, *target_obs_ids],
                )
                for provider, provider_event_id in sorted(move_pairs):
                    conn.execute(
                        """UPDATE provider_event_mapping
                           SET canonical_event_id=?,last_seen_at=?
                           WHERE canonical_event_id=?
                             AND provider=? AND provider_event_id=?""",
                        (
                            new_id,
                            shadow._now(),
                            canonical_id,
                            provider,
                            provider_event_id,
                        ),
                    )
                conn.commit()

            # Raw source-local IDs (DAY_STATE/HISTORY/etc.) are useful for future
            # routing too. Re-add them now that primary mappings have moved.
            for row in target_rows:
                raw_row = _observation_raw(row)
                if raw_row:
                    store.upsert_mappings(
                        new_id,
                        shadow._provider_ids(raw_row, _clean(row.get("source"))),
                    )

            touched.add((target_day, "MLB"))
            touched.add((keeper_day, "MLB"))
            splits.append({
                "survivor": canonical_id,
                "split": new_id,
                "away": canonical.get("away_name"),
                "home": canonical.get("home_name"),
                "survivorDate": keeper_day,
                "splitDate": target_day,
                "survivorGamePks": sorted(keeper_game_pks),
                "splitGamePks": sorted(target_game_pks),
            })
            # One canonical row should represent at most one accidental adjacent
            # merge in this repair pass. A subsequent cycle can reassess safely.
            break

    for day, league in sorted(touched):
        try:
            store.compile_slate(
                day, league, "MLB_STRONG_PROVIDER_SPLIT_REPAIR", force_version=True
            )
        except Exception:
            pass
    return {
        "split": len(splits),
        "pairs": splits,
        "touched": sorted([list(x) for x in touched]),
    }


def _post_collection_repairs(engine):
    mlb = _repair_mlb_cross_day_collapses(engine)

    # Refresh comparison identity for only the repaired MLB dates. Production is
    # still Day State, but its ESPN IDs now resolve to the split canonical rows.
    shadow_engine = getattr(engine, "shadow", None)
    if shadow_engine is not None:
        for day, league in mlb.get("touched", []):
            if league != "MLB":
                continue
            try:
                _count, legacy_ids, _touched, snapshot_present = (
                    shadow_engine.ingest_day_state(day)
                )
                if snapshot_present:
                    engine.store.record_comparison(
                        day, "MLB", legacy_ids.get("MLB", set())
                    )
            except Exception:
                pass

    ncaaf = base_hotfix._repair_ncaaf_alias_duplicates(engine.store)
    return {"mlb": mlb, "ncaaf": ncaaf}


def _install_post_collection_reconciliation():
    cls = v610.CertificationEngine
    if getattr(cls, "__sbbV6116PostCollectionReconciliation", False):
        return
    original_run = cls.run_horizon

    def run_horizon(self):
        stats = original_run(self)
        try:
            repair = _post_collection_repairs(self)
            if isinstance(stats, dict):
                stats["postCollectionRepairs"] = repair
                self.last_stats = stats
            # Repairs alter identity membership after the base run compiled its
            # slates. Recompile touched dates so effective/persisted state agrees
            # immediately rather than waiting for the next worker cycle.
            for section in repair.values():
                for item in section.get("touched", []):
                    day, league = item
                    try:
                        self.store.compile_slate(
                            day,
                            league,
                            "POST_COLLECTION_RECONCILIATION",
                            force_version=True,
                        )
                    except Exception:
                        pass
        except Exception as exc:
            if isinstance(stats, dict):
                stats.setdefault("errors", []).append(
                    f"post-collection reconciliation: {type(exc).__name__}: {exc}"
                )
            self.last_error = (
                f"post-collection reconciliation: {type(exc).__name__}: {exc}"
            )
        return stats

    cls.run_horizon = run_horizon
    cls.__sbbV6116PostCollectionReconciliation = True


def _patch_health():
    cls = v610.CertificationEngine
    if getattr(cls, "__sbbV6116CanonicalFollowupHealth", False):
        return
    original = cls.health

    def health(self):
        payload = original(self)
        payload["canonicalReconcileFollowupVersion"] = VERSION
        payload.setdefault("hardening", {}).update({
            "nflLiveRowParser": True,
            "nflPregameLiveFinalContinuity": True,
            "ncaafPostCollectionAliasRepair": True,
            "mlbStrongProviderIdentityGuard": True,
            "mlbAdjacentDayCollapseRepair": True,
            "productionAuthority": False,
        })
        return payload

    cls.health = health
    cls.__sbbV6116CanonicalFollowupHealth = True


def _runtime_install():
    global _PATCHED
    deadline = time.time() + 180

    base_hotfix.install()
    engine = None
    while time.time() < deadline:
        engine = v6116.engine()
        if engine is not None and getattr(base_hotfix, "_PATCHED", False):
            break
        time.sleep(0.1)
    if engine is None:
        return

    _install_followup_aliases()
    _install_strong_provider_identity_guard()

    cls = v610.CertificationEngine
    cls._collect_nfl = _collect_nfl_followup
    _install_post_collection_reconciliation()
    _patch_health()
    _PATCHED = True

    initial_repair = _post_collection_repairs(engine)
    try:
        server = sys.modules.get("__main__")
        if server is not None:
            server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update({
                "canonicalReconcileFollowupVersion": VERSION,
                "nflPregameLiveFinalContinuity": True,
                "ncaafPostCollectionAliasRepair": True,
                "mlbStrongProviderIdentityGuard": True,
                "mlbAdjacentDayCollapseRepair": True,
                "followupIdentityRepair": initial_repair,
                "productionAuthority": False,
            })
    except Exception:
        pass

    # Refresh now so the new live parser and post-collection repairs become
    # visible in the validation console without waiting for the next 15-minute run.
    try:
        engine.run_horizon()
    except Exception as exc:
        engine.last_error = (
            f"v6.1.16 canonical reconcile follow-up: {type(exc).__name__}: {exc}"
        )


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    threading.Thread(
        target=_runtime_install,
        daemon=True,
        name="sbb-canonical-reconcile-followup-v6116",
    ).start()

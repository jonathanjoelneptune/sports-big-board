"""Sports Big Board v6.1.9 canonical identity + ingestion repair.

Shadow-only hardening for the canonical slate lane. Production authority remains
false. This patch addresses the concrete reconciliation defects observed after
v6.1.8:

* scheduled kickoff owns slate_date at ingestion time using America/New_York;
* conservative league-aware aliases merge equivalent MLS/NCAAF identities without
  globally lowering fuzzy-match thresholds;
* existing duplicate identities are consolidated by evidence while the superseded
  row remains inactive for audit history;
* NCAAF authoritative/independent raw-universe count variance is non-blocking when
  every INCLUDED event is independently proven and the variance is therefore only
  outside the board's inclusion policy;
* validation-console worker output exposes the v6.1.8 in-progress timing fields.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import defaultdict
from contextlib import closing
from datetime import datetime

from . import canonical_shadow_v600 as shadow
from . import canonical_certification_v610 as v610
from . import canonical_certification_v611 as v611
from . import canonical_validation_v612 as v612

VERSION = "6.1.9-canonical-identity-ingestion-1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False

# Explicit aliases are deliberately narrow. The generic normalizer remains strict;
# these are provider spelling variants demonstrated by live canonical evidence.
_ALIAS_GROUPS = {
    "MLS": (
        ("New York City Football Club", "New York City FC"),
        ("Los Angeles Football Club", "Los Angeles FC", "LAFC"),
        ("Red Bull New York", "New York Red Bulls"),
    ),
    "NCAAF": (
        ("Western Ky.", "Western Kentucky", "Western Kentucky Hilltoppers"),
        ("Southern U.", "Southern University", "Southern Jaguars"),
        ("N.C. A&T", "North Carolina A&T", "North Carolina A&T Aggies"),
    ),
}
_ALIAS_LOOKUP = {}
for _league, _groups in _ALIAS_GROUPS.items():
    bucket = {}
    for _group in _groups:
        canonical = shadow._norm(_group[0])
        for _name in _group:
            bucket[shadow._norm(_name)] = canonical
    _ALIAS_LOOKUP[_league] = bucket


def _clean(value):
    return str(value or "").strip()


def _canonical_team_key(league, value):
    key = shadow._norm(value)
    league = _clean(league).upper()
    if league == "MLS":
        # Safe structural equivalence before explicit aliases.
        key = key.replace("footballclub", "fc").replace("soccerclub", "sc")
    return _ALIAS_LOOKUP.get(league, {}).get(key, key)


def _event_pair(league, event):
    return (
        _canonical_team_key(league, shadow._team_name(event, "away")),
        _canonical_team_key(league, shadow._team_name(event, "home")),
    )


def _row_pair(league, row):
    return (
        _canonical_team_key(league, row.get("away_name")),
        _canonical_team_key(league, row.get("home_name")),
    )


def _scheduled_et_day(event, fallback=""):
    ts = shadow._epoch(shadow._scheduled_at(event))
    if ts is not None:
        try:
            return datetime.fromtimestamp(ts, shadow.ET).date().isoformat()
        except Exception:
            pass
    return shadow._event_day(event, fallback)


def _provider_compatible(store, canonical_event_id, provider_ids):
    incoming = defaultdict(set)
    for provider, provider_event_id, _id_type in provider_ids:
        incoming[str(provider)].add(str(provider_event_id))
    if not incoming:
        return True
    for mapping in store.mappings_for_event(canonical_event_id):
        provider = str(mapping.get("provider") or "")
        if provider in incoming and str(mapping.get("provider_event_id") or "") not in incoming[provider]:
            return False
    return True


def _alias_candidates(store, league, slate_date, event, source, tolerance_seconds=20 * 60):
    away_key, home_key = _event_pair(league, event)
    if not away_key or not home_key:
        return []
    incoming_time = shadow._epoch(shadow._scheduled_at(event))
    provider_ids = shadow._provider_ids(event, source)
    with store._lock, closing(store._connect(readonly=True)) as conn:
        rows = [dict(x) for x in conn.execute(
            """SELECT * FROM canonical_event
               WHERE competition_id=? AND slate_date=? AND active=1
               ORDER BY first_seen_at,canonical_event_id""",
            (league, slate_date),
        ).fetchall()]
    compatible = []
    for row in rows:
        if _row_pair(league, row) != (away_key, home_key):
            continue
        existing_time = shadow._epoch(row.get("scheduled_at"))
        if incoming_time is not None and existing_time is not None:
            if abs(incoming_time - existing_time) > tolerance_seconds:
                continue
        if not _provider_compatible(store, row["canonical_event_id"], provider_ids):
            continue
        compatible.append(row)
    return compatible


def _install_alias_resolver():
    cls = shadow.CanonicalIdentityResolver
    if getattr(cls, "__sbbV619AliasResolver", False):
        return
    original = cls.resolve

    def resolve(self, league, slate_date, event, source):
        result = original(self, league, slate_date, event, source)
        # Strong provider mappings and the original exact-pair logic keep priority.
        if len(result) >= 3 and result[2] != "NEW_EVENT":
            return result
        candidates = _alias_candidates(self.store, league, slate_date, event, source)
        if len(candidates) == 1:
            return candidates[0]["canonical_event_id"], "RESOLVED", "LEAGUE_ALIAS_TIME"
        return result

    cls.resolve = resolve
    cls.__sbbV619AliasResolver = True


def _install_ingestion_date_ownership():
    cls = shadow.CanonicalShadowEngine
    if getattr(cls, "__sbbV619EasternIngestion", False):
        return
    original = cls.observe_event

    def observe_event(
        self, event, league, slate_date, source, source_class="LEGACY",
        inclusion_state=None, inclusion_reason=None,
    ):
        if isinstance(event, dict):
            canonical_day = _scheduled_et_day(event, slate_date)
            if canonical_day:
                event = dict(event)
                event["__sbbDate"] = canonical_day
                event["canonicalSlateDate"] = canonical_day
                slate_date = canonical_day
        return original(
            self, event, league, slate_date, source, source_class,
            inclusion_state, inclusion_reason,
        )

    cls.observe_event = observe_event
    cls.__sbbV619EasternIngestion = True


def _event_quality(store, row, canonical_day):
    event_id = str(row["canonical_event_id"])
    classes = set(store.evidence_classes(event_id))
    mappings = store.mappings_for_event(event_id)
    # Correct-day ownership first, then cross-source breadth, then authoritative
    # evidence, then provider mappings, then stable oldest identity.
    return (
        int(_clean(row.get("slate_date")) == canonical_day),
        len(classes),
        int("AUTHORITATIVE" in classes),
        len(mappings),
        -float(row.get("first_seen_at") or 0.0),
    )


def _copy_schedule_evidence(conn, survivor, loser):
    rows = conn.execute(
        "SELECT * FROM schedule_observation WHERE canonical_event_id=?",
        (loser,),
    ).fetchall()
    for row in rows:
        conn.execute(
            """INSERT INTO schedule_observation(
                canonical_event_id,source,source_class,observed_day,observed_at,last_observed_at,
                observation_count,scheduled_at,status,payload_hash,raw_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(canonical_event_id,source,payload_hash) DO UPDATE SET
                last_observed_at=MAX(schedule_observation.last_observed_at,excluded.last_observed_at),
                observation_count=MAX(schedule_observation.observation_count,excluded.observation_count)""",
            (
                survivor, row["source"], row["source_class"], row["observed_day"],
                row["observed_at"], row["last_observed_at"], row["observation_count"],
                row["scheduled_at"], row["status"], row["payload_hash"], row["raw_json"],
            ),
        )


def _copy_score_evidence(conn, survivor, loser):
    rows = conn.execute(
        "SELECT * FROM score_observation WHERE canonical_event_id=?",
        (loser,),
    ).fetchall()
    for row in rows:
        conn.execute(
            """INSERT INTO score_observation(
                canonical_event_id,source,observed_at,last_observed_at,observation_count,
                status,away_score,home_score,period,clock,payload_hash
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(canonical_event_id,source,payload_hash) DO UPDATE SET
                last_observed_at=MAX(score_observation.last_observed_at,excluded.last_observed_at),
                observation_count=MAX(score_observation.observation_count,excluded.observation_count)""",
            (
                survivor, row["source"], row["observed_at"], row["last_observed_at"],
                row["observation_count"], row["status"], row["away_score"], row["home_score"],
                row["period"], row["clock"], row["payload_hash"],
            ),
        )


def _merge_event(store, survivor_row, loser_row, canonical_day):
    survivor = str(survivor_row["canonical_event_id"])
    loser = str(loser_row["canonical_event_id"])
    if survivor == loser:
        return False
    now = shadow._now()
    survivor_inclusion = _clean(survivor_row.get("inclusion_state")).upper()
    loser_inclusion = _clean(loser_row.get("inclusion_state")).upper()
    if "INCLUDED" in {survivor_inclusion, loser_inclusion}:
        inclusion_state = "INCLUDED"
        inclusion_reason = (
            survivor_row.get("inclusion_reason") if survivor_inclusion == "INCLUDED"
            else loser_row.get("inclusion_reason")
        ) or "MERGED_INCLUDED_EVIDENCE"
    elif survivor_inclusion == loser_inclusion == "EXCLUDED":
        inclusion_state = "EXCLUDED"
        inclusion_reason = survivor_row.get("inclusion_reason") or loser_row.get("inclusion_reason") or "MERGED_EXCLUDED_EVIDENCE"
    else:
        inclusion_state = survivor_inclusion or loser_inclusion or "UNKNOWN"
        inclusion_reason = survivor_row.get("inclusion_reason") or loser_row.get("inclusion_reason") or "MERGED_IDENTITY_EVIDENCE"

    with store._lock, closing(store._connect()) as conn:
        _copy_schedule_evidence(conn, survivor, loser)
        _copy_score_evidence(conn, survivor, loser)
        # Provider IDs must follow the surviving identity so all future observations
        # resolve there. provider/provider_event_id is globally unique in the schema.
        conn.execute(
            "UPDATE provider_event_mapping SET canonical_event_id=?,last_seen_at=? WHERE canonical_event_id=?",
            (survivor, now, loser),
        )
        conn.execute(
            """UPDATE canonical_event SET slate_date=?,inclusion_state=?,inclusion_reason=?,
               identity_state='RESOLVED',active=1,removal_state='PRESENT',updated_at=?
               WHERE canonical_event_id=?""",
            (canonical_day, inclusion_state, inclusion_reason, now, survivor),
        )
        conn.execute(
            """UPDATE canonical_event SET active=0,removal_state='MERGED_ALIAS',
               identity_state='MERGED',updated_at=? WHERE canonical_event_id=?""",
            (now, loser),
        )
        conn.commit()
    return True


def _repair_duplicate_identities(store, tolerance_seconds=20 * 60):
    """Merge only high-confidence same-match identities; retain losers for audit."""
    with store._lock, closing(store._connect(readonly=True)) as conn:
        rows = [dict(x) for x in conn.execute(
            """SELECT * FROM canonical_event
               WHERE active=1 AND scheduled_at<>'' AND competition_id IN ('MLB','NFL','NBA','NHL','EPL','MLS','NCAAF')
               ORDER BY competition_id,scheduled_at,canonical_event_id"""
        ).fetchall()]

    groups = defaultdict(list)
    for row in rows:
        ts = shadow._epoch(row.get("scheduled_at"))
        if ts is None:
            continue
        canonical_day = datetime.fromtimestamp(ts, shadow.ET).date().isoformat()
        pair = _row_pair(row.get("competition_id"), row)
        if not all(pair):
            continue
        groups[(row.get("competition_id"), canonical_day, pair)].append(row)

    merged = []
    touched = set()
    for (league, canonical_day, _pair), candidates in groups.items():
        candidates = sorted(candidates, key=lambda x: (shadow._epoch(x.get("scheduled_at")) or 0.0, x["canonical_event_id"]))
        clusters = []
        for row in candidates:
            ts = shadow._epoch(row.get("scheduled_at")) or 0.0
            if not clusters or abs(ts - (shadow._epoch(clusters[-1][-1].get("scheduled_at")) or 0.0)) > tolerance_seconds:
                clusters.append([row])
            else:
                clusters[-1].append(row)
        for cluster in clusters:
            if len(cluster) < 2:
                # Still normalize the active event's stored day if legacy ingestion
                # placed it on an adjacent UTC day.
                row = cluster[0]
                if _clean(row.get("slate_date")) != canonical_day:
                    with store._lock, closing(store._connect()) as conn:
                        conn.execute(
                            "UPDATE canonical_event SET slate_date=?,updated_at=? WHERE canonical_event_id=?",
                            (canonical_day, shadow._now(), row["canonical_event_id"]),
                        )
                        conn.commit()
                    touched.add((_clean(row.get("slate_date")), league))
                    touched.add((canonical_day, league))
                continue
            survivor = max(cluster, key=lambda x: _event_quality(store, x, canonical_day))
            for loser in cluster:
                if loser["canonical_event_id"] == survivor["canonical_event_id"]:
                    continue
                if _merge_event(store, survivor, loser, canonical_day):
                    merged.append({
                        "league": league,
                        "canonicalDate": canonical_day,
                        "survivor": survivor["canonical_event_id"],
                        "merged": loser["canonical_event_id"],
                        "away": survivor.get("away_name"),
                        "home": survivor.get("home_name"),
                    })
                    touched.add((_clean(loser.get("slate_date")), league))
                    touched.add((canonical_day, league))
            survivor = dict(survivor)
            survivor["slate_date"] = canonical_day

    for day, league in sorted(x for x in touched if x[0]):
        try:
            store.compile_slate(day, league, "IDENTITY_INGESTION_REPAIR", force_version=True)
        except Exception:
            pass
    return {"merged": len(merged), "pairs": merged, "touched": sorted([list(x) for x in touched if x[0]])}


def _install_policy_aware_validation():
    cls = v612.ValidationDiagnostics
    if getattr(cls, "__sbbV619PolicyAwareCounts", False):
        return
    original = cls._decision

    def decision(self, day, league, slate, comparison, cov_by_source, events, obs_by_event, event_by_id, adjacent_lookup):
        result = original(self, day, league, slate, comparison, cov_by_source, events, obs_by_event, event_by_id, adjacent_lookup)
        if league != "NCAAF" or not result.get("sourceCountConflict"):
            return result
        counts = result.get("sourceCounts") or {}
        if counts.get("authoritative") is None or counts.get("independent") is None:
            return result
        if result.get("evidenceGaps"):
            return result

        # NCAAF inclusion policy is Top-25 relevance, not raw NCAA universe parity.
        # If every INCLUDED event has both classes, a remaining raw-count delta is
        # outside the policy-relevant slate and remains visible as a warning only.
        result["sourceCountConflict"] = False
        result["sourceCountWarning"] = True
        result["sourceCountWarningReason"] = "NCAAF_EXCLUDED_UNIVERSE_VARIANCE"
        for step in result.get("decisionTrace") or []:
            if step.get("code") == "SOURCE_COUNT_AGREEMENT":
                step["status"] = "WARN"
                step["detail"] = (
                    f"authoritative={counts.get('authoritative')} independent={counts.get('independent')} "
                    "(excluded-universe variance; non-blocking)"
                )

        blockers = bool(
            result.get("productionOnly") or result.get("unresolved") or result.get("unknown")
            or result.get("evidenceGaps")
        )
        if not blockers:
            result["effectiveStatus"] = "CERTIFIED"
            result["cutoverReady"] = True
            result["effectiveReason"] = "CERTIFICATION_EVIDENCE_COMPLETE | NCAAF_EXCLUDED_UNIVERSE_VARIANCE"
            result["stateConsistencyViolation"] = _clean(result.get("persistedStatus")) != "CERTIFIED"
            for step in result.get("decisionTrace") or []:
                if step.get("code") == "EFFECTIVE_CERTIFICATION":
                    step.update({"status": "PASS", "detail": "CERTIFIED"})
                elif step.get("code") == "CUTOVER_READY":
                    step.update({"status": "PASS", "detail": "READY"})
        return result

    cls._decision = decision
    cls.__sbbV619PolicyAwareCounts = True


def _install_validation_worker_observability():
    cls = v612.ValidationDiagnostics
    if getattr(cls, "__sbbV619WorkerObservability", False):
        return
    original = cls.build_snapshot

    def build_snapshot(self):
        snapshot = original(self)
        try:
            health = self.engine.health() or {}
            worker = snapshot.setdefault("worker", {})
            worker.update({
                "certificationRunInProgress": bool(health.get("runInProgress")),
                "certificationCurrentRunStartedAt": health.get("currentRunStartedAt") or 0.0,
                "certificationCurrentRunAgeSeconds": health.get("currentRunAgeSeconds"),
            })
            snapshot.setdefault("diagnosticHooks", {})["workerRunObservability"] = True
            report = self._report(snapshot)
            with self.lock:
                self.cache["snapshot"] = snapshot
                self.cache["report"] = report
        except Exception:
            pass
        return snapshot

    cls.build_snapshot = build_snapshot
    cls.__sbbV619WorkerObservability = True


def _runtime_repair():
    while True:
        engine = v611.engine()
        server = sys.modules.get("__main__")
        if engine and server and hasattr(server, "Handler"):
            break
        time.sleep(0.25)
    repair = _repair_duplicate_identities(engine.store)
    try:
        server.SBB_BACKEND_WIRING.setdefault("canonicalSlate", {}).update({
            "identityIngestionRepairVersion": VERSION,
            "canonicalDateOwnershipAtIngestion": "EASTERN",
            "leagueAliasResolver": True,
            "ncaafExcludedUniverseVarianceBlocking": False,
            "identityRepair": repair,
            "productionAuthority": False,
        })
    except Exception:
        pass


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True
    _install_alias_resolver()
    _install_ingestion_date_ownership()
    _install_policy_aware_validation()
    _install_validation_worker_observability()
    threading.Thread(target=_runtime_repair, daemon=True, name="sbb-canonical-identity-ingestion-v619").start()

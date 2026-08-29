"""Sports Big Board v4.6.15 — persistence-aware special-event association.

v4.6.14 can deterministically prove media titles such as "Ohio vs Alabama |
Full Game Highlights" against rich special-event participant aliases. The normalized
catalog's legacy put_event_media() path then re-ran the older generic matcher against
canonical Little League club names and could quarantine that already-proven match as
TITLE_TEAM_PAIR_CONFLICT.

v4.6.15 adds a narrow, fail-closed pre-proven persistence contract:
- only internal SPECIAL_EVENT_TITLE_ALIAS_PAIR proofs are accepted;
- the proof must name the exact target league/event/canonical key;
- the proof must carry both title-side aliases and confidence >= 0.90;
- competing assigned canonical events are never silently overwritten;
- existing quarantined source assets are released only when the exact event proof
  is re-established;
- ordinary built-in and generic event-media writes still use the original matcher;
- later relationship-repair passes restore valid pre-proven links instead of
  permanently re-quarantining them.

No source media, schedule row, canonical event ID, or existing valid relationship
is deleted.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from contextlib import closing

from . import competition_builder as base
from . import competition_builder_v4613 as tournament
from .catalog_contract import (
    ASSIGNED,
    QUARANTINED,
    EVENT_MATCHER_VERSION,
    MEDIA_CLASSIFIER_VERSION,
)
from .event_matcher import team_name
from .history_repository import HistoryRepository

_INSTALLED = False
_INSTALL_LOCK = threading.Lock()

_ORIGINAL_PUT_EVENT_MEDIA = HistoryRepository.put_event_media
_ORIGINAL_REPAIR_EVENT_ASSOCIATIONS = HistoryRepository.repair_event_associations
_ORIGINAL_DECORATE_ASSIGNMENT = tournament._decorate_assignment

_PROOF_SCHEMA = 1
_PROOF_PRODUCER = "SBB_SPECIAL_EVENT_MATCHER"
_TRUSTED_METHOD_PREFIXES = (
    "SPECIAL_EVENT_TITLE_ALIAS_PAIR",
)


def _clean(value):
    return str(value or "").strip()


def _title_fingerprint(value):
    return hashlib.sha256(_clean(value).encode("utf-8")).hexdigest()[:24]


def _confidence_for_resolution(resolution):
    value = _clean(resolution).upper()
    if value == "PROVIDER_ID":
        return 1.0
    if value in {"UNIQUE_PAIR", "GAME_NUMBER", "EXPLICIT_TITLE_DATE"}:
        return 0.995
    if value == "PUBLICATION_PROXIMITY":
        return 0.985
    return 0.97


def _decorate_assignment_v4615(comp, playlist_row, item, record, evidence, resolution):
    """Attach a signed-by-contract internal proof to v4.6.14 alias-pair matches."""
    row = _ORIGINAL_DECORATE_ASSIGNMENT(
        comp, playlist_row, item, record, evidence, resolution
    )
    method = _clean((evidence or {}).get("associationMethod")).upper()
    if not any(method.startswith(prefix) for prefix in _TRUSTED_METHOD_PREFIXES):
        return row

    league = _clean((comp or {}).get("id")).upper()
    event = (record or {}).get("event") or {}
    event_id = _clean((record or {}).get("eventId") or event.get("eventId") or event.get("id"))
    canonical_key = _clean((record or {}).get("canonicalEventKey") or f"{league}:{event_id}")
    confidence = _confidence_for_resolution(resolution)

    proof = {
        "schema": _PROOF_SCHEMA,
        "producer": _PROOF_PRODUCER,
        "proofVersion": "4.6.15",
        "associationState": ASSIGNED,
        "associationMethod": method,
        "associationConfidence": confidence,
        "associationResolution": _clean(resolution).upper(),
        "league": league,
        "eventId": event_id,
        "canonicalEventKey": canonical_key,
        "titleAlias1": _clean((evidence or {}).get("titleAlias1")),
        "titleAlias1Source": _clean((evidence or {}).get("titleAlias1Source")),
        "titleAlias2": _clean((evidence or {}).get("titleAlias2")),
        "titleAlias2Source": _clean((evidence or {}).get("titleAlias2Source")),
        "titlePairOrder": _clean((evidence or {}).get("titlePairOrder")),
        "titlePairScore": int((evidence or {}).get("titlePairScore") or 0),
        "titleFingerprint": _title_fingerprint((item or {}).get("title")),
    }
    row["associationMethod"] = method
    row["associationConfidence"] = confidence
    row["associationEvidence"] = json.dumps(proof, ensure_ascii=False, separators=(",", ":"))
    row["sbbPreprovenAssociation"] = proof
    return row


def _trusted_proof(raw, *, league, event_id, canonical_key):
    """Return a verified internal proof or None.

    This intentionally rejects generic provider-supplied dictionaries that merely
    happen to contain association-like fields.
    """
    if not isinstance(raw, dict):
        return None
    proof = raw.get("sbbPreprovenAssociation")
    if not isinstance(proof, dict):
        return None
    if int(proof.get("schema") or 0) != _PROOF_SCHEMA:
        return None
    if _clean(proof.get("producer")) != _PROOF_PRODUCER:
        return None
    if _clean(proof.get("associationState")).upper() != ASSIGNED:
        return None

    method = _clean(proof.get("associationMethod")).upper()
    if not any(method.startswith(prefix) for prefix in _TRUSTED_METHOD_PREFIXES):
        return None

    try:
        confidence = float(proof.get("associationConfidence") or 0)
    except Exception:
        return None
    if confidence < 0.90:
        return None

    if _clean(proof.get("league")).upper() != _clean(league).upper():
        return None
    if _clean(proof.get("eventId")) != _clean(event_id):
        return None
    if _clean(proof.get("canonicalEventKey")) != _clean(canonical_key):
        return None

    # A two-sided alias proof must actually preserve both title-side identities.
    if not _clean(proof.get("titleAlias1")) or not _clean(proof.get("titleAlias2")):
        return None

    # The asset being written must agree with the target identity as well.
    raw_key = _clean(raw.get("canonicalEventKey"))
    if raw_key and raw_key != _clean(canonical_key):
        return None
    raw_league = _clean(raw.get("competitionId") or raw.get("league")).upper()
    if raw_league and raw_league != _clean(league).upper():
        return None

    expected_fingerprint = _clean(proof.get("titleFingerprint"))
    if expected_fingerprint and expected_fingerprint != _title_fingerprint(raw.get("title")):
        return None

    return dict(proof)


def _evidence_text(proof):
    return json.dumps(
        {
            "producer": proof.get("producer"),
            "proofVersion": proof.get("proofVersion"),
            "canonicalEventKey": proof.get("canonicalEventKey"),
            "resolution": proof.get("associationResolution"),
            "titleAlias1": proof.get("titleAlias1"),
            "titleAlias1Source": proof.get("titleAlias1Source"),
            "titleAlias2": proof.get("titleAlias2"),
            "titleAlias2Source": proof.get("titleAlias2Source"),
            "titlePairOrder": proof.get("titlePairOrder"),
            "titlePairScore": proof.get("titlePairScore"),
            "titleFingerprint": proof.get("titleFingerprint"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )[:2000]


def _persist_one_preproven(repo, conn, *, raw, proof, league, event_id, key, event, event_date, now):
    away, home = team_name(event, "away"), team_name(event, "home")

    # Keep normal media classification/verification ingestion. Only association
    # proof is supplied externally to the legacy matcher.
    item = dict(raw)
    item["associationMethod"] = proof["associationMethod"]
    item["associationConfidence"] = float(proof["associationConfidence"])
    item["associationEvidence"] = _evidence_text(proof)
    item["canonicalEventKey"] = key

    asset_key = repo._upsert_source_media_conn(
        conn,
        item,
        league=league,
        date=event_date,
        away=away,
        home=home,
        catalog_state=ASSIGNED,
        quarantine_reason="",
    )
    if not asset_key:
        return 0

    # Foreign-key hardening: both parent rows must be visible on this exact
    # connection before history_event_media is written. If either invariant is
    # violated, fail closed instead of allowing sqlite3.IntegrityError to abort
    # verification/deployment.
    event_parent = conn.execute(
        "SELECT 1 FROM history_catalog_event WHERE canonical_event_key=?",
        (key,),
    ).fetchone()
    asset_parent = conn.execute(
        "SELECT scope,asset_json FROM history_source_media WHERE asset_key=?",
        (asset_key,),
    ).fetchone()
    if not event_parent or not asset_parent:
        return 0

    # Normalized source scope is authoritative over an older special-event proof.
    # A title-pair proof establishes WHICH game an asset belongs to only while the
    # classifier still says the asset itself is GAME-scoped.  If a later classifier
    # version determines that it is DAY/WEEK/ROUND/Silver material, fail closed and
    # never recreate an event link that relationship repair just quarantined.
    normalized_scope = _clean(asset_parent["scope"]).upper()
    if normalized_scope != "GAME":
        conn.execute(
            """UPDATE history_event_media
               SET association_state='QUARANTINED',
                   association_confidence=0,
                   association_method='NON_GAME_SCOPE_PREPROVEN_REJECTED',
                   association_evidence=?,
                   matcher_version=?,
                   updated_at=?
               WHERE canonical_event_key=? AND asset_key=?""",
            (
                f"pre-proven association rejected because normalized source scope is {normalized_scope or 'UNKNOWN'}",
                EVENT_MATCHER_VERSION,
                now,
                key,
                asset_key,
            ),
        )
        return 0

    competing = conn.execute(
        """SELECT canonical_event_key,association_confidence,association_method
           FROM history_event_media
           WHERE asset_key=? AND association_state='ASSIGNED' AND canonical_event_key<>?""",
        (asset_key, key),
    ).fetchall()

    state = ASSIGNED
    reason = ""
    evidence = _evidence_text(proof)
    confidence = float(proof["associationConfidence"])
    method = _clean(proof["associationMethod"])

    if competing:
        # Fail closed. A deterministic proof cannot silently steal a source asset
        # from another already-assigned canonical event.
        state = QUARANTINED
        reason = "MULTI_EVENT_CANDIDATE_ENCOUNTER"
        confidence = 0.0
        method = reason
        evidence = (
            "pre-proven special-event candidate encountered an asset already assigned "
            f"to {[str(r['canonical_event_key']) for r in competing]}"
        )[:2000]
    else:
        stored_row = conn.execute(
            "SELECT asset_json FROM history_source_media WHERE asset_key=?",
            (asset_key,),
        ).fetchone()
        stored = repo._load_obj(stored_row["asset_json"]) if stored_row else {}
        stored["canonicalEventKey"] = key
        stored["associationMethod"] = proof["associationMethod"]
        stored["associationConfidence"] = float(proof["associationConfidence"])
        stored["associationEvidence"] = _evidence_text(proof)
        stored["sbbPreprovenAssociation"] = dict(proof)
        conn.execute(
            """UPDATE history_source_media
               SET catalog_state='ASSIGNED',quarantine_reason='',asset_json=?,updated_at=?
               WHERE asset_key=?""",
            (repo._dump_obj(stored), now, asset_key),
        )
        # Keep historical review rows as evidence, but mark target-event quarantine
        # findings resolved so they no longer describe the current link state.
        conn.execute(
            """UPDATE history_assignment_review
               SET state='RESOLVED',updated_at=?
               WHERE asset_key=? AND proposed_event_key=? AND state='QUARANTINED'""",
            (now, asset_key, key),
        )

    if state != ASSIGNED:
        conn.execute(
            """INSERT INTO history_assignment_review(
                 asset_key,league,event_date,proposed_event_key,state,reason,evidence_json,
                 classifier_version,matcher_version,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(asset_key,proposed_event_key,reason)
               DO UPDATE SET state=excluded.state,evidence_json=excluded.evidence_json,
                 matcher_version=excluded.matcher_version,updated_at=excluded.updated_at""",
            (
                asset_key, league, event_date, key, state, reason,
                repo._dump_obj({"preproven": proof, "reason": evidence}),
                MEDIA_CLASSIFIER_VERSION, EVENT_MATCHER_VERSION, now, now,
            ),
        )

    conn.execute(
        """INSERT INTO history_event_media(
             canonical_event_key,asset_key,association_state,association_confidence,
             association_method,association_evidence,matcher_version,
             first_associated_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(canonical_event_key,asset_key)
           DO UPDATE SET
             association_state=excluded.association_state,
             association_confidence=excluded.association_confidence,
             association_method=excluded.association_method,
             association_evidence=excluded.association_evidence,
             matcher_version=excluded.matcher_version,
             updated_at=excluded.updated_at""",
        (
            key, asset_key, state, confidence, method, evidence,
            EVENT_MATCHER_VERSION, now, now,
        ),
    )
    return 1 if state == ASSIGNED else 0


def _put_event_media_v4615(repo, date, league, event_id, rows):
    """Persist trusted special-event proofs; delegate every ordinary row unchanged."""
    date = _clean(date)[:10]
    league = _clean(league).upper()
    event_id = _clean(event_id)
    if not event_id:
        return 0

    rows = [dict(x) for x in (rows or []) if isinstance(x, dict)]
    if not rows:
        return 0

    key = repo.canonical_event_key(league, event_id)
    proven = []
    ordinary = []
    for raw in rows:
        proof = _trusted_proof(
            raw,
            league=league,
            event_id=event_id,
            canonical_key=key,
        )
        if proof:
            proven.append((raw, proof))
        else:
            ordinary.append(raw)

    count = 0
    if proven:
        now = time.time()
        with repo._lock, closing(repo._connect()) as conn:
            # v4.6.15 CI hardening: create/refresh the canonical-event parent on
            # the SAME SQLite connection/transaction that will receive the
            # history_event_media child row. This removes any cross-connection
            # visibility/race assumption from the trusted persistence path.
            conn.execute(
                """INSERT INTO history_catalog_event(
                     canonical_event_key,league,event_id,event_date,event_json,final_at,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(canonical_event_key) DO UPDATE SET
                     event_date=excluded.event_date,
                     updated_at=excluded.updated_at""",
                (key, league, event_id, date, repo._dump_obj({}), 0.0, now, now),
            )
            erow = conn.execute(
                "SELECT event_json,event_date FROM history_catalog_event WHERE canonical_event_key=?",
                (key,),
            ).fetchone()
            if not erow:
                conn.rollback()
                return 0
            event = repo._load_obj(erow["event_json"]) if erow else {}
            event_date = _clean(erow["event_date"] if erow else date)[:10]
            for raw, proof in proven:
                count += _persist_one_preproven(
                    repo,
                    conn,
                    raw=raw,
                    proof=proof,
                    league=league,
                    event_id=event_id,
                    key=key,
                    event=event,
                    event_date=event_date,
                    now=now,
                )
            conn.commit()

    if ordinary:
        count += int(
            _ORIGINAL_PUT_EVENT_MEDIA(repo, date, league, event_id, ordinary) or 0
        )
    return count


def _preproven_source_rows(repo):
    """Read proof-bearing assets together with their CURRENT normalized scope."""
    with closing(repo._read_connect()) as conn:
        rows = conn.execute(
            """SELECT asset_key,scope,asset_json
               FROM history_source_media
               WHERE asset_json LIKE '%"sbbPreprovenAssociation"%'"""
        ).fetchall()
    out = []
    for row in rows:
        item = repo._load_obj(row["asset_json"])
        if isinstance(item, dict):
            item["assetKey"] = _clean(row["asset_key"])
            item["mediaScope"] = _clean(row["scope"]).upper()
            item["normalizedMediaScope"] = _clean(row["scope"]).upper()
            out.append(item)
    return out


def _restore_preproven_links(repo):
    """Restore only proof-bearing assets that remain normalized GAME media."""
    restored = 0
    checked = 0
    scope_rejected = 0
    for item in _preproven_source_rows(repo):
        proof = item.get("sbbPreprovenAssociation")
        if not isinstance(proof, dict):
            continue
        # This is the critical v4.7.0 repair invariant.  Event relationship repair
        # may quarantine a formerly-proven asset because a newer classifier now
        # identifies it as collection/Silver material.  Do not resurrect that link.
        if _clean(item.get("normalizedMediaScope") or item.get("mediaScope")).upper() != "GAME":
            scope_rejected += 1
            continue
        league = _clean(proof.get("league")).upper()
        event_id = _clean(proof.get("eventId"))
        key = _clean(proof.get("canonicalEventKey"))
        if not league or not event_id or key != repo.canonical_event_key(league, event_id):
            continue
        event_row = repo.get_event("", league, event_id)
        if not event_row:
            continue
        checked += 1
        status = repo.event_media_link_status(league, event_id, repo.asset_key_for(item))
        if status and _clean(status.get("associationState")).upper() == ASSIGNED:
            continue
        restored += int(
            _put_event_media_v4615(
                repo,
                event_row.get("date"),
                league,
                event_id,
                [item],
            )
            or 0
        )
    return {"checked": checked, "restored": restored, "scopeRejected": scope_rejected}


def _repair_event_associations_v4615(repo, matcher_version=EVENT_MATCHER_VERSION, force=False):
    """Run the normal fail-closed repair, then restore still-valid internal proofs."""
    result = _ORIGINAL_REPAIR_EVENT_ASSOCIATIONS(
        repo, matcher_version=matcher_version, force=force
    )
    recovery = _restore_preproven_links(repo)
    result = dict(result or {})
    result["preprovenChecked"] = recovery["checked"]
    result["preprovenRestored"] = recovery["restored"]
    result["preprovenScopeRejected"] = recovery.get("scopeRejected", 0)
    return result


def _startup_reassociate():
    """Re-prove existing v4.6.14 quarantines using the new persistence contract."""
    server = None
    for _ in range(600):
        server = getattr(base, "_SERVER", None)
        if server is not None and hasattr(server, "HISTORY_REPOSITORY"):
            break
        time.sleep(0.2)
    else:
        return

    # Let schedule/media registration settle, then replay existing SOURCE_MEDIA.
    time.sleep(3)
    for comp in base._load():
        if (
            _clean(comp.get("type")).upper() != "SPECIAL_EVENT"
            or not comp.get("enabled", True)
        ):
            continue
        try:
            tournament._reassociate_existing_competition(server, comp)
        except Exception:
            pass


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _INSTALLED = True

    # Install synchronously at class/function level so both v4.6.14's own startup
    # reassociation thread and all future reprocesses use the corrected persistence.
    tournament._decorate_assignment = _decorate_assignment_v4615
    HistoryRepository.put_event_media = _put_event_media_v4615
    HistoryRepository.repair_event_associations = _repair_event_associations_v4615

    threading.Thread(
        target=_startup_reassociate,
        daemon=True,
        name="sbb-v4615-preproven-quarantine-release",
    ).start()

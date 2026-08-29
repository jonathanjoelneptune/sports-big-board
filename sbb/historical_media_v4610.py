"""Sports Big Board v4.6.10 historical media association hardening.

Keeps the normalized catalog authoritative on old dates without rebuilding it.
Schedule/provider IDs can become aliases of an existing canonical event, historical
ribbon reads re-prove already-downloaded GAME assets, and alias keys are exposed to
the ribbon while each source-media relationship remains singular.
"""
from __future__ import annotations

import re
import threading
import time
from contextlib import closing

from .catalog_contract import ASSIGNED, EVENT_MATCHER_VERSION
from .event_matcher import match_event, team_name
from .history_repository import HistoryRepository
from .media_classifier import annotate as annotate_recap_tier
from .media_scope import annotate as annotate_media_scope, strip_classifier_fields, GAME

_INSTALLED = False
_INSTALL_LOCK = threading.RLock()

_ORIGINAL_INIT = HistoryRepository.__init__
_ORIGINAL_GET_EVENT = HistoryRepository.get_event
_ORIGINAL_EVENT_MEDIA = HistoryRepository.event_media
_ORIGINAL_RIBBON_MEDIA = HistoryRepository.ribbon_media_for_date
_ORIGINAL_PUT_EVENT_MEDIA = HistoryRepository.put_event_media
_ORIGINAL_SET_EVENT_DISCOVERY = HistoryRepository.set_event_discovery
_ORIGINAL_RESET_EVENT_REINDEX = HistoryRepository.reset_event_for_reindex


def _clean(value):
    return str(value or "").strip()


def _team_key(event, side):
    value = _clean(team_name(event or {}, side)).lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _provider_ids(event):
    event = event if isinstance(event, dict) else {}
    out = []
    for key in (
        "scoreEventId", "matchId", "espnEventId", "providerEventId", "providerGameId",
        "gamePk", "canonicalEventId", "eventId", "id",
    ):
        value = event.get(key)
        if value not in (None, ""):
            token = _clean(value)
            if token and token not in out:
                out.append(token)
    return out


def _clock_minutes(event):
    event = event if isinstance(event, dict) else {}
    for key in ("scheduledAt", "date", "startTime", "startAt", "gameDate", "datetime"):
        text = _clean(event.get(key))
        if not text:
            continue
        match = re.search(r"T(\d{2}):(\d{2})", text)
        if match:
            return int(match.group(1)) * 60 + int(match.group(2))
        match = re.search(r"\b(\d{1,2}):(\d{2})\s*(AM|PM)?\b", text, re.I)
        if match:
            hour = int(match.group(1)); minute = int(match.group(2))
            meridiem = _clean(match.group(3)).upper()
            if meridiem == "PM" and hour < 12: hour += 12
            elif meridiem == "AM" and hour == 12: hour = 0
            return hour * 60 + minute
    return None


def _ensure_alias_table(repo):
    if getattr(repo, "_v4610_alias_table_ready", False):
        return
    with repo._lock, closing(repo._connect()) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS history_event_alias (
            league TEXT NOT NULL,
            alias_event_id TEXT NOT NULL,
            canonical_event_key TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL DEFAULT 0,
            PRIMARY KEY(league,alias_event_id),
            FOREIGN KEY(canonical_event_key) REFERENCES history_catalog_event(canonical_event_key) ON DELETE CASCADE
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_event_alias_key ON history_event_alias(canonical_event_key)")
        conn.execute("""INSERT OR IGNORE INTO history_event_alias(league,alias_event_id,canonical_event_key,evidence,updated_at)
            SELECT league,event_id,canonical_event_key,'CANONICAL_EVENT_ID',? FROM history_catalog_event
            WHERE COALESCE(event_id,'')<>''""", (time.time(),))
        conn.commit()
    repo._v4610_alias_table_ready = True
    repo._v4610_date_repair_at = getattr(repo, "_v4610_date_repair_at", {})
    repo._v4610_date_repair_report = getattr(repo, "_v4610_date_repair_report", {})


def _alias_key_conn(conn, league, event_id):
    row = conn.execute(
        "SELECT canonical_event_key FROM history_event_alias WHERE league=? AND alias_event_id=?",
        (_clean(league).upper(), _clean(event_id)),
    ).fetchone()
    return _clean(row["canonical_event_key"]) if row else ""


def _canonical_id_conn(conn, canonical_key):
    row = conn.execute("SELECT event_id FROM history_catalog_event WHERE canonical_event_key=?", (canonical_key,)).fetchone()
    return _clean(row["event_id"]) if row else ""


def _store_alias_conn(conn, league, alias_event_id, canonical_key, evidence="SCHEDULE_IDENTITY"):
    alias_event_id = _clean(alias_event_id)
    if not alias_event_id or not canonical_key:
        return
    conn.execute("""INSERT INTO history_event_alias(league,alias_event_id,canonical_event_key,evidence,updated_at)
        VALUES(?,?,?,?,?) ON CONFLICT(league,alias_event_id) DO UPDATE SET
        canonical_event_key=excluded.canonical_event_key,evidence=excluded.evidence,updated_at=excluded.updated_at""",
        (_clean(league).upper(), alias_event_id, canonical_key, _clean(evidence)[:200], time.time()))


def _candidate_score(event, candidate_event, candidate_event_id):
    ids = set(_provider_ids(event)); candidate_ids = set(_provider_ids(candidate_event)) | {_clean(candidate_event_id)}
    if ids and candidate_ids and ids.intersection(candidate_ids):
        return 1000
    away, home = _team_key(event, "away"), _team_key(event, "home")
    caway, chome = _team_key(candidate_event, "away"), _team_key(candidate_event, "home")
    if not away or not home or not caway or not chome:
        return -1
    if away == caway and home == chome: score = 200
    elif {away, home} == {caway, chome}: score = 150
    else: return -1
    left, right = _clock_minutes(event), _clock_minutes(candidate_event)
    if left is not None and right is not None:
        diff = min(abs(left-right), 1440-abs(left-right))
        if diff <= 10: score += 80
        elif diff <= 90: score += 50
        elif diff <= 180: score += 15
        else: score -= 140
    return score


def _identity_target_conn(repo, conn, date, league, event_id, event):
    league = _clean(league).upper(); event_id = _clean(event_id)
    direct = repo.canonical_event_key(league, event_id)
    if conn.execute("SELECT 1 FROM history_catalog_event WHERE canonical_event_key=?", (direct,)).fetchone():
        return direct, "DIRECT_EVENT_ID"
    alias = _alias_key_conn(conn, league, event_id)
    if alias and conn.execute("SELECT 1 FROM history_catalog_event WHERE canonical_event_key=?", (alias,)).fetchone():
        return alias, "KNOWN_EVENT_ALIAS"
    if not isinstance(event, dict) or not event:
        return direct, "NEW_EVENT_ID"
    ranked = []
    rows = conn.execute(
        "SELECT canonical_event_key,event_id,event_json FROM history_catalog_event WHERE league=? AND event_date=?",
        (league, _clean(date)[:10]),
    ).fetchall()
    for row in rows:
        score = _candidate_score(event, repo._load_obj(row["event_json"]), row["event_id"])
        if score >= 0:
            ranked.append((score, _clean(row["canonical_event_key"])))
    ranked.sort(reverse=True)
    if not ranked:
        return direct, "NEW_EVENT_ID"
    best_score, best_key = ranked[0]; second_score = ranked[1][0] if len(ranked) > 1 else -999
    if best_score >= 1000 or (best_score >= 200 and best_score-second_score >= 35):
        return best_key, "PROVIDER_ALIAS" if best_score >= 1000 else "DATE_TEAMS_TIME"
    return direct, "AMBIGUOUS_NEW_EVENT"


def _merge_event_conn(repo, conn, canonical_key, date, league, incoming_event_id, event, evidence):
    row = conn.execute(
        "SELECT event_id,event_json,final_at FROM history_catalog_event WHERE canonical_event_key=?", (canonical_key,)
    ).fetchone()
    now = time.time()
    if row:
        previous = repo._load_obj(row["event_json"]); merged = dict(previous); merged.update(event or {})
        aliases = set(_provider_ids(previous)) | set(_provider_ids(event or {})) | {_clean(row["event_id"]), _clean(incoming_event_id)}
        aliases.discard("")
        merged["providerEventAliases"] = sorted(aliases)
        merged["__sbbCanonicalEventId"] = _clean(row["event_id"])
        final_at = max(float(row["final_at"] or 0), float(repo._event_final_at(event) or 0))
        conn.execute(
            "UPDATE history_catalog_event SET event_date=?,event_json=?,final_at=?,updated_at=? WHERE canonical_event_key=?",
            (_clean(date)[:10], repo._dump_obj(merged), final_at, now, canonical_key),
        )
        canonical_id = _clean(row["event_id"])
    else:
        canonical_id = _clean(incoming_event_id); merged = dict(event or {})
        aliases = set(_provider_ids(merged)); aliases.add(canonical_id); aliases.discard("")
        merged["providerEventAliases"] = sorted(aliases); merged["__sbbCanonicalEventId"] = canonical_id
        conn.execute("""INSERT INTO history_catalog_event(canonical_event_key,league,event_id,event_date,event_json,final_at,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)""", (canonical_key, _clean(league).upper(), canonical_id, _clean(date)[:10], repo._dump_obj(merged), repo._event_final_at(event), now, now))
    _store_alias_conn(conn, league, canonical_id, canonical_key, "CANONICAL_EVENT_ID")
    _store_alias_conn(conn, league, incoming_event_id, canonical_key, evidence)
    for alias in _provider_ids(event or {}): _store_alias_conn(conn, league, alias, canonical_key, evidence)
    return canonical_id


def _resolved_event_id(repo, league, event_id):
    _ensure_alias_table(repo)
    league = _clean(league).upper(); event_id = _clean(event_id); direct = repo.canonical_event_key(league, event_id)
    with closing(repo._read_connect()) as conn:
        row = conn.execute("SELECT event_id FROM history_catalog_event WHERE canonical_event_key=?", (direct,)).fetchone()
        if row: return _clean(row["event_id"])
        key = _alias_key_conn(conn, league, event_id)
        return _canonical_id_conn(conn, key) if key else event_id


def _init_v4610(self, *args, **kwargs):
    result = _ORIGINAL_INIT(self, *args, **kwargs); _ensure_alias_table(self); return result


def _put_scores_v4610(self, date, league, rows):
    _ensure_alias_table(self)
    now = time.time(); date = _clean(date)[:10]; league = _clean(league).upper(); rows = list(rows or [])
    with self._lock, closing(self._connect()) as conn:
        conn.execute("""INSERT INTO history_day(date,league,scores_json,scores_saved_at) VALUES(?,?,?,?)
            ON CONFLICT(date,league) DO UPDATE SET scores_json=excluded.scores_json,scores_saved_at=excluded.scores_saved_at""",
            (date, league, self._dump(rows), now))
        for event in rows:
            event_id = self.event_id_for(event)
            if not event_id: continue
            target_key, evidence = _identity_target_conn(self, conn, date, league, event_id, event)
            _merge_event_conn(self, conn, target_key, date, league, event_id, event, evidence)
        conn.commit()
    return now


def _upsert_event_v4610(self, date, league, event_id, event=None):
    _ensure_alias_table(self)
    date = _clean(date)[:10]; league = _clean(league).upper(); event_id = _clean(event_id)
    if not event_id: return 0
    with self._lock, closing(self._connect()) as conn:
        target_key, evidence = _identity_target_conn(self, conn, date, league, event_id, event or {})
        _merge_event_conn(self, conn, target_key, date, league, event_id, event or {}, evidence); conn.commit()
    return time.time()


def _get_event_v4610(self, date, league, event_id):
    return _ORIGINAL_GET_EVENT(self, date, league, _resolved_event_id(self, league, event_id))


def _event_media_v4610(self, date, league, event_id, include_failed=True):
    return _ORIGINAL_EVENT_MEDIA(self, date, league, _resolved_event_id(self, league, event_id), include_failed=include_failed)


def _put_event_media_v4610(self, date, league, event_id, rows):
    self.upsert_event(date, league, event_id)
    return _ORIGINAL_PUT_EVENT_MEDIA(self, date, league, _resolved_event_id(self, league, event_id), rows)


def _set_event_discovery_v4610(self, date, league, event_id, state, details=None, *, error="", retry_at=0, success=False):
    self.upsert_event(date, league, event_id)
    return _ORIGINAL_SET_EVENT_DISCOVERY(self, date, league, _resolved_event_id(self, league, event_id), state, details, error=error, retry_at=retry_at, success=success)


def _reset_event_reindex_v4610(self, date, league, event_id, details=None, *, state="UNKNOWN"):
    self.upsert_event(date, league, event_id)
    return _ORIGINAL_RESET_EVENT_REINDEX(self, date, league, _resolved_event_id(self, league, event_id), details, state=state)


def _date_repair_candidates_conn(repo, conn, target, selected_leagues):
    params = [target, target, target, target, target, target]; league_sql = ""
    if selected_leagues:
        marks = ",".join("?" for _ in selected_leagues)
        league_sql = f""" AND (
            UPPER(COALESCE(json_extract(s.asset_json,'$.__sbbLeague'),json_extract(s.asset_json,'$.competitionId'),json_extract(s.asset_json,'$.league'),'')) IN ({marks})
            OR EXISTS(SELECT 1 FROM history_event_media lx JOIN history_catalog_event le ON le.canonical_event_key=lx.canonical_event_key WHERE lx.asset_key=s.asset_key AND le.event_date=? AND le.league IN ({marks}))
        )"""
        params.extend(selected_leagues); params.append(target); params.extend(selected_leagues)
    sql = f"""SELECT DISTINCT s.* FROM history_source_media s
        WHERE s.scope='GAME' AND COALESCE(s.runtime_state,'UNKNOWN')<>'FAILED'
          AND (
            substr(COALESCE(s.published_at,''),1,10)=?
            OR substr(COALESCE(json_extract(s.asset_json,'$.__sbbDate'),''),1,10)=?
            OR substr(COALESCE(json_extract(s.asset_json,'$.eventDate'),''),1,10)=?
            OR substr(COALESCE(json_extract(s.asset_json,'$.gameDate'),''),1,10)=?
            OR substr(COALESCE(json_extract(s.asset_json,'$.scheduledAt'),''),1,10)=?
            OR EXISTS(SELECT 1 FROM history_event_media ex JOIN history_catalog_event ee ON ee.canonical_event_key=ex.canonical_event_key WHERE ex.asset_key=s.asset_key AND ee.event_date=?)
          ) {league_sql}
        ORDER BY s.updated_at DESC LIMIT 2500"""
    return conn.execute(sql, params).fetchall()


def repair_date_associations(self, date, leagues=None, force=False):
    """Database-only re-association for one historical date; no provider search."""
    _ensure_alias_table(self)
    target = _clean(date)[:10]; selected = sorted({_clean(x).upper() for x in (leagues or []) if _clean(x)})
    cache_key = target + "|" + ",".join(selected or ["ALL"]); now = time.time()
    last = float(self._v4610_date_repair_at.get(cache_key) or 0)
    if not force and now-last < 15:
        cached = dict(self._v4610_date_repair_report.get(cache_key) or {}); cached["cached"] = True; return cached
    report = {"date": target, "leagues": selected or ["ALL"], "checkedAssets": 0, "alreadyAssigned": 0,
              "repaired": 0, "ambiguous": 0, "unmatched": 0, "candidateAssets": 0, "cached": False}
    with self._lock, closing(self._connect()) as conn:
        event_sql = "SELECT canonical_event_key,league,event_id,event_json FROM history_catalog_event WHERE event_date=?"; params = [target]
        if selected:
            event_sql += " AND league IN (" + ",".join("?" for _ in selected) + ")"; params.extend(selected)
        events = conn.execute(event_sql, params).fetchall(); by_league = {}; target_keys = set()
        for row in events:
            payload = {"key": _clean(row["canonical_event_key"]), "league": _clean(row["league"]).upper(), "eventId": _clean(row["event_id"]), "event": self._load_obj(row["event_json"])}
            by_league.setdefault(payload["league"], []).append(payload); target_keys.add(payload["key"])
        if not target_keys:
            self._v4610_date_repair_at[cache_key] = now; self._v4610_date_repair_report[cache_key] = report; return report
        candidates = _date_repair_candidates_conn(self, conn, target, selected); report["candidateAssets"] = len(candidates)
        for row in candidates:
            asset_key = _clean(row["asset_key"])
            if not asset_key: continue
            report["checkedAssets"] += 1
            assigned = conn.execute("""SELECT em.canonical_event_key,e.event_date FROM history_event_media em
                JOIN history_catalog_event e ON e.canonical_event_key=em.canonical_event_key
                WHERE em.asset_key=? AND em.association_state='ASSIGNED'""", (asset_key,)).fetchall()
            if assigned:
                if any(_clean(x["canonical_event_key"]) in target_keys for x in assigned): report["alreadyAssigned"] += 1
                continue
            item = self._load_obj(row["asset_json"])
            league_hint = _clean(item.get("__sbbLeague") or item.get("competitionId") or item.get("league")).upper()
            league_groups = [league_hint] if league_hint in by_league else list(by_league); matches = []
            for league in league_groups:
                for candidate in by_league.get(league, []):
                    event = candidate["event"]; away = team_name(event, "away"); home = team_name(event, "home")
                    working = annotate_media_scope(strip_classifier_fields(dict(item)), league=league, date=target, away=away, home=home)
                    if _clean(working.get("mediaScope")).upper() != GAME: continue
                    if not working.get("recapTier"): working = annotate_recap_tier(working)
                    evidence = match_event(working, event, league=league, date=target)
                    if _clean(evidence.get("associationState")).upper() == ASSIGNED:
                        matches.append((float(evidence.get("associationConfidence") or 0), candidate, working, evidence))
            matches.sort(key=lambda x: x[0], reverse=True)
            if not matches: report["unmatched"] += 1; continue
            if len(matches)>1 and matches[0][0]-matches[1][0] < 0.08 and matches[0][1]["key"] != matches[1][1]["key"]:
                report["ambiguous"] += 1; continue
            confidence, candidate, working, evidence = matches[0]; key = candidate["key"]
            working["canonicalEventKey"] = key; working["__sbbDate"] = target; working["__sbbLeague"] = candidate["league"]
            conn.execute("""INSERT INTO history_event_media(canonical_event_key,asset_key,association_state,association_confidence,association_method,association_evidence,matcher_version,first_associated_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(canonical_event_key,asset_key) DO UPDATE SET association_state=excluded.association_state,
                association_confidence=excluded.association_confidence,association_method=excluded.association_method,
                association_evidence=excluded.association_evidence,matcher_version=excluded.matcher_version,updated_at=excluded.updated_at""",
                (key, asset_key, ASSIGNED, confidence, _clean(evidence.get("associationMethod")), _clean(evidence.get("associationEvidence"))[:2000], int(evidence.get("matcherVersion") or EVENT_MATCHER_VERSION), now, now))
            conn.execute("UPDATE history_source_media SET catalog_state='ASSIGNED',quarantine_reason='',asset_json=?,updated_at=? WHERE asset_key=?",
                         (self._dump_obj(working), now, asset_key)); report["repaired"] += 1
        conn.commit()
    self._v4610_date_repair_at[cache_key] = now; self._v4610_date_repair_report[cache_key] = dict(report); return report


def _ribbon_media_v4610(self, date, leagues=None, include_failed=False):
    try: repair_date_associations(self, date, leagues=leagues, force=False)
    except Exception: pass
    result = _ORIGINAL_RIBBON_MEDIA(self, date, leagues=leagues, include_failed=include_failed)
    try:
        _ensure_alias_table(self)
        with closing(self._read_connect()) as conn:
            aliases = conn.execute("""SELECT league,alias_event_id,canonical_event_key FROM history_event_alias
                WHERE canonical_event_key IN (SELECT canonical_event_key FROM history_catalog_event WHERE event_date=?)""", (_clean(date)[:10],)).fetchall()
        for row in aliases:
            canonical_key = _clean(row["canonical_event_key"]); alias_key = f"{_clean(row['league']).upper()}:{_clean(row['alias_event_id'])}"
            if canonical_key in result and alias_key not in result: result[alias_key] = result[canonical_key]
    except Exception: pass
    return result


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED: return
        _INSTALLED = True
        HistoryRepository.__init__ = _init_v4610
        HistoryRepository.put_scores = _put_scores_v4610
        HistoryRepository.upsert_event = _upsert_event_v4610
        HistoryRepository.get_event = _get_event_v4610
        HistoryRepository.event_media = _event_media_v4610
        HistoryRepository.put_event_media = _put_event_media_v4610
        HistoryRepository.set_event_discovery = _set_event_discovery_v4610
        HistoryRepository.reset_event_for_reindex = _reset_event_reindex_v4610
        HistoryRepository.repair_date_associations = repair_date_associations
        HistoryRepository.ribbon_media_for_date = _ribbon_media_v4610

#!/usr/bin/env python3
"""Sports Big Board A4.15 resilient editorial fallback overlay on A4.14.

A4.14 remains the preferred Sports Ticker path. A4.15 only intervenes when the
OpenAI editorial request is unavailable because of quota/rate-limit exhaustion
after source collection has already produced a healthy model-candidate packet.
In that narrow case it deterministically selects grounded source candidates and
writes a schema-compatible ticker payload, so an external editor outage does not
turn the automatic ribbon refresh action red or freeze the ribbon indefinitely.

Real source failures, malformed candidate packets, authentication failures, and
other unexpected pipeline errors still fail closed with A4.14's original exit
code. When the editor becomes available again, A4.14 succeeds normally and this
fallback is bypassed automatically.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.15-resilient-editor-fallback"
BASE_LEAGUES = ("MLB", "NFL", "NBA", "NHL", "EPL", "MLS", "NCAAF")
MAX_GLOBAL_ITEMS = 35
MAX_PER_LEAGUE = 6
BASE_PER_LEAGUE = 4

LOW_VALUE_PATTERNS = (
    "betting", "odds", "best bet", "prop bet", "uniform", "preview",
    "transfer rumors", "transfer talk", "play the ", "meet to determine",
    "series tied", "look to sweep", "matchup with",
)
RAW_FEED_PATTERNS = (
    r"\bPENALTY\b", r"\bNO PLAY\b", r"\bclock \d{1,2}:\d{2}\b",
    r"#\d+\s+[A-Z]\.", r"\bfield goal attempt\b", r"\byards? from\b",
    r"\|\s*(?:Touchdown|Field Goal|Kickoff|Missed FG)\b",
)


def _load_a414():
    path = Path(__file__).with_name("refresh_sports_ticker_a414.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a414", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.14 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _parse_utc(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _data_dir_from_argv(argv: list[str]) -> Path:
    for index, arg in enumerate(argv):
        if arg == "--data-dir" and index + 1 < len(argv):
            return Path(argv[index + 1])
        if arg.startswith("--data-dir="):
            return Path(arg.split("=", 1)[1])
    return Path("data")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _editor_outage_reason(run_log: dict[str, Any]) -> str | None:
    haystack = json.dumps(run_log, ensure_ascii=False).lower()
    if "credit_balance_exhausted" in haystack:
        return "openai_credit_balance_exhausted"
    if "insufficient_quota" in haystack:
        return "openai_insufficient_quota"
    if "rate_limit_exceeded" in haystack:
        return "openai_rate_limit_exceeded"
    if "openai" in haystack and ("http 429" in haystack or "status 429" in haystack):
        return "openai_http_429"
    return None


def _candidate_packet(run_log: dict[str, Any]) -> list[dict[str, Any]]:
    pipeline = run_log.get("pipeline") if isinstance(run_log.get("pipeline"), dict) else {}
    rows = pipeline.get("modelCandidates") if isinstance(pipeline, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and _clean(row.get("candidateId"))]


def _is_raw_feed_text(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in RAW_FEED_PATTERNS)


def _fused_summary(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    fused = metadata.get("fusedContext") if isinstance(metadata.get("fusedContext"), list) else []
    for row in fused:
        if not isinstance(row, dict):
            continue
        summary = _clean(row.get("summary"))
        if summary and not _is_raw_feed_text(summary):
            return summary.lstrip("—- ")
    return ""


def _display_text(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    promotion = metadata.get("storyPromotion") if isinstance(metadata.get("storyPromotion"), dict) else {}
    choices = [
        promotion.get("freshnessSeed"),
        promotion.get("summarySeed"),
        _fused_summary(candidate),
        candidate.get("summary"),
        promotion.get("headlineSeed"),
        candidate.get("title"),
    ]
    for value in choices:
        text = _clean(value).lstrip("—- ")
        if text and not _is_raw_feed_text(text):
            return text
    return _clean(candidate.get("title")) or "Sports update"


def _compact_headline(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    promotion = metadata.get("storyPromotion") if isinstance(metadata.get("storyPromotion"), dict) else {}
    return _clean(promotion.get("headlineSeed") or candidate.get("title") or _display_text(candidate))


def _event_type(candidate: dict[str, Any]) -> str:
    raw = _clean(candidate.get("typeHint")).upper().replace(" ", "_")
    if raw and raw != "OTHER":
        return raw
    text = f"{_clean(candidate.get('title'))} {_clean(candidate.get('summary'))}".lower()
    if any(word in text for word in ("injury", "injured", "surgery", "out at least", "placed on ir", "spasms")):
        return "INJURY"
    if any(word in text for word in ("contract", "extension", "new deal", "agreed to a deal")):
        return "CONTRACT"
    if "trade" in text:
        return "TRADE"
    if "sign" in text and any(word in text for word in ("deal", "contract", "year")):
        return "SIGNING"
    if any(word in text for word in ("record", "milestone")):
        return "MILESTONE"
    if any(word in text for word in ("ranking", "rankings", "top 12", "playoff")):
        return "RANKING"
    if "streak" in text:
        return "STREAK"
    return "NEWS"


def _candidate_score(candidate: dict[str, Any]) -> float:
    event_type = _event_type(candidate)
    quality = float(candidate.get("quality") or 0)
    age = max(0.0, float(candidate.get("ageHours") or 24.0))
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    promotion = metadata.get("storyPromotion") if isinstance(metadata.get("storyPromotion"), dict) else {}
    story_score = float(promotion.get("storyScore") or 0)
    priority_floor = float(promotion.get("priorityFloor") or 0)
    type_bonus = {
        "MILESTONE": 30, "RECORD": 30, "UPSET": 27, "INJURY": 25,
        "TRADE": 24, "SIGNING": 23, "CONTRACT": 22, "PLAYOFF": 22,
        "STANDINGS": 20, "STREAK": 20, "RANKING": 18, "RESULT": 14,
        "RETURN": 15, "PERFORMANCE": 16, "NEWS": 6,
    }.get(event_type, 6)
    score = quality + type_bonus + max(0.0, 24.0 - age) * 1.25
    score += min(story_score, 90.0) * 0.20 + min(priority_floor, 90.0) * 0.10
    text = f"{_clean(candidate.get('title'))} {_clean(candidate.get('summary'))}".lower()
    if any(pattern in text for pattern in LOW_VALUE_PATTERNS):
        score -= 42
    if _clean(candidate.get("typeHint")).upper() == "OTHER":
        score -= 8
    if not candidate.get("sources"):
        score -= 20
    return score


def _priority(candidate: dict[str, Any]) -> int:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    promotion = metadata.get("storyPromotion") if isinstance(metadata.get("storyPromotion"), dict) else {}
    floor = int(float(promotion.get("priorityFloor") or 0))
    type_floor = {
        "MILESTONE": 82, "RECORD": 82, "UPSET": 82, "INJURY": 78,
        "TRADE": 78, "SIGNING": 76, "CONTRACT": 76, "PLAYOFF": 76,
        "STANDINGS": 74, "STREAK": 74, "RANKING": 72, "RESULT": 70,
        "RETURN": 72, "PERFORMANCE": 72, "NEWS": 64,
    }.get(_event_type(candidate), 64)
    return max(55, min(95, max(floor, type_floor)))


def _candidate_item(candidate: dict[str, Any], rank: int, feed_rank: int, now: datetime) -> dict[str, Any]:
    candidate_id = _clean(candidate.get("candidateId"))
    occurred = _parse_utc(candidate.get("occurredAt"))
    age_hours = (now - occurred).total_seconds() / 3600 if occurred else float(candidate.get("ageHours") or 0)
    age_hours = round(max(0.0, age_hours), 2)
    sources = []
    source_urls = []
    for source in candidate.get("sources") if isinstance(candidate.get("sources"), list) else []:
        if not isinstance(source, dict):
            continue
        url = _clean(source.get("url"))
        row = {
            "provider": _clean(source.get("provider")) or "Source",
            "sourceId": _clean(source.get("sourceId")) or "source",
            "url": url,
        }
        sources.append(row)
        if url and url not in source_urls:
            source_urls.append(url)
    display = _display_text(candidate)
    compact = _compact_headline(candidate)
    item_id = "a415-" + hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:16]
    return {
        "rank": rank,
        "candidateIds": [candidate_id],
        "type": _event_type(candidate),
        "priority": _priority(candidate),
        "headline": display,
        "text": display,
        "entities": [],
        "occurredAt": _utc_iso(occurred) if occurred else _clean(candidate.get("occurredAt")),
        "timePrecision": _clean(candidate.get("timePrecision")) or "exact",
        "ageHours": age_hours,
        "freshnessBasis": _clean(candidate.get("summary")) or display,
        "status": "active",
        "sourceUrls": source_urls,
        "sources": sources,
        "id": item_id,
        "feedRank": feed_rank,
        "compactHeadline": compact,
    }


def _previous_groups(previous: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for group in previous.get("leagues") if isinstance(previous.get("leagues"), list) else []:
        if isinstance(group, dict):
            league = _clean(group.get("league")).upper()
            if league:
                groups[league] = group
    return groups


def _fresh_previous_items(group: dict[str, Any], cutoff: datetime) -> list[dict[str, Any]]:
    items = group.get("items") if isinstance(group.get("items"), list) else []
    fresh = []
    for item in items:
        if not isinstance(item, dict):
            continue
        occurred = _parse_utc(item.get("occurredAt"))
        if occurred and occurred >= cutoff:
            fresh.append(dict(item))
    return fresh


def _select_candidates(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_league: dict[str, list[dict[str, Any]]] = {league: [] for league in BASE_LEAGUES}
    for candidate in candidates:
        league = _clean(candidate.get("leagueHint")).upper()
        if league not in by_league:
            continue
        occurred = _parse_utc(candidate.get("occurredAt"))
        if occurred is None:
            continue
        by_league[league].append(candidate)
    for league in BASE_LEAGUES:
        by_league[league].sort(key=lambda row: (_candidate_score(row), _parse_utc(row.get("occurredAt")) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)

    selected: dict[str, list[dict[str, Any]]] = {league: [] for league in BASE_LEAGUES}
    total = 0
    for league in BASE_LEAGUES:
        take = min(BASE_PER_LEAGUE, len(by_league[league]))
        selected[league].extend(by_league[league][:take])
        total += take

    while total < MAX_GLOBAL_ITEMS:
        best_league = None
        best_candidate = None
        best_score = float("-inf")
        for league in BASE_LEAGUES:
            if len(selected[league]) >= MAX_PER_LEAGUE:
                continue
            index = len(selected[league])
            if index >= len(by_league[league]):
                continue
            candidate = by_league[league][index]
            score = _candidate_score(candidate)
            if score > best_score:
                best_league, best_candidate, best_score = league, candidate, score
        if best_league is None or best_candidate is None:
            break
        selected[best_league].append(best_candidate)
        total += 1
    return selected


def _filtered_special_events(previous: dict[str, Any], cutoff: datetime) -> list[dict[str, Any]]:
    events = previous.get("specialEvents") if isinstance(previous.get("specialEvents"), list) else []
    output = []
    for event in events:
        if not isinstance(event, dict):
            continue
        clone = dict(event)
        items = event.get("items") if isinstance(event.get("items"), list) else []
        clone["items"] = [dict(item) for item in items if isinstance(item, dict) and (_parse_utc(item.get("occurredAt")) or cutoff) >= cutoff]
        if clone["items"]:
            output.append(clone)
    return output


def build_fallback_payload(run_log: dict[str, Any], previous: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now - timedelta(hours=24)
    candidates = [c for c in _candidate_packet(run_log) if (_parse_utc(c.get("occurredAt")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    if len(candidates) < 4:
        raise RuntimeError(f"editor fallback requires >=4 fresh grounded candidates; found {len(candidates)}")

    selected = _select_candidates(candidates)
    previous_groups = _previous_groups(previous)
    leagues = []
    used_candidate_ids: set[str] = set()
    feed_rank = 0

    for league in BASE_LEAGUES:
        group_previous = previous_groups.get(league, {})
        chosen = selected[league]
        items = []
        seen_text: set[str] = set()
        for candidate in chosen:
            feed_rank += 1
            item = _candidate_item(candidate, len(items) + 1, feed_rank, now)
            key = _clean(item.get("text")).lower()
            if key and key not in seen_text:
                items.append(item)
                seen_text.add(key)
                used_candidate_ids.update(item.get("candidateIds", []))

        if len(items) < BASE_PER_LEAGUE:
            for old in _fresh_previous_items(group_previous, cutoff):
                if len(items) >= BASE_PER_LEAGUE:
                    break
                key = _clean(old.get("text") or old.get("headline")).lower()
                old_ids = {str(x) for x in old.get("candidateIds", []) if x}
                if not key or key in seen_text or old_ids.intersection(used_candidate_ids):
                    continue
                old["rank"] = len(items) + 1
                old["status"] = "active"
                items.append(old)
                seen_text.add(key)
                used_candidate_ids.update(old_ids)

        leagues.append({
            "league": league,
            "seasonState": _clean(group_previous.get("seasonState")) or ("active" if items else "inactive"),
            "items": items,
        })

    payload = dict(previous) if isinstance(previous, dict) else {}
    candidate_hash = hashlib.sha256(
        "\n".join(sorted(_clean(c.get("candidateId")) for c in candidates)).encode("utf-8")
    ).hexdigest()
    payload.update({
        "schemaVersion": previous.get("schemaVersion", 11),
        "pipelineVersion": PIPELINE_VERSION,
        "generatedAt": _utc_iso(now),
        "freshnessHours": 24.0,
        "model": "deterministic-source-fallback",
        "sourceCandidateHash": candidate_hash,
        "leagues": leagues,
        "specialEvents": _filtered_special_events(previous, cutoff),
        "displayCopyField": "text",
        "browserDisplayCompatibilityField": "headline",
        "compactHeadlineField": "compactHeadline",
        "headlineRole": "legacy-browser-mirror-of-text",
        "compactHeadlineRole": "compact-editorial-metadata",
        "editorFallback": {
            "active": True,
            "version": "A4.15",
            "mode": "deterministic-grounded-source-selection",
            "reason": _editor_outage_reason(run_log) or "editor_unavailable",
            "freshCandidateCount": len(candidates),
            "publishedItemCount": sum(len(group["items"]) for group in leagues),
            "policy": "Use direct source candidates only; keep prior items only while still inside the 24-hour freshness window.",
        },
    })
    return payload


def _mark_run_log_fallback(run_log: dict[str, Any], reason: str, payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(run_log)
    pipeline = dict(updated.get("pipeline")) if isinstance(updated.get("pipeline"), dict) else {}
    original_error = pipeline.get("sourceError") or pipeline.get("editorError")
    pipeline["status"] = "ok"
    pipeline["pipelineVersion"] = PIPELINE_VERSION
    pipeline["editorCalled"] = False
    pipeline["sourceError"] = None
    if original_error:
        pipeline["editorError"] = original_error
    pipeline["editorFallback"] = {
        "active": True,
        "version": "A4.15",
        "reason": reason,
        "mode": "deterministic-grounded-source-selection",
        "publishedItemCount": sum(len(group.get("items", [])) for group in payload.get("leagues", []) if isinstance(group, dict)),
        "generatedAt": payload.get("generatedAt"),
    }
    updated["pipeline"] = pipeline
    return updated


def main() -> int:
    a414 = _load_a414()
    code = int(a414.main())
    if code == 0:
        return 0

    data_dir = _data_dir_from_argv(sys.argv[1:])
    run_log_path = data_dir / "sports-ticker-run-log.json"
    ticker_path = data_dir / "sports-ticker.json"
    run_log = _read_json(run_log_path)
    reason = _editor_outage_reason(run_log)
    if not reason:
        print(f"A4.15 fallback bypassed: A4.14 failed with non-editor-outage error (exit {code}).")
        return code

    try:
        previous = _read_json(ticker_path)
        payload = build_fallback_payload(run_log, previous)
        _atomic_json(ticker_path, payload)
        _atomic_json(run_log_path, _mark_run_log_fallback(run_log, reason, payload))
    except Exception as exc:
        print(f"A4.15 fallback failed closed: {exc}")
        return code

    item_count = sum(len(group.get("items", [])) for group in payload.get("leagues", []) if isinstance(group, dict))
    print(f"A4.15 editor fallback published {item_count} grounded ticker items ({reason}).")
    print("OpenAI editor remains preferred; fallback will automatically disengage when A4.14 succeeds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

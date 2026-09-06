#!/usr/bin/env python3
"""Sports Big Board A4.8 editorial-progression + pre-budget identity overlay on A4.7.

A4.8 freezes the working 30-35 headline architecture and fixes the remaining
selection-order/editorial-thread issues exposed by the first A4.7 live run:

- run A4.7 game/event identity checks BEFORE the A4.3 global selector, so rejected
  rows can be replaced instead of shrinking the final ribbon after selection;
- collapse cross-type duplicates from the same game when they describe the same
  underlying development (for example a milestone headline plus a streak headline
  about the same player's only goal in the same 1-0 match);
- treat successive STANDINGS headlines for the same matchup/race as a current-state
  thread and keep the newest standings state rather than both the old and new lead;
- reindex section rank and global feedRank after all final correctness filtering.

No discovery source, headline budget, source-depth setting, league cap, or headline
length changes in this release.
"""
from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.8-prebudget-identity-editorial-progression"
SAME_GAME_WINDOW_HOURS = 12.0
STANDINGS_THREAD_WINDOW_HOURS = 24.0

A48_EDITOR_ADDENDUM = r"""

A4.8 CURRENT-STATE EDITORIAL THREADS — CRITICAL
Do NOT change the established 30-35 headline budget, source depth, coverage caps,
or 80/96-character headline contract.

ONE GAME, ONE PRIMARY TICKER STORY
- When two items describe the SAME game and same underlying development from
  different editorial angles, keep the strongest version rather than both.
- Example: a milestone story about Haaland's 300th club goal and a separate streak
  story about Haaland scoring the only goal in that same 1-0 match should become
  one milestone-led ticker story.
- Do NOT collapse independent major developments from the same game, such as a
  serious injury plus a record, or discipline plus a result.

CURRENT STANDINGS STATE
- Standings copy is stateful. When a later game updates the exact same standings
  race/matchup, prefer the newest current state rather than retaining an earlier
  now-superseded lead/gap headline in the same 24-hour ticker.

IDENTITY FILTER ORDER
- Game identity and named-Special-Event affinity must be enforced before final
  global selection so rejected rows can be replaced by another legitimate story.
"""

MERGEABLE_SAME_GAME_TYPES = {
    "RESULT", "UPSET", "MILESTONE", "RECORD", "RECORD_CHASE", "STREAK", "STANDINGS",
}
# Keep independent safety/status/transaction stories even if they happened in the same game.
INDEPENDENT_TYPES = {
    "INJURY", "SUSPENSION", "DISCIPLINE", "LEGAL", "TRADE", "SIGNING", "CONTRACT",
    "COACHING", "ROSTER", "DEPTH_CHART",
}
TYPE_STRENGTH = {
    "RECORD": 90,
    "RECORD_CHASE": 86,
    "MILESTONE": 84,
    "UPSET": 82,
    "STANDINGS": 78,
    "STREAK": 74,
    "RESULT": 70,
}

RACE_PATTERNS = (
    r"\b(?:al|nl)\s+(?:east|central|west)\b",
    r"\bwild\s*card\b",
    r"\bdivision\s+(?:lead|race|gap)\b",
    r"\bconference\s+(?:lead|race|standings)\b",
    r"\bplayoff\s+(?:race|position|spot|picture)\b",
)


def _load_a47():
    path = Path(__file__).with_name("refresh_sports_ticker_a47.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a47", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.7 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm(value: Any) -> str:
    text = _clean(value).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return " ".join(text.split())


def _parse_time(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _item_blob(item: dict[str, Any]) -> str:
    return _norm(" ".join([
        _clean(item.get("headline")),
        _clean(item.get("text")),
        _clean(item.get("freshnessBasis")),
        " ".join(_clean(x) for x in item.get("entities", []) if isinstance(x, str)),
    ]))


def _entities(item: dict[str, Any]) -> set[str]:
    raw = item.get("entities") if isinstance(item.get("entities"), list) else []
    return {_norm(x) for x in raw if _norm(x)}


def _score_pairs(item: dict[str, Any]) -> set[tuple[int, int]]:
    raw = " ".join([
        _clean(item.get("headline")),
        _clean(item.get("text")),
        _clean(item.get("freshnessBasis")),
    ])
    return {
        tuple(sorted((int(a), int(b))))
        for a, b in re.findall(r"(?<!\d)(\d{1,3})\s*[-–—]\s*(\d{1,3})(?!\d)", raw)
    }


def _time_distance_hours(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    da = _parse_time(a.get("occurredAt"))
    db = _parse_time(b.get("occurredAt"))
    if da is None or db is None:
        return None
    return abs((da - db).total_seconds()) / 3600.0


def _same_game_editorial_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ta = _clean(a.get("type")).upper()
    tb = _clean(b.get("type")).upper()
    if ta in INDEPENDENT_TYPES or tb in INDEPENDENT_TYPES:
        return False
    if ta not in MERGEABLE_SAME_GAME_TYPES or tb not in MERGEABLE_SAME_GAME_TYPES:
        return False

    shared = _entities(a) & _entities(b)
    # Require the two teams plus at least one shared actor/identity. This prevents
    # unrelated games in a series/doubleheader from collapsing on teams alone.
    if len(shared) < 3:
        return False

    scores_a, scores_b = _score_pairs(a), _score_pairs(b)
    if not scores_a or not scores_b or not (scores_a & scores_b):
        return False

    hours = _time_distance_hours(a, b)
    if hours is not None and hours > SAME_GAME_WINDOW_HOURS:
        return False
    return True


def _race_tokens(item: dict[str, Any]) -> set[str]:
    blob = _item_blob(item)
    out: set[str] = set()
    for pattern in RACE_PATTERNS:
        out.update(m.group(0) for m in re.finditer(pattern, blob))
    return {_norm(x) for x in out if _norm(x)}


def _same_standings_thread(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if _clean(a.get("type")).upper() != "STANDINGS" or _clean(b.get("type")).upper() != "STANDINGS":
        return False
    if len(_entities(a) & _entities(b)) < 2:
        return False
    races_a, races_b = _race_tokens(a), _race_tokens(b)
    if not races_a or not races_b or not (races_a & races_b):
        return False
    hours = _time_distance_hours(a, b)
    return hours is None or hours <= STANDINGS_THREAD_WINDOW_HOURS


def _story_rank(item: dict[str, Any]) -> tuple[int, int, float]:
    kind = _clean(item.get("type")).upper()
    priority = int(item.get("priority") or 0)
    dt = _parse_time(item.get("occurredAt"))
    timestamp = dt.timestamp() if dt else 0.0
    return (TYPE_STRENGTH.get(kind, 0), priority, timestamp)


def _newer_rank(item: dict[str, Any]) -> tuple[float, int]:
    dt = _parse_time(item.get("occurredAt"))
    return (dt.timestamp() if dt else 0.0, int(item.get("priority") or 0))


def collapse_editorial_progressions(
    normalized: dict[str, Any],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collapse same-game cross-type duplicates and superseded standings state."""
    drops: list[dict[str, Any]] = []

    for group in normalized.get("leagues", []):
        league = _clean(group.get("league"))
        items = group.get("items", []) if isinstance(group.get("items"), list) else []
        kept: list[dict[str, Any]] = []

        for item in items:
            match_index: int | None = None
            reason = ""
            choose_newer = False
            for idx, existing in enumerate(kept):
                if _same_standings_thread(item, existing):
                    match_index = idx
                    reason = "A4.8 superseded standings state"
                    choose_newer = True
                    break
                if _same_game_editorial_duplicate(item, existing):
                    match_index = idx
                    reason = "A4.8 same-game cross-type editorial duplicate"
                    break

            if match_index is None:
                kept.append(item)
                continue

            existing = kept[match_index]
            if choose_newer:
                item_wins = _newer_rank(item) > _newer_rank(existing)
            else:
                item_wins = _story_rank(item) > _story_rank(existing)

            winner, loser = (item, existing) if item_wins else (existing, item)
            if item_wins:
                kept[match_index] = item
            drops.append({
                "league": league,
                "headline": loser.get("headline"),
                "candidateIds": loser.get("candidateIds", []),
                "kept": winner.get("headline"),
                "keptCandidateIds": winner.get("candidateIds", []),
                "reason": reason,
            })

        group["items"] = kept

    if run_log is not None:
        run_log.setdefault("pipeline", {})["a48EditorialProgressionDrops"] = drops
    return normalized


def reindex_output(normalized: dict[str, Any]) -> dict[str, Any]:
    """Make section rank/feedRank contiguous after any fail-closed filtering."""
    all_items: list[dict[str, Any]] = []
    for group in normalized.get("leagues", []):
        items = group.get("items", []) if isinstance(group.get("items"), list) else []
        for rank, item in enumerate(items, 1):
            item["rank"] = rank
            all_items.append(item)

    rebuilt_events = []
    for event in normalized.get("specialEvents", []):
        items = event.get("items", []) if isinstance(event.get("items"), list) else []
        if not items:
            continue
        for rank, item in enumerate(items, 1):
            item["rank"] = rank
            all_items.append(item)
        rebuilt_events.append(event)
    normalized["specialEvents"] = rebuilt_events

    # Preserve the selector's editorial ordering, merely closing any gaps.
    ordered = sorted(
        all_items,
        key=lambda item: (
            int(item.get("feedRank") or 10**9),
            -int(item.get("priority") or 0),
            _clean(item.get("headline")),
        ),
    )
    for feed_rank, item in enumerate(ordered, 1):
        item["feedRank"] = feed_rank
    return normalized


def _patch_a45(a45, a46, a47) -> None:
    # Install A4.7 first, then move its deterministic identity policy ahead of the
    # A4.3 global selector without removing the post-budget safety net.
    a47._patch_a45(a45, a46)
    a45.PIPELINE_VERSION = PIPELINE_VERSION
    a45.A45_EDITOR_ADDENDUM = a45.A45_EDITOR_ADDENDUM + A48_EDITOR_ADDENDUM

    original_load_a44 = a45._load_a44

    def load_a44_a48():
        a44 = original_load_a44()
        a44.PIPELINE_VERSION = PIPELINE_VERSION
        original_patch_a43 = a44._patch_a43

        def patch_a43_a48(a43):
            original_patch_a43(a43)
            a43.PIPELINE_VERSION = PIPELINE_VERSION
            original_patch_a42 = a43._patch_a42

            def patch_a42_a48(a42):
                original_patch_a42(a42)
                a42.PIPELINE_VERSION = PIPELINE_VERSION

                candidate_holder: dict[str, list[dict[str, Any]]] = {"items": []}
                original_budget = a42.apply_global_headline_budget

                def budget_a48(normalized, run_log=None):
                    # A4.7 previously ran after this budget, which could produce 31/32
                    # and stale ranks after a fail-closed drop. Run the exact same
                    # correctness gate here first so the selector can backfill.
                    a47.enforce_output_identity(
                        normalized,
                        candidate_holder.get("items", []),
                        run_log,
                    )
                    collapse_editorial_progressions(normalized, run_log)
                    return original_budget(normalized, run_log)

                a42.apply_global_headline_budget = budget_a48
                original_configure = a42._configure_core

                def configure_a48(core):
                    original_configure(core)
                    core.EDITOR_INSTRUCTIONS = core.EDITOR_INSTRUCTIONS + "\n\n" + A48_EDITOR_ADDENDUM
                    original_normalize = core.normalize_model_output
                    original_init = core.initial_run_log

                    def normalize_a48(model_output, candidates, generated_at, run_log):
                        candidate_holder["items"] = list(candidates or [])
                        try:
                            normalized = original_normalize(model_output, candidates, generated_at, run_log)
                            return reindex_output(normalized)
                        finally:
                            candidate_holder["items"] = []

                    def initial_run_log_a48(generated_at, cutoff, model):
                        log = original_init(generated_at, cutoff, model)
                        log["pipelineVersion"] = PIPELINE_VERSION
                        log.setdefault("configuration", {})["editorialProgressionPolicy"] = (
                            "A4.8 pre-budget A4.7 identity filtering + same-game cross-type dedupe + "
                            "newest-state standings progression; 30-35 architecture unchanged"
                        )
                        return log

                    core.normalize_model_output = normalize_a48
                    core.initial_run_log = initial_run_log_a48

                a42._configure_core = configure_a48

            a43._patch_a42 = patch_a42_a48

        a44._patch_a43 = patch_a43_a48
        return a44

    a45._load_a44 = load_a44_a48


def main() -> int:
    a47 = _load_a47()
    a46 = a47._load_a46()
    a45 = a46._load_a45()
    _patch_a45(a45, a46, a47)
    return a45.main()


if __name__ == "__main__":
    raise SystemExit(main())

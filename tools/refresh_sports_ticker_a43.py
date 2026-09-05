#!/usr/bin/env python3
"""Sports Big Board A4.3 quality/coverage overlay on A4.2.

A4.3 keeps the proven A3/A4.2 discovery, grounding, FBS identity, result-story
promotion and conditional refill machinery, then adds the live-ribbon refinements
learned from the first 30-35 headline runs:

- semantic story dedupe across different candidate IDs/articles;
- coverage-first refill guidance so missing/underrepresented leagues beat the
  ninth routine score from a single league;
- story-driven draws may survive when grounded recap context exists;
- weak generic Special Event buckets such as "Tennis (Tennis)" are suppressed;
- live UI permits longer two-line headlines: target <=80 chars, hard max 96.

This file is deliberately a thin overlay. ``refresh_sports_ticker_a4.py`` remains
A4.2 and is loaded at runtime, minimizing conflict with parallel Big Board work.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import textwrap
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.3-quality-coverage"
GLOBAL_HEADLINE_MIN = 30
GLOBAL_HEADLINE_TARGET = 32
GLOBAL_HEADLINE_MAX = 35
HEADLINE_TARGET_CHARS = 80
HEADLINE_MAX_CHARS = 96
SOFT_BASE_CONTEXT_CAP = 7
HARD_BASE_CONTEXT_CAP = 9
SPECIAL_EVENT_CAP = 4
SPECIAL_TOTAL_CAP = 10
REFILL_RAW_FLOOR = 34
REFILL_RAW_TARGET = 35

GENERIC_SPECIAL_NAMES = {
    "tennis", "golf", "formula 1", "f1", "motorsport", "motor racing",
    "mma", "ufc", "boxing", "racing", "auto racing",
}
WEAK_GENERIC_SPECIAL_TYPES = {
    "OTHER", "NEXT", "SCHEDULE", "PRACTICE", "EVENT_UPDATE",
}

STOPWORDS = {
    "a", "an", "and", "as", "at", "after", "against", "by", "for", "from",
    "in", "into", "is", "it", "its", "of", "on", "past", "the", "to", "with",
    "over", "out", "up", "down", "their", "his", "her", "this", "that",
}
ACTION_WORDS = {
    "advance", "advances", "advanced", "beat", "beats", "defeat", "defeats",
    "defeated", "draw", "draws", "ejected", "extension", "injury", "lose",
    "loses", "lost", "penalty", "pole", "retire", "retires", "retired", "rout",
    "routs", "shutout", "sign", "signs", "signed", "suspend", "suspended",
    "trade", "traded", "walkoff", "win", "wins", "won",
}
DRAW_STORY_CUES = {
    "goalkeeper", "goalkeepers", "save", "saves", "clean sheet", "first goal",
    "unbeaten", "comeback", "rally", "rallies", "late equalizer", "equalizer",
    "record", "milestone", "debut", "streak", "career first", "first english goal",
}

A43_EDITOR_ADDENDUM = r"""

A4.3 LIVE-RIBBON OVERRIDES — THESE SUPERSEDE EARLIER A4 LENGTH/MIX VALUES
The Sports Ticker is now live in the Big Board UI. The cards have enough room for
longer two-line headlines.

HEADLINE COPY
- Preferred headline length: about 50-80 characters.
- HARD maximum: 96 characters including spaces and punctuation.
- Do not shorten a useful natural headline merely to hit 64 characters.
- Still write ticker copy, not article-title prose. Put tertiary detail in the text field.

DUPLICATES
- One underlying sports development gets ONE ticker headline, even when two source
  candidates/articles describe it differently.
- Examples: two articles about the same driver taking the same pole position are one
  story; two articles about the same Williams-sisters doubles loss are one story.
- Prefer the candidate with the clearest result/development and strongest sourcing.

COVERAGE MIX
- Before selecting a sixth or later routine RESULT from one league, prefer a valid
  fresh development/result from a base league that currently has zero or very few
  headlines.
- Do not force equal representation, but the refill should broaden the ribbon rather
  than simply deepen MLB/NCAAF because they have abundant structured scores.
- A grounded draw can be ticker-worthy when the supplied recap establishes a real
  hook such as a goalkeeper duel, first goal, unbeaten streak, comeback or milestone.

SPECIAL EVENTS
- Do not create a weak catch-all event bucket named only "Tennis", "Golf",
  "Formula 1", etc. Generic buckets are reserved for genuinely major standalone
  BREAKING/INJURY/RECORD-style developments. Routine quotes/plans/analysis should omit.
"""

A43_REFILL_TEMPLATE = r"""

A4.3 CONDITIONAL REFILL — COVERAGE FIRST
The first editorial pass returned {primary_count} headlines. Because normalization,
relevance checks and semantic dedupe can remove several stories, build enough useful
inventory to reach roughly {raw_floor}-{raw_target} RAW headlines before final curation.

Return at least {minimum_additional} additional headlines if that many remaining
candidates pass the hard-news test; ideally return {desired_additional}.

FIRST-PASS CONTEXT COUNTS
{context_counts}

FIRST-PASS HEADLINES — DO NOT REPEAT THE SAME UNDERLYING STORY
{primary_headlines}

Refill priorities:
1. Useful fresh candidates from base leagues with zero/one first-pass headline.
2. Major news, records, injuries, transactions, upsets and meaningful Special Events.
3. Useful results from active leagues.
4. Only after broader coverage is exhausted, additional routine MLB/NCAAF results.

Do not select a remaining candidate when it is merely another article about a first-pass
story. Avoid weak generic Special Event buckets. Headlines may run about 50-80 chars;
96 characters is the absolute maximum.
"""


def _load_a42():
    path = Path(__file__).with_name("refresh_sports_ticker_a4.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a42", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.2 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm(value: Any) -> str:
    text = _clean(value).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return " ".join(text.split())


def _tokens(value: Any) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", _norm(value))
        if token not in STOPWORDS and len(token) > 1
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _score_pairs(text: str) -> set[tuple[int, int]]:
    return {
        (int(a), int(b))
        for a, b in re.findall(r"(?<!\d)(\d{1,3})\s*[-–—]\s*(\d{1,3})(?!\d)", text)
    }


def _context_family(row: dict[str, Any]) -> str:
    context = _norm(row.get("context"))
    context = re.sub(r"\b(round of \d+|quarterfinals?|semifinals?|finals?|day \d+)\b", " ", context)
    return " ".join(context.split())


def _meaningful_entities(row: dict[str, Any]) -> set[str]:
    item = row.get("item") if isinstance(row.get("item"), dict) else {}
    context = _norm(row.get("context"))
    sport = _norm(row.get("sport"))
    out: set[str] = set()
    for entity in item.get("entities", []) if isinstance(item.get("entities"), list) else []:
        value = _norm(entity)
        if not value or value in {context, sport} or value in GENERIC_SPECIAL_NAMES:
            continue
        out.add(value)
    return out


def _item_text(row: dict[str, Any]) -> str:
    item = row["item"]
    return " ".join((_clean(item.get("headline")), _clean(item.get("text"))))


def _is_semantic_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ia, ib = a["item"], b["item"]
    ids_a = {x for x in ia.get("candidateIds", []) if isinstance(x, str)}
    ids_b = {x for x in ib.get("candidateIds", []) if isinstance(x, str)}
    if ids_a & ids_b:
        return True

    ta, tb = _tokens(_item_text(a)), _tokens(_item_text(b))
    sim = _jaccard(ta, tb)
    if sim >= 0.72:
        return True

    same_context = _context_family(a) == _context_family(b)
    if not same_context:
        return False

    entities_a, entities_b = _meaningful_entities(a), _meaningful_entities(b)
    entity_overlap = entities_a & entities_b
    actions_a, actions_b = ta & ACTION_WORDS, tb & ACTION_WORDS
    action_overlap = actions_a & actions_b
    type_a = _clean(ia.get("type")).upper()
    type_b = _clean(ib.get("type")).upper()

    if type_a in {"RESULT", "UPSET", "ADVANCEMENT"} or type_b in {"RESULT", "UPSET", "ADVANCEMENT"}:
        scores_a = _score_pairs(_item_text(a))
        scores_b = _score_pairs(_item_text(b))

        # Base-league schedules can contain multiple real games between the same
        # teams (most notably MLB doubleheaders). Do not semantically collapse
        # distinct league results merely because team entities overlap.
        if a.get("kind") == "league" and b.get("kind") == "league":
            if len(entity_overlap) >= 2 and scores_a and (scores_a & scores_b):
                return _result_times_close(a, b)
            return sim >= 0.72

        # Tournament/special-event duplicate articles frequently describe the
        # exact same completed match from different editorial angles.
        if len(entity_overlap) >= 2 and sim >= 0.30:
            return True
        if entity_overlap and scores_a and (scores_a & scores_b):
            return True
        return False

    # Same event + same person/team + same concrete action (pole, penalty,
    # extension, etc.) is one development even if the article framing differs.
    return bool(entity_overlap and action_overlap and sim >= 0.28)



def _parse_occurrence(value: Any) -> datetime | None:
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


def _result_times_close(a: dict[str, Any], b: dict[str, Any]) -> bool:
    da = _parse_occurrence(a["item"].get("occurredAt"))
    db = _parse_occurrence(b["item"].get("occurredAt"))
    if da is None or db is None:
        return True
    return abs((da - db).total_seconds()) <= 3 * 3600

def _age(row: dict[str, Any]) -> float:
    try:
        value = row["item"].get("ageHours")
        return float(value) if value is not None else 24.0
    except Exception:
        return 24.0


def _editorial_score(row: dict[str, Any]) -> float:
    item = row["item"]
    item_type = _clean(item.get("type")).upper()
    score = float(int(item.get("priority") or 0))
    score += {
        "BREAKING": 14, "PLAYOFF": 12, "TRADE": 9, "UPSET": 8,
        "RECORD": 8, "RECORD_CHASE": 7, "INJURY": 7, "SIGNING": 6,
        "MILESTONE": 6, "RANKING": 6, "STANDINGS": 6, "ADVANCEMENT": 6,
        "QUALIFYING": 3, "EVENT_UPDATE": 2, "RESULT": 0,
        "PRACTICE": -1, "NEXT": -3, "SCHEDULE": -4, "OTHER": -4,
    }.get(item_type, 0)
    state = _clean(row.get("seasonState")).lower()
    if state == "postseason":
        score += 5
    elif state == "active":
        score += 3
    elif state == "preseason":
        score -= 1
    elif state == "offseason":
        score -= 2
    score += max(0.0, 3.0 - (_age(row) / 8.0))
    return score


def _quality_key(row: dict[str, Any]) -> tuple[float, int, float, int]:
    item = row["item"]
    source_count = len(item.get("sources", [])) if isinstance(item.get("sources"), list) else 0
    return (
        _editorial_score(row),
        int(item.get("priority") or 0),
        -_age(row),
        source_count,
    )


def _flatten(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in normalized.get("leagues", []):
        league = _clean(group.get("league"))
        state = _clean(group.get("seasonState"))
        for item in group.get("items", []):
            rows.append({
                "kind": "league", "context": league, "league": league,
                "seasonState": state, "item": item,
            })
    for event in normalized.get("specialEvents", []):
        name = _clean(event.get("name"))
        sport = _clean(event.get("sport"))
        for item in event.get("items", []):
            rows.append({
                "kind": "special", "context": name, "event": name,
                "sport": sport, "seasonState": "special", "item": item,
            })
    return rows


def _compact_headline(value: Any) -> str:
    headline = _clean(value)
    if len(headline) <= HEADLINE_TARGET_CHARS:
        return headline
    replacements = [
        ("Italian Grand Prix", "Italian GP"),
        ("United States Grand Prix", "U.S. GP"),
        ("contract extension", "extension"),
        ("first career pole position", "first career pole"),
    ]
    for old, new in replacements:
        headline = headline.replace(old, new)
        if len(headline) <= HEADLINE_TARGET_CHARS:
            return headline
    if len(headline) <= HEADLINE_MAX_CHARS:
        return headline
    return textwrap.shorten(headline, width=HEADLINE_MAX_CHARS, placeholder="…")


def _is_weak_generic_special(row: dict[str, Any]) -> bool:
    if row.get("kind") != "special":
        return False
    context = _context_family(row)
    sport = _norm(row.get("sport"))
    generic = context in GENERIC_SPECIAL_NAMES or context == sport
    if not generic:
        return False
    item = row["item"]
    item_type = _clean(item.get("type")).upper()
    priority = int(item.get("priority") or 0)
    return item_type in WEAK_GENERIC_SPECIAL_TYPES and priority < 75


def _draw_has_story_hook(item: dict[str, Any]) -> bool:
    text = _norm(f"{item.get('headline', '')} {item.get('text', '')}")
    return any(cue in text for cue in DRAW_STORY_CUES)


def _dedupe_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(rows, key=_quality_key, reverse=True)
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for row in ordered:
        duplicate_of = next((existing for existing in kept if _is_semantic_duplicate(row, existing)), None)
        if duplicate_of is None:
            kept.append(row)
            continue
        dropped.append({
            "context": row.get("context"),
            "headline": row["item"].get("headline"),
            "candidateIds": row["item"].get("candidateIds", []),
            "duplicateOf": duplicate_of["item"].get("headline"),
            "duplicateCandidateIds": duplicate_of["item"].get("candidateIds", []),
        })
    return kept, dropped


def _context_counts(model_output: dict[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    leagues = model_output.get("leagues", {})
    if isinstance(leagues, dict):
        for league, group in leagues.items():
            if isinstance(group, dict) and isinstance(group.get("items"), list):
                counts[str(league)] += len(group["items"])
    events = model_output.get("specialEvents", [])
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and isinstance(event.get("items"), list):
                counts[_clean(event.get("name")) or "Special Event"] += len(event["items"])
    return dict(counts)


def _model_headlines(model_output: dict[str, Any]) -> list[str]:
    out: list[str] = []
    leagues = model_output.get("leagues", {})
    if isinstance(leagues, dict):
        for group in leagues.values():
            if isinstance(group, dict):
                for item in group.get("items", []):
                    if isinstance(item, dict) and _clean(item.get("headline")):
                        out.append(_clean(item.get("headline")))
    for event in model_output.get("specialEvents", []) if isinstance(model_output.get("specialEvents"), list) else []:
        if isinstance(event, dict):
            for item in event.get("items", []):
                if isinstance(item, dict) and _clean(item.get("headline")):
                    out.append(_clean(item.get("headline")))
    return out


def _refill_targets(primary_count: int, remaining_count: int) -> tuple[int, int]:
    minimum = min(max(0, REFILL_RAW_FLOOR - primary_count), remaining_count)
    desired = min(max(0, REFILL_RAW_TARGET - primary_count), remaining_count)
    return minimum, desired


def _rebuild(normalized: dict[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
    selected_ids = {id(row["item"]) for row in selected}
    for feed_rank, row in enumerate(selected, 1):
        row["item"]["feedRank"] = feed_rank

    for group in normalized.get("leagues", []):
        kept = [item for item in group.get("items", []) if id(item) in selected_ids]
        kept.sort(key=lambda item: int(item.get("feedRank") or 999))
        for rank, item in enumerate(kept, 1):
            item["rank"] = rank
        group["items"] = kept

    events = []
    for event in normalized.get("specialEvents", []):
        kept = [item for item in event.get("items", []) if id(item) in selected_ids]
        kept.sort(key=lambda item: int(item.get("feedRank") or 999))
        for rank, item in enumerate(kept, 1):
            item["rank"] = rank
        if kept:
            event["items"] = kept
            events.append(event)
    normalized["specialEvents"] = events
    return normalized


def apply_quality_budget(
    normalized: dict[str, Any],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Semantic dedupe + coverage-first 30-35 global selection."""
    rows = _flatten(normalized)
    for row in rows:
        row["item"]["headline"] = _compact_headline(row["item"].get("headline"))

    weak_drops = [row for row in rows if _is_weak_generic_special(row)]
    rows = [row for row in rows if not _is_weak_generic_special(row)]
    rows, duplicate_drops = _dedupe_rows(rows)
    rows.sort(key=_quality_key, reverse=True)

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    base_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    special_total = 0

    def can_take(row: dict[str, Any], base_cap: int) -> bool:
        nonlocal special_total
        if id(row["item"]) in selected_ids:
            return False
        if row["kind"] == "league":
            return base_counts[row["context"]] < base_cap
        return (
            special_total < SPECIAL_TOTAL_CAP
            and event_counts[row["context"]] < SPECIAL_EVENT_CAP
        )

    def take(row: dict[str, Any]) -> None:
        nonlocal special_total
        selected.append(row)
        selected_ids.add(id(row["item"]))
        if row["kind"] == "league":
            base_counts[row["context"]] += 1
        else:
            event_counts[row["context"]] += 1
            special_total += 1

    # Coverage seed: one best legitimate item from every context represented by
    # the editor, preventing abundant score feeds from starving smaller leagues.
    best_by_context: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["kind"], row["context"])
        best_by_context.setdefault(key, row)
    for row in sorted(best_by_context.values(), key=_quality_key, reverse=True):
        if len(selected) >= GLOBAL_HEADLINE_TARGET:
            break
        if can_take(row, SOFT_BASE_CONTEXT_CAP):
            take(row)

    # Normal fill with a soft seven-item base-league cap.
    for row in rows:
        if len(selected) >= GLOBAL_HEADLINE_TARGET:
            break
        if can_take(row, SOFT_BASE_CONTEXT_CAP):
            take(row)

    # Major stories can use the slots above target regardless of soft base cap.
    for row in rows:
        if len(selected) >= GLOBAL_HEADLINE_MAX:
            break
        if id(row["item"]) in selected_ids:
            continue
        if int(row["item"].get("priority") or 0) >= 88 and can_take(row, HARD_BASE_CONTEXT_CAP):
            take(row)

    # Underfill relaxation: deepen a league only after breadth has been exhausted.
    if len(selected) < GLOBAL_HEADLINE_MIN:
        for row in rows:
            if len(selected) >= GLOBAL_HEADLINE_MIN:
                break
            if can_take(row, HARD_BASE_CONTEXT_CAP):
                take(row)

    selected.sort(key=_quality_key, reverse=True)
    selected = selected[:GLOBAL_HEADLINE_MAX]
    _rebuild(normalized, selected)

    if run_log is not None:
        pipe = run_log.setdefault("pipeline", {})
        pipe["semanticDedupe"] = {
            "droppedCount": len(duplicate_drops),
            "dropped": duplicate_drops,
        }
        pipe["weakGenericSpecialDrops"] = [
            {
                "context": row.get("context"),
                "headline": row["item"].get("headline"),
                "type": row["item"].get("type"),
                "priority": row["item"].get("priority"),
            }
            for row in weak_drops
        ]
        budget = pipe.setdefault("globalHeadlineBudget", {})
        budget.update({
            "min": GLOBAL_HEADLINE_MIN,
            "target": GLOBAL_HEADLINE_TARGET,
            "max": GLOBAL_HEADLINE_MAX,
            "inputCount": len(_flatten(normalized)) + len(duplicate_drops) + len(weak_drops),
            "eligibleCount": len(rows),
            "selectedCount": len(selected),
            "underfilled": len(selected) < GLOBAL_HEADLINE_MIN,
            "coverageCounts": dict(base_counts),
            "specialEventCounts": dict(event_counts),
        })
    return normalized


def _make_refilling_editor(a42, core, original_call_openai):
    def call_openai_a43(api_key, model, candidates, run_log):
        primary = original_call_openai(api_key, model, candidates, run_log)
        primary_count = a42._model_output_count(primary)
        used_ids = a42._selected_candidate_ids(primary)
        remaining = [c for c in candidates if c.get("candidateId") not in used_ids]
        minimum_additional, desired_additional = _refill_targets(primary_count, len(remaining))

        refill_log = run_log.setdefault("pipeline", {}).setdefault("editorRefill", {})
        refill_log.update({
            "called": False,
            "primaryCount": primary_count,
            "remainingCandidateCount": len(remaining),
            "minimumAdditional": minimum_additional,
            "desiredAdditional": desired_additional,
            "refillRawCount": 0,
            "mergedRawCount": primary_count,
            "rawFloorTarget": REFILL_RAW_FLOOR,
            "rawIdealTarget": REFILL_RAW_TARGET,
            "primaryContextCounts": _context_counts(primary),
            "skipReason": None,
        })

        if primary_count >= REFILL_RAW_FLOOR:
            refill_log["skipReason"] = "primary editor already supplied normalization buffer"
            return primary
        if not remaining or minimum_additional <= 0:
            refill_log["skipReason"] = "no unused candidates available for refill"
            return primary

        counts = _context_counts(primary)
        context_text = "\n".join(
            f"- {name}: {count}" for name, count in sorted(counts.items(), key=lambda x: (x[1], x[0]))
        ) or "- none"
        headline_text = "\n".join(f"- {headline}" for headline in _model_headlines(primary)) or "- none"
        prompt = A43_REFILL_TEMPLATE.format(
            primary_count=primary_count,
            raw_floor=REFILL_RAW_FLOOR,
            raw_target=REFILL_RAW_TARGET,
            minimum_additional=minimum_additional,
            desired_additional=desired_additional,
            context_counts=context_text,
            primary_headlines=headline_text,
        )

        previous = core.EDITOR_INSTRUCTIONS
        core.EDITOR_INSTRUCTIONS = previous + "\n\n" + prompt
        refill_log["called"] = True
        try:
            refill = original_call_openai(api_key, model, remaining, run_log)
        finally:
            core.EDITOR_INSTRUCTIONS = previous

        merged = a42._merge_model_outputs(primary, refill)
        refill_log["refillRawCount"] = a42._model_output_count(refill)
        refill_log["mergedRawCount"] = a42._model_output_count(merged)
        return merged

    return call_openai_a43


def _patch_a42(a42) -> None:
    # A4.2 functions resolve these globals at runtime, so A4.3 can safely widen
    # the live-card contract and update pipeline identity without copying A4.2.
    a42.PIPELINE_VERSION = PIPELINE_VERSION
    a42.HEADLINE_TARGET_CHARS = HEADLINE_TARGET_CHARS
    a42.HEADLINE_MAX_CHARS = HEADLINE_MAX_CHARS
    a42.GLOBAL_BASE_CONTEXT_CAP = 10  # inventory cap; final A4.3 selector is 7/9.
    a42.GLOBAL_SPECIAL_EVENT_CAP = SPECIAL_EVENT_CAP
    a42.GLOBAL_SPECIAL_TOTAL_CAP = SPECIAL_TOTAL_CAP
    a42.A4_EDITOR_ADDENDUM = a42.A4_EDITOR_ADDENDUM + A43_EDITOR_ADDENDUM
    a42.apply_global_headline_budget = apply_quality_budget

    original_make_refill = a42._make_refilling_editor
    a42._make_refilling_editor = lambda core, original: _make_refilling_editor(a42, core, original)

    original_configure = a42._configure_core

    def configure_a43(core):
        original_configure(core)

        # Keep more legitimate result inventory alive until the GLOBAL selector.
        core.MAX_GENERIC_RESULT_FILLERS = 10
        core.RESULT_RELEVANCE_TARGET = 12

        # Story-driven draws should not be discarded merely because the score is tied.
        original_relevance = core._result_item_relevance

        def relevance_a43(item, league, by_id):
            relevance = original_relevance(item, league, by_id)
            if relevance.get("absoluteDrop") and relevance.get("isDraw") and _draw_has_story_hook(item):
                relevance = dict(relevance)
                relevance["strong"] = True
                relevance["absoluteDrop"] = False
                relevance["dropReason"] = None
                reasons = list(relevance.get("reasons") or [])
                reasons.append("A4.3_STORY_DRIVEN_DRAW")
                relevance["reasons"] = sorted(set(reasons))
            return relevance

        core._result_item_relevance = relevance_a43

        original_init = core.initial_run_log

        def initial_run_log_a43(generated_at, cutoff, model):
            log = original_init(generated_at, cutoff, model)
            log["pipelineVersion"] = PIPELINE_VERSION
            log["configuration"]["headlineLength"] = (
                f"live-card target <= {HEADLINE_TARGET_CHARS} chars; hard max {HEADLINE_MAX_CHARS} chars"
            )
            log["configuration"]["semanticDedupe"] = (
                "cross-candidate same-story dedupe using context, entities, action and text similarity"
            )
            log["configuration"]["coveragePolicy"] = (
                f"coverage seed + soft {SOFT_BASE_CONTEXT_CAP}/hard {HARD_BASE_CONTEXT_CAP} base-context caps; "
                "refill favors missing/underrepresented leagues before abundant routine scores"
            )
            return log

        core.initial_run_log = initial_run_log_a43

    a42._configure_core = configure_a43


def main() -> int:
    a42 = _load_a42()
    _patch_a42(a42)
    return a42.main()


if __name__ == "__main__":
    raise SystemExit(main())

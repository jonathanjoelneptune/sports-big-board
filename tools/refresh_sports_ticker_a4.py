#!/usr/bin/env python3
"""Sports Big Board A4 global-feed overlay for the proven A3.10 ticker core.

A4 intentionally leaves discovery, source parsing, FBS identity, same-game fusion,
decisive-moment enrichment, and final grounding validation in
``refresh_sports_ticker.py``.  This sidecar only changes editorial selection:

- target 32 headlines, with a preferred 30-35 total across ALL leagues/events;
- conditionally run one refill editorial pass when the first editor returns fewer than 30;
- preserve strong A3 relevance gates while allowing a few more legitimate result
  stories when the global feed would otherwise be too thin;
- enforce one global diversity budget instead of treating every league as an
  independent mini ticker;
- add clearer ADVANCEMENT / PRACTICE / QUALIFYING / EVENT_UPDATE taxonomy;
- keep legal/off-field stories only when they clear a higher significance bar.

The wrapper is deliberately additive so controller / UI work can continue in
parallel without modifying the large A3 core file.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.2-editor-refill"
DISPLAY_TITLE = "SPORTS BIG BOARD — SPORTS TICKER A4"
GLOBAL_HEADLINE_MIN = 30
GLOBAL_HEADLINE_TARGET = 32
GLOBAL_HEADLINE_MAX = 35
GLOBAL_BASE_CONTEXT_CAP = 8
GLOBAL_SPECIAL_EVENT_CAP = 4
GLOBAL_SPECIAL_TOTAL_CAP = 8
HEADLINE_TARGET_CHARS = 64
HEADLINE_MAX_CHARS = 72
LEGAL_PRIORITY_FLOOR = 75
PRACTICE_PRIORITY_FLOOR = 62

A4_TYPES = ["ADVANCEMENT", "PRACTICE", "QUALIFYING", "EVENT_UPDATE"]

A4_EDITOR_ADDENDUM = r"""

A4 GLOBAL FEED BUDGET — CRITICAL
The finished Sports Ticker is ONE continuously scrolling feed across every base
league and every Special Event. The headline budget is GLOBAL, never per league.

- Preferred final total: 30-35 headlines across EVERYTHING combined.
- Editorial target before Python's final safety/diversity pass: 32-35 headlines.
- 35 is a hard ceiling for the final feed, not a target for each section.
- Never pad with analysis, generic previews, weak rumors, or meaningless scores
  just to reach 30. If fewer than 30 genuinely useful stories exist, return fewer.
- Conversely, do not stop at 2-3 items per league when several legitimate fresh
  stories exist and the combined feed is still below target.
- Think like a national sports-news desk building one ribbon, not seven separate
  league newsletters.

GLOBAL MIX
- Major breaking news, playoffs, records, major injuries, transactions, upsets,
  standings/rank changes, and decisive result stories should beat routine scores.
- Active/postseason leagues with a legitimate fresh development should usually be
  represented, but there is no hard quota for any league.
- Avoid allowing one league or one story type to dominate simply because it has
  many similar results. Six to eight strong items from one active league can be fine
  when the overall news day supports it; a wall of routine scores is not.
- Special Events compete directly with base-league stories for the same 30-35
  global slots.

HEADLINE LENGTH — CRITICAL FOR THE ON-SCREEN RIBBON
- Headlines are display copy, not article titles. Aim for 45-64 characters.
- HARD maximum: 72 characters, including spaces and punctuation.
- Keep the key actor + development/result; move secondary context into the text field.
- Prefer compact sports wording: "Italian GP" over "Italian Grand Prix" when needed,
  "extension" over "contract extension", and avoid filler such as "in a matchup that".
- A reader should normally see the whole headline in one line, or at most two short lines.
- Do not sacrifice the score, ranking, record, or decisive fact when it is the reason
  the story is ticker-worthy.

RESULTS
- Keep the existing hard-news test. A result still needs a reason to exist.
- When the global feed is thin, a clearly useful completed result can survive even
  without a spectacular finish, especially for an active league, ranked team, major
  matchup, strong individual performance, or meaningful season context.
- Do not over-reward one lexical hook such as "walk-off". Compare the whole story
  value against records, transactions, injuries, rankings, upsets, and other sports.

TYPE TAXONOMY
- ADVANCEMENT: a player/team has already advanced to a later tournament round.
  Do not label completed advancement news as NEXT.
- PRACTICE: a meaningful development occurring specifically in a practice session.
- QUALIFYING: qualifying result/grid/position news.
- EVENT_UPDATE: a material competition-weekend/tournament update that is real news
  but is not itself a completed RESULT, PRACTICE, or QUALIFYING item.
- NEXT remains future-looking only.

LEGAL / OFF-FIELD
Legal or off-field stories involving sports figures may appear, but the threshold is
higher than ordinary competitive news. Select them only when the development itself
is materially significant and worthy of a national sports ticker. Routine procedural
updates should lose to strong on-field/transaction/injury stories.
"""


A4_REFILL_ADDENDUM = r"""
A4.2 CONDITIONAL REFILL PASS — CRITICAL
This is a SECOND editorial pass. Every candidate in this packet was omitted from the
first pass. Do not repeat or reconsider first-pass stories; they are not in this packet.

The continuous ribbon is still under its 30-headline preferred floor. Build ADDITIONAL
headlines from the best remaining candidates.

- Return AT LEAST {minimum_additional} additional headlines if that many candidates
  pass the hard-news test.
- Ideally return up to {desired_additional} additional headlines so Python has enough
  inventory to survive final relevance/diversity checks and land near 30-35.
- In this refill pass, a completed, grounded result from an ACTIVE league is useful
  ticker inventory even when it is not extraordinary. Prefer ranked-team NCAAF
  results, one-run/extra-inning MLB results, notable soccer results, and other clear
  completed outcomes over analysis or previews.
- A4.2 overrides the older five-ordinary-result editorial cap when the global ribbon
  is underfilled. Up to eight useful RESULT items from one active league are allowed.
- Still reject analysis, fantasy advice, opinion, weak rumors, generic previews,
  duplicate stories, and ambiguous/unverified claims.
- Keep headline copy at 45-64 characters when possible; 72 characters remains the
  absolute maximum.
"""


def _load_core():
    core_path = Path(__file__).with_name("refresh_sports_ticker.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a3_core", core_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A3 ticker core from {core_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _age(item: dict[str, Any]) -> float:
    value = item.get("ageHours")
    try:
        return float(value) if value is not None else 24.0
    except Exception:
        return 24.0


def _compact_headline(value: Any) -> str:
    """Keep ribbon headlines to two short lines at most.

    The model is schema-constrained to 72 characters, but A3 post-processing can
    strengthen a result headline after model validation. This deterministic guard
    catches those repaired headlines without changing the grounded story itself.
    """
    headline = " ".join(str(value or "").split()).strip()
    if len(headline) <= HEADLINE_TARGET_CHARS:
        return headline

    replacements = [
        ("Italian Grand Prix", "Italian GP"),
        ("United States Grand Prix", "U.S. GP"),
        ("contract extension", "extension"),
        ("three-place grid penalty", "3-place grid penalty"),
        ("first career pole position", "first career pole"),
        ("first career pole", "first pole"),
        ("defeated", "beat"),
        ("victory over", "win over"),
    ]
    for old, new in replacements:
        headline = headline.replace(old, new)
        if len(headline) <= HEADLINE_TARGET_CHARS:
            return headline

    # Headlines between target and hard max are acceptable as two-line copy.
    if len(headline) <= HEADLINE_MAX_CHARS:
        return headline

    # Final safety net: shorten at a word boundary and mark the omission. The
    # complete supporting detail remains in item["text"].
    return textwrap.shorten(
        headline, width=HEADLINE_MAX_CHARS, placeholder="…"
    )


def _model_headlines_by_candidate(model_output: dict[str, Any]) -> dict[str, str]:
    """Map each selected candidate id to the editor's compact pre-repair headline."""
    mapping: dict[str, str] = {}

    def take(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            headline = " ".join(str(item.get("headline") or "").split()).strip()
            if not headline:
                continue
            for cid in item.get("candidateIds", []):
                if isinstance(cid, str) and cid and cid not in mapping:
                    mapping[cid] = headline

    leagues = model_output.get("leagues", {})
    if isinstance(leagues, dict):
        for group in leagues.values():
            if isinstance(group, dict):
                take(group.get("items"))
    elif isinstance(leagues, list):
        for group in leagues:
            if isinstance(group, dict):
                take(group.get("items"))

    events = model_output.get("specialEvents", [])
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                take(event.get("items"))
    return mapping


def _restore_compact_model_headlines(
    normalized: dict[str, Any],
    model_output: dict[str, Any],
    run_log: dict[str, Any] | None = None,
) -> None:
    """Prefer a compact editor headline if A3's punch repair expanded it too far."""
    mapping = _model_headlines_by_candidate(model_output)
    restores = None
    if run_log is not None:
        restores = run_log.setdefault("pipeline", {}).setdefault("headlineRestores", [])

    rows = _flatten(normalized)
    for row in rows:
        item = row["item"]
        current = " ".join(str(item.get("headline") or "").split()).strip()
        if len(current) <= HEADLINE_MAX_CHARS:
            continue

        compact = ""
        for cid in item.get("candidateIds", []):
            candidate_headline = mapping.get(cid, "")
            if candidate_headline and len(candidate_headline) <= HEADLINE_MAX_CHARS:
                compact = candidate_headline
                break
        if not compact:
            continue

        item["headline"] = compact
        if restores is not None:
            restores.append({
                "context": row.get("context"),
                "expanded": current,
                "restored": compact,
                "expandedChars": len(current),
                "restoredChars": len(compact),
                "reason": "A3 post-editor punch repair exceeded ribbon hard max",
            })


def _repair_headline_lengths(
    rows: list[dict[str, Any]],
    run_log: dict[str, Any] | None = None,
) -> None:
    repairs = None
    if run_log is not None:
        repairs = run_log.setdefault("pipeline", {}).setdefault("headlineRepairs", [])
    for row in rows:
        item = row["item"]
        original = str(item.get("headline") or "")
        repaired = _compact_headline(original)
        if repaired != original:
            item["headline"] = repaired
            if repairs is not None:
                repairs.append({
                    "context": row.get("context"),
                    "original": original,
                    "repaired": repaired,
                    "originalChars": len(original),
                    "repairedChars": len(repaired),
                    "maxChars": HEADLINE_MAX_CHARS,
                })


def _editorial_score(row: dict[str, Any]) -> float:
    item = row["item"]
    item_type = str(item.get("type") or "").upper()
    priority = int(item.get("priority") or 0)
    score = float(priority)

    type_bonus = {
        "BREAKING": 14,
        "PLAYOFF": 12,
        "TRADE": 9,
        "UPSET": 8,
        "RECORD": 8,
        "RECORD_CHASE": 7,
        "INJURY": 7,
        "SIGNING": 6,
        "CONTRACT": 5,
        "MILESTONE": 6,
        "RANKING": 6,
        "STANDINGS": 6,
        "ADVANCEMENT": 6,
        "QUALIFYING": 3,
        "EVENT_UPDATE": 2,
        "PRACTICE": -1,
        "RESULT": 0,
        "NEXT": -3,
        "SCHEDULE": -4,
        "OTHER": -4,
    }
    score += type_bonus.get(item_type, 0)

    season_state = str(row.get("seasonState") or "").lower()
    if season_state == "postseason":
        score += 5
    elif season_state == "active":
        score += 3
    elif season_state == "preseason":
        score -= 1
    elif season_state == "offseason":
        score -= 2

    # Small freshness tiebreaker. Importance still dominates recency.
    score += max(0.0, 3.0 - (_age(item) / 8.0))
    return score


def _flatten(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in normalized.get("leagues", []):
        league = str(group.get("league") or "")
        season_state = str(group.get("seasonState") or "")
        for item in group.get("items", []):
            rows.append({
                "kind": "league",
                "context": league,
                "league": league,
                "seasonState": season_state,
                "item": item,
            })

    for event in normalized.get("specialEvents", []):
        name = str(event.get("name") or "")
        sport = str(event.get("sport") or "")
        for item in event.get("items", []):
            rows.append({
                "kind": "special",
                "context": name,
                "event": name,
                "sport": sport,
                "seasonState": "special",
                "item": item,
            })
    return rows


def _eligible(row: dict[str, Any]) -> tuple[bool, str | None]:
    item = row["item"]
    item_type = str(item.get("type") or "").upper()
    priority = int(item.get("priority") or 0)
    if item_type == "LEGAL" and priority < LEGAL_PRIORITY_FLOOR:
        return False, f"LEGAL below A4 significance floor {LEGAL_PRIORITY_FLOOR}"
    if item_type == "PRACTICE" and priority < PRACTICE_PRIORITY_FLOOR:
        return False, f"PRACTICE below A4 significance floor {PRACTICE_PRIORITY_FLOOR}"
    return True, None


def _select_with_caps(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    base_counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}
    special_total = 0

    for row in rows:
        if len(selected) >= limit:
            break
        if row["kind"] == "league":
            context = row["context"]
            if base_counts.get(context, 0) >= GLOBAL_BASE_CONTEXT_CAP:
                continue
            base_counts[context] = base_counts.get(context, 0) + 1
        else:
            context = row["context"]
            if special_total >= GLOBAL_SPECIAL_TOTAL_CAP:
                continue
            if event_counts.get(context, 0) >= GLOBAL_SPECIAL_EVENT_CAP:
                continue
            event_counts[context] = event_counts.get(context, 0) + 1
            special_total += 1
        selected.append(row)
    return selected


def apply_global_headline_budget(
    normalized: dict[str, Any],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply one deterministic 30-35 headline budget across all sections.

    The editor is asked for 32-35 legitimate stories. This pass then removes
    low-significance legal/practice items, preserves diversity, caps the final
    feed at 35, and only relaxes context caps when that is necessary to approach
    the 30-headline preferred floor. It never manufactures filler copy.
    """
    rows = _flatten(normalized)
    _repair_headline_lengths(rows, run_log)
    budget_log = None
    if run_log is not None:
        budget_log = run_log.setdefault("pipeline", {}).setdefault(
            "globalHeadlineBudget",
            {
                "min": GLOBAL_HEADLINE_MIN,
                "target": GLOBAL_HEADLINE_TARGET,
                "max": GLOBAL_HEADLINE_MAX,
                "inputCount": 0,
                "eligibleCount": 0,
                "selectedCount": 0,
                "underfilled": False,
                "dropped": [],
                "selected": [],
            },
        )
        budget_log["inputCount"] = len(rows)

    eligible_rows: list[dict[str, Any]] = []
    for row in rows:
        ok, reason = _eligible(row)
        if ok:
            row["score"] = _editorial_score(row)
            eligible_rows.append(row)
        elif budget_log is not None:
            budget_log["dropped"].append({
                "context": row["context"],
                "headline": row["item"].get("headline"),
                "reason": reason,
            })

    eligible_rows.sort(
        key=lambda r: (
            -float(r["score"]),
            -int(r["item"].get("priority") or 0),
            _age(r["item"]),
            str(r["item"].get("headline") or ""),
        )
    )
    if budget_log is not None:
        budget_log["eligibleCount"] = len(eligible_rows)

    # First pass: globally diverse target feed.
    selected = _select_with_caps(eligible_rows, min(GLOBAL_HEADLINE_TARGET, GLOBAL_HEADLINE_MAX))
    selected_ids = {id(r["item"]) for r in selected}

    # Always allow truly major remaining stories to compete for the extra slots
    # above the 32-headline target, while still respecting the hard 35 ceiling.
    for row in eligible_rows:
        if len(selected) >= GLOBAL_HEADLINE_MAX:
            break
        if id(row["item"]) in selected_ids:
            continue
        if int(row["item"].get("priority") or 0) >= 88:
            selected.append(row)
            selected_ids.add(id(row["item"]))

    # If diversity caps leave us short of the preferred 30, relax the caps but
    # only with stories the model already selected and A3 already validated.
    if len(selected) < GLOBAL_HEADLINE_MIN:
        selected_special = sum(1 for row in selected if row["kind"] == "special")
        selected_event_counts: dict[str, int] = {}
        for row in selected:
            if row["kind"] == "special":
                selected_event_counts[row["context"]] = selected_event_counts.get(row["context"], 0) + 1

        for row in eligible_rows:
            if len(selected) >= min(GLOBAL_HEADLINE_MIN, GLOBAL_HEADLINE_MAX):
                break
            if id(row["item"]) in selected_ids:
                continue
            # The floor-relaxation is allowed to deepen a strong base league,
            # but Special Events remain globally bounded so one tournament or
            # race weekend cannot take over the ribbon.
            if row["kind"] == "special":
                if selected_special >= GLOBAL_SPECIAL_TOTAL_CAP:
                    continue
                if selected_event_counts.get(row["context"], 0) >= GLOBAL_SPECIAL_EVENT_CAP:
                    continue
                selected_special += 1
                selected_event_counts[row["context"]] = selected_event_counts.get(row["context"], 0) + 1
            selected.append(row)
            selected_ids.add(id(row["item"]))

    # If the first pass somehow exceeded 35 due to future edits, enforce the hard cap.
    selected = sorted(
        selected,
        key=lambda r: (
            -float(r.get("score", _editorial_score(r))),
            -int(r["item"].get("priority") or 0),
            _age(r["item"]),
        ),
    )[:GLOBAL_HEADLINE_MAX]
    selected_ids = {id(r["item"]) for r in selected}

    # Global ribbon order is stored additively on each item. Existing consumers
    # that only understand the grouped A3 shape can ignore this field.
    for feed_rank, row in enumerate(selected, 1):
        row["item"]["feedRank"] = feed_rank

    # Rebuild grouped output without changing the established league/event shape.
    for group in normalized.get("leagues", []):
        kept = [item for item in group.get("items", []) if id(item) in selected_ids]
        kept.sort(key=lambda item: int(item.get("feedRank") or 999))
        for rank, item in enumerate(kept, 1):
            item["rank"] = rank
        group["items"] = kept

    rebuilt_events = []
    for event in normalized.get("specialEvents", []):
        kept = [item for item in event.get("items", []) if id(item) in selected_ids]
        kept.sort(key=lambda item: int(item.get("feedRank") or 999))
        for rank, item in enumerate(kept, 1):
            item["rank"] = rank
        if kept:
            event["items"] = kept
            rebuilt_events.append(event)
    normalized["specialEvents"] = rebuilt_events

    if budget_log is not None:
        budget_log["selectedCount"] = len(selected)
        budget_log["underfilled"] = len(selected) < GLOBAL_HEADLINE_MIN
        budget_log["selected"] = [
            {
                "feedRank": int(row["item"].get("feedRank") or 0),
                "context": row["context"],
                "type": row["item"].get("type"),
                "priority": row["item"].get("priority"),
                "headline": row["item"].get("headline"),
                "score": round(float(row.get("score", _editorial_score(row))), 2),
            }
            for row in sorted(selected, key=lambda r: int(r["item"].get("feedRank") or 999))
        ]
        for row in eligible_rows:
            if id(row["item"]) not in selected_ids:
                budget_log["dropped"].append({
                    "context": row["context"],
                    "headline": row["item"].get("headline"),
                    "reason": "outside A4 global 35-headline/diversity budget",
                })

    return normalized


def _headline_count(dataset: dict[str, Any]) -> int:
    return sum(len(g.get("items", [])) for g in dataset.get("leagues", [])) + sum(
        len(e.get("items", [])) for e in dataset.get("specialEvents", [])
    )


def _model_output_count(model_output: dict[str, Any]) -> int:
    total = 0
    leagues = model_output.get("leagues", {})
    if isinstance(leagues, dict):
        for group in leagues.values():
            if isinstance(group, dict) and isinstance(group.get("items"), list):
                total += len(group["items"])
    elif isinstance(leagues, list):
        for group in leagues:
            if isinstance(group, dict) and isinstance(group.get("items"), list):
                total += len(group["items"])
    for event in model_output.get("specialEvents", []) if isinstance(model_output.get("specialEvents"), list) else []:
        if isinstance(event, dict) and isinstance(event.get("items"), list):
            total += len(event["items"])
    return total


def _selected_candidate_ids(model_output: dict[str, Any]) -> set[str]:
    selected: set[str] = set()

    def take(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            for cid in item.get("candidateIds", []):
                if isinstance(cid, str) and cid:
                    selected.add(cid)

    leagues = model_output.get("leagues", {})
    if isinstance(leagues, dict):
        for group in leagues.values():
            if isinstance(group, dict):
                take(group.get("items"))
    elif isinstance(leagues, list):
        for group in leagues:
            if isinstance(group, dict):
                take(group.get("items"))

    events = model_output.get("specialEvents", [])
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                take(event.get("items"))
    return selected


def _merge_model_outputs(primary: dict[str, Any], refill: dict[str, Any]) -> dict[str, Any]:
    """Merge a refill response into the first editor response without duplicates."""
    merged = json.loads(json.dumps(primary))
    merged_leagues = merged.setdefault("leagues", {})
    refill_leagues = refill.get("leagues", {}) if isinstance(refill, dict) else {}

    if isinstance(merged_leagues, dict) and isinstance(refill_leagues, dict):
        for league, refill_group in refill_leagues.items():
            if not isinstance(refill_group, dict):
                continue
            dst_group = merged_leagues.setdefault(league, {"items": []})
            if not isinstance(dst_group, dict):
                continue
            dst_items = dst_group.setdefault("items", [])
            if not isinstance(dst_items, list):
                dst_items = []
                dst_group["items"] = dst_items
            existing_ids = {
                cid
                for item in dst_items if isinstance(item, dict)
                for cid in item.get("candidateIds", [])
                if isinstance(cid, str)
            }
            for item in refill_group.get("items", []):
                if not isinstance(item, dict):
                    continue
                ids = {
                    cid for cid in item.get("candidateIds", [])
                    if isinstance(cid, str)
                }
                if ids and ids & existing_ids:
                    continue
                dst_items.append(item)
                existing_ids.update(ids)

    merged_events = merged.setdefault("specialEvents", [])
    if not isinstance(merged_events, list):
        merged_events = []
        merged["specialEvents"] = merged_events

    event_index: dict[tuple[str, str], dict[str, Any]] = {}
    for event in merged_events:
        if isinstance(event, dict):
            key = (
                str(event.get("name") or "").strip().lower(),
                str(event.get("sport") or "").strip().lower(),
            )
            event_index[key] = event

    refill_events = refill.get("specialEvents", []) if isinstance(refill, dict) else []
    if isinstance(refill_events, list):
        for event in refill_events:
            if not isinstance(event, dict):
                continue
            key = (
                str(event.get("name") or "").strip().lower(),
                str(event.get("sport") or "").strip().lower(),
            )
            dst = event_index.get(key)
            if dst is None:
                merged_events.append(event)
                event_index[key] = event
                continue
            dst_items = dst.setdefault("items", [])
            if not isinstance(dst_items, list):
                dst_items = []
                dst["items"] = dst_items
            existing_ids = {
                cid
                for item in dst_items if isinstance(item, dict)
                for cid in item.get("candidateIds", [])
                if isinstance(cid, str)
            }
            for item in event.get("items", []):
                if not isinstance(item, dict):
                    continue
                ids = {
                    cid for cid in item.get("candidateIds", [])
                    if isinstance(cid, str)
                }
                if ids and ids & existing_ids:
                    continue
                dst_items.append(item)
                existing_ids.update(ids)
    return merged


def _make_refilling_editor(core, original_call_openai):
    """Wrap the existing single editor call with one bounded underfill refill pass."""
    def call_openai_a42(api_key, model, candidates, run_log):
        primary = original_call_openai(api_key, model, candidates, run_log)
        primary_count = _model_output_count(primary)
        refill_log = run_log.setdefault("pipeline", {}).setdefault(
            "editorRefill",
            {
                "called": False,
                "primaryCount": primary_count,
                "remainingCandidateCount": 0,
                "minimumAdditional": 0,
                "desiredAdditional": 0,
                "refillRawCount": 0,
                "mergedRawCount": primary_count,
                "skipReason": None,
            },
        )
        refill_log["primaryCount"] = primary_count

        if primary_count >= GLOBAL_HEADLINE_MIN:
            refill_log["skipReason"] = "primary editor already met 30-headline preferred floor"
            return primary

        used_ids = _selected_candidate_ids(primary)
        remaining = [
            candidate for candidate in candidates
            if candidate.get("candidateId") not in used_ids
        ]
        refill_log["remainingCandidateCount"] = len(remaining)
        if not remaining:
            refill_log["skipReason"] = "no unused model candidates remain"
            return primary

        minimum_additional = min(
            max(0, GLOBAL_HEADLINE_MIN - primary_count),
            len(remaining),
        )
        desired_additional = min(
            max(0, GLOBAL_HEADLINE_MAX - primary_count),
            len(remaining),
        )
        if minimum_additional <= 0:
            refill_log["skipReason"] = "no additional headlines required"
            return primary

        refill_log.update({
            "called": True,
            "minimumAdditional": minimum_additional,
            "desiredAdditional": desired_additional,
            "skipReason": None,
        })

        previous_instructions = core.EDITOR_INSTRUCTIONS
        refill_instructions = A4_REFILL_ADDENDUM.format(
            minimum_additional=minimum_additional,
            desired_additional=desired_additional,
        )
        core.EDITOR_INSTRUCTIONS = previous_instructions + "\n\n" + refill_instructions
        try:
            refill = original_call_openai(
                api_key,
                model,
                remaining,
                run_log,
            )
        finally:
            core.EDITOR_INSTRUCTIONS = previous_instructions

        refill_count = _model_output_count(refill)
        merged = _merge_model_outputs(primary, refill)
        refill_log["refillRawCount"] = refill_count
        refill_log["mergedRawCount"] = _model_output_count(merged)
        return merged

    return call_openai_a42


def _configure_core(core) -> None:
    # Broaden A3's per-league ordinary-result filler allowance just enough for
    # the GLOBAL feed to reach useful density. The A3 hard relevance checks stay.
    core.MAX_GENERIC_RESULT_FILLERS = 8
    core.RESULT_RELEVANCE_TARGET = 10

    # Extend taxonomy in-place so the strict JSON schema and runtime validator
    # both see the same values.
    for item_type in A4_TYPES:
        if item_type not in core.ALLOWED_TYPES:
            core.ALLOWED_TYPES.append(item_type)

    # Ribbon copy must stay compact even before the deterministic post-pass.
    core.MODEL_ITEM_SCHEMA["properties"]["headline"]["maxLength"] = HEADLINE_MAX_CHARS
    core.MODEL_SCHEMA["$defs"]["item"]["properties"]["headline"]["maxLength"] = HEADLINE_MAX_CHARS
    core.PRIORITY_DEFAULTS.update({
        "ADVANCEMENT": 72,
        "PRACTICE": 62,
        "QUALIFYING": 68,
        "EVENT_UPDATE": 66,
    })
    core.PRIORITY_BANDS.update({
        "ADVANCEMENT": (60, 88),
        "PRACTICE": (55, 78),
        "QUALIFYING": (58, 84),
        "EVENT_UPDATE": (55, 82),
    })

    core.EDITOR_INSTRUCTIONS = core.EDITOR_INSTRUCTIONS + A4_EDITOR_ADDENDUM

    original_initial_run_log = core.initial_run_log
    original_call_openai = core.call_openai
    original_curate_final_items = core.curate_final_items
    original_normalize = core.normalize_model_output
    original_semantic = core.semantic_ticker
    original_render = core.render_text
    original_atomic_write = core.atomic_write

    def curate_final_items_a42(items, context, run_log):
        """A4.2 permits deeper result coverage only because the budget is global."""
        ordered = sorted(
            items,
            key=lambda x: (
                -int(x["priority"]),
                float(x["ageHours"]) if x.get("ageHours") is not None else 23.9,
            ),
        )
        selected = []
        result_count = 0
        preview_count = 0
        other_count = 0
        for item in ordered:
            kind = item["type"]
            if kind == "RESULT" and result_count >= GLOBAL_BASE_CONTEXT_CAP:
                run_log["pipeline"]["finalDrops"].append({
                    "context": context,
                    "headline": item["headline"],
                    "reason": f"A4.2 RESULT cap {GLOBAL_BASE_CONTEXT_CAP}",
                })
                continue
            if kind == "RESULT":
                result_count += 1
            if kind in {"NEXT", "SCHEDULE"} and preview_count >= 2:
                run_log["pipeline"]["finalDrops"].append({
                    "context": context,
                    "headline": item["headline"],
                    "reason": "NEXT/SCHEDULE cap 2",
                })
                continue
            if kind in {"NEXT", "SCHEDULE"}:
                preview_count += 1
            if kind == "OTHER" and other_count >= 1:
                run_log["pipeline"]["finalDrops"].append({
                    "context": context,
                    "headline": item["headline"],
                    "reason": "OTHER cap 1",
                })
                continue
            if kind == "OTHER":
                other_count += 1
            selected.append(item)
            if len(selected) == 10:
                break
        for rank, item in enumerate(selected, 1):
            item["rank"] = rank
        return selected

    def initial_run_log_a4(generated_at, cutoff, model):
        log = original_initial_run_log(generated_at, cutoff, model)
        log["pipelineVersion"] = PIPELINE_VERSION
        log["runId"] = "a4-" + generated_at.strftime("%Y%m%dT%H%M%SZ")
        log["configuration"]["globalHeadlineBudget"] = (
            f"preferred {GLOBAL_HEADLINE_MIN}-{GLOBAL_HEADLINE_MAX} total headlines; "
            f"editor target {GLOBAL_HEADLINE_TARGET}-{GLOBAL_HEADLINE_MAX}; global, not per league"
        )
        log["configuration"]["resultRelevanceGate"] = (
            "A3 strong-story gate retained; up to eight ordinary result fillers per active league "
            "only when needed to support the global 30-35 ribbon budget"
        )
        log["configuration"]["legalStoryPolicy"] = (
            f"off-field/legal stories must clear priority {LEGAL_PRIORITY_FLOOR} after normalization"
        )
        log["configuration"]["headlineLength"] = (
            f"target <= {HEADLINE_TARGET_CHARS} chars; hard max {HEADLINE_MAX_CHARS} chars"
        )
        log["pipeline"]["headlineRepairs"] = []
        log["pipeline"]["headlineRestores"] = []
        log["pipeline"]["editorRefill"] = {
            "called": False,
            "primaryCount": 0,
            "remainingCandidateCount": 0,
            "minimumAdditional": 0,
            "desiredAdditional": 0,
            "refillRawCount": 0,
            "mergedRawCount": 0,
            "skipReason": None,
        }
        log["pipeline"]["globalHeadlineBudget"] = {
            "min": GLOBAL_HEADLINE_MIN,
            "target": GLOBAL_HEADLINE_TARGET,
            "max": GLOBAL_HEADLINE_MAX,
            "inputCount": 0,
            "eligibleCount": 0,
            "selectedCount": 0,
            "underfilled": False,
            "dropped": [],
            "selected": [],
        }
        return log

    def normalize_a4(model_output, candidates, generated_at, run_log):
        normalized = original_normalize(model_output, candidates, generated_at, run_log)
        _restore_compact_model_headlines(normalized, model_output, run_log)
        return apply_global_headline_budget(normalized, run_log)

    def semantic_a4(dataset):
        semantic = original_semantic(dataset)
        # Treat the A4 overlay as the semantic pipeline identity even though the
        # underlying A3 main() still constructs its internal dataset literal.
        semantic["pipelineVersion"] = PIPELINE_VERSION
        return semantic

    def render_a4(dataset):
        rendered = original_render(dataset)
        rendered = rendered.replace(
            "SPORTS BIG BOARD — SPORTS TICKER A3",
            DISPLAY_TITLE,
            1,
        )
        count = _headline_count(dataset)
        marker = f"Global headline budget: {count}/{GLOBAL_HEADLINE_MIN}-{GLOBAL_HEADLINE_MAX} total\n"
        headline_marker = (
            f"Headline length: target <= {HEADLINE_TARGET_CHARS} chars; "
            f"hard max {HEADLINE_MAX_CHARS}\n"
        )
        lines = rendered.splitlines(keepends=True)
        insert_at = 2 if len(lines) >= 2 else len(lines)
        lines.insert(insert_at, marker)
        lines.insert(insert_at + 1, headline_marker)
        return "".join(lines)

    def atomic_write_a4(path: Path, content: str):
        # Rewrite only sidecar output metadata; data shape stays backward-compatible.
        if path.name == "sports-ticker.json":
            try:
                payload = json.loads(content)
                payload["pipelineVersion"] = PIPELINE_VERSION
                payload["discoveryMode"] = (
                    str(payload.get("discoveryMode") or "")
                    + "; A4 global 30-35 headline budget + conditional editor refill + compact-headline diversity selection"
                ).strip("; ")
                payload["headlineCount"] = _headline_count(payload)
                payload["headlineTargetChars"] = HEADLINE_TARGET_CHARS
                payload["headlineMaxChars"] = HEADLINE_MAX_CHARS
                content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            except Exception:
                pass
        elif path.name == "sports-ticker.txt":
            content = content.replace("SPORTS BIG BOARD — SPORTS TICKER A3", DISPLAY_TITLE, 1)
        original_atomic_write(path, content)

    core.initial_run_log = initial_run_log_a4
    core.call_openai = _make_refilling_editor(core, original_call_openai)
    core.curate_final_items = curate_final_items_a42
    core.normalize_model_output = normalize_a4
    core.semantic_ticker = semantic_a4
    core.render_text = render_a4
    core.atomic_write = atomic_write_a4


def _migrate_existing_output(data_dir: Path) -> None:
    """Make pipeline identity visible even if the first A4 run has no semantic delta."""
    json_path = data_dir / "sports-ticker.json"
    txt_path = data_dir / "sports-ticker.txt"
    if json_path.exists():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            changed = False
            if payload.get("pipelineVersion") != PIPELINE_VERSION:
                payload["pipelineVersion"] = PIPELINE_VERSION
                changed = True
            count = _headline_count(payload)
            if payload.get("headlineCount") != count:
                payload["headlineCount"] = count
                changed = True
            if payload.get("headlineTargetChars") != HEADLINE_TARGET_CHARS:
                payload["headlineTargetChars"] = HEADLINE_TARGET_CHARS
                changed = True
            if payload.get("headlineMaxChars") != HEADLINE_MAX_CHARS:
                payload["headlineMaxChars"] = HEADLINE_MAX_CHARS
                changed = True
            if changed:
                json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            pass
    if txt_path.exists():
        text = txt_path.read_text(encoding="utf-8")
        updated = text.replace("SPORTS BIG BOARD — SPORTS TICKER A3", DISPLAY_TITLE, 1)
        if updated != text:
            txt_path.write_text(updated, encoding="utf-8")


def _data_dir_from_argv(argv: list[str]) -> Path:
    for idx, arg in enumerate(argv):
        if arg == "--data-dir" and idx + 1 < len(argv):
            return Path(argv[idx + 1])
        if arg.startswith("--data-dir="):
            return Path(arg.split("=", 1)[1])
    return Path("data")


def main() -> int:
    core = _load_core()
    _configure_core(core)

    data_dir = _data_dir_from_argv(sys.argv[1:])
    previous_path = data_dir / "sports-ticker.json"
    migrating = True
    if previous_path.exists():
        try:
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
            migrating = previous.get("pipelineVersion") != PIPELINE_VERSION
        except Exception:
            migrating = True

    # On the first execution of this A4 revision, force one editorial pass so the new global
    # budget is applied immediately even if the candidate hash has not changed.
    added_force = False
    if migrating and "--force-model" not in sys.argv:
        sys.argv.append("--force-model")
        added_force = True

    try:
        code = core.main()
    finally:
        if added_force and sys.argv and sys.argv[-1] == "--force-model":
            sys.argv.pop()

    if code == 0:
        _migrate_existing_output(data_dir)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

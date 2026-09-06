#!/usr/bin/env python3
"""Sports Big Board A4.11 tier-calibration + surface-copy hygiene overlay.

A4.11 keeps A4.10's sport-aware editorial tier architecture and makes tiering
operationally stricter: the editor must classify the development before assigning
priority, with explicit promotion requirements and tier ceilings for routine items.

It also removes non-editorial source/status fragments from user-facing copy, such
as "End of 4th quarter.", and strips leading feed dashes from otherwise good prose.

No discovery source, global budget, source depth, league cap, refill behavior,
game/event identity rule, headline length, stable launcher, or workflow change.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.11-tier-calibration-copy-hygiene"

A411_EDITOR_ADDENDUM = r"""

A4.11 TIER CALIBRATION — MANDATORY
A4.10's four editorial tiers remain authoritative. Before assigning a priority
number or selecting a story, perform this exact editorial sequence:

1. Identify the concrete development and its sport.
2. Assign Tier 1, Tier 2, Tier 3, or Tier 4 using the sport-specific A4.10 rules.
3. Assign priority ONLY inside that tier's band:
   Tier 1 = 82-95
   Tier 2 = 72-81
   Tier 3 = 60-71
   Tier 4 = omit
4. Compare the story globally against unused candidates of the same or higher tier.

DO NOT promote a story merely because it is fresh, has a famous team name, came from
ESPN, or helps fill 30 slots. Freshness determines eligibility, not importance.
The refill pass MUST use the same tier classification; it may use Tier 3 to reach the
preferred 30-story floor but must not relabel Tier 3 as Tier 2.

PROMOTION REQUIREMENTS / PRIORITY CEILINGS

INJURIES
- "Major star injury" is Tier 1 only when the source establishes meaningful severity
  or competitive consequence: season-ending/long-term absence, surgery, structural
  injury, hospitalization/emergency concern, or a major playoff/title consequence.
- A marquee player missing games with day-to-day soreness but no IL/long-term diagnosis
  is normally Tier 2, not Tier 1.
- A routine 10/15-day IL move, soreness/strain update, or diagnostic follow-up for a
  non-marquee player is Tier 3 (priority <=71) unless the source explicitly establishes
  unusual competitive significance.
- Do not promote a routine injury because the player is simply a starter.

RESULTS
- A generic final score without a record, upset, decisive finish, standout performance,
  rivalry, or standings consequence is Tier 3.
- "Close game" alone is not enough for Tier 2. Identify the hero/decisive play, comeback,
  overtime/extra-inning drama, or standings implication.
- A late/OT/extra-inning finish with a real decisive hook is Tier 2; exceptional/historic
  versions can be Tier 1.

PRACTICE / QUALIFYING
- Routine practice contact, pace order, quote, or minor incident with no damage,
  penalty, missed running, grid effect, or championship consequence is Tier 3.
- Practice becomes Tier 2 only when it materially changes the competitive weekend.
- Pole position, a major qualifying upset, or a penalty with significant grid/race
  consequence can be Tier 1/Tier 2 per A4.10.

TRANSACTIONS / CONTRACTS / ADMINISTRATION
- A routine roster/depth move or ordinary extension is Tier 3 unless the player/contract
  has clear competitive significance.
- Major starter/star signings, major trades, major coaching/executive moves, or unusually
  consequential contracts can be Tier 2 or Tier 1 according to impact.

STREAKS / MILESTONES
- A label such as "first point", "unbeaten", "debut", or "milestone" does not
  automatically make a story Tier 2. Judge the actual significance.
- Historic records, age records, league records, major career marks, or exceptional
  performance milestones can be Tier 1.

GLOBAL COMPARISON
Before finalizing the ribbon, inspect the weakest selected Tier-2 and Tier-3 stories.
If an unused candidate of a higher tier exists, replace the weaker story regardless
of league/type. If two candidates are the same tier, favor the one with the stronger
competitive hook and more useful grounded context.

COPY QUALITY
- Supporting text should add information beyond the headline whenever source evidence
  supports it.
- Freshness basis must state WHAT happened and why the timestamp is valid. Never use
  bare source-state fragments such as "End of 4th quarter.", "Final.", "Full time.",
  "End of OT.", or similar status-only text as user-facing freshness copy.
"""

GENERIC_FRESHNESS_PATTERNS = (
    r"^end of (?:the )?(?:1st|2nd|3rd|4th|first|second|third|fourth) quarter\.?$",
    r"^end of (?:ot|overtime)\.?$",
    r"^end of game\.?$",
    r"^game over\.?$",
    r"^final\.?$",
    r"^full time\.?$",
    r"^full-time\.?$",
    r"^match ended\.?$",
    r"^game ended\.?$",
)


def _load_a410():
    path = Path(__file__).with_name("refresh_sports_ticker_a410.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a410", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.10 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _surface_sentence(value: Any) -> str:
    text = _clean(value)
    text = re.sub(r"^[—–-]\s*", "", text)
    return text.strip()


def _generic_freshness(value: Any) -> bool:
    text = _surface_sentence(value).lower()
    if not text:
        return True
    return any(re.fullmatch(pattern, text, flags=re.I) for pattern in GENERIC_FRESHNESS_PATTERNS)


def polish_surface_copy(
    normalized: dict[str, Any],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Remove feed prefixes and replace status-only freshness with useful copy."""
    updates: list[dict[str, Any]] = []

    def polish(items: list[dict[str, Any]], context: str) -> None:
        for item in items:
            before_text = _clean(item.get("text"))
            before_fresh = _clean(item.get("freshnessBasis"))

            clean_text = _surface_sentence(before_text)
            clean_fresh = _surface_sentence(before_fresh)

            if clean_text:
                item["text"] = clean_text

            freshness_repaired = False
            if _generic_freshness(clean_fresh):
                replacement = clean_text or _surface_sentence(item.get("headline"))
                if replacement:
                    item["freshnessBasis"] = replacement
                    freshness_repaired = True
            elif clean_fresh:
                item["freshnessBasis"] = clean_fresh

            if item.get("text") != before_text or item.get("freshnessBasis") != before_fresh:
                updates.append({
                    "context": context,
                    "headline": item.get("headline"),
                    "candidateIds": item.get("candidateIds", []),
                    "beforeText": before_text,
                    "afterText": item.get("text"),
                    "beforeFreshness": before_fresh,
                    "afterFreshness": item.get("freshnessBasis"),
                    "freshnessRepaired": freshness_repaired,
                })

    for group in normalized.get("leagues", []):
        items = group.get("items", []) if isinstance(group.get("items"), list) else []
        polish(items, _clean(group.get("league")))

    for event in normalized.get("specialEvents", []):
        items = event.get("items", []) if isinstance(event.get("items"), list) else []
        polish(items, _clean(event.get("name")))

    if run_log is not None:
        run_log.setdefault("pipeline", {})["a411SurfaceCopyPolish"] = {
            "updatedCount": len(updates),
            "updated": updates,
            "policy": "strip feed prefixes + replace status-only freshness with grounded item copy",
        }

    return normalized


def main() -> int:
    a410 = _load_a410()
    a410.PIPELINE_VERSION = PIPELINE_VERSION
    a410.A410_EDITOR_ADDENDUM = a410.A410_EDITOR_ADDENDUM + A411_EDITOR_ADDENDUM

    original_load_a49 = a410._load_a49

    def load_a49_a411():
        a49 = original_load_a49()
        a49.PIPELINE_VERSION = PIPELINE_VERSION

        original_sanitize = a49.sanitize_grounded_copy

        def sanitize_a411(a45, normalized, candidates, run_log=None):
            normalized = original_sanitize(a45, normalized, candidates, run_log)
            return polish_surface_copy(normalized, run_log)

        a49.sanitize_grounded_copy = sanitize_a411
        return a49

    a410._load_a49 = load_a49_a411
    return a410.main()


if __name__ == "__main__":
    raise SystemExit(main())

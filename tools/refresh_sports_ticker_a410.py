#!/usr/bin/env python3
"""Sports Big Board A4.10 sport-aware editorial tiers + same-outcome dedupe.

A4.10 keeps the established 30-35 Sports Ticker architecture frozen. It replaces
the idea of content-type hard caps with a sport-aware editorial tier system that
the editor applies to BOTH its primary and refill passes.

The tiers answer the real editorial question: "How valuable is THIS development?"
rather than "How many injuries/results have we already used?" Seven independent
elite finishes can all qualify; seven routine injury updates should not.

A4.10 also retains one deterministic correctness rule learned from A4.9: multiple
articles reporting the exact same Special Event competitive outcome occupy one slot.

No YAML/current-launcher change, discovery-source change, global-budget change,
league-cap change, identity-policy change, or headline-length change.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.10-sport-aware-editorial-tiers"

A410_EDITOR_ADDENDUM = r"""

A4.10 SPORT-AWARE EDITORIAL TIER SYSTEM — CRITICAL
These rules apply to BOTH the primary editor pass and the conditional refill pass.
They supersede any impulse to use a fixed quota for injuries, scores, transactions,
or another story type.

The Sports Ticker has 30-35 GLOBAL slots. Judge the editorial value of each actual
development, not merely its category. Repetition is acceptable when the stories are
independently exceptional. Seven genuinely great walk-offs/upsets/records may all be
better ticker inventory than seven unrelated routine injury-list moves.

TIER 1 — MUST-COMPETE / NATIONAL-TICKER MATERIAL
Suggested priority: 82-95.
There is NO type-count penalty for independent Tier-1 stories. Select as many as
deserve to win global slots, subject only to duplicate/identity rules.
Examples across sports:
- championship/title/playoff-clinching or major standings/ranking consequences;
- major upsets, rivalry shocks, historic comebacks, overtime/extra-inning or
  last-second game winners with a real hook;
- records broken, historic milestones, extraordinary individual performances;
- major star injury, season-ending injury, surgery, major suspension;
- major trade/signing/coaching change with broad competitive significance;
- rare/decisive competitive events such as a walk-off grand slam, no-hitter,
  perfect game, buzzer-beater, title-fight finish, or major-tournament upset.

TIER 2 — STRONG SUPPORTING TICKER STORY
Suggested priority: 72-81.
These are clearly worth reading but are not automatic top-of-feed stories.
Several from one league are fine. Once roughly 4 similar Tier-2 stories from the
same league/type are already represented, prefer an equal/higher-tier story that
adds variety unless the additional story has a materially different hook.
Examples:
- meaningful one-run/extra-inning result with a standout player;
- strong shutout/goalkeeping/pitching performance;
- notable streak, first/return/debut, ranked-team result with performance context;
- meaningful contract/roster/injury update involving an important player;
- qualifying result/grid penalty, tournament advancement, or notable draw with
  a real competitive hook.

TIER 3 — LEGITIMATE FILLER / USE SPARINGLY
Suggested priority: 60-71.
Use mainly when the ribbon needs inventory to approach its 30-story preferred floor.
Generally avoid more than 1-2 similar Tier-3 stories from one league when stronger
unused candidates exist.
Examples:
- routine final scores without a standout/standings/record/decisive hook;
- routine IL/day-to-day injury update for a non-marquee player;
- minor transaction/depth-chart move;
- ordinary early-round advancement by a favorite;
- routine draw, practice note, or preseason result without broader significance.

TIER 4 — OMIT
Do not use these to pad the ribbon:
- analysis/opinion/fantasy content, generic previews, betting content;
- weak rumors or procedural off-field updates without sports consequences;
- duplicate article angles on the same development;
- routine quotes/plans, generic practice chatter, administrative notes;
- a score with no meaningful hook when stronger candidates remain.

SPORT-SPECIFIC TIER GUIDANCE

MLB
Tier 1: walk-offs with a strong hook; grand slams that decide/swing games; no-hitters,
perfect games, cycles, record/milestone performances, major playoff-race movement,
historic streaks, major trades/signings, major star injuries.
Tier 2: one-run/extra-inning games with a clear hero; shutouts with notable pitcher
context; multi-HR/4+ RBI-type standout games; meaningful division/wild-card movement;
important debuts/returns.
Tier 3: ordinary finals, routine IL moves, minor roster transactions, generic shutouts
or homers without broader significance.

NFL
Tier 1: major upset, OT/last-play finish, record performance, playoff/division impact,
major star injury, major trade/signing, coaching dismissal/hire.
Tier 2: strong individual game, meaningful comeback, notable streak, important return
or suspension, roster move involving a major starter.
Tier 3: routine preseason result, depth-chart move, ordinary injury/status update.

NBA
Tier 1: playoff/title impact, buzzer-beater/OT classic, record or historic scoring game,
major trade/signing, major star injury.
Tier 2: standout scoring/triple-double-type performance, major comeback, meaningful
standings streak, notable return/suspension.
Tier 3: routine regular-season result, minor injury, bench/rotation transaction.

NHL
Tier 1: playoff/title impact, OT winner in major game, hat trick/record, exceptional
goalie milestone/shutout, major trade/signing/star injury.
Tier 2: notable comeback, strong goalie/shutout performance, meaningful streak or
standings move, important contract/return.
Tier 3: routine result, minor roster move/injury.

EPL / MLS / SOCCER
Tier 1: title/relegation/qualification consequence, major upset, dramatic late winner,
multi-goal comeback, hat trick/record, major transfer/manager change, star injury.
Tier 2: meaningful unbeaten/winless streak, first/record goal, strong goalkeeper story,
late equalizer with consequence, notable derby/result.
Tier 3: routine draw/result, ordinary first-team injury, minor transfer/admin item.

NCAAF
Tier 1: ranked upset, rivalry shock, OT/last-second finish, record performance,
playoff/ranking consequence, major coaching news.
Tier 2: ranked-team result with a standout performance, major FBS milestone,
five-TD/huge-yardage-type performance, meaningful streak, important injury.
Tier 3: routine ranked blowout without a special performance, ordinary unranked result,
minor injury/roster news.

TENNIS / GRAND SLAMS
Tier 1: seeded/top-player upset, major comeback, five-set classic, semifinal/final/title
result, record/milestone, star withdrawal/injury.
Tier 2: meaningful round-of-16/quarterfinal advancement, notable straight-set dominance,
high-profile matchup set up, seeded player survival.
Tier 3: routine early-round advancement by a favorite.

FORMULA 1
Tier 1: race win/podium shock, pole position, championship lead change, major crash or
penalty with race/championship consequences, record.
Tier 2: qualifying surprise, meaningful grid penalty, major practice incident that
changes the weekend, notable technical/driver development.
Tier 3: routine practice ranking, quote, or low-consequence grid note.

UFC / MMA
Tier 1: title change/vacancy, major upset, knockout/submission finish, star withdrawal
that changes the card, championship booking/cancellation.
Tier 2: important contender result, meaningful injury/discipline/card change.
Tier 3: routine matchmaking or low-impact roster news.

GOLF / MAJORS
Tier 1: major/tournament win, record round/score, major leaderboard swing late,
playoff finish, star withdrawal/injury with event consequence.
Tier 2: notable charge/collapse, ace or rare feat with competitive significance.
Tier 3: routine early-round leaderboard movement or player quote.

EDITORIAL DENSITY RULE
Do not use category quotas as a substitute for judgment.
- Tier 1 can repeat freely when each story is independently exceptional.
- Tier 2 repetition has a soft diversity cost, not a hard cap.
- Tier 3 is where repetition should be aggressively limited.
- Tier 4 never enters the ticker.
The final priority number should reflect this tiering so downstream global selection
naturally favors the strongest material.
"""

SPECIAL_OUTCOME_TYPES = {
    "QUALIFYING", "ADVANCEMENT", "RESULT", "UPSET",
}

ROUND_PATTERNS = (
    r"\bround of 128\b", r"\bround of 64\b", r"\bround of 32\b",
    r"\bround of 16\b", r"\bfourth round\b", r"\bthird round\b",
    r"\bsecond round\b", r"\bfirst round\b", r"\bquarterfinals?\b",
    r"\bsemifinals?\b", r"\bfinals?\b",
)
STOP_TOKENS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "at", "for",
    "with", "after", "as", "from", "by", "past", "over", "into", "its",
    "his", "her", "their", "grand", "prix", "gp", "open", "round",
}


def _load_a49():
    path = Path(__file__).with_name("refresh_sports_ticker_a49.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a49", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.9 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm(value: Any) -> str:
    text = _clean(value).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return " ".join(text.split())


def _blob(item: dict[str, Any]) -> str:
    entities = item.get("entities") if isinstance(item.get("entities"), list) else []
    return _norm(" ".join([
        _clean(item.get("headline")),
        _clean(item.get("text")),
        _clean(item.get("freshnessBasis")),
        " ".join(_clean(x) for x in entities if _clean(x)),
    ]))


def _entities(item: dict[str, Any]) -> set[str]:
    raw = item.get("entities") if isinstance(item.get("entities"), list) else []
    return {_norm(x) for x in raw if _norm(x)}


def _round_marker(item: dict[str, Any]) -> str:
    blob = _blob(item)
    for pattern in ROUND_PATTERNS:
        match = re.search(pattern, blob)
        if match:
            return match.group(0)
    return ""


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


def _token_set(item: dict[str, Any]) -> set[str]:
    return {
        token for token in _blob(item).split()
        if len(token) >= 3 and token not in STOP_TOKENS
    }


def _jaccard(a: dict[str, Any], b: dict[str, Any]) -> float:
    left, right = _token_set(a), _token_set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _same_special_outcome(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """High-confidence same competitive outcome inside one named Special Event."""
    ta = _clean(a.get("type")).upper()
    tb = _clean(b.get("type")).upper()
    if ta != tb or ta not in SPECIAL_OUTCOME_TYPES:
        return False
    if not (_entities(a) & _entities(b)):
        return False

    ba, bb = _blob(a), _blob(b)

    # Same driver + same pole outcome is one qualifying story even if the article
    # angle differs (e.g. career-first angle vs Russell/chess angle).
    if ta == "QUALIFYING":
        pole_a = bool(re.search(r"\bpole(?: position)?\b", ba))
        pole_b = bool(re.search(r"\bpole(?: position)?\b", bb))
        return (pole_a and pole_b) or _jaccard(a, b) >= 0.58

    # Do not collapse consecutive tennis/tournament rounds.
    if ta == "ADVANCEMENT":
        ra, rb = _round_marker(a), _round_marker(b)
        if ra and rb:
            return ra == rb and _jaccard(a, b) >= 0.28
        return _jaccard(a, b) >= 0.68

    # Result/upset duplicates normally share score and enough participant identity.
    scores_a, scores_b = _score_pairs(a), _score_pairs(b)
    if scores_a and scores_b and (scores_a & scores_b):
        return len(_entities(a) & _entities(b)) >= 2 or _jaccard(a, b) >= 0.35
    return _jaccard(a, b) >= 0.68


def _story_strength(item: dict[str, Any]) -> tuple[int, int, int]:
    priority = int(item.get("priority") or 0)
    blob = _blob(item)
    distinctive = int(any(term in blob for term in (
        "first career", "career first", "record", "historic", "championship",
    )))
    clean_angle = int("online chess" not in blob and "chess game" not in blob)
    return (priority, distinctive, clean_angle)


def collapse_special_event_outcomes(
    normalized: dict[str, Any],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    drops: list[dict[str, Any]] = []
    for event in normalized.get("specialEvents", []):
        name = _clean(event.get("name"))
        items = event.get("items", []) if isinstance(event.get("items"), list) else []
        kept: list[dict[str, Any]] = []

        for item in items:
            match_index = next(
                (idx for idx, existing in enumerate(kept) if _same_special_outcome(item, existing)),
                None,
            )
            if match_index is None:
                kept.append(item)
                continue

            existing = kept[match_index]
            item_wins = _story_strength(item) > _story_strength(existing)
            winner, loser = (item, existing) if item_wins else (existing, item)
            if item_wins:
                kept[match_index] = item
            drops.append({
                "event": name,
                "headline": loser.get("headline"),
                "candidateIds": loser.get("candidateIds", []),
                "kept": winner.get("headline"),
                "keptCandidateIds": winner.get("candidateIds", []),
                "reason": "A4.10 duplicate same-Special-Event competitive outcome",
            })
        event["items"] = kept

    if run_log is not None:
        run_log.setdefault("pipeline", {})["a410SpecialOutcomeDrops"] = drops
    return normalized


def _patch_a48(a48) -> None:
    a48.PIPELINE_VERSION = PIPELINE_VERSION
    a48.A48_EDITOR_ADDENDUM = a48.A48_EDITOR_ADDENDUM + A410_EDITOR_ADDENDUM

    original_collapse = a48.collapse_editorial_progressions

    def collapse_a410(normalized, run_log=None):
        normalized = original_collapse(normalized, run_log)
        return collapse_special_event_outcomes(normalized, run_log)

    # This remains a correctness-only deterministic pass. Editorial density/type
    # decisions are intentionally left to the tier-aware model prompt.
    a48.collapse_editorial_progressions = collapse_a410


def main() -> int:
    a49 = _load_a49()
    a49.PIPELINE_VERSION = PIPELINE_VERSION
    a49.A49_EDITOR_ADDENDUM = a49.A49_EDITOR_ADDENDUM + A410_EDITOR_ADDENDUM

    original_load_a48 = a49._load_a48

    def load_a48_a410():
        a48 = original_load_a48()
        _patch_a48(a48)
        return a48

    a49._load_a48 = load_a48_a410
    return a49.main()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Sports Big Board A4.12 explicit editorial tiers + grounded UPSET overlay.

A4.12 keeps A4.11's 30-35 global Sports Ticker architecture frozen and makes
editorial tiering auditable and enforceable:

- every model-selected item must explicitly return editorialTier 1, 2, or 3;
- priority is deterministically constrained to that tier's numeric band before
  global selection;
- a few high-confidence tier sanity ceilings prevent obvious contradictions such
  as a routine 15-day IL move being emitted as Tier 1;
- UPSET is fail-closed unless source/candidate evidence actually establishes an
  underdog/ranking/division upset;
- editorialTier is logged internally but removed from the public ticker payload.

No discovery-source, budget, refill, league-cap, source-depth, headline-length,
stable-launcher, or workflow/YAML change.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.12-explicit-tiers-grounded-upsets"

TIER_BANDS = {
    1: (82, 95),
    2: (72, 81),
    3: (60, 71),
}
VALID_TIERS = frozenset(TIER_BANDS)

A412_EDITOR_ADDENDUM = r"""

A4.12 EXPLICIT EDITORIAL TIER CONTRACT — REQUIRED
For EVERY ticker item you output, return a new integer field:
  editorialTier: 1, 2, or 3

Tier 4 stories are omitted entirely and therefore must never be returned.

Classify FIRST, then write priority:
- editorialTier 1 -> priority MUST be 82-95
- editorialTier 2 -> priority MUST be 72-81
- editorialTier 3 -> priority MUST be 60-71

Do not use priority to hide uncertainty about the tier. The tier is the editorial
judgment; priority only orders stories inside that tier.

Examples of classifications that MUST remain consistent:
- routine 10/15-day IL move without major severity -> Tier 3, never Tier 1;
- marquee player missing games with day-to-day soreness -> normally Tier 2;
- hospitalization, season-ending injury, surgery, title-changing injury -> may be Tier 1;
- consequence-free practice contact -> Tier 3;
- dramatic last-second finish may be Tier 1 even when it is NOT an upset.

UPSET LABEL — EVIDENCE REQUIRED
Use type=UPSET only when the supplied candidate evidence establishes an actual upset:
- unranked/lower-ranked team beats a ranked/higher-ranked team;
- lower seed/rank beats a clearly higher seed/rank;
- FCS/lower-division team beats FBS/higher-division opposition;
- or the SOURCE evidence explicitly establishes favorite/underdog/upset status.

Do NOT call a game an upset merely because the ending was shocking, dramatic,
controversial, a Hail Mary, overtime, or a last-second winner.
Example: a ranked favorite surviving an unranked opponent on a Hail Mary can be
Tier 1 RESULT, but it is not automatically an UPSET.
"""

SEVERE_INJURY_TERMS = (
    "season-ending", "season ending", "out for the season", "miss the season",
    "surgery", "torn acl", "acl tear", "torn achilles", "ruptured achilles",
    "rupture", "fracture", "broken ", "hospital", "hospitalized", "hospitalised",
    "emergency", "career-threatening", "career threatening",
)

SHORT_IL_RE = re.compile(r"\b(?:10|15)[- ]day (?:injured|injury) list\b|\b(?:10|15)[- ]day il\b", re.I)
DAY_TO_DAY_RE = re.compile(
    r"\bday[- ]to[- ]day\b|\bsoreness\b|\bheld out\b|\bmiss(?:es|ed|ing)?\s+\w*\s*game",
    re.I,
)

PRACTICE_CONSEQUENCE_TERMS = (
    "penalty", "grid", "damage", "crash", "missed running", "missed the session",
    "ended his session", "ended her session", "red flag", "engine", "gearbox",
    "investigation", "championship", "race ban", "medical center",
)

UPSET_SOURCE_TERMS = (
    " upset ", " upsets ", " underdog ", " favored ", " favourite ", " favorite ",
)

FCS_OVER_FBS_RE = re.compile(
    r"(?:fcs.{0,120}(?:beat|beats|defeat|defeats|over|past).{0,120}fbs|"
    r"(?:beat|beats|defeat|defeats|over|past).{0,120}fbs.{0,120}fcs)",
    re.I | re.S,
)

RANK_RE = re.compile(r"\b(?:no\.?\s*|#|seed(?:ed)?\s*)(\d{1,2})\b", re.I)


def _load_a411():
    path = Path(__file__).with_name("refresh_sports_ticker_a411.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a411", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.11 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm(value: Any) -> str:
    text = _clean(value).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9#' ]+", " ", text)
    return " ".join(text.split())


def _iter_model_items(model_output: dict[str, Any]):
    leagues = model_output.get("leagues")
    if isinstance(leagues, dict):
        for league, group in leagues.items():
            if not isinstance(group, dict):
                continue
            for item in group.get("items", []) if isinstance(group.get("items"), list) else []:
                if isinstance(item, dict):
                    yield str(league), item

    events = model_output.get("specialEvents")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            context = _clean(event.get("name")) or _clean(event.get("sport")) or "SPECIAL"
            for item in event.get("items", []) if isinstance(event.get("items"), list) else []:
                if isinstance(item, dict):
                    yield context, item


def extract_tier_records(model_output: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for context, item in _iter_model_items(model_output or {}):
        try:
            tier = int(item.get("editorialTier"))
        except Exception:
            tier = 0
        candidate_ids = {
            str(cid) for cid in item.get("candidateIds", [])
            if isinstance(cid, str) and cid
        }
        records.append({
            "context": context,
            "candidateIds": candidate_ids,
            "headline": _clean(item.get("headline")),
            "headlineNorm": _norm(item.get("headline")),
            "type": _clean(item.get("type")).upper(),
            "editorialTier": tier if tier in VALID_TIERS else None,
            "modelPriority": item.get("priority"),
        })
    return records


def _infer_tier_from_priority(priority: Any) -> int:
    try:
        value = int(priority)
    except Exception:
        value = 60
    if value >= 82:
        return 1
    if value >= 72:
        return 2
    return 3


def _match_tier_record(
    item: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    ids = {
        str(cid) for cid in item.get("candidateIds", [])
        if isinstance(cid, str) and cid
    }
    headline = _norm(item.get("headline"))
    kind = _clean(item.get("type")).upper()

    best: tuple[int, dict[str, Any]] | None = None
    for record in records:
        overlap = len(ids & record["candidateIds"])
        exact_ids = bool(ids and ids == record["candidateIds"])
        headline_match = bool(headline and headline == record["headlineNorm"])
        type_match = bool(kind and kind == record["type"])
        if not overlap and not headline_match:
            continue
        score = overlap * 100 + int(exact_ids) * 30 + int(headline_match) * 20 + int(type_match) * 5
        if best is None or score > best[0]:
            best = (score, record)
        elif best is not None and score == best[0]:
            # Same story from primary/refill: keep the stronger editorial tier.
            old_tier = best[1].get("editorialTier") or 9
            new_tier = record.get("editorialTier") or 9
            if new_tier < old_tier:
                best = (score, record)
    return best[1] if best else None


def _candidate_lookup(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(candidate.get("candidateId")): candidate
        for candidate in candidates or []
        if isinstance(candidate, dict) and candidate.get("candidateId")
    }


def _candidate_text(candidate: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "summary", "description", "freshnessBasis", "leagueHint", "sportHint"):
        value = candidate.get(key)
        if isinstance(value, str):
            parts.append(value)
    metadata = candidate.get("metadata")
    if isinstance(metadata, (dict, list)):
        try:
            parts.append(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
        except Exception:
            pass
    return _clean(" ".join(parts))


def _item_evidence(
    item: dict[str, Any],
    lookup: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    public_text = _clean(" ".join([
        _clean(item.get("headline")),
        _clean(item.get("text")),
        _clean(item.get("freshnessBasis")),
        " ".join(_clean(x) for x in item.get("entities", []) if isinstance(x, str)),
    ]))
    source_parts = []
    for cid in item.get("candidateIds", []):
        candidate = lookup.get(str(cid))
        if candidate:
            source_parts.append(_candidate_text(candidate))
    return public_text, _clean(" ".join(source_parts))


def _has_severe_injury_evidence(text: str) -> bool:
    low = text.lower()
    return any(term in low for term in SEVERE_INJURY_TERMS)


def apply_tier_sanity_ceiling(
    item: dict[str, Any],
    requested_tier: int,
    evidence: str,
) -> tuple[int, str | None]:
    """High-confidence contradiction guards; these are not content-count quotas."""
    kind = _clean(item.get("type")).upper()
    low = evidence.lower()

    if kind == "INJURY":
        if _has_severe_injury_evidence(evidence):
            return requested_tier, None
        if SHORT_IL_RE.search(evidence):
            if requested_tier < 3:
                return 3, "routine short-term IL move cannot be Tier 1/2 without severe evidence"
        elif DAY_TO_DAY_RE.search(evidence):
            if requested_tier < 2:
                return 2, "day-to-day/missed-games soreness cannot be Tier 1 without severe evidence"

    if kind == "PRACTICE":
        if not any(term in low for term in PRACTICE_CONSEQUENCE_TERMS):
            if requested_tier < 3:
                return 3, "practice item has no grounded competitive consequence"

    return requested_tier, None


def _headline_winner_prefix(item: dict[str, Any]) -> str:
    headline = _clean(item.get("headline"))
    # The winner/advancing subject is normally before the first result verb.
    parts = re.split(
        r"\b(?:beats?|defeats?|edges?|tops?|stuns?|upsets?|knocks off|rallies past|"
        r"wins?|holds off|gets past|survives?|ousts?|eliminates?)\b",
        headline,
        maxsplit=1,
        flags=re.I,
    )
    return _norm(parts[0] if parts else headline)[:100]


def upset_is_grounded(
    item: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Fail closed: return True only when candidate/source evidence proves upset status."""
    if _clean(item.get("type")).upper() != "UPSET":
        return True, "not-upset"

    lookup = _candidate_lookup(candidates)
    public_text, source_text = _item_evidence(item, lookup)
    source_low = f" {source_text.lower()} "

    # Strongest generic evidence: source itself explicitly identifies upset/favorite status.
    if any(term in source_low for term in UPSET_SOURCE_TERMS):
        return True, "source explicitly establishes upset/favorite status"

    combined = _clean(f"{source_text} {public_text}")

    # College-football division mismatch is independently decisive.
    if (
        ("fcs" in combined.lower() and "fbs" in combined.lower())
        and (
            FCS_OVER_FBS_RE.search(combined)
            or re.search(r"\b(?:beat|beats|defeat|defeats|over|past)\s+(?:an?\s+)?fbs", combined, re.I)
        )
    ):
        return True, "FCS/lower-division winner over FBS opposition"

    # Ranking/seed evidence. Use the rendered/source-grounded story text because the
    # model is not allowed to invent rankings and the final item is source-grounded.
    ranks = [(m.start(), int(m.group(1))) for m in RANK_RE.finditer(combined)]
    winner_prefix = _headline_winner_prefix(item)

    if len(ranks) >= 2:
        # In sports rankings/seeds, a larger number is lower-ranked. If the first
        # subject-associated rank is numerically worse than another opponent rank,
        # the upset label is grounded.
        first_rank = ranks[0][1]
        if any(first_rank > rank for _, rank in ranks[1:]):
            return True, "lower-ranked/lower-seeded winner beat higher-ranked opponent"

    if len(ranks) == 1:
        rank_pos, _ = ranks[0]
        rank_fragment = _norm(combined[max(0, rank_pos - 60): rank_pos + 80])
        # Ranked loser case such as "Tulsa knocks off No. 10 Oklahoma State":
        # the rank appears after the winner-led headline subject.
        headline = _clean(item.get("headline"))
        headline_rank = RANK_RE.search(headline)
        if headline_rank and headline_rank.start() > max(4, len(headline) // 4):
            return True, "winner beat explicitly ranked opponent"

        # Ranked winner with no ranked-opponent evidence is specifically NOT proof
        # of an upset (the Michigan/Western Michigan failure mode).
        if winner_prefix and winner_prefix.split()[-1:] and any(
            token in rank_fragment for token in winner_prefix.split()[-2:]
        ):
            return False, "only the winner is explicitly ranked; no underdog evidence"

    return False, "no grounded ranking/seed/division/favorite evidence"


def enforce_tiers_and_upsets(
    normalized: dict[str, Any],
    tier_records: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit: list[dict[str, Any]] = []
    upset_changes: list[dict[str, Any]] = []
    lookup = _candidate_lookup(candidates)

    def process(items: list[dict[str, Any]], context: str) -> None:
        for item in items:
            record = _match_tier_record(item, tier_records)
            requested_tier = (
                int(record["editorialTier"])
                if record and record.get("editorialTier") in VALID_TIERS
                else _infer_tier_from_priority(item.get("priority"))
            )
            tier_source = "model" if record and record.get("editorialTier") in VALID_TIERS else "priority-fallback"

            public_text, source_text = _item_evidence(item, lookup)
            evidence = _clean(f"{source_text} {public_text}")
            effective_tier, ceiling_reason = apply_tier_sanity_ceiling(
                item, requested_tier, evidence
            )

            before_priority = int(item.get("priority") or TIER_BANDS[effective_tier][0])
            lo, hi = TIER_BANDS[effective_tier]
            after_priority = min(max(before_priority, lo), hi)

            item["editorialTier"] = effective_tier
            item["priority"] = after_priority

            audit.append({
                "context": context,
                "headline": item.get("headline"),
                "candidateIds": item.get("candidateIds", []),
                "modelTier": requested_tier,
                "effectiveTier": effective_tier,
                "tierSource": tier_source,
                "priorityBefore": before_priority,
                "priorityAfter": after_priority,
                "tierCeilingReason": ceiling_reason,
            })

            if _clean(item.get("type")).upper() == "UPSET":
                grounded, reason = upset_is_grounded(item, candidates)
                if not grounded:
                    before_type = item.get("type")
                    item["type"] = "RESULT"
                    upset_changes.append({
                        "context": context,
                        "headline": item.get("headline"),
                        "candidateIds": item.get("candidateIds", []),
                        "beforeType": before_type,
                        "afterType": "RESULT",
                        "reason": reason,
                    })

    for group in normalized.get("leagues", []):
        items = group.get("items", []) if isinstance(group.get("items"), list) else []
        process(items, _clean(group.get("league")))

    for event in normalized.get("specialEvents", []):
        items = event.get("items", []) if isinstance(event.get("items"), list) else []
        process(items, _clean(event.get("name")))

    if run_log is not None:
        pipe = run_log.setdefault("pipeline", {})
        pipe["a412TierAudit"] = audit
        pipe["a412UpsetCorrections"] = upset_changes

    return normalized


def strip_public_editorial_tiers(
    normalized: dict[str, Any],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_audit: list[dict[str, Any]] = []

    def strip(items: list[dict[str, Any]], context: str) -> None:
        for item in items:
            if item.get("editorialTier") in VALID_TIERS:
                selected_audit.append({
                    "context": context,
                    "feedRank": item.get("feedRank"),
                    "headline": item.get("headline"),
                    "candidateIds": item.get("candidateIds", []),
                    "editorialTier": item.get("editorialTier"),
                    "priority": item.get("priority"),
                })
            item.pop("editorialTier", None)

    for group in normalized.get("leagues", []):
        strip(
            group.get("items", []) if isinstance(group.get("items"), list) else [],
            _clean(group.get("league")),
        )
    for event in normalized.get("specialEvents", []):
        strip(
            event.get("items", []) if isinstance(event.get("items"), list) else [],
            _clean(event.get("name")),
        )

    if run_log is not None:
        run_log.setdefault("pipeline", {})["a412SelectedTierAudit"] = selected_audit
    return normalized


def install_editorial_tier_schema(core) -> None:
    prop = {"type": "integer", "enum": [1, 2, 3]}
    core.MODEL_ITEM_SCHEMA.setdefault("properties", {})["editorialTier"] = dict(prop)
    required = core.MODEL_ITEM_SCHEMA.setdefault("required", [])
    if "editorialTier" not in required:
        required.append("editorialTier")

    item_def = core.MODEL_SCHEMA.setdefault("$defs", {}).setdefault("item", {})
    item_def.setdefault("properties", {})["editorialTier"] = dict(prop)
    item_required = item_def.setdefault("required", [])
    if "editorialTier" not in item_required:
        item_required.append("editorialTier")


def _patch_a48_runtime(a48) -> None:
    holder: dict[str, Any] = {
        "tierRecords": [],
        "candidates": [],
    }

    # A4.10 has already wrapped A4.8's pre-budget editorial progression gate.
    original_collapse = a48.collapse_editorial_progressions

    def collapse_a412(normalized, run_log=None):
        enforce_tiers_and_upsets(
            normalized,
            holder.get("tierRecords", []),
            holder.get("candidates", []),
            run_log,
        )
        return original_collapse(normalized, run_log)

    a48.collapse_editorial_progressions = collapse_a412

    # Reach the stable A4 configure point so the structured-output schema requires
    # editorialTier and the raw model output is available while pre-budget gates run.
    original_patch_a45 = a48._patch_a45

    def patch_a45_a412(a45, a46, a47):
        original_patch_a45(a45, a46, a47)
        original_load_a44 = a45._load_a44

        def load_a44_a412():
            a44 = original_load_a44()
            original_patch_a43 = a44._patch_a43

            def patch_a43_a412(a43):
                original_patch_a43(a43)
                original_patch_a42 = a43._patch_a42

                def patch_a42_a412(a42):
                    original_patch_a42(a42)
                    original_configure = a42._configure_core

                    def configure_a412(core):
                        original_configure(core)
                        install_editorial_tier_schema(core)

                        original_normalize = core.normalize_model_output
                        original_init = core.initial_run_log

                        def normalize_a412(model_output, candidates, generated_at, run_log):
                            holder["tierRecords"] = extract_tier_records(model_output or {})
                            holder["candidates"] = list(candidates or [])
                            try:
                                normalized = original_normalize(
                                    model_output, candidates, generated_at, run_log
                                )
                                return strip_public_editorial_tiers(normalized, run_log)
                            finally:
                                holder["tierRecords"] = []
                                holder["candidates"] = []

                        def initial_run_log_a412(generated_at, cutoff, model):
                            log = original_init(generated_at, cutoff, model)
                            log["pipelineVersion"] = PIPELINE_VERSION
                            config = log.setdefault("configuration", {})
                            config["editorialTierContract"] = (
                                "model-required editorialTier: Tier1=82-95, "
                                "Tier2=72-81, Tier3=60-71; enforced pre-budget"
                            )
                            config["upsetEvidencePolicy"] = (
                                "UPSET requires grounded ranking/seed/division/favorite evidence; "
                                "dramatic finish alone is RESULT"
                            )
                            return log

                        core.normalize_model_output = normalize_a412
                        core.initial_run_log = initial_run_log_a412

                    a42._configure_core = configure_a412

                a43._patch_a42 = patch_a42_a412

            a44._patch_a43 = patch_a43_a412
            return a44

        a45._load_a44 = load_a44_a412

    a48._patch_a45 = patch_a45_a412


def main() -> int:
    a411 = _load_a411()
    a411.PIPELINE_VERSION = PIPELINE_VERSION
    a411.A411_EDITOR_ADDENDUM = a411.A411_EDITOR_ADDENDUM + A412_EDITOR_ADDENDUM

    original_load_a410 = a411._load_a410

    def load_a410_a412():
        a410 = original_load_a410()
        a410.PIPELINE_VERSION = PIPELINE_VERSION

        original_patch_a48 = a410._patch_a48

        def patch_a48_a412(a48):
            original_patch_a48(a48)
            _patch_a48_runtime(a48)

        a410._patch_a48 = patch_a48_a412
        return a410

    a411._load_a410 = load_a410_a412
    return a411.main()


if __name__ == "__main__":
    raise SystemExit(main())

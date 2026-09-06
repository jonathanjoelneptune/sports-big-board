#!/usr/bin/env python3
"""Sports Big Board A4.9 grounded copy-integrity overlay on A4.8.

A4.9 keeps the working 30-35 headline architecture completely frozen and fixes
the remaining presentation defect exposed by the first A4.8 live run:

- raw structured play-by-play must never survive into ticker text/freshness copy;
- natural source-grounded article/recap summaries are preferred when available;
- fused ESPN title/summary context is unpacked correctly instead of being treated
  as a stringified metadata dictionary;
- supporting copy should add useful game context rather than merely replaying the
  score or dumping source syntax.

No discovery source, global budget, source depth, league cap, event-identity rule,
or headline-length setting changes in this release.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.9-grounded-copy-integrity"

A49_EDITOR_ADDENDUM = r"""

A4.9 GROUNDED COPY INTEGRITY — CRITICAL
Do NOT change the established 30-35 headline budget, coverage mix, source depth,
event-identity rules, or 80/96-character headline contract.

SUPPORTING COPY
- Never output raw structured play-by-play syntax in headline, text, or freshness copy.
- Examples of forbidden source syntax include clock-prefixed play strings, Shotgun /
  No Huddle notation, player-number tokens, "yards gain to", "1ST DOWN",
  "TOUCHDOWN, clock", "rush attempt failed", or "pass attempt Successful".
- When the candidate packet contains a natural ESPN/article recap title or summary,
  use that grounded prose instead.
- Prefer useful performer/context detail over a sentence that merely repeats the score.
- Never invent a player, stat, scoring play, overtime detail, or game circumstance.
"""

RAW_PLAY_CUES = (
    r"^\(\s*\d{1,2}:\d{2}\s*\)",
    r"\b(?:no huddle[- ]?)?shotgun\b",
    r"\b#\d+\s+[a-z]\.",
    r"\byards?\s+gain\s+to\b",
    r"\b1st\s+down\b",
    r"\b2nd\s+down\b",
    r"\b3rd\s+down\b",
    r"\b4th\s+down\b",
    r"\btouchdown,\s*clock\b",
    r"\brush\s+attempt\s+(?:failed|successful)\b",
    r"\bpass\s+attempt\s+(?:failed|successful)\b",
    r"\btimeout\s+[a-z].*clock\b",
    r"\bpenalty\s+[a-z0-9# ]+\b",
)

RESULTISH_TYPES = {
    "RESULT", "UPSET", "PLAYOFF", "STANDINGS", "STREAK",
    "MILESTONE", "RECORD", "RECORD_CHASE", "ADVANCEMENT",
}


def _load_a48():
    path = Path(__file__).with_name("refresh_sports_ticker_a48.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a48", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.8 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _natural_sentence(value: Any) -> str:
    text = _clean(value)
    text = re.sub(r"^[—–-]\s*", "", text)
    return text.strip()


def _looks_like_raw_structured_play(value: Any) -> bool:
    text = _clean(value)
    if not text:
        return False
    low = text.lower()
    hits = sum(1 for pattern in RAW_PLAY_CUES if re.search(pattern, low, flags=re.I))
    if hits >= 2:
        return True
    # Long clock/player-number feed fragments are also unmistakable play strings.
    if (
        len(text) >= 120
        and re.search(r"\(\s*\d{1,2}:\d{2}\s*\)", text)
        and re.search(r"#\d+", text)
        and ("clock" in low or "yards" in low)
    ):
        return True
    return False


def _is_bad_detail(value: Any, a45=None) -> bool:
    text = _natural_sentence(value)
    if not text:
        return True
    low = text.lower()
    if low.startswith("highlightly final:"):
        return True
    if text.startswith("{") and ("candidateId" in text or "'summary'" in text or '"summary"' in text):
        return True
    if _looks_like_raw_structured_play(text):
        return True
    if a45 is not None:
        try:
            if a45._looks_like_raw_play(text):
                return True
        except Exception:
            pass
    return False


def _append_choice(
    out: list[tuple[str, str]],
    source: str,
    value: Any,
    *,
    a45=None,
) -> None:
    text = _natural_sentence(value)
    if not (18 <= len(text) <= 360):
        return
    if _is_bad_detail(text, a45):
        return
    if any(existing == text for _, existing in out):
        return
    out.append((source, text))


def augment_candidate_detail_choices(
    a45,
    item: dict[str, Any],
    candidate: dict[str, Any],
    base_choices: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Add real candidate/fused prose and remove metadata/PBP artifacts."""
    out: list[tuple[str, str]] = []
    for source, value in base_choices:
        _append_choice(out, source, value, a45=a45)

    # The A4.5 helper did not directly add the candidate's own natural title/summary.
    _append_choice(out, "candidate-summary", candidate.get("summary"), a45=a45)
    _append_choice(out, "candidate-title", candidate.get("title"), a45=a45)

    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    fused = meta.get("fusedContext") if isinstance(meta.get("fusedContext"), list) else []
    for record in fused:
        if not isinstance(record, dict):
            continue
        providers = record.get("providers") if isinstance(record.get("providers"), list) else []
        provider = "-".join(_clean(x).lower() for x in providers if _clean(x)) or "fused"
        _append_choice(out, f"{provider}-fused-summary", record.get("summary"), a45=a45)
        _append_choice(out, f"{provider}-fused-title", record.get("title"), a45=a45)

    return out


def sanitize_grounded_copy(
    a45,
    normalized: dict[str, Any],
    candidates: list[dict[str, Any]],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed on raw PBP in user-facing detail/freshness fields."""
    by_id = {
        c.get("candidateId"): c
        for c in candidates
        if isinstance(c, dict) and isinstance(c.get("candidateId"), str)
    }
    updates: list[dict[str, Any]] = []

    def repair_items(items: list[dict[str, Any]], context: str) -> None:
        for item in items:
            kind = _clean(item.get("type")).upper()
            raw_text = _is_bad_detail(item.get("text"), a45)
            raw_fresh = _is_bad_detail(item.get("freshnessBasis"), a45)
            if not (raw_text or raw_fresh):
                continue

            candidate = next(
                (by_id.get(cid) for cid in item.get("candidateIds", []) if by_id.get(cid)),
                None,
            )
            best = ""
            source = ""
            if isinstance(candidate, dict):
                try:
                    source, best = a45._best_grounded_detail(item, candidate)
                except Exception:
                    best = ""
                best = _natural_sentence(best)
                if _is_bad_detail(best, a45):
                    best = ""

                # Last grounded fallback: walk the augmented candidate choices directly.
                if not best:
                    try:
                        choices = augment_candidate_detail_choices(a45, item, candidate, [])
                    except Exception:
                        choices = []
                    if choices:
                        # Prefer a natural summary over a title when both exist.
                        choices.sort(
                            key=lambda row: (
                                "summary" in row[0],
                                row[0].startswith("espn-"),
                                35 <= len(row[1]) <= 240,
                                len(row[1]),
                            ),
                            reverse=True,
                        )
                        source, best = choices[0]

            if not best:
                # A clean existing headline is still safer than leaking raw source syntax.
                best = _natural_sentence(item.get("headline"))
                source = "headline-fallback"

            if best and not best.endswith((".", "!", "?")):
                best += "."

            before_text = _clean(item.get("text"))
            before_fresh = _clean(item.get("freshnessBasis"))
            if raw_text:
                item["text"] = best[:360]
            if raw_fresh:
                item["freshnessBasis"] = best[:360]

            updates.append({
                "context": context,
                "type": kind,
                "headline": item.get("headline"),
                "candidateIds": item.get("candidateIds", []),
                "textChanged": raw_text,
                "freshnessChanged": raw_fresh,
                "beforeText": before_text,
                "afterText": item.get("text"),
                "beforeFreshness": before_fresh,
                "afterFreshness": item.get("freshnessBasis"),
                "source": source,
            })

    for group in normalized.get("leagues", []):
        items = group.get("items", []) if isinstance(group.get("items"), list) else []
        repair_items(items, _clean(group.get("league")))

    for event in normalized.get("specialEvents", []):
        items = event.get("items", []) if isinstance(event.get("items"), list) else []
        repair_items(items, _clean(event.get("name")))

    if run_log is not None:
        pipe = run_log.setdefault("pipeline", {})
        pipe["a49CopyIntegrity"] = {
            "updatedCount": len(updates),
            "updated": updates,
            "policy": "raw structured PBP replaced only with grounded candidate/fused prose",
        }
    return normalized


def _install_copy_integrity(a45) -> None:
    # Expand A4.5 raw-play detection from baseball syntax to structured football PBP.
    original_raw = a45._looks_like_raw_play

    def raw_a49(value):
        return bool(original_raw(value) or _looks_like_raw_structured_play(value))

    a45._looks_like_raw_play = raw_a49

    # Properly unpack natural candidate/fused article context.
    original_choices = a45._candidate_detail_choices

    def choices_a49(item, candidate):
        base = original_choices(item, candidate)
        return augment_candidate_detail_choices(a45, item, candidate, base)

    a45._candidate_detail_choices = choices_a49

    # A4.5 already polishes RESULT/UPSET detail. Run one deterministic safety pass
    # afterward so raw freshnessBasis copy cannot survive even when text was repaired.
    original_polish = a45.polish_result_details

    def polish_a49(a44, core, normalized, candidates, run_log=None):
        normalized = original_polish(a44, core, normalized, candidates, run_log)
        return sanitize_grounded_copy(a45, normalized, candidates, run_log)

    a45.polish_result_details = polish_a49
    a45.PIPELINE_VERSION = PIPELINE_VERSION


def main() -> int:
    a48 = _load_a48()

    # A4.8's nested pipeline/log closures resolve these globals at runtime.
    a48.PIPELINE_VERSION = PIPELINE_VERSION
    a48.A48_EDITOR_ADDENDUM = a48.A48_EDITOR_ADDENDUM + A49_EDITOR_ADDENDUM

    a47 = a48._load_a47()
    a46 = a47._load_a46()
    a45 = a46._load_a45()

    a48._patch_a45(a45, a46, a47)
    _install_copy_integrity(a45)
    return a45.main()


if __name__ == "__main__":
    raise SystemExit(main())

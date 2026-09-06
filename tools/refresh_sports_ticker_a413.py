#!/usr/bin/env python3
"""Sports Big Board A4.13 semantic type + primary-display-copy overlay on A4.12.

A4.13 leaves the established selection architecture frozen and repairs three
normalization defects seen in the first live A4.12 run:

- restore/protect objectively grounded UPSET labels when ranking/seed/division
  evidence proves the winner was the underdog;
- classify post-qualifying grid penalties as DISCIPLINE rather than QUALIFYING;
- prevent raw structured baseball pitch-feed strings from replacing natural
  grounded ticker copy;
- make item.text the explicit primary Sports Ticker display copy while keeping
  item.headline as compact metadata/debug copy;
- require primary display copy to be a standalone, polished sports-news sentence.

No budget, tier-band, refill, source-depth, league-cap, compact-headline-length,
stable-launcher, or workflow/YAML change.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.13-semantic-type-primary-display-copy"

A413_EDITOR_ADDENDUM = r"""

A4.13 SEMANTIC TYPE + COPY INTEGRITY
Keep A4.12's editorialTier contract and all existing selection rules unchanged.

TYPE PRECISION
- If a lower-ranked/lower-seeded or unranked winner defeats a clearly higher-ranked
  or higher-seeded opponent, use UPSET.
- A dramatic favorite win remains RESULT, even if it is a Hail Mary or overtime.
- A Formula 1 grid penalty/impeding penalty is DISCIPLINE, not QUALIFYING.
  The qualifying session outcome itself (pole, front row, qualifying position)
  remains QUALIFYING.

PRIMARY DISPLAY COPY
- `text` is the ACTUAL user-facing Sports Ticker update. It will be displayed
  without requiring the compact `headline` to appear beside it.
- `headline` is a short editorial label / metadata field only.
- Write `text` as one polished, standalone sports-news sentence. Usually aim for
  roughly 70-180 characters; be descriptive enough to explain what happened and
  why it matters without becoming a full article.
- Name the important player/team/event directly. Do not begin with context-dependent
  phrases such as "The veteran", "The club-record signing", "He", "She", or "They"
  when the identity only exists in the headline.
- For a result, include the score plus the decisive play/performance/consequence
  when grounded. For injuries, transactions, records, standings, and event news,
  include the key action and useful consequence/status.
- Do not write source-process language such as "according to the supplied report."

COPY INTEGRITY
- Never expose raw structured play/pitch feed syntax in ticker text.
- Baseball strings such as "Pitch 3 : Ball In Play ..." are evidence only.
  Prefer the grounded natural recap/freshness sentence instead.
"""

RANK_RE = re.compile(r"\b(?:no\.?\s*|#|seed(?:ed)?\s*)(\d{1,2})\b", re.I)
RESULT_VERB_RE = re.compile(
    r"\b(?:beat|beats|defeat|defeats|defeated|edge|edges|edged|top|tops|"
    r"stun|stuns|stunned|knock(?:s|ed)? off|oust|ousts|eliminate|eliminates|"
    r"rall(?:y|ies|ied) past|hold(?:s)? off|survive|survives)\b",
    re.I,
)
RAW_BASEBALL_RE = re.compile(
    r"^\s*pitch\s+\d+\s*:|\bball in play\b|\bpitch\s+\d+\s*:\s*(?:ball|strike|foul)\b",
    re.I,
)
PENALTY_RE = re.compile(
    r"\b(?:grid penalty|place penalty|places? penalty|penali[sz]ed|penalty|impeding)\b",
    re.I,
)
POLE_RE = re.compile(r"\b(?:takes?|claims?|wins?|earns?|secures?)\s+(?:first\s+career\s+)?pole\b", re.I)

DEPENDENT_DISPLAY_OPENING_RE = re.compile(
    r"^(?:the\s+(?:veteran|rookie|club-record signing|record signing|defender|"
    r"quarterback|running back|pitcher|reliever|starter|forward|midfielder|"
    r"goalkeeper|driver|fighter|coach|manager|star)|he|she|they|his|her|their)\b",
    re.I,
)
SOURCE_PROCESS_RE = re.compile(
    r"\b(?:according to (?:the )?(?:supplied|provided) (?:report|source)|"
    r"the supplied report|the provided source)\b",
    re.I,
)


def _load_a412():
    path = Path(__file__).with_name("refresh_sports_ticker_a412.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a412", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.12 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _candidate_lookup(candidates):
    return {
        str(c.get("candidateId")): c
        for c in candidates or []
        if isinstance(c, dict) and c.get("candidateId")
    }


def _structured_upset_evidence(item, candidates):
    """Use structured score/rank/FBS identity before any prose heuristics."""
    lookup = _candidate_lookup(candidates)
    for cid in item.get("candidateIds", []):
        c = lookup.get(str(cid))
        if not c:
            continue
        meta = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
        try:
            hs, as_ = int(meta.get("homeScore")), int(meta.get("awayScore"))
        except Exception:
            continue
        if hs == as_:
            continue

        home_won = hs > as_
        winner_rank = meta.get("homeRank") if home_won else meta.get("awayRank")
        loser_rank = meta.get("awayRank") if home_won else meta.get("homeRank")
        try:
            wr = int(winner_rank) if winner_rank is not None else None
        except Exception:
            wr = None
        try:
            lr = int(loser_rank) if loser_rank is not None else None
        except Exception:
            lr = None

        if lr is not None and (wr is None or wr > lr):
            return True, "structured lower-ranked/unranked winner beat higher-ranked opponent"

        winner_fbs = meta.get("homeFbs") if home_won else meta.get("awayFbs")
        loser_fbs = meta.get("awayFbs") if home_won else meta.get("homeFbs")
        if not winner_fbs and loser_fbs:
            return True, "structured lower-division/non-FBS winner beat FBS opponent"

    return False, ""


def _public_rank_upset_evidence(item):
    """Prefer winner-led public copy so source article ordering cannot invert ranks."""
    headline = _clean(item.get("headline"))
    text = _clean(item.get("text"))
    fresh = _clean(item.get("freshnessBasis"))
    public = " ".join(x for x in (headline, text, fresh) if x)

    # Lower-ranked/seeded winner explicitly leads the headline.
    hm = RANK_RE.search(headline)
    if hm and hm.start() <= max(20, len(headline) // 3):
        winner_rank = int(hm.group(1))
        ranks = [int(m.group(1)) for m in RANK_RE.finditer(public)]
        if any(rank < winner_rank for rank in ranks[1:]):
            return True, "winner-led copy shows lower-ranked/lower-seeded winner"

    # Unranked winner with a ranked loser named after the result verb.
    verb = RESULT_VERB_RE.search(headline)
    if verb:
        before = headline[:verb.start()]
        after = headline[verb.end():]
        if not RANK_RE.search(before) and RANK_RE.search(after):
            return True, "unranked winner beat explicitly ranked/seeded opponent"

    # Explicit FCS/lower-division winner over FBS in public grounded copy.
    low = public.lower()
    if "fcs" in low and "fbs" in low:
        if re.search(r"\bfcs\b.{0,100}\b(?:beat|defeat|over|past)\b.{0,100}\bfbs\b", low):
            return True, "public copy establishes FCS winner over FBS opponent"

    return False, ""


def objective_upset_evidence(a412, item, candidates):
    grounded, reason = _structured_upset_evidence(item, candidates)
    if grounded:
        return grounded, reason

    grounded, reason = _public_rank_upset_evidence(item)
    if grounded:
        return grounded, reason

    # Secondary reuse of A4.12's explicit-source/FCS logic. Force an UPSET copy
    # because A4.12 short-circuits non-UPSET item types.
    probe = dict(item)
    probe["type"] = "UPSET"
    try:
        grounded, reason = a412.upset_is_grounded(probe, candidates)
        if grounded:
            return True, reason
    except Exception:
        pass
    return False, "no objective upset evidence"


def normalize_semantic_types(a412, normalized, candidates, run_log=None):
    changes = []

    def visit(items, context):
        for item in items:
            before = _clean(item.get("type")).upper()
            after = before
            reason = ""

            # Restore a proven upset even if A4.12's earlier source-order heuristic
            # demoted it to RESULT.
            if before in {"RESULT", "UPSET"}:
                grounded, why = objective_upset_evidence(a412, item, candidates)
                if grounded and before != "UPSET":
                    after = "UPSET"
                    reason = why

            blob = " ".join([
                _clean(item.get("headline")),
                _clean(item.get("text")),
                _clean(item.get("freshnessBasis")),
            ])
            if before == "QUALIFYING" and PENALTY_RE.search(blob) and not POLE_RE.search(_clean(item.get("headline"))):
                after = "DISCIPLINE"
                reason = "grid/impeding penalty is discipline, not qualifying outcome"

            if after != before:
                item["type"] = after
                changes.append({
                    "context": context,
                    "headline": item.get("headline"),
                    "candidateIds": item.get("candidateIds", []),
                    "beforeType": before,
                    "afterType": after,
                    "reason": reason,
                })

    for group in normalized.get("leagues", []):
        visit(
            group.get("items", []) if isinstance(group.get("items"), list) else [],
            _clean(group.get("league")),
        )
    for event in normalized.get("specialEvents", []):
        visit(
            event.get("items", []) if isinstance(event.get("items"), list) else [],
            _clean(event.get("name")),
        )

    if run_log is not None:
        run_log.setdefault("pipeline", {})["a413SemanticTypeCorrections"] = changes
    return normalized


def sanitize_baseball_pitch_copy(normalized, run_log=None):
    changes = []

    def visit(items, context):
        for item in items:
            text = _clean(item.get("text"))
            if not RAW_BASEBALL_RE.search(text):
                continue

            fresh = _clean(item.get("freshnessBasis"))
            replacement = fresh if fresh and not RAW_BASEBALL_RE.search(fresh) else _clean(item.get("headline"))
            if not replacement:
                continue
            if not replacement.endswith((".", "!", "?")):
                replacement += "."

            item["text"] = replacement
            changes.append({
                "context": context,
                "headline": item.get("headline"),
                "candidateIds": item.get("candidateIds", []),
                "beforeText": text,
                "afterText": replacement,
                "reason": "raw structured baseball pitch-feed text replaced with grounded natural copy",
            })

    for group in normalized.get("leagues", []):
        visit(
            group.get("items", []) if isinstance(group.get("items"), list) else [],
            _clean(group.get("league")),
        )
    for event in normalized.get("specialEvents", []):
        visit(
            event.get("items", []) if isinstance(event.get("items"), list) else [],
            _clean(event.get("name")),
        )

    if run_log is not None:
        run_log.setdefault("pipeline", {})["a413CopyCorrections"] = changes
    return normalized



def promote_primary_display_copy(normalized, run_log=None):
    """Make item.text the standalone display sentence; preserve headline metadata."""
    changes = []

    def clean_sentence(value):
        text = _clean(value)
        if text and not text.endswith((".", "!", "?")):
            text += "."
        return text

    def visit(items, context):
        for item in items:
            before = _clean(item.get("text"))
            fresh = _clean(item.get("freshnessBasis"))
            chosen = before
            reason = None

            if SOURCE_PROCESS_RE.search(chosen):
                cleaned = SOURCE_PROCESS_RE.sub("", chosen)
                cleaned = re.sub(r"\s+,", ",", cleaned)
                cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;:-")
                if cleaned and not DEPENDENT_DISPLAY_OPENING_RE.search(cleaned):
                    chosen = cleaned
                    reason = "removed source-process wording from primary display copy"

            if (
                (not chosen or DEPENDENT_DISPLAY_OPENING_RE.search(chosen))
                and fresh
                and not DEPENDENT_DISPLAY_OPENING_RE.search(fresh)
                and not RAW_BASEBALL_RE.search(fresh)
            ):
                chosen = fresh
                reason = "headline-dependent text replaced with standalone grounded freshness copy"

            chosen = clean_sentence(chosen or fresh or item.get("headline"))
            if chosen:
                item["text"] = chosen

            if item.get("text") != before:
                changes.append({
                    "context": context,
                    "headline": item.get("headline"),
                    "candidateIds": item.get("candidateIds", []),
                    "beforeText": before,
                    "afterText": item.get("text"),
                    "reason": reason or "normalized primary display copy",
                })

    for group in normalized.get("leagues", []):
        visit(
            group.get("items", []) if isinstance(group.get("items"), list) else [],
            _clean(group.get("league")),
        )
    for event in normalized.get("specialEvents", []):
        visit(
            event.get("items", []) if isinstance(event.get("items"), list) else [],
            _clean(event.get("name")),
        )

    if run_log is not None:
        run_log.setdefault("pipeline", {})["a413PrimaryDisplayCopy"] = {
            "field": "text",
            "headlineRole": "compact metadata/debug label",
            "updatedCount": len(changes),
            "updated": changes,
        }
    return normalized


def install_primary_display_contract(core):
    """Declare item.text as display copy in JSON and make TXT review display-first."""
    import copy as _copy

    original_render = core.render_text
    original_atomic_write = core.atomic_write

    def visit_dataset_items(dataset, fn):
        for group in dataset.get("leagues", []) if isinstance(dataset, dict) else []:
            if not isinstance(group, dict):
                continue
            for item in group.get("items", []) if isinstance(group.get("items"), list) else []:
                if isinstance(item, dict):
                    fn(item)
        for event in dataset.get("specialEvents", []) if isinstance(dataset, dict) else []:
            if not isinstance(event, dict):
                continue
            for item in event.get("items", []) if isinstance(event.get("items"), list) else []:
                if isinstance(item, dict):
                    fn(item)

    def render_a413(dataset):
        view = _copy.deepcopy(dataset)

        def display_first(item):
            compact = _clean(item.get("headline"))
            display = _clean(item.get("text")) or compact
            if display:
                item["headline"] = display
            if compact and compact != display:
                item["text"] = f"Compact headline: {compact}"
            elif compact:
                item["text"] = "Compact headline: same as display update"

        visit_dataset_items(view, display_first)
        rendered = original_render(view)
        rendered = rendered.replace("Headline length:", "Compact headline length:")

        lines = rendered.splitlines(keepends=True)
        marker = (
            "Primary display copy: item.text (standalone polished update); "
            "headline is compact metadata\n"
        )
        if marker not in lines:
            insert_at = 0
            for idx, line in enumerate(lines):
                if line.startswith("Compact headline length:"):
                    insert_at = idx + 1
                    break
                if line.startswith("Global headline budget:"):
                    insert_at = idx + 1
            lines.insert(insert_at, marker)
        return "".join(lines)

    def atomic_write_a413(path, content):
        if path.name == "sports-ticker.json":
            try:
                payload = json.loads(content)
                payload["displayCopyField"] = "text"
                payload["headlineRole"] = "compact-metadata"
                payload["displayCopyPolicy"] = (
                    "item.text is the standalone user-facing Sports Ticker update; "
                    "item.headline is a compact editorial label retained for metadata/debug use"
                )
                content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            except Exception:
                pass
        original_atomic_write(path, content)

    core.render_text = render_a413
    core.atomic_write = atomic_write_a413

def main():
    a412 = _load_a412()
    a412.PIPELINE_VERSION = PIPELINE_VERSION
    a412.A412_EDITOR_ADDENDUM = a412.A412_EDITOR_ADDENDUM + A413_EDITOR_ADDENDUM

    original_install_schema = a412.install_editorial_tier_schema

    def install_schema_a413(core):
        original_install_schema(core)
        install_primary_display_contract(core)

    a412.install_editorial_tier_schema = install_schema_a413

    # Semantic type repair runs immediately after A4.12's tier/upset enforcement
    # and before the existing A4.8 global-selection progression gates.
    original_enforce = a412.enforce_tiers_and_upsets

    def enforce_a413(normalized, tier_records, candidates, run_log=None):
        normalized = original_enforce(normalized, tier_records, candidates, run_log)
        return normalize_semantic_types(a412, normalized, candidates, run_log)

    a412.enforce_tiers_and_upsets = enforce_a413

    # Copy cleanup runs at A4.11's late surface-copy stage, after result-context
    # enrichment has had its opportunity to replace model copy.
    original_load_a411 = a412._load_a411

    def load_a411_a413():
        a411 = original_load_a411()
        original_polish = a411.polish_surface_copy

        def polish_a413(normalized, run_log=None):
            normalized = original_polish(normalized, run_log)
            normalized = sanitize_baseball_pitch_copy(normalized, run_log)
            return promote_primary_display_copy(normalized, run_log)

        a411.polish_surface_copy = polish_a413
        return a411

    a412._load_a411 = load_a411_a413
    return a412.main()


if __name__ == "__main__":
    raise SystemExit(main())

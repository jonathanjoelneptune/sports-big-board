#!/usr/bin/env python3
"""Sports Big Board A4.5 copy-polish overlay on A4.4.

A4.5 deliberately leaves the proven 30-35 headline budget, source-depth,
semantic-dedupe, league diversity, and refill architecture unchanged. It only
polishes the final selected feed:

- restore the higher significance floor for LEGAL stories;
- prefer natural source-grounded result prose over raw play-by-play fragments;
- keep strong existing decisive/result context when it is already good;
- add bounded ESPN NCAAF summary context for selected generic RESULT/UPSET items,
  using a standout passer/rusher/receiver when the box score supports it.

No web search is used. Every added fact comes from the existing candidate packet
or a bounded ESPN scoreboard/summary lookup for the selected game.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.5-copy-polish"
LEGAL_PRIORITY_FLOOR = 75
MAX_NCAAF_CONTEXT_SUMMARIES = 8

A45_EDITOR_ADDENDUM = r"""

A4.5 FINAL COPY POLISH — DO NOT CHANGE THE 30-35 HEADLINE MIX
The selection architecture is already correct. Focus on readable supporting copy.

RESULT DETAIL COPY
- The text field must read like a sports-news sentence, not a raw play-by-play dump.
- Avoid source syntax such as "homered to left (394 feet), Harris scored" when the
  same grounded evidence supports natural prose such as "Campusano hit a two-run
  walk-off homer in the 10th to lift San Diego past New York."
- Do not merely restate the score when a decisive play, standout performer,
  pitcher, scorer, passer, rusher, receiver, goalkeeper or other grounded actor is
  available.
- Preserve strong existing context. Do not replace a useful one-sentence summary
  with a less informative stat line.
- Never invent a player, statistic, inning, scoring play or game circumstance.

LEGAL / OFF-FIELD
- LEGAL stories must clear priority 75 after normalization. Routine procedural
  developments below that floor should lose to competitive, injury, transaction,
  record and other sports news.
"""


def _load_a44():
    path = Path(__file__).with_name("refresh_sports_ticker_a44.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a44", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.4 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm(value: Any) -> str:
    text = _clean(value).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9'. /-]+", " ", text)
    return " ".join(text.split())


def _intish(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(str(value)))
    except Exception:
        return None


def _looks_like_raw_play(value: Any) -> bool:
    text = _clean(value)
    low = text.lower()
    if not text:
        return False
    if re.search(r"\(\s*\d{2,3}\s+feet\s*\)", low):
        return True
    if re.search(r"\b(homered|singled|doubled|tripled)\s+to\s+(left|right|center)\b", low):
        return True
    if "," in text and re.search(r"\b(scored|out at|advanced to|to third|to second)\b", low):
        return True
    return False


def _is_generic_score_restatement(value: Any) -> bool:
    text = _norm(value)
    if not text:
        return True
    generic = (
        "defeated", "beat", "beats", "victory", "won", "win over", "routed",
        "held off", "edge", "edged", "finished with", "point win", "run win",
    )
    specific = (
        "homered", "singled", "doubled", "tripled", "touchdown", "threw for",
        "ran for", "receiving yards", "goal", "penalty", "save", "saves",
        "walk-off", "walkoff", "rallied", "comeback", "shutout", "scoreless innings",
        "ahead for good", "first goal", "unbeaten", "record", "milestone",
    )
    return any(term in text for term in generic) and not any(term in text for term in specific)


def _detail_quality(value: Any) -> float:
    text = _clean(value)
    low = _norm(text)
    if not text:
        return -100.0
    score = 2.0
    if 35 <= len(text) <= 220:
        score += 2.0
    if _looks_like_raw_play(text):
        score -= 8.0
    if _is_generic_score_restatement(text):
        score -= 2.5
    cues = (
        "walk-off", "walkoff", "ahead for good", "homered", "singled", "doubled",
        "tripled", "scoreless innings", "shutout", "touchdown", "threw for",
        "ran for", "receiving yards", "goal", "penalty", "save", "saves",
        "rallied", "comeback", "first goal", "unbeaten", "record", "milestone",
        "injury", "extension", "lead", "standings",
    )
    score += sum(1.5 for cue in cues if cue in low)
    if re.search(r"\b\d+(?:\.\d+)?\b", low):
        score += 0.5
    # Complete news-style sentences are preferred to stat fragments.
    if text.endswith((".", "!", "?")):
        score += 0.5
    return score


def _candidate_detail_choices(item: dict[str, Any], candidate: dict[str, Any]) -> list[tuple[str, str]]:
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    promotion = meta.get("storyPromotion") if isinstance(meta.get("storyPromotion"), dict) else {}
    enrichment = meta.get("resultEnrichment") if isinstance(meta.get("resultEnrichment"), dict) else {}
    choices: list[tuple[str, str]] = []

    def add(source: str, value: Any) -> None:
        if isinstance(value, list):
            for part in value:
                add(source, part)
            return
        text = _clean(value)
        if 18 <= len(text) <= 360 and all(text != existing for _, existing in choices):
            choices.append((source, text))

    add("current", item.get("text"))
    add("freshness-basis", item.get("freshnessBasis"))
    add("story-promotion", promotion.get("summarySeed"))
    add("decisive-moment", enrichment.get("decisiveMoment"))
    add("result-enrichment", enrichment.get("summarySeed"))
    add("fused-context", meta.get("fusedContext"))
    return choices


def _best_grounded_detail(item: dict[str, Any], candidate: dict[str, Any]) -> tuple[str, str]:
    choices = _candidate_detail_choices(item, candidate)
    if not choices:
        return "current", _clean(item.get("text"))
    return max(choices, key=lambda pair: (_detail_quality(pair[1]), -len(pair[1])))


def _drop_low_significance_legal(
    normalized: dict[str, Any],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dropped: list[dict[str, Any]] = []

    def keep_items(items: list[dict[str, Any]], context: str) -> list[dict[str, Any]]:
        kept: list[dict[str, Any]] = []
        for item in items:
            kind = _clean(item.get("type")).upper()
            priority = int(item.get("priority") or 0)
            if kind == "LEGAL" and priority < LEGAL_PRIORITY_FLOOR:
                dropped.append({
                    "context": context,
                    "headline": item.get("headline"),
                    "priority": priority,
                    "reason": f"A4.5 LEGAL priority floor {LEGAL_PRIORITY_FLOOR}",
                })
                continue
            kept.append(item)
        return kept

    for group in normalized.get("leagues", []):
        items = group.get("items", []) if isinstance(group.get("items"), list) else []
        group["items"] = keep_items(items, _clean(group.get("league")))
    rebuilt_events = []
    for event in normalized.get("specialEvents", []):
        items = event.get("items", []) if isinstance(event.get("items"), list) else []
        event["items"] = keep_items(items, _clean(event.get("name")))
        if event["items"]:
            rebuilt_events.append(event)
    normalized["specialEvents"] = rebuilt_events

    if run_log is not None:
        run_log.setdefault("pipeline", {})["legalSignificanceDrops"] = dropped
    return normalized


def _labels(category: dict[str, Any]) -> list[str]:
    raw = category.get("labels") if isinstance(category.get("labels"), list) else []
    if not raw:
        raw = category.get("names") if isinstance(category.get("names"), list) else []
    return [_norm(x).replace(" ", "") for x in raw]


def _stat_index(labels: list[str], *aliases: str) -> int | None:
    wanted = {_norm(x).replace(" ", "") for x in aliases}
    for idx, label in enumerate(labels):
        if label in wanted:
            return idx
    return None


def _stat_value(stats: list[Any], idx: int | None) -> int | None:
    if idx is None or idx >= len(stats):
        return None
    return _intish(stats[idx])


def _football_standout_context(a44, summary: dict[str, Any], score_ctx: dict[str, Any]) -> str | None:
    """Build one grounded winner performance sentence from an ESPN football box score."""
    boxscore = summary.get("boxscore") if isinstance(summary.get("boxscore"), dict) else {}
    groups = boxscore.get("players") if isinstance(boxscore.get("players"), list) else []
    winner = _clean(score_ctx.get("winner"))
    loser = _clean(score_ctx.get("loser"))
    winner_score = (
        score_ctx.get("homeScore") if score_ctx.get("winnerSide") == "home"
        else score_ctx.get("awayScore")
    )
    loser_score = score_ctx.get("loserScore")
    suffix = ""
    if winner and loser and winner_score is not None and loser_score is not None:
        suffix = f" as {winner} beat {loser} {winner_score}-{loser_score}."

    candidates: list[tuple[float, str]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        team = group.get("team") if isinstance(group.get("team"), dict) else {}
        if not a44._team_matches(team, winner):
            continue
        categories = group.get("statistics") if isinstance(group.get("statistics"), list) else []
        for category in categories:
            if not isinstance(category, dict):
                continue
            cat = _norm(category.get("name") or category.get("displayName") or category.get("abbreviation"))
            labels = _labels(category)
            athletes = category.get("athletes") if isinstance(category.get("athletes"), list) else []
            yds_idx = _stat_index(labels, "YDS", "yards")
            td_idx = _stat_index(labels, "TD", "touchdowns")
            int_idx = _stat_index(labels, "INT", "interceptions")
            for entry in athletes:
                if not isinstance(entry, dict):
                    continue
                athlete = entry.get("athlete") if isinstance(entry.get("athlete"), dict) else {}
                name = _clean(athlete.get("displayName") or athlete.get("fullName") or entry.get("displayName"))
                stats = entry.get("stats") if isinstance(entry.get("stats"), list) else []
                if not name or not stats:
                    continue
                yds = _stat_value(stats, yds_idx)
                tds = _stat_value(stats, td_idx) or 0
                ints = _stat_value(stats, int_idx) or 0
                if "pass" in cat and yds is not None and (yds >= 150 or tds >= 2):
                    line = f"{name} threw for {yds} yards"
                    if tds:
                        line += f" and {tds} TD{'s' if tds != 1 else ''}"
                    candidates.append((yds + 75 * tds - 20 * ints + 50, line + suffix))
                elif "rush" in cat and yds is not None and (yds >= 80 or tds >= 2):
                    line = f"{name} ran for {yds} yards"
                    if tds:
                        line += f" and {tds} TD{'s' if tds != 1 else ''}"
                    candidates.append((yds + 85 * tds, line + suffix))
                elif "receiv" in cat and yds is not None and (yds >= 80 or tds >= 2):
                    line = f"{name} had {yds} receiving yards"
                    if tds:
                        line += f" and {tds} TD{'s' if tds != 1 else ''}"
                    candidates.append((yds + 85 * tds, line + suffix))
    if not candidates:
        return None
    return max(candidates, key=lambda row: row[0])[1]


def _fetch_ncaaf_summary(
    core,
    candidate: dict[str, Any],
    run_log: dict[str, Any],
    scoreboard_cache: dict[str, Any],
    summary_cache: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if not all(hasattr(core, name) for name in (
        "_candidate_game_date", "_fetch_espn_enrichment_json", "_match_espn_event"
    )):
        return None, None, None
    date_key = core._candidate_game_date(candidate)
    if not date_key:
        return None, None, None
    if date_key not in scoreboard_cache:
        url = (
            "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
            f"?dates={date_key}&limit=300"
        )
        scoreboard_cache[date_key] = core._fetch_espn_enrichment_json(
            candidate=candidate,
            run_log=run_log,
            source_id=f"a45-espn-ncaaf-scoreboard-{date_key}",
            kind="result-context-scoreboard",
            url=url,
        )
    scoreboard = scoreboard_cache.get(date_key)
    event = core._match_espn_event(candidate, scoreboard) if isinstance(scoreboard, dict) else None
    event_id = _clean(event.get("id")) if isinstance(event, dict) else ""
    if not event_id:
        return None, None, None
    summary_url = (
        "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
        f"?event={event_id}"
    )
    if event_id not in summary_cache:
        summary_cache[event_id] = core._fetch_espn_enrichment_json(
            candidate=candidate,
            run_log=run_log,
            source_id=f"a45-espn-ncaaf-summary-{event_id}",
            kind="result-context-summary",
            url=summary_url,
        )
    summary = summary_cache.get(event_id)
    return (summary if isinstance(summary, dict) else None), event_id, summary_url


def polish_result_details(
    a44,
    core,
    normalized: dict[str, Any],
    candidates: list[dict[str, Any]],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_id = {
        c.get("candidateId"): c for c in candidates
        if isinstance(c, dict) and isinstance(c.get("candidateId"), str)
    }
    log = None
    if run_log is not None:
        log = run_log.setdefault("pipeline", {}).setdefault(
            "resultCopyPolish",
            {"updated": [], "ncaafSummaryAttempts": 0, "ncaafSummaryMatches": 0},
        )

    scoreboard_cache: dict[str, Any] = {}
    summary_cache: dict[str, Any] = {}
    ncaaf_attempts = 0

    for group in normalized.get("leagues", []):
        league = _clean(group.get("league"))
        for item in group.get("items", []):
            if _clean(item.get("type")).upper() not in {"RESULT", "UPSET"}:
                continue
            candidate = next(
                (by_id.get(cid) for cid in item.get("candidateIds", []) if by_id.get(cid)),
                None,
            )
            if not isinstance(candidate, dict):
                continue

            before = _clean(item.get("text"))
            source, best = _best_grounded_detail(item, candidate)

            # Generic selected NCAAF results get a bounded chance to surface the
            # strongest winner performance from ESPN's game summary.
            if (
                league == "NCAAF"
                and ncaaf_attempts < MAX_NCAAF_CONTEXT_SUMMARIES
                and (_is_generic_score_restatement(best) or _detail_quality(best) < 6.0)
            ):
                score_ctx = a44._candidate_score_context(candidate)
                if score_ctx is not None:
                    ncaaf_attempts += 1
                    if log is not None:
                        log["ncaafSummaryAttempts"] = ncaaf_attempts
                    summary, event_id, summary_url = _fetch_ncaaf_summary(
                        core, candidate, run_log or {}, scoreboard_cache, summary_cache
                    )
                    if summary is not None:
                        context = _football_standout_context(a44, summary, score_ctx)
                        if context and _detail_quality(context) > _detail_quality(best):
                            best = context
                            source = "espn-ncaaf-summary"
                            if log is not None:
                                log["ncaafSummaryMatches"] = int(log.get("ncaafSummaryMatches") or 0) + 1
                            if event_id and summary_url:
                                a44._ensure_item_source(
                                    item, summary_url, f"a45-espn-ncaaf-summary-{event_id}"
                                )

            if best and best != before and _detail_quality(best) > _detail_quality(before):
                if not best.endswith((".", "!", "?")):
                    best += "."
                item["text"] = best[:360]
                if log is not None:
                    log["updated"].append({
                        "league": league,
                        "headline": item.get("headline"),
                        "before": before,
                        "after": item["text"],
                        "source": source,
                    })
    return normalized


def _patch_a44(a44) -> None:
    a44.PIPELINE_VERSION = PIPELINE_VERSION

    original_enrich = a44.enrich_result_context

    def enrich_a45(core, normalized, candidates, run_log=None):
        normalized = original_enrich(core, normalized, candidates, run_log)
        return polish_result_details(a44, core, normalized, candidates, run_log)

    a44.enrich_result_context = enrich_a45

    original_patch_a43 = a44._patch_a43

    def patch_a43_a45(a43):
        original_patch_a43(a43)
        a43.PIPELINE_VERSION = PIPELINE_VERSION

        # Restore the A4 significance policy before A4.3 performs its final
        # coverage-first selection, so a stronger unused story can take the slot.
        original_apply = a43.apply_quality_budget

        def apply_quality_a45(normalized, run_log=None):
            _drop_low_significance_legal(normalized, run_log)
            return original_apply(normalized, run_log)

        a43.apply_quality_budget = apply_quality_a45

        original_patch_a42 = a43._patch_a42

        def patch_a42_a45(a42):
            original_patch_a42(a42)
            a42.PIPELINE_VERSION = PIPELINE_VERSION
            original_configure = a42._configure_core

            def configure_a45(core):
                original_configure(core)
                core.EDITOR_INSTRUCTIONS = core.EDITOR_INSTRUCTIONS + "\n\n" + A45_EDITOR_ADDENDUM
                original_init = core.initial_run_log

                def initial_run_log_a45(generated_at, cutoff, model):
                    log = original_init(generated_at, cutoff, model)
                    log["pipelineVersion"] = PIPELINE_VERSION
                    log["configuration"]["legalStoryPolicy"] = (
                        f"LEGAL stories must clear priority {LEGAL_PRIORITY_FLOOR} after normalization"
                    )
                    log["configuration"]["resultCopyPolicy"] = (
                        "prefer natural grounded sports-news sentences over raw play-by-play; "
                        "bounded NCAAF winner-performance summaries for generic selected results"
                    )
                    return log

                core.initial_run_log = initial_run_log_a45

            a42._configure_core = configure_a45

        a43._patch_a42 = patch_a42_a45

    a44._patch_a43 = patch_a43_a45


def main() -> int:
    a44 = _load_a44()
    _patch_a44(a44)
    return a44.main()


if __name__ == "__main__":
    raise SystemExit(main())

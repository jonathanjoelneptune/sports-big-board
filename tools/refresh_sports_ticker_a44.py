#!/usr/bin/env python3
"""Sports Big Board A4.4 source-depth + grounded result-context overlay.

A4.4 sits on A4.3 and addresses the two issues exposed by the first live runs:

- keep a deeper 24-hour news inventory by explicitly asking ESPN for up to 50
  news articles per configured feed;
- preserve a larger raw editorial buffer before A3/A4 relevance and semantic
  dedupe reduce the feed to its final 30-35 items;
- strengthen cross-article semantic dedupe for sparse duplicate tournament
  stories such as two writeups of the same Serena/Venus doubles loss;
- enrich selected RESULT detail text with the strongest grounded candidate seed;
- for selected MLB close games/shutouts, use bounded ESPN scoreboard + summary
  lookups to add the go-ahead scoring play and shutout pitching context when
  those facts are available.

No web search is used by the ticker. All added result context is source-grounded.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.4-context-depth"
ESPN_NEWS_LIMIT = 50
REFILL_RAW_FLOOR = 40
REFILL_RAW_TARGET = 42
MAX_MLB_CONTEXT_SUMMARIES = 10

A44_EDITOR_ADDENDUM = r"""

A4.4 RESULT CONTEXT — LIVE TICKER DETAIL COPY
The headline identifies the story. The text field should explain what actually
happened whenever the candidate packet supplies the detail.

For RESULT / UPSET items:
- Do not merely repeat the final score in the text field.
- Prefer the decisive actor/play: who drove in or scored the go-ahead run, who
  scored the winning goal, who made the late stop, who threw the key touchdown,
  who delivered the walk-off, etc.
- For a baseball shutout, identify the starter/relievers responsible when pitching
  information is supplied.
- For a blowout, use a standout player/stat line when supplied instead of saying
  only that the winning team "dominated".
- For a draw, explain the grounded hook (goalkeeper duel, comeback, first goal,
  unbeaten streak, etc.).
- Never invent a player, pitcher, inning, statistic or decisive play. If the packet
  does not establish the detail, keep the text factual and generic.

The detail sentence may be longer than the headline. Keep it concise enough for a
quick-read ticker card, normally one sentence.
"""


def _load_a43():
    path = Path(__file__).with_name("refresh_sports_ticker_a43.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a43", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.3 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm(value: Any) -> str:
    text = _clean(value).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return " ".join(text.split())


def _action_families(value: Any) -> set[str]:
    text = _norm(value)
    families: dict[str, tuple[str, ...]] = {
        "win": (" win ", " wins ", " won ", " beat ", " beats ", " defeated ", " victory "),
        "loss": (" lose ", " loses ", " lost ", " loss ", " defeated ", " exit ", " eliminated "),
        "advance": (" advance ", " advances ", " advanced ", " reach ", " reaches "),
        "pole": (" pole ", " qualified first ", " qualifying first "),
        "penalty": (" penalty ", " penalized ", " drops three places ", " grid penalty "),
        "sign": (" sign ", " signs ", " signed ", " extension ", " contract "),
        "injury": (" injury ", " injured ", " strain ", " il ", " injured list "),
        "record": (" record ", " milestone ", " retires ", " retired "),
    }
    padded = f" {text} "
    return {name for name, terms in families.items() if any(term in padded for term in terms)}


def _round_marker(value: Any) -> str | None:
    text = _norm(value)
    patterns = [
        ("first-round", ("first round", "round 1", "opener")),
        ("second-round", ("second round", "round 2")),
        ("third-round", ("third round", "round 3")),
        ("round-of-16", ("round of 16", "fourth round")),
        ("quarterfinal", ("quarterfinal", "quarter final")),
        ("semifinal", ("semifinal", "semi final")),
        ("final", (" championship match", " tournament final", " final match")),
    ]
    for marker, terms in patterns:
        if any(term in text for term in terms):
            return marker
    return None


def _semantic_duplicate_a44(a43, a: dict[str, Any], b: dict[str, Any]) -> bool:
    """A4.3 dedupe plus sparse-article tournament duplicate handling.

    Explicit evidence of different rounds/opponents/scores wins over similarity so
    A4.4 cannot collapse two real matches by the same competitors.
    """
    same_context = a43._context_family(a) == a43._context_family(b)
    ia, ib = a["item"], b["item"]
    resultish = {"RESULT", "UPSET", "ADVANCEMENT"}
    result_pair = (
        _clean(ia.get("type")).upper() in resultish
        and _clean(ib.get("type")).upper() in resultish
    )
    if same_context and result_pair:
        entities_a = a43._meaningful_entities(a)
        entities_b = a43._meaningful_entities(b)
        shared = entities_a & entities_b
        scores_a = a43._score_pairs(a43._item_text(a))
        scores_b = a43._score_pairs(a43._item_text(b))
        if scores_a and scores_b and not (scores_a & scores_b):
            return False
        extras_a, extras_b = entities_a - shared, entities_b - shared
        if len(shared) >= 2 and extras_a and extras_b and not (extras_a & extras_b):
            return False
        round_a = _round_marker(a43._item_text(a))
        round_b = _round_marker(a43._item_text(b))
        if round_a and round_b and round_a != round_b:
            return False

    if a43._is_semantic_duplicate(a, b):
        return True
    if not same_context or not result_pair:
        return False

    entities_a = a43._meaningful_entities(a)
    entities_b = a43._meaningful_entities(b)
    shared = entities_a & entities_b
    if len(shared) < 2:
        return False
    if not (_action_families(a43._item_text(a)) & _action_families(a43._item_text(b))):
        return False
    similarity = a43._jaccard(
        a43._tokens(a43._item_text(a)),
        a43._tokens(a43._item_text(b)),
    )
    return similarity >= 0.10


def _intish(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(str(value)))
    except Exception:
        return None


def _candidate_score_context(candidate: dict[str, Any]) -> dict[str, Any] | None:
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    home = _clean(meta.get("homeTeam"))
    away = _clean(meta.get("awayTeam"))
    home_score = _intish(meta.get("homeScore"))
    away_score = _intish(meta.get("awayScore"))
    if not home or not away or home_score is None or away_score is None or home_score == away_score:
        return None
    if home_score > away_score:
        return {
            "home": home, "away": away, "homeScore": home_score, "awayScore": away_score,
            "winner": home, "loser": away, "winnerSide": "home", "loserScore": away_score,
            "margin": home_score - away_score,
        }
    return {
        "home": home, "away": away, "homeScore": home_score, "awayScore": away_score,
        "winner": away, "loser": home, "winnerSide": "away", "loserScore": home_score,
        "margin": away_score - home_score,
    }


def _candidate_rich_seed(candidate: dict[str, Any]) -> str | None:
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    choices: list[str] = []
    promotion = meta.get("storyPromotion") if isinstance(meta.get("storyPromotion"), dict) else {}
    enrichment = meta.get("resultEnrichment") if isinstance(meta.get("resultEnrichment"), dict) else {}
    for value in (
        promotion.get("summarySeed"),
        enrichment.get("summarySeed"),
        enrichment.get("decisiveMoment"),
        meta.get("fusedContext"),
    ):
        if isinstance(value, list):
            choices.extend(_clean(x) for x in value if _clean(x))
        elif _clean(value):
            choices.append(_clean(value))
    choices = [x for x in choices if 18 <= len(x) <= 280]
    if not choices:
        return None
    # Prefer copy containing a specific sports action over generic score restatement.
    cues = (
        " homered", " singled", " doubled", " scored", " threw", " touchdown",
        " field goal", " goal", " save", " saves", " walk-off", " walkoff",
        " rallied", " blocked", " struck out", " shutout", " pole", " penalty",
    )
    choices.sort(key=lambda x: (sum(cue in x.lower() for cue in cues), len(x)), reverse=True)
    return choices[0]


def _detail_quality(value: Any) -> int:
    text = _norm(value)
    if not text:
        return 0
    score = 1
    cues = (
        "homered", "singled", "doubled", "tripled", "scored", "threw", "innings",
        "strikeout", "struck out", "touchdown", "field goal", "goal", "saves",
        "walk off", "walkoff", "rallied", "blocked", "ahead for good", "shutout",
        "clean sheet", "pole", "penalty",
    )
    score += sum(2 for cue in cues if cue in text)
    if re.search(r"\b\d+(?:\.\d+)?\b", text):
        score += 1
    return score


def _extract_period_number(play: dict[str, Any]) -> int | None:
    period = play.get("period")
    if isinstance(period, dict):
        return _intish(period.get("number") or period.get("value"))
    return _intish(period or play.get("inning") or play.get("periodNumber"))


def _play_text(play: dict[str, Any]) -> str:
    for key in ("text", "shortText", "description", "headline"):
        value = _clean(play.get(key))
        if value:
            return value
    return ""


def _collect_scoring_plays(summary: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None, int | None, int | None]] = set()

    def visit(obj: Any, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(obj, list):
            for value in obj:
                visit(value, depth + 1)
            return
        if not isinstance(obj, dict):
            return
        text = _play_text(obj)
        hs = _intish(obj.get("homeScore"))
        aas = _intish(obj.get("awayScore"))
        if text and hs is not None and aas is not None:
            key = (text, hs, aas, _extract_period_number(obj))
            if key not in seen:
                seen.add(key)
                found.append(obj)
        for key in ("scoringPlays", "plays", "details", "events"):
            if key in obj:
                visit(obj.get(key), depth + 1)

    visit(summary)
    return found


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _go_ahead_context(summary: dict[str, Any], score_ctx: dict[str, Any]) -> str | None:
    plays = _collect_scoring_plays(summary)
    if not plays:
        return None
    winner_side = score_ctx["winnerSide"]
    prev_home = prev_away = 0
    go_ahead: dict[str, Any] | None = None
    for play in plays:
        home = _intish(play.get("homeScore"))
        away = _intish(play.get("awayScore"))
        if home is None or away is None:
            continue
        before_winner = prev_home if winner_side == "home" else prev_away
        before_loser = prev_away if winner_side == "home" else prev_home
        after_winner = home if winner_side == "home" else away
        after_loser = away if winner_side == "home" else home
        if after_winner > after_loser and before_winner <= before_loser:
            go_ahead = play
        prev_home, prev_away = home, away
    if not go_ahead:
        return None
    text = _play_text(go_ahead).rstrip(". ")
    if not text:
        return None
    inning = _extract_period_number(go_ahead)
    inning_clause = f" in the {_ordinal(inning)}" if inning else ""
    return f"{text} to put {score_ctx['winner']} ahead for good{inning_clause}."


def _team_aliases(team: dict[str, Any]) -> set[str]:
    return {
        _norm(team.get(key))
        for key in ("displayName", "name", "shortDisplayName", "abbreviation", "location")
        if _norm(team.get(key))
    }


def _team_matches(team: dict[str, Any], wanted: str) -> bool:
    target = _norm(wanted)
    if not target:
        return False
    for alias in _team_aliases(team):
        if alias == target or alias in target or target in alias:
            return True
    return False


def _pitching_lines(summary: dict[str, Any], winner: str) -> list[tuple[str, str]]:
    boxscore = summary.get("boxscore") if isinstance(summary.get("boxscore"), dict) else {}
    groups = boxscore.get("players") if isinstance(boxscore.get("players"), list) else []
    for group in groups:
        if not isinstance(group, dict):
            continue
        team = group.get("team") if isinstance(group.get("team"), dict) else {}
        if not _team_matches(team, winner):
            continue
        categories = group.get("statistics") if isinstance(group.get("statistics"), list) else []
        for category in categories:
            if not isinstance(category, dict):
                continue
            cat_name = _norm(
                category.get("name") or category.get("displayName") or category.get("abbreviation")
            )
            if "pitch" not in cat_name:
                continue
            labels = category.get("labels") if isinstance(category.get("labels"), list) else []
            names = category.get("names") if isinstance(category.get("names"), list) else []
            ip_index = 0
            for idx, label in enumerate(labels or names):
                if _norm(label) in {"ip", "innings pitched", "inningspitched"}:
                    ip_index = idx
                    break
            lines: list[tuple[str, str]] = []
            athletes = category.get("athletes") if isinstance(category.get("athletes"), list) else []
            for entry in athletes:
                if not isinstance(entry, dict):
                    continue
                athlete = entry.get("athlete") if isinstance(entry.get("athlete"), dict) else {}
                name = _clean(athlete.get("displayName") or athlete.get("fullName") or entry.get("displayName"))
                stats = entry.get("stats") if isinstance(entry.get("stats"), list) else []
                if not name or ip_index >= len(stats):
                    continue
                ip = _clean(stats[ip_index])
                if not ip or ip in {"0", "0.0", "0.00", "-"}:
                    continue
                lines.append((name, ip))
            if lines:
                return lines
    return []


def _shutout_context(summary: dict[str, Any], score_ctx: dict[str, Any]) -> str | None:
    if score_ctx.get("loserScore") != 0:
        return None
    lines = _pitching_lines(summary, score_ctx["winner"])
    if not lines:
        return None
    if len(lines) == 1:
        name, ip = lines[0]
        return f"{name} threw {ip} scoreless innings to complete the shutout."
    starter, starter_ip = lines[0]
    relievers = [name for name, _ in lines[1:]]
    if len(relievers) <= 3:
        if len(relievers) == 1:
            tail = relievers[0]
        else:
            tail = ", ".join(relievers[:-1]) + f" and {relievers[-1]}"
        return f"{starter} threw {starter_ip} scoreless innings; {tail} finished the shutout."
    return f"{starter} threw {starter_ip} scoreless innings before the bullpen finished the shutout."


def _ensure_item_source(item: dict[str, Any], url: str, source_id: str) -> None:
    urls = item.setdefault("sourceUrls", [])
    if isinstance(urls, list) and url not in urls:
        urls.append(url)
    sources = item.setdefault("sources", [])
    if isinstance(sources, list) and not any(isinstance(s, dict) and s.get("url") == url for s in sources):
        sources.append({"provider": "ESPN", "sourceId": source_id, "url": url})


def _fetch_mlb_summary(
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
        scoreboard_url = (
            "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
            f"?dates={date_key}&limit=100"
        )
        scoreboard_cache[date_key] = core._fetch_espn_enrichment_json(
            candidate=candidate,
            run_log=run_log,
            source_id=f"a44-espn-mlb-scoreboard-{date_key}",
            kind="result-context-scoreboard",
            url=scoreboard_url,
        )
    scoreboard = scoreboard_cache.get(date_key)
    event = core._match_espn_event(candidate, scoreboard) if isinstance(scoreboard, dict) else None
    event_id = _clean(event.get("id")) if isinstance(event, dict) else ""
    if not event_id:
        return None, None, None
    summary_url = f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event={event_id}"
    if event_id not in summary_cache:
        summary_cache[event_id] = core._fetch_espn_enrichment_json(
            candidate=candidate,
            run_log=run_log,
            source_id=f"a44-espn-mlb-summary-{event_id}",
            kind="result-context-summary",
            url=summary_url,
        )
    summary = summary_cache.get(event_id)
    return (summary if isinstance(summary, dict) else None), event_id, summary_url


def enrich_result_context(
    core,
    normalized: dict[str, Any],
    candidates: list[dict[str, Any]],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Upgrade selected result detail sentences with grounded context."""
    by_id = {
        c.get("candidateId"): c for c in candidates
        if isinstance(c, dict) and isinstance(c.get("candidateId"), str)
    }
    log = None
    if run_log is not None:
        log = run_log.setdefault("pipeline", {}).setdefault(
            "resultContextEnrichment",
            {"updated": [], "mlbSummaryAttempts": 0, "mlbSummaryMatches": 0},
        )

    scoreboard_cache: dict[str, Any] = {}
    summary_cache: dict[str, Any] = {}
    summary_attempts = 0

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

            current = _clean(item.get("text"))
            best = current
            best_source = "editor"

            seed = _candidate_rich_seed(candidate)
            if seed and _detail_quality(seed) > _detail_quality(best):
                best = seed
                best_source = "candidate-story-context"

            score_ctx = _candidate_score_context(candidate)
            needs_mlb_summary = (
                league == "MLB"
                and score_ctx is not None
                and summary_attempts < MAX_MLB_CONTEXT_SUMMARIES
                and (score_ctx["margin"] <= 2 or score_ctx["loserScore"] == 0)
            )
            if needs_mlb_summary:
                summary_attempts += 1
                if log is not None:
                    log["mlbSummaryAttempts"] = summary_attempts
                summary, event_id, summary_url = _fetch_mlb_summary(
                    core, candidate, run_log or {}, scoreboard_cache, summary_cache
                )
                if summary is not None:
                    if log is not None:
                        log["mlbSummaryMatches"] = int(log.get("mlbSummaryMatches") or 0) + 1
                    context = _shutout_context(summary, score_ctx)
                    if context is None and score_ctx["margin"] <= 2:
                        context = _go_ahead_context(summary, score_ctx)
                    if context and _detail_quality(context) >= _detail_quality(best):
                        best = context
                        best_source = "espn-mlb-summary"
                        if summary_url and event_id:
                            _ensure_item_source(item, summary_url, f"a44-espn-mlb-summary-{event_id}")

            if best and best != current:
                item["text"] = best[:360]
                if log is not None:
                    log["updated"].append({
                        "league": league,
                        "headline": item.get("headline"),
                        "before": current,
                        "after": item["text"],
                        "source": best_source,
                    })
    return normalized


def _patch_espn_news_depth(core) -> None:
    for source in getattr(core, "ESPN_SOURCES", []):
        if not isinstance(source, dict):
            continue
        url = _clean(source.get("url"))
        if not url or "/news" not in url:
            continue
        if re.search(r"(?:\?|&)limit=", url):
            continue
        source["url"] = url + ("&" if "?" in url else "?") + f"limit={ESPN_NEWS_LIMIT}"


def _patch_a43(a43) -> None:
    # Increase raw inventory so normal relevance/dedupe losses can still leave a
    # healthy 30-35 final ribbon.
    a43.PIPELINE_VERSION = PIPELINE_VERSION
    a43.REFILL_RAW_FLOOR = REFILL_RAW_FLOOR
    a43.REFILL_RAW_TARGET = REFILL_RAW_TARGET
    a43.A43_EDITOR_ADDENDUM = a43.A43_EDITOR_ADDENDUM + A44_EDITOR_ADDENDUM

    original_duplicate = a43._is_semantic_duplicate
    a43._is_semantic_duplicate = lambda a, b: (
        original_duplicate(a, b) or _semantic_duplicate_a44_without_recursion(a43, original_duplicate, a, b)
    )

    original_patch = a43._patch_a42

    def patch_a44(a42):
        original_patch(a42)
        original_configure = a42._configure_core

        def configure_a44(core):
            original_configure(core)
            _patch_espn_news_depth(core)
            core.EDITOR_INSTRUCTIONS = core.EDITOR_INSTRUCTIONS + "\n\n" + A44_EDITOR_ADDENDUM

            original_init = core.initial_run_log
            original_normalize = core.normalize_model_output

            def initial_run_log_a44(generated_at, cutoff, model):
                log = original_init(generated_at, cutoff, model)
                log["pipelineVersion"] = PIPELINE_VERSION
                log["configuration"]["espnNewsLimit"] = ESPN_NEWS_LIMIT
                log["configuration"]["rawEditorialBuffer"] = (
                    f"refill raw floor {REFILL_RAW_FLOOR}; ideal {REFILL_RAW_TARGET}; final 30-35"
                )
                log["configuration"]["resultContextPolicy"] = (
                    "prefer grounded decisive/player context; selected MLB close games/shutouts may use "
                    "bounded ESPN scoreboard+summary enrichment"
                )
                return log

            def normalize_a44(model_output, candidates, generated_at, run_log):
                normalized = original_normalize(model_output, candidates, generated_at, run_log)
                return enrich_result_context(core, normalized, candidates, run_log)

            core.initial_run_log = initial_run_log_a44
            core.normalize_model_output = normalize_a44

        a42._configure_core = configure_a44

    a43._patch_a42 = patch_a44


def _semantic_duplicate_a44_without_recursion(a43, original_duplicate, a, b) -> bool:
    same_context = a43._context_family(a) == a43._context_family(b)
    ia, ib = a["item"], b["item"]
    resultish = {"RESULT", "UPSET", "ADVANCEMENT"}
    result_pair = (
        _clean(ia.get("type")).upper() in resultish
        and _clean(ib.get("type")).upper() in resultish
    )
    if same_context and result_pair:
        entities_a = a43._meaningful_entities(a)
        entities_b = a43._meaningful_entities(b)
        shared = entities_a & entities_b
        scores_a = a43._score_pairs(a43._item_text(a))
        scores_b = a43._score_pairs(a43._item_text(b))
        if scores_a and scores_b and not (scores_a & scores_b):
            return False
        extras_a, extras_b = entities_a - shared, entities_b - shared
        if len(shared) >= 2 and extras_a and extras_b and not (extras_a & extras_b):
            return False
        round_a = _round_marker(a43._item_text(a))
        round_b = _round_marker(a43._item_text(b))
        if round_a and round_b and round_a != round_b:
            return False

    if original_duplicate(a, b):
        return True
    if not same_context or not result_pair:
        return False
    entities_a = a43._meaningful_entities(a)
    entities_b = a43._meaningful_entities(b)
    if len(entities_a & entities_b) < 2:
        return False
    if not (_action_families(a43._item_text(a)) & _action_families(a43._item_text(b))):
        return False
    similarity = a43._jaccard(a43._tokens(a43._item_text(a)), a43._tokens(a43._item_text(b)))
    return similarity >= 0.10


def main() -> int:
    a43 = _load_a43()
    _patch_a43(a43)
    return a43.main()


if __name__ == "__main__":
    raise SystemExit(main())

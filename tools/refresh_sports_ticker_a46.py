#!/usr/bin/env python3
"""Sports Big Board A4.6 progression-dedupe + event-identity overlay on A4.5.

A4.6 deliberately preserves the now-working 30-35 headline architecture. It fixes
correctness problems exposed by the first A4.5 live run:

- collapse successive updates in the same injury/status thread so an older
  "left game" or "missed second game" headline does not coexist with a newer,
  stronger "placed on IL" or "missed third game" update;
- reject procedural LEGAL stories even when the editor gives them an inflated
  priority, unless the development itself is materially consequential;
- harden NCAAF ESPN event matching before any player-stat context is copied into
  ticker text: BOTH teams and, when available, the final score must match;
- validate the returned ESPN summary header against the candidate before using its
  box score, preventing cross-game player/stat contamination.

No web search is added. This remains a thin overlay on A4.5/A4.4/A4.3/A4.2.
"""
from __future__ import annotations

import importlib.util
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.6-progression-identity"
PROGRESSION_WINDOW_HOURS = 18.0

A46_EDITOR_ADDENDUM = r"""

A4.6 STORY PROGRESSION + EVENT IDENTITY — CRITICAL
Do NOT change the global 30-35 headline budget or the established coverage mix.

STORY PROGRESSION
- When multiple candidates are successive updates to the SAME underlying player
  status/injury thread, keep only the newest materially strongest development.
- Example: "Player exits with hamstring discomfort" followed hours later by
  "Player placed on IL with hamstring strain" is ONE current ticker story. Keep
  the IL placement; the earlier exit may be summarized in the detail sentence.
- Likewise, "misses second straight game" followed by "misses third straight game"
  should become only the newest update.
- Do not collapse unrelated injuries, different players on the same team, or truly
  independent developments.

EVENT IDENTITY
- Never transfer a player/stat line from a different game.
- Any game-summary/box-score context must belong to the exact selected result.
- BOTH teams must match the selected candidate; when final scores are available,
  they must match too. If identity cannot be proven, keep the existing grounded
  result sentence and omit the extra stat rather than guessing.

LEGAL / OFF-FIELD
- A routine procedural filing, hearing, planned plea change, or court scheduling
  update is not ticker-worthy merely because it involves a famous athlete.
- Keep legal stories only for materially consequential developments such as an
  arrest/charge, conviction/acquittal, sentence, major settlement/ruling, or a
  direct sports-status consequence.
"""

# Injury/status words used only to decide whether two otherwise matching stories
# belong to the same thread. They never create user-facing facts.
INJURY_CUES = {
    "achilles", "ankle", "arm", "back", "biceps", "calf", "concussion",
    "elbow", "foot", "groin", "hamstring", "hand", "head", "hip", "knee",
    "leg", "neck", "oblique", "quad", "shoulder", "wrist",
    "illness", "soreness", "strain", "sprain", "fracture", "torn", "tear",
}

PROCEDURAL_LEGAL_CUES = (
    "plans to change plea", "plan to change plea", "plans to change not guilty",
    "plans to change not-guilty", "court documents say", "court documents show",
    "court filing", "filed a motion", "hearing scheduled", "hearing set",
    "status hearing", "arraignment scheduled", "plea hearing",
)
MATERIAL_LEGAL_CUES = (
    "arrested", "charged with", "indicted", "convicted", "acquitted",
    "sentenced", "sentence of", "suspended", "banned", "major settlement",
    "settlement reached", "found liable", "dismissed charges", "charges dismissed",
)


def _load_a45():
    path = Path(__file__).with_name("refresh_sports_ticker_a45.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a45", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.5 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm(value: Any) -> str:
    text = _clean(value).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return " ".join(text.split())


def _intish(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(str(value)))
    except Exception:
        return None


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
    return _norm(
        " ".join(
            _clean(item.get(key))
            for key in ("headline", "text", "freshnessBasis")
        )
    )


def _entity_set(item: dict[str, Any]) -> set[str]:
    raw = item.get("entities") if isinstance(item.get("entities"), list) else []
    return {_norm(value) for value in raw if _norm(value)}


def _injury_cues(item: dict[str, Any]) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", _item_blob(item)))
    return tokens & INJURY_CUES


def _progression_strength(item: dict[str, Any]) -> int:
    """Rank how definitive a status update is; higher means newer state matters more."""
    text = _item_blob(item)
    score = 0
    rules = (
        (120, ("out for season", "season ending", "season-ending")),
        (115, ("undergo surgery", "underwent surgery", "surgery scheduled")),
        (110, ("placed on injured list", "placed on the injured list", "placed on il", "returns to il", "return to il")),
        (105, ("diagnosed with", "fracture", "torn ", "tear ")),
        (95, ("will miss time", "expected to miss", "to miss time", "ruled out")),
        (85, ("misses another game", "held out", "remains out", "misses third", "miss third")),
        (70, ("misses second", "miss second", "questionable", "doubtful")),
        (55, ("exits", "exit ", "leaves", "left ", "discomfort", "soreness")),
    )
    for value, cues in rules:
        if any(cue in text for cue in cues):
            score = max(score, value)

    # Injury-list copy often inserts the player name between the status verb and
    # "injured list" (for example, "placed Grisham on the injured list").
    if "injured list" in text and any(
        cue in text for cue in ("placed", "put ", "returns", "returned", "return ", "goes back")
    ):
        score = max(score, 110)
    if re.search(r"\b(?:placed|put|returns?|returned|goes back)\b.{0,80}\bil\b", text):
        score = max(score, 110)

    # Consecutive-game progressions should naturally prefer the latest count.
    m = re.search(r"\b(\d+)(?:st|nd|rd|th)?\s+straight\s+game", text)
    if m:
        score = max(score, 80 + min(int(m.group(1)), 15))
    word_counts = {
        "second straight game": 82,
        "third straight game": 83,
        "fourth straight game": 84,
        "fifth straight game": 85,
    }
    for cue, value in word_counts.items():
        if cue in text:
            score = max(score, value)
    return score


def _progression_rank(row: dict[str, Any]) -> tuple[int, float, int]:
    item = row.get("item") if isinstance(row.get("item"), dict) else {}
    dt = _parse_time(item.get("occurredAt"))
    timestamp = dt.timestamp() if dt else 0.0
    return (
        _progression_strength(item),
        timestamp,
        int(item.get("priority") or 0),
    )


def _same_progression(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Conservative same-thread test for successive INJURY status updates."""
    if _norm(a.get("context")) != _norm(b.get("context")):
        return False
    ia = a.get("item") if isinstance(a.get("item"), dict) else {}
    ib = b.get("item") if isinstance(b.get("item"), dict) else {}
    if _clean(ia.get("type")).upper() != "INJURY" or _clean(ib.get("type")).upper() != "INJURY":
        return False

    shared_entities = _entity_set(ia) & _entity_set(ib)
    # Current live duplicates have both the athlete and team in common. Requiring
    # two exact shared entities avoids collapsing different injured players on one team.
    if len(shared_entities) < 2:
        return False

    cues_a, cues_b = _injury_cues(ia), _injury_cues(ib)
    if cues_a and cues_b and not (cues_a & cues_b):
        return False

    da = _parse_time(ia.get("occurredAt"))
    db = _parse_time(ib.get("occurredAt"))
    if da is not None and db is not None:
        hours = abs((da - db).total_seconds()) / 3600.0
        if hours > PROGRESSION_WINDOW_HOURS:
            return False

    # Require at least one status/progression cue so two unrelated injury articles
    # about the same athlete are not collapsed solely by entity overlap.
    combined = f"{_item_blob(ia)} {_item_blob(ib)}"
    progression_words = (
        "injured list", " il ", "exits", "left ", "leaves", "misses", "missed",
        "held out", "remains out", "discomfort", "soreness", "strain", "sprain",
        "expected to miss", "will miss", "ruled out",
    )
    padded = f" {combined} "
    return any(cue in padded for cue in progression_words)


def collapse_progression_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collapse same-thread injury updates before A4.3 global selection."""
    kept: list[dict[str, Any]] = []
    drops: list[dict[str, Any]] = []

    for row in rows:
        match_index = next(
            (idx for idx, existing in enumerate(kept) if _same_progression(row, existing)),
            None,
        )
        if match_index is None:
            kept.append(row)
            continue

        existing = kept[match_index]
        if _progression_rank(row) > _progression_rank(existing):
            winner, loser = row, existing
            kept[match_index] = row
        else:
            winner, loser = existing, row

        loser_item = loser["item"]
        winner_item = winner["item"]
        drops.append({
            "context": loser.get("context"),
            "headline": loser_item.get("headline"),
            "candidateIds": loser_item.get("candidateIds", []),
            "duplicateOf": winner_item.get("headline"),
            "duplicateCandidateIds": winner_item.get("candidateIds", []),
            "reason": "A4.6 superseded injury/status progression",
        })

    return kept, drops


def _is_procedural_legal(item: dict[str, Any]) -> bool:
    if _clean(item.get("type")).upper() != "LEGAL":
        return False
    text = _item_blob(item)
    if any(cue in text for cue in MATERIAL_LEGAL_CUES):
        return False
    return any(cue in text for cue in PROCEDURAL_LEGAL_CUES)


def drop_procedural_legal(
    normalized: dict[str, Any],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Remove routine legal procedure regardless of model-assigned priority."""
    dropped: list[dict[str, Any]] = []

    def filter_items(items: list[dict[str, Any]], context: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in items:
            if _is_procedural_legal(item):
                dropped.append({
                    "context": context,
                    "headline": item.get("headline"),
                    "priority": item.get("priority"),
                    "reason": "A4.6 routine procedural LEGAL development",
                })
            else:
                out.append(item)
        return out

    for group in normalized.get("leagues", []):
        items = group.get("items", []) if isinstance(group.get("items"), list) else []
        group["items"] = filter_items(items, _clean(group.get("league")))
    rebuilt = []
    for event in normalized.get("specialEvents", []):
        items = event.get("items", []) if isinstance(event.get("items"), list) else []
        event["items"] = filter_items(items, _clean(event.get("name")))
        if event["items"]:
            rebuilt.append(event)
    normalized["specialEvents"] = rebuilt

    if run_log is not None:
        run_log.setdefault("pipeline", {})["proceduralLegalDrops"] = dropped
    return normalized


def _team_aliases(team: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for key in ("displayName", "shortDisplayName", "name", "location", "abbreviation"):
        value = _norm(team.get(key))
        if value:
            aliases.add(value)
    return aliases


def _team_matches_wanted(team: dict[str, Any], wanted: str) -> bool:
    target = _norm(wanted)
    if not target:
        return False
    aliases = _team_aliases(team)
    if target in aliases:
        return True
    target_tokens = set(target.split())
    if len(target_tokens) < 2:
        return False
    for alias in aliases:
        alias_tokens = set(alias.split())
        if len(alias_tokens) < 2:
            continue
        # Require at least two common identity tokens; this avoids matching
        # "Texas" to "Texas State" or another same-state school.
        common = target_tokens & alias_tokens
        if len(common) >= 2 and (
            target_tokens <= alias_tokens or alias_tokens <= target_tokens
        ):
            return True
    return False


def _event_competitors(event: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    competitions = event.get("competitions") if isinstance(event.get("competitions"), list) else []
    competition = competitions[0] if competitions and isinstance(competitions[0], dict) else {}
    competitors = competition.get("competitors") if isinstance(competition.get("competitors"), list) else []
    home = away = None
    for comp in competitors:
        if not isinstance(comp, dict):
            continue
        side = _norm(comp.get("homeAway"))
        if side == "home":
            home = comp
        elif side == "away":
            away = comp
    return home, away


def _competitor_team(comp: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(comp, dict):
        return {}
    return comp.get("team") if isinstance(comp.get("team"), dict) else {}


def _competitor_score(comp: dict[str, Any] | None) -> int | None:
    if not isinstance(comp, dict):
        return None
    score = comp.get("score")
    if isinstance(score, dict):
        score = score.get("value") or score.get("displayValue")
    return _intish(score)


def _strict_event_identity(candidate: dict[str, Any], event: dict[str, Any]) -> bool:
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    wanted_home = _clean(meta.get("homeTeam"))
    wanted_away = _clean(meta.get("awayTeam"))
    if not wanted_home or not wanted_away:
        return False

    home, away = _event_competitors(event)
    if not home or not away:
        return False
    if not _team_matches_wanted(_competitor_team(home), wanted_home):
        return False
    if not _team_matches_wanted(_competitor_team(away), wanted_away):
        return False

    wanted_home_score = _intish(meta.get("homeScore"))
    wanted_away_score = _intish(meta.get("awayScore"))
    event_home_score = _competitor_score(home)
    event_away_score = _competitor_score(away)
    if wanted_home_score is not None and event_home_score is not None:
        if wanted_home_score != event_home_score:
            return False
    if wanted_away_score is not None and event_away_score is not None:
        if wanted_away_score != event_away_score:
            return False
    return True


def _strict_match_espn_event(candidate: dict[str, Any], scoreboard: dict[str, Any]) -> dict[str, Any] | None:
    matches = [
        event for event in scoreboard.get("events", []) if isinstance(scoreboard, dict)
        and isinstance(event, dict) and _strict_event_identity(candidate, event)
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _summary_identity_event(summary: dict[str, Any]) -> dict[str, Any] | None:
    header = summary.get("header") if isinstance(summary.get("header"), dict) else {}
    competitions = header.get("competitions") if isinstance(header.get("competitions"), list) else []
    if not competitions or not isinstance(competitions[0], dict):
        return None
    return {"competitions": [competitions[0]]}


def _summary_matches_candidate(candidate: dict[str, Any], summary: dict[str, Any]) -> bool:
    event = _summary_identity_event(summary)
    return bool(event and _strict_event_identity(candidate, event))


def _fetch_ncaaf_summary_strict(
    core,
    candidate: dict[str, Any],
    run_log: dict[str, Any],
    scoreboard_cache: dict[str, Any],
    summary_cache: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """A4.5 NCAAF summary fetch with exact team+score identity validation."""
    if not all(hasattr(core, name) for name in (
        "_candidate_game_date", "_fetch_espn_enrichment_json"
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
            source_id=f"a46-espn-ncaaf-scoreboard-{date_key}",
            kind="result-context-scoreboard-strict",
            url=url,
        )
    scoreboard = scoreboard_cache.get(date_key)
    event = _strict_match_espn_event(candidate, scoreboard) if isinstance(scoreboard, dict) else None
    event_id = _clean(event.get("id")) if isinstance(event, dict) else ""
    if not event_id:
        if isinstance(run_log, dict):
            run_log.setdefault("pipeline", {}).setdefault("eventIdentityRejects", []).append({
                "candidateId": candidate.get("candidateId"),
                "reason": "no unique ESPN NCAAF event matched both teams and final score",
            })
        return None, None, None

    summary_url = (
        "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
        f"?event={event_id}"
    )
    if event_id not in summary_cache:
        summary_cache[event_id] = core._fetch_espn_enrichment_json(
            candidate=candidate,
            run_log=run_log,
            source_id=f"a46-espn-ncaaf-summary-{event_id}",
            kind="result-context-summary-strict",
            url=summary_url,
        )
    summary = summary_cache.get(event_id)
    if not isinstance(summary, dict) or not _summary_matches_candidate(candidate, summary):
        if isinstance(run_log, dict):
            run_log.setdefault("pipeline", {}).setdefault("eventIdentityRejects", []).append({
                "candidateId": candidate.get("candidateId"),
                "eventId": event_id,
                "reason": "ESPN summary header failed exact candidate team/score validation",
            })
        return None, event_id, summary_url
    return summary, event_id, summary_url


def _patch_a45(a45) -> None:
    # A4.5 resolves these globals at runtime, so the strict NCAAF matcher and legal
    # policy can be replaced without copying A4.5's large polish implementation.
    a45.PIPELINE_VERSION = PIPELINE_VERSION
    a45.A45_EDITOR_ADDENDUM = a45.A45_EDITOR_ADDENDUM + A46_EDITOR_ADDENDUM
    a45._fetch_ncaaf_summary = _fetch_ncaaf_summary_strict

    original_legal = a45._drop_low_significance_legal

    def legal_a46(normalized, run_log=None):
        normalized = original_legal(normalized, run_log)
        return drop_procedural_legal(normalized, run_log)

    a45._drop_low_significance_legal = legal_a46

    # Intercept A4.4's A4.3 loader so progression dedupe runs inside A4.3's
    # apply_quality_budget BEFORE the final 30-35 selection. That lets other valid
    # stories replace superseded updates instead of simply shrinking the feed.
    original_load_a44 = a45._load_a44

    def load_a44_a46():
        a44 = original_load_a44()
        original_load_a43 = a44._load_a43

        def load_a43_a46():
            a43 = original_load_a43()
            original_dedupe = a43._dedupe_rows

            def dedupe_a46(rows):
                collapsed, progression_drops = collapse_progression_rows(rows)
                kept, semantic_drops = original_dedupe(collapsed)
                return kept, progression_drops + semantic_drops

            a43._dedupe_rows = dedupe_a46
            return a43

        a44._load_a43 = load_a43_a46
        return a44

    a45._load_a44 = load_a44_a46


def main() -> int:
    a45 = _load_a45()
    _patch_a45(a45)
    return a45.main()


if __name__ == "__main__":
    raise SystemExit(main())

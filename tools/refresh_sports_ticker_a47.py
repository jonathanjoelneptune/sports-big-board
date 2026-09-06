#!/usr/bin/env python3
"""Sports Big Board A4.7 event-affinity + cross-game identity overlay on A4.6.

A4.7 freezes the working 30-35 headline architecture and only adds correctness
checks learned from the first live A4.6 output:

- fail closed when one rendered league RESULT/UPSET carries multiple ESPN game IDs;
- fail closed when structured source score identity disagrees with rendered score;
- reject explicit winner reversals when the selected candidate/source establishes the
  opposite winner;
- enforce named Special Event affinity so Monaco GP news cannot be filed under the
  Italian Grand Prix merely because both are Formula 1 stories.

No new web search or discovery source is added. Invalid rows are removed before the
existing A4.3 global selector, allowing another grounded candidate to take the slot.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "A4.7-event-affinity-game-isolation"

A47_EDITOR_ADDENDUM = r"""

A4.7 EVENT AFFINITY + GAME ISOLATION — CRITICAL
Do NOT change the established 30-35 headline budget, source depth, coverage caps,
or headline-length contract.

GAME IDENTITY
- A league RESULT/UPSET must describe exactly one game.
- Never combine context from two games between the same teams, including series,
  rematches or doubleheaders.
- If structured teams/scores are supplied, the rendered score and winner must agree.
- If evidence conflicts, omit the item rather than trying to reconcile or guess.

SPECIAL EVENT AFFINITY
- A story grouped under a named Special Event must actually belong to that event.
- Example: Monaco Grand Prix appeal news is Formula 1 news, but it is NOT Italian
  Grand Prix news and must not be placed in the Italian Grand Prix bucket.
- Same-sport affinity alone is insufficient. The story must contain the named event's
  distinguishing identity (for example Italian/Monza, US Open, UFC 332).
"""

GENERIC_SPECIAL_NAMES = {
    "tennis", "golf", "formula 1", "f1", "motorsport", "motor racing",
    "mma", "ufc", "boxing", "racing", "auto racing",
}
GENERIC_EVENT_TOKENS = {
    "the", "a", "an", "of", "at", "in", "on", "round", "day",
    "grand", "prix", "gp", "open", "championship", "championships",
    "tournament", "cup", "series", "final", "finals", "race", "racing",
    "tennis", "golf", "formula", "f1", "mma", "ufc", "boxing",
}
RESULT_TYPES = {"RESULT", "UPSET"}
WIN_VERBS = (
    "beat", "beats", "defeat", "defeats", "defeated", "edge", "edges", "edged",
    "top", "tops", "topped", "down", "downs", "downed", "outlast", "outlasts",
    "rout", "routs", "routed", "shut out", "shuts out", "blank", "blanks",
)
GENERIC_TEAM_LAST_TOKENS = {
    "city", "united", "state", "fc", "sc", "club", "town", "county",
    "university", "college",
}


def _load_a46():
    path = Path(__file__).with_name("refresh_sports_ticker_a46.py")
    spec = importlib.util.spec_from_file_location("sports_ticker_a46", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load A4.6 ticker overlay from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _norm(value: Any) -> str:
    text = _clean(value).lower().replace("’", "'")
    text = text.replace("u.s.", "us").replace("u. s.", "us")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    text = re.sub(r"\bu\s+s\b", "us", text)
    return " ".join(text.split())


def _intish(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(str(value)))
    except Exception:
        return None


def _item_blob(item: dict[str, Any]) -> str:
    entities = item.get("entities") if isinstance(item.get("entities"), list) else []
    return _norm(" ".join([
        _clean(item.get("headline")),
        _clean(item.get("text")),
        _clean(item.get("freshnessBasis")),
        " ".join(_clean(x) for x in entities),
    ]))


def _score_pairs(value: Any) -> set[tuple[int, int]]:
    text = _clean(value)
    return {
        (int(a), int(b))
        for a, b in re.findall(r"(?<!\d)(\d{1,3})\s*[-–—]\s*(\d{1,3})(?!\d)", text)
    }


def _unordered_score(pair: tuple[int, int]) -> tuple[int, int]:
    return tuple(sorted(pair))


def _candidate_objects(item: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cid in item.get("candidateIds", []) if isinstance(item.get("candidateIds"), list) else []:
        candidate = by_id.get(cid)
        if isinstance(candidate, dict):
            out.append(candidate)
    return out


def _structured_context(candidate: dict[str, Any]) -> dict[str, Any] | None:
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    home = _clean(meta.get("homeTeam"))
    away = _clean(meta.get("awayTeam"))
    hs = _intish(meta.get("homeScore"))
    aws = _intish(meta.get("awayScore"))
    if not home or not away or hs is None or aws is None:
        return None
    return {
        "home": home,
        "away": away,
        "homeScore": hs,
        "awayScore": aws,
        "matchId": _clean(meta.get("matchId") or meta.get("eventId") or meta.get("gameId")),
    }


def _walk_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            urls.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            urls.extend(_walk_urls(child))
    elif isinstance(value, list):
        for child in value:
            urls.extend(_walk_urls(child))
    return urls


def _espn_game_ids(item: dict[str, Any], candidates: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    urls = _walk_urls(item)
    for candidate in candidates:
        urls.extend(_walk_urls(candidate.get("sourceRecords")))
        meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        urls.extend(_walk_urls(meta.get("fusedContext")))
    for url in urls:
        low = url.lower()
        if "espn" not in low and "site.api.espn" not in low:
            continue
        for pattern in (
            r"[?&]gameid=(\d+)",
            r"[?&]event=(\d+)",
            r"/gameid/(\d+)",
        ):
            ids.update(re.findall(pattern, low))
    return ids


def _team_aliases(name: str) -> list[str]:
    norm = _norm(name)
    if not norm:
        return []
    aliases = [norm]
    tokens = norm.split()
    if len(tokens) >= 2:
        last = tokens[-1]
        if len(last) >= 4 and last not in GENERIC_TEAM_LAST_TOKENS:
            aliases.append(last)
    return sorted(set(aliases), key=len, reverse=True)


def _explicit_winner(text: Any, team_names: list[str]) -> str | None:
    norm = _norm(text)
    if not norm or len(team_names) < 2:
        return None
    for winner in team_names:
        for loser in team_names:
            if _norm(winner) == _norm(loser):
                continue
            for w_alias in _team_aliases(winner):
                for l_alias in _team_aliases(loser):
                    verb = "(?:" + "|".join(re.escape(v) for v in WIN_VERBS) + ")"
                    patterns = (
                        rf"\b{re.escape(w_alias)}\b.{{0,40}}\b{verb}\b.{{0,45}}\b{re.escape(l_alias)}\b",
                        rf"\b{re.escape(w_alias)}\b.{{0,40}}\bwin(?:s)?\s+over\b.{{0,35}}\b{re.escape(l_alias)}\b",
                    )
                    if any(re.search(pattern, norm) for pattern in patterns):
                        return winner
    return None


def _candidate_truth_winner(candidate: dict[str, Any], team_names: list[str]) -> str | None:
    structured = _structured_context(candidate)
    if structured is not None and structured["homeScore"] != structured["awayScore"]:
        return structured["home"] if structured["homeScore"] > structured["awayScore"] else structured["away"]
    for value in (candidate.get("title"), candidate.get("summary")):
        winner = _explicit_winner(value, team_names)
        if winner:
            return winner
    return None


def _result_identity_failure(
    item: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> str | None:
    if _clean(item.get("type")).upper() not in RESULT_TYPES:
        return None
    if not candidates:
        return None

    game_ids = _espn_game_ids(item, candidates)
    if len(game_ids) > 1:
        return "multiple distinct ESPN game IDs attached to one result: " + ", ".join(sorted(game_ids))

    structured = [ctx for ctx in (_structured_context(c) for c in candidates) if ctx is not None]
    if structured:
        match_ids = {ctx["matchId"] for ctx in structured if ctx["matchId"]}
        identities = {
            (
                tuple(sorted((_norm(ctx["home"]), _norm(ctx["away"])))),
                _unordered_score((ctx["homeScore"], ctx["awayScore"])),
            )
            for ctx in structured
        }
        if len(match_ids) > 1 or len(identities) > 1:
            return "conflicting structured game identities among selected candidates"

        canonical_scores = {
            _unordered_score((ctx["homeScore"], ctx["awayScore"]))
            for ctx in structured
        }
        rendered_scores = {
            _unordered_score(pair)
            for pair in _score_pairs(
                " ".join((_clean(item.get("headline")), _clean(item.get("text")), _clean(item.get("freshnessBasis"))))
            )
        }
        if rendered_scores and not (rendered_scores & canonical_scores):
            return (
                "rendered score does not match structured candidate score; "
                f"rendered={sorted(rendered_scores)} structured={sorted(canonical_scores)}"
            )

    # Winner-direction consistency. Use structured teams when possible, otherwise
    # the first two entities (ticker normalization convention puts teams first).
    if structured:
        team_names = [structured[0]["home"], structured[0]["away"]]
    else:
        entities = item.get("entities") if isinstance(item.get("entities"), list) else []
        team_names = [_clean(x) for x in entities[:2] if _clean(x)]
    if len(team_names) >= 2:
        rendered_winner = _explicit_winner(item.get("headline"), team_names)
        if rendered_winner:
            truth_winners = {
                _norm(winner)
                for winner in (_candidate_truth_winner(c, team_names) for c in candidates)
                if winner
            }
            if truth_winners and _norm(rendered_winner) not in truth_winners:
                return (
                    "rendered winner contradicts selected candidate/source; "
                    f"headline winner={rendered_winner} source winner(s)={sorted(truth_winners)}"
                )
    return None


def _event_core_name(event_name: Any, sport: Any) -> str:
    name = _clean(event_name)
    sport_clean = _clean(sport)
    if sport_clean:
        name = re.sub(rf"\s*\(\s*{re.escape(sport_clean)}\s*\)\s*$", "", name, flags=re.I)
    return _clean(name)


def _event_distinguishers(event_name: Any, sport: Any) -> list[str]:
    core = _norm(_event_core_name(event_name, sport))
    sport_norm = _norm(sport)
    if not core or core in GENERIC_SPECIAL_NAMES or core == sport_norm:
        return []
    tokens = [token for token in core.split() if token not in GENERIC_EVENT_TOKENS]
    return tokens


def _special_event_affinity(item: dict[str, Any], event_name: Any, sport: Any) -> bool:
    distinguishers = _event_distinguishers(event_name, sport)
    if not distinguishers:
        return True
    blob = _item_blob(item)
    core = _norm(_event_core_name(event_name, sport))
    if core and core in blob:
        return True
    # One event-specific discriminator is sufficient after generic sport/event words
    # have been removed: Italian distinguishes Italian GP from Monaco GP; "us"
    # distinguishes US Open; 332 distinguishes UFC 332.
    return any(re.search(rf"\b{re.escape(token)}\b", blob) for token in distinguishers)


def enforce_output_identity(
    normalized: dict[str, Any],
    candidates: list[dict[str, Any]],
    run_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Drop ambiguous/wrongly-grouped rows before the existing global selector."""
    by_id = {
        c.get("candidateId"): c
        for c in candidates
        if isinstance(c, dict) and isinstance(c.get("candidateId"), str)
    }
    result_drops: list[dict[str, Any]] = []
    event_drops: list[dict[str, Any]] = []

    for group in normalized.get("leagues", []):
        league = _clean(group.get("league"))
        kept = []
        for item in group.get("items", []) if isinstance(group.get("items"), list) else []:
            objs = _candidate_objects(item, by_id)
            failure = _result_identity_failure(item, objs)
            if failure:
                result_drops.append({
                    "league": league,
                    "headline": item.get("headline"),
                    "candidateIds": item.get("candidateIds", []),
                    "reason": failure,
                })
                continue
            kept.append(item)
        group["items"] = kept

    rebuilt_events = []
    for event in normalized.get("specialEvents", []):
        name = _clean(event.get("name"))
        sport = _clean(event.get("sport"))
        kept = []
        for item in event.get("items", []) if isinstance(event.get("items"), list) else []:
            if not _special_event_affinity(item, name, sport):
                event_drops.append({
                    "event": name,
                    "sport": sport,
                    "headline": item.get("headline"),
                    "candidateIds": item.get("candidateIds", []),
                    "reason": "named Special Event affinity failed",
                    "distinguishers": _event_distinguishers(name, sport),
                })
                continue
            kept.append(item)
        if kept:
            event["items"] = kept
            rebuilt_events.append(event)
    normalized["specialEvents"] = rebuilt_events

    if run_log is not None:
        pipe = run_log.setdefault("pipeline", {})
        pipe["a47GameIdentityDrops"] = result_drops
        pipe["a47SpecialEventAffinityDrops"] = event_drops
    return normalized


def _patch_a45(a45, a46) -> None:
    # First install every A4.6 protection, then add A4.7 without disturbing its
    # progression/legal/NCAAF identity behavior.
    a46._patch_a45(a45)
    a45.PIPELINE_VERSION = PIPELINE_VERSION
    a45.A45_EDITOR_ADDENDUM = a45.A45_EDITOR_ADDENDUM + A47_EDITOR_ADDENDUM

    original_load_a44 = a45._load_a44

    def load_a44_a47():
        a44 = original_load_a44()
        a44.PIPELINE_VERSION = PIPELINE_VERSION
        original_patch_a43 = a44._patch_a43

        def patch_a43_a47(a43):
            original_patch_a43(a43)
            a43.PIPELINE_VERSION = PIPELINE_VERSION
            original_patch_a42 = a43._patch_a42

            def patch_a42_a47(a42):
                original_patch_a42(a42)
                a42.PIPELINE_VERSION = PIPELINE_VERSION
                original_configure = a42._configure_core

                def configure_a47(core):
                    original_configure(core)
                    core.EDITOR_INSTRUCTIONS = core.EDITOR_INSTRUCTIONS + "\n\n" + A47_EDITOR_ADDENDUM
                    original_normalize = core.normalize_model_output
                    original_init = core.initial_run_log

                    def normalize_a47(model_output, candidates, generated_at, run_log):
                        normalized = original_normalize(model_output, candidates, generated_at, run_log)
                        return enforce_output_identity(normalized, candidates, run_log)

                    def initial_run_log_a47(generated_at, cutoff, model):
                        log = original_init(generated_at, cutoff, model)
                        log["pipelineVersion"] = PIPELINE_VERSION
                        log.setdefault("configuration", {})["eventIdentityPolicy"] = (
                            "A4.7 fail-closed cross-game isolation + named Special Event affinity; "
                            "30-35 architecture unchanged"
                        )
                        return log

                    core.normalize_model_output = normalize_a47
                    core.initial_run_log = initial_run_log_a47

                a42._configure_core = configure_a47

            a43._patch_a42 = patch_a42_a47

        a44._patch_a43 = patch_a43_a47
        return a44

    a45._load_a44 = load_a44_a47


def main() -> int:
    a46 = _load_a46()
    a45 = a46._load_a45()
    _patch_a45(a45, a46)
    return a45.main()


if __name__ == "__main__":
    raise SystemExit(main())

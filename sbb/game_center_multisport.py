"""Sports Big Board v4.7.17 — multisport Game Center expansion.

Adds College Football to the existing ESPN Game Summary adapter and normalizes
period-by-period line scores plus ESPN win probability into the shared Game Center
contract.  v4.7.21 also makes period linescores part of the completeness contract
for live/final football, basketball and hockey so stale pre-linescore cache records
are automatically enriched instead of remaining permanently "complete".
"""
from __future__ import annotations

import copy
import threading

from . import game_center as _gc

VERSION = "4.7.21-game-center-multisport-2"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False
_ORIGINAL_NORMALIZE = _gc.normalize_espn_summary
_ORIGINAL_FETCH = _gc.fetch_espn_game_center
_ORIGINAL_COVERAGE = _gc.game_center_coverage

_ESPN_COMPETITIONS = {
    "NFL": ("football", "nfl"),
    "CFB": ("football", "college-football"),
    "NBA": ("basketball", "nba"),
    "NHL": ("hockey", "nhl"),
    "MLS": ("soccer", "usa.1"),
    "EPL": ("soccer", "eng.1"),
}


def _number(value):
    try:
        if value in (None, ""):
            return None
        number = float(value)
        return int(number) if number.is_integer() else number
    except Exception:
        return None


def _percent(value):
    number = _number(value)
    if number is None:
        return None
    if -1.000001 <= number <= 1.000001:
        number *= 100.0
    return max(0.0, min(100.0, float(number)))


def _period_label(competition, index, raw=""):
    raw = str(raw or "").strip()
    if raw and not raw.isdigit():
        return raw.upper().replace("QUARTER", "Q").replace("PERIOD", "P")
    n = int(index or 0)
    comp = str(competition or "").upper()
    if comp in {"NFL", "CFB", "NBA"}:
        if n <= 4:
            return f"Q{n}"
        return "OT" if n == 5 else f"{n-4}OT"
    if comp == "NHL":
        if n <= 3:
            return f"P{n}"
        if n == 4:
            return "OT"
        return "SO" if n == 5 else f"{n-3}OT"
    if comp in {"MLS", "EPL"}:
        if n <= 2:
            return f"H{n}"
        return "ET" if n == 3 else f"ET{n-2}"
    return raw or str(n)


def _competitor_periods(payload, competition):
    header, comp, *_ = _gc._espn_status_parts(payload)
    competitors = comp.get("competitors") or []
    by_side = {"away": [], "home": []}
    labels = {}
    for competitor in competitors:
        side = str(competitor.get("homeAway") or "").lower()
        if side not in by_side:
            continue
        rows = competitor.get("linescores") or competitor.get("lineScores") or []
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("periods") or []
        values = []
        for idx, row in enumerate(rows if isinstance(rows, list) else [], 1):
            if isinstance(row, dict):
                value = row.get("displayValue")
                if value in (None, ""):
                    value = row.get("value")
                period = row.get("period")
                if isinstance(period, dict):
                    period_num = int(period.get("number") or idx)
                    label = period.get("displayValue") or period.get("abbreviation") or ""
                else:
                    try:
                        period_num = int(period or idx)
                    except Exception:
                        period_num = idx
                    label = row.get("label") or row.get("abbreviation") or ""
            else:
                value = row
                period_num = idx
                label = ""
            values.append((period_num, _gc._safe(value)))
            labels.setdefault(period_num, _period_label(competition, period_num, label))
        by_side[side] = values
    away = {n: v for n, v in by_side["away"]}
    home = {n: v for n, v in by_side["home"]}
    nums = sorted(set(away) | set(home))
    return [
        {
            "num": n,
            "label": labels.get(n) or _period_label(competition, n),
            "away": away.get(n, ""),
            "home": home.get(n, ""),
        }
        for n in nums
    ]


def _play_lookup(payload):
    lookup = {}
    for play in _gc._espn_flat_plays(payload):
        if not isinstance(play, dict):
            continue
        pid = str(play.get("id") or play.get("playId") or "")
        if pid:
            lookup[pid] = play
    return lookup


def _play_label(play, competition=""):
    play = play or {}
    period = play.get("period") or {}
    if isinstance(period, dict):
        number = period.get("number")
        raw = period.get("displayValue") or period.get("abbreviation") or ""
    else:
        number = period
        raw = ""
    try:
        number = int(number or 0)
    except Exception:
        number = 0
    clock = play.get("clock") or {}
    clock_text = clock.get("displayValue") if isinstance(clock, dict) else str(clock or "")
    bits = []
    if number:
        bits.append(_period_label(competition, number, raw))
    elif raw:
        bits.append(str(raw))
    if clock_text:
        bits.append(str(clock_text))
    return " • ".join(bits)


def _win_probability(payload, competition):
    raw = (payload or {}).get("winprobability") or (payload or {}).get("winProbability") or []
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("plays") or raw.get("probabilities") or []
    if not isinstance(raw, list):
        return []
    plays = _play_lookup(payload)
    out = []
    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        play_id = str(row.get("playId") or row.get("id") or "")
        play = row.get("play") if isinstance(row.get("play"), dict) else plays.get(play_id, {})
        home = _percent(row.get("homeWinPercentage") if row.get("homeWinPercentage") is not None else row.get("home"))
        tie = _percent(row.get("tiePercentage") if row.get("tiePercentage") is not None else row.get("tie"))
        away_explicit = _percent(row.get("awayWinPercentage") if row.get("awayWinPercentage") is not None else row.get("away"))
        if home is None and away_explicit is None:
            continue
        tie = tie or 0.0
        away = away_explicit if away_explicit is not None else max(0.0, 100.0 - float(home or 0.0) - tie)
        if home is None:
            home = max(0.0, 100.0 - away - tie)
        label = _play_label(play, competition)
        if not label:
            label = "START" if idx == 0 else ("LATEST" if idx == len(raw)-1 else f"PLAY {idx+1}")
        out.append({
            "index": idx,
            "playId": play_id,
            "label": label,
            "away": round(float(away), 1),
            "home": round(float(home), 1),
            "tie": round(float(tie), 1),
            "scoreAway": _gc._safe((play or {}).get("awayScore")),
            "scoreHome": _gc._safe((play or {}).get("homeScore")),
        })
    return out


def normalize_espn_summary(payload, competition, event_id):
    competition = str(competition or "").upper()
    out = _ORIGINAL_NORMALIZE(payload, competition, event_id)
    if not isinstance(out, dict):
        return out
    event = out.setdefault("event", {})
    board = out.setdefault("scoreboard", {})
    if competition == "CFB":
        event["competitionId"] = "CFB"
        event["sportId"] = "american-football"
        event["eventKind"] = "game"
        out["competitionId"] = "CFB"
    periods = _competitor_periods(payload, competition)
    if periods:
        board["periods"] = periods
        board["lineScoreType"] = "quarters" if competition in {"NFL", "CFB", "NBA"} else ("periods" if competition == "NHL" else "segments")
    probability = _win_probability(payload, competition)
    if probability:
        board["winProbability"] = probability
        out["winProbability"] = probability
        out["winProbabilitySource"] = "ESPN Game Summary"
    _gc._apply_coverage_fields(out)
    return out


def fetch_espn_game_center(competition, event_id, fetch_json, site_api_base):
    competition = str(competition or "").upper()
    cfg = _ESPN_COMPETITIONS.get(competition)
    if not cfg:
        raise NotImplementedError(f"Game Center provider not implemented for {competition}")
    sport, slug = cfg
    base = str(site_api_base).rstrip("/")
    payload = fetch_json(f"{base}/{sport}/{slug}/summary?event={event_id}", timeout=10)
    return normalize_espn_summary(payload, competition, event_id)


def game_center_coverage(data):
    """Extend base coverage with the persistent multisport linescore contract.

    Old cached NFL/NBA/NHL records could satisfy the base richness checks without
    ``scoreboard.periods`` and therefore never refresh.  CFB inherits NFL richness.
    A live/final period sport is now incomplete until at least one normalized period
    is present. Scheduled games remain complete without a linescore.
    """
    data = data or {}
    comp = str(data.get("competitionId") or ((data.get("event") or {}).get("competitionId")) or "").upper()
    if comp == "CFB":
        probe = copy.deepcopy(data)
        probe["competitionId"] = "NFL"
        probe.setdefault("event", {})["competitionId"] = "NFL"
        result = dict(_ORIGINAL_COVERAGE(probe))
        result["competitionId"] = "CFB"
    else:
        result = dict(_ORIGINAL_COVERAGE(data))

    periods = [x for x in (((data.get("scoreboard") or {}).get("periods")) or []) if isinstance(x, dict)]
    result["periods"] = len(periods)
    if comp in {"NFL", "CFB", "NBA", "NHL"} and (result.get("final") or result.get("live")) and not periods:
        missing = list(result.get("missing") or [])
        if "linescore" not in missing:
            missing.append("linescore")
        result["missing"] = missing
        result["complete"] = False
    return result


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return False
        _gc.normalize_espn_summary = normalize_espn_summary
        _gc.fetch_espn_game_center = fetch_espn_game_center
        _gc.game_center_coverage = game_center_coverage
        _INSTALLED = True
        return True


__all__ = [
    "VERSION", "install", "normalize_espn_summary", "fetch_espn_game_center",
    "game_center_coverage", "_competitor_periods", "_win_probability",
]

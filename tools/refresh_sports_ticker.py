#!/usr/bin/env python3
"""Sports Big Board A3 Sports Ticker pipeline.

Discovery:
  - direct ESPN JSON news endpoints
  - direct official league news pages (best-effort JSON-LD/article extraction)
  - Highlightly structured match data

Editorial:
  - one GPT-4o Mini Responses API call by default
  - NO OpenAI web_search tool

Outputs:
  - data/sports-ticker.json
  - data/sports-ticker.txt
  - data/sports-ticker-run-log.json

The run log is always written, including on failures. Secrets are never logged.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

OPENAI_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4o-mini"
FRESHNESS_HOURS = 24.0
MAX_MODEL_CANDIDATES = 140
SOURCE_TIMEOUT = 25
OPENAI_TIMEOUT = 180

BASE_LEAGUES = ["MLB", "NFL", "NBA", "NHL", "EPL", "MLS", "NCAAF"]


# 2026 FBS fallback universe. Primary FBS eligibility/rank context is fetched
# from ESPN's FBS scoreboard (group 80) for the current and previous dates.
# This static set prevents a transient scoreboard-context failure from allowing
# lower-division NCAA results into the ticker.
FBS_TEAMS_2026 = [
    # SEC
    "Alabama Crimson Tide", "Arkansas Razorbacks", "Auburn Tigers",
    "Florida Gators", "Georgia Bulldogs", "Kentucky Wildcats", "LSU Tigers",
    "Mississippi State Bulldogs", "Missouri Tigers", "Oklahoma Sooners",
    "Ole Miss Rebels", "South Carolina Gamecocks", "Tennessee Volunteers",
    "Texas A&M Aggies", "Texas Longhorns", "Vanderbilt Commodores",
    # Big Ten
    "Illinois Fighting Illini", "Indiana Hoosiers", "Iowa Hawkeyes",
    "Maryland Terrapins", "Michigan State Spartans", "Michigan Wolverines",
    "Minnesota Golden Gophers", "Nebraska Cornhuskers", "Northwestern Wildcats",
    "Ohio State Buckeyes", "Oregon Ducks", "Penn State Nittany Lions",
    "Purdue Boilermakers", "Rutgers Scarlet Knights", "UCLA Bruins",
    "USC Trojans", "Washington Huskies", "Wisconsin Badgers",
    # Big 12
    "Arizona State Sun Devils", "Arizona Wildcats", "Baylor Bears", "BYU Cougars",
    "Cincinnati Bearcats", "Colorado Buffaloes", "Houston Cougars",
    "Iowa State Cyclones", "Kansas Jayhawks", "Kansas State Wildcats",
    "Oklahoma State Cowboys", "TCU Horned Frogs", "Texas Tech Red Raiders",
    "UCF Knights", "Utah Utes", "West Virginia Mountaineers",
    # ACC
    "Boston College Eagles", "California Golden Bears", "Clemson Tigers",
    "Duke Blue Devils", "Florida State Seminoles", "Georgia Tech Yellow Jackets",
    "Louisville Cardinals", "Miami Hurricanes", "NC State Wolfpack",
    "North Carolina Tar Heels", "Pittsburgh Panthers", "SMU Mustangs",
    "Stanford Cardinal", "Syracuse Orange", "Virginia Cavaliers",
    "Virginia Tech Hokies", "Wake Forest Demon Deacons",
    # American
    "Army Black Knights", "Charlotte 49ers", "East Carolina Pirates", "FAU Owls",
    "Memphis Tigers", "Navy Midshipmen", "North Texas Mean Green", "Rice Owls",
    "South Florida Bulls", "Temple Owls", "Tulane Green Wave",
    "Tulsa Golden Hurricane", "UAB Blazers", "UTSA Roadrunners",
    # Mountain West
    "Air Force Falcons", "Hawaii Rainbow Warriors", "Nevada Wolf Pack",
    "New Mexico Lobos", "North Dakota State Bison", "Northern Illinois Huskies",
    "San Jose State Spartans", "UNLV Rebels", "UTEP Miners", "Wyoming Cowboys",
    # Sun Belt
    "Appalachian State Mountaineers", "Arkansas State Red Wolves",
    "Coastal Carolina Chanticleers", "Georgia Southern Eagles",
    "Georgia State Panthers", "James Madison Dukes", "Louisiana Ragin Cajuns",
    "Louisiana Tech Bulldogs", "Louisiana-Monroe Warhawks",
    "Marshall Thundering Herd", "Old Dominion Monarchs",
    "South Alabama Jaguars", "Southern Miss Golden Eagles", "Troy Trojans",
    # Conference USA
    "Delaware Fightin Blue Hens", "FIU Panthers", "Jacksonville State Gamecocks",
    "Kennesaw State Owls", "Liberty Flames", "Middle Tennessee Blue Raiders",
    "Missouri State Bears", "New Mexico State Aggies", "Sam Houston Bearkats",
    "Western Kentucky Hilltoppers",
    # MAC
    "Akron Zips", "Ball State Cardinals", "Bowling Green Falcons", "Buffalo Bulls",
    "Central Michigan Chippewas", "Eastern Michigan Eagles",
    "Kent State Golden Flashes", "Miami (OH) RedHawks", "Ohio Bobcats",
    "Sacramento State Hornets", "Toledo Rockets", "UMass Minutemen",
    "Western Michigan Broncos",
    # Pac-12
    "Boise State Broncos", "Colorado State Rams", "Fresno State Bulldogs",
    "Oregon State Beavers", "San Diego State Aztecs", "Texas State Bobcats",
    "Utah State Aggies", "Washington State Cougars",
    # Independents
    "Notre Dame Fighting Irish", "UConn Huskies",
]

FBS_TEAM_ALIASES = {
    "connecticut huskies": "UConn Huskies",
    "florida atlantic owls": "FAU Owls",
    "massachusetts minutemen": "UMass Minutemen",
    "miami ohio redhawks": "Miami (OH) RedHawks",
    "miami of ohio redhawks": "Miami (OH) RedHawks",
    "louisiana ragin cajuns": "Louisiana Ragin Cajuns",
    "ul monroe warhawks": "Louisiana-Monroe Warhawks",
    "louisiana monroe warhawks": "Louisiana-Monroe Warhawks",
    "sam houston state bearkats": "Sam Houston Bearkats",
    "delaware blue hens": "Delaware Fightin Blue Hens",
}

ESPN_FBS_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/"
    "college-football/scoreboard"
)

ALLOWED_TYPES = [
    "BREAKING", "RESULT", "UPSET", "TRADE", "SIGNING", "INJURY", "RETURN",
    "RECORD", "RECORD_CHASE", "MILESTONE", "STREAK", "SLUMP", "RANKING",
    "PLAYOFF", "STANDINGS", "AWARD", "STAT_LEADER", "CONTRACT", "SUSPENSION",
    "DISCIPLINE", "LEGAL", "COACHING", "ROSTER", "DEPTH_CHART", "LEAGUE_NEWS",
    "SCHEDULE", "NEXT", "OTHER",
]

ALLOWED_STATUS = ["active", "watch", "next"]

ESPN_SOURCES = [
    {"id": "espn-mlb", "leagueHint": "MLB", "sportHint": "baseball",
     "url": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/news"},
    {"id": "espn-nfl", "leagueHint": "NFL", "sportHint": "football",
     "url": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"},
    {"id": "espn-nba", "leagueHint": "NBA", "sportHint": "basketball",
     "url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news"},
    {"id": "espn-nhl", "leagueHint": "NHL", "sportHint": "hockey",
     "url": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/news"},
    {"id": "espn-ncaaf", "leagueHint": "NCAAF", "sportHint": "college football",
     "url": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/news"},
    {"id": "espn-epl", "leagueHint": "EPL", "sportHint": "soccer",
     "url": "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/news"},
    {"id": "espn-mls", "leagueHint": "MLS", "sportHint": "soccer",
     "url": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/news"},

    # Special-event discovery / context.
    {"id": "espn-f1", "leagueHint": "SPECIAL", "sportHint": "Formula 1",
     "url": "https://site.api.espn.com/apis/site/v2/sports/racing/f1/news"},
    {"id": "espn-pga", "leagueHint": "SPECIAL", "sportHint": "golf",
     "url": "https://site.api.espn.com/apis/site/v2/sports/golf/pga/news"},
    {"id": "espn-lpga", "leagueHint": "SPECIAL", "sportHint": "golf",
     "url": "https://site.api.espn.com/apis/site/v2/sports/golf/lpga/news"},
    {"id": "espn-atp", "leagueHint": "SPECIAL", "sportHint": "tennis",
     "url": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/news"},
    {"id": "espn-wta", "leagueHint": "SPECIAL", "sportHint": "tennis",
     "url": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/news"},
    {"id": "espn-ufc", "leagueHint": "SPECIAL", "sportHint": "MMA",
     "url": "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/news"},
]

OFFICIAL_PAGES = [
    {"id": "official-mlb", "leagueHint": "MLB", "sportHint": "baseball",
     "url": "https://www.mlb.com/news"},
    {"id": "official-nfl", "leagueHint": "NFL", "sportHint": "football",
     "url": "https://www.nfl.com/news/"},
    {"id": "official-nba", "leagueHint": "NBA", "sportHint": "basketball",
     "url": "https://www.nba.com/news/category/news"},
    {"id": "official-nhl", "leagueHint": "NHL", "sportHint": "hockey",
     "url": "https://www.nhl.com/news/"},
    {"id": "official-ncaa", "leagueHint": "NCAAF", "sportHint": "college football",
     "url": "https://www.ncaa.com/sports/football/fbs"},
    {"id": "official-epl", "leagueHint": "EPL", "sportHint": "soccer",
     "url": "https://www.premierleague.com/en/news"},
    {"id": "official-mls", "leagueHint": "MLS", "sportHint": "soccer",
     "url": "https://www.mlssoccer.com/news/"},
]

HIGHLIGHTLY_SPORTS = [
    {
        "id": "highlightly-baseball",
        "sportHint": "baseball",
        "path": "/baseball/matches",
        "leagueMatchers": {
            "MLB": ["mlb", "major league baseball"],
        },
    },
    {
        "id": "highlightly-american-football",
        "sportHint": "american football",
        "path": "/american-football/matches",
        "leagueMatchers": {
            "NFL": ["nfl", "national football league"],
            "NCAAF": ["ncaa", "college football", "ncaaf"],
        },
    },
    {
        "id": "highlightly-basketball",
        "sportHint": "basketball",
        "path": "/basketball/matches",
        "leagueMatchers": {
            "NBA": ["nba", "national basketball association"],
        },
    },
    {
        "id": "highlightly-hockey",
        "sportHint": "hockey",
        "path": "/hockey/matches",
        "leagueMatchers": {
            "NHL": ["nhl", "national hockey league"],
        },
    },
    {
        "id": "highlightly-football",
        "sportHint": "soccer",
        "path": "/football/matches",
        "leagueMatchers": {
            "EPL": ["premier league", "english premier league"],
            "MLS": ["major league soccer", "mls"],
        },
    },
]

MODEL_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "candidateIds", "type", "priority", "headline", "text",
        "entities", "freshnessBasis", "status",
    ],
    "properties": {
        "candidateIds": {
            "type": "array", "minItems": 1, "maxItems": 4,
            "items": {"type": "string", "minLength": 4, "maxLength": 80},
        },
        "type": {"type": "string", "enum": ALLOWED_TYPES},
        "priority": {"type": "integer", "minimum": 1, "maximum": 100},
        "headline": {"type": "string", "minLength": 4, "maxLength": 120},
        "text": {"type": "string", "minLength": 10, "maxLength": 360},
        "entities": {
            "type": "array", "maxItems": 8,
            "items": {"type": "string", "minLength": 1, "maxLength": 80},
        },
        "freshnessBasis": {"type": "string", "minLength": 8, "maxLength": 240},
        "status": {"type": "string", "enum": ALLOWED_STATUS},
    },
}

MODEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["leagues", "specialEvents"],
    "properties": {
        "leagues": {
            "type": "object",
            "additionalProperties": False,
            "required": BASE_LEAGUES,
            "properties": {
                league: {"$ref": "#/$defs/leagueGroup"}
                for league in BASE_LEAGUES
            },
        },
        "specialEvents": {
            "type": "array", "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "sport", "items"],
                "properties": {
                    "name": {"type": "string", "minLength": 2, "maxLength": 100},
                    "sport": {"type": "string", "minLength": 2, "maxLength": 50},
                    "items": {
                        "type": "array", "minItems": 1, "maxItems": 10,
                        "items": {"$ref": "#/$defs/item"},
                    },
                },
            },
        },
    },
    "$defs": {
        "item": MODEL_ITEM_SCHEMA,
        "leagueGroup": {
            "type": "object",
            "additionalProperties": False,
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array", "minItems": 0, "maxItems": 10,
                    "items": {"$ref": "#/$defs/item"},
                },
            },
        },
    },
}

EDITOR_INSTRUCTIONS = """You are the final editor for Sports Big Board Sports Ticker.

You are NOT a researcher. You have NO browsing task. Use ONLY the candidate packet
provided by Python. Never add a fact that is not supported by one or more cited
candidateIds.

Goal: create a concise rolling "what actually happened or materially changed in
the last 24 hours?" ticker. This is NOT an article feed.

HARD NEWS TEST
For every selected item, you must be able to answer:
"What happened or changed?"
Do NOT select an item merely because ESPN published analysis, opinion, a feature,
a prediction, a preview, a quote, a question article, or a discussion topic.

Selection priorities:
1. BREAKING / major league news
2. playoff and standings consequences
3. major injuries / returns
4. trades / signings / contracts
5. records / milestones / record chases
6. rankings / awards / streaks / slumps
7. discipline / legal / actual coaching personnel changes / meaningful roster/depth-chart changes
8. major upsets
9. meaningful results
10. weak previews only when a genuinely NEW development makes them ticker-worthy

PRIORITY SCALE — ALWAYS USE THE FULL 1-100 SCALE
Priority is importance, NOT rank number.
- 95-100: extraordinary / sport-dominating breaking development
- 88-94: major national story, major playoff/championship consequence, blockbuster transaction
- 80-87: highly important injury, signing, record, upset, legal/discipline or standings development
- 70-79: strong league-wide story, notable return/milestone/ranking change
- 60-69: useful normal ticker item
- 50-65: ordinary completed result unless supplied metadata proves major context
- below 50: usually omit unless the league has exceptionally little legitimate news
Never use 1, 2, 3... as ranking positions. rank is assigned later by Python.

TYPE RULES
- COACHING means a coaching personnel/status change: hired, fired, resigned,
  extended, promoted, demoted, or role changed. A coach giving a quote is NOT COACHING.
- RESULT means a completed game/match result.
- UPSET means the supplied candidate establishes a genuinely surprising result.
- RETURN means a player actually returned/was activated after absence.
- DEPTH_CHART means a starter/backup/role change, not merely unavailable players.
- OTHER should be rare.
- For structured RESULT candidates, use metadata such as homeTeam, awayTeam,
  scores, ranks, FBS context, and fusedContext. Do not invent context that is not
  present in the candidate.

Editorial mix rules:
- Maximum 5 ordinary RESULT items per base league.
- Maximum 2 combined NEXT/SCHEDULE items per base league.
- Do not pad a league.
- A major UPSET is not an ordinary RESULT.
- Special Events should cover important active events outside the seven base leagues.

Grounding:
- Every final item must reference candidateIds from the supplied packet.
- Do not invent URLs, scores, dates, injuries, rankings, records, quotes, or transactions.
- If Python has already fused multiple sources into one candidate, treat that
  candidate's fusedContext metadata as grounded support for that same candidateId.
- If a candidate is ambiguous, omit it rather than guessing.

FRESHNESS BASIS
freshnessBasis must be a concrete factual clause describing the new development.
GOOD: "Chicago activated Kyle Teel from the injured list Friday."
GOOD: "Sacramento agreed to a one-year deal with Ben Simmons Friday."
GOOD: "Liverpool beat Ipswich 2-0 for its first league win of the season."
BAD: "hours ago"
BAD: "today"
BAD: "recently"
BAD: "new report"
Never return a vague time phrase by itself.

Consistency:
- Do not say shutout/shut out/blanked if the opponent scored.
- Do not call something a one-point win unless the score margin is one.
- Do not call a routine result an upset without evidence in the candidate packet.

OUTPUT SHAPE
The "leagues" field is an object with EXACTLY these seven required keys:
MLB, NFL, NBA, NHL, EPL, MLS, NCAAF.
Each key contains only "items". Python owns season-state determination.
Do not rename, duplicate, or omit league keys.

Write factual, compact, non-clickbait ticker copy.
"""

class TickerError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_datetime(value: str) -> datetime:
    text = (value or "").strip()
    if not text:
        raise ValueError("empty datetime")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return dt.astimezone(timezone.utc)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def strip_tags(value: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", value or ""))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def semantic_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def safe_headers(headers: Any) -> dict[str, str]:
    wanted = [
        "content-type", "etag", "last-modified",
        "x-ratelimit-requests-limit", "x-ratelimit-requests-remaining",
        "x-ratelimit-limit", "x-ratelimit-remaining",
    ]
    out: dict[str, str] = {}
    for name in wanted:
        val = headers.get(name)
        if val is not None:
            out[name] = str(val)
    return out


def redacted_request_headers(provider: str) -> dict[str, str]:
    headers = {"User-Agent": "SportsBigBoardTickerA3/1.0"}
    if provider == "Highlightly":
        headers["x-rapidapi-key"] = "[REDACTED]"
    if provider == "OpenAI":
        headers["Authorization"] = "Bearer [REDACTED]"
    return headers


def append_failure(log: dict[str, Any], stage: str, message: str, **extra: Any) -> None:
    entry = {"at": iso_z(utc_now()), "stage": stage, "message": clean_text(message)}
    entry.update(extra)
    log["failures"].append(entry)


def make_source_log(
    *,
    source_id: str,
    provider: str,
    kind: str,
    league_hint: str,
    url: str,
) -> dict[str, Any]:
    return {
        "sourceId": source_id,
        "provider": provider,
        "kind": kind,
        "leagueHint": league_hint,
        "url": url,
        "requestHeaders": redacted_request_headers(provider),
        "startedAt": iso_z(utc_now()),
        "finishedAt": None,
        "elapsedMs": None,
        "httpStatus": None,
        "responseHeaders": {},
        "contentType": None,
        "bytes": 0,
        "responseSha256": None,
        "rawPreview": None,
        "receivedItems": [],
        "acceptedCandidateIds": [],
        "rejectedItems": [],
        "error": None,
    }


def fetch_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = SOURCE_TIMEOUT):
    request_headers = {
        "User-Agent": "SportsBigBoardTickerA3/1.0 (+https://github.com/jonathanjoelneptune/sports-big-board)",
        "Accept": "*/*",
    }
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, headers=request_headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
        return response.status, response.headers, body


def finalize_source_log(entry: dict[str, Any], started: float, status: int | None, headers: Any, body: bytes | None):
    entry["finishedAt"] = iso_z(utc_now())
    entry["elapsedMs"] = int((time.monotonic() - started) * 1000)
    entry["httpStatus"] = status
    if headers is not None:
        entry["responseHeaders"] = safe_headers(headers)
        entry["contentType"] = headers.get("content-type")
    if body is not None:
        entry["bytes"] = len(body)
        entry["responseSha256"] = sha256_bytes(body)
        entry["rawPreview"] = body[:800].decode("utf-8", errors="replace")


def infer_league_hint(default_hint: str, url: str, title: str) -> str:
    u = (url or "").lower()
    t = (title or "").lower()

    path_hints = [
        ("/mlb/", "MLB"), ("/baseball/", "MLB"),
        ("/nfl/", "NFL"),
        ("/nba/", "NBA"),
        ("/nhl/", "NHL"),
        ("/college-football/", "NCAAF"), ("/ncf/", "NCAAF"),
    ]
    for token, league in path_hints:
        if token in u:
            return league

    if "major league soccer" in t or re.search(r"\bmls\b", t):
        return "MLS"
    if "premier league" in t:
        return "EPL"
    return default_hint


def keyword_type_hint(title: str, summary: str) -> str:
    text = (" " + title + " " + summary + " ").lower()

    result_patterns = [
        r"\bdefeat(?:s|ed)?\b",
        r"\bbeat(?:s|en)?\b",
        r"\bedges?\b",
        r"\btops?\b",
        r"\brouts?\b",
        r"\bshuts?\s+out\b",
        r"\bblank(?:s|ed)?\b",
        r"\bpowered past\b",
        r"\badvances? past\b",
        r"\bwins? over\b",
        r"\bwon\b",
    ]
    has_score = bool(
        re.search(r"(?<!\d)\d{1,3}\s*[-–—]\s*\d{1,3}(?!\d)", text)
        or re.search(r"\b\d{1,2}-\d{1,2},\s*\d{1,2}-\d{1,2}\b", text)
    )
    if has_score and any(re.search(pattern, text) for pattern in result_patterns):
        return "RESULT"

    headline_only = title.lower()
    scoreless_result_patterns = [
        r"\bwin(?:s)? at (?:the )?us open\b",
        r"\bwon (?:his|her|their) [^.!?]{0,60}\bmatch(?:es)?\b",
        r"\badvance(?:s|d)? at (?:the )?us open\b",
        r"\bto advance at (?:the )?us open\b",
    ]
    result_noise = ("complains", "bothered by", "smell of", "controversy")
    if (
        any(re.search(pattern, headline_only) for pattern in scoreless_result_patterns)
        and not any(noise in headline_only for noise in result_noise)
    ):
        return "RESULT"

    # Return/activation must be checked before generic injury-list wording.
    if any(word in text for word in [
        "activated off", "activated from", "returns to practice",
        "returns from injury", "back from injury", "returns to the lineup",
    ]):
        return "RETURN"

    if any(word in text for word in [
        "injury", "injured", "out for", "placed on injured", "concussion",
    ]):
        return "INJURY"

    if any(word in text for word in [" traded ", "trade for", "acquire", "acquired"]):
        return "TRADE"

    if (
        any(word in text for word in [
            "signs ", "signed ", "agrees to a deal", "agreed to a deal",
            "one-year deal", "two-year deal", "three-year deal",
            "deal with ", "reaching a one-year", "reaching one-year",
        ])
        or re.search(r"\b\d+-year,\s*\$?[\d.]+[mk]?\s+deal\b", text)
    ):
        return "SIGNING"

    if any(word in text for word in ["extension", "contract"]):
        return "CONTRACT"
    if any(word in text for word in ["suspended", "suspension"]):
        return "SUSPENSION"
    if any(word in text for word in ["fine", "discipline", "exempt list"]):
        return "DISCIPLINE"
    if any(word in text for word in ["arrest", "lawsuit", "charged with", "court appearance", "court date"]):
        return "LEGAL"

    if any(word in text for word in [
        "fired coach", "fires coach", "coach fired",
        "hired as coach", "named head coach", "names head coach",
        "coach resigns", "coach resigned", "coach steps down",
        "coach dismissed", "coaching change",
    ]):
        return "COACHING"

    if any(word in text for word in [
        "will be without", "without three", "without 3", "without five",
        "without 5", "inactive for", "ruled unavailable",
    ]):
        return "ROSTER"

    if any(word in text for word in [
        "starter", "backup quarterback", "depth chart", "qb1", "qb2",
    ]):
        return "DEPTH_CHART"

    checks = [
        ("RANKING", ["ranked", "ranking", "top 25"]),
        ("RECORD", ["record", "all-time"]),
        ("MILESTONE", ["milestone", "1,000", "100th", "500th"]),
        ("STREAK", ["winning streak", "win streak", "losing streak"]),
        ("PLAYOFF", ["playoff", "postseason", "wild card"]),
        ("STANDINGS", ["standings", "division lead", "games back"]),
        ("LEAGUE_NEWS", ["league announced", "sets spring training schedule", "rule change", "cba"]),
    ]
    for kind, words in checks:
        if any(word in text for word in words):
            return kind
    return "OTHER"


def low_signal_editorial_story(title: str, summary: str, type_hint: str) -> tuple[bool, str | None]:
    """Reject article-format noise that is not itself a new ticker development."""
    headline = clean_text(title).lower()
    body = clean_text(summary).lower()
    combined = headline + " " + body

    # These are article formats, not discrete news events, even when the text
    # happens to contain words like "record", "playoff", or "trade."
    always_reject = [
        "what makes ",
        "career, background",
        "questions to answer",
        "questions facing",
        "things to know",
        "what to know",
        "what we learned",
        "takeaways",
        "roundtable",
        "expert picks",
        "predictions",
        "prediction:",
        "preview:",
        "power rankings",
        "stock watch",
        "mailbag",
        "winners and losers",
        "grades:",
        "grading ",
        " review:",
        " review ",
        "live updates",
        "offseason recap",
        "season preview",
        "season previews",
        "latest free agency and trade updates",
        "buzz:",
        "separating fact from fiction",
    ]
    if any(phrase in combined for phrase in always_reject):
        return True, "analysis/feature/live-blog/roundup rather than one new development"

    # Opinion/quote-only pieces.
    quote_phrases = [
        "stands by",
        "believes ",
        "warns ",
        "says there is no way",
        "takes aim at",
        "need to take this l",
    ]
    if any(phrase in combined for phrase in quote_phrases):
        # A genuine legal/transaction/injury/etc. headline can still survive.
        if type_hint in {"OTHER", "COACHING", "RECORD", "RANKING"}:
            return True, "opinion/quote item without a material new development"

    # Pure question headlines are generally analysis unless Python already found
    # a strong factual transaction/injury/legal/return/result type.
    if "?" in headline and type_hint in {"OTHER", "RECORD", "RANKING", "COACHING"}:
        return True, "question/analysis headline without a strong factual event"

    return False, None



def _normalize_team_label(value: str) -> str:
    value = clean_text(value).lower().replace("&", " and ")
    value = re.sub(r"['’]", "", value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _team_token_set(value: str) -> set[str]:
    return {
        token for token in _normalize_team_label(value).split()
        if token not in {"the", "of", "university", "college"}
    }


def team_match_score(a: str, b: str) -> float:
    na, nb = _normalize_team_label(a), _normalize_team_label(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    alias_a = FBS_TEAM_ALIASES.get(na)
    alias_b = FBS_TEAM_ALIASES.get(nb)
    if alias_a and _normalize_team_label(alias_a) == nb:
        return 1.0
    if alias_b and _normalize_team_label(alias_b) == na:
        return 1.0
    ta, tb = _team_token_set(a), _team_token_set(b)
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / max(1, len(ta | tb))
    containment = len(ta & tb) / max(1, min(len(ta), len(tb)))
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    return max(jaccard, containment * 0.92, seq * 0.82)


def build_fbs_alias_index(team_names: list[str]) -> list[tuple[str, str]]:
    values: dict[str, str] = {}
    for name in team_names:
        normalized = _normalize_team_label(name)
        if normalized:
            values[normalized] = name
    for alias, canonical in FBS_TEAM_ALIASES.items():
        values[_normalize_team_label(alias)] = canonical
    return list(values.items())


def match_fbs_team(team_name: str, fbs_context: dict[str, Any]) -> str | None:
    best_name = None
    best_score = 0.0
    for _, canonical in fbs_context.get("aliasIndex", []):
        score = team_match_score(team_name, canonical)
        if score > best_score:
            best_score = score
            best_name = canonical
    return best_name if best_score >= 0.74 else None


def fetch_espn_fbs_context(
    generated_at: datetime,
    run_log: dict[str, Any],
) -> dict[str, Any]:
    """Build current FBS eligibility/rank context.

    ESPN group=80 scoreboard data is primary. A baked-in 2026 FBS universe is
    always present as fallback, so this enrichment cannot break ticker refreshes.
    """
    eastern_now = generated_at.astimezone(
        __import__("zoneinfo").ZoneInfo("America/New_York")
    )
    dates = [eastern_now.date(), (eastern_now - timedelta(days=1)).date()]

    team_names = set(FBS_TEAMS_2026)
    rank_by_name: dict[str, int] = {}
    successful = 0
    event_count = 0

    for day in dates:
        date_token = day.strftime("%Y%m%d")
        url = ESPN_FBS_SCOREBOARD_URL + "?" + urllib.parse.urlencode({
            "dates": date_token,
            "groups": 80,
            "limit": 100,
        })
        source_id = f"espn-ncaaf-fbs-scoreboard-{day.isoformat()}"
        entry = make_source_log(
            source_id=source_id,
            provider="ESPN",
            kind="scoreboard-context",
            league_hint="NCAAF",
            url=url,
        )
        run_log["sourceFetches"].append(entry)
        started = time.monotonic()
        try:
            status, headers, body = fetch_bytes(url, headers={"Accept": "application/json"})
            finalize_source_log(entry, started, status, headers, body)
            payload = json.loads(body.decode("utf-8"))
            events = payload.get("events", []) if isinstance(payload, dict) else []
            if not isinstance(events, list):
                events = []
            entry["receivedItems"] = events[:100]
            successful += 1
            event_count += len(events)

            for event in events:
                if not isinstance(event, dict):
                    continue
                comps = event.get("competitions")
                if not isinstance(comps, list) or not comps:
                    continue
                competitors = comps[0].get("competitors") if isinstance(comps[0], dict) else []
                if not isinstance(competitors, list):
                    continue
                for competitor in competitors:
                    if not isinstance(competitor, dict):
                        continue
                    team = competitor.get("team")
                    if not isinstance(team, dict):
                        continue
                    name = clean_text(
                        team.get("displayName")
                        or team.get("shortDisplayName")
                        or team.get("name")
                    )
                    if name:
                        team_names.add(name)
                        rank = competitor.get("curatedRank")
                        if isinstance(rank, dict):
                            try:
                                current = int(rank.get("current"))
                                if 1 <= current <= 25:
                                    rank_by_name[name] = current
                            except Exception:
                                pass

            entry["note"] = (
                f"FBS context accepted; events={len(events)}; "
                f"teamUniverse={len(team_names)}"
            )
        except Exception as exc:
            # Optional enrichment. Keep the error in the source log, but do not
            # mark the overall run failed because the static 2026 FBS fallback
            # is intentionally sufficient.
            if entry["finishedAt"] is None:
                finalize_source_log(entry, started, None, None, None)
            entry["error"] = clean_text(exc)
            entry["note"] = "Using static 2026 FBS fallback for this date."

    context = {
        "mode": "espn-scoreboard+static-fallback" if successful else "static-fallback",
        "successfulScoreboardRequests": successful,
        "scoreboardEventCount": event_count,
        "teamCount": len(team_names),
        "teamNames": sorted(team_names),
        "rankByName": rank_by_name,
    }
    context["aliasIndex"] = build_fbs_alias_index(context["teamNames"])

    run_log["pipeline"]["ncaafFbsContext"] = {
        "mode": context["mode"],
        "successfulScoreboardRequests": successful,
        "scoreboardEventCount": event_count,
        "teamCount": len(team_names),
        "rankedTeams": dict(sorted(rank_by_name.items(), key=lambda kv: kv[1])),
    }
    return context


def fbs_rank_for(team_name: str, fbs_context: dict[str, Any]) -> int | None:
    matched = match_fbs_team(team_name, fbs_context)
    if not matched:
        return None
    rank_map = fbs_context.get("rankByName", {})
    if matched in rank_map:
        return rank_map[matched]
    # Scoreboard display names can differ slightly from fallback names.
    for name, rank in rank_map.items():
        if team_match_score(team_name, name) >= 0.74:
            return rank
    return None


def _first_monday_of_september(year: int, tzinfo: Any) -> datetime:
    # Build the date directly in the target timezone. Constructing at 00:00 UTC
    # and then converting to Eastern can move the calendar date backward.
    day = datetime(year, 9, 1, tzinfo=tzinfo)
    return day + timedelta(days=(7 - day.weekday()) % 7)


def deterministic_season_state(league: str, generated_at: datetime) -> str:
    """Calendar-owned season state; OpenAI never decides this field."""
    dt = generated_at.astimezone(
        __import__("zoneinfo").ZoneInfo("America/New_York")
    )
    y, m, d = dt.year, dt.month, dt.day
    md = (m, d)

    if league == "MLB":
        if (2, 15) <= md <= (3, 25):
            return "preseason"
        if (3, 26) <= md <= (10, 4):
            return "active"
        if (10, 5) <= md <= (11, 10):
            return "postseason"
        return "offseason"

    if league == "NFL":
        labor_day = _first_monday_of_september(y, dt.tzinfo)
        kickoff = labor_day + timedelta(days=3)  # Thursday after Labor Day
        if m == 8 or (m == 9 and dt.date() < kickoff.date()):
            return "preseason"
        if (m == 9 and dt.date() >= kickoff.date()) or m in {10, 11, 12} or (m == 1 and d <= 10):
            return "active"
        if (m == 1 and d >= 11) or (m == 2 and d <= 20):
            return "postseason"
        return "offseason"

    if league == "NBA":
        if (10, 1) <= md <= (10, 19):
            return "preseason"
        if md >= (10, 20) or md <= (4, 15):
            return "active"
        if (4, 16) <= md <= (6, 25):
            return "postseason"
        return "offseason"

    if league == "NHL":
        if (9, 15) <= md <= (10, 6):
            return "preseason"
        if md >= (10, 7) or md <= (4, 20):
            return "active"
        if (4, 21) <= md <= (6, 30):
            return "postseason"
        return "offseason"

    if league == "EPL":
        return "active" if m in {8, 9, 10, 11, 12, 1, 2, 3, 4, 5} else "offseason"

    if league == "MLS":
        if (2, 15) <= md <= (10, 20):
            return "active"
        if (10, 21) <= md <= (12, 10):
            return "postseason"
        return "offseason"

    if league == "NCAAF":
        if md >= (8, 20) and md <= (12, 7):
            return "active"
        if md >= (12, 8) or md <= (1, 20):
            return "postseason"
        return "offseason"

    return "offseason"


def occurrence_from_date(
    value: str,
    generated_at: datetime,
    cutoff: datetime,
) -> tuple[str, str, float | None]:
    raw = clean_text(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        day = datetime.strptime(raw, "%Y-%m-%d").date()
        if day <= cutoff.date():
            raise TickerError(f"date-only {raw} cannot prove freshness")
        if day > generated_at.date():
            raise TickerError(f"date-only {raw} is in future")
        return raw, "date", None

    dt = parse_datetime(raw)
    age = (generated_at - dt).total_seconds() / 3600.0
    if age < -0.5:
        raise TickerError(f"future timestamp {raw}")
    if age > FRESHNESS_HOURS:
        raise TickerError(f"stale age={age:.2f}h")
    return iso_z(dt), "exact", round(age, 2)


def make_candidate(
    *,
    source_id: str,
    provider: str,
    league_hint: str,
    sport_hint: str,
    title: str,
    summary: str,
    source_url: str,
    occurrence: str,
    generated_at: datetime,
    cutoff: datetime,
    type_hint: str | None = None,
    quality: int = 80,
    raw_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    occurred_at, precision, age = occurrence_from_date(occurrence, generated_at, cutoff)
    title = clean_text(title)
    summary = clean_text(summary)
    if not title:
        raise TickerError("candidate has empty title")
    if len(title) > 180:
        title = title[:177] + "..."
    if len(summary) > 600:
        summary = summary[:597] + "..."

    fingerprint = hashlib.sha1(
        f"{league_hint}|{title.lower()}|{source_url}".encode("utf-8")
    ).hexdigest()[:16]

    return {
        "candidateId": f"cand-{fingerprint}",
        "leagueHint": infer_league_hint(league_hint, source_url, title),
        "sportHint": sport_hint,
        "typeHint": type_hint or keyword_type_hint(title, summary),
        "title": title,
        "summary": summary,
        "occurredAt": occurred_at,
        "timePrecision": precision,
        "ageHours": age,
        "quality": quality,
        "sourceRecords": [{
            "sourceId": source_id,
            "provider": provider,
            "url": source_url,
            "rawRef": raw_ref,
        }],
        "metadata": metadata or {},
    }


def article_is_fantasy(article: dict[str, Any]) -> bool:
    headline = clean_text(article.get("headline")).lower()
    description = clean_text(article.get("description")).lower()
    web_url = ""
    links = article.get("links")
    if isinstance(links, dict):
        web = links.get("web")
        if isinstance(web, dict):
            web_url = clean_text(web.get("href")).lower()

    category_text = []
    for category in article.get("categories", []) if isinstance(article.get("categories"), list) else []:
        if isinstance(category, dict):
            category_text.append(clean_text(category.get("description")).lower())

    combined = " ".join([headline, description, web_url] + category_text)
    return "fantasy" in combined


def article_web_url(article: dict[str, Any], fallback: str) -> str:
    links = article.get("links")
    if isinstance(links, dict):
        web = links.get("web")
        if isinstance(web, dict) and clean_text(web.get("href")):
            return clean_text(web.get("href"))
        mobile = links.get("mobile")
        if isinstance(mobile, dict) and clean_text(mobile.get("href")):
            return clean_text(mobile.get("href"))
        if isinstance(mobile, str) and clean_text(mobile):
            return clean_text(mobile)
    return fallback


def parse_espn_source(
    source: dict[str, str],
    generated_at: datetime,
    cutoff: datetime,
    run_log: dict[str, Any],
) -> list[dict[str, Any]]:
    entry = make_source_log(
        source_id=source["id"], provider="ESPN", kind="json-news-api",
        league_hint=source["leagueHint"], url=source["url"],
    )
    run_log["sourceFetches"].append(entry)
    started = time.monotonic()
    candidates: list[dict[str, Any]] = []

    try:
        status, headers, body = fetch_bytes(
            source["url"],
            headers={"Accept": "application/json"},
        )
        finalize_source_log(entry, started, status, headers, body)

        payload = json.loads(body.decode("utf-8"))
        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            raise TickerError("ESPN JSON response missing articles[]")

        entry["receivedItems"] = articles[:100]

        for idx, article in enumerate(articles[:100]):
            if not isinstance(article, dict):
                entry["rejectedItems"].append({
                    "index": idx, "reason": "article is not an object",
                })
                continue

            headline = clean_text(article.get("headline"))
            try:
                if clean_text(article.get("type")).lower() == "media":
                    raise TickerError("media/video item excluded")
                if article_is_fantasy(article):
                    raise TickerError("fantasy item excluded")

                published = clean_text(article.get("published") or article.get("lastModified"))
                if not published:
                    raise TickerError("missing published timestamp")

                description = clean_text(article.get("description"))
                type_hint = keyword_type_hint(headline, description)
                low_signal, low_signal_reason = low_signal_editorial_story(
                    headline, description, type_hint
                )
                if low_signal:
                    raise TickerError(low_signal_reason or "low-signal editorial item")

                source_url = article_web_url(article, source["url"])
                candidate = make_candidate(
                    source_id=source["id"],
                    provider="ESPN",
                    league_hint=source["leagueHint"],
                    sport_hint=source["sportHint"],
                    title=headline,
                    summary=description,
                    source_url=source_url,
                    occurrence=published,
                    generated_at=generated_at,
                    cutoff=cutoff,
                    type_hint=type_hint,
                    quality=90,
                    raw_ref=f"{source['id']}#{idx}",
                    metadata={
                        "espnArticleId": article.get("id"),
                        "espnType": article.get("type"),
                        "byline": article.get("byline"),
                        "categories": [
                            clean_text(c.get("description"))
                            for c in article.get("categories", [])
                            if isinstance(c, dict) and clean_text(c.get("description"))
                        ][:20],
                    },
                )
                candidates.append(candidate)
                entry["acceptedCandidateIds"].append(candidate["candidateId"])
            except Exception as exc:
                entry["rejectedItems"].append({
                    "index": idx,
                    "title": headline,
                    "reason": clean_text(exc),
                })

        if not candidates:
            entry["note"] = (
                "ESPN endpoint fetched successfully but no fresh non-fantasy "
                "news candidates survived the 24-hour gate."
            )
    except Exception as exc:
        if entry["finishedAt"] is None:
            finalize_source_log(entry, started, None, None, None)
        entry["error"] = clean_text(exc)
        append_failure(run_log, f"source:{source['id']}", str(exc), provider="ESPN")

    return candidates


class NewsPageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.article_depth = 0
        self.current_article: dict[str, Any] | None = None
        self.current_anchor_href: str | None = None
        self.current_anchor_text: list[str] = []
        self.current_heading_text: list[str] | None = None
        self.current_time: str | None = None
        self.articles: list[dict[str, Any]] = []
        self.ld_json_buffers: list[str] = []
        self._in_ld_json = False
        self._ld_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "article":
            self.article_depth += 1
            if self.article_depth == 1:
                self.current_article = {"title": "", "url": "", "publishedAt": ""}
        if tag == "a":
            self.current_anchor_href = attrs_d.get("href")
            self.current_anchor_text = []
        if tag in {"h1", "h2", "h3"}:
            self.current_heading_text = []
        if tag == "time":
            self.current_time = attrs_d.get("datetime") or attrs_d.get("content")
            if self.current_article is not None and self.current_time:
                self.current_article["publishedAt"] = self.current_time
        if tag == "script" and attrs_d.get("type", "").lower() == "application/ld+json":
            self._in_ld_json = True
            self._ld_buf = []

    def handle_data(self, data):
        if self.current_anchor_href is not None:
            self.current_anchor_text.append(data)
        if self.current_heading_text is not None:
            self.current_heading_text.append(data)
        if self._in_ld_json:
            self._ld_buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current_anchor_href is not None:
            text = clean_text(" ".join(self.current_anchor_text))
            href = urllib.parse.urljoin(self.base_url, self.current_anchor_href)
            if self.current_article is not None and len(text) >= 20:
                if not self.current_article.get("title"):
                    self.current_article["title"] = text
                    self.current_article["url"] = href
            self.current_anchor_href = None
            self.current_anchor_text = []
        if tag in {"h1", "h2", "h3"} and self.current_heading_text is not None:
            text = clean_text(" ".join(self.current_heading_text))
            if self.current_article is not None and len(text) >= 20:
                self.current_article["title"] = text
            self.current_heading_text = None
        if tag == "article":
            if self.article_depth == 1 and self.current_article is not None:
                if self.current_article.get("title") and self.current_article.get("url"):
                    self.articles.append(self.current_article)
                self.current_article = None
            self.article_depth = max(0, self.article_depth - 1)
        if tag == "script" and self._in_ld_json:
            self.ld_json_buffers.append("".join(self._ld_buf))
            self._in_ld_json = False
            self._ld_buf = []


def iter_json_objects(value: Any):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from iter_json_objects(v)
    elif isinstance(value, list):
        for v in value:
            yield from iter_json_objects(v)


def parse_official_source(
    source: dict[str, str],
    generated_at: datetime,
    cutoff: datetime,
    run_log: dict[str, Any],
) -> list[dict[str, Any]]:
    entry = make_source_log(
        source_id=source["id"], provider="OfficialLeague", kind="html-news-page",
        league_hint=source["leagueHint"], url=source["url"],
    )
    run_log["sourceFetches"].append(entry)
    started = time.monotonic()
    candidates: list[dict[str, Any]] = []

    try:
        status, headers, body = fetch_bytes(
            source["url"],
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        finalize_source_log(entry, started, status, headers, body)
        text = body.decode("utf-8", errors="replace")
        parser = NewsPageParser(source["url"])
        parser.feed(text)

        extracted: list[dict[str, Any]] = []
        for blob in parser.ld_json_buffers:
            try:
                data = json.loads(blob)
            except Exception:
                continue
            for obj in iter_json_objects(data):
                obj_type = obj.get("@type")
                types = obj_type if isinstance(obj_type, list) else [obj_type]
                if not any(t in {"NewsArticle", "Article", "SportsEvent"} for t in types):
                    continue
                headline = clean_text(obj.get("headline") or obj.get("name"))
                published = clean_text(
                    obj.get("datePublished") or obj.get("dateModified") or obj.get("startDate")
                )
                url = obj.get("url")
                if isinstance(url, dict):
                    url = url.get("@id")
                url = clean_text(url)
                desc = clean_text(obj.get("description"))
                if headline and published and url:
                    extracted.append({
                        "title": headline,
                        "url": urllib.parse.urljoin(source["url"], url),
                        "publishedAt": published,
                        "description": desc,
                        "extraction": "json-ld",
                    })

        extracted.extend(
            {**a, "description": "", "extraction": "article-tag"}
            for a in parser.articles
            if a.get("publishedAt")
        )

        # Keep the log useful but bounded.
        seen_keys: set[str] = set()
        unique_extracted = []
        for item in extracted:
            key = (item.get("url") or "") + "|" + (item.get("title") or "")
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_extracted.append(item)
        entry["receivedItems"] = unique_extracted[:100]

        for idx, raw_item in enumerate(unique_extracted[:100]):
            try:
                candidate = make_candidate(
                    source_id=source["id"],
                    provider="OfficialLeague",
                    league_hint=source["leagueHint"],
                    sport_hint=source["sportHint"],
                    title=raw_item["title"],
                    summary=raw_item.get("description", ""),
                    source_url=raw_item["url"],
                    occurrence=raw_item["publishedAt"],
                    generated_at=generated_at,
                    cutoff=cutoff,
                    quality=100,
                    raw_ref=f"{source['id']}#{idx}",
                )
                candidates.append(candidate)
                entry["acceptedCandidateIds"].append(candidate["candidateId"])
            except Exception as exc:
                entry["rejectedItems"].append({
                    "index": idx,
                    "title": raw_item.get("title"),
                    "reason": clean_text(exc),
                })
    except Exception as exc:
        if entry["finishedAt"] is None:
            finalize_source_log(entry, started, None, None, None)
        entry["error"] = clean_text(exc)
        append_failure(run_log, f"source:{source['id']}", str(exc), provider="OfficialLeague")
    return candidates


def unwrap_highlightly(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        for key in ("data", "matches", "results"):
            items = value.get(key)
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
    return []


def score_scalar(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        return int(value.strip())
    if isinstance(value, list):
        nums = [score_scalar(v) for v in value]
        nums = [n for n in nums if n is not None]
        if not nums:
            return None
        return sum(nums) if len(nums) > 1 else nums[0]
    if isinstance(value, dict):
        # Baseball exposes per-inning runs rather than a side-level total.
        innings = value.get("innings")
        if isinstance(innings, list):
            nums = [score_scalar(v) for v in innings]
            nums = [n for n in nums if n is not None]
            if nums:
                return sum(nums)

        for key in ("total", "current", "score", "value", "displayValue", "points", "runs"):
            if key in value:
                n = score_scalar(value[key])
                if n is not None:
                    return n
    return None


def parse_highlightly_current_score(value: Any) -> tuple[int | None, int | None]:
    """Parse Highlightly's state.score.current.

    Highlightly returns current as HOME - AWAY across the observed baseball,
    NCAA football, basketball, hockey and soccer payloads.
    """
    if not isinstance(value, str):
        return None, None
    match = re.fullmatch(r"\s*(\d{1,3})\s*[-–—]\s*(\d{1,3})\s*", value)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))

def team_name(match: dict[str, Any], side: str) -> str:
    obj = match.get(f"{side}Team")
    if isinstance(obj, dict):
        return clean_text(obj.get("displayName") or obj.get("name") or obj.get("abbreviation"))
    return clean_text(match.get(f"{side}TeamDisplayName") or match.get(f"{side}TeamName"))


def match_score(match: dict[str, Any]) -> tuple[int | None, int | None]:
    state = match.get("state")
    if not isinstance(state, dict):
        state = {}

    score = state.get("score")
    if not isinstance(score, dict):
        score = match.get("score") if isinstance(match.get("score"), dict) else {}

    # Primary Highlightly shape:
    #   score.current = "HOME - AWAY"
    home, away = parse_highlightly_current_score(score.get("current"))
    if home is not None and away is not None:
        return home, away

    # Baseball and some legacy payloads expose side objects.
    home = score_scalar(score.get("home"))
    away = score_scalar(score.get("away"))
    if home is not None and away is not None:
        return home, away

    # Backward-compatible variants.
    home = score_scalar(score.get("homeTeam"))
    away = score_scalar(score.get("awayTeam"))
    if home is not None and away is not None:
        return home, away

    home = score_scalar(match.get("homeScore"))
    away = score_scalar(match.get("awayScore"))
    return home, away

def match_finished(match: dict[str, Any]) -> bool:
    state = match.get("state")
    desc = ""
    if isinstance(state, dict):
        desc = clean_text(state.get("description") or state.get("status") or state.get("name"))
    desc = (desc + " " + clean_text(match.get("status"))).lower()
    return any(word in desc for word in ("finished", "final", "ended", "complete", "completed"))


def match_league_text(match: dict[str, Any]) -> str:
    values = []

    league = match.get("league")
    if isinstance(league, dict):
        for key in ("name", "displayName", "abbreviation", "slug"):
            if clean_text(league.get(key)):
                values.append(clean_text(league.get(key)))
    elif league is not None:
        values.append(clean_text(league))

    for key in ("leagueName", "competitionName", "tournamentName"):
        if clean_text(match.get(key)):
            values.append(clean_text(match.get(key)))

    return " | ".join(values).lower()


def match_country_text(match: dict[str, Any]) -> str:
    country = match.get("country")
    if isinstance(country, dict):
        return clean_text(country.get("name") or country.get("code")).lower()
    return clean_text(country).lower()


def classify_highlightly_league(
    match: dict[str, Any],
    league_matchers: dict[str, list[str]],
) -> str | None:
    league_text = match_league_text(match)
    country_text = match_country_text(match)
    if not league_text:
        return None

    for league, needles in league_matchers.items():
        if not any(needle.lower() in league_text for needle in needles):
            continue

        # "Premier League" exists in multiple countries. EPL means England only.
        if league == "EPL":
            if country_text not in {"england", "gb-eng", "eng"}:
                continue

        # MLS should be the North American Major League Soccer competition.
        if league == "MLS":
            if "major league soccer" not in league_text and league_text.strip() != "mls":
                continue
            if country_text and country_text not in {
                "usa", "united states", "united states of america",
                "canada", "us", "ca",
            }:
                continue

        return league
    return None

def build_highlightly_url(cfg: dict[str, Any], date_text: str) -> str:
    # Date is itself a primary filter in Highlightly's documented matches API.
    # Fetch by sport/date, then classify the returned league locally. This avoids
    # league-filter differences between MLB/NFL/NBA/NHL/football products.
    params = urllib.parse.urlencode({
        "date": date_text,
        "timezone": "America/New_York",
        "limit": 100,
    })
    return f"https://sports.highlightly.net{cfg['path']}?{params}"


def parse_highlightly_sport(
    cfg: dict[str, Any],
    generated_at: datetime,
    cutoff: datetime,
    run_log: dict[str, Any],
    api_key: str,
    fbs_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    if not api_key:
        entry = make_source_log(
            source_id=cfg["id"], provider="Highlightly", kind="matches",
            league_hint="MULTI", url="[disabled: missing HIGHLIGHTLY_API_KEY]",
        )
        entry["finishedAt"] = iso_z(utc_now())
        entry["error"] = "HIGHLIGHTLY_API_KEY not configured"
        run_log["sourceFetches"].append(entry)
        return candidates

    eastern_now = generated_at.astimezone(
        __import__("zoneinfo").ZoneInfo("America/New_York")
    )
    dates = [eastern_now.date(), (eastern_now - timedelta(days=1)).date()]

    for day in dates:
        source_id = f"{cfg['id']}-{day.isoformat()}"
        url = build_highlightly_url(cfg, day.isoformat())
        entry = make_source_log(
            source_id=source_id,
            provider="Highlightly",
            kind="matches",
            league_hint="MULTI",
            url=url,
        )
        run_log["sourceFetches"].append(entry)
        started = time.monotonic()

        try:
            status, headers, body = fetch_bytes(
                url,
                headers={
                    "Accept": "application/json",
                    "x-rapidapi-key": api_key,
                },
            )
            finalize_source_log(entry, started, status, headers, body)
            payload = json.loads(body.decode("utf-8"))
            matches = unwrap_highlightly(payload)
            entry["receivedItems"] = matches[:100]

            for idx, match in enumerate(matches[:100]):
                try:
                    target_league = classify_highlightly_league(
                        match, cfg["leagueMatchers"]
                    )
                    if not target_league:
                        entry["rejectedItems"].append({
                            "index": idx,
                            "matchId": match.get("id"),
                            "reason": (
                                "league not one of tracked base leagues; "
                                f"leagueText={match_league_text(match)!r}"
                            ),
                        })
                        continue

                    if not match_finished(match):
                        entry["rejectedItems"].append({
                            "index": idx,
                            "matchId": match.get("id"),
                            "reason": "match not final",
                        })
                        continue

                    scheduled = clean_text(
                        match.get("date")
                        or match.get("startDate")
                        or match.get("startTime")
                    )
                    home = team_name(match, "home")
                    away = team_name(match, "away")
                    home_score, away_score = match_score(match)

                    if not scheduled or not home or not away:
                        raise TickerError("missing date/team data")
                    if home_score is None or away_score is None:
                        raise TickerError("final match missing usable score")

                    if home_score > away_score:
                        winner, loser = home, away
                    elif away_score > home_score:
                        winner, loser = away, home
                    else:
                        winner, loser = home, away

                    type_hint = "RESULT"
                    quality = 100
                    result_context: dict[str, Any] = {}

                    if target_league == "NCAAF":
                        fbs_context = fbs_context or {
                            "teamNames": FBS_TEAMS_2026,
                            "rankByName": {},
                            "aliasIndex": build_fbs_alias_index(FBS_TEAMS_2026),
                            "mode": "static-fallback",
                        }
                        home_fbs = match_fbs_team(home, fbs_context)
                        away_fbs = match_fbs_team(away, fbs_context)
                        home_rank = fbs_rank_for(home, fbs_context)
                        away_rank = fbs_rank_for(away, fbs_context)

                        if not home_fbs and not away_fbs:
                            raise TickerError("NCAAF result excluded: no FBS team involved")

                        fbs_winner = (
                            home_fbs if winner == home else away_fbs
                        )
                        fbs_loser = (
                            away_fbs if winner == home else home_fbs
                        )

                        # FBS-v-lower-division wins are routine and noisy. Keep
                        # them only if a top-25 FBS team is involved. But if the
                        # lower-division team beats an FBS team, preserve it as
                        # a major upset candidate.
                        exactly_one_fbs = bool(home_fbs) ^ bool(away_fbs)
                        fbs_team_lost = exactly_one_fbs and not fbs_winner
                        ranked_involved = bool(home_rank or away_rank)

                        if exactly_one_fbs and fbs_team_lost:
                            type_hint = "UPSET"
                            quality = 110
                        elif exactly_one_fbs and not ranked_involved:
                            raise TickerError(
                                "routine FBS-v-non-FBS win excluded from ticker candidates"
                            )
                        elif ranked_involved:
                            quality = 105
                        else:
                            quality = 96

                        result_context = {
                            "fbsContextMode": fbs_context.get("mode"),
                            "homeFbs": home_fbs,
                            "awayFbs": away_fbs,
                            "homeRank": home_rank,
                            "awayRank": away_rank,
                            "rankedTeamInvolved": ranked_involved,
                            "fbsVsFbs": bool(home_fbs and away_fbs),
                        }

                    if home_score != away_score:
                        winner_score = home_score if winner == home else away_score
                        loser_score = away_score if winner == home else home_score
                        title = f"{winner} beat {loser} {winner_score}-{loser_score}"
                    else:
                        title = f"{home} and {away} finished tied {home_score}-{away_score}"

                    summary = (
                        f"Highlightly final: {away} {away_score}, "
                        f"{home} {home_score}."
                    )

                    candidate = make_candidate(
                        source_id=entry["sourceId"],
                        provider="Highlightly",
                        league_hint=target_league,
                        sport_hint=cfg["sportHint"],
                        title=title,
                        summary=summary,
                        source_url="https://highlightly.net",
                        occurrence=scheduled,
                        generated_at=generated_at,
                        cutoff=cutoff,
                        type_hint=type_hint,
                        quality=quality,
                        raw_ref=f"{entry['sourceId']}#{idx}",
                        metadata={
                            "matchId": match.get("id"),
                            "eventKey": f"highlightly:{cfg['sportHint']}:{match.get('id')}",
                            "leagueText": match_league_text(match),
                            "homeTeam": home,
                            "awayTeam": away,
                            "homeScore": home_score,
                            "awayScore": away_score,
                            "scheduledAt": scheduled,
                            "scoreParser": "A3.3-current-home-away",
                            "rawScore": (
                                match.get("state", {}).get("score")
                                if isinstance(match.get("state"), dict)
                                else None
                            ),
                            "state": match.get("state"),
                            **result_context,
                        },
                    )
                    candidates.append(candidate)
                    entry["acceptedCandidateIds"].append(candidate["candidateId"])

                except Exception as exc:
                    entry["rejectedItems"].append({
                        "index": idx,
                        "matchId": match.get("id"),
                        "reason": clean_text(exc),
                    })

            if not entry["acceptedCandidateIds"]:
                entry["note"] = (
                    "Highlightly request succeeded but produced no FINAL matches "
                    "for tracked leagues inside the 24-hour window."
                )

        except urllib.error.HTTPError as exc:
            body = exc.read()
            finalize_source_log(entry, started, exc.code, exc.headers, body)
            entry["error"] = (
                f"HTTP {exc.code}: "
                f"{body[:1000].decode('utf-8', errors='replace')}"
            )
            append_failure(
                run_log,
                f"source:{source_id}",
                entry["error"],
                provider="Highlightly",
                sport=cfg["sportHint"],
            )
        except Exception as exc:
            if entry["finishedAt"] is None:
                finalize_source_log(entry, started, None, None, None)
            entry["error"] = clean_text(exc)
            append_failure(
                run_log,
                f"source:{source_id}",
                str(exc),
                provider="Highlightly",
                sport=cfg["sportHint"],
            )

    return candidates


STOPWORDS = {
    "the", "a", "an", "to", "of", "and", "in", "on", "for", "with", "at",
    "from", "as", "after", "before", "over", "vs", "v", "news", "latest",
}


def title_tokens(title: str) -> set[str]:
    return {
        tok for tok in re.findall(r"[a-z0-9]+", title.lower())
        if tok not in STOPWORDS and len(tok) > 1
    }


def title_similarity(a: str, b: str) -> float:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / max(1, len(ta | tb))
    seq = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return max(jaccard, seq * 0.85)


def candidate_provider_set(candidate: dict[str, Any]) -> set[str]:
    return {
        clean_text(record.get("provider"))
        for record in candidate.get("sourceRecords", [])
        if clean_text(record.get("provider"))
    }


def candidate_text_blob(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    values = [
        candidate.get("title", ""),
        candidate.get("summary", ""),
    ]
    categories = metadata.get("categories")
    if isinstance(categories, list):
        values.extend(clean_text(x) for x in categories)
    return _normalize_team_label(" ".join(clean_text(v) for v in values if clean_text(v)))


def team_mention_aliases(team: str) -> list[str]:
    normalized = _normalize_team_label(team)
    if not normalized:
        return []
    tokens = normalized.split()
    aliases = {normalized}
    if len(tokens) >= 2:
        aliases.add(" ".join(tokens[-2:]))
        aliases.add(tokens[-1])
        # School/location portion often appears without mascot.
        aliases.add(tokens[0])
        if len(tokens) >= 3:
            aliases.add(" ".join(tokens[:2]))
    aliases = {
        alias for alias in aliases
        if len(alias) >= 4
        and alias not in {"state", "united", "city", "college", "university", "team"}
    }
    return sorted(aliases, key=len, reverse=True)


def candidate_mentions_team(candidate: dict[str, Any], team: str) -> bool:
    blob = " " + candidate_text_blob(candidate) + " "
    for alias in team_mention_aliases(team):
        if f" {alias} " in blob:
            return True
    return False


def structured_match_pair(candidate: dict[str, Any]) -> tuple[str, str] | None:
    metadata = candidate.get("metadata")
    if not isinstance(metadata, dict):
        return None
    home = clean_text(metadata.get("homeTeam"))
    away = clean_text(metadata.get("awayTeam"))
    if home and away:
        return home, away
    return None


def structured_match_id(candidate: dict[str, Any]) -> str | None:
    metadata = candidate.get("metadata")
    if not isinstance(metadata, dict):
        return None
    match_id = metadata.get("matchId")
    return clean_text(match_id) if match_id is not None else None


def generic_source_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/").lower()
    if host in {"highlightly.net", "www.highlightly.net"}:
        return True
    if path in {
        "", "/news", "/en/news", "/news/category/news",
        "/sports/football/fbs",
    }:
        return True
    return False


def cross_source_match_reason(
    candidate: dict[str, Any],
    existing: dict[str, Any],
) -> str | None:
    if candidate.get("leagueHint") != existing.get("leagueHint"):
        return None
    if candidate.get("typeHint") not in {"RESULT", "UPSET"}:
        return None
    if existing.get("typeHint") not in {"RESULT", "UPSET"}:
        return None

    cand_id = structured_match_id(candidate)
    exist_id = structured_match_id(existing)

    # Same structured match ID is definitive.
    if cand_id and exist_id:
        return "same structured matchId" if cand_id == exist_id else None

    # If one side is a structured game and the other is an article/recap,
    # require the article to mention BOTH teams and be reasonably close in time.
    structured = candidate if structured_match_pair(candidate) else existing
    article = existing if structured is candidate else candidate
    pair = structured_match_pair(structured)
    if not pair:
        return None

    if not all(candidate_mentions_team(article, team) for team in pair):
        return None

    try:
        a = parse_datetime(candidate["occurredAt"])
        b = parse_datetime(existing["occurredAt"])
        if abs((a - b).total_seconds()) > 18 * 3600:
            return None
    except Exception:
        pass

    return "same game by team pair across structured/article sources"


def merge_candidate(
    dst: dict[str, Any],
    src: dict[str, Any],
    *,
    preserve_event_time: bool = False,
    merge_reason: str | None = None,
) -> None:
    seen = {(r["sourceId"], r["url"]) for r in dst["sourceRecords"]}
    for record in src["sourceRecords"]:
        key = (record["sourceId"], record["url"])
        if key not in seen:
            dst["sourceRecords"].append(record)
            seen.add(key)

    dst_meta = dst.setdefault("metadata", {})
    if not isinstance(dst_meta, dict):
        dst_meta = {}
        dst["metadata"] = dst_meta

    merged_ids = dst_meta.setdefault("mergedCandidateIds", [])
    if src.get("candidateId") and src["candidateId"] not in merged_ids:
        merged_ids.append(src["candidateId"])

    if merge_reason and merge_reason.startswith("same game"):
        fused = dst_meta.setdefault("fusedContext", [])
        fused.append({
            "candidateId": src.get("candidateId"),
            "providers": sorted(candidate_provider_set(src)),
            "title": src.get("title"),
            "summary": src.get("summary"),
            "occurredAt": src.get("occurredAt"),
            "sources": [
                {
                    "sourceId": r.get("sourceId"),
                    "provider": r.get("provider"),
                    "url": r.get("url"),
                }
                for r in src.get("sourceRecords", [])
            ],
        })

    # Structured score candidates should keep their actual event time and score
    # while still inheriting contextual source records / metadata.
    if src["quality"] > dst["quality"] and not structured_match_pair(dst):
        dst["quality"] = src["quality"]
        dst["summary"] = src["summary"] or dst["summary"]
        dst["title"] = src["title"] or dst["title"]
    else:
        dst["quality"] = max(int(dst.get("quality", 0)), int(src.get("quality", 0)))

    if not preserve_event_time:
        try:
            dst_dt = parse_datetime(dst["occurredAt"])
            src_dt = parse_datetime(src["occurredAt"])
            if src_dt > dst_dt:
                dst["occurredAt"] = src["occurredAt"]
                dst["timePrecision"] = src["timePrecision"]
                dst["ageHours"] = src["ageHours"]
        except Exception:
            pass

    if dst.get("typeHint") == "OTHER" and src.get("typeHint") != "OTHER":
        dst["typeHint"] = src["typeHint"]
    if src.get("typeHint") == "UPSET":
        dst["typeHint"] = "UPSET"


def dedupe_candidates(
    raw_candidates: list[dict[str, Any]],
    run_log: dict[str, Any],
) -> list[dict[str, Any]]:
    ordered = sorted(
        raw_candidates,
        key=lambda c: (
            -int(c.get("quality", 0)),
            float(c["ageHours"]) if c.get("ageHours") is not None else 999.0,
        ),
    )
    kept: list[dict[str, Any]] = []
    actions = []

    for candidate in ordered:
        merged_into = None
        candidate_urls = {r["url"] for r in candidate["sourceRecords"]}

        for existing in kept:
            same_bucket = (
                candidate["leagueHint"] == existing["leagueHint"]
                or "SPECIAL" in {candidate["leagueHint"], existing["leagueHint"]}
                or "SOCCER" in {candidate["leagueHint"], existing["leagueHint"]}
            )
            if not same_bucket:
                continue

            cand_match_id = structured_match_id(candidate)
            exist_match_id = structured_match_id(existing)

            # A3.5 critical rule: two structured matches with different match IDs
            # are distinct games. The generic Highlightly homepage URL must never
            # collapse them.
            if cand_match_id and exist_match_id and cand_match_id != exist_match_id:
                continue

            event_reason = cross_source_match_reason(candidate, existing)
            sim = title_similarity(candidate["title"], existing["title"])

            existing_urls = {r["url"] for r in existing["sourceRecords"]}
            intersecting = candidate_urls & existing_urls
            safe_same_url = any(
                not generic_source_url(url) for url in intersecting
            )

            merge_reason = None
            preserve_event_time = False

            if event_reason:
                merge_reason = event_reason
                preserve_event_time = bool(
                    structured_match_pair(candidate) or structured_match_pair(existing)
                )
            elif safe_same_url:
                merge_reason = "same specific source URL"
            elif sim >= 0.72:
                # Never use title similarity to merge two distinct structured
                # matches. That was already guarded above by matchId.
                merge_reason = "high title similarity"

            if merge_reason:
                # Prefer the structured match candidate as the destination so
                # scores/event time survive cross-source fusion.
                if structured_match_pair(candidate) and not structured_match_pair(existing):
                    candidate_copy = candidate
                    merge_candidate(
                        candidate_copy,
                        existing,
                        preserve_event_time=True,
                        merge_reason=merge_reason,
                    )
                    kept[kept.index(existing)] = candidate_copy
                    merged_into = candidate_copy["candidateId"]
                    into_id = candidate_copy["candidateId"]
                    merged_id = existing["candidateId"]
                else:
                    merge_candidate(
                        existing,
                        candidate,
                        preserve_event_time=preserve_event_time,
                        merge_reason=merge_reason,
                    )
                    merged_into = existing["candidateId"]
                    into_id = existing["candidateId"]
                    merged_id = candidate["candidateId"]

                actions.append({
                    "action": "merge",
                    "candidateId": merged_id,
                    "into": into_id,
                    "similarity": round(sim, 3),
                    "sameUrl": bool(intersecting),
                    "safeSameUrl": safe_same_url,
                    "reason": merge_reason,
                })
                break

        if merged_into is None:
            kept.append(candidate)
            actions.append({
                "action": "keep",
                "candidateId": candidate["candidateId"],
                "matchId": structured_match_id(candidate),
            })

    run_log["pipeline"]["dedupeActions"] = actions
    return kept


def candidate_sort_key(c: dict[str, Any]):
    type_weight = {
        "BREAKING": 0, "INJURY": 1, "TRADE": 1, "SIGNING": 1, "CONTRACT": 1,
        "PLAYOFF": 1, "STANDINGS": 1, "RECORD": 1, "MILESTONE": 2,
        "DEPTH_CHART": 2, "SUSPENSION": 2, "DISCIPLINE": 2, "LEGAL": 2,
        "COACHING": 2, "RESULT": 5, "OTHER": 6,
    }.get(c.get("typeHint"), 4)
    age = float(c["ageHours"]) if c.get("ageHours") is not None else 23.9
    return (type_weight, -int(c.get("quality", 0)), age)


def trim_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Preserve breadth by taking up to 25 per explicit base league and then fill
    # remaining slots from special/soccer/general candidates.
    buckets: dict[str, list[dict[str, Any]]] = {}
    for c in candidates:
        buckets.setdefault(c["leagueHint"], []).append(c)
    for values in buckets.values():
        values.sort(key=candidate_sort_key)

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    for league in BASE_LEAGUES:
        for c in buckets.get(league, [])[:25]:
            if c["candidateId"] not in selected_ids:
                selected.append(c)
                selected_ids.add(c["candidateId"])

    leftovers = [
        c for c in candidates
        if c["candidateId"] not in selected_ids
    ]
    leftovers.sort(key=candidate_sort_key)

    for c in leftovers:
        if len(selected) >= MAX_MODEL_CANDIDATES:
            break
        selected.append(c)
        selected_ids.add(c["candidateId"])

    selected.sort(key=candidate_sort_key)
    return selected[:MAX_MODEL_CANDIDATES]


def model_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidateId": candidate["candidateId"],
        "leagueHint": candidate["leagueHint"],
        "sportHint": candidate["sportHint"],
        "typeHint": candidate["typeHint"],
        "title": candidate["title"],
        "summary": candidate["summary"],
        "occurredAt": candidate["occurredAt"],
        "timePrecision": candidate["timePrecision"],
        "ageHours": candidate["ageHours"],
        "quality": candidate["quality"],
        "sources": [
            {
                "sourceId": r["sourceId"],
                "provider": r["provider"],
                "url": r["url"],
            }
            for r in candidate["sourceRecords"]
        ],
        "metadata": candidate.get("metadata", {}),
    }


def candidate_hash(candidates: list[dict[str, Any]]) -> str:
    semantic = []
    for c in candidates:
        semantic.append({
            "candidateId": c["candidateId"],
            "leagueHint": c["leagueHint"],
            "typeHint": c["typeHint"],
            "title": c["title"],
            "summary": c["summary"],
            "occurredAt": c["occurredAt"],
            "sources": sorted(
                (r["sourceId"], r["url"]) for r in c["sourceRecords"]
            ),
            "metadata": c.get("metadata", {}),
        })
    return semantic_hash(semantic)


def load_previous(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def extract_output_text(response: dict[str, Any]) -> str:
    chunks = []
    refusals = []
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                chunks.append(content["text"])
            elif content.get("type") == "refusal":
                refusals.append(str(content.get("refusal", "")))
    if refusals:
        raise TickerError("Model refusal: " + " | ".join(refusals))
    text = "\n".join(chunks).strip()
    if not text:
        raise TickerError("OpenAI response contained no output text")
    return text


def parse_openai_error(details: str) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(details)
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict):
            return clean_text(err.get("code")), clean_text(err.get("type"))
    except Exception:
        pass
    return None, None


def output_shape_summary(response: dict[str, Any]) -> list[dict[str, Any]]:
    summary=[]
    for item in response.get("output", []):
        if not isinstance(item, dict):
            summary.append({"type": type(item).__name__})
            continue
        content_types=[]
        for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
            if isinstance(content, dict):
                content_types.append(content.get("type"))
        summary.append({
            "type": item.get("type"),
            "status": item.get("status"),
            "contentTypes": content_types,
        })
    return summary


def call_openai(
    api_key: str,
    model: str,
    candidates: list[dict[str, Any]],
    run_log: dict[str, Any],
) -> dict[str, Any]:
    packet = {
        "generatedAt": run_log["generatedAt"],
        "freshnessCutoff": run_log["freshnessCutoff"],
        "baseLeagues": BASE_LEAGUES,
        "candidates": [model_candidate(c) for c in candidates],
    }

    payload = {
        "model": model,
        "store": False,
        "instructions": EDITOR_INSTRUCTIONS,
        "input": (
            "Select and wordsmith the Sports Ticker using only this candidate packet:\n"
            + json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
        ),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "sports_ticker_a3",
                "strict": True,
                "schema": MODEL_SCHEMA,
            }
        },
        # GPT-4o Mini supports 16,384 max output tokens. 12k leaves substantial
        # room for the seven league groups while bounding worst-case cost.
        "max_output_tokens": 12000,
        "prompt_cache_key": "sports-big-board-a3-editor-v4",
    }

    run_log["openai"]["called"] = True
    run_log["openai"]["requestPayload"] = payload
    run_log["openai"]["candidateCount"] = len(candidates)
    run_log["openai"]["startedAt"] = iso_z(utc_now())
    run_log["openai"]["selectedModel"] = model

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "sports-big-board-ticker-a3.4/1.0",
    }

    last_error: Exception | None = None

    # Two attempts maximum. This is primarily for transient transport/service
    # failures; a normal successful run is exactly one model call.
    for attempt_number in range(1, 3):
        attempt_log = {
            "attempt": attempt_number,
            "model": model,
            "startedAt": iso_z(utc_now()),
            "finishedAt": None,
            "httpStatus": None,
            "responseId": None,
            "responseStatus": None,
            "incompleteDetails": None,
            "usage": None,
            "outputShape": None,
            "rawResponseEnvelope": None,
            "rawOutputText": None,
            "error": None,
        }
        run_log["openai"]["attempts"].append(attempt_log)

        req = urllib.request.Request(
            OPENAI_API_URL, data=body, headers=headers, method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=OPENAI_TIMEOUT) as response:
                raw = response.read().decode("utf-8")
                result = json.loads(raw)

                # CRITICAL A3.2 CHANGE:
                # Record the entire non-secret API response BEFORE attempting to
                # extract output_text. If parsing fails, the run log still shows
                # exactly what OpenAI returned.
                attempt_log["finishedAt"] = iso_z(utc_now())
                attempt_log["httpStatus"] = response.status
                attempt_log["responseId"] = result.get("id")
                attempt_log["responseStatus"] = result.get("status")
                attempt_log["incompleteDetails"] = result.get("incomplete_details")
                attempt_log["usage"] = result.get("usage")
                attempt_log["outputShape"] = output_shape_summary(result)
                attempt_log["rawResponseEnvelope"] = result

                run_log["openai"]["httpStatus"] = response.status
                run_log["openai"]["responseId"] = result.get("id")
                run_log["openai"]["responseMeta"] = {
                    "model": result.get("model"),
                    "status": result.get("status"),
                    "serviceTier": result.get("service_tier"),
                    "incompleteDetails": result.get("incomplete_details"),
                    "outputShape": attempt_log["outputShape"],
                }
                run_log["openai"]["usage"] = result.get("usage")
                run_log["openai"]["rawResponseEnvelope"] = result

                if result.get("status") == "incomplete":
                    details = result.get("incomplete_details")
                    raise TickerError(
                        f"OpenAI response incomplete: {json.dumps(details, ensure_ascii=False)}"
                    )

                output_text = extract_output_text(result)
                attempt_log["rawOutputText"] = output_text
                run_log["openai"]["rawOutput"] = output_text

                model_output = json.loads(output_text)

                run_log["openai"]["finishedAt"] = iso_z(utc_now())
                run_log["openai"]["successfulAttempt"] = attempt_number
                run_log["openai"]["error"] = None
                return model_output

        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            code, err_type = parse_openai_error(details)
            message = f"OpenAI HTTP {exc.code}: {details[:4000]}"

            attempt_log["finishedAt"] = iso_z(utc_now())
            attempt_log["httpStatus"] = exc.code
            attempt_log["error"] = {
                "message": message,
                "code": code,
                "type": err_type,
            }
            run_log["openai"]["httpStatus"] = exc.code
            run_log["openai"]["error"] = {
                "message": message,
                "code": code,
                "type": err_type,
                "attempt": attempt_number,
            }
            last_error = TickerError(message)

            # These errors cannot recover by waiting.
            if (
                code in {"credit_balance_exhausted", "insufficient_quota"}
                or err_type == "insufficient_quota"
            ):
                raise last_error

            if (
                exc.code not in {408, 409, 429, 500, 502, 503, 504}
                or attempt_number == 2
            ):
                raise last_error

        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            TickerError,
        ) as exc:
            attempt_log["finishedAt"] = (
                attempt_log["finishedAt"] or iso_z(utc_now())
            )
            attempt_log["error"] = {
                "message": clean_text(exc),
                "exceptionType": type(exc).__name__,
            }
            run_log["openai"]["error"] = {
                "message": clean_text(exc),
                "attempt": attempt_number,
                "exceptionType": type(exc).__name__,
            }
            last_error = exc

            # Retry once for no-output/incomplete/transport/JSON issues. At
            # current GPT-4o Mini prices, this rare recovery is still pennies.
            if attempt_number == 2:
                raise TickerError(f"OpenAI editor failed: {exc}") from exc

        time.sleep(3 * attempt_number)

    raise TickerError(f"OpenAI editor failed: {last_error}")


def score_pairs(text: str) -> list[tuple[int, int]]:
    return [
        (int(a), int(b))
        for a, b in re.findall(r"(?<!\d)(\d{1,3})\s*[-–—]\s*(\d{1,3})(?!\d)", text)
    ]


def validate_copy_consistency(item: dict[str, Any], context: str) -> None:
    text = (item["headline"] + " " + item["text"]).lower()
    pairs = score_pairs(text)
    if any(term in text for term in ("shutout", "shut out", "blanked")):
        for a, b in pairs:
            if a > 0 and b > 0:
                raise TickerError(f"{context}: shutout wording conflicts with {a}-{b}")
    if any(term in text for term in ("one-point win", "one point win", "one-point victory", "one point victory")):
        for a, b in pairs:
            if abs(a - b) != 1:
                raise TickerError(f"{context}: one-point wording conflicts with {a}-{b}")


def union_sources(candidate_ids: list[str], by_id: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    out = []
    seen = set()
    for cid in candidate_ids:
        for record in by_id[cid]["sourceRecords"]:
            key = (record["provider"], record["sourceId"], record["url"])
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "provider": record["provider"],
                "sourceId": record["sourceId"],
                "url": record["url"],
            })
    return out


def best_occurrence(candidate_ids: list[str], by_id: dict[str, dict[str, Any]]):
    candidates = [by_id[cid] for cid in candidate_ids]
    exact = []
    date_only = []
    for c in candidates:
        if c["timePrecision"] == "date":
            date_only.append(c)
        else:
            try:
                exact.append((parse_datetime(c["occurredAt"]), c))
            except Exception:
                pass
    if exact:
        _, c = max(exact, key=lambda pair: pair[0])
        return c["occurredAt"], c["timePrecision"], c["ageHours"]
    c = max(date_only, key=lambda x: x["occurredAt"])
    return c["occurredAt"], "date", None


def curate_final_items(items: list[dict[str, Any]], context: str, run_log: dict[str, Any]):
    ordered = sorted(items, key=lambda x: (-int(x["priority"]), float(x["ageHours"]) if x["ageHours"] is not None else 23.9))
    selected = []
    result_count = 0
    preview_count = 0
    other_count = 0
    for item in ordered:
        kind = item["type"]
        if kind == "RESULT" and result_count >= 5:
            run_log["pipeline"]["finalDrops"].append({
                "context": context, "headline": item["headline"], "reason": "RESULT cap 5",
            })
            continue
        if kind == "RESULT":
            result_count += 1
        if kind in {"NEXT", "SCHEDULE"} and preview_count >= 2:
            run_log["pipeline"]["finalDrops"].append({
                "context": context, "headline": item["headline"], "reason": "NEXT/SCHEDULE cap 2",
            })
            continue
        if kind in {"NEXT", "SCHEDULE"}:
            preview_count += 1
        if kind == "OTHER" and other_count >= 1:
            run_log["pipeline"]["finalDrops"].append({
                "context": context, "headline": item["headline"], "reason": "OTHER cap 1",
            })
            continue
        if kind == "OTHER":
            other_count += 1
        selected.append(item)
        if len(selected) == 10:
            break
    for rank, item in enumerate(selected, 1):
        item["rank"] = rank
    return selected


PRIORITY_DEFAULTS = {
    "BREAKING": 96,
    "PLAYOFF": 90,
    "STANDINGS": 84,
    "TRADE": 86,
    "INJURY": 82,
    "RECORD": 84,
    "RECORD_CHASE": 80,
    "UPSET": 82,
    "SIGNING": 78,
    "CONTRACT": 76,
    "SUSPENSION": 80,
    "DISCIPLINE": 78,
    "LEGAL": 76,
    "RETURN": 74,
    "MILESTONE": 76,
    "RANKING": 74,
    "AWARD": 74,
    "STREAK": 70,
    "SLUMP": 68,
    "COACHING": 76,
    "ROSTER": 68,
    "DEPTH_CHART": 70,
    "LEAGUE_NEWS": 76,
    "STAT_LEADER": 68,
    "RESULT": 58,
    "NEXT": 52,
    "SCHEDULE": 50,
    "OTHER": 52,
}

PRIORITY_BANDS = {
    "BREAKING": (90, 100),
    "PLAYOFF": (80, 96),
    "STANDINGS": (70, 92),
    "TRADE": (72, 96),
    "INJURY": (65, 92),
    "RECORD": (70, 94),
    "RECORD_CHASE": (68, 90),
    "UPSET": (70, 94),
    "SIGNING": (65, 90),
    "CONTRACT": (62, 88),
    "SUSPENSION": (68, 92),
    "DISCIPLINE": (65, 90),
    "LEGAL": (62, 90),
    "RETURN": (60, 84),
    "MILESTONE": (62, 88),
    "RANKING": (60, 88),
    "AWARD": (60, 88),
    "STREAK": (58, 84),
    "SLUMP": (55, 80),
    "COACHING": (65, 90),
    "ROSTER": (55, 80),
    "DEPTH_CHART": (55, 80),
    "LEAGUE_NEWS": (58, 82),
    "STAT_LEADER": (55, 82),
    # Routine results cannot be 100. If it is truly seismic, classify UPSET,
    # PLAYOFF, RECORD, etc.
    "RESULT": (50, 65),
    "NEXT": (45, 62),
    "SCHEDULE": (45, 60),
    "OTHER": (45, 65),
}


def normalize_editor_priority(
    raw_priority: Any,
    item_type: str,
    context: str,
    run_log: dict[str, Any],
) -> int:
    try:
        priority = int(raw_priority)
    except Exception:
        priority = 0

    if priority <= 10:
        repaired = PRIORITY_DEFAULTS.get(item_type, 55)
        run_log["pipeline"]["editorRepairs"].append({
            "context": context,
            "field": "priority",
            "original": priority,
            "repaired": repaired,
            "reason": "editor appeared to use priority as ordinal rank",
        })
        return repaired

    low, high = PRIORITY_BANDS.get(item_type, (1, 100))
    repaired = max(low, min(high, priority))
    if repaired != priority:
        run_log["pipeline"]["editorRepairs"].append({
            "context": context,
            "field": "priority",
            "original": priority,
            "repaired": repaired,
            "reason": f"priority clamped to calibrated {item_type} band {low}-{high}",
        })
    return repaired


VAGUE_FRESHNESS = {
    "hours ago", "an hour ago", "today", "recently", "new report",
    "just now", "minutes ago", "this morning", "this afternoon",
    "this evening", "overnight",
}


def repair_freshness_basis(
    raw_basis: Any,
    candidate_ids: list[str],
    by_id: dict[str, dict[str, Any]],
    context: str,
    run_log: dict[str, Any],
) -> str:
    basis = clean_text(raw_basis)
    normalized = basis.lower().strip(" .")

    vague = (
        normalized in VAGUE_FRESHNESS
        or len(normalized.split()) < 4
        or not re.search(r"[a-zA-Z]", normalized)
    )
    if not vague:
        return basis

    primary = by_id[candidate_ids[0]]
    repaired = f"Fresh development: {primary['title']}."
    run_log["pipeline"]["editorRepairs"].append({
        "context": context,
        "field": "freshnessBasis",
        "original": basis,
        "repaired": repaired,
        "reason": "vague/non-factual freshness basis",
    })
    return repaired

def normalize_model_output(
    model_output: dict[str, Any],
    candidates: list[dict[str, Any]],
    generated_at: datetime,
    run_log: dict[str, Any],
) -> dict[str, Any]:
    by_id = {c["candidateId"]: c for c in candidates}
    leagues = []

    raw_leagues = model_output.get("leagues")
    league_map: dict[str, dict[str, Any]] = {}

    if isinstance(raw_leagues, dict):
        # A3.4 canonical shape: fixed required keys.
        unknown = [key for key in raw_leagues.keys() if key not in BASE_LEAGUES]
        if unknown:
            raise TickerError("model returned unknown league keys: " + ", ".join(unknown))
        for league in BASE_LEAGUES:
            group = raw_leagues.get(league)
            if not isinstance(group, dict):
                raise TickerError(f"model omitted/invalid fixed league key {league}")
            league_map[league] = group

    elif isinstance(raw_leagues, list):
        # Defensive legacy repair. Merge duplicate groups and synthesize missing
        # groups rather than failing a whole ticker.
        repairs = []
        for raw_group in raw_leagues:
            if not isinstance(raw_group, dict):
                continue
            league = clean_text(raw_group.get("league")).upper()
            if league not in BASE_LEAGUES:
                continue
            if league not in league_map:
                league_map[league] = {
                    "seasonState": raw_group.get("seasonState"),
                    "items": list(raw_group.get("items", []))
                    if isinstance(raw_group.get("items"), list) else [],
                }
            else:
                extra = raw_group.get("items", [])
                if isinstance(extra, list):
                    league_map[league]["items"].extend(extra)
                repairs.append(f"merged duplicate legacy league group {league}")

        for league in BASE_LEAGUES:
            if league not in league_map:
                league_map[league] = {"items": []}
                repairs.append(f"synthesized missing legacy league group {league}")

        if repairs:
            run_log["pipeline"]["editorRepairs"].append({
                "context": "league-groups",
                "field": "leagues",
                "original": "legacy array",
                "repaired": repairs,
                "reason": "defensive repair of duplicate/missing league groups",
            })
    else:
        raise TickerError("model output missing leagues object")

    for league in BASE_LEAGUES:
        group = league_map[league]
        season_state = deterministic_season_state(league, generated_at)
        run_log["pipeline"]["seasonStates"][league] = season_state
        legacy_state = clean_text(group.get("seasonState")).lower()
        if legacy_state and legacy_state != season_state:
            run_log["pipeline"]["editorRepairs"].append({
                "context": league,
                "field": "seasonState",
                "original": legacy_state,
                "repaired": season_state,
                "reason": "seasonState is owned deterministically by Python in A3.5",
            })

        raw_items = group.get("items", [])
        if not isinstance(raw_items, list):
            raw_items = []

        final_items = []
        for idx, raw_item in enumerate(raw_items, 1):
            try:
                candidate_ids = [clean_text(cid) for cid in raw_item["candidateIds"]]
                if not candidate_ids or any(cid not in by_id for cid in candidate_ids):
                    raise TickerError("unknown candidateId")

                # A base-league item must be grounded in at least one candidate
                # mapped to the same league. This prevents cross-league leakage.
                candidate_leagues = {by_id[cid].get("leagueHint") for cid in candidate_ids}
                if league not in candidate_leagues:
                    raise TickerError(
                        f"candidate league mismatch: expected {league}, got {sorted(candidate_leagues)}"
                    )

                item_type = clean_text(raw_item["type"]).upper()
                if item_type not in ALLOWED_TYPES:
                    raise TickerError("invalid type")

                occurred_at, precision, age = best_occurrence(candidate_ids, by_id)
                sources = union_sources(candidate_ids, by_id)

                item = {
                    "rank": idx,
                    "candidateIds": candidate_ids,
                    "type": item_type,
                    "priority": normalize_editor_priority(
                        raw_item["priority"], item_type, f"{league} #{idx}", run_log
                    ),
                    "headline": clean_text(raw_item["headline"]),
                    "text": clean_text(raw_item["text"]),
                    "entities": [
                        clean_text(x)
                        for x in raw_item.get("entities", [])
                        if clean_text(x)
                    ],
                    "occurredAt": occurred_at,
                    "timePrecision": precision,
                    "ageHours": age,
                    "freshnessBasis": repair_freshness_basis(
                        raw_item["freshnessBasis"], candidate_ids, by_id,
                        f"{league} #{idx}", run_log
                    ),
                    "status": clean_text(raw_item["status"]).lower(),
                    "sourceUrls": [s["url"] for s in sources],
                    "sources": sources,
                }
                item["id"] = "a3-" + hashlib.sha1(
                    ("|".join(candidate_ids) + "|" + item["headline"]).encode("utf-8")
                ).hexdigest()[:16]

                if item["status"] not in ALLOWED_STATUS:
                    raise TickerError("invalid status")
                validate_copy_consistency(item, f"{league} #{idx}")
                final_items.append(item)

            except Exception as exc:
                run_log["pipeline"]["finalDrops"].append({
                    "context": league,
                    "index": idx,
                    "headline": clean_text(raw_item.get("headline")),
                    "reason": clean_text(exc),
                })

        final_items = curate_final_items(final_items, league, run_log)
        leagues.append({
            "league": league,
            "seasonState": season_state,
            "items": final_items,
        })

    special_events = []
    for event_index, event in enumerate(model_output.get("specialEvents", []), 1):
        name = clean_text(event.get("name"))
        sport = clean_text(event.get("sport"))
        if not name or not sport:
            continue

        items = []
        for idx, raw_item in enumerate(event.get("items", []), 1):
            try:
                candidate_ids = [clean_text(cid) for cid in raw_item["candidateIds"]]
                if not candidate_ids or any(cid not in by_id for cid in candidate_ids):
                    raise TickerError("unknown candidateId")

                occurred_at, precision, age = best_occurrence(candidate_ids, by_id)
                sources = union_sources(candidate_ids, by_id)
                item_type = clean_text(raw_item["type"]).upper()
                if item_type not in ALLOWED_TYPES:
                    raise TickerError("invalid type")

                item = {
                    "rank": idx,
                    "candidateIds": candidate_ids,
                    "type": item_type,
                    "priority": normalize_editor_priority(
                        raw_item["priority"], item_type, f"{name} #{idx}", run_log
                    ),
                    "headline": clean_text(raw_item["headline"]),
                    "text": clean_text(raw_item["text"]),
                    "entities": [
                        clean_text(x)
                        for x in raw_item.get("entities", [])
                        if clean_text(x)
                    ],
                    "occurredAt": occurred_at,
                    "timePrecision": precision,
                    "ageHours": age,
                    "freshnessBasis": repair_freshness_basis(
                        raw_item["freshnessBasis"], candidate_ids, by_id,
                        f"{name} #{idx}", run_log
                    ),
                    "status": clean_text(raw_item["status"]).lower(),
                    "sourceUrls": [s["url"] for s in sources],
                    "sources": sources,
                }
                item["id"] = "a3-special-" + hashlib.sha1(
                    ("|".join(candidate_ids) + "|" + item["headline"]).encode("utf-8")
                ).hexdigest()[:16]

                if item["status"] not in ALLOWED_STATUS:
                    raise TickerError("invalid status")
                validate_copy_consistency(item, f"{name} #{idx}")
                items.append(item)

            except Exception as exc:
                run_log["pipeline"]["finalDrops"].append({
                    "context": name,
                    "index": idx,
                    "headline": clean_text(raw_item.get("headline")),
                    "reason": clean_text(exc),
                })

        items = curate_final_items(items, name, run_log)
        if items:
            special_events.append({"name": name, "sport": sport, "items": items})

    return {"leagues": leagues, "specialEvents": special_events}

def semantic_ticker(dataset: dict[str, Any]) -> dict[str, Any]:
    def sem_item(i):
        return {
            "candidateIds": i.get("candidateIds", []),
            "type": i.get("type"),
            "priority": i.get("priority"),
            "headline": i.get("headline"),
            "text": i.get("text"),
            "entities": i.get("entities", []),
            "occurredAt": i.get("occurredAt"),
            "timePrecision": i.get("timePrecision"),
            "freshnessBasis": i.get("freshnessBasis"),
            "status": i.get("status"),
            "sourceUrls": i.get("sourceUrls", []),
        }
    return {
        "schemaVersion": dataset.get("schemaVersion"),
        "pipelineVersion": dataset.get("pipelineVersion"),
        "sourceCandidateHash": dataset.get("sourceCandidateHash"),
        "leagues": [
            {
                "league": g.get("league"),
                "seasonState": g.get("seasonState"),
                "items": [sem_item(i) for i in g.get("items", [])],
            }
            for g in dataset.get("leagues", [])
        ],
        "specialEvents": [
            {
                "name": e.get("name"),
                "sport": e.get("sport"),
                "items": [sem_item(i) for i in e.get("items", [])],
            }
            for e in dataset.get("specialEvents", [])
        ],
    }


def age_label(item: dict[str, Any]) -> str:
    age = item.get("ageHours")
    if age is None:
        return f"date-only {item['occurredAt']}"
    return f"{float(age):.2f}h"


def render_text(dataset: dict[str, Any]) -> str:
    lines = [
        "SPORTS BIG BOARD — SPORTS TICKER A3",
        f"Updated: {dataset['generatedAt']}",
        f"Freshness window: last {dataset['freshnessHours']} hours",
        f"Discovery: {dataset['discoveryMode']}",
        f"Editor model: {dataset['model']}",
        f"Candidate hash: {dataset['sourceCandidateHash']}",
        "",
    ]
    for group in dataset["leagues"]:
        lines += ["=" * 76, f"{group['league']}  [{group['seasonState'].upper()}]", "=" * 76, ""]
        if not group["items"]:
            lines += ["    No selected ticker items in this run.", ""]
        for item in group["items"]:
            lines.append(
                f"{item['rank']:>2}. [{item['type']}] {item['headline']} "
                f"(priority {item['priority']}, age {age_label(item)})"
            )
            lines.append(f"    {item['text']}")
            lines.append(
                f"    Occurred: {item['occurredAt']} | "
                f"Precision: {item['timePrecision']} | Status: {item['status']}"
            )
            lines.append(f"    Freshness basis: {item['freshnessBasis']}")
            if item["entities"]:
                lines.append("    Entities: " + ", ".join(item["entities"]))
            lines.append("    Candidate IDs: " + ", ".join(item["candidateIds"]))
            for source in item["sources"]:
                lines.append(
                    f"    Source [{source['provider']}/{source['sourceId']}]: {source['url']}"
                )
            lines.append("")
    if dataset["specialEvents"]:
        lines += ["#" * 76, "SPECIAL EVENTS", "#" * 76, ""]
        for event in dataset["specialEvents"]:
            lines += [f"{event['name']} ({event['sport']})", "-" * 76, ""]
            for item in event["items"]:
                lines.append(
                    f"{item['rank']:>2}. [{item['type']}] {item['headline']} "
                    f"(priority {item['priority']}, age {age_label(item)})"
                )
                lines.append(f"    {item['text']}")
                lines.append(f"    Freshness basis: {item['freshnessBasis']}")
                lines.append("    Candidate IDs: " + ", ".join(item["candidateIds"]))
                for source in item["sources"]:
                    lines.append(
                        f"    Source [{source['provider']}/{source['sourceId']}]: {source['url']}"
                    )
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def atomic_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)


def write_run_log(path: Path, run_log: dict[str, Any]):
    run_log["finishedAt"] = iso_z(utc_now())
    atomic_write(path, json.dumps(run_log, indent=2, ensure_ascii=False) + "\n")


def initial_run_log(generated_at: datetime, cutoff: datetime, model: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "pipelineVersion": "A3.5-result-preservation-event-fusion",
        "runId": f"a3-{generated_at.strftime('%Y%m%dT%H%M%SZ')}",
        "status": "running",
        "startedAt": iso_z(generated_at),
        "finishedAt": None,
        "generatedAt": iso_z(generated_at),
        "freshnessCutoff": iso_z(cutoff),
        "configuration": {
            "freshnessHours": FRESHNESS_HOURS,
            "model": model,
            "openAIWebSearchEnabled": False,
            "editorTransport": "Responses API structured output; raw envelope logged before parsing",
            "espnTransport": "site.api.espn.com JSON news endpoints",
            "highlightlyTransport": "sports.highlightly.net by sport/date, local league filtering",
            "maxModelCandidates": MAX_MODEL_CANDIDATES,
            "espnSourceCount": len(ESPN_SOURCES),
            "officialPageCount": len(OFFICIAL_PAGES),
            "highlightlySportCount": len(HIGHLIGHTLY_SPORTS),
            "highlightlyConfigured": bool(os.environ.get("HIGHLIGHTLY_API_KEY", "").strip()),
            "gitSha": os.environ.get("GITHUB_SHA"),
            "githubRunId": os.environ.get("GITHUB_RUN_ID"),
        },
        "sourceFetches": [],
        "pipeline": {
            "rawCandidateCount": 0,
            "dedupedCandidateCount": 0,
            "modelCandidateCount": 0,
            "candidateHash": None,
            "previousCandidateHash": None,
            "candidateSetChanged": None,
            "dedupeActions": [],
            "normalizedCandidates": [],
            "modelCandidates": [],
            "finalDrops": [],
            "editorRepairs": [],
            "seasonStates": {},
            "ncaafFbsContext": {},
        },
        "openai": {
            "called": False,
            "skipReason": None,
            "candidateCount": 0,
            "selectedModel": model,
            "startedAt": None,
            "finishedAt": None,
            "requestPayload": None,
            "attempts": [],
            "successfulAttempt": None,
            "httpStatus": None,
            "responseId": None,
            "responseMeta": None,
            "usage": None,
            "rawResponseEnvelope": None,
            "rawOutput": None,
            "error": None,
        },
        "output": {
            "tickerChanged": False,
            "tickerPreserved": False,
            "writtenFiles": [],
            "leagueItemCounts": {},
            "specialEventCount": 0,
            "semanticHash": None,
        },
        "failures": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument(
        "--model",
        default=os.environ.get("SPORTS_TICKER_EDITOR_MODEL", DEFAULT_MODEL),
    )
    parser.add_argument("--force-model", action="store_true")
    args = parser.parse_args()

    generated_at = utc_now()
    cutoff = generated_at - timedelta(hours=FRESHNESS_HOURS)
    data_dir = Path(args.data_dir)
    ticker_json = data_dir / "sports-ticker.json"
    ticker_txt = data_dir / "sports-ticker.txt"
    run_log_path = data_dir / "sports-ticker-run-log.json"

    run_log = initial_run_log(generated_at, cutoff, args.model)
    previous = load_previous(ticker_json)
    previous_candidate_hash = (
        previous.get("sourceCandidateHash")
        if isinstance(previous, dict)
        else None
    )
    run_log["pipeline"]["previousCandidateHash"] = previous_candidate_hash

    try:
        print(
            f"A3.5 direct-source refresh: {iso_z(cutoff)} to {iso_z(generated_at)}; "
            f"editor={args.model}; OpenAI web_search=OFF"
        )

        raw_candidates: list[dict[str, Any]] = []

        for source in ESPN_SOURCES:
            print(f"Fetching {source['id']}...")
            raw_candidates.extend(
                parse_espn_source(source, generated_at, cutoff, run_log)
            )

        for source in OFFICIAL_PAGES:
            print(f"Fetching {source['id']}...")
            raw_candidates.extend(parse_official_source(source, generated_at, cutoff, run_log))

        print("Fetching ESPN FBS scoreboard context...")
        fbs_context = fetch_espn_fbs_context(generated_at, run_log)

        highlightly_key = os.environ.get("HIGHLIGHTLY_API_KEY", "").strip()
        for cfg in HIGHLIGHTLY_SPORTS:
            print(f"Fetching {cfg['id']}...")
            raw_candidates.extend(
                parse_highlightly_sport(
                    cfg, generated_at, cutoff, run_log, highlightly_key,
                    fbs_context=fbs_context,
                )
            )

        run_log["pipeline"]["rawCandidateCount"] = len(raw_candidates)

        deduped = dedupe_candidates(raw_candidates, run_log)
        run_log["pipeline"]["dedupedCandidateCount"] = len(deduped)

        model_candidates = trim_candidates(deduped)
        run_log["pipeline"]["modelCandidateCount"] = len(model_candidates)
        run_log["pipeline"]["normalizedCandidates"] = deduped
        run_log["pipeline"]["modelCandidates"] = [model_candidate(c) for c in model_candidates]

        c_hash = candidate_hash(model_candidates)
        run_log["pipeline"]["candidateHash"] = c_hash
        changed = c_hash != previous_candidate_hash
        run_log["pipeline"]["candidateSetChanged"] = changed

        successful_espn = sum(
            1 for s in run_log["sourceFetches"]
            if s["provider"] == "ESPN"
            and s.get("kind") == "json-news-api"
            and s["httpStatus"] == 200
            and not s["error"]
        )
        successful_highlightly = sum(
            1 for s in run_log["sourceFetches"]
            if s["provider"] == "Highlightly"
            and s["httpStatus"] == 200
            and not s["error"]
        )
        run_log["pipeline"]["sourceHealth"] = {
            "successfulEspnJsonSources": successful_espn,
            "successfulHighlightlyRequests": successful_highlightly,
            "totalModelCandidates": len(model_candidates),
        }

        # We can tolerate official-page scraping failures. But do not call the
        # editor on an obviously broken discovery run.
        if successful_espn < 4 and successful_highlightly < 2:
            raise TickerError(
                "source-health gate failed: "
                f"ESPN JSON successes={successful_espn}, "
                f"Highlightly successes={successful_highlightly}"
            )
        if len(model_candidates) < 5:
            raise TickerError(
                f"source-health gate failed: only {len(model_candidates)} "
                "fresh candidates survived"
            )
        if not model_candidates:
            raise TickerError("no fresh candidates survived direct-source collection")

        if not changed and not args.force_model and previous is not None:
            run_log["status"] = "success-no-change"
            run_log["openai"]["skipReason"] = "candidate set unchanged"
            run_log["output"]["tickerPreserved"] = True
            run_log["output"]["tickerChanged"] = False
            print("Candidate set unchanged; skipping OpenAI and preserving ticker.")
            return 0

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise TickerError("OPENAI_API_KEY is required when candidate set changes")

        model_output = call_openai(
            api_key, args.model, model_candidates, run_log
        )

        normalized = normalize_model_output(
            model_output, model_candidates, generated_at, run_log
        )

        dataset = {
            "schemaVersion": 7,
            "pipelineVersion": "A3.5-result-preservation-event-fusion",
            "generatedAt": iso_z(generated_at),
            "freshnessHours": FRESHNESS_HOURS,
            "discoveryMode": "Highlightly + ESPN JSON news + ESPN FBS scoreboard context + official league pages; no OpenAI web search",
            "model": args.model,
            "sourceCandidateHash": c_hash,
            "leagues": normalized["leagues"],
            "specialEvents": normalized["specialEvents"],
        }

        json_output = json.dumps(dataset, indent=2, ensure_ascii=False) + "\n"
        text_output = render_text(dataset)

        previous_sem = semantic_ticker(previous) if previous else None
        current_sem = semantic_ticker(dataset)
        ticker_changed = previous_sem != current_sem

        if ticker_changed:
            atomic_write(ticker_json, json_output)
            atomic_write(ticker_txt, text_output)
            run_log["output"]["writtenFiles"].extend([
                str(ticker_json), str(ticker_txt)
            ])
        else:
            run_log["output"]["tickerPreserved"] = True

        run_log["status"] = (
            "success-with-source-failures"
            if run_log["failures"]
            else "success"
        )
        run_log["output"]["tickerChanged"] = ticker_changed
        run_log["output"]["semanticHash"] = semantic_hash(current_sem)
        run_log["output"]["leagueItemCounts"] = {
            g["league"]: len(g["items"]) for g in dataset["leagues"]
        }
        run_log["output"]["specialEventCount"] = len(dataset["specialEvents"])

        print(
            "A3 complete: "
            f"{len(model_candidates)} model candidates, "
            f"tickerChanged={ticker_changed}, "
            f"sourceFailures={len(run_log['failures'])}"
        )
        return 0

    except Exception as exc:
        run_log["status"] = "failed"
        run_log["output"]["tickerPreserved"] = True
        append_failure(run_log, "pipeline", str(exc))
        print(f"SPORTS TICKER A3 ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        write_run_log(run_log_path, run_log)


if __name__ == "__main__":
    raise SystemExit(main())

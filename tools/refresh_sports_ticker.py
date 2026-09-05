#!/usr/bin/env python3
"""Sports Big Board A3 Sports Ticker pipeline.

Discovery:
  - direct ESPN JSON news endpoints
  - direct official league news pages (best-effort JSON-LD/article extraction)
  - Highlightly structured match data

Editorial:
  - one configured OpenAI Responses API editorial call
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
MAX_DECISIVE_ENRICHMENTS = 16
MAX_HIGHLIGHTS_PER_ENRICHMENT = 20
MAX_GENERIC_RESULT_FILLERS = 2
RESULT_RELEVANCE_TARGET = 3
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
- 70-79: strong grounded result story: standout performance, late winner, milestone,
  meaningful first/clinching win, or similarly useful game context
- 60-69: useful normal ticker item; a close score alone belongs here, not in the 70s
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
  scores, ranks, FBS context, fusedContext, and resultEnrichment. Do not invent
  context that is not present in the candidate.
- If metadata.resultEnrichment.decisiveMoment exists, the headline and detail
  MUST lead with that decisive moment rather than merely restating the final score.
- Treat metadata.resultEnrichment.headlineSeed and summarySeed as grounded
  editorial seeds. You may tighten their wording, but do not remove the decisive
  fact they contain.
- metadata.storyPromotion is Python's strongest grounded result-story context.
  If storyPromotion exists, prefer its headlineSeed/summarySeed over a generic
  "Team A beat Team B" score headline. The headline should teach the reader WHY
  the result mattered or HOW it happened.
- When choosing among ordinary RESULT candidates, prefer higher storyPromotion.storyScore.
  A decisive-moment promotion or standout performance should beat a generic close
  score with no known story.
- Never use raw evidence boilerplate such as "Highlightly final:" as user-facing
  ticker copy when storyPromotion or fusedContext provides richer grounded prose.
- Never say walk-off, blocked kick, last-second, buzzer-beater, overtime,
  game-winner, or comeback unless those facts are present in resultEnrichment
  or another grounded candidate source.

Editorial mix rules:
- A RESULT should have a reason to exist: decisive finish, standout performance,
  upset, ranked consequence, playoff/standings consequence, milestone, comeback,
  or another grounded story hook. Prefer omission over padding.
- A generic draw or routine score with no story hook is low value and should
  normally be omitted.
- Maximum 5 ordinary RESULT items per base league.
- Maximum 2 combined NEXT/SCHEDULE items per base league.
- Do not pad a league.
- A major UPSET is not an ordinary RESULT.
- Special Events should cover important active events outside the seven base leagues.
- A Special Event name must be grounded in the selected candidate itself. Never place
  a Monaco Grand Prix story under the Italian Grand Prix merely because the Italian
  Grand Prix is the currently active F1 weekend. If the candidate names a specific
  tournament/race/event, use that event name.

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
        r"\blose(?:s|st)?\b[^.!?]{0,100}\bus open\b",
        r"\beliminated\b[^.!?]{0,100}\bus open\b",
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
    """Return normalized alias -> canonical FBS identity pairs."""
    values: dict[str, str] = {}
    for name in team_names:
        normalized = _normalize_team_label(name)
        if normalized:
            values[normalized] = name
    for alias, canonical in FBS_TEAM_ALIASES.items():
        values[_normalize_team_label(alias)] = canonical
    return list(values.items())


def _strict_fbs_alias_score(team_name: str, alias: str, canonical: str) -> float:
    """Conservative FBS name similarity used only after exact/known aliases.

    A3.8 used the ESPN group=80 scoreboard to expand membership, which caused
    FCS opponents in FBS-v-FCS games to become accidental FBS identities. A3.9
    makes the explicit 2026 FBS roster authoritative and uses fuzzy matching
    only to resolve spelling/display variants of those known members.
    """
    team_norm = _normalize_team_label(team_name)
    alias_norm = _normalize_team_label(alias)
    canonical_norm = _normalize_team_label(canonical)
    if not team_norm or not alias_norm:
        return 0.0
    if team_norm == alias_norm:
        return 1.0

    score = max(
        team_match_score(team_name, alias),
        team_match_score(team_name, canonical),
    )
    team_tokens = _team_token_set(team_name)
    canonical_tokens = _team_token_set(canonical)
    if not team_tokens or not canonical_tokens:
        return 0.0

    # Mascot agreement is a strong guard against location-name collisions such
    # as Indiana State vs Indiana or North Carolina A&T vs North Carolina.
    team_last = _normalize_team_label(team_name).split()[-1]
    canonical_last = canonical_norm.split()[-1]
    same_mascot = team_last == canonical_last

    if same_mascot and score >= 0.80:
        return score
    if score >= 0.94:
        return score
    return 0.0


def match_fbs_team(team_name: str, fbs_context: dict[str, Any]) -> str | None:
    team_norm = _normalize_team_label(team_name)
    if not team_norm:
        return None

    best_name = None
    best_score = 0.0
    for alias, canonical in fbs_context.get("aliasIndex", []):
        if team_norm == alias:
            return canonical
        score = _strict_fbs_alias_score(team_name, alias, canonical)
        if score > best_score:
            best_score = score
            best_name = canonical
    return best_name if best_score >= 0.80 else None


def fetch_espn_fbs_context(
    generated_at: datetime,
    run_log: dict[str, Any],
) -> dict[str, Any]:
    """Build FBS eligibility/rank context without allowing FCS contamination.

    The explicit 2026 138-team FBS roster is authoritative for membership.
    ESPN group=80 scoreboards validate current ESPN team IDs and top-25 ranks,
    but opponents that do not resolve to that roster remain non-FBS.
    """
    eastern_now = generated_at.astimezone(
        __import__("zoneinfo").ZoneInfo("America/New_York")
    )
    dates = [eastern_now.date(), (eastern_now - timedelta(days=1)).date()]

    team_names = set(FBS_TEAMS_2026)
    authoritative_alias_index = build_fbs_alias_index(sorted(team_names))
    identity_context = {
        "teamNames": sorted(team_names),
        "aliasIndex": authoritative_alias_index,
        "rankByName": {},
    }
    rank_by_name: dict[str, int] = {}
    espn_team_id_by_canonical: dict[str, str] = {}
    validated_fbs: set[str] = set()
    non_fbs_opponents: set[str] = set()
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
                    if not name:
                        continue

                    canonical = match_fbs_team(name, identity_context)
                    if not canonical:
                        non_fbs_opponents.add(name)
                        continue

                    validated_fbs.add(canonical)
                    team_id = clean_text(team.get("id") or team.get("uid"))
                    if team_id:
                        espn_team_id_by_canonical[canonical] = team_id

                    rank = competitor.get("curatedRank")
                    if isinstance(rank, dict):
                        try:
                            current = int(rank.get("current"))
                            if 1 <= current <= 25:
                                rank_by_name[canonical] = current
                        except Exception:
                            pass

            entry["note"] = (
                f"FBS identity validation accepted; events={len(events)}; "
                f"authoritativeRoster={len(team_names)}; "
                f"validatedFbs={len(validated_fbs)}; "
                f"nonFbsOpponents={len(non_fbs_opponents)}"
            )
        except Exception as exc:
            if entry["finishedAt"] is None:
                finalize_source_log(entry, started, None, None, None)
            entry["error"] = clean_text(exc)
            entry["note"] = "Using authoritative static 2026 FBS roster for this date."

    context = {
        "mode": (
            "authoritative-2026-roster+espn-id-rank-validation"
            if successful else "authoritative-2026-roster"
        ),
        "successfulScoreboardRequests": successful,
        "scoreboardEventCount": event_count,
        "teamCount": len(team_names),
        "teamNames": sorted(team_names),
        "rankByName": rank_by_name,
        "espnTeamIdByCanonical": dict(sorted(espn_team_id_by_canonical.items())),
        "validatedFbsTeams": sorted(validated_fbs),
        "scoreboardNonFbsOpponents": sorted(non_fbs_opponents),
        "aliasIndex": authoritative_alias_index,
    }

    run_log["pipeline"]["ncaafFbsContext"] = {
        "mode": context["mode"],
        "authoritativeRosterSize": len(team_names),
        "successfulScoreboardRequests": successful,
        "scoreboardEventCount": event_count,
        "validatedFbsTeamCount": len(validated_fbs),
        "validatedFbsTeams": sorted(validated_fbs),
        "espnTeamIdByCanonical": context["espnTeamIdByCanonical"],
        "nonFbsOpponentCount": len(non_fbs_opponents),
        "scoreboardNonFbsOpponents": sorted(non_fbs_opponents)[:100],
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
                            "fbsIdentityPolicy": "authoritative-2026-roster",
                            "homeFbs": home_fbs,
                            "awayFbs": away_fbs,
                            "homeRank": home_rank,
                            "awayRank": away_rank,
                            "rankedTeamInvolved": ranked_involved,
                            "fbsVsFbs": bool(home_fbs and away_fbs),
                            "homeEspnTeamId": (
                                fbs_context.get("espnTeamIdByCanonical", {}).get(home_fbs)
                                if home_fbs else None
                            ),
                            "awayEspnTeamId": (
                                fbs_context.get("espnTeamIdByCanonical", {}).get(away_fbs)
                                if away_fbs else None
                            ),
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



GAME_EVENT_FUSABLE_TYPES = {
    "RESULT", "UPSET", "RECORD", "RECORD_CHASE", "MILESTONE", "STREAK",
    "PLAYOFF", "STANDINGS", "RANKING", "STAT_LEADER", "AWARD",
}

TYPE_HINT_PRECEDENCE = {
    "OTHER": 0,
    "RESULT": 10,
    "NEXT": 12,
    "SCHEDULE": 12,
    "ROSTER": 20,
    "DEPTH_CHART": 20,
    "RETURN": 25,
    "INJURY": 25,
    "SIGNING": 30,
    "CONTRACT": 30,
    "TRADE": 35,
    "STREAK": 38,
    "RANKING": 40,
    "STAT_LEADER": 42,
    "MILESTONE": 45,
    "RECORD_CHASE": 48,
    "RECORD": 50,
    "STANDINGS": 52,
    "PLAYOFF": 55,
    "UPSET": 58,
    "BREAKING": 60,
}


def candidate_raw_text(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    parts = [
        clean_text(candidate.get("title")),
        clean_text(candidate.get("summary")),
    ]
    categories = metadata.get("categories")
    if isinstance(categories, list):
        parts.extend(clean_text(x) for x in categories if clean_text(x))
    for record in candidate.get("sourceRecords", []):
        if isinstance(record, dict):
            parts.append(clean_text(record.get("url")))
    fused = metadata.get("fusedContext")
    if isinstance(fused, list):
        for item in fused:
            if isinstance(item, dict):
                parts.append(clean_text(item.get("title")))
                parts.append(clean_text(item.get("summary")))
    return " ".join(x for x in parts if x)


def candidate_has_game_result_evidence(
    article: dict[str, Any],
    structured: dict[str, Any],
) -> bool:
    """Require score/result evidence before fusing non-RESULT news into a game.

    This deliberately refuses to merge an injury/legal/transaction story merely
    because it mentions both teams.
    """
    article_type = clean_text(article.get("typeHint")).upper()
    if article_type not in GAME_EVENT_FUSABLE_TYPES:
        return False

    raw = candidate_raw_text(article).lower()
    meta = structured.get("metadata") if isinstance(structured.get("metadata"), dict) else {}
    try:
        home_score = int(meta.get("homeScore"))
        away_score = int(meta.get("awayScore"))
    except Exception:
        home_score = away_score = None

    if home_score is not None and away_score is not None:
        score_patterns = [
            rf"(?<!\d){home_score}\s*[-–—]\s*{away_score}(?!\d)",
            rf"(?<!\d){away_score}\s*[-–—]\s*{home_score}(?!\d)",
        ]
        if any(re.search(pattern, raw) for pattern in score_patterns):
            return True

    result_terms = (
        " win ", " wins ", " won ", " beat ", " beats ", " defeated ",
        " defeats ", " rout ", " routs ", " shut out ", " shuts out ",
        " victory ", " loss ", " upset ",
    )
    padded = f" {raw} "
    return any(term in padded for term in result_terms)


def stronger_type_hint(a: str, b: str) -> str:
    aa = clean_text(a).upper() or "OTHER"
    bb = clean_text(b).upper() or "OTHER"
    return bb if TYPE_HINT_PRECEDENCE.get(bb, 0) > TYPE_HINT_PRECEDENCE.get(aa, 0) else aa


def cross_source_match_reason(
    candidate: dict[str, Any],
    existing: dict[str, Any],
) -> str | None:
    if candidate.get("leagueHint") != existing.get("leagueHint"):
        return None

    cand_id = structured_match_id(candidate)
    exist_id = structured_match_id(existing)

    # Same structured match ID is definitive.
    if cand_id and exist_id:
        return "same structured matchId" if cand_id == exist_id else None

    # We only cross-fuse when exactly one side supplies structured match identity.
    candidate_structured = bool(structured_match_pair(candidate))
    existing_structured = bool(structured_match_pair(existing))
    if candidate_structured == existing_structured:
        return None

    structured = candidate if candidate_structured else existing
    article = existing if candidate_structured else candidate
    pair = structured_match_pair(structured)
    if not pair:
        return None

    # Both teams must be explicitly represented in the article/recap.
    if not all(candidate_mentions_team(article, team) for team in pair):
        return None

    # RESULT/UPSET recaps are intrinsically game-result candidates. Other news
    # types (RECORD, MILESTONE, PLAYOFF, etc.) need score/result evidence.
    article_type = clean_text(article.get("typeHint")).upper()
    if article_type not in {"RESULT", "UPSET"}:
        if not candidate_has_game_result_evidence(article, structured):
            return None

    try:
        a = parse_datetime(candidate["occurredAt"])
        b = parse_datetime(existing["occurredAt"])
        if abs((a - b).total_seconds()) > 18 * 3600:
            return None
    except Exception:
        pass

    if article_type in {"RESULT", "UPSET"}:
        return "same game by team pair across structured/article sources"
    return f"same game news fusion: {article_type}"




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

    # Preserve the strongest grounded editorial type when a game result fuses
    # with a record/milestone/playoff/news development about that same game.
    dst["typeHint"] = stronger_type_hint(
        clean_text(dst.get("typeHint")),
        clean_text(src.get("typeHint")),
    )


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

                action = {
                    "action": "merge",
                    "candidateId": merged_id,
                    "into": into_id,
                    "similarity": round(sim, 3),
                    "sameUrl": bool(intersecting),
                    "safeSameUrl": safe_same_url,
                    "reason": merge_reason,
                }
                actions.append(action)
                if merge_reason.startswith("same game news fusion:"):
                    run_log["pipeline"]["gameEventFusion"]["merged"].append({
                        "candidateId": merged_id,
                        "into": into_id,
                        "reason": merge_reason,
                        "league": candidate.get("leagueHint"),
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



def highlightly_cfg_for_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    league = clean_text(candidate.get("leagueHint")).upper()
    sport_hint = clean_text(candidate.get("sportHint")).lower()

    for cfg in HIGHLIGHTLY_SPORTS:
        if sport_hint and sport_hint == clean_text(cfg.get("sportHint")).lower():
            return cfg
        if league and league in cfg.get("leagueMatchers", {}):
            return cfg
    return None


def unwrap_highlightly_detail(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, list):
        return next((x for x in payload if isinstance(x, dict)), None)
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return next((x for x in data if isinstance(x, dict)), None)
        return payload
    return None


def result_score_margin(candidate: dict[str, Any]) -> int | None:
    meta = candidate.get("metadata")
    if not isinstance(meta, dict):
        return None
    try:
        return abs(int(meta.get("homeScore")) - int(meta.get("awayScore")))
    except Exception:
        return None


def result_enrichment_threshold(candidate: dict[str, Any]) -> int:
    league = clean_text(candidate.get("leagueHint")).upper()
    if league == "MLB":
        return 2
    if league in {"NFL", "NCAAF"}:
        return 8
    if league == "NBA":
        return 6
    if league in {"NHL", "EPL", "MLS"}:
        return 1
    return 3


def fused_context_text(candidate: dict[str, Any]) -> str:
    meta = candidate.get("metadata")
    if not isinstance(meta, dict):
        return ""
    fused = meta.get("fusedContext")
    if not isinstance(fused, list):
        return ""
    parts = []
    for item in fused:
        if not isinstance(item, dict):
            continue
        parts.append(clean_text(item.get("title")))
        parts.append(clean_text(item.get("summary")))
    return " ".join(p for p in parts if p)


def result_enrichment_selection_score(candidate: dict[str, Any]) -> tuple[int, int, float]:
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    margin = result_score_margin(candidate)
    threshold = result_enrichment_threshold(candidate)
    type_hint = clean_text(candidate.get("typeHint")).upper()

    score = 0
    if type_hint == "UPSET":
        score += 100
    if meta.get("rankedTeamInvolved"):
        score += 30
    if margin is not None and margin <= threshold:
        score += 80 + max(0, threshold - margin)
    context = fused_context_text(candidate).lower()
    if any(term in context for term in (
        "walk-off", "walkoff", "game-winning", "last-second", "last second",
        "blocked field goal", "blocked kick", "overtime", "extra innings",
        "buzzer-beater", "buzzer beater", "time expired",
    )):
        score += 80

    age = float(candidate.get("ageHours") or 0.0)
    return score, int(candidate.get("quality", 0)), -age


def should_enrich_result(candidate: dict[str, Any]) -> tuple[bool, str]:
    if structured_match_id(candidate) is None:
        return False, "no structured matchId"
    if clean_text(candidate.get("typeHint")).upper() not in {"RESULT", "UPSET"}:
        return False, "not RESULT/UPSET"

    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    margin = result_score_margin(candidate)
    threshold = result_enrichment_threshold(candidate)

    reasons = []
    if clean_text(candidate.get("typeHint")).upper() == "UPSET":
        reasons.append("upset candidate")
    if meta.get("rankedTeamInvolved"):
        reasons.append("ranked team involved")
    if margin is not None and margin <= threshold:
        reasons.append(f"close result margin={margin}")
    context = fused_context_text(candidate).lower()
    if any(term in context for term in (
        "walk-off", "walkoff", "game-winning", "last-second", "last second",
        "blocked field goal", "blocked kick", "overtime", "extra innings",
        "buzzer-beater", "buzzer beater", "time expired",
    )):
        reasons.append("fused context signals decisive finish")

    if not reasons:
        return False, f"routine result margin={margin}"
    return True, "; ".join(reasons)


def highlightly_detail_url(cfg: dict[str, Any], match_id: str) -> str:
    return f"https://sports.highlightly.net{cfg['path']}/{match_id}"


def highlightly_highlights_url(cfg: dict[str, Any], match_id: str) -> str:
    highlight_path = cfg["path"].replace("/matches", "/highlights")
    params = urllib.parse.urlencode({
        "matchId": match_id,
        "limit": MAX_HIGHLIGHTS_PER_ENRICHMENT,
        "timezone": "America/New_York",
    })
    return f"https://sports.highlightly.net{highlight_path}?{params}"


def _clock_seconds(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    text = clean_text(value)
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    if re.fullmatch(r"\d+", text):
        return int(text)
    return None


def _period_number(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    text = clean_text(value).lower()
    match = re.search(r"(\d+)", text)
    if match:
        return int(match.group(1))
    words = {
        "first": 1, "1st": 1,
        "second": 2, "2nd": 2,
        "third": 3, "3rd": 3,
        "fourth": 4, "4th": 4,
        "fifth": 5, "5th": 5,
    }
    for word, num in words.items():
        if word in text:
            return num
    return None


def _baseball_inning(period: Any) -> tuple[str | None, int | None]:
    text = clean_text(period).lower()
    half = "bottom" if "bottom" in text else ("top" if "top" in text else None)
    match = re.search(r"(\d+)", text)
    return half, int(match.group(1)) if match else None


def _score_from_play(play: dict[str, Any]) -> tuple[int | None, int | None]:
    score = play.get("score")
    if not isinstance(score, dict):
        return None, None
    home = score_scalar(score.get("home"))
    away = score_scalar(score.get("away"))
    return home, away


def _named_player_from_baseball_play(play: dict[str, Any]) -> str | None:
    for key in ("batter", "player", "hitter"):
        obj = play.get(key)
        if isinstance(obj, dict):
            name = clean_text(
                obj.get("fullName") or obj.get("displayName") or obj.get("name")
            )
            if name:
                return name
    return None


def _candidate_result_names(candidate: dict[str, Any]) -> tuple[str, str, str, int, int]:
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    home = clean_text(meta.get("homeTeam"))
    away = clean_text(meta.get("awayTeam"))
    home_score = int(meta.get("homeScore"))
    away_score = int(meta.get("awayScore"))
    if home_score >= away_score:
        winner, loser = home, away
        winner_score, loser_score = home_score, away_score
    else:
        winner, loser = away, home
        winner_score, loser_score = away_score, home_score
    return winner, loser, home, winner_score, loser_score


def _base_result_flags(candidate: dict[str, Any]) -> list[str]:
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    league = clean_text(candidate.get("leagueHint")).upper()
    margin = result_score_margin(candidate)
    home_score = int(meta.get("homeScore", 0))
    away_score = int(meta.get("awayScore", 0))
    flags = []

    if margin is not None:
        if league == "MLB" and margin == 1:
            flags.append("ONE_RUN_GAME")
        elif league in {"NFL", "NCAAF"} and margin <= 8:
            flags.append("ONE_SCORE_GAME")
        elif league == "NBA" and margin <= 3:
            flags.append("ONE_POSSESSION_GAME")
        elif league in {"NHL", "EPL", "MLS"} and margin == 1:
            flags.append("ONE_GOAL_GAME")

    loser_score = min(home_score, away_score)
    if loser_score == 0:
        flags.append("SHUTOUT")

    blowout = (
        (league == "MLB" and margin is not None and margin >= 6)
        or (league in {"NFL", "NCAAF"} and margin is not None and margin >= 21)
        or (league == "NBA" and margin is not None and margin >= 20)
        or (league in {"NHL", "EPL", "MLS"} and margin is not None and margin >= 3)
    )
    if blowout:
        flags.append("BLOWOUT")
    if meta.get("rankedTeamInvolved"):
        flags.append("RANKED_TEAM_INVOLVED")
    if clean_text(candidate.get("typeHint")).upper() == "UPSET":
        flags.append("UPSET")

    return flags


def _ordinal_number(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _baseball_walkoff_inning_from_lines(candidate: dict[str, Any]) -> int | None:
    """Detect a walk-off directly from MLB inning lines.

    Highlightly's detailed MLB play array can contain more than one representation
    of the game (plate-appearance states followed by pitch-level events).  Inning
    lines are therefore the cheapest and most deterministic walk-off signal.
    """
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    try:
        final_home = int(meta.get("homeScore"))
        final_away = int(meta.get("awayScore"))
    except Exception:
        return None
    if final_home <= final_away:
        return None

    raw = meta.get("rawScore")
    if not isinstance(raw, dict):
        return None
    home = raw.get("home")
    away = raw.get("away")
    if not isinstance(home, dict) or not isinstance(away, dict):
        return None
    home_innings = home.get("innings")
    away_innings = away.get("innings")
    if not isinstance(home_innings, list) or not isinstance(away_innings, list):
        return None

    running_home = 0
    running_away = 0
    count = max(len(home_innings), len(away_innings))
    for idx in range(count):
        try:
            away_runs = int(away_innings[idx] or 0) if idx < len(away_innings) else 0
            home_runs = int(home_innings[idx] or 0) if idx < len(home_innings) else 0
        except Exception:
            return None
        running_away += away_runs
        home_before_bottom = running_home
        running_home += home_runs
        inning = idx + 1
        if (
            inning >= 9
            and home_runs > 0
            and home_before_bottom <= running_away
            and running_home > running_away
            and running_home == final_home
            and running_away == final_away
        ):
            return inning
    return None


def _baseball_play_order(period: Any) -> int | None:
    half, inning = _baseball_inning(period)
    if inning is None:
        return None
    return inning * 2 + (1 if half == "bottom" else 0)


def _baseball_segments(plays: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split duplicated Highlightly MLB representations into monotonic streams."""
    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    last_order = None
    last_total = None
    for idx, play in enumerate(plays):
        order = _baseball_play_order(play.get("period"))
        score = _score_from_play(play)
        total = None if score == (None, None) else int(score[0]) + int(score[1])
        reset = False
        if current and order is not None and last_order is not None and order < last_order:
            reset = True
        if current and total is not None and last_total is not None and total < last_total:
            reset = True
        if reset:
            segments.append(current)
            current = []
            last_order = None
            last_total = None
        clone = dict(play)
        clone["_a37Index"] = idx
        current.append(clone)
        if order is not None:
            last_order = order
        if total is not None:
            last_total = total
    if current:
        segments.append(current)
    return segments


def _baseball_scoring_description(
    plays: list[dict[str, Any]],
    inning: int,
    final_score: tuple[int, int],
) -> tuple[str | None, str | None]:
    """Find the actual bottom-inning scoring result, not a reset-state artifact."""
    ranked = []
    for idx, play in enumerate(plays):
        half, play_inning = _baseball_inning(play.get("period"))
        if half != "bottom" or play_inning != inning:
            continue
        desc = clean_text(play.get("description"))
        if not desc:
            continue
        low = desc.lower()
        player = _named_player_from_baseball_play(play)
        ptype = clean_text(play.get("type")).lower()
        score = _score_from_play(play)
        evidence = 0
        if " scored" in low or "homered" in low or "walk-off" in low or "walkoff" in low:
            evidence += 80
        if ptype in {
            "play result", "end batter/pitcher", "single", "double", "triple",
            "home run", "sacrifice fly", "sac fly", "fielder's choice",
        }:
            evidence += 25
        if score == final_score:
            evidence += 20
        if player:
            evidence += 10
        if evidence:
            ranked.append((evidence, idx, desc, player))
    if not ranked:
        return None, None
    _, _, desc, player = max(ranked, key=lambda item: (item[0], item[1]))
    return desc, player


def _baseball_walkoff_from_segment(
    candidate: dict[str, Any],
    segments: list[list[dict[str, Any]]],
) -> tuple[int | None, str | None, str | None]:
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    final_home = int(meta.get("homeScore"))
    final_away = int(meta.get("awayScore"))
    if final_home <= final_away:
        return None, None, None

    for segment in segments:
        last_score = None
        transitions = []
        for idx, play in enumerate(segment):
            current = _score_from_play(play)
            if current == (None, None):
                continue
            if last_score is not None and current != last_score:
                transitions.append((idx, play, last_score, current))
            last_score = current
        for idx, play, before, after in reversed(transitions):
            half, inning = _baseball_inning(play.get("period"))
            if (
                half == "bottom"
                and inning is not None
                and inning >= 9
                and after == (final_home, final_away)
                and before[0] <= before[1]
                and after[0] > after[1]
            ):
                desc = clean_text(play.get("description")) or None
                return inning, desc, _named_player_from_baseball_play(play)
    return None, None, None


def _derive_baseball_decisive(
    candidate: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any]:
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    home = clean_text(meta.get("homeTeam"))
    away = clean_text(meta.get("awayTeam"))
    final_home = int(meta.get("homeScore"))
    final_away = int(meta.get("awayScore"))
    if final_home <= final_away:
        return {}

    raw_plays = detail.get("plays")
    structured_plays = [p for p in raw_plays if isinstance(p, dict)] if isinstance(raw_plays, list) else []
    segments = _baseball_segments(structured_plays) if structured_plays else []

    inning = _baseball_walkoff_inning_from_lines(candidate)
    description = None
    player = None
    detection = None
    if inning is not None:
        detection = "inning-lines"
        if structured_plays:
            description, player = _baseball_scoring_description(
                structured_plays, inning, (final_home, final_away)
            )
    else:
        inning, description, player = _baseball_walkoff_from_segment(candidate, segments)
        if inning is not None:
            detection = "segmented-play-stream"

    if inning is None:
        return {}

    flags = ["WALK_OFF", "GAME_WINNER"]
    if inning > 9:
        flags.append("EXTRA_INNINGS")
    ordinal = _ordinal_number(inning)
    if player:
        decisive = f"{player} delivered the walk-off in the bottom of the {ordinal} inning."
        headline_seed = (
            f"{player} delivers walk-off as {home} beat {away} "
            f"{final_home}-{final_away}"
        )
    else:
        decisive = f"{home} scored the game-winning run in the bottom of the {ordinal} inning."
        headline_seed = f"{home} walk off {away} {final_home}-{final_away}"

    return {
        "flags": flags,
        "decisiveMoment": decisive,
        "decisivePlayer": player,
        "headlineSeed": headline_seed,
        "summarySeed": description or decisive,
        "priorityFloor": 78 if inning == 9 else 80,
        "contextLines": [x for x in (description, f"walk-off detected from {detection}") if x],
        "parserMode": detection,
    }

def _clock_from_football_text(text: str) -> str:
    match = re.search(r"\((\d{1,2}:\d{2})\)", text or "")
    return match.group(1) if match else ""


def _normalize_football_events(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize both Highlightly event.plays strings and playDetails objects."""
    events = detail.get("events")
    if not isinstance(events, list):
        return []
    normalized = []
    for event_index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        result = clean_text(event.get("result"))
        description = clean_text(event.get("description"))
        event_end = event.get("end") if isinstance(event.get("end"), dict) else {}
        event_start = event.get("start") if isinstance(event.get("start"), dict) else {}
        event_period = _period_number(event_end.get("period") or event_start.get("period"))
        event_clock = clean_text(event_end.get("clock") or event_start.get("clock"))

        seen_text = set()
        details = event.get("playDetails")
        if isinstance(details, list):
            for play_index, play in enumerate(details):
                if not isinstance(play, dict):
                    continue
                text = clean_text(play.get("text"))
                if text:
                    seen_text.add(text)
                period = _period_number(play.get("period")) or event_period
                clock = clean_text(play.get("clock")) or _clock_from_football_text(text) or event_clock
                combined = " | ".join(x for x in (text, result, description) if x)
                if combined:
                    normalized.append({
                        "eventIndex": event_index,
                        "playIndex": play_index,
                        "text": text or combined,
                        "combined": combined,
                        "period": period,
                        "clock": clock,
                        "clockSeconds": _clock_seconds(clock),
                        "sourceShape": "playDetails",
                    })

        # The live payload can put the decisive play only in event.plays even
        # when playDetails is also present. A3.6 skipped this representation.
        simple_plays = event.get("plays")
        if isinstance(simple_plays, list):
            for simple_index, raw in enumerate(simple_plays):
                text = clean_text(raw.get("text") if isinstance(raw, dict) else raw)
                if not text or text in seen_text:
                    continue
                period = event_period
                if isinstance(raw, dict):
                    period = _period_number(raw.get("period")) or event_period
                    clock = clean_text(raw.get("clock")) or _clock_from_football_text(text) or event_clock
                else:
                    clock = _clock_from_football_text(text) or event_clock
                combined = " | ".join(x for x in (text, result, description) if x)
                normalized.append({
                    "eventIndex": event_index,
                    "playIndex": 1000 + simple_index,
                    "text": text,
                    "combined": combined,
                    "period": period,
                    "clock": clock,
                    "clockSeconds": _clock_seconds(clock),
                    "sourceShape": "plays",
                })

        if not isinstance(details, list) and not isinstance(simple_plays, list):
            combined = " | ".join(x for x in (result, description) if x)
            if combined:
                normalized.append({
                    "eventIndex": event_index,
                    "playIndex": 0,
                    "text": combined,
                    "combined": combined,
                    "period": event_period,
                    "clock": event_clock,
                    "clockSeconds": _clock_seconds(event_clock),
                    "sourceShape": "event",
                })
    return normalized


def _derive_american_football_decisive(
    candidate: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any]:
    plays = _normalize_football_events(detail)
    if not plays:
        return {}

    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    home = clean_text(meta.get("homeTeam"))
    away = clean_text(meta.get("awayTeam"))
    home_score = int(meta.get("homeScore"))
    away_score = int(meta.get("awayScore"))
    winner = home if home_score > away_score else away
    loser = away if home_score > away_score else home
    winner_score = max(home_score, away_score)
    loser_score = min(home_score, away_score)
    margin = abs(home_score - away_score)

    event_ids = sorted({int(p.get("eventIndex", 0)) for p in plays})
    final_event_ids = set(event_ids[-3:])
    candidates = []
    for position, play in enumerate(plays):
        low = play["combined"].lower()
        period = play.get("period") or 0
        clock_seconds = play.get("clockSeconds")
        final_drive_window = int(play.get("eventIndex", 0)) in final_event_ids
        late = period >= 4 and clock_seconds is not None and clock_seconds <= 120
        last_seconds = (
            "time expired" in low
            or "as time expired" in low
            or "final play" in low
            or (period >= 4 and clock_seconds is not None and clock_seconds <= 15)
        )

        score = 0
        flags = []
        if "block" in low and ("field goal" in low or "kick" in low):
            score += 140
            flags.append("BLOCKED_KICK")
        if ("no good" in low or "missed" in low) and ("field goal" in low or "kick" in low):
            score += 105
            flags.append("MISSED_KICK")
        if "touchdown" in low:
            score += 60
        if "field goal" in low and any(term in low for term in (" good", "made", "is good")):
            score += 50
        if late:
            score += 40
            flags.append("LATE_GAME")
        if last_seconds:
            score += 70
            flags.append("LAST_SECOND")
        if final_drive_window:
            score += 35
        elif period < 4:
            score -= 45
        if margin <= 3:
            score += 20
        elif margin <= 8:
            score += 10

        if score > 0 and (final_drive_window or period >= 4):
            candidates.append((score, int(play.get("eventIndex", 0)), position, play, flags))

    if not candidates:
        return {}

    _, event_index, position, play, flags = max(candidates, key=lambda x: (x[0], x[1], x[2]))
    low = play["combined"].lower()
    decisive = None
    headline_seed = None
    summary_seed = None
    priority_floor = None

    if "BLOCKED_KICK" in flags and margin <= 3:
        flags.extend(["GAME_SAVING_PLAY", "GAME_WINNER"])
        last_second = "LAST_SECOND" in flags or event_index == max(event_ids)
        if last_second and "LAST_SECOND" not in flags:
            flags.append("LAST_SECOND")
        descriptor = "last-second " if last_second else "late "
        decisive = (
            f"{winner} blocked a {descriptor}field-goal attempt to preserve "
            f"a {winner_score}-{loser_score} win over {loser}."
        )
        headline_seed = (
            f"Blocked {descriptor}field goal seals {winner}'s "
            f"{winner_score}-{loser_score} win over {loser}"
        )
        summary_seed = play["text"] or decisive
        priority_floor = 82 if last_second else 78

    elif "MISSED_KICK" in flags and margin <= 3 and event_index in final_event_ids:
        flags.extend(["GAME_SAVING_PLAY", "GAME_WINNER"])
        last_second = "LAST_SECOND" in flags or event_index == max(event_ids)
        if last_second and "LAST_SECOND" not in flags:
            flags.append("LAST_SECOND")
        descriptor = "last-second " if last_second else "late "
        decisive = (
            f"{loser} missed a {descriptor}field-goal attempt as {winner} "
            f"held on {winner_score}-{loser_score}."
        )
        headline_seed = (
            f"{winner} survives {descriptor}missed field goal to beat "
            f"{loser} {winner_score}-{loser_score}"
        )
        summary_seed = play["text"] or decisive
        priority_floor = 80 if last_second else 76

    elif event_index in final_event_ids and margin <= 8 and (
        "touchdown" in low or "field goal" in low
    ) and ("LATE_GAME" in flags or "LAST_SECOND" in flags):
        flags.append("GAME_WINNER")
        priority_floor = 78 if "LAST_SECOND" in flags else 74
        decisive = play["text"] or play["combined"]
        headline_seed = (
            f"Late score lifts {winner} past {loser} "
            f"{winner_score}-{loser_score}"
        )
        summary_seed = decisive

    return {
        "flags": sorted(set(flags)),
        "decisiveMoment": decisive,
        "decisivePlayer": None,
        "headlineSeed": headline_seed,
        "summarySeed": summary_seed,
        "priorityFloor": priority_floor,
        "contextLines": [play["combined"]] if play.get("combined") else [],
        "parserMode": play.get("sourceShape"),
    } if decisive else {}

def _derive_soccer_decisive(
    candidate: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any]:
    events = detail.get("events")
    if not isinstance(events, list):
        return {}

    goals = []
    for event in events:
        if not isinstance(event, dict):
            continue
        type_text = clean_text(event.get("type")).lower()
        if "goal" not in type_text or "own" in type_text and "goal" not in type_text:
            continue
        minute_raw = event.get("minute") or event.get("time") or event.get("elapsed")
        minute = None
        if isinstance(minute_raw, (int, float)):
            minute = int(minute_raw)
        else:
            match = re.search(r"(\d+)", clean_text(minute_raw))
            if match:
                minute = int(match.group(1))
        player_obj = event.get("player")
        player = None
        if isinstance(player_obj, dict):
            player = clean_text(
                player_obj.get("name") or player_obj.get("displayName")
                or player_obj.get("fullName")
            )
        desc = clean_text(event.get("description") or event.get("text"))
        goals.append((minute or 0, player, desc))

    if not goals:
        return {}

    minute, player, desc = max(goals, key=lambda x: x[0])
    if minute < 85 or result_score_margin(candidate) != 1:
        return {}

    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    home = clean_text(meta.get("homeTeam"))
    away = clean_text(meta.get("awayTeam"))
    home_score = int(meta.get("homeScore"))
    away_score = int(meta.get("awayScore"))
    winner = home if home_score > away_score else away
    loser = away if home_score > away_score else home
    flags = ["LATE_GOAL", "GAME_WINNER"]
    if minute >= 90:
        flags.append("LAST_SECOND")
    decisive = (
        f"{player + ' scored' if player else 'A late goal came'} in the "
        f"{minute}th minute to decide {winner}'s {home_score if winner == home else away_score}-"
        f"{away_score if winner == home else home_score} win over {loser}."
    )
    return {
        "flags": flags,
        "decisiveMoment": decisive,
        "decisivePlayer": player,
        "headlineSeed": (
            f"{player + ' scores late as ' if player else 'Late goal lifts '}"
            f"{winner} beat {loser} "
            f"{home_score if winner == home else away_score}-"
            f"{away_score if winner == home else home_score}"
        ),
        "summarySeed": desc or decisive,
        "priorityFloor": 72 if minute < 90 else 76,
        "contextLines": [desc] if desc else [],
    }


def _derive_highlight_context(
    candidate: dict[str, Any],
    highlights: list[dict[str, Any]],
) -> dict[str, Any]:
    if not highlights:
        return {}

    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    home = clean_text(meta.get("homeTeam"))
    away = clean_text(meta.get("awayTeam"))
    home_score = int(meta.get("homeScore"))
    away_score = int(meta.get("awayScore"))
    winner = home if home_score > away_score else away
    loser = away if home_score > away_score else home
    winner_score = max(home_score, away_score)
    loser_score = min(home_score, away_score)

    category_weights = {
        "walk-off": 100,
        "buzzer-beater-game-winner": 100,
        "overtime-shootout-goal": 90,
        "defensive-play": 70,
        "field-goal": 65,
        "special-teams-play": 60,
        "big-play": 50,
        "match-highlights": 10,
    }

    scored = []
    for h in highlights:
        if not isinstance(h, dict):
            continue
        category = clean_text(h.get("category")).lower()
        title = clean_text(h.get("title"))
        description = clean_text(h.get("description"))
        combined = f"{title} {description}".lower()
        score = category_weights.get(category, 0)
        if "walk-off" in combined or "walkoff" in combined:
            score += 110
        if "blocked" in combined and ("field goal" in combined or "kick" in combined):
            score += 110
        if "buzzer" in combined and ("winner" in combined or "beater" in combined):
            score += 100
        if "game-winning" in combined or "game winner" in combined:
            score += 80
        if "overtime" in combined or "extra innings" in combined:
            score += 65
        if "last-second" in combined or "last second" in combined or "time expired" in combined:
            score += 70
        if score:
            scored.append((score, h, category, title, description))

    if not scored:
        return {}

    score, h, category, title, description = max(scored, key=lambda x: x[0])
    combined = f"{title} {description}".lower()
    flags = []
    decisive = None
    headline_seed = None
    summary_seed = description or title
    priority_floor = None

    if category == "walk-off" or "walk-off" in combined or "walkoff" in combined:
        flags.extend(["WALK_OFF", "GAME_WINNER"])
        priority_floor = 76
        decisive = description or title
        # Extract a leading person-name phrase only when the highlight itself
        # names the actor. The editor still receives the original title/desc.
        person_match = re.match(
            r"([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'.-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'.-]+){1,3})",
            title,
        )
        player = person_match.group(1) if person_match else None
        headline_seed = (
            f"{player} delivers walk-off as {winner} beat {loser} "
            f"{winner_score}-{loser_score}"
            if player else
            f"{winner} walk off {loser} {winner_score}-{loser_score}"
        )
        return {
            "flags": flags,
            "decisiveMoment": decisive,
            "decisivePlayer": player,
            "headlineSeed": headline_seed,
            "summarySeed": summary_seed,
            "priorityFloor": priority_floor,
            "contextLines": [x for x in (title, description) if x],
            "highlightId": h.get("id"),
            "highlightCategory": category,
        }

    if (
        category == "buzzer-beater-game-winner"
        or ("buzzer" in combined and ("winner" in combined or "beater" in combined))
    ):
        flags.extend(["BUZZER_BEATER", "GAME_WINNER", "LAST_SECOND"])
        priority_floor = 78
        decisive = description or title
        headline_seed = (
            f"Buzzer-beater lifts {winner} past {loser} "
            f"{winner_score}-{loser_score}"
        )

    elif (
        ("blocked" in combined and ("field goal" in combined or "kick" in combined))
        or (
            category in {"defensive-play", "field-goal", "special-teams-play"}
            and "blocked" in combined
        )
    ):
        flags.extend(["BLOCKED_KICK", "GAME_SAVING_PLAY"])
        if "last-second" in combined or "last second" in combined or "time expired" in combined:
            flags.append("LAST_SECOND")
        priority_floor = 78 if "LAST_SECOND" in flags else 74
        decisive = description or title
        descriptor = "last-second " if "LAST_SECOND" in flags else "late "
        headline_seed = (
            f"Blocked {descriptor}field goal seals {winner}'s "
            f"{winner_score}-{loser_score} win over {loser}"
        )

    elif category == "overtime-shootout-goal" or "overtime" in combined:
        flags.extend(["OVERTIME", "GAME_WINNER"])
        priority_floor = 72
        decisive = description or title
        headline_seed = (
            f"Overtime winner lifts {winner} past {loser} "
            f"{winner_score}-{loser_score}"
        )

    elif "game-winning" in combined or "game winner" in combined:
        flags.append("GAME_WINNER")
        if "last-second" in combined or "last second" in combined:
            flags.append("LAST_SECOND")
        priority_floor = 76 if "LAST_SECOND" in flags else 70
        decisive = description or title
        headline_seed = (
            f"Late winner lifts {winner} past {loser} "
            f"{winner_score}-{loser_score}"
        )

    if not decisive:
        return {}

    return {
        "flags": flags,
        "decisiveMoment": decisive,
        "decisivePlayer": None,
        "headlineSeed": headline_seed,
        "summarySeed": summary_seed,
        "priorityFloor": priority_floor,
        "contextLines": [x for x in (title, description) if x],
        "highlightId": h.get("id"),
        "highlightCategory": category,
    }


def _merge_enrichment_parts(
    base_flags: list[str],
    detail_part: dict[str, Any],
    highlight_part: dict[str, Any],
) -> dict[str, Any]:
    # Prefer a strong detailed-play derivation. Highlight metadata fills gaps.
    primary = detail_part if detail_part.get("decisiveMoment") else highlight_part
    secondary = highlight_part if primary is detail_part else detail_part

    flags = list(base_flags)
    flags.extend(primary.get("flags", []))
    flags.extend(secondary.get("flags", []))

    result = {
        "flags": sorted(set(flags)),
        "decisiveMoment": primary.get("decisiveMoment") or secondary.get("decisiveMoment"),
        "decisivePlayer": primary.get("decisivePlayer") or secondary.get("decisivePlayer"),
        "headlineSeed": primary.get("headlineSeed") or secondary.get("headlineSeed"),
        "summarySeed": primary.get("summarySeed") or secondary.get("summarySeed"),
        "priorityFloor": max(
            [
                x for x in (
                    primary.get("priorityFloor"),
                    secondary.get("priorityFloor"),
                )
                if isinstance(x, int)
            ] or [None],
            key=lambda x: -1 if x is None else x,
        ),
        "contextLines": list(dict.fromkeys(
            [
                clean_text(x)
                for x in (
                    list(primary.get("contextLines", []))
                    + list(secondary.get("contextLines", []))
                )
                if clean_text(x)
            ]
        ))[:8],
    }
    if primary.get("highlightId") or secondary.get("highlightId"):
        result["highlightId"] = primary.get("highlightId") or secondary.get("highlightId")
        result["highlightCategory"] = (
            primary.get("highlightCategory") or secondary.get("highlightCategory")
        )
    return result


def derive_decisive_context(
    candidate: dict[str, Any],
    detail: dict[str, Any] | None,
    highlights: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    detail = detail or {}
    highlights = highlights or []
    league = clean_text(candidate.get("leagueHint")).upper()
    base_flags = _base_result_flags(candidate)

    if league == "MLB":
        detail_part = _derive_baseball_decisive(candidate, detail)
    elif league in {"NFL", "NCAAF"}:
        detail_part = _derive_american_football_decisive(candidate, detail)
    elif league in {"EPL", "MLS"}:
        detail_part = _derive_soccer_decisive(candidate, detail)
    else:
        detail_part = {}

    highlight_part = _derive_highlight_context(candidate, highlights)
    merged = _merge_enrichment_parts(base_flags, detail_part, highlight_part)

    # Close/ranked games still get factual flags even when no named decisive
    # play is available. These flags help prioritization without inventing copy.
    if "UPSET" in base_flags:
        merged["priorityFloor"] = max(int(merged.get("priorityFloor") or 0), 82)
    if any(flag in base_flags for flag in (
        "ONE_RUN_GAME", "ONE_SCORE_GAME", "ONE_POSSESSION_GAME", "ONE_GOAL_GAME"
    )):
        merged["priorityFloor"] = max(int(merged.get("priorityFloor") or 0), 63)
    if "RANKED_TEAM_INVOLVED" in base_flags:
        merged["priorityFloor"] = max(int(merged.get("priorityFloor") or 0), 66)

    return merged


def _candidate_game_date(candidate: dict[str, Any]) -> str | None:
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    for value in (meta.get("scheduledAt"), candidate.get("occurredAt")):
        text = clean_text(value)
        if not text:
            continue
        try:
            return parse_iso(text).strftime("%Y%m%d")
        except Exception:
            match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
            if match:
                return "".join(match.groups())
    return None


def _espn_football_path(candidate: dict[str, Any]) -> str | None:
    league = clean_text(candidate.get("leagueHint")).upper()
    if league == "NCAAF":
        return "football/college-football"
    if league == "NFL":
        return "football/nfl"
    return None


def _fetch_espn_enrichment_json(
    *, candidate: dict[str, Any], run_log: dict[str, Any], source_id: str,
    kind: str, url: str,
) -> Any:
    entry = make_source_log(
        source_id=source_id, provider="ESPN", kind=kind,
        league_hint=clean_text(candidate.get("leagueHint")).upper(), url=url,
    )
    run_log["sourceFetches"].append(entry)
    started = time.monotonic()
    try:
        status, headers, body = fetch_bytes(url, headers={"Accept": "application/json"})
        finalize_source_log(entry, started, status, headers, body)
        payload = json.loads(body.decode("utf-8"))
        if isinstance(payload, dict):
            items = payload.get("events") or payload.get("plays") or []
            entry["receivedItems"] = items[:20] if isinstance(items, list) else []
        return payload
    except urllib.error.HTTPError as exc:
        body = exc.read()
        finalize_source_log(entry, started, exc.code, exc.headers, body)
        entry["error"] = f"HTTP {exc.code}: {body[:1200].decode('utf-8', errors='replace')}"
    except Exception as exc:
        if entry["finishedAt"] is None:
            finalize_source_log(entry, started, None, None, None)
        entry["error"] = clean_text(exc)
    return None


def _espn_competitor_name(comp: dict[str, Any]) -> str:
    team = comp.get("team") if isinstance(comp.get("team"), dict) else {}
    return clean_text(team.get("displayName") or team.get("shortDisplayName") or team.get("name"))


def _match_espn_event(candidate: dict[str, Any], scoreboard: dict[str, Any]) -> dict[str, Any] | None:
    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    wanted_home = clean_text(meta.get("homeTeam"))
    wanted_away = clean_text(meta.get("awayTeam"))
    best = None
    best_score = 0.0
    for event in scoreboard.get("events", []) if isinstance(scoreboard, dict) else []:
        if not isinstance(event, dict):
            continue
        comps = event.get("competitions")
        if not isinstance(comps, list) or not comps or not isinstance(comps[0], dict):
            continue
        competitors = comps[0].get("competitors")
        if not isinstance(competitors, list):
            continue
        home = next((x for x in competitors if isinstance(x, dict) and x.get("homeAway") == "home"), None)
        away = next((x for x in competitors if isinstance(x, dict) and x.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        score = (team_match_score(wanted_home, _espn_competitor_name(home)) +
                 team_match_score(wanted_away, _espn_competitor_name(away))) / 2.0
        if score > best_score:
            best_score = score
            best = event
    return best if best_score >= 0.72 else None


def _espn_summary_to_detail(summary: dict[str, Any]) -> dict[str, Any]:
    events = []
    drives_obj = summary.get("drives") if isinstance(summary, dict) else None
    drives = []
    if isinstance(drives_obj, dict):
        prev = drives_obj.get("previous")
        if isinstance(prev, list):
            drives.extend(prev)
        current = drives_obj.get("current")
        if isinstance(current, dict):
            drives.append(current)
    elif isinstance(drives_obj, list):
        drives.extend(drives_obj)

    if not drives and isinstance(summary.get("plays"), list):
        drives = [{"plays": summary.get("plays"), "displayResult": ""}]

    for drive in drives:
        if not isinstance(drive, dict):
            continue
        details = []
        for play in drive.get("plays", []) if isinstance(drive.get("plays"), list) else []:
            if not isinstance(play, dict):
                continue
            period_obj = play.get("period") if isinstance(play.get("period"), dict) else {}
            clock_obj = play.get("clock") if isinstance(play.get("clock"), dict) else {}
            details.append({
                "text": clean_text(play.get("text") or play.get("shortText")),
                "period": period_obj.get("number") or play.get("period"),
                "clock": clock_obj.get("displayValue") or play.get("clock"),
            })
        end_obj = drive.get("end") if isinstance(drive.get("end"), dict) else {}
        period_obj = end_obj.get("period") if isinstance(end_obj.get("period"), dict) else {}
        clock_obj = end_obj.get("clock") if isinstance(end_obj.get("clock"), dict) else {}
        events.append({
            "result": clean_text(drive.get("displayResult") or drive.get("result")),
            "description": clean_text(drive.get("description") or drive.get("shortDisplayName")),
            "end": {
                "period": period_obj.get("number") or end_obj.get("period"),
                "clock": clock_obj.get("displayValue") or end_obj.get("clock"),
            },
            "playDetails": details,
            "plays": [d["text"] for d in details if d.get("text")],
        })
    return {"events": events}


def _fetch_espn_football_fallback(
    candidate: dict[str, Any], run_log: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    path = _espn_football_path(candidate)
    date_key = _candidate_game_date(candidate)
    if not path or not date_key:
        return None, None, None
    scoreboard_url = (
        f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
        f"?dates={date_key}&limit=100"
    )
    scoreboard = _fetch_espn_enrichment_json(
        candidate=candidate, run_log=run_log,
        source_id=f"espn-{clean_text(candidate.get('leagueHint')).lower()}-scoreboard-{date_key}",
        kind="decisive-scoreboard", url=scoreboard_url,
    )
    event = _match_espn_event(candidate, scoreboard) if isinstance(scoreboard, dict) else None
    event_id = clean_text(event.get("id")) if isinstance(event, dict) else ""
    if not event_id:
        return None, None, None
    summary_url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={event_id}"
    summary = _fetch_espn_enrichment_json(
        candidate=candidate, run_log=run_log,
        source_id=f"espn-{clean_text(candidate.get('leagueHint')).lower()}-summary-{event_id}",
        kind="decisive-summary", url=summary_url,
    )
    if not isinstance(summary, dict):
        return None, event_id, summary_url
    return _espn_summary_to_detail(summary), event_id, summary_url


def _fetch_enrichment_json(
    *,
    candidate: dict[str, Any],
    run_log: dict[str, Any],
    api_key: str,
    source_id: str,
    kind: str,
    url: str,
) -> Any:
    entry = make_source_log(
        source_id=source_id,
        provider="Highlightly",
        kind=kind,
        league_hint=clean_text(candidate.get("leagueHint")).upper(),
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
        if kind == "match-detail":
            detail = unwrap_highlightly_detail(payload)
            entry["receivedItems"] = [detail] if isinstance(detail, dict) else []
            return detail
        highlights = unwrap_highlightly(payload)
        entry["receivedItems"] = highlights[:MAX_HIGHLIGHTS_PER_ENRICHMENT]
        return highlights
    except urllib.error.HTTPError as exc:
        body = exc.read()
        finalize_source_log(entry, started, exc.code, exc.headers, body)
        entry["error"] = (
            f"HTTP {exc.code}: "
            f"{body[:1500].decode('utf-8', errors='replace')}"
        )
        return None
    except Exception as exc:
        if entry["finishedAt"] is None:
            finalize_source_log(entry, started, None, None, None)
        entry["error"] = clean_text(exc)
        return None


def enrich_decisive_moments(
    candidates: list[dict[str, Any]],
    run_log: dict[str, Any],
    api_key: str,
) -> list[dict[str, Any]]:
    summary = run_log["pipeline"]["decisiveMomentEnrichment"]

    if not api_key:
        summary["skipReason"] = "HIGHLIGHTLY_API_KEY not configured"
        return candidates

    eligible = []
    for candidate in candidates:
        should, reason = should_enrich_result(candidate)
        if should:
            eligible.append((candidate, reason))
        elif structured_match_id(candidate) and clean_text(candidate.get("typeHint")).upper() in {"RESULT", "UPSET"}:
            summary["skipped"].append({
                "candidateId": candidate["candidateId"],
                "matchId": structured_match_id(candidate),
                "league": candidate.get("leagueHint"),
                "reason": reason,
            })

    eligible.sort(
        key=lambda pair: result_enrichment_selection_score(pair[0]),
        reverse=True,
    )
    selected = eligible[:MAX_DECISIVE_ENRICHMENTS]
    summary["selectedCandidateIds"] = [c["candidateId"] for c, _ in selected]
    summary["eligibleCount"] = len(eligible)

    for candidate, reason in selected:
        summary["attempted"] += 1
        cfg = highlightly_cfg_for_candidate(candidate)
        match_id = structured_match_id(candidate)
        item_log = {
            "candidateId": candidate["candidateId"],
            "league": candidate.get("leagueHint"),
            "matchId": match_id,
            "selectionReason": reason,
            "detailFetched": False,
            "highlightsFetched": False,
            "espnFallbackAttempted": False,
            "espnEventId": None,
            "espnSummaryFetched": False,
            "flags": [],
            "decisiveMoment": None,
            "headlineSeed": None,
            "priorityFloor": None,
            "error": None,
        }

        if not cfg or not match_id:
            item_log["error"] = "missing Highlightly sport config or matchId"
            summary["failures"].append(item_log)
            continue

        detail_url = highlightly_detail_url(cfg, match_id)
        detail = _fetch_enrichment_json(
            candidate=candidate,
            run_log=run_log,
            api_key=api_key,
            source_id=f"{cfg['id']}-detail-{match_id}",
            kind="match-detail",
            url=detail_url,
        )
        item_log["detailFetched"] = isinstance(detail, dict)

        detail_context = derive_decisive_context(candidate, detail, [])
        strong_detail = bool(detail_context.get("decisiveMoment"))

        highlights = []
        # Highlight lookup is the fallback/confirmation layer. Avoid a second
        # request when detailed play-by-play already gave a decisive moment,
        # except for MLB where walk-off highlight categories can identify the
        # named player more cleanly.
        if not strong_detail or clean_text(candidate.get("leagueHint")).upper() == "MLB":
            highlight_url = highlightly_highlights_url(cfg, match_id)
            highlight_payload = _fetch_enrichment_json(
                candidate=candidate,
                run_log=run_log,
                api_key=api_key,
                source_id=f"{cfg['id']}-highlights-{match_id}",
                kind="match-highlights",
                url=highlight_url,
            )
            if isinstance(highlight_payload, list):
                highlights = highlight_payload
                item_log["highlightsFetched"] = True

        enrichment = derive_decisive_context(candidate, detail, highlights)

        # For close NFL/NCAAF games, ESPN play-by-play is a bounded public-data
        # fallback when Highlightly detail/highlight metadata does not expose the
        # decisive play. No OpenAI web search is used.
        league = clean_text(candidate.get("leagueHint")).upper()
        margin = result_score_margin(candidate)
        if (
            not enrichment.get("decisiveMoment")
            and league in {"NFL", "NCAAF"}
            and margin is not None and margin <= 8
        ):
            item_log["espnFallbackAttempted"] = True
            espn_detail, espn_event_id, espn_summary_url = _fetch_espn_football_fallback(
                candidate, run_log
            )
            item_log["espnEventId"] = espn_event_id
            item_log["espnSummaryFetched"] = isinstance(espn_detail, dict)
            if isinstance(espn_detail, dict):
                espn_part = _derive_american_football_decisive(candidate, espn_detail)
                enrichment = _merge_enrichment_parts([], enrichment, espn_part)
                if espn_part.get("decisiveMoment") and espn_summary_url:
                    sources = candidate.setdefault("sources", [])
                    if not any(
                        isinstance(src, dict) and src.get("url") == espn_summary_url
                        for src in sources
                    ):
                        sources.append({
                            "sourceId": f"espn-{league.lower()}-summary-{espn_event_id}",
                            "provider": "ESPN",
                            "url": espn_summary_url,
                        })
                    enrichment["espnEventId"] = espn_event_id
                    enrichment["espnSummaryUrl"] = espn_summary_url

        enrichment.update({
            "attempted": True,
            "matchId": match_id,
            "selectionReason": reason,
            "detailFetched": item_log["detailFetched"],
            "highlightsFetched": item_log["highlightsFetched"],
        })

        candidate_meta = candidate.setdefault("metadata", {})
        candidate_meta["resultEnrichment"] = enrichment

        item_log["flags"] = enrichment.get("flags", [])
        item_log["decisiveMoment"] = enrichment.get("decisiveMoment")
        item_log["headlineSeed"] = enrichment.get("headlineSeed")
        item_log["priorityFloor"] = enrichment.get("priorityFloor")

        if enrichment.get("decisiveMoment"):
            summary["enriched"] += 1
        else:
            summary["noDecisiveMoment"] += 1
        summary["items"].append(item_log)

    return candidates



def _score_story_context(candidate: dict[str, Any], title: str, summary: str) -> dict[str, Any]:
    """Score grounded recap context for user-facing ticker value.

    A3.9 deliberately treats closeness and story value as separate signals. A
    generic 1-0 result is not automatically more important than a multi-homer,
    multi-goal, milestone, or other clearly stated performance.
    """
    title = clean_text(title)
    summary = clean_text(summary)
    combined = f"{title} {summary}".lower()
    signals: list[str] = []
    floor = 0

    signal_rules = [
        (r"\b(?:walk[- ]?off|game[- ]winning|game winner|last[- ]second|time expired|buzzer[- ]beater)\b", "DECISIVE_CONTEXT", 78),
        (r"\b(?:hat trick|three goals|3 goals)\b", "HAT_TRICK", 76),
        (r"\b(?:two|2|three|3|four|4)\s+(?:home runs|homers)\b|\bhomers twice\b|\bhit two home runs\b", "MULTI_HOMER", 74),
        (r"\b(?:brace|scored twice|two goals|2 goals)\b", "MULTI_GOAL", 72),
        (r"\b(?:career-high|season-high|career high|season high)\b", "HIGH_WATER_MARK", 72),
        (r"\b(?:drove in|drives in)\s+(?:four|4|five|5|six|6)\s+runs?\b|\b(?:four|4|five|5|six|6)\s+rbi\b", "RUN_PRODUCTION", 72),
        (r"\b(?:complete game|no-hitter|perfect game)\b", "PITCHING_FEAT", 78),
        (r"\b(?:(?:\d+\s+)?(?:scoreless|strong|sharp)\s+innings|struck out \d+|\d+ strikeouts)\b", "PITCHING_PERFORMANCE", 69),
        (r"\b(?:first (?:league|conference|season) win|first win of the season|clinches?|clinch(?:ed|ing)?|record|milestone)\b", "MILESTONE_CONTEXT", 71),
        (r"\b(?:(?:two|2)-run|(?:three|3)-run|grand slam)\s+(?:homer|home run)\b", "IMPACT_HOMER", 69),
        (r"\b(?:stole|steals)\s+(?:his|her|their)?\s*\d+(?:st|nd|rd|th)\b", "MILESTONE_STAT", 68),
    ]
    for pattern, label, priority_floor in signal_rules:
        if re.search(pattern, combined, re.I):
            signals.append(label)
            floor = max(floor, priority_floor)

    # A genuinely different recap headline is itself useful context even when it
    # does not match one of the high-signal lexical rules above.
    generic_title = clean_text(candidate.get("title"))
    similarity = title_similarity(title, generic_title) if title and generic_title else 1.0
    if title and len(title) >= 20 and similarity < 0.68:
        signals.append("SPECIFIC_RECAP_CONTEXT")
        floor = max(floor, 67)

    # Avoid promoting copy that is just another restatement of the final score.
    if not signals:
        return {}

    score = floor
    if len(signals) >= 2:
        score = min(86, score + 2)

    return {
        "signals": sorted(set(signals)),
        "storyScore": score,
        "priorityFloor": floor,
        "headlineSeed": _clean_story_headline_seed(title),
        "summarySeed": summary or title,
    }


def _clean_story_headline_seed(value: Any) -> str:
    seed = clean_text(value)
    seed = re.sub(r"^(?:premier league|mlb|nfl|nba|nhl|college football|ncaaf)\s+recap:\s*", "", seed, flags=re.I)
    seed = re.sub(r"^recap:\s*", "", seed, flags=re.I)
    return seed


def build_result_story_promotion(candidate: dict[str, Any]) -> dict[str, Any] | None:
    if clean_text(candidate.get("typeHint")).upper() not in {"RESULT", "UPSET"}:
        return None

    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    enrichment = meta.get("resultEnrichment") if isinstance(meta.get("resultEnrichment"), dict) else {}
    decisive = clean_text(enrichment.get("decisiveMoment"))
    if decisive:
        return {
            "kind": "decisive-moment",
            "storyScore": max(90, int(enrichment.get("priorityFloor") or 0)),
            "priorityFloor": int(enrichment.get("priorityFloor") or 0),
            "signals": list(enrichment.get("flags") or []),
            "headlineSeed": clean_text(enrichment.get("headlineSeed")) or clean_text(candidate.get("title")),
            "summarySeed": clean_text(enrichment.get("summarySeed")) or decisive,
            "freshnessSeed": decisive,
            "sourceCandidateId": candidate.get("candidateId"),
        }

    fused = meta.get("fusedContext")
    if not isinstance(fused, list):
        return None

    best: dict[str, Any] | None = None
    for context in fused:
        if not isinstance(context, dict):
            continue
        title = clean_text(context.get("title"))
        summary = clean_text(context.get("summary"))
        scored = _score_story_context(candidate, title, summary)
        if not scored:
            continue
        scored.update({
            "kind": "fused-recap-context",
            "freshnessSeed": summary or title,
            "sourceCandidateId": context.get("candidateId"),
            "providers": list(context.get("providers") or []),
        })
        if best is None or int(scored.get("storyScore") or 0) > int(best.get("storyScore") or 0):
            best = scored
    return best


def promote_result_story_context(
    candidates: list[dict[str, Any]],
    run_log: dict[str, Any],
) -> list[dict[str, Any]]:
    log = run_log["pipeline"]["resultStoryPromotion"]
    for candidate in candidates:
        promotion = build_result_story_promotion(candidate)
        if not promotion:
            continue
        meta = candidate.setdefault("metadata", {})
        meta["storyPromotion"] = promotion
        log["promoted"] += 1
        log["items"].append({
            "candidateId": candidate.get("candidateId"),
            "league": candidate.get("leagueHint"),
            "kind": promotion.get("kind"),
            "signals": promotion.get("signals", []),
            "storyScore": promotion.get("storyScore"),
            "priorityFloor": promotion.get("priorityFloor"),
            "headlineSeed": promotion.get("headlineSeed"),
        })
    return candidates


def result_story_promotion_for_candidates(
    candidate_ids: list[str],
    by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    best = None
    for cid in candidate_ids:
        candidate = by_id.get(cid)
        if not candidate:
            continue
        meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        promotion = meta.get("storyPromotion")
        if not isinstance(promotion, dict):
            continue
        if best is None or int(promotion.get("storyScore") or 0) > int(best.get("storyScore") or 0):
            best = promotion
    return best


def _result_copy_is_generic(
    item: dict[str, Any],
    candidate_ids: list[str],
    by_id: dict[str, dict[str, Any]],
) -> bool:
    headline = clean_text(item.get("headline"))
    if not headline:
        return True
    for cid in candidate_ids:
        candidate = by_id.get(cid)
        if not candidate or not structured_match_pair(candidate):
            continue
        generic = clean_text(candidate.get("title"))
        if generic and title_similarity(headline, generic) >= 0.78:
            return True
    return False


def _raw_result_evidence_text(value: Any) -> bool:
    text = clean_text(value).lower()
    return (
        text.startswith("highlightly final:")
        or text.startswith("final:")
        or text == "highlightly final"
    )


def _natural_result_summary_for_candidates(
    candidate_ids: list[str],
    by_id: dict[str, dict[str, Any]],
) -> str:
    for cid in candidate_ids:
        candidate = by_id.get(cid)
        if not candidate:
            continue
        meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        home = clean_text(meta.get("homeTeam"))
        away = clean_text(meta.get("awayTeam"))
        try:
            home_score = int(meta.get("homeScore"))
            away_score = int(meta.get("awayScore"))
        except Exception:
            continue
        if not home or not away:
            continue
        if home_score == away_score:
            return f"{home} and {away} finished tied {home_score}-{away_score}."
        if home_score > away_score:
            return f"{home} beat {away} {home_score}-{away_score}."
        return f"{away} beat {home} {away_score}-{home_score}."
    return ""


def _make_promoted_result_item(
    candidate: dict[str, Any],
    promotion: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidate_id = candidate["candidateId"]
    item_type = "UPSET" if clean_text(candidate.get("typeHint")).upper() == "UPSET" else "RESULT"
    sources = union_sources([candidate_id], by_id)
    headline = clean_text(promotion.get("headlineSeed")) or clean_text(candidate.get("title"))
    text_value = clean_text(promotion.get("summarySeed")) or clean_text(candidate.get("summary"))
    freshness = clean_text(promotion.get("freshnessSeed")) or text_value or headline
    priority = max(65, int(promotion.get("priorityFloor") or 0))
    item = {
        "rank": 999,
        "candidateIds": [candidate_id],
        "type": item_type,
        "priority": min(95, priority),
        "headline": headline[:120],
        "text": text_value[:360],
        "entities": [],
        "occurredAt": candidate.get("occurredAt"),
        "timePrecision": candidate.get("timePrecision"),
        "ageHours": candidate.get("ageHours"),
        "freshnessBasis": freshness[:240],
        "status": "active",
        "sourceUrls": [s["url"] for s in sources],
        "sources": sources,
    }
    item["id"] = "a3-promoted-" + hashlib.sha1(
        (candidate_id + "|" + item["headline"]).encode("utf-8")
    ).hexdigest()[:16]
    return item


def ensure_promoted_result_coverage(
    final_items: list[dict[str, Any]],
    league: str,
    candidates: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    run_log: dict[str, Any],
    *,
    max_auto_add: int = 3,
    min_story_score: int = 72,
) -> list[dict[str, Any]]:
    """Backstop the cheap editor when it omits a clearly stronger result story.

    Only grounded storyPromotion candidates at/above the threshold are eligible,
    and at most three are injected per league before normal final curation/caps.
    """
    represented = {
        cid
        for item in final_items
        for cid in item.get("candidateIds", [])
    }
    eligible = []
    for candidate in candidates:
        if clean_text(candidate.get("leagueHint")).upper() != league:
            continue
        if clean_text(candidate.get("typeHint")).upper() not in {"RESULT", "UPSET"}:
            continue
        promotion = result_story_promotion_for_candidates([candidate["candidateId"]], by_id)
        if not isinstance(promotion, dict):
            continue
        score = int(promotion.get("storyScore") or 0)
        if score < min_story_score or candidate["candidateId"] in represented:
            continue
        eligible.append((score, int(promotion.get("priorityFloor") or 0), candidate, promotion))

    eligible.sort(key=lambda row: (-row[0], -row[1], float(row[2].get("ageHours") or 99.0)))
    additions = 0
    for score, floor, candidate, promotion in eligible:
        if additions >= max_auto_add:
            break
        item = _make_promoted_result_item(candidate, promotion, by_id)
        final_items.append(item)
        represented.add(candidate["candidateId"])
        additions += 1
        run_log["pipeline"]["resultStoryPromotion"]["autoAdded"].append({
            "league": league,
            "candidateId": candidate["candidateId"],
            "storyScore": score,
            "priorityFloor": floor,
            "headline": item["headline"],
            "reason": "strong grounded result story omitted by editor",
        })
    return final_items


def result_enrichment_for_candidates(
    candidate_ids: list[str],
    by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    best = None
    for cid in candidate_ids:
        candidate = by_id.get(cid)
        if not candidate:
            continue
        meta = candidate.get("metadata")
        if not isinstance(meta, dict):
            continue
        enrichment = meta.get("resultEnrichment")
        if not isinstance(enrichment, dict):
            continue
        if best is None:
            best = enrichment
            continue
        if int(enrichment.get("priorityFloor") or 0) > int(best.get("priorityFloor") or 0):
            best = enrichment
    return best


def apply_result_enrichment_priority(
    priority: int,
    candidate_ids: list[str],
    by_id: dict[str, dict[str, Any]],
    item_type: str,
    context: str,
    run_log: dict[str, Any],
) -> int:
    if item_type not in {"RESULT", "UPSET"}:
        return priority
    enrichment = result_enrichment_for_candidates(candidate_ids, by_id)
    promotion = result_story_promotion_for_candidates(candidate_ids, by_id)
    floors = []
    reasons = []
    if isinstance(enrichment, dict) and isinstance(enrichment.get("priorityFloor"), int):
        floors.append(int(enrichment["priorityFloor"]))
        reasons.extend(enrichment.get("flags", []))
    if isinstance(promotion, dict) and isinstance(promotion.get("priorityFloor"), int):
        floors.append(int(promotion["priorityFloor"]))
        reasons.extend(promotion.get("signals", []))
    if not floors:
        return priority
    floor = max(floors)
    if floor <= priority:
        return priority
    repaired = min(95, floor)
    run_log["pipeline"]["editorRepairs"].append({
        "context": context,
        "field": "priority",
        "original": priority,
        "repaired": repaired,
        "reason": "grounded result-story priority floor: " + ", ".join(sorted(set(reasons))),
    })
    return repaired


def repair_result_story_punch(
    item: dict[str, Any],
    candidate_ids: list[str],
    by_id: dict[str, dict[str, Any]],
    context: str,
    run_log: dict[str, Any],
) -> None:
    if item.get("type") not in {"RESULT", "UPSET"}:
        return

    enrichment = result_enrichment_for_candidates(candidate_ids, by_id)
    promotion = result_story_promotion_for_candidates(candidate_ids, by_id)

    # Decisive moments remain the strongest mandatory story signal.
    if isinstance(enrichment, dict) and enrichment.get("decisiveMoment"):
        flags = set(enrichment.get("flags", []))
        headline = clean_text(item.get("headline")).lower()
        required_signal = True
        if "WALK_OFF" in flags:
            required_signal = "walk" in headline
        elif "BLOCKED_KICK" in flags:
            required_signal = "block" in headline and (
                "field goal" in headline or "kick" in headline
            )
        elif "BUZZER_BEATER" in flags:
            required_signal = "buzzer" in headline
        elif "OVERTIME" in flags:
            required_signal = "overtime" in headline or re.search(r"\\bot\\b", headline) is not None
        elif "LAST_SECOND" in flags and "GAME_WINNER" in flags:
            required_signal = (
                "last-second" in headline or "last second" in headline
                or "late" in headline or "winner" in headline
            )
        if not required_signal:
            seed = clean_text(enrichment.get("headlineSeed"))
            summary_seed = clean_text(enrichment.get("summarySeed"))
            decisive = clean_text(enrichment.get("decisiveMoment"))
            if seed:
                original = item["headline"]
                item["headline"] = seed[:120]
                item["text"] = (summary_seed or decisive or item["text"])[:360]
                if decisive:
                    item["freshnessBasis"] = decisive[:240]
                run_log["pipeline"]["editorRepairs"].append({
                    "context": context,
                    "field": "headline/text",
                    "original": original,
                    "repaired": item["headline"],
                    "reason": "editor omitted grounded decisive moment: " + ", ".join(sorted(flags)),
                })

    # A3.9: when no decisive play exists but ESPN/another fused recap gives a
    # clearly stronger grounded game story, do not publish the bare score line.
    promotion = result_story_promotion_for_candidates(candidate_ids, by_id)
    raw_text = _raw_result_evidence_text(item.get("text"))

    if isinstance(promotion, dict):
        generic_headline = _result_copy_is_generic(item, candidate_ids, by_id)
        story_score = int(promotion.get("storyScore") or 0)
        seed = clean_text(promotion.get("headlineSeed"))
        summary_seed = clean_text(promotion.get("summarySeed"))
        freshness_seed = clean_text(promotion.get("freshnessSeed"))

        if generic_headline and story_score >= 67 and seed:
            original = item["headline"]
            item["headline"] = seed[:120]
            run_log["pipeline"]["editorRepairs"].append({
                "context": context,
                "field": "headline",
                "original": original,
                "repaired": item["headline"],
                "reason": "promoted stronger grounded result story: " + ", ".join(promotion.get("signals", [])),
            })

        if raw_text and summary_seed:
            original = item["text"]
            item["text"] = summary_seed[:360]
            raw_text = False
            run_log["pipeline"]["editorRepairs"].append({
                "context": context,
                "field": "text",
                "original": original,
                "repaired": item["text"],
                "reason": "replaced raw result evidence with grounded fused story context",
            })

        # Only replace a vague/generic freshness line. Preserve a richer model-written
        # freshness basis when it already contains the promoted fact.
        if freshness_seed:
            current = clean_text(item.get("freshnessBasis"))
            if not current or current.lower().startswith(("game completed", "the match ended", "the game ended")):
                item["freshnessBasis"] = freshness_seed[:240]

    # Even without richer context, never publish transport/evidence boilerplate.
    if raw_text:
        natural = _natural_result_summary_for_candidates(candidate_ids, by_id)
        if natural:
            original = item["text"]
            item["text"] = natural[:360]
            run_log["pipeline"]["editorRepairs"].append({
                "context": context,
                "field": "text",
                "original": original,
                "repaired": item["text"],
                "reason": "raw Highlightly evidence is not user-facing ticker prose",
            })


def candidate_sort_key(c: dict[str, Any]):
    type_weight = {
        "BREAKING": 0, "INJURY": 1, "TRADE": 1, "SIGNING": 1, "CONTRACT": 1,
        "PLAYOFF": 1, "STANDINGS": 1, "RECORD": 1, "MILESTONE": 2,
        "DEPTH_CHART": 2, "SUSPENSION": 2, "DISCIPLINE": 2, "LEGAL": 2,
        "COACHING": 2, "RESULT": 5, "OTHER": 6,
    }.get(c.get("typeHint"), 4)
    age = float(c["ageHours"]) if c.get("ageHours") is not None else 23.9
    meta = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
    promotion = meta.get("storyPromotion") if isinstance(meta.get("storyPromotion"), dict) else {}
    story_score = int(promotion.get("storyScore") or 0)
    return (type_weight, -story_score, -int(c.get("quality", 0)), age)


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
        "prompt_cache_key": "sports-big-board-a3-editor-v6",
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


def _result_item_candidates(
    item: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        by_id[cid]
        for cid in item.get("candidateIds", [])
        if cid in by_id
    ]


def _result_item_is_draw(
    item: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> bool:
    for candidate in _result_item_candidates(item, by_id):
        meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        if "homeScore" not in meta or "awayScore" not in meta:
            continue
        try:
            if int(meta.get("homeScore")) == int(meta.get("awayScore")):
                return True
        except Exception:
            pass
    return False


def _result_item_has_verified_ncaaf_identity(
    item: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> bool:
    """Require a structured FBS identity for ordinary NCAAF results.

    Standalone ESPN recaps can still represent a major result when a strong
    promotion exists, but a routine recap cannot reintroduce the FCS games that
    the Highlightly identity gate intentionally removed.
    """
    for candidate in _result_item_candidates(item, by_id):
        meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        if not structured_match_pair(candidate):
            continue
        home_fbs = clean_text(meta.get("homeFbs"))
        away_fbs = clean_text(meta.get("awayFbs"))
        if home_fbs or away_fbs:
            return True
    return False


def _result_item_relevance(
    item: dict[str, Any],
    league: str,
    by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidate_ids = [cid for cid in item.get("candidateIds", []) if cid in by_id]
    reasons: list[str] = []
    strong = False

    if clean_text(item.get("type")).upper() == "UPSET":
        strong = True
        reasons.append("UPSET")

    enrichment = result_enrichment_for_candidates(candidate_ids, by_id)
    if isinstance(enrichment, dict):
        if clean_text(enrichment.get("decisiveMoment")):
            strong = True
            reasons.append("DECISIVE_MOMENT")
        flags = set(enrichment.get("flags") or [])
        decisive_flags = {
            "WALK_OFF", "GAME_WINNER", "LAST_SECOND", "BLOCKED_KICK",
            "BUZZER_BEATER", "OVERTIME", "LATE_GOAL", "UPSET",
        }
        matched = sorted(flags & decisive_flags)
        if matched:
            strong = True
            reasons.extend(matched)

    promotion = result_story_promotion_for_candidates(candidate_ids, by_id)
    if isinstance(promotion, dict):
        story_score = int(promotion.get("storyScore") or 0)
        if story_score >= 67:
            strong = True
            reasons.append(f"STORY_SCORE_{story_score}")
            reasons.extend(promotion.get("signals") or [])

    ranked = False
    for candidate in _result_item_candidates(item, by_id):
        meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        if meta.get("rankedTeamInvolved"):
            ranked = True
            break
    if ranked:
        strong = True
        reasons.append("RANKED_TEAM_INVOLVED")

    is_draw = _result_item_is_draw(item, by_id)
    verified_ncaaf = (
        _result_item_has_verified_ncaaf_identity(item, by_id)
        if league == "NCAAF" else True
    )

    absolute_drop = False
    drop_reason = None
    if is_draw and not strong:
        absolute_drop = True
        drop_reason = "generic draw/tie without a grounded story hook"
    elif league == "NCAAF" and not verified_ncaaf and not strong:
        absolute_drop = True
        drop_reason = "ordinary NCAAF result lacks verified FBS identity"

    return {
        "strong": strong,
        "reasons": sorted(set(reasons)),
        "isDraw": is_draw,
        "verifiedNcaafIdentity": verified_ncaaf,
        "absoluteDrop": absolute_drop,
        "dropReason": drop_reason,
    }


def apply_final_result_relevance_gate(
    items: list[dict[str, Any]],
    league: str,
    by_id: dict[str, dict[str, Any]],
    run_log: dict[str, Any],
) -> list[dict[str, Any]]:
    """Prefer meaningful result stories and use ordinary scores only as filler.

    A3.9 quality rule: a result needs a reason to exist. Decisive finishes,
    standout recap context, upsets, and ranked consequences are strong. Generic
    draws are omitted. Ordinary wins may fill at most two slots and only when
    the league does not already have roughly three stronger current stories.
    """
    gate = run_log["pipeline"]["relevanceGate"]
    non_results = [item for item in items if item.get("type") not in {"RESULT", "UPSET"}]
    results = [item for item in items if item.get("type") in {"RESULT", "UPSET"}]

    strong_results: list[dict[str, Any]] = []
    generic_results: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for item in results:
        relevance = _result_item_relevance(item, league, by_id)
        if relevance["absoluteDrop"]:
            gate["dropped"].append({
                "league": league,
                "headline": item.get("headline"),
                "candidateIds": item.get("candidateIds", []),
                "reason": relevance["dropReason"],
            })
            run_log["pipeline"]["finalDrops"].append({
                "context": league,
                "headline": item.get("headline"),
                "reason": "A3.9 relevance gate: " + clean_text(relevance["dropReason"]),
            })
            continue
        if relevance["strong"]:
            strong_results.append(item)
            gate["keptStrong"].append({
                "league": league,
                "headline": item.get("headline"),
                "candidateIds": item.get("candidateIds", []),
                "reasons": relevance["reasons"],
            })
        else:
            generic_results.append((item, relevance))

    meaningful_count = len(non_results) + len(strong_results)
    filler_slots = min(
        MAX_GENERIC_RESULT_FILLERS,
        max(0, RESULT_RELEVANCE_TARGET - meaningful_count),
    )
    generic_results.sort(
        key=lambda row: (
            -int(row[0].get("priority") or 0),
            float(row[0].get("ageHours") or 99.0),
        )
    )

    kept_generic = []
    for item, relevance in generic_results:
        # Unverified NCAAF routine recaps are never used as fillers.
        if league == "NCAAF" and not relevance["verifiedNcaafIdentity"]:
            gate["dropped"].append({
                "league": league,
                "headline": item.get("headline"),
                "candidateIds": item.get("candidateIds", []),
                "reason": "routine NCAAF filler lacks structured FBS identity",
            })
            run_log["pipeline"]["finalDrops"].append({
                "context": league,
                "headline": item.get("headline"),
                "reason": "A3.9 relevance gate: routine NCAAF filler lacks structured FBS identity",
            })
            continue
        if len(kept_generic) < filler_slots:
            kept_generic.append(item)
            gate["keptFillers"].append({
                "league": league,
                "headline": item.get("headline"),
                "candidateIds": item.get("candidateIds", []),
                "reason": (
                    f"ordinary result used as filler; meaningfulStories={meaningful_count}; "
                    f"fillerSlots={filler_slots}"
                ),
            })
        else:
            gate["dropped"].append({
                "league": league,
                "headline": item.get("headline"),
                "candidateIds": item.get("candidateIds", []),
                "reason": (
                    f"ordinary result suppressed; meaningfulStories={meaningful_count}; "
                    f"fillerSlots={filler_slots}"
                ),
            })
            run_log["pipeline"]["finalDrops"].append({
                "context": league,
                "headline": item.get("headline"),
                "reason": "A3.9 relevance gate: ordinary result suppressed by stronger stories",
            })

    return non_results + strong_results + kept_generic


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


F1_EVENT_LOCATIONS = {
    "australia": "Australian Grand Prix",
    "australian": "Australian Grand Prix",
    "china": "Chinese Grand Prix",
    "chinese": "Chinese Grand Prix",
    "japan": "Japanese Grand Prix",
    "japanese": "Japanese Grand Prix",
    "bahrain": "Bahrain Grand Prix",
    "saudi arabia": "Saudi Arabian Grand Prix",
    "saudi": "Saudi Arabian Grand Prix",
    "miami": "Miami Grand Prix",
    "canada": "Canadian Grand Prix",
    "canadian": "Canadian Grand Prix",
    "monaco": "Monaco Grand Prix",
    "spain": "Spanish Grand Prix",
    "spanish": "Spanish Grand Prix",
    "austria": "Austrian Grand Prix",
    "austrian": "Austrian Grand Prix",
    "britain": "British Grand Prix",
    "british": "British Grand Prix",
    "belgium": "Belgian Grand Prix",
    "belgian": "Belgian Grand Prix",
    "hungary": "Hungarian Grand Prix",
    "hungarian": "Hungarian Grand Prix",
    "netherlands": "Dutch Grand Prix",
    "dutch": "Dutch Grand Prix",
    "italy": "Italian Grand Prix",
    "italian": "Italian Grand Prix",
    "azerbaijan": "Azerbaijan Grand Prix",
    "singapore": "Singapore Grand Prix",
    "united states": "United States Grand Prix",
    "mexico": "Mexico City Grand Prix",
    "mexican": "Mexico City Grand Prix",
    "brazil": "São Paulo Grand Prix",
    "sao paulo": "São Paulo Grand Prix",
    "las vegas": "Las Vegas Grand Prix",
    "qatar": "Qatar Grand Prix",
    "abu dhabi": "Abu Dhabi Grand Prix",
}

TENNIS_EVENT_PATTERNS = [
    (r"\b(?:u\.?s\.?|us)\s+open\b", "US Open"),
    (r"\bwimbledon\b", "Wimbledon"),
    (r"\bfrench\s+open\b|\broland\s+garros\b", "French Open"),
    (r"\baustralian\s+open\b", "Australian Open"),
]

GOLF_EVENT_PATTERNS = [
    (r"\bmasters(?:\s+tournament)?\b", "Masters Tournament"),
    (r"\bu\.?s\.?\s+open\b", "U.S. Open"),
    (r"\bthe\s+open(?:\s+championship)?\b|\bbritish\s+open\b", "The Open Championship"),
    (r"\bpga\s+championship\b", "PGA Championship"),
    (r"\bryder\s+cup\b", "Ryder Cup"),
    (r"\btour\s+championship\b", "Tour Championship"),
]


def special_candidate_text(
    candidate_ids: list[str],
    by_id: dict[str, dict[str, Any]],
) -> str:
    return " ".join(
        candidate_raw_text(by_id[cid])
        for cid in candidate_ids
        if cid in by_id
    )


def infer_special_event_name(
    candidate_ids: list[str],
    by_id: dict[str, dict[str, Any]],
    sport: str,
) -> str | None:
    text = special_candidate_text(candidate_ids, by_id)
    low = text.lower()
    sport_low = clean_text(sport).lower()

    if "formula" in sport_low or "f1" in sport_low or any(
        clean_text(by_id[cid].get("sportHint")).lower() == "formula 1"
        for cid in candidate_ids if cid in by_id
    ):
        # Prefer an explicit "<location> Grand Prix/GP" mention.
        for location, canonical in sorted(F1_EVENT_LOCATIONS.items(), key=lambda kv: -len(kv[0])):
            loc = re.escape(location)
            if re.search(rf"\b{loc}\b(?:\s+(?:grand\s+prix|gp))?", low):
                # Avoid treating generic source text like "Italian" as enough
                # unless the candidate actually has F1/GP context.
                if (
                    "grand prix" in low or re.search(r"\bgp\b", low)
                    or "formula 1" in low or "/f1/" in low
                ):
                    return canonical + " (Formula 1)"

    patterns = TENNIS_EVENT_PATTERNS if "tennis" in sport_low else (
        GOLF_EVENT_PATTERNS if "golf" in sport_low else []
    )
    for pattern, canonical in patterns:
        if re.search(pattern, low, flags=re.I):
            return canonical

    if "mma" in sport_low or "ufc" in sport_low:
        match = re.search(r"\bufc\s+(\d{2,4})\b", text, flags=re.I)
        if match:
            return f"UFC {match.group(1)}"

    return None


def special_event_family(name: str) -> str:
    low = clean_text(name).lower()
    low = re.sub(r"\([^)]*\)", " ", low)
    low = re.sub(r"\b(round of \d+|quarterfinals?|semifinals?|finals?|day \d+)\b", " ", low)
    low = re.sub(r"\s+", " ", low).strip()

    for location, canonical in F1_EVENT_LOCATIONS.items():
        if location in low or canonical.lower() in low:
            return canonical.lower()
    for patterns in (TENNIS_EVENT_PATTERNS, GOLF_EVENT_PATTERNS):
        for pattern, canonical in patterns:
            if re.search(pattern, low, flags=re.I):
                return canonical.lower()
    match = re.search(r"\bufc\s+(\d{2,4})\b", low)
    if match:
        return f"ufc {match.group(1)}"
    return low


def validate_special_event_target(
    model_event_name: str,
    sport: str,
    candidate_ids: list[str],
    by_id: dict[str, dict[str, Any]],
    run_log: dict[str, Any],
) -> str:
    inferred = infer_special_event_name(candidate_ids, by_id, sport)
    model_family = special_event_family(model_event_name)

    if not inferred:
        run_log["pipeline"]["specialEventValidation"]["unverified"].append({
            "modelEvent": model_event_name,
            "sport": sport,
            "candidateIds": candidate_ids,
            "reason": "candidate does not expose a specific recognized event name",
        })
        return model_event_name

    inferred_family = special_event_family(inferred)
    if model_family == inferred_family:
        run_log["pipeline"]["specialEventValidation"]["verified"].append({
            "modelEvent": model_event_name,
            "inferredEvent": inferred,
            "sport": sport,
            "candidateIds": candidate_ids,
        })
        return model_event_name

    run_log["pipeline"]["specialEventValidation"]["rehomed"].append({
        "from": model_event_name,
        "to": inferred,
        "sport": sport,
        "candidateIds": candidate_ids,
        "reason": "candidate explicitly grounds a different named event",
    })
    return inferred


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
                    "priority": apply_result_enrichment_priority(
                        normalize_editor_priority(
                            raw_item["priority"], item_type, f"{league} #{idx}", run_log
                        ),
                        candidate_ids, by_id, item_type, f"{league} #{idx}", run_log
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
                repair_result_story_punch(
                    item, candidate_ids, by_id, f"{league} #{idx}", run_log
                )
                validate_copy_consistency(item, f"{league} #{idx}")
                final_items.append(item)

            except Exception as exc:
                run_log["pipeline"]["finalDrops"].append({
                    "context": league,
                    "index": idx,
                    "headline": clean_text(raw_item.get("headline")),
                    "reason": clean_text(exc),
                })

        final_items = ensure_promoted_result_coverage(
            final_items, league, candidates, by_id, run_log
        )
        final_items = apply_final_result_relevance_gate(
            final_items, league, by_id, run_log
        )
        final_items = curate_final_items(final_items, league, run_log)
        leagues.append({
            "league": league,
            "seasonState": season_state,
            "items": final_items,
        })

    # Validate Special Event membership item-by-item. A model group can be split
    # when its candidates explicitly name different events.
    special_buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for event_index, event in enumerate(model_output.get("specialEvents", []), 1):
        model_name = clean_text(event.get("name"))
        sport = clean_text(event.get("sport"))
        if not model_name or not sport:
            continue

        for idx, raw_item in enumerate(event.get("items", []), 1):
            try:
                candidate_ids = [clean_text(cid) for cid in raw_item["candidateIds"]]
                if not candidate_ids or any(cid not in by_id for cid in candidate_ids):
                    raise TickerError("unknown candidateId")

                target_name = validate_special_event_target(
                    model_name, sport, candidate_ids, by_id, run_log
                )

                occurred_at, precision, age = best_occurrence(candidate_ids, by_id)
                sources = union_sources(candidate_ids, by_id)
                item_type = clean_text(raw_item["type"]).upper()
                if item_type not in ALLOWED_TYPES:
                    raise TickerError("invalid type")

                item = {
                    "rank": idx,
                    "candidateIds": candidate_ids,
                    "type": item_type,
                    "priority": apply_result_enrichment_priority(
                        normalize_editor_priority(
                            raw_item["priority"], item_type, f"{target_name} #{idx}", run_log
                        ),
                        candidate_ids, by_id, item_type, f"{target_name} #{idx}", run_log
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
                        f"{target_name} #{idx}", run_log
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
                repair_result_story_punch(
                    item, candidate_ids, by_id, f"{target_name} #{idx}", run_log
                )
                validate_copy_consistency(item, f"{target_name} #{idx}")

                bucket_key = (special_event_family(target_name), sport.lower())
                bucket = special_buckets.setdefault(
                    bucket_key,
                    {"name": target_name, "sport": sport, "items": []},
                )
                bucket["items"].append(item)

            except Exception as exc:
                run_log["pipeline"]["finalDrops"].append({
                    "context": model_name,
                    "index": idx,
                    "headline": clean_text(raw_item.get("headline")),
                    "reason": clean_text(exc),
                })

    special_events = []
    for bucket in special_buckets.values():
        items = curate_final_items(bucket["items"], bucket["name"], run_log)
        if items:
            special_events.append({
                "name": bucket["name"],
                "sport": bucket["sport"],
                "items": items,
            })
    special_events.sort(
        key=lambda event: max(
            (int(item.get("priority") or 0) for item in event["items"]),
            default=0,
        ),
        reverse=True,
    )

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
        handle.flush()
        os.fsync(handle.fileno())
        temp_name = handle.name
    os.replace(temp_name, path)


def write_run_log(path: Path, run_log: dict[str, Any]):
    run_log["finishedAt"] = iso_z(utc_now())
    atomic_write(path, json.dumps(run_log, indent=2, ensure_ascii=False) + "\n")


def initial_run_log(generated_at: datetime, cutoff: datetime, model: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "pipelineVersion": "A3.10-final-relevance-event-fusion",
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
            "maxDecisiveEnrichments": MAX_DECISIVE_ENRICHMENTS,
            "decisiveEnrichmentStrategy": (
                "selective Highlightly match detail + matchId-filtered highlights + "
                "bounded ESPN football scoreboard/summary fallback; no OpenAI web search"
            ),
            "resultStoryPromotion": (
                "decisive moment first; otherwise strongest grounded fused recap context; "
                "raw Highlightly-final boilerplate is evidence-only"
            ),
            "resultRelevanceGate": (
                "strong story first; generic draws suppressed; max two ordinary result fillers "
                "only when fewer than three stronger league stories exist"
            ),
            "fbsIdentityPolicy": (
                "authoritative 138-team 2026 FBS roster; ESPN scoreboard validates IDs/ranks "
                "but cannot expand membership"
            ),
            "sameGameNewsFusion": (
                "structured result + both-team article + result evidence; "
                "RECORD/MILESTONE/PLAYOFF/etc. can fuse into the same game candidate"
            ),
            "specialEventValidation": (
                "candidate-grounded event membership with deterministic re-homing of mismatches"
            ),
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
            "decisiveMomentEnrichment": {
                "selectedCandidateIds": [],
                "eligibleCount": 0,
                "attempted": 0,
                "enriched": 0,
                "noDecisiveMoment": 0,
                "skipped": [],
                "failures": [],
                "items": [],
                "skipReason": None,
            },
            "resultStoryPromotion": {
                "promoted": 0,
                "items": [],
                "autoAdded": [],
            },
            "relevanceGate": {
                "keptStrong": [],
                "keptFillers": [],
                "dropped": [],
            },
            "specialEventValidation": {
                "verified": [],
                "rehomed": [],
                "unverified": [],
            },
            "gameEventFusion": {
                "merged": [],
            },
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
            f"A3.9 direct-source refresh: {iso_z(cutoff)} to {iso_z(generated_at)}; "
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

        print("Enriching decisive moments for close/important results...")
        deduped = enrich_decisive_moments(
            deduped, run_log, highlightly_key
        )

        print("Promoting strongest grounded result stories...")
        deduped = promote_result_story_context(deduped, run_log)

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
            and s.get("kind") == "matches"
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
            "schemaVersion": 11,
            "pipelineVersion": "A3.10-final-relevance-event-fusion",
            "generatedAt": iso_z(generated_at),
            "freshnessHours": FRESHNESS_HOURS,
            "discoveryMode": "Highlightly + decisive parsing + result-story promotion + final relevance gate + game-event fusion + validated special events + hardened FBS identity + bounded ESPN football summary fallback + ESPN JSON news + ESPN FBS scoreboard context + official league pages; no OpenAI web search",
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

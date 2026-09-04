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
            "type": "array", "minItems": 7, "maxItems": 7,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["league", "seasonState", "items"],
                "properties": {
                    "league": {"type": "string", "enum": BASE_LEAGUES},
                    "seasonState": {
                        "type": "string",
                        "enum": ["active", "offseason", "preseason", "postseason"],
                    },
                    "items": {
                        "type": "array", "minItems": 0, "maxItems": 10,
                        "items": {"$ref": "#/$defs/item"},
                    },
                },
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
    "$defs": {"item": MODEL_ITEM_SCHEMA},
}

EDITOR_INSTRUCTIONS = """You are the final editor for Sports Big Board Sports Ticker.

You are NOT a researcher. You have NO browsing task. Use ONLY the candidate packet
provided by Python. Never add a fact that is not supported by one or more cited
candidateIds.

Goal: create a concise rolling "what happened in the last 24 hours?" ticker.

Selection priorities:
1. BREAKING / major league news
2. playoff and standings consequences
3. major injuries / returns
4. trades / signings / contracts
5. records / milestones / record chases
6. rankings / awards / streaks / slumps
7. discipline / legal / coaching / meaningful roster/depth-chart changes
8. major upsets
9. ordinary results
10. weak previews only when a genuinely new development makes them newsworthy

Editorial mix rules:
- Maximum 5 ordinary RESULT items per base league.
- Maximum 2 combined NEXT/SCHEDULE items per base league.
- Do not pad an offseason league.
- A major UPSET is not an ordinary RESULT.
- Special Events should cover important active events outside the seven base leagues.

Grounding:
- Every final item must reference candidateIds from the supplied packet.
- Do not invent URLs, scores, dates, injuries, rankings, records, quotes, or transactions.
- If multiple candidates describe the same event, merge them into one item and cite all
  useful candidateIds.
- If a candidate is ambiguous, omit it rather than guessing.

Consistency:
- Do not say shutout/shut out/blanked if the opponent scored.
- Do not call something a one-point win unless the score margin is one.
- Do not call a routine result an upset without evidence in the candidate packet.

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
    text = (title + " " + summary).lower()
    checks = [
        ("INJURY", ["injury", "injured", "out for", "placed on injured", "concussion"]),
        ("RETURN", ["returns to practice", "activated from", "returns from injury"]),
        ("TRADE", [" traded ", "trade for", "acquire", "acquired"]),
        ("SIGNING", ["signs ", "signed ", "agrees to a deal", "one-year deal"]),
        ("CONTRACT", ["extension", "contract"]),
        ("SUSPENSION", ["suspended", "suspension"]),
        ("DISCIPLINE", ["fine", "discipline", "exempt list"]),
        ("LEGAL", ["arrest", "lawsuit", "charged with", "court"]),
        ("COACHING", ["fired", "hired as coach", "head coach"]),
        ("DEPTH_CHART", ["starter", "backup quarterback", "depth chart", "qb1", "qb2"]),
        ("RANKING", ["ranked", "ranking", "top 25"]),
        ("RECORD", ["record", "all-time"]),
        ("MILESTONE", ["milestone", "1,000", "100th", "500th"]),
        ("STREAK", ["winning streak", "win streak", "losing streak"]),
        ("PLAYOFF", ["playoff", "postseason", "wild card"]),
        ("STANDINGS", ["standings", "division lead", "games back"]),
    ]
    for kind, words in checks:
        if any(word in text for word in words):
            return kind
    return "OTHER"


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

                source_url = article_web_url(article, source["url"])
                candidate = make_candidate(
                    source_id=source["id"],
                    provider="ESPN",
                    league_hint=source["leagueHint"],
                    sport_hint=source["sportHint"],
                    title=headline,
                    summary=clean_text(article.get("description")),
                    source_url=source_url,
                    occurrence=published,
                    generated_at=generated_at,
                    cutoff=cutoff,
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
        for key in ("total", "current", "score", "value", "displayValue"):
            if key in value:
                n = score_scalar(value[key])
                if n is not None:
                    return n
    return None


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
    home = score_scalar(score.get("homeTeam"))
    away = score_scalar(score.get("awayTeam"))
    if home is None:
        home = score_scalar(match.get("homeScore"))
    if away is None:
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


def classify_highlightly_league(
    match: dict[str, Any],
    league_matchers: dict[str, list[str]],
) -> str | None:
    league_text = match_league_text(match)
    if not league_text:
        return None

    for league, needles in league_matchers.items():
        if any(needle.lower() in league_text for needle in needles):
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

                    if home_score != away_score:
                        winner_score = home_score if winner == home else away_score
                        loser_score = away_score if winner == home else home_score
                        title = f"{winner} defeats {loser} {winner_score}-{loser_score}"
                    else:
                        title = f"{home} and {away} finish {home_score}-{away_score}"

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
                        type_hint="RESULT",
                        quality=100,
                        raw_ref=f"{entry['sourceId']}#{idx}",
                        metadata={
                            "matchId": match.get("id"),
                            "leagueText": match_league_text(match),
                            "homeTeam": home,
                            "awayTeam": away,
                            "homeScore": home_score,
                            "awayScore": away_score,
                            "scheduledAt": scheduled,
                            "state": match.get("state"),
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


def merge_candidate(dst: dict[str, Any], src: dict[str, Any]) -> None:
    seen = {(r["sourceId"], r["url"]) for r in dst["sourceRecords"]}
    for record in src["sourceRecords"]:
        key = (record["sourceId"], record["url"])
        if key not in seen:
            dst["sourceRecords"].append(record)
            seen.add(key)
    if src["quality"] > dst["quality"]:
        dst["quality"] = src["quality"]
        dst["summary"] = src["summary"] or dst["summary"]
        dst["title"] = src["title"] or dst["title"]
    # Prefer the newest independently reported development timestamp.
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
            existing_urls = {r["url"] for r in existing["sourceRecords"]}
            same_url = bool(candidate_urls & existing_urls)
            same_bucket = (
                candidate["leagueHint"] == existing["leagueHint"]
                or "SPECIAL" in {candidate["leagueHint"], existing["leagueHint"]}
                or "SOCCER" in {candidate["leagueHint"], existing["leagueHint"]}
            )
            if not same_bucket:
                continue
            sim = title_similarity(candidate["title"], existing["title"])
            if same_url or sim >= 0.72:
                merge_candidate(existing, candidate)
                merged_into = existing["candidateId"]
                actions.append({
                    "action": "merge",
                    "candidateId": candidate["candidateId"],
                    "into": existing["candidateId"],
                    "similarity": round(sim, 3),
                    "sameUrl": same_url,
                })
                break
        if merged_into is None:
            kept.append(candidate)
            actions.append({"action": "keep", "candidateId": candidate["candidateId"]})

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
        "prompt_cache_key": "sports-big-board-a3-editor-v2",
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
        "User-Agent": "sports-big-board-ticker-a3.2/1.0",
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


def normalize_model_output(
    model_output: dict[str, Any],
    candidates: list[dict[str, Any]],
    generated_at: datetime,
    run_log: dict[str, Any],
) -> dict[str, Any]:
    by_id = {c["candidateId"]: c for c in candidates}
    seen_leagues = set()
    leagues = []

    raw_leagues = model_output.get("leagues")
    if not isinstance(raw_leagues, list):
        raise TickerError("model output missing leagues array")

    for group in raw_leagues:
        league = clean_text(group.get("league")).upper()
        if league not in BASE_LEAGUES or league in seen_leagues:
            raise TickerError(f"invalid/duplicate league group {league!r}")
        seen_leagues.add(league)
        season_state = clean_text(group.get("seasonState")).lower()
        if season_state not in {"active", "offseason", "preseason", "postseason"}:
            raise TickerError(f"{league}: invalid seasonState")

        final_items = []
        for idx, raw_item in enumerate(group.get("items", []), 1):
            try:
                candidate_ids = [clean_text(cid) for cid in raw_item["candidateIds"]]
                if not candidate_ids or any(cid not in by_id for cid in candidate_ids):
                    raise TickerError("unknown candidateId")
                item_type = clean_text(raw_item["type"]).upper()
                if item_type not in ALLOWED_TYPES:
                    raise TickerError("invalid type")
                occurred_at, precision, age = best_occurrence(candidate_ids, by_id)
                sources = union_sources(candidate_ids, by_id)
                item = {
                    "rank": idx,
                    "candidateIds": candidate_ids,
                    "type": item_type,
                    "priority": int(raw_item["priority"]),
                    "headline": clean_text(raw_item["headline"]),
                    "text": clean_text(raw_item["text"]),
                    "entities": [clean_text(x) for x in raw_item.get("entities", []) if clean_text(x)],
                    "occurredAt": occurred_at,
                    "timePrecision": precision,
                    "ageHours": age,
                    "freshnessBasis": clean_text(raw_item["freshnessBasis"]),
                    "status": clean_text(raw_item["status"]).lower(),
                    "sourceUrls": [s["url"] for s in sources],
                    "sources": sources,
                }
                item["id"] = "a3-" + hashlib.sha1(
                    ("|".join(candidate_ids) + "|" + item["headline"]).encode("utf-8")
                ).hexdigest()[:16]
                if not 1 <= item["priority"] <= 100:
                    raise TickerError("priority out of range")
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

    missing = [league for league in BASE_LEAGUES if league not in seen_leagues]
    if missing:
        raise TickerError("model omitted league groups: " + ", ".join(missing))

    # Return in canonical league order regardless of model ordering.
    order = {league: i for i, league in enumerate(BASE_LEAGUES)}
    leagues.sort(key=lambda g: order[g["league"]])

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
                item = {
                    "rank": idx,
                    "candidateIds": candidate_ids,
                    "type": clean_text(raw_item["type"]).upper(),
                    "priority": int(raw_item["priority"]),
                    "headline": clean_text(raw_item["headline"]),
                    "text": clean_text(raw_item["text"]),
                    "entities": [clean_text(x) for x in raw_item.get("entities", []) if clean_text(x)],
                    "occurredAt": occurred_at,
                    "timePrecision": precision,
                    "ageHours": age,
                    "freshnessBasis": clean_text(raw_item["freshnessBasis"]),
                    "status": clean_text(raw_item["status"]).lower(),
                    "sourceUrls": [s["url"] for s in sources],
                    "sources": sources,
                }
                item["id"] = "a3-special-" + hashlib.sha1(
                    ("|".join(candidate_ids) + "|" + item["headline"]).encode("utf-8")
                ).hexdigest()[:16]
                if item["type"] not in ALLOWED_TYPES:
                    raise TickerError("invalid type")
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
        "pipelineVersion": "A3.2-editor-reliability",
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
            f"A3.2 direct-source refresh: {iso_z(cutoff)} to {iso_z(generated_at)}; "
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

        highlightly_key = os.environ.get("HIGHLIGHTLY_API_KEY", "").strip()
        for cfg in HIGHLIGHTLY_SPORTS:
            print(f"Fetching {cfg['id']}...")
            raw_candidates.extend(
                parse_highlightly_sport(
                    cfg, generated_at, cutoff, run_log, highlightly_key
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
            "schemaVersion": 4,
            "pipelineVersion": "A3.2-editor-reliability",
            "generatedAt": iso_z(generated_at),
            "freshnessHours": FRESHNESS_HOURS,
            "discoveryMode": "Highlightly + ESPN JSON news + official league pages; no OpenAI web search",
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

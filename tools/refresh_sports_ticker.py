#!/usr/bin/env python3
"""Sports Big Board Sports Ticker Phase A sidecar generator.

Isolation contract:
  - Does not import or modify Sports Big Board application code.
  - May write only data/sports-ticker.json and data/sports-ticker.txt.
  - A failed refresh leaves the previous good cache untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-luna"

BASE_LEAGUES = ["MLB", "NFL", "NBA", "NHL", "EPL", "MLS", "NCAAF"]

ALLOWED_TYPES = [
    "BREAKING",
    "RESULT",
    "UPSET",
    "TRADE",
    "SIGNING",
    "INJURY",
    "RETURN",
    "RECORD",
    "RECORD_CHASE",
    "MILESTONE",
    "STREAK",
    "SLUMP",
    "RANKING",
    "PLAYOFF",
    "STANDINGS",
    "AWARD",
    "STAT_LEADER",
    "CONTRACT",
    "SUSPENSION",
    "COACHING",
    "SCHEDULE",
    "NEXT",
    "OTHER",
]

ALLOWED_STATUS = ["active", "watch", "next"]

STORY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "type",
        "priority",
        "headline",
        "text",
        "entities",
        "eventDate",
        "status",
        "sourceUrls",
    ],
    "properties": {
        "type": {"type": "string", "enum": ALLOWED_TYPES},
        "priority": {"type": "integer", "minimum": 1, "maximum": 100},
        "headline": {"type": "string", "minLength": 4, "maxLength": 120},
        "text": {"type": "string", "minLength": 10, "maxLength": 360},
        "entities": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "minLength": 1, "maxLength": 80},
        },
        "eventDate": {"type": "string", "maxLength": 32},
        "status": {"type": "string", "enum": ALLOWED_STATUS},
        "sourceUrls": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {"type": "string", "minLength": 8, "maxLength": 500},
        },
    },
}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["leagues", "specialEvents"],
    "properties": {
        "leagues": {
            "type": "array",
            "minItems": 7,
            "maxItems": 7,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["league", "items"],
                "properties": {
                    "league": {"type": "string", "enum": BASE_LEAGUES},
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 10,
                        "items": {"$ref": "#/$defs/story"},
                    },
                },
            },
        },
        "specialEvents": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "sport", "items"],
                "properties": {
                    "name": {"type": "string", "minLength": 2, "maxLength": 100},
                    "sport": {"type": "string", "minLength": 2, "maxLength": 50},
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 10,
                        "items": {"$ref": "#/$defs/story"},
                    },
                },
            },
        },
    },
    "$defs": {"story": STORY_SCHEMA},
}

SYSTEM_PROMPT = """You are the editorial intelligence layer for Sports Big Board.

Your job is not to summarize the latest ten articles. Determine the most
important information a knowledgeable sports fan would want to know RIGHT NOW
and convert it into a high-information-density sports ticker.

Research current information on the live web before answering. Use reliable,
current sources. Prefer league/competition sites, major sports newsrooms,
official team/player announcements, and high-quality wire services. Do not
invent facts or URLs.

Always cover these seven Sports Big Board leagues exactly once:
MLB, NFL, NBA, NHL, EPL, MLS, NCAAF.

For each league target 10 high-value ticker items. If fewer than 10 genuinely
current, verified, useful items exist, return fewer rather than padding with
weak or stale filler.

Also include currently active major Special Events when they have meaningful
ticker value, such as a Grand Slam, World Cup, Olympics, major tournament, or
major championship outside the seven base leagues. Do not create a Special
Event merely to fill space.

Prioritize:
BREAKING, RESULT, UPSET, TRADE, SIGNING, INJURY, RETURN, RECORD,
RECORD_CHASE, MILESTONE, STREAK, SLUMP, RANKING, PLAYOFF, STANDINGS,
AWARD, STAT_LEADER, CONTRACT, SUSPENSION, COACHING, SCHEDULE, NEXT.

Editorial rules:
- Rank by consequence and fan usefulness, not article recency alone.
- Mix categories.
- Prefer concrete facts, standings movement, records, milestones and verified
  transactions over generic opinion or preview copy.
- Keep each item glanceable and self-contained.
- Do not duplicate the same development inside one league.
- An older major development may remain if it is still materially important.
- eventDate is YYYY-MM-DD when known, otherwise an empty string.
- status is active for a development that happened and still matters, watch for
  an unresolved situation, and next for a clearly upcoming item.
- sourceUrls must be real URLs used to verify that specific ticker item.
- priority is 1-100, with 100 reserved for exceptionally consequential news.
- Headlines should be short and non-clickbait.
- Text should usually be one or two compact sentences.
"""

USER_PROMPT = """Generate the current Sports Big Board Sports Ticker dataset now.
Use live web research and return only the structured dataset requested by the
schema. Favor factual accuracy and useful breadth over sensationalism."""


class TickerError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def call_openai(api_key: str, model: str, timeout: int = 240) -> dict[str, Any]:
    now = utc_now().isoformat().replace("+00:00", "Z")
    payload = {
        "model": model,
        "reasoning": {"effort": "low"},
        "tools": [{"type": "web_search"}],
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT + f"\nCurrent UTC time: {now}",
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "sports_big_board_sports_ticker",
                "strict": True,
                "schema": SCHEMA,
            }
        },
        "max_output_tokens": 30000,
    }

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "sports-big-board-ticker-sidecar/phase-a",
    }

    last_error: Exception | None = None

    for attempt in range(1, 4):
        request = urllib.request.Request(
            API_URL,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            last_error = TickerError(
                f"OpenAI HTTP {exc.code}: {details[:2000]}"
            )
            if (
                exc.code not in {408, 409, 429, 500, 502, 503, 504}
                or attempt == 3
            ):
                raise last_error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == 3:
                raise TickerError(f"OpenAI request failed: {exc}") from exc

        delay = attempt * 8
        print(
            f"OpenAI request attempt {attempt} failed; retrying in {delay}s",
            file=sys.stderr,
        )
        time.sleep(delay)

    raise TickerError(f"OpenAI request failed: {last_error}")


def extract_output_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    refusals: list[str] = []

    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue

        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue

            if (
                content.get("type") == "output_text"
                and isinstance(content.get("text"), str)
            ):
                chunks.append(content["text"])

            elif (
                content.get("type") == "refusal"
                and isinstance(content.get("refusal"), str)
            ):
                refusals.append(content["refusal"])

    if refusals:
        raise TickerError(
            "Model refused the ticker request: " + " | ".join(refusals)
        )

    text = "\n".join(chunks).strip()

    if not text:
        raise TickerError("OpenAI response contained no output text")

    return text


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def valid_url(value: str) -> bool:
    return value.startswith("https://") or value.startswith("http://")


def story_fingerprint(item: dict[str, Any]) -> str:
    core = "|".join(
        [
            item["type"].lower(),
            re.sub(
                r"[^a-z0-9]+",
                "-",
                item["headline"].lower(),
            ).strip("-"),
            item["eventDate"],
        ]
    )
    return hashlib.sha1(core.encode("utf-8")).hexdigest()[:16]


def normalize_story(
    story: dict[str, Any],
    rank: int,
    id_prefix: str,
) -> dict[str, Any]:
    item = {
        "rank": rank,
        "type": clean_text(story["type"]).upper(),
        "priority": int(story["priority"]),
        "headline": clean_text(story["headline"]),
        "text": clean_text(story["text"]),
        "entities": [
            clean_text(value)
            for value in story.get("entities", [])
            if clean_text(value)
        ],
        "eventDate": clean_text(story.get("eventDate", "")),
        "status": clean_text(story["status"]).lower(),
        "sourceUrls": [],
    }

    seen_urls: set[str] = set()

    for raw_url in story.get("sourceUrls", []):
        url = clean_text(raw_url)
        if url and url not in seen_urls:
            item["sourceUrls"].append(url)
            seen_urls.add(url)

    item["id"] = f"{id_prefix}-{story_fingerprint(item)}"
    return item


def validate_story(item: dict[str, Any], context: str) -> None:
    if item["type"] not in ALLOWED_TYPES:
        raise TickerError(f"{context}: unsupported type {item['type']!r}")

    if not 1 <= item["priority"] <= 100:
        raise TickerError(f"{context}: priority out of range")

    if not item["headline"] or len(item["headline"]) > 120:
        raise TickerError(f"{context}: invalid headline")

    if len(item["text"]) < 10 or len(item["text"]) > 360:
        raise TickerError(f"{context}: invalid text length")

    if item["status"] not in ALLOWED_STATUS:
        raise TickerError(f"{context}: invalid status {item['status']!r}")

    if item["eventDate"] and not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}",
        item["eventDate"],
    ):
        raise TickerError(
            f"{context}: eventDate must be YYYY-MM-DD or empty"
        )

    if not item["sourceUrls"]:
        raise TickerError(f"{context}: missing source URL")

    if any(not valid_url(url) for url in item["sourceUrls"]):
        raise TickerError(f"{context}: invalid source URL")


def normalize_and_validate(
    raw: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TickerError("Structured output is not a JSON object")

    raw_leagues = raw.get("leagues")

    if not isinstance(raw_leagues, list) or len(raw_leagues) != 7:
        raise TickerError("Expected exactly seven base league groups")

    by_league: dict[str, dict[str, Any]] = {}

    for group in raw_leagues:
        if not isinstance(group, dict):
            raise TickerError("Invalid league group")

        league = clean_text(group.get("league", "")).upper()

        if league in by_league:
            raise TickerError(f"Duplicate league group: {league}")

        if league not in BASE_LEAGUES:
            raise TickerError(f"Unexpected league group: {league}")

        stories = group.get("items")

        if not isinstance(stories, list) or not 1 <= len(stories) <= 10:
            raise TickerError(f"{league}: expected 1-10 ticker items")

        normalized: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for rank, story in enumerate(stories, start=1):
            if not isinstance(story, dict):
                raise TickerError(f"{league} #{rank}: invalid item")

            item = normalize_story(
                story,
                rank,
                league.lower(),
            )
            validate_story(item, f"{league} #{rank}")

            if item["id"] in seen_ids:
                raise TickerError(
                    f"{league}: duplicate ticker item {item['headline']!r}"
                )

            seen_ids.add(item["id"])
            normalized.append(item)

        by_league[league] = {
            "league": league,
            "items": normalized,
        }

    missing = [
        league
        for league in BASE_LEAGUES
        if league not in by_league
    ]

    if missing:
        raise TickerError(
            "Missing league groups: " + ", ".join(missing)
        )

    special_events: list[dict[str, Any]] = []
    raw_special = raw.get("specialEvents", [])

    if not isinstance(raw_special, list) or len(raw_special) > 6:
        raise TickerError(
            "specialEvents must contain at most six events"
        )

    seen_special_names: set[str] = set()

    for group_index, group in enumerate(raw_special, start=1):
        if not isinstance(group, dict):
            raise TickerError(
                f"Special Event #{group_index}: invalid group"
            )

        name = clean_text(group.get("name", ""))
        sport = clean_text(group.get("sport", ""))

        if len(name) < 2 or len(sport) < 2:
            raise TickerError(
                f"Special Event #{group_index}: invalid name/sport"
            )

        name_key = name.lower()

        if name_key in seen_special_names:
            raise TickerError(f"Duplicate Special Event: {name}")

        seen_special_names.add(name_key)

        stories = group.get("items")

        if not isinstance(stories, list) or not 1 <= len(stories) <= 10:
            raise TickerError(
                f"{name}: expected 1-10 ticker items"
            )

        prefix = re.sub(
            r"[^a-z0-9]+",
            "-",
            name.lower(),
        ).strip("-")[:40] or "event"

        normalized_items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for rank, story in enumerate(stories, start=1):
            if not isinstance(story, dict):
                raise TickerError(f"{name} #{rank}: invalid item")

            item = normalize_story(
                story,
                rank,
                f"special-{prefix}",
            )
            validate_story(item, f"{name} #{rank}")

            if item["id"] in seen_ids:
                raise TickerError(
                    f"{name}: duplicate ticker item {item['headline']!r}"
                )

            seen_ids.add(item["id"])
            normalized_items.append(item)

        special_events.append(
            {
                "name": name,
                "sport": sport,
                "items": normalized_items,
            }
        )

    generated_at = utc_now().isoformat().replace("+00:00", "Z")

    return {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "model": model,
        "leagues": [
            by_league[league]
            for league in BASE_LEAGUES
        ],
        "specialEvents": special_events,
    }


def semantic_payload(dataset: dict[str, Any]) -> dict[str, Any]:
    """Fields used to determine whether a commit is meaningful."""
    return {
        "schemaVersion": dataset.get("schemaVersion"),
        "model": dataset.get("model"),
        "leagues": dataset.get("leagues", []),
        "specialEvents": dataset.get("specialEvents", []),
    }


def load_previous(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def render_text(dataset: dict[str, Any]) -> str:
    lines = [
        "SPORTS BIG BOARD — SPORTS TICKER SIDECAR",
        f"Updated: {dataset['generatedAt']}",
        f"Model: {dataset['model']}",
        "",
    ]

    for group in dataset["leagues"]:
        lines.extend(
            [
                "=" * 72,
                group["league"],
                "=" * 72,
                "",
            ]
        )

        for item in group["items"]:
            lines.append(
                f"{item['rank']:>2}. [{item['type']}] "
                f"{item['headline']} "
                f"(priority {item['priority']})"
            )
            lines.append(f"    {item['text']}")

            if item["eventDate"]:
                lines.append(
                    f"    Event date: {item['eventDate']} | "
                    f"Status: {item['status']}"
                )
            else:
                lines.append(f"    Status: {item['status']}")

            if item["entities"]:
                lines.append(
                    "    Entities: " + ", ".join(item["entities"])
                )

            for url in item["sourceUrls"]:
                lines.append(f"    Source: {url}")

            lines.append("")

    if dataset["specialEvents"]:
        lines.extend(
            [
                "#" * 72,
                "SPECIAL EVENTS",
                "#" * 72,
                "",
            ]
        )

        for event in dataset["specialEvents"]:
            lines.extend(
                [
                    f"{event['name']} ({event['sport']})",
                    "-" * 72,
                    "",
                ]
            )

            for item in event["items"]:
                lines.append(
                    f"{item['rank']:>2}. [{item['type']}] "
                    f"{item['headline']} "
                    f"(priority {item['priority']})"
                )
                lines.append(f"    {item['text']}")

                if item["eventDate"]:
                    lines.append(
                        f"    Event date: {item['eventDate']} | "
                        f"Status: {item['status']}"
                    )
                else:
                    lines.append(f"    Status: {item['status']}")

                for url in item["sourceUrls"]:
                    lines.append(f"    Source: {url}")

                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        newline="\n",
    ) as handle:
        handle.write(content)
        temp_name = handle.name

    os.replace(temp_name, path)


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--data-dir",
        default="data",
        help="Output directory (default: data)",
    )

    parser.add_argument(
        "--model",
        default=os.environ.get(
            "SPORTS_TICKER_MODEL",
            DEFAULT_MODEL,
        ),
        help="OpenAI model",
    )

    parser.add_argument(
        "--force-write",
        action="store_true",
        help="Write even if semantic content is unchanged",
    )

    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not api_key:
        raise TickerError("OPENAI_API_KEY is required")

    data_dir = Path(args.data_dir)
    json_path = data_dir / "sports-ticker.json"
    text_path = data_dir / "sports-ticker.txt"

    print(
        f"Refreshing Sports Ticker with model {args.model}"
    )

    response = call_openai(api_key, args.model)
    output_text = extract_output_text(response)

    try:
        raw = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise TickerError(
            f"Structured output was not valid JSON: {exc}"
        ) from exc

    dataset = normalize_and_validate(raw, args.model)
    previous = load_previous(json_path)

    if (
        not args.force_write
        and previous is not None
        and semantic_payload(previous) == semantic_payload(dataset)
    ):
        print(
            "No meaningful Sports Ticker changes; "
            "cached files left untouched."
        )
        return 0

    json_output = (
        json.dumps(
            dataset,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    text_output = render_text(dataset)

    # Hard sidecar boundary: these are the only two files this program writes.
    atomic_write(json_path, json_output)
    atomic_write(text_path, text_output)

    league_count = sum(
        len(group["items"])
        for group in dataset["leagues"]
    )

    special_count = sum(
        len(group["items"])
        for group in dataset["specialEvents"]
    )

    print(
        f"Wrote {json_path} and {text_path}: "
        f"{league_count} league items + "
        f"{special_count} Special Event items."
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TickerError as exc:
        print(
            f"SPORTS TICKER ERROR: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2)

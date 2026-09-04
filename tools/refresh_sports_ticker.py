#!/usr/bin/env python3
"""Sports Big Board Sports Ticker Phase A2 sidecar generator."""

from __future__ import annotations
import argparse, hashlib, json, os, re, sys, tempfile, time
import urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-luna"
FRESHNESS_HOURS = 24.0
BASE_LEAGUES = ["MLB","NFL","NBA","NHL","EPL","MLS","NCAAF"]

ALLOWED_TYPES = [
    "BREAKING","RESULT","UPSET","TRADE","SIGNING","INJURY","RETURN","RECORD",
    "RECORD_CHASE","MILESTONE","STREAK","SLUMP","RANKING","PLAYOFF","STANDINGS",
    "AWARD","STAT_LEADER","CONTRACT","SUSPENSION","DISCIPLINE","LEGAL",
    "COACHING","ROSTER","DEPTH_CHART","LEAGUE_NEWS","SCHEDULE","NEXT","OTHER",
]
ALLOWED_STATUS = ["active","watch","next"]

PREFERRED_SOURCE_HOSTS = {
    "mlb.com","nfl.com","nba.com","nhl.com","premierleague.com","mlssoccer.com",
    "ncaa.com","espn.com","apnews.com","reuters.com","cbssports.com",
    "sports.yahoo.com","nbcsports.com","foxsports.com","theathletic.com","si.com",
    "usopen.org","atptour.com","wtatennis.com","pgatour.com","formula1.com",
    "ufc.com","olympics.com","fifa.com",
}
REJECTED_SOURCE_HOSTS = {"wikipedia.org","en.wikipedia.org"}

STORY_SCHEMA = {
    "type":"object","additionalProperties":False,
    "required":["type","priority","headline","text","entities","occurredAt","timePrecision","freshnessBasis","status","sourceUrls"],
    "properties":{
        "type":{"type":"string","enum":ALLOWED_TYPES},
        "priority":{"type":"integer","minimum":1,"maximum":100},
        "headline":{"type":"string","minLength":4,"maxLength":120},
        "text":{"type":"string","minLength":10,"maxLength":360},
        "entities":{"type":"array","maxItems":8,"items":{"type":"string","minLength":1,"maxLength":80}},
        "occurredAt":{"type":"string","minLength":10,"maxLength":40},
        "timePrecision":{"type":"string","enum":["exact","hour","date"]},
        "freshnessBasis":{"type":"string","minLength":8,"maxLength":240},
        "status":{"type":"string","enum":ALLOWED_STATUS},
        "sourceUrls":{"type":"array","minItems":1,"maxItems":3,"items":{"type":"string","minLength":8,"maxLength":500}},
    },
}

LEAGUE_SCHEMA: dict[str, Any] = {
    "type":"object","additionalProperties":False,
    "required":["league","seasonState","items"],
    "properties":{
        "league":{"type":"string","enum":BASE_LEAGUES},
        "seasonState":{"type":"string","enum":["active","offseason","preseason","postseason"]},
        "items":{"type":"array","minItems":1,"maxItems":10,"items":{"$ref":"#/$defs/story"}},
    },
    "$defs":{"story":STORY_SCHEMA},
}

SPECIAL_SCHEMA: dict[str, Any] = {
    "type":"object","additionalProperties":False,
    "required":["specialEvents"],
    "properties":{
        "specialEvents":{"type":"array","maxItems":6,"items":{
            "type":"object","additionalProperties":False,
            "required":["name","sport","items"],
            "properties":{
                "name":{"type":"string","minLength":2,"maxLength":100},
                "sport":{"type":"string","minLength":2,"maxLength":50},
                "items":{"type":"array","minItems":1,"maxItems":10,"items":{"$ref":"#/$defs/story"}},
            },
        }},
    },
    "$defs":{"story":STORY_SCHEMA},
}

BASE_SYSTEM_PROMPT = """You are the editorial intelligence layer for Sports Big Board.

The Sports Ticker is a rolling "what happened in the last 24 hours?" catch-up feed.
It is NOT a general news archive and NOT a list of the newest articles.

HARD FRESHNESS RULE
- Every item MUST describe a development that happened, was announced, was newly
  reported, or materially changed within the previous 24 hours.
- Do not include older evergreen context merely because it is still important.
- For NEXT/SCHEDULE, the event may be future, but the reason it is ticker-worthy
  must itself have become relevant or materially changed within the last 24 hours.
- occurredAt must be the best ISO 8601 timestamp for the development itself.
- If you cannot establish that it is within the last 24 hours, omit it.

EDITORIAL OBJECTIVE
Return the most important developments a knowledgeable sports fan would want to
know right now. Rank by consequence and usefulness, not article recency.

Prioritize:
BREAKING, RESULT, UPSET, TRADE, SIGNING, INJURY, RETURN, RECORD, RECORD_CHASE,
MILESTONE, STREAK, SLUMP, RANKING, PLAYOFF, STANDINGS, AWARD, STAT_LEADER,
CONTRACT, SUSPENSION, DISCIPLINE, LEGAL, COACHING, ROSTER, DEPTH_CHART,
LEAGUE_NEWS, SCHEDULE, NEXT.

SOURCE QUALITY
Prefer:
1. official league / competition / team / event sites
2. AP or Reuters
3. ESPN, CBS Sports, NBC Sports, Fox Sports, The Athletic, Yahoo Sports,
   Sports Illustrated and similarly established sports newsrooms
4. credible local beat reporting when stronger sources are unavailable

Avoid Wikipedia for current news, aggregators, scraped mirrors, SEO pages,
unrecognized republishers, and invented URLs.

For priority >= 90, prefer two independent sources when practical unless one
source is the official announcement.

CLASSIFICATION
Use the most semantically accurate type.
- player/team recognition -> RANKING or AWARD, not CONTRACT
- starter/backup changes -> DEPTH_CHART
- exempt list/punishment -> DISCIPLINE or SUSPENSION
- criminal/civil proceedings -> LEGAL
- roster move without signing/trade -> ROSTER

EDITORIAL MIX
Before filling the list with routine game results, actively search for:
- playoff / standings movement
- injuries and returns
- transactions and contracts
- records, record chases and milestones
- streaks and slumps
- rankings and awards
- suspensions, discipline, legal or coaching developments
- consequential roster / depth-chart changes

Ordinary RESULT items should usually fill the bottom of the list after
higher-information developments are considered.
- Return no more than 5 ordinary RESULT items in one league.
- Return no more than 2 combined NEXT/SCHEDULE items in one league.
- UPSET is not treated as an ordinary RESULT when the upset itself is major.
- Do not include a weak preview merely to reach a target count.

NEXT / SCHEDULE GATE
A future game/event alone is not fresh news. For NEXT or SCHEDULE,
freshnessBasis must identify the NEW development from the last 24 hours that
makes the item ticker-worthy. If there is no such development, omit it.

TIMESTAMP PRECISION
- timePrecision="exact": a real timestamp is known; occurredAt is ISO 8601.
- timePrecision="hour": only the hour is known; occurredAt uses the top of that
  known hour, with no invented minutes/seconds.
- timePrecision="date": only the calendar date is known; occurredAt is
  YYYY-MM-DD. Never manufacture 00:00:00Z for a date-only source.
- If only a date is known and it is the same UTC calendar date as the 24-hour
  cutoff, freshness cannot be proven. Omit it.
- freshnessBasis briefly states what became new within the 24-hour window.

CONSISTENCY
Verify wording agrees with stated facts.
- Never say shutout / shut out / blanked if the opponent scored.
- Never call a result a one-point win unless the score margin is one.
- Do not claim a sweep, record, ranking, or streak unless sources support it.

QUALITY CONTROL
Before finalizing ask:
"Am I missing any story substantially more important than the lowest-ranked
story currently in my list?"
If yes, replace the weaker item.

Do not duplicate the same development. Keep headlines factual and compact.
"""

LEAGUE_USER_TEMPLATE = """Research ONLY {league} for the current Sports Big Board ticker.

Current UTC time: {now}
Freshness cutoff: {cutoff}

Determine seasonState: active, offseason, preseason, or postseason.

Target up to 10 verified, high-value developments from ONLY the last 24 hours.

Coverage:
- active/postseason: search deeply enough to find 8-10 strong items when that many exist
- preseason: include results, depth-chart changes, injuries, signings, cuts,
  suspensions, and major 24-hour league developments
- offseason: do not pad; 4-7 strong items may be correct
- before ordinary results, explicitly look for standings/playoff movement,
  records, milestones, injuries, transactions, rankings, streaks, discipline,
  coaching, roster and depth-chart news
- ordinary RESULT cap: 5
- combined NEXT/SCHEDULE cap: 2
- never use stale or weak items to hit a quota

Return only the structured result for {league}.
"""

SPECIAL_USER_PROMPT = """Discover currently active major Special Events OUTSIDE
MLB, NFL, NBA, NHL, EPL, MLS, NCAAF.

Current UTC time: {now}
Freshness cutoff: {cutoff}

Examples: Grand Slam tennis, World Cups, Olympics, golf majors, major racing
weekends, major combat-sports cards, and comparable events.

Only include an event if it has meaningful developments in the last 24 hours.
Return up to 6 events, each with up to 10 strong items.

Do not duplicate routine base-league coverage into Special Events unless the
event has distinct standalone editorial value.

Return only the structured Special Events result.
"""

class TickerError(RuntimeError): pass

def utc_now(): return datetime.now(timezone.utc).replace(microsecond=0)
def iso_z(dt): return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
def clean_text(v): return re.sub(r"\s+"," ",str(v or "")).strip()

def parse_iso(value):
    text=value.strip()
    if text.endswith("Z"): text=text[:-1] + "+00:00"
    dt=datetime.fromisoformat(text)
    if dt.tzinfo is None: raise ValueError("timestamp has no timezone")
    return dt.astimezone(timezone.utc)

def normalize_occurrence(value,precision,generated_at):
    raw=clean_text(value)
    precision=clean_text(precision).lower()

    if precision == "date":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",raw):
            raise ValueError("date precision requires occurredAt=YYYY-MM-DD")
        day=datetime.strptime(raw,"%Y-%m-%d").date()
        cutoff=generated_at-timedelta(hours=FRESHNESS_HOURS)
        if day <= cutoff.date():
            raise TickerError(
                f"date-only occurrence {raw} cannot prove it is inside the 24h window"
            )
        if day > generated_at.date():
            raise TickerError(f"date-only occurrence {raw} is in the future")
        return raw,None

    if precision not in {"exact","hour"}:
        raise ValueError(f"unsupported timePrecision {precision!r}")

    dt=parse_iso(raw)
    if precision == "hour" and (dt.minute != 0 or dt.second != 0):
        raise ValueError("hour precision must use minute=00 and second=00")

    age=round((generated_at-dt).total_seconds()/3600.0,2)
    return iso_z(dt),age

def age_label(item):
    age=item.get("ageHours")
    if age is None:
        return f"date-only {item['occurredAt']}"
    return f"{float(age):.2f}h"

def hostname(url):
    try: host=(urllib.parse.urlparse(url).hostname or "").lower()
    except Exception: return ""
    return host[4:] if host.startswith("www.") else host

def is_rejected_host(host):
    return any(host==bad or host.endswith("."+bad) for bad in REJECTED_SOURCE_HOSTS)

def is_preferred_host(host):
    return any(host==good or host.endswith("."+good) for good in PREFERRED_SOURCE_HOSTS)

def valid_url(value):
    p=urllib.parse.urlparse(value)
    return p.scheme in {"http","https"} and bool(p.netloc)

def extract_output_text(response):
    chunks=[]; refusals=[]
    for item in response.get("output",[]):
        if not isinstance(item,dict) or item.get("type")!="message": continue
        for content in item.get("content",[]):
            if not isinstance(content,dict): continue
            if content.get("type")=="output_text" and isinstance(content.get("text"),str):
                chunks.append(content["text"])
            elif content.get("type")=="refusal" and isinstance(content.get("refusal"),str):
                refusals.append(content["refusal"])
    if refusals: raise TickerError("Model refused ticker request: "+" | ".join(refusals))
    text="\n".join(chunks).strip()
    if not text: raise TickerError("OpenAI response contained no output text")
    return text

def call_openai(api_key, model, system_prompt, user_prompt, schema_name, schema, timeout=240):
    payload={
        "model":model,
        "reasoning":{"effort":"low"},
        "tools":[{"type":"web_search"}],
        "input":[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}],
        "text":{"format":{"type":"json_schema","name":schema_name,"strict":True,"schema":schema}},
        "max_output_tokens":12000,
    }
    body=json.dumps(payload).encode("utf-8")
    headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json",
             "User-Agent":"sports-big-board-ticker-sidecar/phase-a2.3"}
    last=None
    for attempt in range(1,4):
        req=urllib.request.Request(API_URL,data=body,headers=headers,method="POST")
        try:
            with urllib.request.urlopen(req,timeout=timeout) as r:
                result=json.loads(r.read().decode("utf-8"))
                return json.loads(extract_output_text(result))
        except urllib.error.HTTPError as exc:
            details=exc.read().decode("utf-8",errors="replace")
            last=TickerError(f"OpenAI HTTP {exc.code}: {details[:2000]}")
            if exc.code not in {408,409,429,500,502,503,504} or attempt==3: raise last
        except (urllib.error.URLError,TimeoutError,json.JSONDecodeError) as exc:
            last=exc
            if attempt==3: raise TickerError(f"OpenAI request failed: {exc}") from exc
        delay=attempt*6
        print(f"OpenAI attempt {attempt} failed; retrying in {delay}s",file=sys.stderr)
        time.sleep(delay)
    raise TickerError(f"OpenAI request failed: {last}")

def story_fingerprint(item):
    core="|".join([item["type"].lower(),
                   re.sub(r"[^a-z0-9]+","-",item["headline"].lower()).strip("-"),
                   item["occurredAt"][:13]])
    return hashlib.sha1(core.encode()).hexdigest()[:16]

def normalize_story(story,rank,id_prefix,generated_at):
    urls=[]; seen=set()
    for raw in story.get("sourceUrls",[]):
        url=clean_text(raw)
        if url and url not in seen:
            urls.append(url); seen.add(url)

    precision=clean_text(story["timePrecision"]).lower()
    occurred_at,age=normalize_occurrence(
        story["occurredAt"],precision,generated_at
    )

    item={
        "rank":rank,
        "type":clean_text(story["type"]).upper(),
        "priority":int(story["priority"]),
        "headline":clean_text(story["headline"]),
        "text":clean_text(story["text"]),
        "entities":[clean_text(v) for v in story.get("entities",[]) if clean_text(v)],
        "occurredAt":occurred_at,
        "timePrecision":precision,
        "freshnessBasis":clean_text(story["freshnessBasis"]),
        "ageHours":age,
        "status":clean_text(story["status"]).lower(),
        "sourceUrls":urls,
    }
    item["id"]=f"{id_prefix}-{story_fingerprint(item)}"
    return item

def score_pairs(text):
    return [
        (int(a),int(b))
        for a,b in re.findall(
            r"(?<!\d)(\d{1,3})\s*[-–—]\s*(\d{1,3})(?!\d)",
            text,
        )
    ]

def validate_consistency(item,context):
    combined=(item["headline"]+" "+item["text"]).lower()
    pairs=score_pairs(combined)

    if any(word in combined for word in ("shutout","shut out","shuts out","blanked")):
        for a,b in pairs:
            if a > 0 and b > 0:
                raise TickerError(
                    f"{context}: shutout/blanked wording conflicts with score {a}-{b}"
                )

    if any(
        phrase in combined
        for phrase in (
            "one-point win","one point win",
            "one-point victory","one point victory",
        )
    ):
        for a,b in pairs:
            if abs(a-b) != 1:
                raise TickerError(
                    f"{context}: one-point wording conflicts with score {a}-{b}"
                )

def validate_story(item,context,generated_at):
    if item["type"] not in ALLOWED_TYPES: raise TickerError(f"{context}: unsupported type")
    if not 1<=item["priority"]<=100: raise TickerError(f"{context}: priority out of range")
    if not item["headline"] or len(item["headline"])>120: raise TickerError(f"{context}: invalid headline")
    if len(item["text"])<10 or len(item["text"])>360: raise TickerError(f"{context}: invalid text")
    if len(item["freshnessBasis"])<8 or len(item["freshnessBasis"])>240:
        raise TickerError(f"{context}: invalid freshnessBasis")
    if item["status"] not in ALLOWED_STATUS: raise TickerError(f"{context}: invalid status")

    if item["timePrecision"] in {"exact","hour"}:
        occurred=parse_iso(item["occurredAt"])
        age=(generated_at-occurred).total_seconds()/3600.0
        if age < -0.5: raise TickerError(f"{context}: occurredAt is in future")
        if age > FRESHNESS_HOURS: raise TickerError(f"{context}: stale age={age:.2f}h")
    elif item["timePrecision"] != "date":
        raise TickerError(f"{context}: invalid timePrecision")

    if not item["sourceUrls"]: raise TickerError(f"{context}: missing source")
    hosts=[]
    for url in item["sourceUrls"]:
        if not valid_url(url): raise TickerError(f"{context}: invalid source URL")
        host=hostname(url)
        if is_rejected_host(host): raise TickerError(f"{context}: rejected source {host}")
        hosts.append(host)
    if item["priority"]>=90:
        unique=set(hosts)
        if len(unique)<2 and not any(is_preferred_host(h) for h in unique):
            raise TickerError(f"{context}: priority >=90 source gate failed")

    validate_consistency(item,context)

def curate_items(items,context):
    ordered=sorted(
        items,
        key=lambda item:(
            -int(item.get("priority",0)),
            float(item["ageHours"]) if item.get("ageHours") is not None else 999.0,
            int(item.get("rank",999)),
        ),
    )

    selected=[]
    result_count=0
    preview_count=0
    other_count=0
    capped=0

    for item in ordered:
        kind=item["type"]

        if kind == "RESULT":
            if result_count >= 5:
                capped += 1
                print(
                    f"{context}: editorial cap dropping RESULT {item['headline']!r}",
                    file=sys.stderr,
                )
                continue
            result_count += 1

        if kind in {"NEXT","SCHEDULE"}:
            if preview_count >= 2:
                capped += 1
                print(
                    f"{context}: editorial cap dropping {kind} {item['headline']!r}",
                    file=sys.stderr,
                )
                continue
            preview_count += 1

        if kind == "OTHER":
            if other_count >= 1:
                capped += 1
                print(
                    f"{context}: editorial cap dropping OTHER {item['headline']!r}",
                    file=sys.stderr,
                )
                continue
            other_count += 1

        selected.append(item)
        if len(selected) == 10:
            break

    for rank,item in enumerate(selected,1):
        item["rank"]=rank

    return selected,capped

def normalize_league(raw,expected,generated_at):
    if not isinstance(raw,dict): raise TickerError(f"{expected}: invalid output")
    league=clean_text(raw.get("league","")).upper()
    if league!=expected: raise TickerError(f"{expected}: returned {league}")
    season=clean_text(raw.get("seasonState","")).lower()
    if season not in {"active","offseason","preseason","postseason"}:
        raise TickerError(f"{expected}: invalid seasonState")
    stories=raw.get("items")
    if not isinstance(stories,list) or not 1<=len(stories)<=10:
        raise TickerError(f"{expected}: expected 1-10 items")

    out=[]; ids=set(); dropped=[]
    for original_rank,story in enumerate(stories,1):
        try:
            item=normalize_story(story,original_rank,expected.lower(),generated_at)
            validate_story(item,f"{expected} #{original_rank}",generated_at)
            if item["id"] in ids:
                raise TickerError(f"{expected} #{original_rank}: duplicate item")
        except (TickerError, ValueError, KeyError, TypeError) as exc:
            dropped.append(f"#{original_rank}: {exc}")
            print(f"{expected}: dropping item #{original_rank}: {exc}",file=sys.stderr)
            continue

        ids.add(item["id"])
        out.append(item)

    if not out:
        details=" | ".join(dropped[:5]) if dropped else "no usable items"
        raise TickerError(f"{expected}: no fresh valid ticker items remain after filtering ({details})")

    out,editorial_dropped=curate_items(out,expected)

    if dropped or editorial_dropped:
        print(
            f"{expected}: kept {len(out)} of {len(stories)} items; "
            f"validationDropped={len(dropped)} editorialDropped={editorial_dropped}",
            file=sys.stderr,
        )

    if season in {"active","postseason"} and len(out)<6:
        print(
            f"WARNING: {expected} is {season} but only {len(out)} fresh valid items survived",
            file=sys.stderr,
        )

    return {
        "league":expected,
        "seasonState":season,
        "items":out,
        "droppedItemCount":len(dropped),
        "editorialDroppedCount":editorial_dropped,
    }

def normalize_special(raw,generated_at):
    events=raw.get("specialEvents",[])
    if not isinstance(events,list) or len(events)>6: raise TickerError("invalid specialEvents")
    out=[]; names=set()
    for idx,event in enumerate(events,1):
        name=clean_text(event.get("name","")); sport=clean_text(event.get("sport",""))
        if len(name)<2 or len(sport)<2:
            print(f"Special Event #{idx}: dropping malformed event",file=sys.stderr)
            continue
        if name.lower() in names:
            print(f"Special Events: dropping duplicate event {name}",file=sys.stderr)
            continue
        names.add(name.lower())

        stories=event.get("items")
        if not isinstance(stories,list) or not 1<=len(stories)<=10:
            print(f"{name}: dropping event with invalid item collection",file=sys.stderr)
            continue

        prefix=re.sub(r"[^a-z0-9]+","-",name.lower()).strip("-")[:40] or "event"
        items=[]; ids=set(); dropped=0
        for original_rank,story in enumerate(stories,1):
            try:
                item=normalize_story(story,original_rank,f"special-{prefix}",generated_at)
                validate_story(item,f"{name} #{original_rank}",generated_at)
                if item["id"] in ids:
                    raise TickerError(f"{name} #{original_rank}: duplicate item")
            except (TickerError, ValueError, KeyError, TypeError) as exc:
                dropped += 1
                print(f"{name}: dropping item #{original_rank}: {exc}",file=sys.stderr)
                continue
            ids.add(item["id"]); items.append(item)

        if not items:
            print(f"{name}: dropping event because no fresh valid items remain",file=sys.stderr)
            continue

        items,editorial_dropped=curate_items(items,name)

        out.append({
            "name":name,
            "sport":sport,
            "items":items,
            "droppedItemCount":dropped,
            "editorialDroppedCount":editorial_dropped,
        })
    return out

def semantic_story(item):
    return {
        "id":item.get("id"),
        "type":item.get("type"),
        "priority":item.get("priority"),
        "headline":item.get("headline"),
        "text":item.get("text"),
        "entities":item.get("entities",[]),
        "occurredAt":item.get("occurredAt"),
        "timePrecision":item.get("timePrecision"),
        "freshnessBasis":item.get("freshnessBasis"),
        "status":item.get("status"),
        "sourceUrls":item.get("sourceUrls",[]),
    }

def semantic_payload(dataset):
    return {
        "schemaVersion":dataset.get("schemaVersion"),
        "freshnessHours":dataset.get("freshnessHours"),
        "model":dataset.get("model"),
        "researchMode":dataset.get("researchMode"),
        "a2Revision":dataset.get("a2Revision"),
        "leagues":[
            {
                "league":group.get("league"),
                "seasonState":group.get("seasonState"),
                "items":[semantic_story(item) for item in group.get("items",[])],
            }
            for group in dataset.get("leagues",[])
        ],
        "specialEvents":[
            {
                "name":event.get("name"),
                "sport":event.get("sport"),
                "items":[semantic_story(item) for item in event.get("items",[])],
            }
            for event in dataset.get("specialEvents",[])
        ],
    }

def load_previous(path):
    if not path.exists(): return None
    try:
        v=json.loads(path.read_text(encoding="utf-8"))
        return v if isinstance(v,dict) else None
    except Exception: return None

def render_text(dataset):
    lines=[
        "SPORTS BIG BOARD — SPORTS TICKER PHASE A2.3",
        f"Updated: {dataset['generatedAt']}",
        f"Freshness window: last {dataset['freshnessHours']} hours",
        f"Model: {dataset['model']}","",
    ]

    for group in dataset["leagues"]:
        lines += [
            "="*72,
            f"{group['league']}  [{group['seasonState'].upper()}]",
            "="*72,
            "",
        ]
        for item in group["items"]:
            lines.append(
                f"{item['rank']:>2}. [{item['type']}] {item['headline']} "
                f"(priority {item['priority']}, age {age_label(item)})"
            )
            lines.append(f"    {item['text']}")
            lines.append(
                f"    Occurred: {item['occurredAt']} | "
                f"Precision: {item['timePrecision']} | "
                f"Status: {item['status']}"
            )
            lines.append(f"    Freshness basis: {item['freshnessBasis']}")
            if item["entities"]:
                lines.append("    Entities: "+", ".join(item["entities"]))
            for url in item["sourceUrls"]:
                lines.append(f"    Source: {url}")
            lines.append("")

    if dataset["specialEvents"]:
        lines += ["#"*72,"SPECIAL EVENTS","#"*72,""]
        for event in dataset["specialEvents"]:
            lines += [f"{event['name']} ({event['sport']})","-"*72,""]
            for item in event["items"]:
                lines.append(
                    f"{item['rank']:>2}. [{item['type']}] {item['headline']} "
                    f"(priority {item['priority']}, age {age_label(item)})"
                )
                lines.append(f"    {item['text']}")
                lines.append(
                    f"    Occurred: {item['occurredAt']} | "
                    f"Precision: {item['timePrecision']} | "
                    f"Status: {item['status']}"
                )
                lines.append(f"    Freshness basis: {item['freshnessBasis']}")
                for url in item["sourceUrls"]:
                    lines.append(f"    Source: {url}")
                lines.append("")

    return "\n".join(lines).rstrip()+"\n"

def atomic_write(path,content):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=path.parent,delete=False,newline="\n") as h:
        h.write(content); tmp=h.name
    os.replace(tmp,path)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",default="data")
    p.add_argument("--model",default=os.environ.get("SPORTS_TICKER_MODEL",DEFAULT_MODEL))
    p.add_argument("--force-write",action="store_true")
    args=p.parse_args()
    api_key=os.environ.get("OPENAI_API_KEY","").strip()
    if not api_key: raise TickerError("OPENAI_API_KEY is required")

    generated=utc_now(); cutoff=generated-timedelta(hours=FRESHNESS_HOURS)
    print(f"Refreshing Sports Ticker A2.3 with {args.model}; window={iso_z(cutoff)} to {iso_z(generated)}")

    leagues=[]
    for league in BASE_LEAGUES:
        print(f"Researching {league}...")
        raw=call_openai(api_key,args.model,BASE_SYSTEM_PROMPT,
            LEAGUE_USER_TEMPLATE.format(league=league,now=iso_z(generated),cutoff=iso_z(cutoff)),
            f"sports_ticker_{league.lower()}",LEAGUE_SCHEMA)
        group=normalize_league(raw,league,generated)
        print(f"{league}: {len(group['items'])} items, seasonState={group['seasonState']}")
        leagues.append(group)

    print("Researching Special Events...")
    raw_special=call_openai(api_key,args.model,BASE_SYSTEM_PROMPT,
        SPECIAL_USER_PROMPT.format(now=iso_z(generated),cutoff=iso_z(cutoff)),
        "sports_ticker_special_events",SPECIAL_SCHEMA)
    specials=normalize_special(raw_special,generated)

    dataset={
        "schemaVersion":3,
        "generatedAt":iso_z(generated),
        "freshnessHours":FRESHNESS_HOURS,
        "model":args.model,
        "researchMode":"per-league-plus-special-events",
        "a2Revision":"A2.3-editorial-ranking-precision",
        "leagues":leagues,
        "specialEvents":specials,
    }

    data_dir=Path(args.data_dir)
    json_path=data_dir/"sports-ticker.json"
    txt_path=data_dir/"sports-ticker.txt"
    previous=load_previous(json_path)

    if not args.force_write and previous is not None and semantic_payload(previous)==semantic_payload(dataset):
        print("No meaningful Sports Ticker changes; cache left untouched.")
        return 0

    atomic_write(json_path,json.dumps(dataset,indent=2,ensure_ascii=False)+"\n")
    atomic_write(txt_path,render_text(dataset))
    league_count=sum(len(g["items"]) for g in leagues)
    special_count=sum(len(g["items"]) for g in specials)
    print(f"Wrote {json_path} and {txt_path}: {league_count} league items + {special_count} Special Event items.")
    return 0

if __name__=="__main__":
    try: raise SystemExit(main())
    except TickerError as exc:
        print(f"SPORTS TICKER ERROR: {exc}",file=sys.stderr)
        raise SystemExit(2)

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
    "required":["type","priority","headline","text","entities","occurredAt","status","sourceUrls"],
    "properties":{
        "type":{"type":"string","enum":ALLOWED_TYPES},
        "priority":{"type":"integer","minimum":1,"maximum":100},
        "headline":{"type":"string","minLength":4,"maxLength":120},
        "text":{"type":"string","minLength":10,"maxLength":360},
        "entities":{"type":"array","maxItems":8,"items":{"type":"string","minLength":1,"maxLength":80}},
        "occurredAt":{"type":"string","minLength":20,"maxLength":40},
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
- never use stale items to hit a quota

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
             "User-Agent":"sports-big-board-ticker-sidecar/phase-a2"}
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
    occurred=parse_iso(clean_text(story["occurredAt"]))
    age=round((generated_at-occurred).total_seconds()/3600.0,2)
    item={
        "rank":rank,"type":clean_text(story["type"]).upper(),
        "priority":int(story["priority"]),"headline":clean_text(story["headline"]),
        "text":clean_text(story["text"]),
        "entities":[clean_text(v) for v in story.get("entities",[]) if clean_text(v)],
        "occurredAt":iso_z(occurred),"ageHours":age,
        "status":clean_text(story["status"]).lower(),"sourceUrls":urls,
    }
    item["id"]=f"{id_prefix}-{story_fingerprint(item)}"
    return item

def validate_story(item,context,generated_at):
    if item["type"] not in ALLOWED_TYPES: raise TickerError(f"{context}: unsupported type")
    if not 1<=item["priority"]<=100: raise TickerError(f"{context}: priority out of range")
    if not item["headline"] or len(item["headline"])>120: raise TickerError(f"{context}: invalid headline")
    if len(item["text"])<10 or len(item["text"])>360: raise TickerError(f"{context}: invalid text")
    if item["status"] not in ALLOWED_STATUS: raise TickerError(f"{context}: invalid status")
    occurred=parse_iso(item["occurredAt"])
    age=(generated_at-occurred).total_seconds()/3600.0
    if age < -0.5: raise TickerError(f"{context}: occurredAt is in future")
    if age > FRESHNESS_HOURS: raise TickerError(f"{context}: stale age={age:.2f}h")
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

    # Re-rank only the fresh, valid survivors.
    for rank,item in enumerate(out,1):
        item["rank"]=rank

    if dropped:
        print(f"{expected}: kept {len(out)} of {len(stories)} items; dropped {len(dropped)}",file=sys.stderr)

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

        for rank,item in enumerate(items,1):
            item["rank"]=rank

        out.append({
            "name":name,
            "sport":sport,
            "items":items,
            "droppedItemCount":dropped,
        })
    return out

def semantic_payload(dataset):
    return {k:dataset.get(k) for k in ["schemaVersion","freshnessHours","model","researchMode","a2Revision","leagues","specialEvents"]}

def load_previous(path):
    if not path.exists(): return None
    try:
        v=json.loads(path.read_text(encoding="utf-8"))
        return v if isinstance(v,dict) else None
    except Exception: return None

def render_text(dataset):
    lines=[
        "SPORTS BIG BOARD — SPORTS TICKER PHASE A2",
        f"Updated: {dataset['generatedAt']}",
        f"Freshness window: last {dataset['freshnessHours']} hours",
        f"Model: {dataset['model']}","",
    ]
    for group in dataset["leagues"]:
        lines += ["="*72,f"{group['league']}  [{group['seasonState'].upper()}]","="*72,""]
        for item in group["items"]:
            lines.append(f"{item['rank']:>2}. [{item['type']}] {item['headline']} (priority {item['priority']}, age {item['ageHours']:.2f}h)")
            lines.append(f"    {item['text']}")
            lines.append(f"    Occurred: {item['occurredAt']} | Status: {item['status']}")
            if item["entities"]: lines.append("    Entities: "+", ".join(item["entities"]))
            for url in item["sourceUrls"]: lines.append(f"    Source: {url}")
            lines.append("")
    if dataset["specialEvents"]:
        lines += ["#"*72,"SPECIAL EVENTS","#"*72,""]
        for event in dataset["specialEvents"]:
            lines += [f"{event['name']} ({event['sport']})","-"*72,""]
            for item in event["items"]:
                lines.append(f"{item['rank']:>2}. [{item['type']}] {item['headline']} (priority {item['priority']}, age {item['ageHours']:.2f}h)")
                lines.append(f"    {item['text']}")
                lines.append(f"    Occurred: {item['occurredAt']} | Status: {item['status']}")
                for url in item["sourceUrls"]: lines.append(f"    Source: {url}")
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
    print(f"Refreshing Sports Ticker A2 with {args.model}; window={iso_z(cutoff)} to {iso_z(generated)}")

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
        "schemaVersion":2,
        "generatedAt":iso_z(generated),
        "freshnessHours":FRESHNESS_HOURS,
        "model":args.model,
        "researchMode":"per-league-plus-special-events",
        "a2Revision":"A2.1-filter-invalid-items",
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

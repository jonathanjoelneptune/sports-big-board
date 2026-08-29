"""Sports Big Board v4.6.16 — consolidated special-event media pipeline.

This module turns the v4.6.13-v4.6.15 special-event overlays into one explicit
association pipeline:

SOURCE -> ELIGIBLE -> CANDIDATES -> MATCHED -> PERSISTED -> PLAYABLE

Key contracts:
- custom-competition registry events are the identity authority because they retain
  imported participant aliases/groups/abbreviations and official game numbers;
- normalized history rows contribute current date/status/provider metadata but may
  not erase imported identity;
- operator YouTube playlists and web recap indexes share the same associator;
- REASSOCIATE never needs network access;
- RECRAWL is the only operation that revisits configured sources;
- one durable EVENT_MEDIA relationship is the single source of truth for Statistics
  and ribbon playback;
- every source asset receives an auditable stage/result instead of disappearing into
  an aggregate orphan count.
"""
from __future__ import annotations

import html as html_lib
import re
import threading
import time
from contextlib import closing
from copy import deepcopy
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from . import competition_builder as base
from . import competition_builder_v4613 as tournament
from . import competition_builder_v4614 as aliases
from .catalog_contract import ASSIGNED

_INSTALLED=False
_INSTALL_LOCK=threading.Lock()
_AUDIT_LOCK=threading.RLock()
_AUDIT_CACHE={}
_ORIGINAL_HANDLE_GET=None

LLWS_GREEN_URL="https://www.littleleague.org/videos/video-tags/little-league-baseball,game-recaps/"
LLWS_PURPLE_URL="https://www.youtube.com/playlist?list=PLJBIB5zsrIC8"


def _clean(value):
    return str(value or "").strip()


def _norm(value):
    return aliases._norm(value)


def _media_id(item):
    item=item or {}
    return _clean(
        item.get("youtubeId") or item.get("providerMediaId") or item.get("mediaId")
        or item.get("id") or item.get("mediaUrl") or item.get("externalUrl")
    )


def _event_id(event):
    event=event or {}
    return _clean(event.get("eventId") or event.get("id") or event.get("matchId"))


def _merge_team_identity(primary, secondary):
    if not isinstance(primary,dict):
        primary={"name":_clean(primary),"displayName":_clean(primary)}
    if not isinstance(secondary,dict):
        secondary={"name":_clean(secondary),"displayName":_clean(secondary)}
    out=dict(secondary or {})
    out.update({k:v for k,v in dict(primary or {}).items() if v not in (None,"",[],{})})
    pa=primary.get("aliases") or []
    sa=secondary.get("aliases") or []
    if isinstance(pa,str): pa=[x.strip() for x in re.split(r"[\r\n]+",pa) if x.strip()]
    if isinstance(sa,str): sa=[x.strip() for x in re.split(r"[\r\n]+",sa) if x.strip()]
    merged=[]
    for x in [*pa,*sa]:
        x=_clean(x)
        if x and x.casefold() not in {y.casefold() for y in merged}: merged.append(x)
    if merged: out["aliases"]=merged
    return out


def _identity_event(comp_event, history_event):
    c=dict(comp_event or {}); h=dict(history_event or {})
    out=dict(h); out.update({k:v for k,v in c.items() if v not in (None,"",[],{})})
    out["awayTeam"]=_merge_team_identity(c.get("awayTeam") or c.get("away"),h.get("awayTeam") or h.get("away"))
    out["homeTeam"]=_merge_team_identity(c.get("homeTeam") or c.get("home"),h.get("homeTeam") or h.get("home"))
    out["away"]=out["awayTeam"]; out["home"]=out["homeTeam"]
    for key in ("status","awayScore","homeScore","providerEventId","espnEventId","scheduledAt"):
        if h.get(key) not in (None,""): out[key]=h.get(key)
    return out


def competition_records(server, comp):
    cid=_clean(comp.get("id")).upper()
    by_id={_event_id(e):dict(e) for e in (comp.get("events") or []) if _event_id(e)}
    try:
        history=server.HISTORY_REPOSITORY.catalog_events(
            league=cid,
            date_from=_clean(comp.get("startDate"))[:10],
            date_to=_clean(comp.get("endDate"))[:10],
            limit=50000,
        )
    except Exception:
        history=[]
    hmap={_clean(r.get("eventId")):r for r in history if _clean(r.get("eventId"))}
    ids=list(dict.fromkeys([*by_id.keys(),*hmap.keys()]))
    out=[]
    for eid in ids:
        c=by_id.get(eid) or {}
        hr=hmap.get(eid) or {}
        merged=_identity_event(c,dict(hr.get("event") or {}))
        merged.setdefault("eventId",eid); merged.setdefault("id",eid)
        date=_clean(hr.get("date") or merged.get("date"))[:10]
        merged["date"]=date; merged["gameDate"]=date
        merged["competitionId"]=cid; merged["__sbbLeague"]=cid; merged["__sbbDate"]=date
        out.append({
            "canonicalEventKey":_clean(hr.get("canonicalEventKey")) or f"{cid}:{eid}",
            "league":cid,"eventId":eid,"date":date,"event":merged,
            "identitySource":"CUSTOM_COMPETITION+HISTORY",
        })
    out.sort(key=lambda r:(_clean(r.get("date")),int((r.get("event") or {}).get("gameNumber") or 9999),_clean(r.get("eventId"))))
    return out


def participant_crosswalk(comp, records=None):
    records=records or [{"event":e} for e in (comp.get("events") or [])]
    out={}
    for record in records:
        event=record.get("event") or {}
        for side in ("away","home"):
            team=event.get(f"{side}Team") or event.get(side) or {}
            details=aliases._media_alias_details(team)
            identity=_clean((team or {}).get("name") if isinstance(team,dict) else team)
            if not identity: continue
            key=_norm(identity)
            row=out.setdefault(key,{"canonicalName":identity,"aliases":[],"events":[]})
            for detail in details:
                value=_clean(detail.get("value"))
                if value and value.casefold() not in {x.casefold() for x in row["aliases"]}: row["aliases"].append(value)
            eid=_clean(event.get("eventId") or record.get("eventId"))
            if eid and eid not in row["events"]: row["events"].append(eid)
    return out


def _title_game_number(item):
    title=_clean((item or {}).get("title"))
    m=re.search(r"\b(?:game|match)\s*#?\s*(\d{1,3})\b",title,re.I)
    return int(m.group(1)) if m else None


def _explicit_game_number_match(item, records):
    number=_title_game_number(item)
    if number is None:return None
    rows=[r for r in records if int(((r.get("event") or {}).get("gameNumber") or -1))==number]
    return rows[0] if len(rows)==1 else None


def _direct_alias_matches(item, records):
    matches=[]
    for record in records:
        ev=record.get("event") or {}
        evidence=aliases._direct_title_pair_evidence(item,ev)
        if evidence: matches.append((record,evidence))
    return tournament._dedupe_matches(matches)


def diagnose_item(server, comp, records, item, playlist_row=None):
    result={
        "mediaId":_media_id(item),"title":_clean(item.get("title")),
        "sourceType":_clean(item.get("sourceType") or item.get("provider")),
        "stage":"SOURCE","eligible":False,"candidateCount":0,
        "selectedEventId":"","selectedGameNumber":None,"selectedDate":"",
        "associationMethod":"","resolution":"","persisted":False,
        "playable":False,"reason":"",
    }
    allowed,reason=tournament._playlist_title_allows(comp,playlist_row,item)
    if not allowed:
        result.update(stage="ELIGIBILITY_REJECTED",reason=reason)
        return result,None,None
    result.update(stage="ELIGIBLE",eligible=True)

    numbered=_explicit_game_number_match(item,records)
    if numbered:
        evidence={
            "associationState":"ASSIGNED","associationMethod":"SPECIAL_EVENT_TITLE_ALIAS_PAIR_GAME_NUMBER",
            "titleAlias1":"official game number","titleAlias2":"official game number",
            "titlePairOrder":"GAME_NUMBER","titlePairScore":250,
        }
        result["candidateCount"]=1
        selected=(numbered,evidence);resolution="GAME_NUMBER"
    else:
        matches=_direct_alias_matches(item,records)
        result["candidateCount"]=len(matches)
        if matches:
            selected,resolution=tournament._choose_match(server,item,matches,default_year=int(comp.get("year") or 0))
        else:
            selected=None;resolution="NO_ALIAS_PAIR"

    if not selected:
        result.update(stage="AMBIGUOUS" if result["candidateCount"] else "UNMATCHED",resolution=resolution,reason=resolution)
        return result,None,None

    record,evidence=selected
    event=record.get("event") or {}
    result.update(
        stage="MATCHED",selectedEventId=_clean(record.get("eventId")),
        selectedGameNumber=event.get("gameNumber"),selectedDate=_clean(record.get("date")),
        associationMethod=_clean(evidence.get("associationMethod")),resolution=resolution,
    )
    return result,record,evidence


def _tier_for_source(item,playlist_row=None):
    explicit=_clean((item or {}).get("recapTier")).lower()
    if explicit in {"green","extended","purple","blue","gold"}:
        return "extended" if explicit=="purple" else explicit
    objective=_clean((playlist_row or {}).get("objective")).lower()
    if objective=="quick": return "green"
    if objective=="extended": return "extended"
    return "green" if _clean((item or {}).get("sourceType")).lower()=="littleleague-game-recap" else "extended"


def _persist_canonical_relationship(server, comp, item, record, evidence, resolution, playlist_row=None):
    """Persist one already-proven special-event relationship directly into v4 truth.

    The source asset and canonical event already exist independently.  Association is
    the relationship between them; re-running a generic title classifier here is both
    redundant and was the source of the v4.6.14/v4.6.15 failure cycle.

    This method stays fail-closed:
    - only this module's game-number or two-sided alias proofs reach it;
    - source asset + canonical event parents must both exist;
    - an asset already ASSIGNED to another event cannot be stolen;
    - persistence never manufactures a playable transport.
    """
    repo=server.HISTORY_REPOSITORY
    cid=_clean(comp.get("id")).upper();eid=_clean(record.get("eventId"));date=_clean(record.get("date"))[:10]
    if not cid or not eid:return 0,False,dict(item or {}),"MISSING_CANONICAL_ID"
    key=repo.canonical_event_key(cid,eid)
    event=record.get("event") or {}
    tier=_tier_for_source(item,playlist_row)

    # Decorate provenance/canonical identity for hydration, but persistence below
    # deliberately does not ask the legacy generic matcher to reinterpret the title.
    decorated=tournament._decorate_assignment(comp,playlist_row,item,record,evidence,resolution)
    decorated.update({
        "league":cid,"competitionId":cid,"eventId":eid,"matchId":eid,
        "scoreEventId":eid,"canonicalEventId":eid,"canonicalEventKey":key,
        "date":date,"gameDate":date,"__sbbDate":date,
        "mediaScope":"GAME","mediaScopeConfidence":1.0,
        "mediaScopeReason":"SPECIAL_EVENT_CANONICAL_ASSOCIATION","recapTier":tier,
        "programType":"recap" if tier=="green" else "extended",
        "associationMethod":_clean(evidence.get("associationMethod")),
        "associationResolution":_clean(resolution),
    })

    # Parent rows are written before the relationship.  put_source_media is
    # idempotent and preserves the provider-stable asset key.
    repo.upsert_event(date,cid,eid,event)
    repo.put_source_media([decorated],league=cid,date=date,catalog_state="UNASSIGNED")
    asset_key=repo.asset_key_for(decorated)
    if not asset_key:return 0,False,decorated,"SOURCE_ASSET_KEY_MISSING"

    now=time.time();method=_clean(evidence.get("associationMethod")) or "SPECIAL_EVENT_PROVEN"
    evidence_obj={
        "pipeline":"v4.6.16","resolution":_clean(resolution),"canonicalEventKey":key,
        "gameNumber":event.get("gameNumber"),"title":_clean(item.get("title")),
        "titleAlias1":_clean(evidence.get("titleAlias1")),
        "titleAlias2":_clean(evidence.get("titleAlias2")),
        "titlePairOrder":_clean(evidence.get("titlePairOrder")),
        "titlePairScore":int(evidence.get("titlePairScore") or 0),
    }
    evidence_text=repo._dump_obj(evidence_obj)[:2000]
    with repo._lock, closing(repo._connect()) as conn:
        event_parent=conn.execute(
            "SELECT event_json FROM history_catalog_event WHERE canonical_event_key=?",(key,)
        ).fetchone()
        source_parent=conn.execute(
            "SELECT asset_json,validation_state,runtime_state FROM history_source_media WHERE asset_key=?",(asset_key,)
        ).fetchone()
        if not event_parent or not source_parent:
            return 0,False,decorated,"PERSISTENCE_PARENT_MISSING"

        competing=conn.execute(
            """SELECT canonical_event_key FROM history_event_media
               WHERE asset_key=? AND association_state='ASSIGNED' AND canonical_event_key<>?""",
            (asset_key,key),
        ).fetchall()
        if competing:
            return 0,False,decorated,"CROSS_EVENT_ASSET_CONFLICT"

        existed=bool(conn.execute(
            "SELECT 1 FROM history_event_media WHERE canonical_event_key=? AND asset_key=? AND association_state='ASSIGNED'",
            (key,asset_key),
        ).fetchone())
        conn.execute(
            """INSERT INTO history_event_media(
                 canonical_event_key,asset_key,association_state,association_confidence,
                 association_method,association_evidence,matcher_version,first_associated_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(canonical_event_key,asset_key) DO UPDATE SET
                 association_state='ASSIGNED',association_confidence=excluded.association_confidence,
                 association_method=excluded.association_method,association_evidence=excluded.association_evidence,
                 matcher_version=excluded.matcher_version,updated_at=excluded.updated_at""",
            (key,asset_key,'ASSIGNED',0.995,method,evidence_text,4616,now,now),
        )
        stored=repo._load_obj(source_parent["asset_json"]);stored.update(decorated)
        stored.update({
            "assetKey":asset_key,"mediaScope":"GAME","mediaScopeConfidence":1.0,
            "mediaScopeReason":"SPECIAL_EVENT_CANONICAL_ASSOCIATION","recapTier":tier,
            "canonicalEventKey":key,"eventId":eid,"matchId":eid,"scoreEventId":eid,
            "associationMethod":method,"associationEvidence":evidence_text,
        })
        conn.execute(
            """UPDATE history_source_media SET
                 scope='GAME',scope_confidence=1.0,scope_reason='SPECIAL_EVENT_CANONICAL_ASSOCIATION',
                 catalog_state='ASSIGNED',quarantine_reason='',asset_json=?,updated_at=?
               WHERE asset_key=?""",
            (repo._dump_obj(stored),now,asset_key),
        )
        conn.execute(
            """UPDATE history_assignment_review SET state='RESOLVED',updated_at=?
               WHERE asset_key=? AND proposed_event_key=? AND state='QUARANTINED'""",
            (now,asset_key,key),
        )
        conn.commit()
    return (0 if existed else 1),True,decorated,"ALREADY_ASSIGNED" if existed else "ASSIGNED"


def persist_match(server, comp, item, record, evidence, resolution, playlist_row=None):
    return _persist_canonical_relationship(server,comp,item,record,evidence,resolution,playlist_row)


class SpecialEventMediaAssociator:
    def __init__(self,server,comp):
        self.server=server;self.comp=comp;self.cid=_clean(comp.get("id")).upper()
        self.records=competition_records(server,comp)
        self.crosswalk=participant_crosswalk(comp,self.records)
        self.playlists=[
            row for row in server._operator_media_playlists_load()
            if _clean(row.get("league")).upper()==self.cid and row.get("enabled",True)
        ]

    def playlist_for(self,item):
        row=tournament._playlist_row_for_item(self.playlists,item)
        if row:return row
        # Old SOURCE_MEDIA rows can predate v4.6.13's playlist-id stamping.  When
        # this competition has exactly one operator YouTube source, preserve its
        # title rules rather than letting legacy orphan rows bypass eligibility.
        source_type=_clean((item or {}).get("sourceType")).lower()
        provider=_clean((item or {}).get("provider")).upper()
        if len(self.playlists)==1 and (provider=="YOUTUBE" or "youtube" in source_type or "operator" in source_type):
            return self.playlists[0]
        return None

    def associate(self,items):
        audit=[];assigned=already=unmatched=ambiguous=rejected=0
        for raw in items or []:
            item=dict(raw or {});row=self.playlist_for(item)
            diag,record,evidence=diagnose_item(self.server,self.comp,self.records,item,row)
            if record and evidence:
                try:
                    added,scoped,decorated,persist_reason=persist_match(self.server,self.comp,item,record,evidence,diag["resolution"],row)
                    diag["persisted"]=bool(scoped);diag["stage"]="PERSISTED" if scoped else "PERSISTENCE_REJECTED"
                    diag["reason"]="" if scoped else persist_reason
                    diag["playable"]=bool(scoped and (decorated.get("youtubeId") or decorated.get("mediaUrl")) and decorated.get("verifiedPlayable") is not False)
                    if added>0:assigned+=1
                    elif scoped:already+=1
                except Exception as exc:
                    diag.update(stage="PERSISTENCE_ERROR",reason=f"{type(exc).__name__}: {exc}")
            elif diag["stage"]=="ELIGIBILITY_REJECTED":rejected+=1
            elif diag["stage"]=="AMBIGUOUS":ambiguous+=1
            else:unmatched+=1
            audit.append(diag)
        summary={
            "competitionId":self.cid,"sourceItems":len(items or []),"events":len(self.records),
            "participantIdentities":len(self.crosswalk),"assigned":assigned,
            "alreadyAssociated":already,"unmatched":unmatched,"ambiguous":ambiguous,
            "eligibilityRejected":rejected,"persisted":sum(1 for x in audit if x["persisted"]),
            "playable":sum(1 for x in audit if x["playable"]),
        }
        with _AUDIT_LOCK:_AUDIT_CACHE[self.cid]={"updatedAt":time.time(),"summary":summary,"assets":audit}
        return {"summary":summary,"assets":audit}


def _source_items(server,cid):
    try:return [dict(x) for x in (base._league_source_media(server,cid) or [])]
    except Exception:return []


def reassociate(server,comp):
    engine=SpecialEventMediaAssociator(server,comp)
    return engine.associate(_source_items(server,engine.cid))


def _strip_tags(value):
    return re.sub(r"\s+"," ",html_lib.unescape(re.sub(r"<[^>]+>"," ",str(value or "")))).strip()


def _extract_recap_links(index_html,base_url):
    links=[];seen=set()
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',index_html or "",re.I|re.S):
        href=html_lib.unescape(m.group(1));title=_strip_tags(m.group(2))
        if not re.search(r"\brecap\s*:",title,re.I):continue
        url=urljoin(base_url,href)
        if "/videos/" not in url or url in seen:continue
        seen.add(url);links.append({"url":url,"title":title})
    return links


def _extract_direct_media(page_html):
    text=html_lib.unescape(page_html or "").replace("\\/","/")
    urls=[]
    for pattern in (
        r'https://[^"\'<>\s]+\.mp4(?:\?[^"\'<>\s]*)?',
        r'https://[^"\'<>\s]+\.m3u8(?:\?[^"\'<>\s]*)?',
    ):
        urls.extend(re.findall(pattern,text,re.I))
    return urls[0] if urls else ""


def _extract_brightcove(page_html):
    text=html_lib.unescape(page_html or "")
    direct=re.search(r'https://players\.brightcove\.net/([^/]+)/([^/"\']+?)(?:_default)?/index\.html\?videoId=([A-Za-z0-9_-]+)',text,re.I)
    if direct:
        account,player,video=map(_clean,direct.groups())
        player=re.sub(r'_default$','',player) or 'default'
        return f"https://players.brightcove.net/{account}/{player}_default/index.html?videoId={video}",video
    def one(pattern):
        m=re.search(pattern,text,re.I);return _clean(m.group(1)) if m else ""
    video=one(r'data-video-id=["\']([^"\']+)') or one(r'"videoId"\s*:\s*"([^"]+)')
    account=one(r'data-account=["\']([^"\']+)') or one(r'"accountId"\s*:\s*"([^"]+)')
    player=one(r'data-player=["\']([^"\']+)') or one(r'"playerId"\s*:\s*"([^"]+)')
    if video and account:
        player=player or "default"
        return f"https://players.brightcove.net/{account}/{player}_default/index.html?videoId={video}",video
    return "",video


def _extract_published_at(page_html):
    text=html_lib.unescape(page_html or "")
    patterns=(
        r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|date|datePublished)["\'][^>]+content=["\']([^"\']+)',
        r'"(?:datePublished|uploadDate)"\s*:\s*"([^"]+)"',
        r'<time[^>]+datetime=["\']([^"\']+)',
    )
    for pattern in patterns:
        m=re.search(pattern,text,re.I)
        if m:return _clean(m.group(1))
    return ""


def _extract_duration_seconds(page_html):
    text=html_lib.unescape(page_html or "")
    m=re.search(r'"duration"\s*:\s*"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"',text,re.I)
    if m:return int(m.group(1) or 0)*3600+int(m.group(2) or 0)*60+int(m.group(3) or 0)
    return 0


def _fetch_text(url,timeout=12):
    req=Request(url,headers={"User-Agent":"SportsBigBoard/4.6.16","Accept":"text/html,application/xhtml+xml"})
    with urlopen(req,timeout=timeout) as resp:
        return resp.read(2_500_000).decode(resp.headers.get_content_charset() or "utf-8","replace")


def crawl_web_recap_source(server,comp,source):
    url=_clean(source.get("url"));items=[]
    if not url:return {"items":[],"error":"missing URL"}
    try:index=_fetch_text(url)
    except Exception as exc:return {"items":[],"error":f"{type(exc).__name__}: {exc}"}
    links=_extract_recap_links(index,url)
    for row in links[:120]:
        try:page=_fetch_text(row["url"])
        except Exception:page=""
        direct=_extract_direct_media(page);brightcove,bcid=_extract_brightcove(page)
        published=_extract_published_at(page);duration=_extract_duration_seconds(page)
        slug=urlparse(row["url"]).path.strip("/").split("/")[-1]
        item={
            "id":f"littleleague:{slug}","provider":"LITTLE_LEAGUE",
            "providerMediaId":bcid or slug,"sourceType":"littleleague-game-recap",
            "sourceLabel":"LittleLeague.org Game Recaps","title":row["title"],
            "externalUrl":row["url"],"recapTier":"green","programType":"recap",
            "mediaScope":"GAME","mediaScopeConfidence":1.0,"officialSource":True,
            "league":_clean(comp.get("id")).upper(),"competitionId":_clean(comp.get("id")).upper(),
            "publishedAt":published,"durationSeconds":duration,"duration":duration,
        }
        if direct:item.update(mediaUrl=direct,verifiedPlayable=True,transport="DIRECT_VIDEO")
        elif brightcove:item.update(brightcoveEmbedUrl=brightcove,externalPlayerUrl=brightcove,externalOnly=True,verifiedPlayable=False)
        else:item.update(externalOnly=True,verifiedPlayable=False)
        items.append(item)
    server.HISTORY_REPOSITORY.put_source_media(items,league=_clean(comp.get("id")).upper(),catalog_state="UNASSIGNED")
    return {"items":items,"error":"","links":len(links)}


def _ensure_llws_sources(server):
    comp=base._find("LLWS2026")
    if not comp:return None
    raw=deepcopy(comp);media=deepcopy(raw.get("mediaSources") or {"green":[],"purple":[],"blue":[]})
    for tier in ("green","purple","blue"):media.setdefault(tier,[])
    def has(url,tier):return any(_clean((x or {}).get("url") if isinstance(x,dict) else x)==url for x in media[tier])
    changed=False
    if not has(LLWS_GREEN_URL,"green"):
        media["green"].append({
            "url":LLWS_GREEN_URL,"sourceType":"WEB_RECAP_INDEX",
            "requiredTitlePhrases":["Recap:"],"priority":"PRIMARY","trust":"OPERATOR_TRUSTED",
        });changed=True
    found=False
    for tier in ("green","purple","blue"):
        keep=[]
        for src in media[tier]:
            row=dict(src) if isinstance(src,dict) else {"url":src}
            if _clean(row.get("url"))==LLWS_PURPLE_URL:
                desired={**row,"requiredTitlePhrases":["Full Game Highlights"],"sourceType":"YOUTUBE_PLAYLIST"}
                if tier=="purple":
                    keep.append(desired)
                    if desired!=row:changed=True
                elif not found:
                    media["purple"].append(desired);changed=True
                else:
                    changed=True
                found=True
            else:keep.append(src)
        media[tier]=keep
    if not found:
        media["purple"].append({"url":LLWS_PURPLE_URL,"requiredTitlePhrases":["Full Game Highlights"],"sourceType":"YOUTUBE_PLAYLIST"});changed=True
    if changed:
        raw["mediaSources"]=media
        try:
            base.save_competition(raw,list(comp.get("events") or []),server)
            # save_competition returns a catalog row with events intentionally omitted.
            # Association identity must always use the full persisted definition.
            return base._find("LLWS2026") or comp
        except Exception:
            return base._find("LLWS2026") or comp
    return base._find("LLWS2026") or comp


def recrawl(server,comp):
    cid=_clean(comp.get("id")).upper();started=[]
    for row in server._operator_media_playlists_load():
        if _clean(row.get("league")).upper()!=cid or not row.get("enabled",True):continue
        try:
            server._operator_media_playlist_crawl_async(_clean(row.get("id")),force=True)
            started.append({"type":"YOUTUBE_PLAYLIST","id":_clean(row.get("id"))})
        except Exception as exc:
            started.append({"type":"YOUTUBE_PLAYLIST","id":_clean(row.get("id")),"error":str(exc)})
    web=[]
    for _tier,sources in (comp.get("mediaSources") or {}).items():
        for src in sources or []:
            row=dict(src) if isinstance(src,dict) else {"url":src}
            url=_clean(row.get("url"));st=_clean(row.get("sourceType")).upper()
            if st=="WEB_RECAP_INDEX" or (url and "littleleague.org/videos/" in url):
                result=crawl_web_recap_source(server,comp,row)
                web.append({"url":url,"items":len(result.get("items") or []),"error":result.get("error") or ""})
    assoc=reassociate(server,comp)
    return {"competitionId":cid,"youtubeStarted":started,"webSources":web,"association":assoc.get("summary")}


def durable_stats(server,comp):
    """One normalized relationship query drives association counts and ribbon truth."""
    cid=_clean(comp.get("id")).upper();records=competition_records(server,comp)
    games=playable_games=0;playable_assets=set();assigned_assets=set();tiers={"gold":0,"green":0,"extended":0,"blue":0}
    for record in records:
        eid=_clean(record.get("eventId"));games+=1
        try:media=list(server.HISTORY_REPOSITORY.event_media(_clean(record.get("date")),cid,eid,include_failed=False) or [])
        except Exception:media=[]
        valid=[]
        for item in media:
            mid=_media_id(item)
            if mid:assigned_assets.add(mid)
            if not (item.get("youtubeId") or item.get("mediaUrl")):continue
            if item.get("verifiedPlayable") is False:continue
            valid.append(item)
            if mid:playable_assets.add(mid)
        if valid:
            playable_games+=1;best="blue";rank={"gold":4,"green":3,"extended":2,"blue":1}
            for item in valid:
                tier=_clean(item.get("recapTier") or "blue").lower()
                if tier=="purple":tier="extended"
                if tier not in rank:tier="blue"
                if rank[tier]>rank[best]:best=tier
            tiers[best]+=1
    source_items=_source_items(server,cid);source_ids={_media_id(x) for x in source_items if _media_id(x)}
    return {
        "competitionId":cid,"games":games,
        "gamesWithPlayableAssociatedMedia":playable_games,
        "gamesWithoutPlayableAssociatedMedia":max(0,games-playable_games),
        "associatedAssets":len(assigned_assets),"playableAssociatedAssets":len(playable_assets),
        "sourceAssets":len(source_ids),"orphanedAssets":len(source_ids-assigned_assets),"best":tiers,
    }


def _handle_get_v4616(server,handler,parsed):
    if parsed.path in {
        "/api/competition-builder/media-association-audit",
        "/api/competition-builder/reassociate-media",
        "/api/competition-builder/recrawl-media",
        "/api/competition-builder/media-association-stats",
    }:
        qs=parse_qs(parsed.query);cid=_clean((qs.get("id") or [""])[-1]).upper()
        comp=base._find(cid)
        if not comp:return base._send(server,handler,{"ok":False,"error":"COMPETITION_NOT_FOUND"},404)
        if parsed.path.endswith("media-association-audit"):
            with _AUDIT_LOCK:cached=deepcopy(_AUDIT_CACHE.get(cid))
            if not cached:
                result=reassociate(server,comp);cached={"updatedAt":time.time(),**result}
            return base._send(server,handler,{"ok":True,"data":cached},200)
        if parsed.path.endswith("reassociate-media"):
            result=reassociate(server,comp)
            return base._send(server,handler,{"ok":True,"data":result,"stats":durable_stats(server,comp)},200)
        if parsed.path.endswith("recrawl-media"):
            result=recrawl(server,comp)
            return base._send(server,handler,{"ok":True,"data":result,"stats":durable_stats(server,comp)},200)
        return base._send(server,handler,{"ok":True,"data":durable_stats(server,comp)},200)
    return _ORIGINAL_HANDLE_GET(server,handler,parsed)




# Startup relationship-repair routing is owned by server.py.  v4.7.0 deliberately
# does not monkeypatch HistoryRepository.repair_relationships; the repository's
# silverGameLeaks metric describes non-GAME assets that still have ASSIGNED EVENT
# links, so event repair is the correct owner of that integrity condition.

def _install_when_ready():
    global _ORIGINAL_HANDLE_GET
    server=None
    for _ in range(600):
        server=getattr(base,"_SERVER",None)
        if server is not None and hasattr(server,"_operator_media_playlist_crawl") and getattr(tournament,"_ORIGINAL_HANDLE_GET",None) is not None:
            break
        time.sleep(0.2)
    else:return

    tournament._competition_records=competition_records

    def associate_compat(server_arg,comp,records,items,playlist_rows):
        result=SpecialEventMediaAssociator(server_arg,comp).associate(items);s=result["summary"]
        return {
            "items":s["sourceItems"],"assigned":s["assigned"],"alreadyAssociated":s["alreadyAssociated"],
            "ambiguous":s["ambiguous"],"unmatched":s["unmatched"],
            "titleRuleRejected":s["eligibilityRejected"],"resolutionMethods":{},"resolvedAssets":s["persisted"],
        }
    tournament._associate_items=associate_compat

    _ORIGINAL_HANDLE_GET=base._handle_get;base._handle_get=_handle_get_v4616

    comp=_ensure_llws_sources(server)
    if comp:
        try:
            reassociate(server,comp)
            existing_green=any(_clean(x.get("sourceType")).lower()=="littleleague-game-recap" for x in _source_items(server,"LLWS2026"))
            if not existing_green:
                for src in (comp.get("mediaSources") or {}).get("green",[]):
                    row=dict(src) if isinstance(src,dict) else {"url":src}
                    if _clean(row.get("sourceType")).upper()=="WEB_RECAP_INDEX":
                        crawl_web_recap_source(server,comp,row)
                reassociate(server,comp)
        except Exception:
            pass


def install():
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:return
        _INSTALLED=True

    # Relationship-repair ownership remains in core server.py / HistoryRepository.
    # This module owns special-event media discovery and canonical persistence only.
    threading.Thread(target=_install_when_ready,daemon=True,name="sbb-special-event-media-v4616-install").start()

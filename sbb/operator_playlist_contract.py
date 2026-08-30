"""Sports Big Board v4.7.16 — operator playlist contract preservation.

Competition Builder enrolls operator YouTube playlists into the shared server
crawler. This adapter preserves competition-specific source policy that the generic
registry historically discarded: title include phrases, source labels/types, and
cross-calendar-year season bounds. It is intentionally metadata/crawler-only and
does not alter Event Matcher association rules.
"""
from __future__ import annotations

import threading
import time

_LOCK=threading.RLock()
_INSTALLED_SERVERS=set()


def _clean(value):
    return str(value or '').strip()


def install_on_server(server):
    """Patch one server module in place; idempotent and safe across restarts/tests."""
    if server is None:return False
    key=id(server)
    with _LOCK:
        if key in _INSTALLED_SERVERS:return True
    required=(
        '_operator_media_playlist_normalize',
        '_operator_playlist_to_curated',
        '_curated_playlist_items',
    )
    if not all(callable(getattr(server,name,None)) for name in required):return False

    original_normalize=server._operator_media_playlist_normalize
    original_to_curated=server._operator_playlist_to_curated
    original_items=server._curated_playlist_items

    if getattr(original_normalize,'__sbbPlaylistContract',False):
        with _LOCK:_INSTALLED_SERVERS.add(key)
        return True

    def normalize(raw,existing=None):
        raw=dict(raw or {});existing=dict(existing or {})
        row=original_normalize(raw,existing)
        for field in ('titleIncludePhrase','sourceLabel','sourceType'):
            value=raw.get(field) if raw.get(field) not in (None,'') else existing.get(field)
            if value not in (None,''):row[field]=_clean(value)
            elif field in row:row.pop(field,None)
        if 'includeAllItems' in raw or 'includeAllItems' in existing:
            row['includeAllItems']=bool(raw.get('includeAllItems',existing.get('includeAllItems',True)))
        return row
    normalize.__sbbPlaylistContract=True
    normalize.__sbbOriginal=original_normalize

    def to_curated(row):
        source=dict(row or {})
        cfg=dict(original_to_curated(source) or {})
        for field in ('titleIncludePhrase','sourceLabel','sourceType'):
            if source.get(field) not in (None,''):cfg[field]=_clean(source.get(field))
        if source.get('titleIncludePhrase'):
            # A title contract is stronger than the generic operator "include all"
            # path. The final phrase check below is still authoritative.
            cfg['includeAllItems']=False
        elif 'includeAllItems' in source:
            cfg['includeAllItems']=bool(source.get('includeAllItems'))
        return cfg
    to_curated.__sbbPlaylistContract=True
    to_curated.__sbbOriginal=original_to_curated

    def curated_items(league,playlist,force=False):
        cfg=dict(playlist or {})
        items=list(original_items(league,cfg,force=force) or [])
        phrase=_clean(cfg.get('titleIncludePhrase')).lower()
        if phrase:
            items=[item for item in items if phrase in _clean((item or {}).get('title')).lower()]
        source_label=_clean(cfg.get('sourceLabel'))
        source_type=_clean(cfg.get('sourceType'))
        if source_label or source_type:
            out=[]
            for raw in items:
                item=dict(raw or {})
                if source_label:item['source']=source_label;item['sourceLabel']=source_label
                if source_type:item['sourceType']=source_type
                out.append(item)
            items=out
        return items
    curated_items.__sbbPlaylistContract=True
    curated_items.__sbbOriginal=original_items

    server._operator_media_playlist_normalize=normalize
    server._operator_playlist_to_curated=to_curated
    server._curated_playlist_items=curated_items
    with _LOCK:_INSTALLED_SERVERS.add(key)
    return True


def ensure_competition_sources(server,competition,*,force=False):
    """Persist enriched media-source policy and schedule crawler refresh as needed."""
    if not install_on_server(server):return {'ok':False,'reason':'SERVER_NOT_READY','updated':0,'crawled':0}
    if not all(callable(getattr(server,name,None)) for name in (
        '_operator_media_playlists_load','_operator_media_playlists_save',
        '_operator_media_playlist_crawl_async','_youtube_playlist_id'
    )):return {'ok':False,'reason':'PLAYLIST_REGISTRY_NOT_READY','updated':0,'crawled':0}

    comp=dict(competition or {});cid=_clean(comp.get('id')).upper()
    try:
        leagues=list(server.HISTORY_LEAGUES)
        if cid and cid not in leagues:server.HISTORY_LEAGUES=tuple(leagues+[cid])
    except Exception:pass
    start_date=_clean(comp.get('startDate'))[:10];end_date=_clean(comp.get('endDate'))[:10]
    try:season_start=int(start_date[:4] or comp.get('year') or 0)
    except Exception:season_start=int(comp.get('year') or 0)
    try:season_end=int(end_date[:4] or season_start)
    except Exception:season_end=season_start
    objective={'green':'quick','purple':'extended','blue':'coverage'}
    rows=server._operator_media_playlists_load();updated=0;crawl_ids=[]

    for tier,sources in (comp.get('mediaSources') or {}).items():
        for src0 in sources or []:
            src=dict(src0 or {});url=_clean(src.get('url'))
            pid=server._youtube_playlist_id(url) if url else ''
            if not pid:continue
            wanted=objective.get(str(tier).lower(),'coverage')
            existing=next((x for x in rows if _clean(x.get('league')).upper()==cid and _clean(x.get('playlistId'))==pid and _clean(x.get('objective')).lower()==wanted),None)
            raw={
                'league':cid,'url':url,'playlistId':pid,
                'seasonStart':season_start,'seasonEnd':max(season_start,season_end),
                'objective':wanted,'priority':_clean(src.get('priority') or 'PRIMARY'),
                'trust':_clean(src.get('trust') or 'OPERATOR_TRUSTED'),
                'enabled':True,'autoRecrawl':True,'recrawlMinutes':int(src.get('recrawlMinutes') or 60),
                'resolveMetadata':True,
                'titleIncludePhrase':_clean(src.get('titleIncludePhrase')),
                'sourceLabel':_clean(src.get('sourceLabel')),
                'sourceType':_clean(src.get('sourceType') or f'{cid.lower()}-operator-youtube-playlist'),
                'includeAllItems':not bool(_clean(src.get('titleIncludePhrase'))),
            }
            normalized=server._operator_media_playlist_normalize(raw,existing)
            if existing:
                idx=rows.index(existing)
                if rows[idx]!=normalized:rows[idx]=normalized;updated+=1
            else:
                rows.append(normalized);updated+=1
            stats=(existing or {}).get('stats') or {}
            if force or updated or not float((existing or {}).get('lastCrawlAt') or 0) or int(stats.get('associatedThisCrawl') or 0)<=0:
                crawl_ids.append(_clean(normalized.get('id')))

    if updated:server._operator_media_playlists_save(rows)
    crawled=0
    for playlist_id in dict.fromkeys(x for x in crawl_ids if x):
        try:
            server._operator_media_playlist_crawl_async(playlist_id,force=bool(force or updated));crawled+=1
        except Exception:pass
    return {'ok':True,'updated':updated,'crawled':crawled,'seasonStart':season_start,'seasonEnd':season_end}

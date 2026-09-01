"""Sports Big Board v5.1.10 — one-way CFB -> NCAAF namespace reset.

This is intentionally destructive only for the retired CFB namespace. NCAAF is not a
migration target for derived CFB state; it is rebuilt from the ranked ESPN authority.
"""
from __future__ import annotations
from pathlib import Path
import json, os, sqlite3, threading, time

VERSION="5.1.15-ncaaf-namespace-reset-4"
STATE_DIR=Path(os.environ.get("SBB_STATE_DIR") or (Path.home()/".sports-big-board")).expanduser()
MARKER=STATE_DIR/"ncaaf-v5111-cfb-retired.json"
_LOCK=threading.Lock();_DONE=False;_STARTED=False

CFB_FILE_PATTERNS=("cfb-ranked-*.json","*cfb*cache*","*cfb*game*center*","*CFB*cache*","*CFB*game*center*")
LEAGUE_COLUMNS=("league","competition_id","competitionId","competition","league_id","leagueId")

def _q(name): return '"'+str(name).replace('"','""')+'"'

def _purge_sqlite(path):
    stats={"rows":0,"tables":{}}
    try: conn=sqlite3.connect(path,timeout=4)
    except Exception:return stats
    try:
        tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            try: cols=[r[1] for r in conn.execute(f"PRAGMA table_info({_q(table)})")]
            except Exception: continue
            before=conn.total_changes
            for col in LEAGUE_COLUMNS:
                if col in cols:
                    try: conn.execute(f"DELETE FROM {_q(table)} WHERE UPPER(COALESCE({_q(col)},''))='CFB'")
                    except Exception: pass
            # Relationship tables key the league into canonical_event_key rather than a league column.
            if "canonical_event_key" in cols:
                try: conn.execute(f"DELETE FROM {_q(table)} WHERE UPPER(COALESCE(canonical_event_key,'')) LIKE 'CFB:%'")
                except Exception: pass
            # Aliases/snapshots can carry CFB in opaque identity columns.
            for col in ("canonical_key","event_key","alias_key","cache_key","snapshot_key"):
                if col in cols:
                    try: conn.execute(f"DELETE FROM {_q(table)} WHERE UPPER(COALESCE({_q(col)},'')) LIKE 'CFB:%'")
                    except Exception: pass
            # Day State stores a complete date projection as JSON. Older snapshots
            # can therefore contain a retired CFB row even after every normalized
            # CFB table row was deleted. Drop only cache/snapshot JSON rows that
            # explicitly contain a CFB namespace marker; the engine will rebuild
            # them from the now-clean normalized repositories.
            if any(token in table.lower() for token in ("day_state","snapshot","cache")):
                for col in ("payload_json","snapshot_json","data_json","payload"):
                    if col in cols:
                        try: conn.execute(f"DELETE FROM {_q(table)} WHERE UPPER(COALESCE({_q(col)},'')) LIKE '%\"CFB\"%'")
                        except Exception: pass
            changed=conn.total_changes-before
            if changed:stats["tables"][table]=changed;stats["rows"]+=changed
        conn.commit()
    except Exception:
        try:conn.rollback()
        except Exception:pass
    finally:conn.close()
    return stats

def _purge_custom_competitions():
    path=STATE_DIR/'custom-competitions.json'
    if not path.exists():return 0
    try:
        payload=json.loads(path.read_text(encoding='utf-8'));rows=payload.get('competitions') if isinstance(payload,dict) else payload
        rows=list(rows or []); kept=[x for x in rows if str((x or {}).get('id') or '').upper()!='CFB']; removed=len(rows)-len(kept)
        if removed:
            if isinstance(payload,dict):payload['competitions']=kept;payload['revision']=max(int(payload.get('revision') or 0)+1,int(time.time()*1000));payload['updatedAt']=time.time()
            else:payload=kept
            tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,path)
        return removed
    except Exception:return 0

def _marker_result():
    if not MARKER.exists():
        return None
    try:
        value=json.loads(MARKER.read_text(encoding="utf-8"))
        return value if isinstance(value,dict) and value.get("ok") else None
    except Exception:
        return None

def purge(force=False):
    global _DONE
    force=bool(force) or str(os.environ.get("SBB_FORCE_CFB_PURGE") or "").lower() in ("1","true","yes","on")
    with _LOCK:
        if _DONE and not force:return {"ok":True,"alreadyDone":True,"version":VERSION}
        # v5.1.15 startup recovery: retirement is a one-time maintenance action.
        # v5.1.15 rescanned every persistent sqlite/cache file on every restart,
        # which could invalidate Day State snapshots while the board was starting.
        # A successful marker means the destructive cleanup already completed.
        prior=None if force else _marker_result()
        if prior:
            _DONE=True
            return {"ok":True,"alreadyDone":True,"reason":"CFB_RETIREMENT_ALREADY_APPLIED","marker":str(MARKER),"previousVersion":prior.get("version"),"version":VERSION}
        STATE_DIR.mkdir(parents=True,exist_ok=True)
        files=[]
        for pattern in CFB_FILE_PATTERNS:
            for p in STATE_DIR.glob(pattern):
                if p==MARKER or not p.is_file():continue
                try:p.unlink();files.append(p.name)
                except Exception:pass
        db={}
        for p in list(STATE_DIR.glob('*.db'))+list(STATE_DIR.glob('*.sqlite'))+list(STATE_DIR.glob('*.sqlite3')):
            result=_purge_sqlite(p)
            if result.get('rows'):db[p.name]=result
        custom=_purge_custom_competitions()
        # Runtime competition registry and GC support/indexes are also retired in-memory.
        try:
            from . import competition_registry as registry
            registry.unregister('CFB')
        except Exception:pass
        server=None
        try:
            import sys;server=sys.modules.get('__main__')
            supported=getattr(server,'GAME_CENTER_SUPPORTED',None)
            if hasattr(supported,'discard'):supported.discard('CFB')
            elif isinstance(supported,list):
                while 'CFB' in supported:supported.remove('CFB')
            repo=getattr(server,'GAME_CENTER_REPOSITORY',None)
            for attr in ('_index','index','_aliases','aliases','_cache','cache'):
                obj=getattr(repo,attr,None)
                if isinstance(obj,dict):
                    for key in list(obj):
                        if 'CFB' in str(key).upper():obj.pop(key,None)
        except Exception:pass
        result={"ok":True,"version":VERSION,"deletedFiles":sorted(set(files)),"sqlite":db,"customCompetitionsRemoved":custom,"completedAt":time.time()}
        try:MARKER.write_text(json.dumps(result,indent=2),encoding='utf-8')
        except Exception:pass
        _DONE=True
        return result

def install():
    global _STARTED,_DONE
    # Never make normal backend startup wait on a repository-wide cleanup. If the
    # v5.1.15 marker exists this returns immediately; on an older installation the
    # one-time purge is scheduled after import and the frontend already rejects CFB.
    prior=_marker_result()
    if prior:
        _DONE=True
        return {"ok":True,"alreadyDone":True,"reason":"CFB_RETIREMENT_ALREADY_APPLIED","version":VERSION}
    with _LOCK:
        if _STARTED:
            return {"ok":True,"scheduled":True,"version":VERSION}
        _STARTED=True
    def run():
        try: purge()
        except Exception: pass
    threading.Thread(target=run,daemon=True,name="sbb-cfb-retirement-once-v5115").start()
    return {"ok":True,"scheduled":True,"version":VERSION}

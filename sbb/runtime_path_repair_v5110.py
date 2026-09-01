"""Sports Big Board v5.1.10 — v4.7.20 recovery bridge with CFB worker removed."""
from __future__ import annotations
import threading,time,sys
VERSION="5.1.10-runtime-recovery-bridge-1"
_LOCK=threading.Lock();_INSTALLED=False

def _startup_without_cfb(runtime):
    server=None
    for _ in range(300):
        server=sys.modules.get('__main__')
        if server and getattr(server,'HISTORY_REPOSITORY',None):break
        time.sleep(.2)
    repo=getattr(server,'HISTORY_REPOSITORY',None) if server else None
    if repo is None:return
    # Preserve deterministic tournament/Silver recovery only. There is deliberately
    # no import of cfb_trusted_youtube and no USC/CFB polling loop.
    for name in ('restore_special_event_links','restore_silver_collection_links'):
        fn=getattr(runtime,name,None)
        if callable(fn):
            try:fn(repo)
            except Exception:pass

def install():
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:return False
        _INSTALLED=True
    try:
        from . import runtime_path_repair_v4720 as runtime
        runtime._startup_runtime_recovery=lambda: _startup_without_cfb(runtime)
        return bool(runtime.install())
    except Exception:
        return False

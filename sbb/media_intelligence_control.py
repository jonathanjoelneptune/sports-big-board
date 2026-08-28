"""Sports Big Board v4.5.3 Media Intelligence operator API.

Adds read/query/priority-scan endpoints without forking server.py. The installer
waits until the real server Handler exists, regardless of whether server.py is
executed as __main__ or imported as a module, then wraps only the dedicated
/api/media-intelligence/* namespace.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

from sbb.media_intelligence import MediaIntelligenceStore, wake_worker, worker_snapshot

_INSTALL_LOCK=threading.Lock()
_INSTALL_STARTED=False
_INSTALLED=False
_INSTALL_MODULE=""


def _read_json(handler, limit=32000):
    length=min(limit,max(0,int(handler.headers.get('Content-Length') or 0)))
    if not length:
        return {}
    raw=handler.rfile.read(length)
    data=json.loads(raw.decode('utf-8') or '{}')
    return data if isinstance(data,dict) else {}


def _status_payload(store):
    snap=store.snapshot()
    worker=worker_snapshot()
    return {
        'ok':True,
        'routeVersion':'1.1',
        'controlInstalled':True,
        'mediaIntelligence':snap,
        'worker':worker,
        'validationSet':store.validation_set(3),
        'generatedAt':time.time(),
    }


def _find_server_context():
    """Find the live server module without assuming it is named __main__."""
    preferred=[]
    for name in ('__main__','server'):
        mod=sys.modules.get(name)
        if mod is not None:
            preferred.append((name,mod))
    seen={id(mod) for _,mod in preferred}
    for name,mod in list(sys.modules.items()):
        if mod is None or id(mod) in seen:
            continue
        preferred.append((name,mod)); seen.add(id(mod))
    for name,mod in preferred:
        handler_cls=getattr(mod,'Handler',None)
        repo=getattr(mod,'HISTORY_REPOSITORY',None)
        send_json=getattr(mod,'send_json',None)
        if handler_cls is not None and repo is not None and getattr(repo,'path',None) and callable(send_json):
            return name,mod,handler_cls,repo,send_json
    return None


def _install_routes(module_name,main,handler_cls,repo,send_json):
    """Install Media Intelligence routes onto one concrete server Handler class."""
    global _INSTALLED,_INSTALL_MODULE
    if getattr(handler_cls,'__sbb_media_intelligence_control__',False):
        _INSTALLED=True; _INSTALL_MODULE=module_name
        return True

    store=MediaIntelligenceStore(repo.path)
    original_get=handler_cls.do_GET
    original_post=handler_cls.do_POST

    def do_GET(self):
        parsed=urlparse(self.path)
        if parsed.path=='/api/media-intelligence/status':
            payload=_status_payload(store)
            payload['installModule']=module_name
            return send_json(self,payload,200)
        if parsed.path=='/api/media-intelligence/assets':
            qs=parse_qs(parsed.query)
            status=str((qs.get('status') or [''])[-1]).upper()
            try:
                limit=int((qs.get('limit') or ['25'])[-1])
            except Exception:
                limit=25
            rows=store.list_assets(status,limit)
            return send_json(self,{'ok':True,'status':status or 'ALL','count':len(rows),'assets':rows},200)
        if parsed.path=='/api/media-intelligence/asset':
            qs=parse_qs(parsed.query)
            key=str((qs.get('assetKey') or [''])[-1])
            row=store.asset(key)
            return send_json(self,{'ok':bool(row),'asset':row,'assetKey':key},200 if row else 404)
        return original_get(self)

    def do_POST(self):
        parsed=urlparse(self.path)
        if parsed.path=='/api/media-intelligence/scan':
            try:
                body=_read_json(self)
                key=str(body.get('assetKey') or '').strip()
                if not key:
                    return send_json(self,{'ok':False,'error':'ASSET_KEY_REQUIRED'},400)
                current=bool(body.get('current',False))
                try:
                    requested_priority=int(body.get('priority') or (1000 if current else 250))
                except Exception:
                    requested_priority=1000 if current else 250
                priority=max(1,min(1000,requested_priority))
                row=store.request_scan(
                    key,
                    priority=priority,
                    reason=str(body.get('reason') or ('operator-current' if current else 'playback-auto'))
                )
                if not row:
                    return send_json(self,{'ok':False,'error':'MEDIA_ASSET_NOT_FOUND','assetKey':key},404)
                woke=wake_worker()
                return send_json(self,{
                    'ok':True,'queued':True,'priority':priority,'workerWoken':woke,
                    'asset':row,'worker':worker_snapshot()
                },202)
            except Exception as exc:
                return send_json(self,{'ok':False,'error':'MEDIA_INTELLIGENCE_SCAN_ERROR','message':f'{type(exc).__name__}: {exc}'},500)
        return original_post(self)

    handler_cls.do_GET=do_GET
    handler_cls.do_POST=do_POST
    handler_cls.__sbb_media_intelligence_control__=True
    setattr(main,'MEDIA_INTELLIGENCE_CONTROL_STORE',store)
    _INSTALLED=True; _INSTALL_MODULE=module_name
    try:
        log=getattr(main,'_history_console_log',None)
        if callable(log):
            log('media-intelligence','INFO',f'operator API installed • module={module_name} • status/assets/asset/scan')
    except Exception:
        pass
    return True


def schedule_media_intelligence_control_install():
    global _INSTALL_STARTED
    with _INSTALL_LOCK:
        if _INSTALL_STARTED:
            return
        _INSTALL_STARTED=True

    def install():
        # No arbitrary startup deadline: a slow catalog migration can never make
        # the Media Intelligence API disappear for the lifetime of the process.
        while not _INSTALLED:
            ctx=_find_server_context()
            if not ctx:
                time.sleep(.35)
                continue
            _install_routes(*ctx)

    threading.Thread(target=install,name='sbb-media-intelligence-control-install',daemon=True).start()


def installed():
    return bool(_INSTALLED)


def install_module():
    return str(_INSTALL_MODULE or '')

"""Sports Big Board v4.5.2 Media Intelligence operator API.

Adds read/query/priority-scan endpoints without modifying the large server.py handler.
The installer waits for server.py to construct Handler/send_json/HISTORY_REPOSITORY,
then wraps only /api/media-intelligence/* and delegates every other request unchanged.
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
        'mediaIntelligence':snap,
        'worker':worker,
        'validationSet':store.validation_set(3),
        'generatedAt':time.time(),
    }


def schedule_media_intelligence_control_install():
    global _INSTALL_STARTED
    with _INSTALL_LOCK:
        if _INSTALL_STARTED:
            return
        _INSTALL_STARTED=True

    def install():
        global _INSTALLED
        deadline=time.time()+90
        main=None; handler_cls=None; repo=None; send_json=None
        while time.time()<deadline:
            main=sys.modules.get('__main__')
            handler_cls=getattr(main,'Handler',None) if main else None
            repo=getattr(main,'HISTORY_REPOSITORY',None) if main else None
            send_json=getattr(main,'send_json',None) if main else None
            if handler_cls is not None and repo is not None and getattr(repo,'path',None) and callable(send_json):
                break
            time.sleep(.25)
        if handler_cls is None or repo is None or not callable(send_json):
            return
        if getattr(handler_cls,'__sbb_media_intelligence_control__',False):
            _INSTALLED=True; return

        store=MediaIntelligenceStore(repo.path)
        original_get=handler_cls.do_GET
        original_post=handler_cls.do_POST

        def do_GET(self):
            parsed=urlparse(self.path)
            if parsed.path=='/api/media-intelligence/status':
                return send_json(self,_status_payload(store),200)
            if parsed.path=='/api/media-intelligence/assets':
                qs=parse_qs(parsed.query)
                status=str((qs.get('status') or [''])[-1]).upper()
                try: limit=int((qs.get('limit') or ['25'])[-1])
                except Exception: limit=25
                rows=store.list_assets(status,limit)
                return send_json(self,{'ok':True,'status':status or 'ALL','count':len(rows),'assets':rows},200)
            if parsed.path=='/api/media-intelligence/asset':
                qs=parse_qs(parsed.query); key=str((qs.get('assetKey') or [''])[-1])
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
                    row=store.request_scan(key,priority=1000 if body.get('current',True) else 500,reason=str(body.get('reason') or 'operator-current'))
                    if not row:
                        return send_json(self,{'ok':False,'error':'MEDIA_ASSET_NOT_FOUND','assetKey':key},404)
                    woke=wake_worker()
                    return send_json(self,{'ok':True,'queued':True,'workerWoken':woke,'asset':row,'worker':worker_snapshot()},202)
                except Exception as exc:
                    return send_json(self,{'ok':False,'error':'MEDIA_INTELLIGENCE_SCAN_ERROR','message':f'{type(exc).__name__}: {exc}'},500)
            return original_post(self)

        handler_cls.do_GET=do_GET
        handler_cls.do_POST=do_POST
        handler_cls.__sbb_media_intelligence_control__=True
        setattr(main,'MEDIA_INTELLIGENCE_CONTROL_STORE',store)
        _INSTALLED=True
        try:
            log=getattr(main,'_history_console_log',None)
            if callable(log): log('media-intelligence','INFO','operator API installed • status/assets/asset/scan')
        except Exception:
            pass

    threading.Thread(target=install,name='sbb-media-intelligence-control-install',daemon=True).start()


def installed():
    return bool(_INSTALLED)

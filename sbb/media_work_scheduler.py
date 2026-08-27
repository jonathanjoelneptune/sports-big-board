"""Priority scheduler for background media work.

Foreground /api/media streams never enter this queue; they retain absolute network
priority. Background jobs are ordered by explicit user-visible importance. v4.2 adds
observable de-duplication so milestone testing can prove workers are not multiplying
identical upstream work. v4.3.6 adds a Game Center rate-limit circuit so a provider
429 stops already-queued background work instead of amplifying the outage.
"""
from dataclasses import dataclass, field
from queue import PriorityQueue
from threading import Thread, Lock
from concurrent.futures import Future
import itertools, time

PRIORITY = {
    "ACTIVE_PLAYBACK":1000,
    "TOUCH_INTENT":900,
    "VISIBLE_SCORE":800,
    "NEXT_PROGRAM":700,
    "NEARBY_SCORE":600,
    "RECENT_FINAL":500,
    "BACKGROUND_DISCOVERY":200,
    "FULL_CACHE_COMPLETION":100,
}

@dataclass(order=True)
class _Task:
    sort_key: tuple
    key: str=field(compare=False)
    generation: int=field(compare=False)
    fn: object=field(compare=False)
    args: tuple=field(compare=False)
    kwargs: dict=field(compare=False)
    future: Future=field(compare=False)
    submitted_at: float=field(compare=False,default_factory=time.time)

class MediaWorkScheduler:
    def __init__(self, workers=4, name="sbb-media-work"):
        self._q=PriorityQueue(); self._counter=itertools.count(); self._lock=Lock(); self._latest={}; self._threads=[]; self._active={}
        self._stats={"submitted":0,"reused":0,"superseded":0,"executed":0,"completed":0,"errors":0,"cancelled":0,"circuitRejected":0,"circuitOpened":0,"waitSeconds":0.0,"runSeconds":0.0}
        self._error_categories={}; self._recent_errors=[]; self._circuits={}
        for i in range(max(1,int(workers))):
            t=Thread(target=self._worker,name=f"{name}-{i+1}",daemon=True); t.start(); self._threads.append(t)

    @staticmethod
    def _circuit_group(key):
        key=str(key or '')
        if not key.startswith('game-center:'): return ''
        parts=key.split(':',2)
        return ':'.join(parts[:2]) if len(parts)>=2 else 'game-center'

    @staticmethod
    def _rate_limit_delay(exc):
        try:
            headers=getattr(exc,'headers',None) or {}
            raw=headers.get('Retry-After') if hasattr(headers,'get') else None
            if raw not in (None,''):
                return max(5.0,min(900.0,float(raw)))
        except Exception:
            pass
        # Match the server-side Game Center provider cooldown. The scheduler circuit
        # is a second line of defense for work that was already queued before the
        # first provider 429 was observed.
        return 900.0

    def _circuit_open_locked(self,key,priority,now=None):
        group=self._circuit_group(key)
        if not group or int(priority)>=PRIORITY['TOUCH_INTENT']: return False,0.0,group
        now=float(now or time.time()); retry=float(self._circuits.get(group) or 0)
        return retry>now,max(0.0,retry-now),group

    def submit(self,key,priority,fn,*args,**kwargs):
        key=str(key); priority=int(priority)
        fut=Future(); now=time.time()
        with self._lock:
            self._stats["submitted"]+=1
            blocked,_,_=self._circuit_open_locked(key,priority,now)
            if blocked:
                self._stats["cancelled"]+=1; self._stats["circuitRejected"]+=1
                fut.cancel(); return fut
            gen=int(self._latest.get(key,{}).get("generation",0))+1
            prior=self._latest.get(key)
            # A running task cannot be safely pre-empted. Reuse it regardless of a
            # later priority increase so the same upstream request can never execute
            # concurrently twice. A queued lower-priority task may still be
            # superseded before it starts, allowing touch/visible work to move up.
            if prior and not prior["future"].done():
                if prior["future"].running() or int(prior["priority"])>=priority:
                    self._stats["reused"]+=1
                    return prior["future"]
                self._stats["superseded"]+=1
            self._latest[key]={"generation":gen,"priority":priority,"future":fut,"submittedAt":now}
        self._q.put(_Task(sort_key=(-priority,next(self._counter)),key=key,generation=gen,fn=fn,args=args,kwargs=kwargs,future=fut,submitted_at=now))
        return fut

    @staticmethod
    def _error_category(exc):
        text=f"{type(exc).__name__}: {exc}".lower()
        code=getattr(exc,"code",None)
        if code==429 or " 429" in text or "too many requests" in text: return "rate-limit"
        if code==404 or " 404" in text or "not found" in text: return "not-found"
        if "timeout" in text or "timed out" in text: return "timeout"
        if "cancel" in text or "obsolete" in text: return "cancelled-obsolete"
        if "json" in text or "parse" in text or "decode" in text: return "parse"
        if "rate" in text and "limit" in text: return "rate-limit"
        if "http" in text or code is not None: return "provider-http"
        return type(exc).__name__ or "exception"

    def _record_error(self,task,exc):
        category=self._error_category(exc); now=time.time(); group=self._circuit_group(task.key)
        with self._lock:
            self._error_categories[category]=int(self._error_categories.get(category) or 0)+1
            self._recent_errors.append({"at":now,"key":task.key,"category":category,"error":f"{type(exc).__name__}: {exc}"[:700]})
            if len(self._recent_errors)>24:self._recent_errors=self._recent_errors[-24:]
            if category=='rate-limit' and group:
                retry=now+self._rate_limit_delay(exc)
                prior=float(self._circuits.get(group) or 0)
                self._circuits[group]=max(prior,retry)
                self._stats["circuitOpened"]+=1

    def _worker(self):
        worker_name=__import__('threading').current_thread().name
        while True:
            task=self._q.get(); run_started=0.0
            try:
                priority=-task.sort_key[0]
                with self._lock:
                    latest=self._latest.get(task.key)
                    blocked,_,_=self._circuit_open_locked(task.key,priority)
                if not latest or latest["generation"]!=task.generation:
                    if not task.future.done(): task.future.cancel()
                    with self._lock:self._stats["cancelled"]+=1
                    continue
                # A provider can rate-limit one worker while several same-league
                # Game Center jobs are already queued. Re-check the circuit here so
                # those queued jobs are cancelled before they can amplify the 429.
                if blocked:
                    if not task.future.done(): task.future.cancel()
                    with self._lock:
                        self._stats["cancelled"]+=1; self._stats["circuitRejected"]+=1
                    continue
                if task.future.set_running_or_notify_cancel():
                    run_started=time.time()
                    with self._lock:
                        self._active[worker_name]={"key":task.key,"priority":priority,"startedAt":run_started,"waitSeconds":max(0.0,run_started-task.submitted_at)}
                        self._stats["executed"]+=1; self._stats["waitSeconds"]+=max(0.0,run_started-task.submitted_at)
                    try:
                        task.future.set_result(task.fn(*task.args,**task.kwargs))
                        with self._lock:self._stats["completed"]+=1
                    except BaseException as exc:
                        task.future.set_exception(exc)
                        with self._lock:self._stats["errors"]+=1
                        self._record_error(task,exc)
            finally:
                with self._lock:
                    if run_started:self._stats["runSeconds"]+=max(0.0,time.time()-run_started)
                    self._active.pop(worker_name,None)
                    latest=self._latest.get(task.key)
                    if latest and latest["generation"]==task.generation: self._latest.pop(task.key,None)
                self._q.task_done()

    def snapshot(self):
        now=time.time()
        with self._lock:
            rows=[{"key":k,"priority":v["priority"],"done":v["future"].done(),"ageSeconds":round(max(0,now-float(v.get('submittedAt') or now)),2)} for k,v in self._latest.items()]
            active=[{**v,"worker":name,"runSeconds":round(max(0,now-float(v.get('startedAt') or now)),2)} for name,v in self._active.items()]
            stats=dict(self._stats); error_categories=dict(self._error_categories); recent_errors=list(self._recent_errors[-12:])
            circuits={k:round(max(0.0,float(v)-now),1) for k,v in self._circuits.items() if float(v)>now}
            self._circuits={k:v for k,v in self._circuits.items() if float(v)>now}
        for k in ("waitSeconds","runSeconds"):stats[k]=round(float(stats.get(k) or 0),3)
        stats["errorCategories"]=error_categories
        return {"queued":self._q.qsize(),"activeOrQueued":len(rows),"active":active,"jobs":rows[:30],"stats":stats,"recentErrors":recent_errors,"circuits":circuits,"threadCount":len(self._threads),"threadsAlive":sum(1 for t in self._threads if t.is_alive())}

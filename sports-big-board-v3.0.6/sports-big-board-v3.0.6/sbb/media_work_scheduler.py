"""Priority scheduler for background media work.

Foreground /api/media streams never enter this queue; they retain absolute network
priority. Background jobs are ordered by explicit user-visible importance.
"""
from dataclasses import dataclass, field
from queue import PriorityQueue
from threading import Thread, Lock
from concurrent.futures import Future
import itertools

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

class MediaWorkScheduler:
    def __init__(self, workers=4, name="sbb-media-work"):
        self._q=PriorityQueue(); self._counter=itertools.count(); self._lock=Lock(); self._latest={}; self._threads=[]
        for i in range(max(1,int(workers))):
            t=Thread(target=self._worker,name=f"{name}-{i+1}",daemon=True); t.start(); self._threads.append(t)

    def submit(self,key,priority,fn,*args,**kwargs):
        key=str(key); priority=int(priority)
        fut=Future()
        with self._lock:
            gen=int(self._latest.get(key,{}).get("generation",0))+1
            prior=self._latest.get(key)
            # If an equal/higher-priority queued job already represents this key,
            # reuse it instead of creating duplicate upstream work.
            if prior and not prior["future"].done() and int(prior["priority"])>=priority:
                return prior["future"]
            self._latest[key]={"generation":gen,"priority":priority,"future":fut}
        self._q.put(_Task(sort_key=(-priority,next(self._counter)),key=key,generation=gen,fn=fn,args=args,kwargs=kwargs,future=fut))
        return fut

    def _worker(self):
        while True:
            task=self._q.get()
            try:
                with self._lock:
                    latest=self._latest.get(task.key)
                if not latest or latest["generation"]!=task.generation:
                    if not task.future.done(): task.future.cancel()
                    continue
                if task.future.set_running_or_notify_cancel():
                    try: task.future.set_result(task.fn(*task.args,**task.kwargs))
                    except BaseException as exc: task.future.set_exception(exc)
            finally:
                with self._lock:
                    latest=self._latest.get(task.key)
                    if latest and latest["generation"]==task.generation: self._latest.pop(task.key,None)
                self._q.task_done()

    def snapshot(self):
        with self._lock:
            rows=[{"key":k,"priority":v["priority"],"done":v["future"].done()} for k,v in self._latest.items()]
        return {"queued":self._q.qsize(),"activeOrQueued":len(rows),"jobs":rows[:30]}

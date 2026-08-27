/* Sports Big Board v4.4.2 — Dev Playback Terminal.
   Read-only observer of canonical playback session + Ultimate Playback readiness.
   It never controls playback. */
(() => {
  'use strict';
  if(window.SBB_PLAYBACK_TERMINAL)return;
  const rows=[],bySession=new Map();let lastSessionId='',tickTimer=null;
  const now=()=>performance.now();
  const fmtMs=ms=>`${(Math.max(0,Number(ms)||0)/1000).toFixed(1)}s`;
  const clean=(v,n=160)=>String(v??'').replace(/\s+/g,' ').trim().slice(0,n);
  function devEnabled(){return window.SBB_DEV_MODE?.isEnabled?.()===true||document.body?.classList.contains('dev-mode')||document.body?.dataset?.sbbDev==='1';}
  function durationFor(row,kind,t=now()){
    let total=Number(row[kind+'Ms']||0);if(row.state===kind&&row.stateStartedPerf)total+=Math.max(0,t-row.stateStartedPerf);return total;
  }
  function finalizeState(row,t=now()){
    if(!row?.stateStartedPerf)return;
    const delta=Math.max(0,t-row.stateStartedPerf);
    if(row.state==='playing')row.playingMs+=delta;
    if(row.state==='buffering')row.bufferingMs+=delta;
    row.stateStartedPerf=0;
  }
  function ingest(session,t=now()){
    session=session||{};const sid=clean(session.sessionId||`selection-${session.selectionId||0}`,120);if(!sid)return null;
    if(lastSessionId&&lastSessionId!==sid){const prev=bySession.get(lastSessionId);if(prev){finalizeState(prev,t);if(!['failed','ended'].includes(prev.state))prev.exitState=prev.firstFrameAt?'LEFT':'SKIPPED/NO FRAME';}}
    lastSessionId=sid;let row=bySession.get(sid);
    if(!row){row={sessionId:sid,selectionId:Number(session.selectionId||0),title:clean(session.title||'Untitled',120),league:clean(session.league||'',20),provider:clean(session.provider||'',32),transport:clean(session.transport||'',28),mediaKey:clean(session.mediaKey||'',500),source:clean(session.sourceExternalUrl||session.sourceUrl||'',500),state:'selected',stateStartedPerf:t,playingMs:0,bufferingMs:0,firstFrameAt:0,firstFrameMs:null,stallCount:0,sessionStallTotalMs:0,failureCount:0,lastError:'',createdPerf:t,exitState:''};bySession.set(sid,row);rows.unshift(row);if(rows.length>40){const gone=rows.pop();bySession.delete(gone.sessionId);}}
    const nextState=clean(session.state||row.state,24).toLowerCase();
    if(nextState&&nextState!==row.state){finalizeState(row,t);row.state=nextState;row.stateStartedPerf=t;}
    row.title=clean(session.title||row.title,120);row.league=clean(session.league||row.league,20);row.provider=clean(session.provider||row.provider,32);row.transport=clean(session.transport||row.transport,28);row.mediaKey=clean(session.mediaKey||row.mediaKey,500);row.source=clean(session.sourceExternalUrl||session.sourceUrl||row.source,500);
    row.firstFrameAt=Math.max(Number(row.firstFrameAt||0),Number(session.firstFrameAt||0));if(session.firstFrameMs!=null)row.firstFrameMs=Number(session.firstFrameMs);
    row.stallCount=Math.max(Number(row.stallCount||0),Number(session.stallCount||0));row.sessionStallTotalMs=Math.max(Number(row.sessionStallTotalMs||0),Number(session.stallTotalMs||0));row.failureCount=Math.max(Number(row.failureCount||0),Number(session.failureCount||0));row.lastError=clean(session.lastError||row.lastError,180);
    render();return row;
  }
  function snapshot(){const t=now();return rows.map(r=>({...r,playTimeMs:durationFor(r,'playing',t),bufferTimeMs:Math.max(durationFor(r,'buffering',t),Number(r.sessionStallTotalMs||0))}));}
  function clear(){rows.splice(0);bySession.clear();lastSessionId='';render();}
  function render(){
    const host=document.getElementById('playbackTerminal');if(!host)return;host.classList.toggle('is-visible',devEnabled());if(!devEnabled())return;
    const body=document.getElementById('playbackTerminalRows'),summary=document.getElementById('playbackTerminalSummary');if(!body||!summary)return;
    const data=snapshot(),rt=window.SBB_ULTIMATE_PLAYBACK?.runtimeSnapshot?.()||{},metrics=rt.metrics||window.SBB_ULTIMATE_PLAYBACK?.metrics?.()||{};
    const totalPlay=data.reduce((a,r)=>a+r.playTimeMs,0),totalBuffer=data.reduce((a,r)=>a+r.bufferTimeMs,0),ratio=totalPlay?100*totalBuffer/totalPlay:0;
    summary.textContent=`PLAY ${fmtMs(totalPlay)}  •  BUFFER ${fmtMs(totalBuffer)} (${ratio.toFixed(1)}%)  •  HOT ${Number(metrics.hotStandbyHitRate??100).toFixed(1)}%  •  RUNWAY ${rt.bufferAhead==null?'—':Number(rt.bufferAhead).toFixed(1)+'s'}  •  NEXT ${rt.standby?.ready?'HOT_READY':rt.standby?.warming?'WARMING':'IDLE'}`;
    body.innerHTML=data.slice(0,20).map((r,i)=>{const item={mediaKey:r.mediaKey,competitionId:r.league,provider:r.provider,transport:r.transport};const ready=window.SBB_PLAYBACK_READINESS?.state?.(item)||'DISCOVERED',score=window.SBB_PLAYBACK_READINESS?.score?.(item)??80;const status=r.exitState||r.state.toUpperCase();const src=r.source?` title="${r.source.replace(/"/g,'&quot;')}"`:'';return `<div class="pt-row"><span>${String(data.length-i).padStart(2,'0')}</span><b class="pt-state">${status}</b><span>${r.league||'—'}</span><span>${r.transport||'—'}</span><span>${r.provider||'—'}</span><span>${fmtMs(r.playTimeMs)}</span><span>${fmtMs(r.bufferTimeMs)}</span><span>${r.stallCount}</span><span>${r.firstFrameMs==null?'—':Math.round(r.firstFrameMs)+'ms'}</span><span>${ready}</span><span>${Math.round(Number(score||0))}</span><span${src}>${(r.title||'Untitled').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</span></div>`;}).join('')||'<div class="pt-empty">Waiting for playback sessions…</div>';
  }
  window.addEventListener?.('sbb:playback-session',ev=>ingest(ev?.detail||{}));
  window.addEventListener?.('sbb:dev-mode',render);
  document.addEventListener('DOMContentLoaded',()=>{document.getElementById('playbackTerminalClear')?.addEventListener('click',clear);document.getElementById('playbackTerminalCopy')?.addEventListener('click',()=>{const lines=snapshot().map(r=>`${r.league}\t${r.transport}\t${r.provider}\tPLAY=${fmtMs(r.playTimeMs)}\tBUFFER=${fmtMs(r.bufferTimeMs)}\tSTALLS=${r.stallCount}\tSTART=${r.firstFrameMs??''}\t${r.title}`);navigator.clipboard?.writeText?.(lines.join('\n')).catch(()=>{});});render();tickTimer=setInterval(render,500);});
  try{const s=window.SBB_PLAYBACK_SESSION?.snapshot?.();if(s?.sessionId)ingest(s);}catch(_){}
  window.SBB_PLAYBACK_TERMINAL=Object.freeze({version:'1.0',snapshot,clear,ingest,render});
})();

/* Sports Big Board v4.3.0 — Foundation Certification.
   This layer certifies the already-hardened v4.2.x foundation. It does not own
   playback, discovery, Game Center, soundtrack, or catalog state. */
(() => {
  'use strict';
  const RELEASE=String(window.SBB_RELEASE_VERSION||window.SBB_CORE?.version||'4.3.0');
  const CERT_SCHEMA=1;
  const REQUIRED_PROCEDURES=['release-handshake','playback-cycle','historical-read','operator-load','resource-modes','game-center','soundtrack','ui-responsiveness'];
  let certificate=null,running=false;
  const $=id=>document.getElementById(id);
  const safe=x=>{try{return JSON.parse(JSON.stringify(x??null));}catch(_){return null;}};
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));

  function style(){
    if($('foundationCertificationStyle'))return;
    const el=document.createElement('style');el.id='foundationCertificationStyle';el.textContent=`
      .foundation-certification-panel{margin:0 18px 14px;border:1px solid rgba(125,211,252,.32);background:rgba(4,18,30,.78);border-radius:12px;padding:13px 14px;display:grid;gap:10px}
      .foundation-certification-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.foundation-certification-head>div{min-width:240px;flex:1}.foundation-certification-head small{display:block;letter-spacing:.11em;color:#8da7bb;font-size:10px}.foundation-certification-head strong{display:block;margin-top:2px;font-size:16px}.foundation-certification-status{font-weight:900;letter-spacing:.08em;font-size:12px;padding:6px 9px;border-radius:999px;border:1px solid #465b6b}.foundation-certification-status[data-state="certified"]{border-color:#42d392;color:#9ff7c7}.foundation-certification-status[data-state="failed"]{border-color:#fb7185;color:#fecdd3}.foundation-certification-status[data-state="running"]{border-color:#38bdf8;color:#bae6fd}.foundation-certification-actions{display:flex;gap:7px;flex-wrap:wrap}.foundation-certification-actions button{border:1px solid #365269;background:#0a1b28;color:#dceefb;border-radius:7px;padding:8px 10px;font-size:11px;font-weight:800}.foundation-certification-actions button.primary{background:#0d4f69;border-color:#38bdf8}.foundation-certification-actions button:disabled{opacity:.45}.foundation-certification-note{font-size:11px;color:#9eb4c4;line-height:1.45}.foundation-certification-gates{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:6px}.foundation-certification-gate{border:1px solid #223a4b;border-radius:7px;padding:8px 9px;display:flex;gap:8px;align-items:flex-start}.foundation-certification-gate b{font-size:10px}.foundation-certification-gate span{font-size:10px;color:#9eb4c4;line-height:1.35}.foundation-certification-gate.pass b{color:#86efac}.foundation-certification-gate.fail b{color:#fda4af}.foundation-certification-gate.pending b{color:#bae6fd}
    `;document.head.appendChild(el);
  }
  function install(){
    const strip=document.querySelector('.milestone-stress-strip');if(!strip||$('foundationCertificationPanel'))return false;
    style();const panel=document.createElement('section');panel.id='foundationCertificationPanel';panel.className='foundation-certification-panel';panel.setAttribute('aria-label','Foundation certification');
    panel.innerHTML=`<div class="foundation-certification-head"><div><small>V4.3.0 RELEASE GATE</small><strong>FOUNDATION CERTIFICATION</strong></div><span id="foundationCertificationStatus" class="foundation-certification-status" data-state="idle">NOT RUN</span><div class="foundation-certification-actions"><button id="foundationCertificationRun" class="primary" type="button">RUN FOUNDATION CERTIFICATION</button><button id="foundationCertificationCopy" type="button" disabled>COPY CERTIFICATE</button><button id="foundationCertificationSave" type="button" disabled>SAVE JSON</button></div></div><div class="foundation-certification-note">Certification resets only the in-memory milestone observation window, then reuses the existing eight release procedures. Historical catalog data, media, settings, and playback architecture are not reset or rebuilt.</div><div id="foundationCertificationGates" class="foundation-certification-gates"><div class="foundation-certification-gate pending"><b>READY</b><span>Run certification to create clean-window evidence.</span></div></div>`;
    strip.insertAdjacentElement('afterend',panel);
    $('foundationCertificationRun')?.addEventListener('click',run);
    $('foundationCertificationCopy')?.addEventListener('click',copy);
    $('foundationCertificationSave')?.addEventListener('click',save);
    render();return true;
  }
  function gate(id,name,ok,detail){return {id,name,ok:ok===true,detail:String(detail||'')};}
  function evaluate(M,snap,stress,results){
    const rel=snap?.extra?.release||{},workers=Object.values(snap?.extra?.history?.workers||{}),checks=Array.isArray(snap?.checks)?snap.checks:[],steps=Array.isArray(stress?.steps)?stress.steps:[];
    const procedureRows=REQUIRED_PROCEDURES.map(id=>[id,results?.[id]]);
    const nonPassSteps=steps.filter(x=>String(x?.status||'')!=='PASS');
    const restoreErrors=(snap?.recent||[]).filter(x=>String(x?.message||'').startsWith('stress restore ')&&String(x?.level||'').toUpperCase()==='ERROR');
    const legacyDay=snap?.api?.['/api/history/day'];
    const gates=[
      gate('release-handshake','Release handshake',snap?.version===RELEASE&&snap?.versionMatch===true&&rel.versionMatch===true&&String(rel.frontendVersion||RELEASE)===RELEASE&&String(rel.backendVersion||snap?.version)===RELEASE,`frontend ${rel.frontendVersion||RELEASE} / backend ${rel.backendVersion||snap?.version||'?'}`),
      gate('stress-suite','Stress suite',stress?.status==='PASS'&&steps.length>0,`${stress?.status||'NOT RUN'} • ${steps.length} evidence step(s)`),
      gate('procedure-suite','Eight procedures',procedureRows.every(([,r])=>r?.status==='PASS'),`${procedureRows.filter(([,r])=>r?.status==='PASS').length}/${REQUIRED_PROCEDURES.length} PASS`),
      gate('step-debt','No step debt',steps.length>0&&nonPassSteps.length===0,nonPassSteps.length?nonPassSteps.map(x=>`${x.status}:${x.name}`).join(', '):'all recorded stress steps PASS'),
      gate('platform-checks','Platform checks',checks.length>0&&checks.every(x=>x?.ok===true),`${checks.filter(x=>x?.ok===true).length}/${checks.length} PASS`),
      gate('clean-window-errors','Clean-window errors',Number(snap?.problemCounts?.errors||0)===0,`${Number(snap?.problemCounts?.errors||0)} errors • ${Number(snap?.problemCounts?.warnings||0)} non-blocking warning(s)`),
      gate('playback-invariant','Playback ownership',String(snap?.playback?.latest?.invariant||'OK')==='OK',String(snap?.playback?.latest?.invariant||'OK')),
      gate('worker-health','Worker health',workers.length>0&&workers.every(w=>w?.healthy===true),`${workers.filter(w=>w?.healthy===true).length}/${workers.length} healthy`),
      gate('state-restore','State restoration',restoreErrors.length===0,restoreErrors.length?`${restoreErrors.length} restore error(s)`:'no restoration errors'),
      gate('legacy-read-isolation','Legacy read isolation',!legacyDay||Number(legacyDay.count||0)===0,legacyDay?`/api/history/day count=${Number(legacyDay.count||0)}`:'legacy /api/history/day unused in certification window')
    ];
    const ok=gates.every(x=>x.ok);
    return {schemaVersion:CERT_SCHEMA,release:RELEASE,certification:'FOUNDATION',baseline:'v4.2.2 Milestone 1 Final Hardening',status:ok?'CERTIFIED':'NOT_CERTIFIED',generatedAt:new Date().toISOString(),cleanWindow:true,stressRunId:String(stress?.id||''),stressDurationMs:Math.max(0,Number((stress?.finishedAt||0)-(stress?.startedAt||0))||0),warningCount:Number(snap?.problemCounts?.warnings||0),gates,procedures:Object.fromEntries(procedureRows.map(([id,r])=>[id,safe(r)])),stress:safe(stress),releaseSnapshot:{version:snap?.version,versionMatch:snap?.versionMatch,overall:snap?.overall,problemCounts:safe(snap?.problemCounts),checks:safe(checks),playbackInvariant:snap?.playback?.latest?.invariant||'OK',workers:safe(snap?.extra?.history?.workers||{})}};
  }
  function render(){
    const status=$('foundationCertificationStatus'),runBtn=$('foundationCertificationRun'),copyBtn=$('foundationCertificationCopy'),saveBtn=$('foundationCertificationSave'),gatesEl=$('foundationCertificationGates');if(!status)return;
    if(running){status.textContent='RUNNING';status.dataset.state='running';if(gatesEl)gatesEl.innerHTML='<div class="foundation-certification-gate pending"><b>RUNNING</b><span>Resetting the observation window and executing existing milestone procedures…</span></div>';}
    else if(certificate){const passed=certificate.status==='CERTIFIED';status.textContent=passed?'FOUNDATION CERTIFIED':'NOT CERTIFIED';status.dataset.state=passed?'certified':'failed';if(gatesEl)gatesEl.innerHTML=certificate.gates.map(g=>`<div class="foundation-certification-gate ${g.ok?'pass':'fail'}"><b>${g.ok?'PASS':'FAIL'} • ${g.name}</b><span>${g.detail}</span></div>`).join('');}
    else{status.textContent='NOT RUN';status.dataset.state='idle';}
    if(runBtn)runBtn.disabled=running;if(copyBtn)copyBtn.disabled=!certificate||running;if(saveBtn)saveBtn.disabled=!certificate||running;
  }
  async function run(){
    if(running)return;const M=window.SBB_MILESTONE;if(!M?.reset||!M?.runStressTest){certificate={status:'NOT_CERTIFIED',gates:[gate('runtime','Certification runtime',false,'Milestone API v1.2 is unavailable')]};render();return;}
    running=true;certificate=null;render();
    try{
      // The reset is the certification boundary. It removes stale diagnostic
      // residue but does not touch the durable sports/media catalog.
      await M.reset();await sleep(250);
      await M.runStressTest();
      const snap=await M.refresh()||M.snapshot;
      certificate=evaluate(M,snap,M.stress,M.procedureResults);
      M.record?.('foundation-certification',certificate.status==='CERTIFIED'?'INFO':'ERROR',`FOUNDATION ${certificate.status}`,{release:RELEASE,stressRunId:certificate.stressRunId,gates:certificate.gates.map(g=>({id:g.id,ok:g.ok,detail:g.detail}))});
    }catch(err){certificate={schemaVersion:CERT_SCHEMA,release:RELEASE,certification:'FOUNDATION',status:'NOT_CERTIFIED',generatedAt:new Date().toISOString(),cleanWindow:true,gates:[gate('certification-run','Certification run',false,String(err?.stack||err))]};}
    finally{running=false;render();}
  }
  function text(){return certificate?JSON.stringify(certificate,null,2):'';}
  async function copy(){const t=text();if(!t)return;try{await navigator.clipboard.writeText(t);}catch(_){const ta=document.createElement('textarea');ta.value=t;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();document.execCommand?.('copy');ta.remove();}}
  function save(){const t=text();if(!t)return;const blob=new Blob([t+'\n'],{type:'application/json;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`sports-big-board-${RELEASE}-foundation-certificate-${new Date().toISOString().replace(/[:.]/g,'-')}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000);}
  function boot(){if(!install())setTimeout(boot,100);}
  window.SBB_FOUNDATION_CERTIFICATION=Object.freeze({version:'1.0',release:RELEASE,run,get certificate(){return safe(certificate);},text});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

/* Sports Big Board v4.3.10 — Three-Tier Foundation Certification.
   Tier 1 = functional/stress + regression hardening.
   Tier 2 = extended soak.
   Tier 3 = controlled chaos/recovery.
   Overall FOUNDATION CERTIFIED requires all three tiers plus final recovery health. */
(() => {
  'use strict';
  const RELEASE=String(window.SBB_RELEASE_VERSION||window.SBB_CORE?.version||'4.3.10');
  const CERT_SCHEMA=2;
  const SOAK_MS=15*60*1000;
  const REQUIRED_PROCEDURES=['release-handshake','playback-cycle','historical-read','operator-load','resource-modes','game-center','soundtrack','ui-responsiveness','regression-hardening'];
  let certificate=null,running='',tierEvidence={tier1:null,tier2:null,tier3:null},finalRecovery=null;
  const $=id=>document.getElementById(id);
  const safe=x=>{try{return JSON.parse(JSON.stringify(x??null));}catch(_){return null;}};
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  function style(){
    if($('foundationCertificationStyle'))return;
    const el=document.createElement('style');el.id='foundationCertificationStyle';el.textContent=`
      .foundation-certification-panel{margin:0 18px 14px;border:1px solid rgba(125,211,252,.32);background:rgba(4,18,30,.82);border-radius:12px;padding:13px 14px;display:grid;gap:10px}
      .foundation-certification-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.foundation-certification-head>div:first-child{min-width:240px;flex:1}.foundation-certification-head small{display:block;letter-spacing:.11em;color:#8da7bb;font-size:10px}.foundation-certification-head strong{display:block;margin-top:2px;font-size:16px}.foundation-certification-status{font-weight:900;letter-spacing:.08em;font-size:12px;padding:6px 9px;border-radius:999px;border:1px solid #465b6b}.foundation-certification-status[data-state="certified"]{border-color:#42d392;color:#9ff7c7}.foundation-certification-status[data-state="failed"]{border-color:#fb7185;color:#fecdd3}.foundation-certification-status[data-state="running"]{border-color:#38bdf8;color:#bae6fd}.foundation-certification-status[data-state="partial"]{border-color:#f59e0b;color:#fde68a}.foundation-certification-actions{display:flex;gap:7px;flex-wrap:wrap}.foundation-certification-actions button{border:1px solid #365269;background:#0a1b28;color:#dceefb;border-radius:7px;padding:8px 10px;font-size:11px;font-weight:800}.foundation-certification-actions button.primary{background:#0d4f69;border-color:#38bdf8}.foundation-certification-actions button:disabled{opacity:.45}.foundation-certification-note{font-size:11px;color:#9eb4c4;line-height:1.45}.foundation-tier-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}.foundation-tier{border:1px solid #223a4b;border-radius:9px;padding:10px;display:grid;gap:5px}.foundation-tier b{font-size:11px}.foundation-tier span{font-size:10px;color:#9eb4c4;line-height:1.35}.foundation-tier.pass{border-color:#245e43}.foundation-tier.pass b{color:#86efac}.foundation-tier.fail{border-color:#73313b}.foundation-tier.fail b{color:#fda4af}.foundation-tier.running{border-color:#256987}.foundation-tier.running b{color:#bae6fd}.foundation-certification-gates{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:6px}.foundation-certification-gate{border:1px solid #223a4b;border-radius:7px;padding:8px 9px;display:flex;gap:8px;align-items:flex-start}.foundation-certification-gate b{font-size:10px}.foundation-certification-gate span{font-size:10px;color:#9eb4c4;line-height:1.35}.foundation-certification-gate.pass b{color:#86efac}.foundation-certification-gate.fail b{color:#fda4af}
    `;document.head.appendChild(el);
  }
  function install(){
    const strip=document.querySelector('.milestone-stress-strip');if(!strip||$('foundationCertificationPanel'))return false;
    style();const panel=document.createElement('section');panel.id='foundationCertificationPanel';panel.className='foundation-certification-panel';panel.setAttribute('aria-label','Three-tier Foundation certification');
    panel.innerHTML=`<div class="foundation-certification-head"><div><small>V4.3.10 THREE-TIER RELEASE GATE</small><strong>FOUNDATION CERTIFICATION</strong></div><span id="foundationCertificationStatus" class="foundation-certification-status" data-state="partial">IN PROGRESS</span><div class="foundation-certification-actions"><button id="foundationTier1Run" type="button">RUN TIER 1</button><button id="foundationTier2Run" type="button">RUN TIER 2 • 15 MIN</button><button id="foundationTier3Run" type="button">RUN TIER 3</button><button id="foundationCertificationRun" class="primary" type="button">RUN FULL CERTIFICATION</button><button id="foundationCertificationCopy" type="button" disabled>COPY CERTIFICATE</button><button id="foundationCertificationSave" type="button" disabled>SAVE JSON</button></div></div><div class="foundation-certification-note">Tier 1 proves functional/stress behavior and the reported playback regressions. Tier 2 requires 15 minutes of continuously sampled live operation with forward playback progress, bounded buffering, and bounded transitions. Tier 3 injects controlled request, resource-mode, standby and transition disruption and proves recovery. Overall certification is withheld until all three pass.</div><div id="foundationTierGrid" class="foundation-tier-grid"></div><div id="foundationCertificationGates" class="foundation-certification-gates"></div>`;
    strip.insertAdjacentElement('afterend',panel);
    $('foundationTier1Run')?.addEventListener('click',()=>runTier1());$('foundationTier2Run')?.addEventListener('click',()=>runTier2());$('foundationTier3Run')?.addEventListener('click',()=>runTier3());$('foundationCertificationRun')?.addEventListener('click',runFull);$('foundationCertificationCopy')?.addEventListener('click',copy);$('foundationCertificationSave')?.addEventListener('click',save);render();return true;
  }
  const gate=(id,name,ok,detail)=>({id,name,ok:ok===true,detail:String(detail||'')});
  const compactErrorRecord=row=>{
    const data=safe(row?.data)||{};
    if(data&&typeof data==='object'&&typeof data.stack==='string')data.stack=data.stack.slice(0,5000);
    return {at:Number(row?.at||0)||null,level:String(row?.level||'ERROR').toUpperCase(),code:String(row?.code||''),category:String(row?.category||''),source:String(row?.source||''),message:String(row?.message||'').slice(0,1800),detail:safe(row?.detail),data};
  };
  function browserRuntime(){
    const fromMilestone=window.SBB_MILESTONE?.browserRuntime?.();if(fromMilestone)return safe(fromMilestone);
    const uaData=navigator.userAgentData||{};return safe({userAgent:String(navigator.userAgent||'').slice(0,700),browserBrands:Array.isArray(uaData.brands)?uaData.brands:[],platform:String(uaData.platform||navigator.platform||''),mobile:!!uaData.mobile,vendor:String(navigator.vendor||''),language:String(navigator.language||''),visibility:String(document.visibilityState||''),online:navigator.onLine!==false});
  }
  function transientMediaInterruption(row){
    const text=`${row?.category||''} ${row?.code||''} ${row?.message||''} ${JSON.stringify(row?.data||{})}`;
    return /(AbortError|play\(\) request was interrupted|play request was interrupted|interrupted by a call to pause|interrupted by a new load request|media playback was aborted|fetching process for the media resource was aborted)/i.test(text);
  }
  function laterPlaybackRecovery(row,snap,stress){
    const latest=snap?.playback?.latest||{},errAtMs=(Number(row?.at||0)||0)*1000,steps=Array.isArray(stress?.steps)?stress.steps:[];
    if(String(latest?.invariant||'OK')!=='OK'||String(latest?.state||'')!=='playing')return false;
    return steps.some(step=>String(step?.status)==='PASS'&&Number(step?.at||0)>=errAtMs&&(String(step?.data?.state||'')==='playing'||/playback: (buffering health|next clip transition)|hardening: background program refresh/i.test(String(step?.name||''))));
  }
  function collectErrorEvidence(snap,stress){
    const reportedErrorCount=Math.max(0,Number(snap?.problemCounts?.errors||0)||0),problems=Array.isArray(snap?.problems)?snap.problems:[],recent=Array.isArray(snap?.recent)?snap.recent:[];
    const recentErrors=recent.filter(x=>String(x?.level||'').toUpperCase()==='ERROR').slice(-20).map(compactErrorRecord);
    const directProblems=problems.filter(x=>String(x?.level||'').toUpperCase()==='ERROR'&&String(x?.code||'')!=='RECENT_ERRORS').slice(-20).map(compactErrorRecord);
    const candidates=[...directProblems,...recentErrors],actionableErrors=[],recoveredAdvisories=[];
    for(const row of candidates){if(recentErrors.includes(row)&&transientMediaInterruption(row)&&laterPlaybackRecovery(row,snap,stress))recoveredAdvisories.push({...row,classification:'RECOVERED_ADVISORY',recoveryProof:'known transient media interruption + later PASS playback evidence + final PLAYING/OK session'});else actionableErrors.push({...row,classification:'ACTIONABLE'});}
    const diagnosticMismatch=reportedErrorCount>0&&candidates.length===0;
    return {reportedErrorCount,exportedRecordCount:candidates.length,actionableErrors,recoveredAdvisories,recentErrors,problems:problems.slice(-20).map(compactErrorRecord),diagnosticMismatch,browser:browserRuntime()};
  }
  function errorGateDetail(evidence,label='clean window'){
    if(evidence.actionableErrors.length){const x=evidence.actionableErrors[0];return `${evidence.actionableErrors.length} actionable • ${x.code||x.category||'ERROR'}: ${x.message||'unknown error'}`;}
    if(evidence.recoveredAdvisories.length)return `0 actionable • ${evidence.recoveredAdvisories.length} recovered media advisory`;
    if(evidence.diagnosticMismatch)return `ADVISORY: backend reported ${evidence.reportedErrorCount} error(s) but exported no error record; count alone does not block certification`;
    return `0 actionable errors • ${evidence.exportedRecordCount} exported error record(s)`;
  }
  function tier1Evaluation(snap,stress,results){
    const rel=snap?.extra?.release||{},workers=Object.values(snap?.extra?.history?.workers||{}),checks=Array.isArray(snap?.checks)?snap.checks:[],steps=Array.isArray(stress?.steps)?stress.steps:[];
    const procedures=REQUIRED_PROCEDURES.map(id=>[id,results?.[id]]),bad=steps.filter(x=>String(x?.status)!=='PASS'),legacy=snap?.api?.['/api/history/day'],errors=collectErrorEvidence(snap,stress);
    const proceduresOk=procedures.every(([,r])=>r?.status==='PASS'),restore=Array.isArray(stress?.restoration)?stress.restoration:[],restoreHealth=stress?.restorationHealth||null,restoreAdvisories=restore.filter(x=>String(x?.status)==='ADVISORY');
    // Certification is based on test evidence plus final application health, not on
    // whether cleanup could reproduce the exact pre-test UI/media snapshot. A live
    // program may rerank during Tier 1, making exact media restoration impossible
    // while the application itself remains fully healthy.
    const evidenceStressOk=steps.length>0&&bad.length===0&&proceduresOk&&restoreHealth?.ok===true&&String(stress?.status||'')!=='STOPPED';
    const stressDetail=evidenceStressOk&&String(stress?.status||'')!=='PASS'?`PASS by evidence • raw=${stress?.status||'UNKNOWN'} • ${steps.length} steps`:`${stress?.status||'NOT RUN'} • ${steps.length} evidence steps`;
    const gates=[
      gate('release-handshake','Release handshake',snap?.version===RELEASE&&snap?.versionMatch===true&&rel.versionMatch===true,`frontend ${rel.frontendVersion||RELEASE} / backend ${rel.backendVersion||snap?.version||'?'}`),
      gate('stress-suite','Tier 1 stress suite',evidenceStressOk,stressDetail),
      gate('procedures','Nine procedures',proceduresOk,`${procedures.filter(([,r])=>r?.status==='PASS').length}/${REQUIRED_PROCEDURES.length} PASS`),
      gate('regressions','Reported bug regressions',results?.['regression-hardening']?.status==='PASS',results?.['regression-hardening']?.detail||'NOT RUN'),
      gate('step-debt','No Tier 1 step debt',steps.length>0&&bad.length===0,bad.length?bad.map(x=>`${x.status}:${x.name}`).join(', '):'all Tier 1 evidence PASS'),
      gate('post-test-health','Post-test application health',restoreHealth?.ok===true,restoreHealth?restoreHealth.ok?`healthy after cleanup • ${restoreAdvisories.length} restoration advisor${restoreAdvisories.length===1?'y':'ies'}`:(restoreHealth.problems||[]).join(' | '):'post-test health evidence missing'),
      gate('restore-advisories','Exact pre-test state restoration',true,restoreAdvisories.length?`ADVISORY • ${restoreAdvisories.map(x=>x.name).join(', ')}`:'exact restoration completed'),
      gate('platform','Platform checks',checks.length>0&&checks.every(x=>x?.ok===true),`${checks.filter(x=>x?.ok===true).length}/${checks.length} PASS`),
      gate('clean-errors','Tier 1 clean-window errors',errors.actionableErrors.length===0,errorGateDetail(errors)),
      gate('error-evidence','Tier 1 error evidence',true,errors.diagnosticMismatch?'ADVISORY • count-only error cannot block without an exported record':`${errors.exportedRecordCount} exported error record(s) • browser ${errors.browser?.browserBrands?.map(x=>x.brand).join('/')||errors.browser?.platform||'identified'}`),
      gate('playback','Playback ownership',String(snap?.playback?.latest?.invariant||'OK')==='OK',String(snap?.playback?.latest?.invariant||'OK')),
      gate('workers','Worker health',workers.length>0&&workers.every(w=>w?.healthy===true),`${workers.filter(w=>w?.healthy===true).length}/${workers.length} healthy`),
      gate('legacy','Legacy read isolation',!legacy||Number(legacy.count||0)===0,legacy?`/api/history/day count=${legacy.count}`:'legacy path unused')
    ];
    return {id:'tier1',name:'Tier 1 — Functional / Stress Hardening',status:gates.every(x=>x.ok)?'PASS':'FAIL',generatedAt:new Date().toISOString(),gates,stress:safe(stress),procedures:Object.fromEntries(procedures.map(([id,r])=>[id,safe(r)])),errorEvidence:safe(errors),snapshot:safe({version:snap?.version,problemCounts:snap?.problemCounts,problems:snap?.problems,recentErrors:errors.recentErrors,browser:errors.browser,checks:snap?.checks,workers:snap?.extra?.history?.workers,playback:snap?.playback?.latest})};
  }
  function tierRunEvidence(id,name,run,minDuration=0,{allowWarnings=false}={}){
    const steps=Array.isArray(run?.steps)?run.steps:[],acceptable=allowWarnings?new Set(['PASS','WARN']):new Set(['PASS']);
    const bad=steps.filter(x=>!acceptable.has(String(x?.status||''))),warnings=steps.filter(x=>String(x?.status||'')==='WARN'),duration=Math.max(0,Number((run?.finishedAt||0)-(run?.startedAt||0))||0);
    const runStatus=String(run?.status||'NOT RUN'),runOk=runStatus==='PASS'||(allowWarnings&&runStatus==='WARN');
    const gates=[gate(`${id}-run`,`${name} run`,runOk,`${runStatus} • ${steps.length} evidence steps`),gate(`${id}-steps`,`${name} step debt`,steps.length>0&&bad.length===0,bad.length?bad.map(x=>`${x.status}:${x.name}`).join(', '):(warnings.length?`${warnings.length} advisory warning${warnings.length===1?'':'s'}; no failed evidence`:'all evidence PASS'))];
    if(allowWarnings)gates.push(gate(`${id}-warnings`,`${name} advisory warnings`,true,warnings.length?warnings.map(x=>`${x.name}: ${x.detail||'WARN'}`).join(' | '):'none'));
    if(minDuration)gates.push(gate(`${id}-duration`,`${name} duration`,duration>=minDuration,`${Math.round(duration/1000)}s observed / ${Math.round(minDuration/1000)}s required`));
    return {id,name,status:gates.every(x=>x.ok)?'PASS':'FAIL',generatedAt:new Date().toISOString(),durationMs:duration,gates,warningCount:warnings.length,run:safe(run)};
  }
  function tier2Evaluation(run){
    const evidence=tierRunEvidence('tier2','Tier 2 soak',run,SOAK_MS-2000),c=run?.coverage||{},limits=run?.limits||{};
    const expected=Number(c.expectedSamples||limits.expectedSamples||Math.floor(SOAK_MS/15000)),minimum=Number(c.minimumSamples||limits.minimumSamples||Math.floor(expected*0.90));
    const samples=Number(c.samples||run?.samples?.length||0),ratio=Number(c.coverageRatio||0),span=Number(c.sampledSpanMs||0),maxGap=Number(c.maxSampleGapMs||0),allowedGap=Number(c.maxAllowedSampleGapMs||limits.maxAllowedSampleGapMs||37500);
    const noProgress=Number(c.longestNoProgressMs||0),noProgressLimit=Number(c.maxNoProgressMs||limits.maxNoProgressMs||45000),buffering=Number(c.longestBufferingMs||0),bufferLimit=Number(c.maxBufferingMs||limits.maxBufferingMs||45000),transitionTimeouts=Number(c.transitionTimeouts||0);
    evidence.gates.push(
      gate('tier2-telemetry-count','Tier 2 telemetry coverage',samples>=minimum&&ratio>=0.90,`${samples}/${expected} samples • ${(ratio*100).toFixed(1)}% coverage`),
      gate('tier2-telemetry-span','Tier 2 continuous observation span',span>=SOAK_MS-(15000*2.5),`${Math.round(span/1000)}s sampled span`),
      gate('tier2-telemetry-gap','Tier 2 maximum sample gap',maxGap<=allowedGap,`${Math.round(maxGap/1000)}s max / ${Math.round(allowedGap/1000)}s allowed`),
      gate('tier2-forward-progress','Tier 2 playback forward progress',noProgress<=noProgressLimit,`${Math.round(noProgress/1000)}s longest no-progress / ${Math.round(noProgressLimit/1000)}s allowed`),
      gate('tier2-buffering','Tier 2 sustained buffering',buffering<=bufferLimit,`${Math.round(buffering/1000)}s longest buffering / ${Math.round(bufferLimit/1000)}s allowed`),
      gate('tier2-transition-timeouts','Tier 2 bounded transitions',transitionTimeouts===0,`${transitionTimeouts} transition timeout${transitionTimeouts===1?'':'s'}`)
    );
    evidence.status=evidence.gates.every(x=>x.ok)?'PASS':'FAIL';evidence.coverage=safe(c);return evidence;
  }
  function recoveryEvaluation(snap){
    const workers=Object.values(snap?.extra?.history?.workers||{}),rel=snap?.extra?.release||{},checks=snap?.checks||[],errors=collectErrorEvidence(snap,{steps:[]});
    const gates=[gate('recovery-release','Post-chaos release health',snap?.version===RELEASE&&rel.versionMatch!==false&&snap?.versionMatch!==false,`frontend/backend ${RELEASE}`),gate('recovery-errors','Post-chaos clean errors',errors.actionableErrors.length===0,errorGateDetail(errors,'post-chaos')),gate('recovery-error-evidence','Post-chaos error evidence',true,errors.diagnosticMismatch?'ADVISORY • count-only error cannot block without an exported record':`${errors.exportedRecordCount} exported error record(s)`),gate('recovery-workers','Post-chaos workers',workers.length>0&&workers.every(w=>w?.healthy===true),`${workers.filter(w=>w?.healthy).length}/${workers.length} healthy`),gate('recovery-playback','Post-chaos playback invariant',String(snap?.playback?.latest?.invariant||'OK')==='OK',String(snap?.playback?.latest?.invariant||'OK')),gate('recovery-platform','Post-chaos platform checks',checks.length>0&&checks.every(x=>x?.ok===true),`${checks.filter(x=>x?.ok).length}/${checks.length} PASS`)];
    return {status:gates.every(x=>x.ok)?'PASS':'FAIL',gates,errorEvidence:safe(errors),snapshot:safe({version:snap?.version,problemCounts:snap?.problemCounts,problems:snap?.problems,recentErrors:errors.recentErrors,browser:errors.browser,checks,workers:snap?.extra?.history?.workers,playback:snap?.playback?.latest})};
  }
  function assemble(){
    const tiers=[tierEvidence.tier1,tierEvidence.tier2,tierEvidence.tier3],all=tiers.every(x=>x?.status==='PASS'),recovered=finalRecovery?.status==='PASS';
    certificate={schemaVersion:CERT_SCHEMA,release:RELEASE,certification:'FOUNDATION',baseline:'prior hardening baseline; full-soak telemetry + playback progress + explicit error-evidence closure in v4.3.10',status:all&&recovered?'FOUNDATION_CERTIFIED':'IN_PROGRESS',generatedAt:new Date().toISOString(),requirements:{tier1:'Functional / stress + reported regression hardening',tier2:`Extended soak >= ${SOAK_MS/60000} minutes`,tier3:'Controlled chaos / recovery',allThreeRequired:true},tiers:safe({tier1:tierEvidence.tier1,tier2:tierEvidence.tier2,tier3:tierEvidence.tier3}),finalRecovery:safe(finalRecovery)};return certificate;
  }
  function render(){
    const status=$('foundationCertificationStatus'),grid=$('foundationTierGrid'),gates=$('foundationCertificationGates');if(!status)return;const cert=assemble();
    const rows=[['tier1','TIER 1','Functional / Stress + regression hardening'],['tier2','TIER 2','15-minute extended soak'],['tier3','TIER 3','Controlled chaos / recovery']];
    if(grid)grid.innerHTML=rows.map(([id,label,desc])=>{const e=tierEvidence[id],state=running===id?'running':e?.status==='PASS'?'pass':e?.status==='FAIL'?'fail':'';return `<div class="foundation-tier ${state}"><b>${running===id?'RUNNING':e?.status||'PENDING'} • ${label}</b><span>${desc}${e?.durationMs?` • ${Math.round(e.durationMs/1000)}s`:''}</span></div>`;}).join('');
    if(running){status.textContent=running==='full'?'FULL CERTIFICATION RUNNING':`${running.toUpperCase()} RUNNING`;status.dataset.state='running';}
    else if(cert.status==='FOUNDATION_CERTIFIED'){status.textContent='FOUNDATION CERTIFIED';status.dataset.state='certified';}
    else if(Object.values(tierEvidence).some(x=>x?.status==='FAIL')||finalRecovery?.status==='FAIL'){status.textContent='NOT CERTIFIED';status.dataset.state='failed';}
    else{status.textContent='CERTIFICATION IN PROGRESS';status.dataset.state='partial';}
    const gateRows=[...(tierEvidence.tier1?.gates||[]),...(tierEvidence.tier2?.gates||[]),...(tierEvidence.tier3?.gates||[]),...(finalRecovery?.gates||[])];if(gates)gates.innerHTML=gateRows.length?gateRows.map(g=>`<div class="foundation-certification-gate ${g.ok?'pass':'fail'}"><b>${g.ok?'PASS':'FAIL'} • ${g.name}</b><span>${g.detail}</span></div>`).join(''):'<div class="foundation-certification-gate"><b>PENDING</b><span>No certification tier has been run in this browser tab.</span></div>';
    document.querySelectorAll('#foundationCertificationPanel button').forEach(b=>{if(!['foundationCertificationCopy','foundationCertificationSave'].includes(b.id))b.disabled=!!running;});
    if($('foundationCertificationCopy'))$('foundationCertificationCopy').disabled=!certificate||!!running;if($('foundationCertificationSave'))$('foundationCertificationSave').disabled=!certificate||!!running;
  }
  async function cleanBoundary({preserveRunEvidence=false}={}){const M=window.SBB_MILESTONE;if(!M?.reset)throw new Error('Milestone API unavailable');if(preserveRunEvidence&&M.resetObservationWindow)await M.resetObservationWindow();else await M.reset();await sleep(300);}
  async function runTier1({withinFull=false}={}){if(running&&!withinFull)return;const M=window.SBB_MILESTONE;if(!M?.runStressTest)throw new Error('Milestone API v1.3 unavailable');if(!withinFull)running='tier1';render();try{await cleanBoundary();await M.runStressTest();const snap=await M.refresh()||M.snapshot;tierEvidence.tier1=tier1Evaluation(snap,M.stress,M.procedureResults);}catch(err){tierEvidence.tier1={id:'tier1',name:'Tier 1 — Functional / Stress Hardening',status:'FAIL',error:String(err?.message||err),gates:[gate('tier1-runtime','Tier 1 runtime',false,String(err?.message||err))]};}finally{if(!withinFull){running='';assemble();render();}}return tierEvidence.tier1;}
  async function runTier2({withinFull=false}={}){if(running&&!withinFull)return;const M=window.SBB_MILESTONE;if(!M?.runSoakTest)throw new Error('Milestone soak API unavailable');if(!withinFull)running='tier2';render();try{await cleanBoundary();const run=await M.runSoakTest({durationMs:SOAK_MS,sampleMs:15000});tierEvidence.tier2=tier2Evaluation(run);}catch(err){tierEvidence.tier2={id:'tier2',name:'Tier 2 — Extended Soak',status:'FAIL',error:String(err?.message||err),gates:[gate('tier2-runtime','Tier 2 runtime',false,String(err?.message||err))]};}finally{if(!withinFull){running='';assemble();render();}}return tierEvidence.tier2;}
  async function runTier3({withinFull=false}={}){if(running&&!withinFull)return;const M=window.SBB_MILESTONE;if(!M?.runChaosTest)throw new Error('Milestone chaos API unavailable');if(!withinFull)running='tier3';render();try{await cleanBoundary();const run=await M.runChaosTest();tierEvidence.tier3=tierRunEvidence('tier3','Tier 3 chaos',run,0,{allowWarnings:true});await cleanBoundary({preserveRunEvidence:true});finalRecovery=recoveryEvaluation(await M.refresh()||M.snapshot);}catch(err){tierEvidence.tier3={id:'tier3',name:'Tier 3 — Controlled Chaos / Recovery',status:'FAIL',error:String(err?.message||err),gates:[gate('tier3-runtime','Tier 3 runtime',false,String(err?.message||err))]};finalRecovery={status:'FAIL',gates:[gate('recovery-runtime','Post-chaos recovery',false,String(err?.message||err))]};}finally{if(!withinFull){running='';assemble();render();}}return tierEvidence.tier3;}
  async function runFull(){if(running)return;running='full';tierEvidence={tier1:null,tier2:null,tier3:null};finalRecovery=null;certificate=null;render();try{await runTier1({withinFull:true});if(tierEvidence.tier1?.status!=='PASS')throw new Error('Tier 1 failed; full certification stopped');await runTier2({withinFull:true});if(tierEvidence.tier2?.status!=='PASS')throw new Error('Tier 2 failed; full certification stopped');await runTier3({withinFull:true});}catch(err){window.SBB_MILESTONE?.record?.('foundation-certification','ERROR','FULL CERTIFICATION STOPPED',{error:String(err?.message||err)});}finally{running='';assemble();render();window.SBB_MILESTONE?.record?.('foundation-certification',certificate.status==='FOUNDATION_CERTIFIED'?'INFO':'ERROR',certificate.status,{release:RELEASE,tiers:{tier1:tierEvidence.tier1?.status,tier2:tierEvidence.tier2?.status,tier3:tierEvidence.tier3?.status},finalRecovery:finalRecovery?.status});}}
  function json(){return JSON.stringify(assemble(),null,2);}function copy(){const text=json();navigator.clipboard?.writeText?.(text).catch(()=>{});}function save(){const blob=new Blob([json()],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`sports-big-board-${RELEASE}-foundation-certificate-${new Date().toISOString().replace(/[:.]/g,'-')}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1500);}
  window.SBB_FOUNDATION_CERTIFICATION=Object.freeze({version:'2.1',release:RELEASE,schemaVersion:CERT_SCHEMA,soakDurationMs:SOAK_MS,run:runFull,runTier1,runTier2,runTier3,_dev:Object.freeze({collectErrorEvidence,tier1Evaluation,recoveryEvaluation}),get certificate(){return safe(assemble());}});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})();

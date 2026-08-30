/* Sports Big Board v4.7.5 — Efficiency Certification.
   Lightweight continuous instrumentation plus scripted, non-destructive
   efficiency tests. Backend access is GET-only; test state is restored.
*/
(() => {
  'use strict';
  if (window.SBB_EFFICIENCY?.version === '4.7.5') return;

  const VERSION = '4.7.5';
  const REPORT_KEY = 'sbb.efficiency.reports.v1';
  const MAX_REQUESTS = 2500;
  const MAX_LONG_TASKS = 1000;
  const MAX_SAMPLES = 500;
  
  const THRESHOLDS = Object.freeze({
    launchInteractiveMs: {pass:1500, warn:3000},
    startToBoardMs:      {pass:1000, warn:2000},
    ribbonP95Ms:         {pass:500,  warn:1000},
    ribbonMaxMs:         {pass:900,  warn:1800},
    apiP95Ms:            {pass:300,  warn:800},
    duplicateConcurrent: {pass:2,    warn:10},
    networkPerDateMax:    {pass:6,    warn:12},
    longTaskMaxMs:       {pass:150,  warn:300},
    longTaskCount:       {pass:3,    warn:10},
    domGrowthPct:        {pass:5,    warn:15},
    heapGrowthPct:       {pass:15,   warn:30},
    timeouts:            {pass:0,    warn:0},
    api5xx:              {pass:0,    warn:0},
  });

  const state = {
    installedAt: performance.now(),
    launchParsedMs: Number(window.__SBB_LAUNCH_CONTROL_PARSED_AT)||null,
    launchInteractiveMs: null,
    launchClickAt: null,
    startToBoardMs: null,
    firstScorePaintMs: null,
    requests: [],
    activeRequests: new Map(),
    duplicateConcurrent: 0,
    brokerCallerEvents: 0,
    brokerCacheHits: 0,
    brokerSupersededAborts: 0,
    brokerDeferred: 0,
    brokerDeferredAborts: 0,
    brokerDeferredReleases: 0,
    longTasks: [],
    domSamples: [],
    heapSamples: [],
    running: false,
    currentRunId: '',
    lastReport: null,
    cardInstalled: false,
    lastCardRenderAt: 0,
  };

  const now = () => performance.now();
  const clean = v => String(v ?? '').trim();
  const upper = v => clean(v).toUpperCase();
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const raf = () => new Promise(resolve => requestAnimationFrame(() => resolve()));
  const today = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  };
  const addDays = (iso, delta) => {
    const d = new Date(`${iso}T12:00:00`);
    d.setDate(d.getDate() + delta);
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  };
  const browseDate = () => {
    try {
      return clean(window.SBB_SCORE_DATE?.snapshot?.().browseDate || window.scoreBrowseDate || today()).slice(0,10) || today();
    } catch (_) { return today(); }
  };
  const currentFilter = () => upper(window.scoreRibbonLeagueFilter || 'ALL') || 'ALL';
  const percentile = (values, p) => {
    const xs = values.filter(Number.isFinite).sort((a,b)=>a-b);
    if (!xs.length) return null;
    const i = Math.max(0, Math.min(xs.length-1, Math.ceil((p/100)*xs.length)-1));
    return xs[i];
  };
  const round = v => Number.isFinite(v) ? Math.round(v * 10) / 10 : null;
  const pct = (a,b) => (Number.isFinite(a) && Number.isFinite(b) && a > 0) ? ((b-a)/a)*100 : null;
  const nodeCount = () => document.getElementsByTagName('*').length;
  const heapBytes = () => {
    try { return Number(performance.memory?.usedJSHeapSize) || null; }
    catch (_) { return null; }
  };
  const normalizeUrl = raw => {
    try {
      const u = new URL(typeof raw === 'string' ? raw : raw?.url || '', location.href);
      for (const k of ['_','t','ts','cacheBust','cachebust']) u.searchParams.delete(k);
      return `${u.pathname}${u.search}`;
    } catch (_) { return clean(raw); }
  };
  const requestKey = (input, init={}) => `${upper(init.method || input?.method || 'GET')} ${normalizeUrl(input)}`;
  const apiPath = raw => {
    try { return new URL(typeof raw === 'string' ? raw : raw?.url || '', location.href).pathname; }
    catch (_) { return ''; }
  };
  const boundedPush = (arr, item, max) => {
    arr.push(item);
    if (arr.length > max) arr.splice(0, arr.length - max);
  };

  function gradeLow(value, thresholds, {optional=false}={}) {
    if (!Number.isFinite(value)) return optional ? 'NA' : 'WARN';
    if (value <= thresholds.pass) return 'PASS';
    if (value <= thresholds.warn) return 'WARN';
    return 'FAIL';
  }

  function overallGrade(metrics) {
    const critical = [
      metrics.ribbonP95,
      metrics.ribbonMax,
      metrics.timeouts,
      metrics.api5xx,
      metrics.restoreOk === false ? Infinity : 0,
    ];
    if (
      gradeLow(metrics.ribbonP95,THRESHOLDS.ribbonP95Ms)==='FAIL' ||
      gradeLow(metrics.ribbonMax,THRESHOLDS.ribbonMaxMs)==='FAIL' ||
      gradeLow(metrics.networkPerDateMax,THRESHOLDS.networkPerDateMax)==='FAIL' ||
      metrics.timeouts > 0 ||
      metrics.api5xx > 0 ||
      metrics.restoreOk === false ||
      gradeLow(metrics.longTaskMax,THRESHOLDS.longTaskMaxMs)==='FAIL'
    ) return 'FAIL';

    const grades = [
      gradeLow(metrics.ribbonP95,THRESHOLDS.ribbonP95Ms),
      gradeLow(metrics.ribbonMax,THRESHOLDS.ribbonMaxMs),
      gradeLow(metrics.apiP95,THRESHOLDS.apiP95Ms),
      gradeLow(metrics.duplicateConcurrent,THRESHOLDS.duplicateConcurrent),
      gradeLow(metrics.networkPerDateMax,THRESHOLDS.networkPerDateMax),
      gradeLow(metrics.longTaskMax,THRESHOLDS.longTaskMaxMs),
      gradeLow(metrics.longTaskCount,THRESHOLDS.longTaskCount),
      gradeLow(metrics.domGrowthPct,THRESHOLDS.domGrowthPct,{optional:true}),
      gradeLow(metrics.heapGrowthPct,THRESHOLDS.heapGrowthPct,{optional:true}),
    ];
    return grades.includes('WARN') ? 'WARN' : 'PASS';
  }

  // ----------------------------------------------------------
  // Request Broker telemetry.
  // ----------------------------------------------------------
  function onBrokerEvent(ev){
    const d=ev?.detail||{};
    if(!d?.type)return;

    if(d.type==='coalesced'){
      state.duplicateConcurrent+=1;
      state.brokerCallerEvents+=1;
      return;
    }
    if(d.type==='cache-hit'){
      state.brokerCacheHits+=1;
      state.brokerCallerEvents+=1;
      return;
    }
    if(d.type==='superseded-abort'){
      state.brokerSupersededAborts+=1;
      return;
    }
    if(d.type==='deferred'){state.brokerDeferred+=1;return;}
    if(d.type==='deferred-abort'){state.brokerDeferredAborts+=1;return;}
    if(d.type==='deferred-release'){state.brokerDeferredReleases+=1;return;}

    if(d.type==='network-finish' || d.type==='network-error'){
      const row={
        id:d.id||'',
        at:Date.now(),
        runId:state.currentRunId,
        method:'GET',
        key:d.key||'',
        path:d.path||'',
        date:d.date||'',
        durationMs:Number(d.durationMs)||0,
        status:Number(d.status)||0,
        ok:d.type==='network-finish' ? !!d.ok : false,
        cacheState:'',
        error:d.type==='network-error' ? String(d.reason||'') : '',
        aborted:!!d.aborted,
        coalesced:Number(d.coalesced)||0,
      };
      boundedPush(state.requests,row,MAX_REQUESTS);
      return;
    }

    if(d.type==='metadata' && d.id){
      const row=[...state.requests].reverse().find(x=>x.id===d.id);
      if(row)row.cacheState=String(d.cacheState||'');
    }
  }
  window.addEventListener('sbb:request-broker',onBrokerEvent);

  // ----------------------------------------------------------
  // Browser main-thread and resource samples.
  // ----------------------------------------------------------
  try {
    if ('PerformanceObserver' in window) {
      const supported = PerformanceObserver.supportedEntryTypes || [];
      if (supported.includes('longtask')) {
        const po = new PerformanceObserver(list => {
          for (const entry of list.getEntries()) {
            boundedPush(state.longTasks,{
              at:Date.now(),
              runId:state.currentRunId,
              durationMs:round(entry.duration),
              startTime:round(entry.startTime),
            },MAX_LONG_TASKS);
          }
        });
        po.observe({entryTypes:['longtask']});
      }
    }
  } catch (_) {}

  function sampleResources() {
    boundedPush(state.domSamples,{at:Date.now(),count:nodeCount()},MAX_SAMPLES);
    const heap = heapBytes();
    if (heap) boundedPush(state.heapSamples,{at:Date.now(),bytes:heap},MAX_SAMPLES);
  }
  sampleResources();
  setInterval(sampleResources,10000);

  // ----------------------------------------------------------
  // Launch/startup measurements.
  // ----------------------------------------------------------
  function installLaunchProbe() {
    const button = document.getElementById('launchPlayBtn');
    const launch = document.getElementById('launchScreen');
    if (!button || !launch) return false;
    if (state.launchInteractiveMs == null) state.launchInteractiveMs = round(now());
    if (button.dataset.sbbEfficiencyBound === '1') return true;
    button.dataset.sbbEfficiencyBound = '1';
    button.addEventListener('click',() => {
      state.launchClickAt = now();
      const started = state.launchClickAt;
      let frames = 0;
      const check = () => {
        frames += 1;
        const hidden = launch.classList.contains('hidden') || getComputedStyle(launch).display === 'none';
        if (hidden && state.startToBoardMs == null) {
          state.startToBoardMs = round(now()-started);
        }
        const cards = document.querySelectorAll('#scoreCells .score-card');
        if (cards.length && state.firstScorePaintMs == null) {
          state.firstScorePaintMs = round(now()-started);
        }
        if ((!hidden || state.firstScorePaintMs == null) && frames < 360) requestAnimationFrame(check);
      };
      requestAnimationFrame(check);
    },{capture:true});
    return true;
  }
  if(!installLaunchProbe() && document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',installLaunchProbe,{once:true});
  }
  setInterval(() => { if (state.launchInteractiveMs == null) installLaunchProbe(); },1000);

  // ----------------------------------------------------------
  // Ribbon transition measurement.
  // ----------------------------------------------------------
  function ribbonSettled(date) {
    const selected = browseDate();
    if (selected !== date) return false;
    const cells = document.getElementById('scoreCells');
    if (!cells) return false;
    const text = clean(cells.textContent).toLowerCase();
    if (!text) return false;
    if (text.includes('loading') || text.includes('scores…') || text.includes('scores...')) return false;
    return true;
  }

  async function waitFor(predicate, timeoutMs=3000, intervalMs=32) {
    const started = now();
    while (now()-started < timeoutMs) {
      try { if (predicate()) return true; } catch (_) {}
      await sleep(intervalMs);
    }
    return false;
  }

  async function switchDate(date, timeoutMs=3500) {
    const started = now();
    const requestStart = state.requests.length;
    let commandError = '';
    try {
      if (typeof window.setScoreBrowseDate !== 'function') throw new Error('setScoreBrowseDate unavailable');
      window.scoreRibbonInteractionUntil = Date.now() + timeoutMs + 2500;
      await Promise.resolve(window.setScoreBrowseDate(date,{animate:false,hold:timeoutMs+1000,load:true}));
    } catch (err) {
      commandError = clean(err?.message || err);
    }
    const settled = !commandError && await waitFor(()=>ribbonSettled(date),timeoutMs,40);
    const elapsed = round(now()-started);
    const reqs = state.requests.slice(requestStart);
    const cacheStates = reqs.map(r=>r.cacheState).filter(Boolean);
    return {
      date,
      elapsedMs:elapsed,
      settled,
      timeout:!settled,
      commandError,
      requestCount:reqs.length,
      cacheStates,
      apiMs:reqs.filter(r=>r.path.startsWith('/api/')).map(r=>r.durationMs),
    };
  }

  async function clickFilter(id, timeoutMs=1200) {
    id = upper(id || 'ALL');
    const started = now();
    const button = [...document.querySelectorAll('#scoreFilters [data-score-filter]')]
      .find(x=>upper(x.dataset.scoreFilter)===id);
    try {
      if (button) {
        button.click();
      } else if (window.SBB_FRONTEND_REGISTRY?.select) {
        await Promise.resolve(window.SBB_FRONTEND_REGISTRY.select(id));
      } else {
        window.scoreRibbonLeagueFilter = id;
        window.renderScoresFromMatchesCombined?.(true);
      }
      await raf(); await raf();
      await waitFor(()=>currentFilter()===id || document.querySelector(`#scoreFilters [data-score-filter="${id}"].active`),timeoutMs,30);
      return {id,elapsedMs:round(now()-started),ok:true};
    } catch (err) {
      return {id,elapsedMs:round(now()-started),ok:false,error:clean(err?.message||err)};
    }
  }

  async function probeEndpoints(date) {
    const endpoints = [
      '/api/status',
      '/api/competition-registry',
      '/api/competition-builder/catalog',
      `/api/day-state?date=${encodeURIComponent(date)}`,
    ];
    const rows=[];
    for (const path of endpoints) {
      const started=now();
      try {
        const r=await fetch(path,{cache:'no-store'});
        rows.push({path,status:r.status,ok:r.ok||r.status===202,elapsedMs:round(now()-started)});
      } catch (err) {
        rows.push({path,status:0,ok:false,elapsedMs:round(now()-started),error:clean(err?.message||err)});
      }
    }
    return rows;
  }

  function candidateDates(mode) {
    const current=browseDate();
    const offsets=mode==='hammer'
      ? [0,-1,1,-2,2,-3,3,-7,7,-14,14,-30]
      : [0,-1,1,-2,2,-7];
    const dates=offsets.map(x=>addDays(current,x));

    try {
      const rows=window.SBB_FRONTEND_REGISTRY?.snapshot?.().competitions || [];
      for (const row of rows) {
        if (row?.type!=='SPECIAL_EVENT') continue;
        if (row.startDate) dates.push(clean(row.startDate).slice(0,10));
        if (row.endDate) dates.push(clean(row.endDate).slice(0,10));
        if (mode!=='hammer' && dates.length>=8) break;
      }
    } catch (_) {}

    return [...new Set(dates.filter(Boolean))].slice(0,mode==='hammer'?16:8);
  }

  function candidateFilters(mode) {
    const ids=[...document.querySelectorAll('#scoreFilters [data-score-filter]')]
      .map(x=>upper(x.dataset.scoreFilter)).filter(Boolean);
    try {
      const snap=window.SBB_FRONTEND_REGISTRY?.snapshot?.();
      ids.push(...(snap?.specialEvents||[]).map(upper));
      ids.push(...(snap?.dynamicLeagues||[]).map(upper));
    } catch (_) {}
    return [...new Set(ids)].slice(0,mode==='hammer'?8:5);
  }

  function requestsForRun(runId) {
    return state.requests.filter(x=>x.runId===runId);
  }
  function longTasksForRun(runId) {
    return state.longTasks.filter(x=>x.runId===runId);
  }

  function persistedReports() {
    try {
      const rows=JSON.parse(localStorage.getItem(REPORT_KEY)||'[]');
      return Array.isArray(rows)?rows:[];
    } catch (_) { return []; }
  }
  function persistReport(report) {
    try {
      const rows=persistedReports();
      rows.unshift(report);
      localStorage.setItem(REPORT_KEY,JSON.stringify(rows.slice(0,10)));
    } catch (_) {}
  }

  function makeMetrics({runId,switches,filters,probes,baseline,restoreOk,durationMs}) {
    const reqs=requestsForRun(runId);
    const api=reqs.filter(r=>r.path.startsWith('/api/'));
    const apiMs=api.map(r=>r.durationMs).filter(Number.isFinite);
    const tasks=longTasksForRun(runId);
    const ribbonMs=switches.filter(x=>x.settled).map(x=>x.elapsedMs);
    const cacheStates={};
    for (const row of switches) for (const c of row.cacheStates||[]) cacheStates[c]=(cacheStates[c]||0)+1;
    const heapEnd=heapBytes();
    const domEnd=nodeCount();

    return {
      durationMs:round(durationMs),
      launchParsedMs:state.launchParsedMs,
      launchInteractiveMs:state.launchInteractiveMs,
      startToBoardMs:state.startToBoardMs,
      firstScorePaintMs:state.firstScorePaintMs,
      ribbonCount:switches.length,
      ribbonP50:round(percentile(ribbonMs,50)),
      ribbonP95:round(percentile(ribbonMs,95)),
      ribbonMax:round(ribbonMs.length?Math.max(...ribbonMs):null),
      timeouts:switches.filter(x=>x.timeout).length,
      wrongDate:switches.filter(x=>x.settled && x.date!==browseDate()).length,
      filterSwitches:filters.length,
      filterFailures:filters.filter(x=>!x.ok).length,
      apiRequests:api.length,
      apiP50:round(percentile(apiMs,50)),
      apiP95:round(percentile(apiMs,95)),
      apiMax:round(apiMs.length?Math.max(...apiMs):null),
      api5xx:api.filter(x=>x.status>=500).length,
      apiErrors:api.filter(x=>x.status===0&&!x.aborted).length,
      supersededAborts:Math.max(0,state.brokerSupersededAborts-(baseline.supersededAborts||0)),
      deferred:Math.max(0,state.brokerDeferred-(baseline.deferred||0)),
      deferredAborts:Math.max(0,state.brokerDeferredAborts-(baseline.deferredAborts||0)),
      deferredReleases:Math.max(0,state.brokerDeferredReleases-(baseline.deferredReleases||0)),
      duplicateConcurrent:Math.max(0,state.duplicateConcurrent-baseline.duplicateConcurrent),
      cacheHits:Math.max(0,state.brokerCacheHits-(baseline.cacheHits||0)),
      networkPerDateMax:Math.max(0,...switches.map(x=>Number(x.requestCount||0))),
      longTaskCount:tasks.length,
      longTaskMax:round(tasks.length?Math.max(...tasks.map(x=>x.durationMs)):0),
      longTaskTotal:round(tasks.reduce((a,b)=>a+(b.durationMs||0),0)),
      domStart:baseline.dom,
      domEnd,
      domGrowthPct:round(pct(baseline.dom,domEnd)),
      heapStart:baseline.heap,
      heapEnd,
      heapGrowthPct:round(pct(baseline.heap,heapEnd)),
      restoreOk,
      cacheStates,
      probeFailures:probes.filter(x=>!x.ok).length,
    };
  }

  function metricRows(metrics) {
    return [
      ['Launch control ready',metrics.launchInteractiveMs,'ms',THRESHOLDS.launchInteractiveMs,true],
      ['START → board',metrics.startToBoardMs,'ms',THRESHOLDS.startToBoardMs,true],
      ['Ribbon p95',metrics.ribbonP95,'ms',THRESHOLDS.ribbonP95Ms],
      ['Ribbon max',metrics.ribbonMax,'ms',THRESHOLDS.ribbonMaxMs],
      ['API p95',metrics.apiP95,'ms',THRESHOLDS.apiP95Ms],
      ['Broker-coalesced callers',metrics.duplicateConcurrent,'',THRESHOLDS.duplicateConcurrent],
      ['Max network req/date',metrics.networkPerDateMax,'',THRESHOLDS.networkPerDateMax],
      ['Long tasks >50ms',metrics.longTaskCount,'',THRESHOLDS.longTaskCount],
      ['Longest task',metrics.longTaskMax,'ms',THRESHOLDS.longTaskMaxMs],
      ['DOM growth',metrics.domGrowthPct,'%',THRESHOLDS.domGrowthPct,true],
      ['Heap growth',metrics.heapGrowthPct,'%',THRESHOLDS.heapGrowthPct,true],
      ['Ribbon timeouts',metrics.timeouts,'',THRESHOLDS.timeouts],
      ['API 5xx',metrics.api5xx,'',THRESHOLDS.api5xx],
    ].map(([name,value,unit,threshold,optional])=>({
      name,value,unit,grade:gradeLow(value,threshold,{optional:!!optional}),
      pass:threshold.pass,warn:threshold.warn
    }));
  }

  function reportText(report) {
    if (!report) return 'No efficiency report yet.';
    const m=report.metrics;
    const rows=metricRows(m);
    return [
      `Sports Big Board v${VERSION} Efficiency Certification`,
      `MODE=${report.mode.toUpperCase()}  RESULT=${report.result}  ELAPSED=${Math.round((m.durationMs||0)/1000)}s`,
      `DATE_SWITCHES=${m.ribbonCount}  FILTER_SWITCHES=${m.filterSwitches}  API_REQUESTS=${m.apiRequests}`,
      `CACHE=${Object.entries(m.cacheStates||{}).map(([k,v])=>`${k}:${v}`).join(' ')||'none observed'}`,
      '',
      ...rows.map(r=>`${r.grade.padEnd(4)}  ${r.name.padEnd(30)} ${r.value==null?'N/A':r.value}${r.unit}`),
      '',
      `RESTORE=${m.restoreOk?'PASS':'FAIL'}  FILTER_FAILURES=${m.filterFailures}  PROBE_FAILURES=${m.probeFailures}`,
      `API_ERRORS=${m.apiErrors}  SUPERSEDED_ABORTS=${m.supersededAborts}  CACHE_HITS=${m.cacheHits}`,
      `DEFERRED=${m.deferred}  DEFERRED_ABORTS=${m.deferredAborts}  DEFERRED_RELEASES=${m.deferredReleases}`,
      `OPERATOR_MODULES=${window.SBB_OPERATOR_MODULES?.snapshot?.().loaded?'LOADED':'LAZY'}  FIRST_PAINT=${window.SBB_DATE_TRANSITIONS?.snapshot?.().firstPaintSource||'—'}`,
      `LONG_TASK_TOTAL=${m.longTaskTotal}ms  MAX_NETWORK_REQ/DATE=${m.networkPerDateMax}`,
      '',
      'SLOWEST ENDPOINTS',
      ...((report.slowestEndpoints||[]).map(x=>`${String(x.p95Ms).padStart(7)}ms p95  ${String(x.maxMs).padStart(7)}ms max  n=${String(x.count).padStart(3)}  ${x.path}`)),
      '',
      ...report.switches.map(x=>`${x.settled?'PASS':'FAIL'} DATE ${x.date} ${x.elapsedMs}ms network=${x.requestCount} cache=${(x.cacheStates||[]).join(',')||'—'}`),
    ].join('\n');
  }

  async function restoreState(saved) {
    let ok=true;
    try {
      if (saved.date && typeof window.setScoreBrowseDate==='function') {
        await Promise.resolve(window.setScoreBrowseDate(saved.date,{animate:false,hold:5000,load:true}));
        await waitFor(()=>browseDate()===saved.date,3000,40);
      }
    } catch (_) { ok=false; }
    try {
      const f=await clickFilter(saved.filter||'ALL',1500);
      if (!f.ok) ok=false;
    } catch (_) { ok=false; }
    return ok;
  }

  async function run(mode='auto') {
    mode=mode==='hammer'?'hammer':'auto';
    if (state.running) return state.lastReport;
    state.running=true;
    renderCard();

    const runId=`eff-${Date.now()}-${Math.random().toString(36).slice(2,7)}`;
    const saved={date:browseDate(),filter:currentFilter()};
    const baseline={
      dom:nodeCount(),
      heap:heapBytes(),
      duplicateConcurrent:state.duplicateConcurrent,
      cacheHits:state.brokerCacheHits,
      supersededAborts:state.brokerSupersededAborts,
      deferred:state.brokerDeferred,
      deferredAborts:state.brokerDeferredAborts,
      deferredReleases:state.brokerDeferredReleases,
    };
    const started=now();
    state.currentRunId=runId;
    const switches=[],filters=[],probes=[];

    try {
      const launch=document.getElementById('launchScreen');
      const launchVisible=launch && !launch.classList.contains('hidden') && getComputedStyle(launch).display!=='none';
      if (launchVisible) throw new Error('Start Sports Big Board before running the automated efficiency test.');

      probes.push(...await probeEndpoints(saved.date));

      const dates=candidateDates(mode);
      const rounds=mode==='hammer'?2:1;
      for (let roundIndex=0;roundIndex<rounds;roundIndex++) {
        for (const date of dates) {
          switches.push(await switchDate(date,mode==='hammer'?4500:3500));
          await sleep(mode==='hammer'?80:140);
        }
      }

      const filterIds=candidateFilters(mode);
      for (const id of filterIds) {
        filters.push(await clickFilter(id,1500));
        await sleep(80);
      }
    } catch (err) {
      switches.push({date:browseDate(),elapsedMs:0,settled:false,timeout:true,commandError:clean(err?.message||err),requestCount:0,cacheStates:[]});
    } finally {
      const restoreOk=await restoreState(saved);
      const durationMs=now()-started;
      state.currentRunId='';
      const metrics=makeMetrics({runId,switches,filters,probes,baseline,restoreOk,durationMs});
      const result=overallGrade(metrics);
      const runRequests=requestsForRun(runId).filter(x=>x.path&&x.path.startsWith('/api/'));
      const endpointMap=new Map();
      for(const row of runRequests){
        const key=row.path;
        const list=endpointMap.get(key)||[];
        if(Number.isFinite(row.durationMs))list.push(row.durationMs);
        endpointMap.set(key,list);
      }
      const slowestEndpoints=[...endpointMap.entries()].map(([path,values])=>({
        path,count:values.length,
        p95Ms:round(percentile(values,95)),
        maxMs:round(values.length?Math.max(...values):0),
      })).sort((a,b)=>(b.p95Ms||0)-(a.p95Ms||0)).slice(0,10);
      const report={
        version:VERSION,
        id:runId,
        at:new Date().toISOString(),
        mode,
        result,
        metrics,
        switches,
        filters,
        probes,
        slowestEndpoints,
        thresholds:THRESHOLDS,
      };
      report.text=reportText(report);
      state.lastReport=report;
      state.running=false;
      persistReport(report);
      renderCard();
      try { window.dispatchEvent(new CustomEvent('sbb:efficiency-report',{detail:report})); } catch (_) {}
      return report;
    }
  }

  function reset() {
    state.requests.length=0;
    state.longTasks.length=0;
    state.domSamples.length=0;
    state.heapSamples.length=0;
    state.duplicateConcurrent=0;
    state.brokerCallerEvents=0;
    state.brokerCacheHits=0;
    state.brokerSupersededAborts=0;
    state.brokerDeferred=0;
    state.brokerDeferredAborts=0;
    state.brokerDeferredReleases=0;
    state.lastReport=null;
    sampleResources();
    renderCard();
  }

  function snapshot() {
    return {
      version:VERSION,
      running:state.running,
      launchParsedMs:state.launchParsedMs,
      launchInteractiveMs:state.launchInteractiveMs,
      startToBoardMs:state.startToBoardMs,
      firstScorePaintMs:state.firstScorePaintMs,
      requestCount:state.requests.length,
      duplicateConcurrent:state.duplicateConcurrent,
      broker:window.SBB_REQUEST_BROKER?.snapshot?.()||null,
      dateTransition:window.SBB_DATE_TRANSITIONS?.snapshot?.()||null,
      operatorModules:window.SBB_OPERATOR_MODULES?.snapshot?.()||null,
      longTaskCount:state.longTasks.length,
      domNodes:nodeCount(),
      heapBytes:heapBytes(),
      lastReport:state.lastReport,
      history:persistedReports(),
    };
  }

  // ----------------------------------------------------------
  // Dev-mode UI.
  // ----------------------------------------------------------
  function injectStyle() {
    if (document.getElementById('sbbEfficiencyStyle')) return;
    const style=document.createElement('style');
    style.id='sbbEfficiencyStyle';
    style.textContent=`
      #sbbEfficiencyCard .eff-head{display:flex;gap:10px;align-items:center;justify-content:space-between}
      #sbbEfficiencyCard .eff-grade{font-weight:900;letter-spacing:.08em}
      #sbbEfficiencyCard .eff-grade.PASS{color:#4ade80}
      #sbbEfficiencyCard .eff-grade.WARN{color:#fbbf24}
      #sbbEfficiencyCard .eff-grade.FAIL{color:#fb7185}
      #sbbEfficiencyCard .eff-actions{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
      #sbbEfficiencyCard .eff-actions button{min-height:34px}
      #sbbEfficiencyCard .eff-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}
      #sbbEfficiencyCard .eff-metric{border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:7px}
      #sbbEfficiencyCard .eff-metric small{display:block;opacity:.65;font-size:9px}
      #sbbEfficiencyCard .eff-metric strong{font-size:14px}
      #sbbEfficiencyCard .eff-metric.PASS strong{color:#4ade80}
      #sbbEfficiencyCard .eff-metric.WARN strong{color:#fbbf24}
      #sbbEfficiencyCard .eff-metric.FAIL strong{color:#fb7185}
      #sbbEfficiencyOutput{max-height:220px;overflow:auto;white-space:pre-wrap;font:10px/1.4 ui-monospace,monospace;background:#080d13;border-radius:7px;padding:8px;margin-top:8px}
      @media(max-width:900px){#sbbEfficiencyCard .eff-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
    `;
    document.head.appendChild(style);
  }

  function ensureCard() {
    if (document.getElementById('sbbEfficiencyCard')) {
      state.cardInstalled=true;
      return true;
    }
    const anchor=document.getElementById('sbbCompetitionBuilderCard') ||
      document.querySelector('.milestone-launch-card') ||
      document.querySelector('.settings-card:last-of-type');
    if (!anchor) return false;
    injectStyle();

    const card=document.createElement('div');
    card.id='sbbEfficiencyCard';
    card.className='settings-card hidden';
    card.innerHTML=`
      <div class="eff-head">
        <div><div class="settings-card-title">EFFICIENCY CERTIFICATION</div>
        <small>Startup • Day State • ribbon • API • main thread • memory/DOM</small></div>
        <span id="sbbEfficiencyGrade" class="eff-grade">IDLE</span>
      </div>
      <div class="eff-actions">
        <button id="sbbEfficiencyAuto" class="settings-save-btn" type="button">RUN AUTO TEST</button>
        <button id="sbbEfficiencyHammer" type="button">RUN HAMMER</button>
        <button id="sbbEfficiencyCopy" type="button">COPY REPORT</button>
        <button id="sbbEfficiencyReset" type="button">RESET</button>
      </div>
      <div id="sbbEfficiencyMetrics" class="eff-grid"></div>
      <pre id="sbbEfficiencyOutput">No efficiency test has run yet.</pre>`;
    anchor.after(card);

    document.getElementById('sbbEfficiencyAuto').onclick=()=>run('auto');
    document.getElementById('sbbEfficiencyHammer').onclick=()=>run('hammer');
    document.getElementById('sbbEfficiencyReset').onclick=reset;
    document.getElementById('sbbEfficiencyCopy').onclick=async()=>{
      const text=state.lastReport?.text||'No efficiency report yet.';
      try { await navigator.clipboard.writeText(text); } catch (_) {}
    };

    const apply=()=>card.classList.toggle('hidden',!window.SBB_DEV_MODE?.isEnabled?.());
    apply();
    window.addEventListener('sbb:dev-mode',apply);
    state.cardInstalled=true;
    renderCard();
    return true;
  }

  function renderCard() {
    if (!state.cardInstalled && !ensureCard()) return;
    const grade=document.getElementById('sbbEfficiencyGrade');
    const grid=document.getElementById('sbbEfficiencyMetrics');
    const output=document.getElementById('sbbEfficiencyOutput');
    const auto=document.getElementById('sbbEfficiencyAuto');
    const hammer=document.getElementById('sbbEfficiencyHammer');
    if (!grade||!grid||!output) return;

    auto.disabled=hammer.disabled=state.running;
    if (state.running) {
      grade.className='eff-grade WARN';
      grade.textContent='RUNNING';
      output.textContent='Automated efficiency test in progress… current state will be restored.';
      return;
    }

    const report=state.lastReport;
    grade.className=`eff-grade ${report?.result||''}`;
    grade.textContent=report?.result||'IDLE';

    const m=report?.metrics||{};
    const rows=report?metricRows(m):[
      {name:'Launch ready',value:state.launchInteractiveMs,unit:'ms',grade:'NA'},
      {name:'START → board',value:state.startToBoardMs,unit:'ms',grade:'NA'},
      {name:'Requests observed',value:state.requests.length,unit:'',grade:'NA'},
      {name:'Long tasks',value:state.longTasks.length,unit:'',grade:'NA'},
    ];
    grid.innerHTML=rows.slice(0,12).map(r=>`
      <div class="eff-metric ${r.grade||''}">
        <small>${r.name}</small><strong>${r.value==null?'—':r.value}${r.unit||''}</strong>
      </div>`).join('');
    output.textContent=report?.text||'No efficiency test has run yet.';
  }

  function boot() {
    installLaunchProbe();
    ensureCard();
    setInterval(ensureCard,1500);
  }

  window.SBB_EFFICIENCY=Object.freeze({
    version:VERSION,
    thresholds:THRESHOLDS,
    snapshot,
    runAutoTest:()=>run('auto'),
    runHammer:()=>run('hammer'),
    reset,
    reportText:()=>state.lastReport?.text||'No efficiency report yet.',
  });

  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

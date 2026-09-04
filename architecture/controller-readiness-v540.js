/* Sports Big Board v5.4.3 — Controller Readiness / Interaction Architecture.
   This release deliberately does NOT poll the Gamepad API or bind controller
   buttons. It prepares one semantic interaction graph that mouse, keyboard and the
   v5.4.x controller layer can all share. Every actionable control is registered,
   assigned a stable focus identity and placed in a named region. Newly rendered
   controls are registered from child-list mutations only, so registration cannot
   create an attribute-observer feedback loop. */
(() => {
  'use strict';
  if(window.SBB_CONTROLLER_READINESS?.version==='5.4.3')return;
  const VERSION='5.4.3';
  const FALLBACK_REGION='global-utility';
  const POINTER_MOVE_THRESHOLD=10;
  const REGION_MEMORY_KEY='sports-big-board.controller-focus-memory.v1';
  const ACTIONABLE_SELECTOR=[
    'button','a[href]','input:not([type="hidden"])','select','textarea','summary',
    'video[controls]','audio[controls]','[contenteditable="true"]',
    '[role="button"]','[role="tab"]','[role="menuitem"]','[role="option"]','[role="link"]',
    '[data-sbb-action]','.score-cell','.score-card','.queue-item','.next-up-dock-card','[data-curation-index]'
  ].join(',');

  // More-specific regions must come before their broad ancestors. The final
  // global-utility region is a safety net only; audit() reports any actionable
  // control that had to use it so newly added UI cannot silently fall between
  // controller-navigation cracks.
  const REGION_SPECS=Object.freeze([
    {name:'launch',label:'Launch / startup',selectors:['#launchScreen','#localFileWarning'],entry:'#launchPlayBtn'},
    {name:'special-events',label:'Special Events menu',selectors:['#sbbSpecialEventsMenu'],entry:'#sbbSpecialEventsMenu button'},
    {name:'date-picker',label:'Date picker / calendar',selectors:['#sbbDatePopover','.sbb-date-popover','.sbb-calendar-popover','.sbb-calendar'],entry:'[aria-current="date"],.sbb-calendar-day.today,.sbb-calendar-day,button'},
    {name:'team-browse',label:'Team / player browse and focus',selectors:['#sbbBrowsePopover','#sbbCurationRibbon','#sbbEntityFocusControls'],entry:'#sbbBrowseSearch,#sbbBrowseSuggestions button,#sbbCurationCards button,#sbbFocusPlayAll'},
    {name:'milestone-console',label:'Certification console',selectors:['#milestoneConsoleModal'],entry:'#milestoneConsoleClose,#milestoneStressRun'},
    {name:'history-audit',label:'Historical database audit',selectors:['#historyAuditModal'],entry:'#historyAuditClose,#historyAuditRefresh'},
    {name:'sport-match-center',label:'Sport / special-event Match Center',selectors:['#sbbSportMatchCenter','.sbb-sport-match-center','.sbb-special-event-match-center','.sbb-smc-shell'],entry:'button,[href]'},
    {name:'league-view',label:'League View',selectors:['#leagueViewRoot','.league-view-root'],entry:'#leagueViewRefresh'},
    {name:'settings',label:'Settings',selectors:['#settingsPane'],entry:'#settingsPane button,#settingsPane input,#settingsPane select'},
    {name:'game-center',label:'Game Center',selectors:['#gameCenterPane','#gameCenterContent'],entry:'#gcSections .gc-section-tab.active,#gcSections .gc-section-tab'},
    {name:'coming-up',label:'Coming Up / queue',selectors:['#nextUpDock','.next-up-dock','#queueList','.drawer-queue-panel'],entry:'#nextUpDockGrid .next-up-dock-card,#queueList .queue-item'},
    {name:'drawer-tabs',label:'Information drawer tabs',selectors:['#infoDrawer .info-drawer-head','.info-drawer-tabs'],entry:'#infoDrawer .info-drawer-tab.active,#infoDrawer .info-drawer-tab'},
    {name:'transition-overlay',label:'Bumper / playback transition overlay',selectors:['#bumper','#videoLoadingOverlay','#searchPriorityPlaybackLock'],entry:'#bumperAction button,#bumperAction a'},
    {name:'playback-terminal',label:'Playback terminal',selectors:['#playbackTerminal'],entry:'#playbackEnduranceStart,#playbackTerminalCopy'},
    {name:'soundtrack',label:'Soundtrack controls',selectors:['#soundtrackControls','#soundtrackVolumePopover'],entry:'#soundtrackToggle'},
    {name:'player-alternates',label:'Recap alternate controls',selectors:['#recapAltButtons'],entry:'#recapAltButtons button:not(.hidden)'},
    {name:'player-transport',label:'Primary playback transport',selectors:['.player-topbar > .transport'],entry:'#playBtn'},
    {name:'player-utilities',label:'Player utility / drawer launch controls',selectors:['.utility-controls'],entry:'#gameCenterDrawerBtn'},
    {name:'player-stage',label:'Video stage',selectors:['#stage','.stage'],entry:'#playBtn'},
    {name:'now-watching',label:'Now Watching metadata',selectors:['.now-playing-copy'],entry:'#playBtn'},
    {name:'left-nav',label:'Primary left navigation',selectors:['.left-rail'],entry:'.left-rail .nav.active,.left-rail .nav'},
    {name:'date-nav',label:'Date / day navigation',selectors:['.top-date-controls','#scoreDayPager','#scoreDayIndicator','#scoreDatePicker','#scoreDayPagerRight'],entry:'#scoreDayIndicator,#topDateSelectBtn'},
    {name:'league-nav',label:'League and scope navigation',selectors:['#scoreFilters','#sbbBrowseSubnav'],entry:'#scoreFilters [data-score-filter].active,#scoreFilters [data-score-filter="ALL"],#sbbBrowseBtn'},
    {name:'global-header',label:'Global header utilities',selectors:['.top-nav-header'],entry:'#bigBoardFullscreenBtn,#topDateSelectBtn'},
    {name:'sports-ticker',label:'Sports Ticker',selectors:['.key-info-ribbon','#keyInfoTrack'],entry:'button,a[href]'},
    {name:'score-ribbon',label:'Score ribbon / curated game cards',selectors:['.score-ribbon','#scoreCells','#sbbCurationCards'],entry:'#scoreCells .score-card,#scoreCells .score-cell,#sbbCurationCards [data-curation-index]'},
    {name:'system-status',label:'Data / media system status',selectors:['.mobile-live-bar','.sport-feed-diagnostics','#coveragePipeline','.coverage-pipeline'],entry:'button,a[href]'},
    {name:'developer-tools',label:'Developer diagnostics',selectors:['#playbackDebug','.sbb-dev-global-card'],entry:'button,a[href],input,select'},
    {name:'modal',label:'Generic modal / popover',selectors:['[role="dialog"]','.modal','.popover'],entry:'button,a[href],input,select,textarea'},
    {name:FALLBACK_REGION,label:'Global utility fallback',selectors:['#app-shell','body'],entry:'#bigBoardFullscreenBtn'}
  ]);

  const REGION_GRAPH=Object.freeze({
    launch:{down:'global-header'},
    'global-header':{down:'league-nav'},
    'league-nav':{up:'global-header',down:'sports-ticker',right:'date-nav'},
    'date-nav':{up:'global-header',left:'league-nav',down:'score-ribbon'},
    'sports-ticker':{up:'league-nav',down:'score-ribbon'},
    'score-ribbon':{up:'sports-ticker',down:'player-transport'},
    'system-status':{up:'score-ribbon',down:'left-nav'},
    'left-nav':{up:'score-ribbon',right:'player-transport'},
    'now-watching':{up:'score-ribbon',down:'player-transport',left:'left-nav'},
    'player-alternates':{up:'now-watching',down:'player-transport',left:'left-nav'},
    'player-transport':{up:'now-watching',left:'left-nav',right:'player-utilities',down:'player-stage'},
    soundtrack:{left:'player-transport',right:'player-utilities'},
    'player-stage':{up:'player-transport',down:'player-utilities',right:'drawer-tabs'},
    'transition-overlay':{up:'player-transport',down:'player-utilities'},
    'player-utilities':{up:'player-stage',left:'player-transport',right:'drawer-tabs',down:'coming-up'},
    'playback-terminal':{up:'player-stage',down:'player-utilities'},
    'drawer-tabs':{left:'player-utilities',down:'game-center'},
    'game-center':{up:'drawer-tabs',left:'player-stage'},
    'sport-match-center':{up:'drawer-tabs',left:'player-stage'},
    'league-view':{up:'drawer-tabs',left:'player-stage'},
    settings:{up:'drawer-tabs',left:'player-stage'},
    'coming-up':{up:'player-utilities',left:'player-stage'},
    'team-browse':{up:'league-nav',down:'coming-up'},
    'special-events':{up:'league-nav',down:'score-ribbon'},
    'date-picker':{up:'date-nav',down:'score-ribbon'},
    'milestone-console':{},'history-audit':{},'developer-tools':{},modal:{},
    [FALLBACK_REGION]:{}
  });

  const regionByName=new Map(REGION_SPECS.map(spec=>[spec.name,spec]));
  const listeners=new Set();
  let inputOwner='pointer',ownerReason='initial',ownerChangedAt=Date.now();
  let pointerAnchor=null,controllerFocus=null,mutationObserver=null,scanQueued=false,auditTimer=null;
  let focusMemory=loadMemory();
  const registered=new WeakSet();
  const diagnostics={scans:0,registered:0,customKeyboardBridges:0,fallbackAssignments:0,lastAudit:null,lastScanAt:0};

  function clean(v){return String(v??'').trim();}
  function slug(v){return clean(v).toLowerCase().replace(/&/g,' and ').replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,84);}
  function cssEscape(v){try{return CSS.escape(String(v));}catch(_){return String(v).replace(/[^a-zA-Z0-9_-]/g,'\\$&');}}
  function loadMemory(){try{const raw=JSON.parse(sessionStorage.getItem(REGION_MEMORY_KEY)||'{}');return raw&&typeof raw==='object'?raw:{};}catch(_){return {};}}
  function saveMemory(){try{sessionStorage.setItem(REGION_MEMORY_KEY,JSON.stringify(focusMemory));}catch(_){}}
  function emitOwner(){
    document.documentElement.dataset.sbbInputOwner=inputOwner;
    const detail={owner:inputOwner,reason:ownerReason,changedAt:ownerChangedAt};
    for(const fn of [...listeners]){try{fn(detail);}catch(err){console.warn('[SBB controller-readiness] input listener failed',err);}}
    try{window.dispatchEvent(new CustomEvent('sbb:input-owner-change',{detail}));}catch(_){ }
  }
  function claimInput(owner,{reason='input'}={}){
    owner=['pointer','keyboard','controller'].includes(String(owner))?String(owner):'pointer';
    if(owner===inputOwner&&reason===ownerReason)return inputOwner;
    inputOwner=owner;ownerReason=String(reason||'input');ownerChangedAt=Date.now();
    if(owner!=='controller')clearControllerFocus({preserveMemory:true});
    emitOwner();return inputOwner;
  }
  function subscribeInput(fn){if(typeof fn!=='function')return()=>{};listeners.add(fn);try{fn({owner:inputOwner,reason:ownerReason,changedAt:ownerChangedAt});}catch(_){}return()=>listeners.delete(fn);}

  function regionRootMatches(spec,scope=document){
    const roots=[];
    for(const selector of spec.selectors){
      try{
        if(scope?.nodeType===1&&scope.matches?.(selector))roots.push(scope);
        scope?.querySelectorAll?.(selector)?.forEach?.(node=>roots.push(node));
      }catch(_){ }
    }
    return [...new Set(roots)];
  }
  function markRegionRoots(scope=document){
    for(const spec of REGION_SPECS){
      for(const root of regionRootMatches(spec,scope)){
        if(!root.dataset.sbbRegionRoot)root.dataset.sbbRegionRoot=spec.name;
        if(!root.dataset.sbbRegion)root.dataset.sbbRegion=spec.name;
      }
    }
  }
  function resolveRegion(el){
    if(!el||el.nodeType!==1)return FALLBACK_REGION;
    for(const spec of REGION_SPECS){
      for(const selector of spec.selectors){
        try{if(el.matches(selector)||el.closest(selector))return spec.name;}catch(_){ }
      }
    }
    return FALLBACK_REGION;
  }
  function accessibleToken(el){
    const dataset=el.dataset||{};
    const pairs=[
      ['scoreFilter','league'],['drawerTab','drawer'],['gcSection','game-center-tab'],
      ['browseEntity','entity'],['browseStar','favorite'],['specialCompetition','special-event'],
      ['curationIndex','curation'],['eventId','event'],['gameId','game'],['teamId','team'],
      ['action','action'],['league','league'],['date','date']
    ];
    for(const [key,prefix] of pairs){if(clean(dataset[key]))return `${prefix}:${slug(dataset[key])}`;}
    if(el.id)return `id:${slug(el.id)}`;
    const aria=clean(el.getAttribute('aria-label')||el.getAttribute('title'));
    if(aria)return `label:${slug(aria)}`;
    const txt=clean(el.textContent).replace(/\s+/g,' ').slice(0,90);
    if(txt)return `text:${slug(txt)}`;
    const type=clean(el.getAttribute('type')||el.tagName).toLowerCase();
    return `${type||'control'}`;
  }
  function uniqueFocusId(el,region){
    const base=`${region}:${accessibleToken(el)}`;
    let candidate=base,n=2;
    while(true){
      const found=document.querySelector(`[data-sbb-focus-id="${cssEscape(candidate)}"]`);
      if(!found||found===el)return candidate;
      candidate=`${base}:${n++}`;
    }
  }
  function isNativeActionable(el){return /^(BUTTON|A|INPUT|SELECT|TEXTAREA|SUMMARY|VIDEO|AUDIO)$/.test(el.tagName);}
  function needsKeyboardBridge(el){return !isNativeActionable(el)&&!el.hasAttribute('contenteditable');}
  function accessibleName(el){return clean(el.getAttribute('aria-label')||el.getAttribute('title')||el.textContent||el.getAttribute('value')||el.id);}
  function registerElement(el){
    if(!el||el.nodeType!==1||!el.matches(ACTIONABLE_SELECTOR))return false;
    const region=resolveRegion(el);
    el.dataset.sbbFocusable='1';
    el.dataset.sbbRegion=region;
    if(region===FALLBACK_REGION){el.dataset.sbbRegionFallback='1';diagnostics.fallbackAssignments++;}
    else delete el.dataset.sbbRegionFallback;
    if(!el.dataset.sbbFocusId)el.dataset.sbbFocusId=uniqueFocusId(el,region);
    if(!accessibleName(el)&&el.id)el.setAttribute('aria-label',el.id.replace(/[-_]+/g,' '));
    if(needsKeyboardBridge(el)){
      if(!el.hasAttribute('tabindex'))el.tabIndex=0;
      if(!el.hasAttribute('role'))el.setAttribute('role','button');
      if(!el.dataset.sbbKeyboardBridge){
        el.dataset.sbbKeyboardBridge='1';
        el.addEventListener('keydown',event=>{
          if(event.defaultPrevented)return;
          if(event.key==='Enter'||event.key===' '){event.preventDefault();el.click();}
        });
        diagnostics.customKeyboardBridges++;
      }
    }
    if(!registered.has(el)){registered.add(el);diagnostics.registered++;}
    return true;
  }
  function registerTree(root=document){
    diagnostics.scans++;diagnostics.lastScanAt=Date.now();
    markRegionRoots(root);
    if(root?.nodeType===1&&root.matches?.(ACTIONABLE_SELECTOR))registerElement(root);
    let nodes=[];try{nodes=[...root.querySelectorAll(ACTIONABLE_SELECTOR)];}catch(_){ }
    for(const el of nodes)registerElement(el);
    return nodes.length;
  }
  function queueRegister(nodes=[]){
    for(const node of nodes){if(node?.nodeType===1)pendingRoots.add(node);}
    if(scanQueued)return;scanQueued=true;
    const run=()=>{
      scanQueued=false;const roots=[...pendingRoots];pendingRoots.clear();
      const before=diagnostics.registered;
      for(const root of roots)registerTree(root);
      // Audit only after the semantic control set actually changes. It is debounced
      // and never runs inside the mutation callback.
      if(diagnostics.registered!==before)scheduleAudit();
    };
    if(typeof requestIdleCallback==='function')requestIdleCallback(run,{timeout:120});else requestAnimationFrame(run);
  }
  const pendingRoots=new Set();

  function hiddenByDom(el){
    if(!el||!el.isConnected||el.hidden)return true;
    if(el.closest('[hidden],.hidden,[aria-hidden="true"]'))return true;
    const style=getComputedStyle(el);if(style.display==='none'||style.visibility==='hidden'||Number(style.opacity)===0)return true;
    const r=el.getBoundingClientRect();return r.width<1||r.height<1;
  }
  function enabled(el){return !!el&&!el.disabled&&el.getAttribute('aria-disabled')!=='true';}
  function visibleFocusable(el){return enabled(el)&&!hiddenByDom(el);}
  function focusables(region=null,{visible=true,root=null}={}){
    const scope=root||document;let nodes=[];
    try{nodes=[...scope.querySelectorAll('[data-sbb-focusable="1"]')];}catch(_){return [];}
    if(region)nodes=nodes.filter(el=>el.dataset.sbbRegion===region);
    if(visible)nodes=nodes.filter(visibleFocusable);
    return nodes;
  }
  function activeModalRoot(){
    const selectors=['#milestoneConsoleModal','#historyAuditModal','#sbbBrowsePopover','#sbbSpecialEventsMenu','#sbbDatePopover','.sbb-date-popover','[role="dialog"]','.modal','.popover'];
    const candidates=[];
    for(const selector of selectors){try{document.querySelectorAll(selector).forEach(el=>{if(!hiddenByDom(el))candidates.push(el);});}catch(_){}}
    return candidates[candidates.length-1]||null;
  }
  function remember(el){
    if(!el?.dataset?.sbbFocusId)return;
    const region=el.dataset.sbbRegion||resolveRegion(el);focusMemory[region]=el.dataset.sbbFocusId;saveMemory();
  }
  function clearControllerFocus({preserveMemory=true}={}){
    if(controllerFocus){controllerFocus.removeAttribute('data-sbb-controller-focus');if(!preserveMemory)delete focusMemory[controllerFocus.dataset.sbbRegion||''];}
    controllerFocus=null;
  }
  function ensureVisible(el){
    if(!el)return false;
    try{el.scrollIntoView({block:'nearest',inline:'nearest',behavior:'auto'});}catch(_){try{el.scrollIntoView(false);}catch(__){}}
    return true;
  }
  function focusElement(el,{owner='controller',domFocus=true,scroll=true}={}){
    if(!visibleFocusable(el))return false;
    clearControllerFocus({preserveMemory:true});controllerFocus=el;el.dataset.sbbControllerFocus='1';remember(el);
    if(owner)claimInput(owner,{reason:'semantic focus'});
    if(domFocus&&typeof el.focus==='function'){try{el.focus({preventScroll:true});}catch(_){try{el.focus();}catch(__){}}}
    if(scroll)ensureVisible(el);
    return true;
  }
  function focusById(id,opts={}){const el=document.querySelector(`[data-sbb-focus-id="${cssEscape(id)}"]`);return focusElement(el,opts);}
  function preferredEntry(region){
    const spec=regionByName.get(region);if(!spec)return null;
    const remembered=focusMemory[region];if(remembered){const el=document.querySelector(`[data-sbb-focus-id="${cssEscape(remembered)}"]`);if(visibleFocusable(el))return el;}
    if(spec.entry){for(const selector of spec.entry.split(',')){try{const el=document.querySelector(selector.trim());if(visibleFocusable(el))return el;}catch(_){}}}
    return focusables(region)[0]||null;
  }
  function enterRegion(region,opts={}){return focusElement(preferredEntry(region),opts);}

  function center(rect){return {x:rect.left+rect.width/2,y:rect.top+rect.height/2};}
  function directionalScore(from,to,direction){
    const a=center(from),b=center(to),dx=b.x-a.x,dy=b.y-a.y;
    let primary=0,cross=0;
    if(direction==='right'){if(dx<=4)return Infinity;primary=dx;cross=Math.abs(dy);}
    else if(direction==='left'){if(dx>=-4)return Infinity;primary=-dx;cross=Math.abs(dy);}
    else if(direction==='down'){if(dy<=4)return Infinity;primary=dy;cross=Math.abs(dx);}
    else if(direction==='up'){if(dy>=-4)return Infinity;primary=-dy;cross=Math.abs(dx);}
    else return Infinity;
    const overlap=(direction==='left'||direction==='right')
      ? Math.max(0,Math.min(from.bottom,to.bottom)-Math.max(from.top,to.top))
      : Math.max(0,Math.min(from.right,to.right)-Math.max(from.left,to.left));
    return primary+(cross*2.25)+(overlap>0?0:36);
  }
  function bestDirectional(from,candidates,direction){
    if(!from)return null;const fr=from.getBoundingClientRect();let best=null,bestScore=Infinity;
    for(const el of candidates){if(el===from)continue;const score=directionalScore(fr,el.getBoundingClientRect(),direction);if(score<bestScore){best=el;bestScore=score;}}
    return best;
  }
  function currentFocus(){
    if(controllerFocus&&visibleFocusable(controllerFocus))return controllerFocus;
    const active=document.activeElement;if(active?.dataset?.sbbFocusable==='1'&&visibleFocusable(active))return active;
    const modal=activeModalRoot();return (modal?focusables(null,{root:modal})[0]:null)||preferredEntry('league-nav')||focusables()[0]||null;
  }
  function move(direction,{from=currentFocus(),focus=true}={}){
    if(!['up','down','left','right'].includes(direction))return null;
    if(!from)return null;
    const modal=activeModalRoot();
    const region=from.dataset.sbbRegion||resolveRegion(from);
    const scope=modal||document;
    let candidate=bestDirectional(from,focusables(region,{root:scope}),direction);
    if(!candidate)candidate=bestDirectional(from,focusables(null,{root:scope}),direction);
    if(!candidate&&!modal){const neighbor=REGION_GRAPH[region]?.[direction];if(neighbor)candidate=preferredEntry(neighbor);}
    if(candidate&&focus)focusElement(candidate,{owner:'controller'});
    return candidate||null;
  }
  function activate(el=currentFocus()){
    if(!visibleFocusable(el))return false;
    if(el.tagName==='SELECT'||el.tagName==='INPUT'&&['text','search','password','date','range'].includes(clean(el.type).toLowerCase())){focusElement(el,{owner:'controller'});return true;}
    try{el.click();return true;}catch(_){return false;}
  }

  function clickVisible(selector){
    let nodes=[];try{nodes=[...document.querySelectorAll(selector)];}catch(_){return false;}
    const el=nodes.find(visibleFocusable);if(!el)return false;try{el.click();return true;}catch(_){return false;}
  }
  function navigateBack(){
    // Close the deepest transient context first. This is the canonical behavior
    // future Controller-B will call; no controller binding is installed here.
    if(clickVisible('#milestoneConsoleClose'))return 'milestone-console';
    if(clickVisible('#historyAuditClose'))return 'history-audit';
    if(!hiddenByDom(document.getElementById('sbbBrowsePopover'))&&clickVisible('#sbbBrowseClose'))return 'team-browse';
    if(!hiddenByDom(document.getElementById('sbbSpecialEventsMenu'))&&clickVisible('#sbbSpecialEventsBtn'))return 'special-events';
    const dateDialog=activeModalRoot();
    if(dateDialog&&(dateDialog.matches?.('.sbb-date-popover,#sbbDatePopover,.sbb-calendar-popover')||dateDialog.querySelector?.('.sbb-calendar-day'))){
      const close=dateDialog.querySelector('[data-close],.close,[aria-label*="close" i]');if(close&&visibleFocusable(close)){close.click();return 'date-picker';}
      if(clickVisible('#topDateSelectBtn'))return 'date-picker';
    }
    if(clickVisible('#sbbFocusExit'))return 'team-focus';
    if(clickVisible('#sbbSpecialExitBtn'))return /event/i.test(clean(document.getElementById('sbbSpecialExitBtn')?.textContent))?'special-event':'league';
    const drawer=document.getElementById('infoDrawer');
    if(drawer&&!drawer.classList.contains('is-closed')&&drawer.getAttribute('aria-hidden')!=='true'&&clickVisible('#infoDrawerClose'))return 'drawer';
    const activeLeague=[...document.querySelectorAll('#scoreFilters [data-score-filter].active')].find(el=>clean(el.dataset.scoreFilter).toUpperCase()!=='ALL'&&visibleFocusable(el));
    if(activeLeague){const all=document.querySelector('#scoreFilters [data-score-filter="ALL"]');if(all&&visibleFocusable(all)){all.click();return 'league';}}
    return false;
  }


  function scheduleAudit(delay=900){
    if(auditTimer)return;
    auditTimer=setTimeout(()=>{auditTimer=null;audit({log:false});},Math.max(160,Number(delay)||900));
  }
  function audit({log=true}={}){
    registerTree(document);
    const all=[...document.querySelectorAll(ACTIONABLE_SELECTOR)];
    const uncovered=all.filter(el=>el.dataset.sbbFocusable!=='1'||!el.dataset.sbbRegion||!el.dataset.sbbFocusId);
    const fallback=all.filter(el=>el.dataset.sbbRegionFallback==='1');
    const unnamed=all.filter(el=>!accessibleName(el));
    const duplicateIds=[];const seen=new Map();
    for(const el of all){const id=clean(el.dataset.sbbFocusId);if(!id)continue;if(seen.has(id)&&seen.get(id)!==el)duplicateIds.push(id);else seen.set(id,el);}
    const regions={};for(const spec of REGION_SPECS){const roots=regionRootMatches(spec);const controls=all.filter(el=>el.dataset.sbbRegion===spec.name);regions[spec.name]={roots:roots.length,controls:controls.length,visible:controls.filter(visibleFocusable).length};}
    const result={
      version:VERSION,ok:uncovered.length===0&&duplicateIds.length===0&&fallback.length===0,
      actionable:all.length,uncovered:uncovered.length,fallback: fallback.length,unnamed:unnamed.length,
      duplicateFocusIds:[...new Set(duplicateIds)],regions,
      uncoveredSamples:uncovered.slice(0,10).map(el=>el.id||el.outerHTML.slice(0,100)),
      fallbackSamples:fallback.slice(0,10).map(el=>el.id||clean(el.textContent).slice(0,60)||el.tagName)
    };
    diagnostics.lastAudit=result;document.documentElement.dataset.sbbControllerAudit=result.ok?'pass':'warn';
    if(log){if(result.ok)console.info('[SBB v5.4.3] controller readiness audit PASS',result);else console.warn('[SBB v5.4.3] controller readiness audit WARN',result);}
    try{window.dispatchEvent(new CustomEvent('sbb:controller-readiness-audit',{detail:result}));}catch(_){ }
    return result;
  }
  function snapshot(){return {version:VERSION,inputOwner,ownerReason,ownerChangedAt,controllerFocusId:controllerFocus?.dataset?.sbbFocusId||'',focusMemory:{...focusMemory},diagnostics:{...diagnostics},regions:REGION_SPECS.map(x=>x.name)};}

  function bindInputOwnership(){
    document.addEventListener('pointerdown',()=>claimInput('pointer',{reason:'pointer down'}),{capture:true,passive:true});
    document.addEventListener('wheel',()=>claimInput('pointer',{reason:'wheel'}),{capture:true,passive:true});
    document.addEventListener('pointermove',event=>{
      const p={x:Number(event.clientX)||0,y:Number(event.clientY)||0};
      if(!pointerAnchor){pointerAnchor=p;return;}
      const distance=Math.hypot(p.x-pointerAnchor.x,p.y-pointerAnchor.y);
      if(distance>=POINTER_MOVE_THRESHOLD){pointerAnchor=p;claimInput('pointer',{reason:'meaningful pointer move'});}
    },{capture:true,passive:true});
    document.addEventListener('keydown',event=>{
      if(['Shift','Control','Alt','Meta','CapsLock','NumLock','ScrollLock'].includes(event.key))return;
      claimInput('keyboard',{reason:`key:${event.key}`});
    },{capture:true});
    document.addEventListener('focusin',event=>{const el=event.target;if(el?.dataset?.sbbFocusable==='1')remember(el);},{capture:true});
  }
  function bindDynamicRegistration(){
    if(typeof MutationObserver==='undefined')return;
    mutationObserver=new MutationObserver(records=>{
      const added=[];for(const record of records)for(const node of record.addedNodes||[])if(node?.nodeType===1)added.push(node);
      if(added.length)queueRegister(added);
    });
    // Child-list only by design. Attribute changes from registration never feed
    // back into this observer, preventing the v5.3.19 class/DOM observer failure mode.
    mutationObserver.observe(document.body,{childList:true,subtree:true});
  }
  function init(){
    registerTree(document);bindInputOwnership();bindDynamicRegistration();emitOwner();
    requestAnimationFrame(()=>requestAnimationFrame(()=>audit({log:true})));
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();

  window.SBB_INPUT_OWNERSHIP=Object.freeze({version:VERSION,claim:claimInput,current:()=>inputOwner,subscribe:subscribeInput,snapshot:()=>({owner:inputOwner,reason:ownerReason,changedAt:ownerChangedAt})});
  window.SBB_INTERACTION_REGIONS=Object.freeze({version:VERSION,specs:REGION_SPECS,graph:REGION_GRAPH,register:registerTree,resolve:resolveRegion,focusables,entry:preferredEntry,enter:enterRegion,memory:()=>({...focusMemory})});
  window.SBB_SEMANTIC_NAVIGATION=Object.freeze({version:VERSION,current:currentFocus,focus:focusElement,focusById,move,activate,back:navigateBack,ensureVisible,clearFocus:clearControllerFocus});
  window.SBB_CONTROLLER_READINESS=Object.freeze({version:VERSION,installed:true,mode:'READINESS_ONLY_NO_GAMEPAD_BINDINGS',actionableSelector:ACTIONABLE_SELECTOR,regions:REGION_SPECS.map(x=>x.name),audit,snapshot,register:registerTree});
})();

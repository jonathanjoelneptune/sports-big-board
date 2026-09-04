/* Sports Big Board v5.4.1 — Core Controller Mode.
   Automatic, last-meaningful-input controller ownership built on the v5.4.0
   semantic interaction graph. No mouse emulation and no radial menus yet.
   Standard-mapped gamepads get D-pad/left-stick focus navigation, A/B, X/Y,
   LB/RB, right-stick contextual scrolling, automatic mouse/keyboard takeover,
   connection status, and a compact controller legend. */
(() => {
  'use strict';
  if(window.SBB_CONTROLLER_MODE?.version==='5.4.1')return;
  const VERSION='5.4.1';
  const PREF_KEY='sports-big-board.controller-mode.v1';
  const DEADZONE=.22;
  const SCROLL_DEADZONE=.26;
  const BUTTON_THRESHOLD=.55;
  const REPEAT_DELAY_MS=360;
  const REPEAT_MS=118;
  const DISCOVERY_MS=800;
  const HELP_AUTO_MS=3600;
  const BUTTON={A:0,B:1,X:2,Y:3,LB:4,RB:5,LT:6,RT:7,VIEW:8,MENU:9,LS:10,RS:11,UP:12,DOWN:13,LEFT:14,RIGHT:15};

  let preference=loadPreference();
  let activeIndex=null,activeId='',connected=false,pollRaf=0,discoverTimer=0,lastFrame=0;
  let previousButtons=[],directionState={value:'',startedAt:0,lastFireAt:0};
  let waitingForNeutral=false,controllerEverActive=false,helpTimer=0,helpPinned=false,helpEl=null;
  let lastAction='',lastActionAt=0,frames=0,meaningfulInputs=0;

  const clean=v=>String(v??'').trim();
  const nav=()=>window.SBB_SEMANTIC_NAVIGATION||null;
  const regions=()=>window.SBB_INTERACTION_REGIONS||null;
  const ownerApi=()=>window.SBB_INPUT_OWNERSHIP||null;
  const enabled=()=>preference!=='disabled';
  const visible=el=>{
    if(!el||!el.isConnected||el.hidden||el.disabled||el.getAttribute('aria-disabled')==='true')return false;
    if(el.closest?.('[hidden],.hidden,[aria-hidden="true"]'))return false;
    const r=el.getBoundingClientRect?.();return !!r&&r.width>0&&r.height>0;
  };

  function loadPreference(){try{return localStorage.getItem(PREF_KEY)==='disabled'?'disabled':'automatic';}catch(_){return 'automatic';}}
  function savePreference(){try{localStorage.setItem(PREF_KEY,preference);}catch(_){}}
  function buttonPressed(gamepad,index){const b=gamepad?.buttons?.[index];return !!b&&(!!b.pressed||Number(b.value||0)>=BUTTON_THRESHOLD);}
  function axis(gamepad,index){const n=Number(gamepad?.axes?.[index]||0);return Number.isFinite(n)?n:0;}
  function gamepads(){try{return typeof navigator.getGamepads==='function'?[...(navigator.getGamepads()||[])].filter(Boolean):[];}catch(_){return [];}}
  function firstGamepad(){const pads=gamepads();if(activeIndex!=null){const exact=pads.find(p=>p.index===activeIndex);if(exact)return exact;}return pads[0]||null;}
  function controllerFamily(id=''){
    id=clean(id).toLowerCase();
    if(/dualshock|dualsense|playstation|sony/.test(id))return 'playstation';
    if(/nintendo|switch|joy-con|pro controller/.test(id))return 'nintendo';
    if(/xbox|xinput|microsoft/.test(id))return 'xbox';
    return 'generic';
  }
  function glyphs(){
    const family=controllerFamily(activeId);
    if(family==='playstation')return {a:'✕',b:'○',x:'□',y:'△',lb:'L1',rb:'R1',menu:'OPTIONS'};
    if(family==='nintendo')return {a:'B',b:'A',x:'Y',y:'X',lb:'L',rb:'R',menu:'+'};
    if(family==='xbox')return {a:'A',b:'B',x:'X',y:'Y',lb:'LB',rb:'RB',menu:'☰'};
    return {a:'A/1',b:'B/2',x:'X/3',y:'Y/4',lb:'L1',rb:'R1',menu:'MENU'};
  }

  function ensureHelp(){
    if(helpEl?.isConnected)return helpEl;
    helpEl=document.createElement('div');helpEl.id='sbbControllerHelp';helpEl.className='sbb-controller-help hidden';
    helpEl.setAttribute('role','status');helpEl.setAttribute('aria-live','polite');
    document.body.appendChild(helpEl);renderHelp();return helpEl;
  }
  function renderHelp(message=''){
    const el=ensureHelp();const g=glyphs();
    el.innerHTML=`<div class="sbb-controller-help-head"><span class="sbb-controller-icon">🎮</span><strong>${message||'CONTROLLER MODE'}</strong><small>${clean(activeId)||'Gamepad'}</small></div><div class="sbb-controller-help-grid"><span><b>D-PAD / LS</b> Navigate</span><span><b>${g.a}</b> Select</span><span><b>${g.b}</b> Back</span><span><b>${g.x}</b> Play All</span><span><b>${g.y}</b> Cycle View</span><span><b>${g.lb} / ${g.rb}</b> Prev / Next</span><span><b>RS</b> Scroll</span><span><b>${g.menu}</b> Help</span></div>`;
    return el;
  }
  function showHelp({message='',persist=false,duration=HELP_AUTO_MS}={}){
    const el=renderHelp(message);el.classList.remove('hidden');document.documentElement.dataset.sbbControllerHelp='1';
    if(helpTimer){clearTimeout(helpTimer);helpTimer=0;}
    if(persist||helpPinned)return;
    helpTimer=setTimeout(()=>hideHelp(),Math.max(900,Number(duration)||HELP_AUTO_MS));
  }
  function hideHelp(force=false){
    if(helpPinned&&!force)return;
    if(helpTimer){clearTimeout(helpTimer);helpTimer=0;}
    ensureHelp().classList.add('hidden');delete document.documentElement.dataset.sbbControllerHelp;
  }
  function toggleHelp(){helpPinned=!helpPinned;if(helpPinned)showHelp({persist:true});else hideHelp(true);updateStatus();}

  function updateStatus(){
    const select=document.getElementById('controllerModeSelect');if(select&&select.value!==preference)select.value=preference;
    const status=document.getElementById('controllerStatusValue');
    if(status){
      if(!enabled())status.textContent='Disabled';
      else if(!connected)status.textContent='No controller detected';
      else if(ownerApi()?.current?.()==='controller')status.textContent=`Active • ${clean(activeId)||'Gamepad'}`;
      else status.textContent=`Connected • ${clean(activeId)||'Gamepad'}`;
    }
    const hint=document.getElementById('controllerStatusHint');
    if(hint)hint.textContent=enabled()?'Press any controller button or move a stick to take control. Mouse or keyboard input takes control back automatically.':'Controller input is ignored until Automatic is selected.';
  }
  function bindSettings(){
    const select=document.getElementById('controllerModeSelect');if(!select||select.dataset.sbbControllerBound)return;
    select.dataset.sbbControllerBound='1';select.value=preference;
    select.addEventListener('change',()=>{
      preference=select.value==='disabled'?'disabled':'automatic';savePreference();
      if(!enabled()){
        if(ownerApi()?.current?.()==='controller')ownerApi()?.claim?.('pointer',{reason:'controller mode disabled'});
        waitingForNeutral=true;hideHelp(true);helpPinned=false;
      }else{discoverNow();}
      updateStatus();
    });
    updateStatus();
  }

  function setConnected(gamepad){
    const next=!!gamepad,nextIndex=next?gamepad.index:null,nextId=next?clean(gamepad.id):'';
    const changed=connected!==next||activeIndex!==nextIndex||activeId!==nextId;
    connected=next;activeIndex=nextIndex;activeId=nextId;
    document.documentElement.dataset.sbbControllerConnected=next?'1':'0';
    if(changed){previousButtons=[];directionState={value:'',startedAt:0,lastFireAt:0};renderHelp();updateStatus();}
    if(!next)stopPoll();
  }
  function disconnectActive(reason='controller disconnected'){
    setConnected(null);waitingForNeutral=false;
    if(ownerApi()?.current?.()==='controller')ownerApi()?.claim?.('pointer',{reason});
    hideHelp(true);helpPinned=false;updateStatus();scheduleDiscovery();
  }
  function discoverNow(){
    if(!enabled()||document.visibilityState==='hidden'){scheduleDiscovery();return;}
    const pad=firstGamepad();if(pad){setConnected(pad);startPoll();return;}
    setConnected(null);scheduleDiscovery();
  }
  function scheduleDiscovery(){
    if(discoverTimer)clearTimeout(discoverTimer);
    discoverTimer=setTimeout(()=>{discoverTimer=0;discoverNow();},DISCOVERY_MS);
  }
  function startPoll(){
    if(!enabled()||!connected||pollRaf||document.visibilityState==='hidden')return;
    pollRaf=requestAnimationFrame(poll);
  }
  function stopPoll(){if(pollRaf)cancelAnimationFrame(pollRaf);pollRaf=0;}

  function launchVisible(){const el=document.getElementById('launchScreen');return visible(el)&&visible(document.getElementById('launchPlayBtn'));}
  function ensureControllerFocus(){
    const semantic=nav();if(!semantic)return null;
    let current=semantic.current?.();
    if(launchVisible())current=document.getElementById('launchPlayBtn');
    if(!visible(current))current=regions()?.entry?.('league-nav')||document.querySelector('#scoreFilters [data-score-filter].active,#scoreFilters [data-score-filter="ALL"]');
    if(current)semantic.focus?.(current,{owner:'controller'});
    return current||null;
  }
  function claimController(reason='gamepad input'){
    if(!enabled())return false;
    const was=ownerApi()?.current?.();ownerApi()?.claim?.('controller',{reason});
    meaningfulInputs++;lastAction=reason;lastActionAt=Date.now();
    document.documentElement.dataset.sbbControllerActive='1';
    if(was!=='controller'){ensureControllerFocus();showHelp({duration:HELP_AUTO_MS});}
    updateStatus();return true;
  }

  function dispatchValueChange(el){try{el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}catch(_){}}
  function adjustForm(direction){
    const el=nav()?.current?.();if(!el)return false;
    if(direction!=='left'&&direction!=='right')return false;
    if(el.tagName==='INPUT'&&clean(el.type).toLowerCase()==='range'){
      const min=Number(el.min||0),max=Number(el.max||100),step=Number(el.step||1)||1,current=Number(el.value||0);
      el.value=String(Math.max(min,Math.min(max,current+(direction==='right'?step:-step))));dispatchValueChange(el);return true;
    }
    if(el.tagName==='SELECT'&&el.options?.length){
      const delta=direction==='right'?1:-1;let idx=Math.max(0,el.selectedIndex);idx=Math.max(0,Math.min(el.options.length-1,idx+delta));
      if(idx!==el.selectedIndex){el.selectedIndex=idx;dispatchValueChange(el);}return true;
    }
    return false;
  }
  function handleDirection(direction,repeat=false){
    if(!claimController(`controller ${direction}${repeat?' repeat':''}`))return;
    if(adjustForm(direction))return;
    ensureControllerFocus();nav()?.move?.(direction);
  }
  function clickVisible(selector){
    let items=[];try{items=[...document.querySelectorAll(selector)];}catch(_){return false;}
    const el=items.find(visible);if(!el)return false;try{el.click();return true;}catch(_){return false;}
  }
  function playAll(){
    if(clickVisible('#sbbFocusPlayAll,[data-sbb-action="play-all"]'))return true;
    showHelp({message:'PLAY ALL IS NOT AVAILABLE HERE',duration:1800});return false;
  }
  function cycleDrawer(){
    const drawer=document.getElementById('infoDrawer');
    const closed=!drawer||drawer.classList.contains('is-closed')||drawer.getAttribute('aria-hidden')==='true';
    if(closed)return clickVisible('#gameCenterDrawerBtn,#gameCenterTabBtn');
    const order=['game-center','up-next','settings'];
    const active=document.querySelector('.info-drawer-tab.active,[data-drawer-tab][aria-selected="true"]')?.dataset?.drawerTab||'game-center';
    const next=order[(Math.max(0,order.indexOf(active))+1)%order.length];
    return clickVisible(`[data-drawer-tab="${next}"]`);
  }
  function transport(delta){return clickVisible(delta<0?'#prevBtn':'#nextBtn');}
  function handleButton(index){
    if(!claimController(`controller button ${index}`))return;
    ensureControllerFocus();
    if(index===BUTTON.A){nav()?.activate?.();return;}
    if(index===BUTTON.B){nav()?.back?.();return;}
    if(index===BUTTON.X){playAll();return;}
    if(index===BUTTON.Y){cycleDrawer();return;}
    if(index===BUTTON.LB){transport(-1);return;}
    if(index===BUTTON.RB){transport(1);return;}
    if(index===BUTTON.MENU){toggleHelp();return;}
    // LT/RT and stick clicks are intentionally reserved for v5.4.2 radial/pointer UX.
  }

  function directionFrom(gamepad){
    if(buttonPressed(gamepad,BUTTON.UP))return 'up';if(buttonPressed(gamepad,BUTTON.DOWN))return 'down';
    if(buttonPressed(gamepad,BUTTON.LEFT))return 'left';if(buttonPressed(gamepad,BUTTON.RIGHT))return 'right';
    const x=axis(gamepad,0),y=axis(gamepad,1);if(Math.max(Math.abs(x),Math.abs(y))<DEADZONE)return '';
    if(Math.abs(x)>Math.abs(y))return x>0?'right':'left';return y>0?'down':'up';
  }
  function controllerNeutral(gamepad){
    const buttonActive=(gamepad?.buttons||[]).some(b=>!!b&&(!!b.pressed||Number(b.value||0)>=BUTTON_THRESHOLD));
    const axesActive=(gamepad?.axes||[]).some(v=>Math.abs(Number(v||0))>=DEADZONE);
    return !buttonActive&&!axesActive;
  }
  function processButtons(gamepad){
    const now=[];for(let i=0;i<(gamepad.buttons?.length||0);i++)now[i]=buttonPressed(gamepad,i);
    for(let i=0;i<now.length;i++){if(now[i]&&!previousButtons[i]&&![BUTTON.UP,BUTTON.DOWN,BUTTON.LEFT,BUTTON.RIGHT].includes(i))handleButton(i);}
    previousButtons=now;
  }
  function processDirection(gamepad,now){
    const direction=directionFrom(gamepad);
    if(!direction){directionState={value:'',startedAt:0,lastFireAt:0};return;}
    if(direction!==directionState.value){directionState={value:direction,startedAt:now,lastFireAt:now};handleDirection(direction,false);return;}
    if(now-directionState.startedAt>=REPEAT_DELAY_MS&&now-directionState.lastFireAt>=REPEAT_MS){directionState.lastFireAt=now;handleDirection(direction,true);}
  }

  function scrollableAncestor(el,axisName){
    for(let cur=el;cur&&cur!==document.body;cur=cur.parentElement){
      const style=getComputedStyle(cur);const overflow=axisName==='x'?style.overflowX:style.overflowY;
      const can=axisName==='x'?cur.scrollWidth>cur.clientWidth+2:cur.scrollHeight>cur.clientHeight+2;
      if(can&&/(auto|scroll)/.test(overflow))return cur;
    }
    return null;
  }
  function processRightStick(gamepad,dt){
    const x=axis(gamepad,2),y=axis(gamepad,3);if(Math.abs(x)<SCROLL_DEADZONE&&Math.abs(y)<SCROLL_DEADZONE)return;
    if(ownerApi()?.current?.()!=='controller'){if(!claimController('controller right stick'))return;ensureControllerFocus();}
    const focus=nav()?.current?.();if(!focus)return;
    const scale=Math.min(2,Math.max(.55,dt/16.7));
    if(Math.abs(y)>=SCROLL_DEADZONE){const host=scrollableAncestor(focus,'y');if(host)host.scrollTop+=y*18*scale;}
    if(Math.abs(x)>=SCROLL_DEADZONE){const host=scrollableAncestor(focus,'x');if(host)host.scrollLeft+=x*18*scale;}
  }

  function poll(ts){
    pollRaf=0;if(!enabled()||document.visibilityState==='hidden'){stopPoll();scheduleDiscovery();return;}
    const pad=firstGamepad();if(!pad){disconnectActive();return;}if(!connected||pad.index!==activeIndex)setConnected(pad);
    frames++;const dt=lastFrame?Math.min(50,Math.max(1,ts-lastFrame)):16.7;lastFrame=ts;
    if(waitingForNeutral){
      if(controllerNeutral(pad)){waitingForNeutral=false;previousButtons=[];directionState={value:'',startedAt:0,lastFireAt:0};}
      pollRaf=requestAnimationFrame(poll);return;
    }
    processButtons(pad);processDirection(pad,ts);processRightStick(pad,dt);
    pollRaf=requestAnimationFrame(poll);
  }

  function onOwnerChange(detail){
    const owner=detail?.owner||ownerApi()?.current?.();
    if(owner==='controller'){
      controllerEverActive=true;document.documentElement.dataset.sbbControllerActive='1';updateStatus();return;
    }
    delete document.documentElement.dataset.sbbControllerActive;
    if(controllerEverActive)waitingForNeutral=true;helpPinned=false;hideHelp(true);updateStatus();
  }
  function onConnected(event){if(!enabled())return;setConnected(event.gamepad);startPoll();}
  function onDisconnected(event){if(activeIndex==null||event.gamepad?.index===activeIndex)disconnectActive();}
  function onVisibility(){if(document.visibilityState==='hidden')stopPoll();else discoverNow();}

  function init(){
    bindSettings();ensureHelp();hideHelp(true);
    try{ownerApi()?.subscribe?.(onOwnerChange);}catch(_){ }
    window.addEventListener('gamepadconnected',onConnected);
    window.addEventListener('gamepaddisconnected',onDisconnected);
    document.addEventListener('visibilitychange',onVisibility);
    discoverNow();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();

  window.SBB_CONTROLLER_MODE=Object.freeze({
    version:VERSION,installed:true,mode:'CORE_AUTOMATIC_GAMEPAD',
    get preference(){return preference;},get connected(){return connected;},get active(){return ownerApi()?.current?.()==='controller';},
    setPreference:value=>{preference=value==='disabled'?'disabled':'automatic';savePreference();bindSettings();updateStatus();return preference;},
    showHelp:()=>showHelp({persist:true}),hideHelp:()=>{helpPinned=false;hideHelp(true);},
    snapshot:()=>({version:VERSION,preference,connected,activeIndex,activeId,inputOwner:ownerApi()?.current?.()||'',waitingForNeutral,helpPinned,frames,meaningfulInputs,lastAction,lastActionAt,controllerEverActive})
  });
})();

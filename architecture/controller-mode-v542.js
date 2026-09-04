/* Sports Big Board v5.4.5 — Controller Radials + Native Windows Bridge + Pointer Fallback.
   Builds on the v5.4.0 semantic navigation graph and v5.4.1 automatic takeover.
   Adds robust browser-level gamepad diagnostics, a live header indicator, RT
   League radial, LT Date/Scope radial, and R3 analog pointer fallback. */
(() => {
  'use strict';
  if(window.SBB_CONTROLLER_MODE?.version==='5.4.5')return;
  const VERSION='5.4.5';
  const PREF_KEY='sports-big-board.controller-mode.v1';
  const DEADZONE=.20;
  const NEUTRAL_DEADZONE=.28;
  const SCROLL_DEADZONE=.25;
  const POINTER_DEADZONE=.16;
  const RADIAL_DEADZONE=.38;
  const BUTTON_THRESHOLD=.48;
  const TRIGGER_THRESHOLD=.42;
  const REPEAT_DELAY_MS=350;
  const REPEAT_MS=112;
  const DISCOVERY_MS=650;
  const HELP_AUTO_MS=3600;
  const POINTER_SPEED=760;
  const BUTTON={A:0,B:1,X:2,Y:3,LB:4,RB:5,LT:6,RT:7,VIEW:8,MENU:9,LS:10,RS:11,UP:12,DOWN:13,LEFT:14,RIGHT:15};

  let preference=loadPreference();
  let activeIndex=null,activeId='',activeMapping='',connected=false,pollRaf=0,discoverTimer=0,lastFrame=0;
  let previousButtons=[],directionState={value:'',startedAt:0,lastFireAt:0};
  let waitingForNeutral=false,controllerEverActive=false,helpTimer=0,helpPinned=false,helpEl=null;
  let lastAction='',lastActionAt=0,frames=0,meaningfulInputs=0,rawInputs=0,lastRawInputAt=0,rawSignalActive=false;
  let radial=null,radialEl=null,radialSelection=-1,radialOpenedAt=0,triggerWas={lt:false,rt:false,both:false},commandChordActive=false;
  let pointerMode=false,pointerEl=null,pointerX=0,pointerY=0,pointerInitialized=false;
  let triggerAxes={left:null,right:null};
  let indicatorEl=null,lastIndicatorState='';

  const clean=v=>String(v??'').trim();
  const nav=()=>window.SBB_SEMANTIC_NAVIGATION||null;
  const regions=()=>window.SBB_INTERACTION_REGIONS||null;
  const ownerApi=()=>window.SBB_INPUT_OWNERSHIP||null;
  const enabled=()=>preference!=='disabled';
  const gamepadApiAvailable=()=>typeof navigator.getGamepads==='function';
  const nativeBridge=()=>window.SBB_CONTROLLER_NATIVE_BRIDGE||null;
  const nativeBridgeApiAvailable=()=>!!nativeBridge()?.supported?.();
  const nativeBridgeGamepad=()=>{try{return nativeBridge()?.gamepad?.()||null;}catch(_){return null;}};
  const hidBridge=()=>window.SBB_CONTROLLER_HID_BRIDGE||null;
  const hidApiAvailable=()=>!!hidBridge()?.supported?.();
  const hidGamepad=()=>{try{return hidBridge()?.gamepad?.()||null;}catch(_){return null;}};
  const visible=el=>{
    if(!el||!el.isConnected||el.hidden||el.disabled||el.getAttribute('aria-disabled')==='true')return false;
    if(el.closest?.('[hidden],.hidden,[aria-hidden="true"]'))return false;
    const r=el.getBoundingClientRect?.();return !!r&&r.width>0&&r.height>0;
  };

  function loadPreference(){try{return localStorage.getItem(PREF_KEY)==='disabled'?'disabled':'automatic';}catch(_){return 'automatic';}}
  function savePreference(){try{localStorage.setItem(PREF_KEY,preference);}catch(_){} }
  function buttonValue(gamepad,index){const b=gamepad?.buttons?.[index];return b?Math.max(Number(b.value||0),b.pressed?1:0):0;}
  function buttonPressed(gamepad,index){return buttonValue(gamepad,index)>=BUTTON_THRESHOLD;}
  function axis(gamepad,index){const n=Number(gamepad?.axes?.[index]||0);return Number.isFinite(n)?n:0;}
  function gamepads(){
    let browser=[];try{browser=gamepadApiAvailable()?[...(navigator.getGamepads()||[])].filter(Boolean):[];}catch(_){browser=[];}
    // Transport priority is deliberate: native browser Gamepad first, then the
    // loopback Windows bridge, then WebHID. Never expose duplicate representations
    // of the same physical controller to semantic navigation.
    if(browser.length)return browser;
    const bridged=nativeBridgeGamepad();if(bridged)return [bridged];
    const hid=hidGamepad();return hid?[hid]:[];
  }
  function firstGamepad(){const pads=gamepads();if(activeIndex!=null){const exact=pads.find(p=>p.index===activeIndex);if(exact)return exact;}return pads[0]||null;}
  function controllerFamily(id=''){
    id=clean(id).toLowerCase();
    if(/dualshock|dualsense|playstation|sony/.test(id))return 'playstation';
    if(/nintendo|switch|joy-con|pro controller/.test(id))return 'nintendo';
    if(/xbox|xinput|microsoft|turtle beach|recon|stealth/.test(id))return 'xbox';
    return 'generic';
  }
  function glyphs(){
    const family=controllerFamily(activeId);
    if(family==='playstation')return {a:'✕',b:'○',x:'□',y:'△',lb:'L1',rb:'R1',lt:'L2',rt:'R2',menu:'OPTIONS',r3:'R3'};
    if(family==='nintendo')return {a:'B',b:'A',x:'Y',y:'X',lb:'L',rb:'R',lt:'ZL',rt:'ZR',menu:'+',r3:'R3'};
    if(family==='xbox')return {a:'A',b:'B',x:'X',y:'Y',lb:'LB',rb:'RB',lt:'LT',rt:'RT',menu:'☰',r3:'R3'};
    return {a:'A/1',b:'B/2',x:'X/3',y:'Y/4',lb:'L1',rb:'R1',lt:'LT',rt:'RT',menu:'MENU',r3:'R3'};
  }

  function calibrateTriggerAxes(gamepad){
    if(activeMapping==='standard'||!gamepad)return;
    if(triggerAxes.left!=null&&triggerAxes.right!=null)return;
    // Some non-standard XInput wrappers expose triggers as axes resting at -1.
    // Calibrate only axes that are actually near -1 at rest so a centered stick
    // axis (0) can never be mistaken for a half-pressed trigger.
    const candidates=[];
    for(let i=2;i<(gamepad.axes?.length||0);i++){const raw=axis(gamepad,i);if(raw<=-.72)candidates.push(i);}
    if(triggerAxes.left==null&&candidates.length)triggerAxes.left=candidates[0];
    if(triggerAxes.right==null&&candidates.length>1)triggerAxes.right=candidates[1];
  }
  function triggerValue(gamepad,side){
    const buttonIndex=side==='left'?BUTTON.LT:BUTTON.RT;
    const direct=buttonValue(gamepad,buttonIndex);
    if(direct>0.02)return direct;
    calibrateTriggerAxes(gamepad);
    const idx=triggerAxes[side];if(idx==null)return 0;
    const raw=axis(gamepad,idx);return Math.max(0,Math.min(1,(raw+1)/2));
  }
  function leftStick(gamepad){return {x:axis(gamepad,0),y:axis(gamepad,1)};}
  function rightStick(gamepad){
    // Standard mapping is axes 2/3. A few generic/XInput wrappers shift RS to 3/4.
    let x=axis(gamepad,2),y=axis(gamepad,3);
    if(activeMapping!=='standard' && Math.abs(x)<.02 && Math.abs(y)<.02 && (gamepad?.axes?.length||0)>=5){x=axis(gamepad,3);y=axis(gamepad,4);}
    return {x,y};
  }
  function stickMagnitude(stick){return Math.hypot(Number(stick?.x||0),Number(stick?.y||0));}

  function ensureHelp(){
    if(helpEl?.isConnected)return helpEl;
    helpEl=document.createElement('div');helpEl.id='sbbControllerHelp';helpEl.className='sbb-controller-help hidden';
    helpEl.setAttribute('role','status');helpEl.setAttribute('aria-live','polite');
    document.body.appendChild(helpEl);renderHelp();return helpEl;
  }
  function renderHelp(message=''){
    const el=ensureHelp();const g=glyphs();
    el.innerHTML=`<div class="sbb-controller-help-head"><span class="sbb-controller-icon">🎮</span><strong>${message||'CONTROLLER MODE'}</strong><small>${clean(activeId)||'Gamepad'}</small></div><div class="sbb-controller-help-grid"><span><b>D-PAD / LS</b> Navigate</span><span><b>${g.a}</b> Select</span><span><b>${g.b}</b> Back</span><span><b>${g.x}</b> Play / Pause</span><span><b>${g.y}</b> Cycle View</span><span><b>${g.lb} / ${g.rb}</b> Prev / Next</span><span><b>${g.rt}</b> Leagues</span><span><b>${g.lt}</b> Date / Scope</span><span><b>${g.lt}+${g.rt}</b> Commands</span><span><b>${g.r3}</b> Pointer</span><span><b>RS</b> Scroll</span><span><b>${g.menu}</b> Help</span></div>`;
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

  function ensureIndicator(){
    if(indicatorEl?.isConnected)return indicatorEl;
    indicatorEl=document.getElementById('controllerLiveIndicator');
    return indicatorEl||null;
  }
  function indicatorState(){
    if(!enabled())return {state:'disabled',label:'🎮 OFF'};
    const native=nativeBridge(),ns=native?.snapshot?.()||null,hid=hidBridge();
    if(!gamepadApiAvailable()&&!nativeBridgeApiAvailable()&&!hidApiAvailable())return {state:'unsupported',label:'🎮 NO API'};
    if(!connected){
      if(ns?.transportConnected)return {state:'bridge-wait',label:'🎮 BRIDGE'};
      return {state:'no-bridge',label:'🎮 NO BRIDGE'};
    }
    const bridgeOwned=activeIndex===-544,hidOwned=activeIndex===-543;
    if(ownerApi()?.current?.()==='controller'||(lastRawInputAt&&Date.now()-lastRawInputAt<2600)){
      if(pointerMode)return {state:'pointer',label:'🎮 POINTER'};
      if(bridgeOwned)return {state:'bridge-live',label:'🎮 BR LIVE'};
      if(hidOwned)return {state:'hid-live',label:'🎮 HID LIVE'};
      return {state:'live',label:'🎮 LIVE'};
    }
    if(bridgeOwned)return {state:'bridge-ready',label:'🎮 BR READY'};
    if(hidOwned)return {state:'hid-ready',label:'🎮 HID READY'};
    return {state:'ready',label:'🎮 READY'};
  }
  function updateIndicator(){
    const el=ensureIndicator();if(!el)return;
    const info=indicatorState();el.dataset.state=info.state;el.textContent=info.label;
    const ns=nativeBridge()?.snapshot?.(),hs=hidBridge()?.snapshot?.();
    el.title=[`Controller: ${clean(activeId)||'not detected'}`,`Browser Gamepad API: ${gamepadApiAvailable()?'available':'unavailable'}`,ns?`Windows bridge: ${ns.state}`:'Windows bridge: client not loaded',`WebHID: ${hidApiAvailable()?'available':'unavailable'}`,hs?`HID: ${hs.state}`:'HID: bridge not loaded',`Mapping: ${activeMapping||'—'}`,`Input owner: ${ownerApi()?.current?.()||'—'}`,lastRawInputAt?`Last input: ${new Date(lastRawInputAt).toLocaleTimeString()}`:'No controller input received yet'].join('\n');
    el.setAttribute('aria-label',info.state==='no-bridge'?'Windows controller bridge is not connected':info.label.replace('🎮','Controller').trim());
    el.disabled=info.state==='disabled';lastIndicatorState=info.state;
  }
  function updateStatus(){
    const select=document.getElementById('controllerModeSelect');if(select&&select.value!==preference)select.value=preference;
    const ns=nativeBridge()?.snapshot?.();
    const status=document.getElementById('controllerStatusValue');
    if(status){
      if(!enabled())status.textContent='Disabled';
      else if(!connected&&ns?.transportConnected)status.textContent='Windows bridge connected • waiting for controller';
      else if(!connected)status.textContent='No browser controller detected • Windows bridge offline';
      else if(ownerApi()?.current?.()==='controller')status.textContent=`Live • ${clean(activeId)||'Gamepad'}`;
      else status.textContent=`Ready • ${clean(activeId)||'Gamepad'}`;
    }
    const hint=document.getElementById('controllerStatusHint');
    if(hint)hint.textContent=enabled()?'Input priority: browser Gamepad → local Windows bridge → WebHID. The Stealth Ultra 2.4 GHz receiver can use the Windows bridge when Chrome does not expose it directly. Mouse or keyboard still takes control back automatically.':'Controller input is ignored until Automatic is selected.';
    const nativeStat=document.getElementById('controllerNativeBridgeStatus');if(nativeStat)nativeStat.textContent=ns?.state||'Windows bridge client initializing…';
    const hidStat=document.getElementById('controllerHidStatus');if(hidStat)hidStat.textContent=hidBridge()?.snapshot?.().state||'WebHID bridge initializing…';
    updateIndicator();
  }
  function bindSettings(){
    const select=document.getElementById('controllerModeSelect');if(!select||select.dataset.sbbControllerBound)return;
    select.dataset.sbbControllerBound='1';select.value=preference;
    select.addEventListener('change',()=>{
      preference=select.value==='disabled'?'disabled':'automatic';savePreference();
      if(!enabled()){
        if(ownerApi()?.current?.()==='controller')ownerApi()?.claim?.('pointer',{reason:'controller mode disabled'});
        waitingForNeutral=true;closeRadial(false);setPointerMode(false,{restoreFocus:false,announce:false});hideHelp(true);helpPinned=false;
      }else{discoverNow();}
      updateStatus();
    });
    updateStatus();
  }

  function setConnected(gamepad){
    const next=!!gamepad,nextIndex=next?gamepad.index:null,nextId=next?clean(gamepad.id):'',nextMapping=next?clean(gamepad.mapping)||'non-standard':'';
    const changed=connected!==next||activeIndex!==nextIndex||activeId!==nextId||activeMapping!==nextMapping;
    connected=next;activeIndex=nextIndex;activeId=nextId;activeMapping=nextMapping;
    document.documentElement.dataset.sbbControllerConnected=next?'1':'0';
    if(changed){previousButtons=[];directionState={value:'',startedAt:0,lastFireAt:0};triggerWas={lt:false,rt:false,both:false};triggerAxes={left:null,right:null};if(next)calibrateTriggerAxes(gamepad);renderHelp();updateStatus();}
    if(!next)stopPoll();
  }
  function disconnectActive(reason='controller disconnected'){
    setConnected(null);waitingForNeutral=false;rawSignalActive=false;closeRadial(false);setPointerMode(false,{restoreFocus:false,announce:false});
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
    if(current&&!pointerMode)semantic.focus?.(current,{owner:'controller'});
    return current||null;
  }
  function claimController(reason='gamepad input'){
    if(!enabled())return false;
    const was=ownerApi()?.current?.();ownerApi()?.claim?.('controller',{reason});
    meaningfulInputs++;lastAction=reason;lastActionAt=Date.now();lastRawInputAt=Date.now();rawInputs++;
    document.documentElement.dataset.sbbControllerActive='1';
    if(was!=='controller'){if(!pointerMode)ensureControllerFocus();showHelp({duration:HELP_AUTO_MS});}
    updateStatus();return true;
  }

  function dispatchValueChange(el){try{el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}catch(_){} }
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
    if(radial||pointerMode)return;
    if(!claimController(`controller ${direction}${repeat?' repeat':''}`))return;
    if(adjustForm(direction))return;
    ensureControllerFocus();nav()?.move?.(direction);
  }
  function clickVisible(selector){
    let items=[];try{items=[...document.querySelectorAll(selector)];}catch(_){return false;}
    const el=items.find(visible);if(!el)return false;try{el.click();return true;}catch(_){return false;}
  }
  function playPause(){
    if(clickVisible('#playBtn'))return true;
    showHelp({message:'PLAYBACK CONTROL IS NOT AVAILABLE HERE',duration:1600});return false;
  }
  function toggleActiveMute(){
    // Muting is intentionally scoped to the active video transport. Sports Big
    // Board soundtrack controls remain independent. This works for both YouTube
    // and direct-video playback without manufacturing a second audio state model.
    try{
      const slot=(typeof activeSlot!=='undefined'&&activeSlot)?activeSlot:'A';
      const media=(typeof slotMedia!=='undefined'&&slotMedia)?slotMedia[slot]:'';
      if(media==='native'){
        const v=document.getElementById(`native${slot}`);
        if(v){v.muted=!v.muted;try{window.SBB_PLAYBACK_SESSION?.setAudible?.('video',slot,!v.muted);}catch(_){}showHelp({message:v.muted?'VIDEO MUTED':'VIDEO SOUND ON',duration:1200});return true;}
      }
      if(typeof players!=='undefined'&&players?.[slot]){
        const p=players[slot];let muted=false;try{muted=typeof p.isMuted==='function'?!!p.isMuted():false;}catch(_){muted=false;}
        try{if(muted)p.unMute?.();else p.mute?.();}catch(_){return false;}
        try{window.SBB_PLAYBACK_SESSION?.setAudible?.('video',slot,muted);}catch(_){}
        showHelp({message:muted?'VIDEO SOUND ON':'VIDEO MUTED',duration:1200});return true;
      }
    }catch(_){}
    // If playback globals are not visible for a future transport, prefer an
    // explicit semantic mute action if one has been registered by that transport.
    if(clickVisible('[data-sbb-action="mute-video"],[data-sbb-action="mute"]'))return true;
    showHelp({message:'MUTE IS NOT AVAILABLE FOR THIS SOURCE',duration:1600});return false;
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

  function leagueOptions(){
    const defs=[
      ['ALL','ALL'],['MLB','MLB'],['NFL','NFL'],['NBA','NBA'],['NHL','NHL'],['EPL','EPL'],['MLS','MLS'],['NCAAF','NCAAF'],['SPECIAL','SPECIAL EVENTS']
    ];
    return defs.map(([value,label])=>({value,label,action:()=>{
      if(value==='SPECIAL')return clickVisible('#sbbSpecialEventsBtn');
      return clickVisible(`#scoreFilters [data-score-filter="${value}"]`);
    }}));
  }
  function isoLocal(offset=0){const d=new Date();d.setDate(d.getDate()+offset);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
  function chooseAbsoluteDate(value){
    const picker=document.getElementById('scoreDatePicker');if(!picker)return false;
    picker.value=value;dispatchValueChange(picker);return true;
  }
  function dateScopeOptions(){return [
    {value:'TODAY',label:'TODAY',action:()=>clickVisible('#sbbLeagueTodayBtn,#returnTodayBtn')||chooseAbsoluteDate(isoLocal(0))},
    {value:'YESTERDAY',label:'YESTERDAY',action:()=>chooseAbsoluteDate(isoLocal(-1))},
    {value:'PREV',label:'PREV DAY',action:()=>clickVisible('[data-score-date-step="-1"]')},
    {value:'NEXT',label:'NEXT DAY',action:()=>clickVisible('[data-score-date-step="1"]')},
    {value:'DATE',label:'SELECT DATE',action:()=>clickVisible('#topDateSelectBtn,#scoreDayIndicator')},
    {value:'ALL',label:'ALL',action:()=>clickVisible('#sbbLeagueAllBtn')||clickVisible('#scoreFilters [data-score-filter="ALL"]')},
    {value:'BROWSE',label:'TEAM BROWSE',action:()=>clickVisible('#sbbBrowseBtn')},
    {value:'RETURN',label:'RETURN TODAY',action:()=>clickVisible('#returnTodayBtn')||chooseAbsoluteDate(isoLocal(0))}
  ];}
  function commandOptions(){return [
    {value:'APPFS',label:'APP FULLSCREEN',action:()=>window.SBB_FULLSCREEN_CONTROL?.toggleApp?.({controller:true})},
    {value:'VIDEOFS',label:'VIDEO FULLSCREEN',action:()=>window.SBB_FULLSCREEN_CONTROL?.toggleVideo?.({controller:true})},
    {value:'EXITFS',label:'EXIT FULLSCREEN',action:()=>window.SBB_FULLSCREEN_CONTROL?.exitFullscreen?.({controller:true})},
    {value:'PLAY',label:'PLAY / PAUSE',action:()=>playPause()},
    {value:'MUTE',label:'MUTE / UNMUTE',action:()=>toggleActiveMute()},
    {value:'GAMECENTER',label:'GAME CENTER',action:()=>clickVisible('#gameCenterDrawerBtn,#gameCenterTabBtn')},
    {value:'LEAGUEVIEW',label:'LEAGUE VIEW',action:()=>clickVisible('#upNextDrawerBtn,#upNextTabBtn')},
    {value:'SETTINGS',label:'SETTINGS',action:()=>clickVisible('#settingsDrawerBtn,#settingsTabBtn')}
  ];}

  function ensureRadial(){
    if(radialEl?.isConnected)return radialEl;
    radialEl=document.createElement('div');radialEl.id='sbbControllerRadial';radialEl.className='sbb-controller-radial hidden';radialEl.setAttribute('aria-hidden','true');
    radialEl.innerHTML='<div class="sbb-controller-radial-dim"></div><div class="sbb-controller-radial-wheel"><div class="sbb-controller-radial-center"><strong></strong><span>MOVE RIGHT STICK • RELEASE TRIGGER</span></div><div class="sbb-controller-radial-items"></div></div>';
    document.body.appendChild(radialEl);return radialEl;
  }
  function renderRadial(){
    const el=ensureRadial();if(!radial)return;
    const items=radial.options||[],host=el.querySelector('.sbb-controller-radial-items'),center=el.querySelector('.sbb-controller-radial-center strong');
    if(center)center.textContent=radial.type==='league'?'LEAGUES':(radial.type==='date'?'DATE / SCOPE':'SPECIAL COMMANDS');
    const radius=178;host.innerHTML=items.map((item,i)=>{
      const angle=(-Math.PI/2)+(Math.PI*2*i/items.length),x=Math.cos(angle)*radius,y=Math.sin(angle)*radius;
      const selected=i===radialSelection?' selected':'',current=item.value===radial.current?' current':'';
      return `<div class="sbb-controller-radial-item${selected}${current}" data-radial-index="${i}" style="--rx:${x.toFixed(1)}px;--ry:${y.toFixed(1)}px"><span>${item.label}</span></div>`;
    }).join('');
  }
  function currentLeague(){return clean(document.querySelector('#scoreFilters [data-score-filter].active')?.dataset?.scoreFilter).toUpperCase()||'ALL';}
  function openRadial(type){
    if(!claimController(`open ${type} radial`))return false;
    if(radial?.type===type)return true;
    setPointerVisual(false);radialSelection=-1;radialOpenedAt=Date.now();
    const options=type==='league'?leagueOptions():(type==='date'?dateScopeOptions():commandOptions());
    radial={type,options,current:type==='league'?currentLeague():''};
    const el=ensureRadial();el.classList.remove('hidden');el.setAttribute('aria-hidden','false');document.documentElement.dataset.sbbControllerRadial=type;renderRadial();
    return true;
  }
  function closeRadial(commit=true){
    if(!radial)return false;
    const selected=radialSelection>=0?radial.options?.[radialSelection]:null;const type=radial.type;
    radial=null;radialSelection=-1;delete document.documentElement.dataset.sbbControllerRadial;
    const el=ensureRadial();el.classList.add('hidden');el.setAttribute('aria-hidden','true');
    if(pointerMode)setPointerVisual(true);
    if(commit&&selected){try{selected.action?.();lastAction=`${type} radial: ${selected.value}`;lastActionAt=Date.now();}catch(_){} }
    return true;
  }
  function radialVector(gamepad){const rs=rightStick(gamepad);if(stickMagnitude(rs)>=RADIAL_DEADZONE)return rs;const ls=leftStick(gamepad);return stickMagnitude(ls)>=RADIAL_DEADZONE?ls:{x:0,y:0};}
  function processRadial(gamepad){
    if(!radial)return;
    const v=radialVector(gamepad),mag=stickMagnitude(v);if(mag<RADIAL_DEADZONE){if(radialSelection!==-1){radialSelection=-1;renderRadial();}return;}
    let angle=Math.atan2(v.y,v.x),best=0,bestDelta=Infinity;
    for(let i=0;i<radial.options.length;i++){
      const target=(-Math.PI/2)+(Math.PI*2*i/radial.options.length);let d=Math.abs(Math.atan2(Math.sin(angle-target),Math.cos(angle-target)));
      if(d<bestDelta){bestDelta=d;best=i;}
    }
    if(best!==radialSelection){radialSelection=best;lastRawInputAt=Date.now();renderRadial();updateIndicator();}
  }
  function processTriggers(gamepad){
    const lt=triggerValue(gamepad,'left')>=TRIGGER_THRESHOLD,rt=triggerValue(gamepad,'right')>=TRIGGER_THRESHOLD,both=lt&&rt;
    // LT+RT is a chord. If one trigger opened its normal wheel a fraction of a
    // second earlier, promote that wheel to Special Commands without committing it.
    if(both&&!triggerWas.both){if(radial)closeRadial(false);commandChordActive=true;openRadial('commands');}
    else if(!both&&radial?.type!=='commands'){
      if(rt&&!triggerWas.rt)openRadial('league');
      if(lt&&!triggerWas.lt&&!rt)openRadial('date');
      if(triggerWas.rt&&!rt&&radial?.type==='league')closeRadial(true);
      if(triggerWas.lt&&!lt&&radial?.type==='date')closeRadial(true);
    }
    // Keep the command wheel open while either trigger is still held; commit only
    // after the chord is fully released so staggered trigger release is harmless.
    if(radial?.type==='commands'&&commandChordActive&&!lt&&!rt){closeRadial(true);commandChordActive=false;}
    triggerWas={lt,rt,both};
  }

  function ensurePointer(){
    if(pointerEl?.isConnected)return pointerEl;
    pointerEl=document.createElement('div');pointerEl.id='sbbControllerPointer';pointerEl.className='sbb-controller-pointer hidden';pointerEl.setAttribute('aria-hidden','true');document.body.appendChild(pointerEl);return pointerEl;
  }
  function initPointerPosition(){
    if(pointerInitialized)return;const focus=nav()?.current?.();const r=visible(focus)?focus.getBoundingClientRect():null;
    pointerX=r?r.left+r.width/2:window.innerWidth/2;pointerY=r?r.top+r.height/2:window.innerHeight/2;pointerInitialized=true;
  }
  function setPointerVisual(show){const el=ensurePointer();el.classList.toggle('hidden',!show);el.setAttribute('aria-hidden',show?'false':'true');if(show){el.style.transform=`translate3d(${pointerX}px,${pointerY}px,0)`;}}
  function setPointerMode(on,{restoreFocus=true,announce=true}={}){
    on=!!on;if(pointerMode===on){if(on&&!radial)setPointerVisual(true);return pointerMode;}
    pointerMode=on;document.documentElement.dataset.sbbControllerPointer=on?'1':'0';
    if(on){claimController('controller pointer mode');initPointerPosition();try{nav()?.clear?.();}catch(_){}setPointerVisual(!radial);if(announce)showHelp({message:'POINTER MODE',duration:1600});}
    else{delete document.documentElement.dataset.sbbControllerPointer;setPointerVisual(false);if(restoreFocus&&ownerApi()?.current?.()==='controller')ensureControllerFocus();if(announce&&ownerApi()?.current?.()==='controller')showHelp({message:'FOCUS MODE',duration:1200});}
    updateIndicator();return pointerMode;
  }
  function movePointer(gamepad,dt){
    if(!pointerMode||radial)return;const s=leftStick(gamepad),mag=stickMagnitude(s);if(mag<POINTER_DEADZONE)return;
    claimController('controller pointer move');const scale=Math.min(2,Math.max(.45,dt/16.7)),gain=Math.pow(Math.min(1,mag),1.35);
    pointerX=Math.max(8,Math.min(window.innerWidth-8,pointerX+(s.x/mag)*POINTER_SPEED*gain*(dt/1000)*scale));
    pointerY=Math.max(8,Math.min(window.innerHeight-8,pointerY+(s.y/mag)*POINTER_SPEED*gain*(dt/1000)*scale));setPointerVisual(true);
  }
  function pointerTarget(){try{return document.elementFromPoint(pointerX,pointerY);}catch(_){return null;}}
  function pointerClick(){
    const raw=pointerTarget();if(!raw)return false;
    const target=raw.closest?.('button,a[href],input,select,textarea,[role="button"],[role="tab"],[data-sbb-action],.score-card,.score-cell')||raw;
    if(!visible(target))return false;
    try{target.click();return true;}catch(_){try{target.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,clientX:pointerX,clientY:pointerY}));return true;}catch(__){return false;}}
  }
  function pointerScroll(gamepad,dt){
    if(!pointerMode||radial)return;const s=rightStick(gamepad);if(Math.abs(s.x)<SCROLL_DEADZONE&&Math.abs(s.y)<SCROLL_DEADZONE)return;
    claimController('controller pointer scroll');const raw=pointerTarget(),scale=Math.min(2,Math.max(.55,dt/16.7));
    if(Math.abs(s.y)>=SCROLL_DEADZONE){const host=scrollableAncestor(raw,'y');if(host)host.scrollTop+=s.y*20*scale;else window.scrollBy(0,s.y*20*scale);}
    if(Math.abs(s.x)>=SCROLL_DEADZONE){const host=scrollableAncestor(raw,'x');if(host)host.scrollLeft+=s.x*20*scale;}
  }

  function handleButton(index){
    if(!claimController(`controller button ${index}`))return;
    if(radial){if(index===BUTTON.B){closeRadial(false);return;}if(index===BUTTON.A){closeRadial(true);return;}if(index===BUTTON.MENU){toggleHelp();return;}return;}
    if(index===BUTTON.RS){setPointerMode(!pointerMode);return;}
    if(pointerMode){
      if(index===BUTTON.A){pointerClick();return;}
      if(index===BUTTON.B){setPointerMode(false);return;}
      if(index===BUTTON.MENU){toggleHelp();return;}
      if(index===BUTTON.LB){transport(-1);return;}if(index===BUTTON.RB){transport(1);return;}
      return;
    }
    ensureControllerFocus();
    if(index===BUTTON.A){nav()?.activate?.();return;}
    if(index===BUTTON.B){nav()?.back?.();return;}
    if(index===BUTTON.X){playPause();return;}
    if(index===BUTTON.Y){cycleDrawer();return;}
    if(index===BUTTON.LB){transport(-1);return;}
    if(index===BUTTON.RB){transport(1);return;}
    if(index===BUTTON.MENU){toggleHelp();return;}
  }

  function directionFrom(gamepad){
    if(buttonPressed(gamepad,BUTTON.UP))return 'up';if(buttonPressed(gamepad,BUTTON.DOWN))return 'down';
    if(buttonPressed(gamepad,BUTTON.LEFT))return 'left';if(buttonPressed(gamepad,BUTTON.RIGHT))return 'right';
    const s=leftStick(gamepad);if(Math.max(Math.abs(s.x),Math.abs(s.y))>=DEADZONE){if(Math.abs(s.x)>Math.abs(s.y))return s.x>0?'right':'left';return s.y>0?'down':'up';}
    // Generic controllers sometimes expose the D-pad as axes 6/7.
    if(activeMapping!=='standard'&&(gamepad?.axes?.length||0)>=8){const x=axis(gamepad,6),y=axis(gamepad,7);if(Math.max(Math.abs(x),Math.abs(y))>=.55){if(Math.abs(x)>Math.abs(y))return x>0?'right':'left';return y>0?'down':'up';}}
    return '';
  }
  function meaningfulRaw(gamepad){
    const buttonActive=(gamepad?.buttons||[]).some((b,i)=>i!==BUTTON.LT&&i!==BUTTON.RT&&!!b&&(!!b.pressed||Number(b.value||0)>=BUTTON_THRESHOLD));
    const ls=leftStick(gamepad),rs=rightStick(gamepad),triggers=triggerValue(gamepad,'left')>=TRIGGER_THRESHOLD||triggerValue(gamepad,'right')>=TRIGGER_THRESHOLD;
    return buttonActive||stickMagnitude(ls)>=DEADZONE||stickMagnitude(rs)>=SCROLL_DEADZONE||triggers;
  }
  function controllerNeutral(gamepad){
    // Deliberately ignore arbitrary non-standard axes. Trigger axes often rest at
    // -1 and previously could trap a controller forever in the takeover neutral latch.
    const buttonActive=(gamepad?.buttons||[]).some((b,i)=>i!==BUTTON.LT&&i!==BUTTON.RT&&!!b&&(!!b.pressed||Number(b.value||0)>=BUTTON_THRESHOLD));
    const ls=leftStick(gamepad),rs=rightStick(gamepad);
    return !buttonActive&&stickMagnitude(ls)<NEUTRAL_DEADZONE&&stickMagnitude(rs)<NEUTRAL_DEADZONE&&triggerValue(gamepad,'left')<.18&&triggerValue(gamepad,'right')<.18;
  }
  function processRawActivity(gamepad){
    const active=meaningfulRaw(gamepad);
    if(active&&!rawSignalActive){rawSignalActive=true;claimController('raw gamepad input');}
    else if(!active&&rawSignalActive){rawSignalActive=false;updateIndicator();}
  }
  function processButtons(gamepad){
    const now=[];for(let i=0;i<(gamepad.buttons?.length||0);i++)now[i]=buttonPressed(gamepad,i);
    for(let i=0;i<now.length;i++){if(now[i]&&!previousButtons[i]&&![BUTTON.UP,BUTTON.DOWN,BUTTON.LEFT,BUTTON.RIGHT,BUTTON.LT,BUTTON.RT].includes(i))handleButton(i);}
    previousButtons=now;
  }
  function processDirection(gamepad,now){
    if(radial||pointerMode)return;
    const direction=directionFrom(gamepad);
    if(!direction){directionState={value:'',startedAt:0,lastFireAt:0};return;}
    if(direction!==directionState.value){directionState={value:direction,startedAt:now,lastFireAt:now};handleDirection(direction,false);return;}
    if(now-directionState.startedAt>=REPEAT_DELAY_MS&&now-directionState.lastFireAt>=REPEAT_MS){directionState.lastFireAt=now;handleDirection(direction,true);}
  }

  function scrollableAncestor(el,axisName){
    for(let cur=el;cur&&cur!==document.body;cur=cur.parentElement){
      const style=getComputedStyle(cur),overflow=axisName==='x'?style.overflowX:style.overflowY;
      const can=axisName==='x'?cur.scrollWidth>cur.clientWidth+2:cur.scrollHeight>cur.clientHeight+2;
      if(can&&/(auto|scroll)/.test(overflow))return cur;
    }
    return null;
  }
  function processRightStick(gamepad,dt){
    if(radial||pointerMode)return;
    const s=rightStick(gamepad);if(Math.abs(s.x)<SCROLL_DEADZONE&&Math.abs(s.y)<SCROLL_DEADZONE)return;
    if(ownerApi()?.current?.()!=='controller'){if(!claimController('controller right stick'))return;ensureControllerFocus();}
    const focus=nav()?.current?.();if(!focus)return;const scale=Math.min(2,Math.max(.55,dt/16.7));
    if(Math.abs(s.y)>=SCROLL_DEADZONE){const host=scrollableAncestor(focus,'y');if(host)host.scrollTop+=s.y*18*scale;}
    if(Math.abs(s.x)>=SCROLL_DEADZONE){const host=scrollableAncestor(focus,'x');if(host)host.scrollLeft+=s.x*18*scale;}
  }

  function poll(ts){
    pollRaf=0;if(!enabled()||document.visibilityState==='hidden'){stopPoll();scheduleDiscovery();return;}
    const pad=firstGamepad();if(!pad){disconnectActive();return;}if(!connected||pad.index!==activeIndex)setConnected(pad);
    frames++;const dt=lastFrame?Math.min(50,Math.max(1,ts-lastFrame)):16.7;lastFrame=ts;
    if(waitingForNeutral){
      if(controllerNeutral(pad)){waitingForNeutral=false;rawSignalActive=false;previousButtons=[];directionState={value:'',startedAt:0,lastFireAt:0};triggerWas={lt:false,rt:false,both:false};commandChordActive=false;}
      pollRaf=requestAnimationFrame(poll);return;
    }
    processRawActivity(pad);processTriggers(pad);processButtons(pad);
    if(radial)processRadial(pad);
    else if(pointerMode){movePointer(pad,dt);pointerScroll(pad,dt);}
    else{processDirection(pad,ts);processRightStick(pad,dt);}
    pollRaf=requestAnimationFrame(poll);
  }

  function onOwnerChange(detail){
    const owner=detail?.owner||ownerApi()?.current?.();
    if(owner==='controller'){controllerEverActive=true;document.documentElement.dataset.sbbControllerActive='1';updateStatus();return;}
    delete document.documentElement.dataset.sbbControllerActive;
    if(controllerEverActive){waitingForNeutral=true;rawSignalActive=false;closeRadial(false);setPointerMode(false,{restoreFocus:false,announce:false});helpPinned=false;hideHelp(true);}updateStatus();
  }
  function onConnected(event){if(!enabled())return;setConnected(event.gamepad);startPoll();}
  function onDisconnected(event){if(activeIndex==null||event.gamepad?.index===activeIndex)disconnectActive();}
  function onVisibility(){if(document.visibilityState==='hidden')stopPoll();else discoverNow();}
  function onWindowFocus(){setTimeout(discoverNow,0);}
  function onPointerWake(){setTimeout(discoverNow,0);}

  function init(){
    bindSettings();ensureHelp();hideHelp(true);ensureIndicator();updateStatus();
    try{ownerApi()?.subscribe?.(onOwnerChange);}catch(_){ }
    window.addEventListener('gamepadconnected',onConnected);window.addEventListener('gamepaddisconnected',onDisconnected);
    document.addEventListener('sbb:controller-native-bridge-change',()=>{updateStatus();discoverNow();});
    document.addEventListener('sbb:controller-hid-change',()=>{updateStatus();discoverNow();});
    const indicator=ensureIndicator();if(indicator&&!indicator.dataset.sbbPairBound){indicator.dataset.sbbPairBound='1';indicator.addEventListener('click',()=>{const info=indicatorState();if(info.state==='no-bridge'){nativeBridge()?.reconnect?.();showHelp({message:'START WINDOWS BRIDGE',duration:2200});}else if(info.state==='hid-pair')hidBridge()?.pair?.();else showHelp({message:info.label.replace('🎮','').trim(),duration:1800});});}
    document.addEventListener('visibilitychange',onVisibility);window.addEventListener('focus',onWindowFocus);
    document.addEventListener('pointerdown',onPointerWake,{passive:true});
    discoverNow();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();

  window.SBB_CONTROLLER_MODE=Object.freeze({
    version:VERSION,installed:true,mode:'RADIALS_POINTER_COMMANDS_AUTOMATIC_GAMEPAD',
    get preference(){return preference;},get connected(){return connected;},get active(){return ownerApi()?.current?.()==='controller';},get pointerMode(){return pointerMode;},
    setPreference:value=>{preference=value==='disabled'?'disabled':'automatic';savePreference();bindSettings();updateStatus();return preference;},
    showHelp:()=>showHelp({persist:true}),hideHelp:()=>{helpPinned=false;hideHelp(true);},
    openLeagueRadial:()=>openRadial('league'),openDateRadial:()=>openRadial('date'),openCommandRadial:()=>openRadial('commands'),closeRadial,
    playPause,toggleActiveMute,
    setPointerMode,
    snapshot:()=>({version:VERSION,preference,apiAvailable:gamepadApiAvailable(),nativeBridgeApiAvailable:nativeBridgeApiAvailable(),nativeBridge:nativeBridge()?.snapshot?.()||null,hidApiAvailable:hidApiAvailable(),hid:hidBridge()?.snapshot?.()||null,connected,activeIndex,activeId,activeMapping,inputOwner:ownerApi()?.current?.()||'',waitingForNeutral,helpPinned,frames,meaningfulInputs,rawInputs,lastRawInputAt,lastAction,lastActionAt,controllerEverActive,pointerMode,radial:radial?.type||'',indicator:lastIndicatorState})
  });
})();

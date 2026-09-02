/* Sports Big Board v5.2.10 — low-overhead Keep Video Visible controller.

   Smoothness rules:
   - ordinary page scrolling is passive and zero-work unless the below-video Game
     Center shrink runway is actually eligible and open;
   - blocking wheel/touch listeners exist ONLY while the minimum-size Game Center
     handoff is locked, and are removed immediately on unlock;
   - stage geometry is captured once per activation/resize and visual resizing uses
     compositor transforms instead of width/height layout writes every frame;
   - reads are batched before writes; the scroll hot path never performs a
     read-after-write layout cycle.

   Playback ownership is never touched by this module. */
(() => {
  'use strict';
  if(window.SBB_VIEW_PREFS?.version==='1.7')return;

  const KEEP_KEY='sbb.keepVideoVisible.v1';
  const LAYOUT_KEY='sbb.gameCenterLayout.v1';
  const $=id=>document.getElementById(id);
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));

  let keep=localStorage.getItem(KEEP_KEY)!=='0';
  let layout=localStorage.getItem(LAYOUT_KEY)||'side';
  let raf=0,active=false,minLocked=false,boundRoot=null,correctingOuterScroll=false;
  let anchorTop=null,baseRect=null,lockScroll=0,stickyTopCache=0,travelCache=0,minFractionCache=.58;
  let compactObserver=null,touchStartY=null,upperTouchLastY=null,upperReverseGesture=false;
  let lockGesturesBound=false;
  const diag={scrollEvents:0,scrollNoops:0,scheduledFrames:0,layoutCaptures:0,activeFrames:0,lockFrames:0,blockingGestureBinds:0,blockingGestureUnbinds:0};

  function sideEligible(){return !!window.matchMedia?.('(pointer:fine)').matches&&window.innerWidth>=1100;}
  function fullscreenRoot(){return document.fullscreenElement||document.webkitFullscreenElement||null;}
  function scrollRoot(){const fs=fullscreenRoot();if(fs&&fs.id==='app-shell')return fs;return document.scrollingElement||document.documentElement;}
  function rootIsDocument(root){return root===document.scrollingElement||root===document.documentElement||root===document.body;}
  function rootScroll(){const r=scrollRoot();return Number(rootIsDocument(r)?(window.scrollY||r?.scrollTop||0):(r?.scrollTop||0));}
  function setRootScroll(y){const r=scrollRoot();y=Math.max(0,Number(y)||0);if(rootIsDocument(r))window.scrollTo(0,y);else r.scrollTop=y;}
  function rootViewportTop(){const r=scrollRoot();return rootIsDocument(r)?0:(r.getBoundingClientRect().top||0);}
  function gameCenterScroller(){return $('gameCenterPane');}
  function fullscreenContainsInfo(info){const fs=fullscreenRoot();return !fs||fs===document.documentElement||fs===document.body||fs.contains?.(info);}

  function ensurePlaceholder(){
    const stage=$('stage');if(!stage)return null;
    let ph=$('sbbStagePlaceholder');
    if(!ph){ph=document.createElement('div');ph.id='sbbStagePlaceholder';ph.className='sbb-stage-placeholder';stage.parentNode?.insertBefore(ph,stage);}
    return ph;
  }

  function ensureCompactChrome(){
    let chrome=$('sbbCompactChrome');if(chrome)return chrome;
    const card=document.querySelector('.stage-card');if(!card)return null;
    chrome=document.createElement('div');chrome.id='sbbCompactChrome';chrome.className='sbb-compact-chrome';chrome.setAttribute('aria-hidden','true');
    chrome.innerHTML=`<div class="sbb-compact-copy"><span class="sbb-compact-league"></span><strong class="sbb-compact-title">Now Playing</strong></div><div class="sbb-compact-transport" aria-label="Compact playback controls"><button type="button" class="sbb-compact-btn" data-proxy="prevBtn" aria-label="Previous highlight">⏮</button><button type="button" class="sbb-compact-btn sbb-compact-play" data-proxy="playBtn" aria-label="Play or pause">Ⅱ</button><button type="button" class="sbb-compact-btn" data-proxy="nextBtn" aria-label="Next highlight">⏭</button></div>`;
    chrome.addEventListener('click',ev=>{const btn=ev.target?.closest?.('[data-proxy]');if(!btn)return;ev.preventDefault();ev.stopPropagation();const source=$(btn.dataset.proxy);if(source&&!source.disabled)source.click();});
    card.appendChild(chrome);syncCompactChrome();return chrome;
  }
  function syncCompactChrome(){
    const chrome=$('sbbCompactChrome');if(!chrome)return;
    const league=chrome.querySelector('.sbb-compact-league'),title=chrome.querySelector('.sbb-compact-title');
    if(league)league.textContent=String($('currentLeague')?.textContent||'').trim();
    if(title)title.textContent=String($('currentTitle')?.textContent||'Now Playing').trim()||'Now Playing';
    for(const id of ['prevBtn','playBtn','nextBtn']){const source=$(id),proxy=chrome.querySelector(`[data-proxy="${id}"]`);if(!proxy||!source)continue;proxy.textContent=source.textContent||proxy.textContent;proxy.disabled=!!source.disabled;proxy.setAttribute('aria-label',source.getAttribute('aria-label')||source.title||proxy.getAttribute('aria-label')||'Playback control');proxy.title=source.title||source.getAttribute('aria-label')||'';proxy.classList.toggle('is-buffering',source.classList.contains('is-buffering'));}
  }
  function observeCompactChrome(){
    if(compactObserver||!window.MutationObserver)return;
    compactObserver=new MutationObserver(syncCompactChrome);
    for(const id of ['currentLeague','currentTitle','prevBtn','playBtn','nextBtn']){const node=$(id);if(node)compactObserver.observe(node,{subtree:true,childList:true,characterData:true,attributes:true});}
  }
  function compactChromeHeight(){return (window.matchMedia?.('(pointer:coarse)').matches||window.innerWidth<820)?42:46;}
  function hideCompactChrome(){const chrome=$('sbbCompactChrome');if(!chrome)return;chrome.classList.remove('is-visible');chrome.setAttribute('aria-hidden','true');for(const prop of ['top','left','width','height','opacity','transform'])chrome.style.removeProperty(prop);}
  function setCompactChrome(left,width,videoBottom,p){
    const chrome=ensureCompactChrome();if(!chrome)return 8;
    const q=clamp((p-.07)/.23,0,1),fullHeight=compactChromeHeight();
    if(q<=.001){hideCompactChrome();return 8;}
    const topGap=4*q,barHeight=Math.max(1,fullHeight*q),opacity=clamp((q-.66)/.34,0,1);
    chrome.style.left=`${Math.round(left)}px`;chrome.style.top=`${Math.ceil(videoBottom+topGap)}px`;chrome.style.width=`${Math.round(width)}px`;chrome.style.height=`${Math.round(barHeight)}px`;chrome.style.opacity=String(opacity);chrome.style.transform=`translate3d(0,${Math.round((1-opacity)*-4)}px,0)`;chrome.classList.toggle('is-visible',opacity>.03);chrome.setAttribute('aria-hidden',opacity>.03?'false':'true');
    return 8+q*(4+fullHeight);
  }

  function refreshStaticGeometry(){
    const header=document.querySelector('.top-nav-header');
    stickyTopCache=Math.max(0,Math.ceil((header?.getBoundingClientRect().height||0)+4));
    travelCache=Math.max(180,Math.min(390,window.innerHeight*.42));
    const coarse=window.matchMedia?.('(pointer:coarse)').matches;
    minFractionCache=coarse?(window.matchMedia?.('(orientation:portrait)').matches?.66:.56):.58;
    document.documentElement.style.setProperty('--sbb-sticky-video-top',`${stickyTopCache}px`);
  }

  function canUseSticky(){
    const info=$('infoDrawer');
    return !!(keep&&info&&info.classList.contains('is-open')&&(window.SBB_INFO_DRAWER?.activeTab||'game-center')==='game-center'&&!document.body.classList.contains('sbb-game-center-side')&&fullscreenContainsInfo(info));
  }

  function capture(stage){
    const y=rootScroll(),r=stage.getBoundingClientRect(),rootTop=rootViewportTop();
    anchorTop=y+(r.top-rootTop);baseRect={left:r.left,width:r.width,height:r.height};diag.layoutCaptures++;
  }

  function clearStageInline(stage){
    if(!stage)return;
    for(const p of ['position','top','left','right','width','height','max-height','margin','z-index','transform','transform-origin','will-change'])stage.style.removeProperty(p);
    stage.style.borderRadius='';
  }

  function bindLockGestures(){
    if(lockGesturesBound)return;lockGesturesBound=true;diag.blockingGestureBinds++;
    document.addEventListener('wheel',onUpperWheel,{passive:false,capture:true});
    document.addEventListener('touchstart',onUpperTouchStart,{passive:true,capture:true});
    document.addEventListener('touchmove',onUpperTouchMove,{passive:false,capture:true});
    document.addEventListener('touchend',onUpperTouchEnd,{passive:true,capture:true});
    document.addEventListener('touchcancel',onUpperTouchEnd,{passive:true,capture:true});
    $('infoDrawer')?.addEventListener('wheel',onInfoWheel,{passive:false});
    $('infoDrawer')?.addEventListener('touchstart',onInfoTouchStart,{passive:true});
    $('infoDrawer')?.addEventListener('touchmove',onInfoTouchMove,{passive:true});
  }
  function unbindLockGestures(){
    if(!lockGesturesBound)return;lockGesturesBound=false;diag.blockingGestureUnbinds++;
    document.removeEventListener('wheel',onUpperWheel,true);document.removeEventListener('touchstart',onUpperTouchStart,true);document.removeEventListener('touchmove',onUpperTouchMove,true);document.removeEventListener('touchend',onUpperTouchEnd,true);document.removeEventListener('touchcancel',onUpperTouchEnd,true);
    $('infoDrawer')?.removeEventListener('wheel',onInfoWheel);$('infoDrawer')?.removeEventListener('touchstart',onInfoTouchStart);$('infoDrawer')?.removeEventListener('touchmove',onInfoTouchMove);
  }

  function clearLockGeometry(){
    if(!minLocked&&!lockGesturesBound)return;
    for(const x of ['--sbb-gc-lock-top','--sbb-gc-lock-left','--sbb-gc-lock-width','--sbb-gc-lock-bottom'])document.documentElement.style.removeProperty(x);
    document.body.classList.remove('sbb-gc-scroll-locked');minLocked=false;unbindLockGestures();
  }
  function normalStage(){
    if(!active&&!minLocked)return;
    const stage=$('stage'),ph=$('sbbStagePlaceholder');
    clearLockGeometry();clearStageInline(stage);hideCompactChrome();
    if(ph){ph.style.display='none';ph.style.height='';}
    document.documentElement.style.removeProperty('--sbb-sticky-video-bottom');document.body.classList.remove('sbb-stage-sticky-active','sbb-stage-minimized');active=false;anchorTop=null;baseRect=null;
  }
  function resetGeometry(){normalStage();anchorTop=null;baseRect=null;upperReverseGesture=false;refreshStaticGeometry();bindScrollRoot();}

  function setFixedStage(stage,top,visualLeft,visualWidth,visualHeight,p){
    const baseWidth=Math.max(1,baseRect?.width||visualWidth),baseHeight=Math.max(1,baseRect?.height||visualHeight);
    const scale=Math.min(1,Math.max(.01,visualWidth/baseWidth));const dx=visualLeft-(baseRect?.left||visualLeft);
    if(!active){stage.style.setProperty('position','fixed','important');stage.style.setProperty('top',`${Math.ceil(top)}px`,'important');stage.style.setProperty('left',`${Math.round(baseRect?.left||visualLeft)}px`,'important');stage.style.setProperty('right','auto','important');stage.style.setProperty('width',`${Math.round(baseWidth)}px`,'important');stage.style.setProperty('height',`${Math.round(baseHeight)}px`,'important');stage.style.setProperty('margin','0','important');stage.style.setProperty('z-index','1400','important');stage.style.setProperty('transform-origin','0 0','important');stage.style.setProperty('will-change','transform','important');}
    stage.style.setProperty('transform',`translate3d(${dx.toFixed(2)}px,0,0) scale(${scale.toFixed(6)})`,'important');stage.style.borderRadius=p>.04?'12px':'';
  }

  function lockWorkspace(info,workspaceTop){
    if(minLocked||!info)return;
    lockScroll=rootScroll();const r=info.getBoundingClientRect();
    document.documentElement.style.setProperty('--sbb-gc-lock-top',`${Math.ceil(workspaceTop)}px`);document.documentElement.style.setProperty('--sbb-gc-lock-left',`${Math.max(6,Math.round(r.left))}px`);document.documentElement.style.setProperty('--sbb-gc-lock-width',`${Math.max(1,Math.round(r.width))}px`);document.documentElement.style.setProperty('--sbb-gc-lock-bottom','6px');document.body.classList.add('sbb-gc-scroll-locked');minLocked=true;bindLockGestures();
  }

  function update(){
    raf=0;
    const usable=canUseSticky();
    if(!usable){if(active||minLocked)normalStage();return;}
    const stage=$('stage'),info=$('infoDrawer'),ph=ensurePlaceholder();if(!stage||!info||!ph)return;

    if(anchorTop==null||!baseRect)capture(stage);
    const top=stickyTopCache,y=rootScroll(),baseWidth=Math.max(1,baseRect.width),baseHeight=Math.max(1,baseRect.height||baseWidth*9/16);

    if(minLocked){
      diag.lockFrames++;
      const frac=minFractionCache,width=baseWidth*frac,height=baseHeight*frac,margin=8,maxLeft=Math.max(margin,window.innerWidth-width-margin),left=clamp(baseRect.left+(baseWidth-width)/2,margin,maxLeft);
      setFixedStage(stage,top,left,width,height,1);const videoBottom=top+height,workspaceExtent=setCompactChrome(left,width,videoBottom,1);document.documentElement.style.setProperty('--sbb-sticky-video-bottom',`${Math.ceil(videoBottom)}px`);document.documentElement.style.setProperty('--sbb-gc-lock-top',`${Math.ceil(videoBottom+workspaceExtent)}px`);return;
    }

    const consumed=Math.max(0,y+top-anchorTop);
    if(consumed<=.5){if(active)normalStage();return;}
    const p=clamp(consumed/travelCache,0,1),frac=1-p*(1-minFractionCache),width=baseWidth*frac,height=baseHeight*frac,margin=8,maxLeft=Math.max(margin,window.innerWidth-width-margin),left=clamp(baseRect.left+(baseWidth-width)/2,margin,maxLeft);
    if(!active){ph.style.display='block';active=true;document.body.classList.add('sbb-stage-sticky-active');}
    diag.activeFrames++;
    setFixedStage(stage,top,left,width,height,p);
    const flowTravel=Math.min(consumed,travelCache),videoBottom=top+height,workspaceExtent=setCompactChrome(left,width,videoBottom,p);
    ph.style.height=`${Math.max(1,Math.round(height+flowTravel+workspaceExtent))}px`;document.documentElement.style.setProperty('--sbb-sticky-video-bottom',`${Math.ceil(videoBottom)}px`);
    const atMin=p>=.999;document.body.classList.toggle('sbb-stage-minimized',atMin);if(atMin)lockWorkspace(info,videoBottom+workspaceExtent);
  }

  function schedule(){if(!raf){diag.scheduledFrames++;raf=requestAnimationFrame(update);}}
  function onRootScroll(){
    diag.scrollEvents++;
    if(minLocked&&!upperReverseGesture&&!correctingOuterScroll){const y=rootScroll();if(Math.abs(y-lockScroll)>1){correctingOuterScroll=true;setRootScroll(lockScroll);requestAnimationFrame(()=>{correctingOuterScroll=false;schedule();});return;}}
    if(!canUseSticky()){diag.scrollNoops++;return;} // zero-rAF, zero-style-write ordinary scrolling
    schedule();
  }
  function bindScrollRoot(){
    const next=scrollRoot();if(boundRoot===next)return;
    if(boundRoot===window)window.removeEventListener('scroll',onRootScroll);else boundRoot?.removeEventListener?.('scroll',onRootScroll);
    if(rootIsDocument(next)){boundRoot=window;window.addEventListener('scroll',onRootScroll,{passive:true});}else{boundRoot=next;next.addEventListener('scroll',onRootScroll,{passive:true});}
  }

  function targetInsideInfo(target){return !!target?.closest?.('#infoDrawer');}
  function targetIsUpperInteractive(target){return !!target?.closest?.('button,a,input,select,textarea,video,iframe,[contenteditable="true"]');}
  function releaseMinLock({grow=false}={}){if(!minLocked)return;clearLockGeometry();if(grow)setRootScroll(Math.max(0,lockScroll-Math.max(4,travelCache*.035)));schedule();}
  function onUpperWheel(ev){if(targetInsideInfo(ev.target)||!minLocked)return;ev.preventDefault();if(ev.deltaY<0){const delta=Math.max(-Math.min(travelCache*.28,120),ev.deltaY);clearLockGeometry();upperReverseGesture=true;setRootScroll(Math.max(0,lockScroll+delta));schedule();requestAnimationFrame(()=>{upperReverseGesture=false;});}}
  function onUpperTouchStart(ev){if(!minLocked||targetInsideInfo(ev.target)||targetIsUpperInteractive(ev.target)){upperTouchLastY=null;return;}upperTouchLastY=ev.touches?.[0]?.clientY??null;upperReverseGesture=false;}
  function onUpperTouchMove(ev){if(!minLocked||upperTouchLastY==null)return;const y=ev.touches?.[0]?.clientY??upperTouchLastY,delta=y-upperTouchLastY;upperTouchLastY=y;ev.preventDefault();if(delta>0){clearLockGeometry();upperReverseGesture=true;setRootScroll(Math.max(0,lockScroll-delta));schedule();}}
  function onUpperTouchEnd(){upperTouchLastY=null;upperReverseGesture=false;}
  function onInfoWheel(ev){if(!minLocked||ev.deltaY>=0)return;const s=gameCenterScroller();if(s&&s.scrollTop<=1){ev.preventDefault();releaseMinLock({grow:true});}}
  function onInfoTouchStart(ev){touchStartY=ev.touches?.[0]?.clientY??null;}
  function onInfoTouchMove(ev){if(!minLocked||touchStartY==null)return;const y=ev.touches?.[0]?.clientY??touchStartY,delta=y-touchStartY,s=gameCenterScroller();if(delta>28&&s&&s.scrollTop<=1){releaseMinLock({grow:true});touchStartY=y;}}

  function dispatch(){window.dispatchEvent(new CustomEvent('sbb:view-prefs',{detail:{keepVideoVisible:keep,gameCenterLayout:layout,sideActive:document.body.classList.contains('sbb-game-center-side')}}));}
  function applyClasses(){document.body.classList.toggle('sbb-keep-video-visible',keep);const side=layout==='side'&&sideEligible();document.body.classList.toggle('sbb-game-center-side',side);document.body.classList.toggle('sbb-game-center-below',!side);resetGeometry();dispatch();}
  function setKeep(v){keep=!!v;localStorage.setItem(KEEP_KEY,keep?'1':'0');applyClasses();}
  function setLayout(v){layout=v==='side'?'side':'below';localStorage.setItem(LAYOUT_KEY,layout);applyClasses();}

  function init(){
    ensurePlaceholder();ensureCompactChrome();observeCompactChrome();refreshStaticGeometry();bindScrollRoot();applyClasses();
    window.addEventListener('resize',()=>{resetGeometry();applyClasses();},{passive:true});
    window.addEventListener('orientationchange',()=>setTimeout(()=>{resetGeometry();applyClasses();},160),{passive:true});
    document.addEventListener('fullscreenchange',()=>setTimeout(()=>{resetGeometry();bindScrollRoot();schedule();},100));
    window.addEventListener('sbb:drawer-state',()=>{resetGeometry();if(canUseSticky())schedule();});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();

  window.SBB_VIEW_PREFS=Object.freeze({
    version:'1.7',setKeepVideoVisible:setKeep,setGameCenterLayout:setLayout,refresh:()=>{if(canUseSticky())schedule();},reset:resetGeometry,
    diagnostics:()=>({...diag,active,minLocked,blockingGestureListeners:lockGesturesBound,ordinaryScrollSchedulesJs:canUseSticky()}),
    get keepVideoVisible(){return keep;},get gameCenterLayout(){return layout;},get sideActive(){return document.body.classList.contains('sbb-game-center-side');},get gameCenterScrollLocked(){return minLocked;}
  });
})();

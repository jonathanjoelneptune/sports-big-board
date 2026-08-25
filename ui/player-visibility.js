/* v4.1.17 presentation-only Keep Video Visible controller.

   One bounded sticky workspace, two deterministic phases:
   1) The active page scroll shrinks the video while the in-flow Game Center edge
      remains attached below the visible player. A compact Now Playing + transport
      strip grows in beneath the shrinking video so the controls follow the player
      instead of disappearing from the workspace.
   2) At minimum size, BOTH the compact player workspace and information surface are
      fixed. The page scroll is no longer used for Game Center navigation; the active
      Game Center pane is the only scrollable surface.

   Upward gestures that start in the upper-page real estate reverse phase 1. The root
   cannot drift behind the fixed player while minimum-size handoff is active, avoiding
   the score-ribbon-behind-video state seen on Android Chromium.

   Playback ownership is never touched by this module. */
(() => {
  const KEEP_KEY='sbb.keepVideoVisible.v1';
  const LAYOUT_KEY='sbb.gameCenterLayout.v1';
  let keep=localStorage.getItem(KEEP_KEY)!=='0';
  let layout=localStorage.getItem(LAYOUT_KEY)||'side';
  let raf=0,anchorTop=null,baseRect=null,active=false,minLocked=false,lockScroll=0,boundRoot=null;
  let touchStartY=null;
  let upperTouchActive=false,upperTouchLastY=null,upperReverseGesture=false,correctingOuterScroll=false;
  let compactObserver=null;
  const $=id=>document.getElementById(id);
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));

  function sideEligible(){return !!window.matchMedia?.('(pointer:fine)').matches&&window.innerWidth>=1100;}
  function ensurePlaceholder(){
    const stage=$('stage');if(!stage)return null;
    let ph=$('sbbStagePlaceholder');
    if(!ph){ph=document.createElement('div');ph.id='sbbStagePlaceholder';ph.className='sbb-stage-placeholder';stage.parentNode?.insertBefore(ph,stage);}
    return ph;
  }
  function ensureCompactChrome(){
    let chrome=$('sbbCompactChrome');
    if(chrome)return chrome;
    const card=document.querySelector('.stage-card');if(!card)return null;
    chrome=document.createElement('div');
    chrome.id='sbbCompactChrome';
    chrome.className='sbb-compact-chrome';
    chrome.setAttribute('aria-hidden','true');
    chrome.innerHTML=`
      <div class="sbb-compact-copy">
        <span class="sbb-compact-league"></span>
        <strong class="sbb-compact-title">Now Playing</strong>
      </div>
      <div class="sbb-compact-transport" aria-label="Compact playback controls">
        <button type="button" class="sbb-compact-btn" data-proxy="prevBtn" aria-label="Previous highlight">⏮</button>
        <button type="button" class="sbb-compact-btn sbb-compact-play" data-proxy="playBtn" aria-label="Play or pause">Ⅱ</button>
        <button type="button" class="sbb-compact-btn" data-proxy="nextBtn" aria-label="Next highlight">⏭</button>
      </div>`;
    chrome.addEventListener('click',ev=>{
      const btn=ev.target?.closest?.('[data-proxy]');if(!btn)return;
      ev.preventDefault();ev.stopPropagation();
      const source=$(btn.dataset.proxy);if(source&&!source.disabled)source.click();
    });
    card.appendChild(chrome);
    syncCompactChrome();
    return chrome;
  }
  function syncCompactChrome(){
    const chrome=$('sbbCompactChrome');if(!chrome)return;
    const league=chrome.querySelector('.sbb-compact-league'),title=chrome.querySelector('.sbb-compact-title');
    if(league)league.textContent=String($('currentLeague')?.textContent||'').trim();
    if(title)title.textContent=String($('currentTitle')?.textContent||'Now Playing').trim()||'Now Playing';
    for(const id of ['prevBtn','playBtn','nextBtn']){
      const source=$(id),proxy=chrome.querySelector(`[data-proxy="${id}"]`);if(!proxy||!source)continue;
      proxy.textContent=source.textContent||proxy.textContent;
      proxy.disabled=!!source.disabled;
      proxy.setAttribute('aria-label',source.getAttribute('aria-label')||source.title||proxy.getAttribute('aria-label')||'Playback control');
      proxy.title=source.title||source.getAttribute('aria-label')||'';
      proxy.classList.toggle('is-buffering',source.classList.contains('is-buffering'));
    }
  }
  function observeCompactChrome(){
    if(compactObserver||!window.MutationObserver)return;
    compactObserver=new MutationObserver(syncCompactChrome);
    for(const id of ['currentLeague','currentTitle','prevBtn','playBtn','nextBtn']){
      const node=$(id);if(node)compactObserver.observe(node,{subtree:true,childList:true,characterData:true,attributes:true});
    }
  }
  function compactChromeHeight(){return (window.matchMedia?.('(pointer:coarse)').matches||window.innerWidth<820)?42:46;}
  function compactProgress(p){return clamp((p-.07)/.23,0,1);}
  function hideCompactChrome(){
    const chrome=$('sbbCompactChrome');if(!chrome)return;
    chrome.classList.remove('is-visible');chrome.setAttribute('aria-hidden','true');
    for(const prop of ['top','left','width','height','opacity','transform'])chrome.style.removeProperty(prop);
  }
  function setCompactChrome(left,width,videoBottom,p){
    const chrome=ensureCompactChrome();if(!chrome)return 8;
    syncCompactChrome();
    const q=compactProgress(p),fullHeight=compactChromeHeight();
    if(q<=.001){hideCompactChrome();return 8;}
    const topGap=4*q,barHeight=Math.max(1,fullHeight*q),opacity=clamp((q-.66)/.34,0,1);
    chrome.style.left=`${Math.round(left)}px`;
    chrome.style.top=`${Math.ceil(videoBottom+topGap)}px`;
    chrome.style.width=`${Math.round(width)}px`;
    chrome.style.height=`${Math.round(barHeight)}px`;
    chrome.style.opacity=String(opacity);
    chrome.style.transform=`translateY(${Math.round((1-opacity)*-4)}px)`;
    chrome.classList.toggle('is-visible',opacity>.03);
    chrome.setAttribute('aria-hidden',opacity>.03?'false':'true');
    return 8+q*(4+fullHeight);
  }

  function fullscreenRoot(){return document.fullscreenElement||document.webkitFullscreenElement||null;}
  function scrollRoot(){
    const fs=fullscreenRoot();
    if(fs&&fs.id==='app-shell')return fs;
    return document.scrollingElement||document.documentElement;
  }
  function rootIsDocument(root){return root===document.scrollingElement||root===document.documentElement||root===document.body;}
  function rootScroll(){const r=scrollRoot();return Number(rootIsDocument(r)?(window.scrollY||r?.scrollTop||0):(r?.scrollTop||0));}
  function setRootScroll(y){const r=scrollRoot();y=Math.max(0,Number(y)||0);if(rootIsDocument(r))window.scrollTo(0,y);else r.scrollTop=y;}
  function rootViewportTop(){const r=scrollRoot();return rootIsDocument(r)?0:(r.getBoundingClientRect().top||0);}
  function stickyTop(){
    const h=document.querySelector('.top-nav-header')?.getBoundingClientRect().height||0;
    const top=Math.max(0,h+4);document.documentElement.style.setProperty('--sbb-sticky-video-top',`${Math.ceil(top)}px`);return top;
  }
  function minFraction(){
    const coarse=window.matchMedia?.('(pointer:coarse)').matches;
    if(coarse)return window.matchMedia?.('(orientation:portrait)').matches?.66:.56;
    return .58;
  }
  function shrinkTravel(){return Math.max(180,Math.min(390,window.innerHeight*.42));}
  function clearStageInline(stage){if(!stage)return;for(const p of ['position','top','left','right','width','height','max-height','margin','z-index'])stage.style.removeProperty(p);stage.style.borderRadius='';}
  function gameCenterScroller(){return $('gameCenterPane');}

  function clearLockGeometry(){
    for(const x of ['--sbb-gc-lock-top','--sbb-gc-lock-left','--sbb-gc-lock-width','--sbb-gc-lock-bottom'])document.documentElement.style.removeProperty(x);
    document.body.classList.remove('sbb-gc-scroll-locked');
    minLocked=false;
  }
  function releaseMinLock({grow=false}={}){
    if(!minLocked)return;
    clearLockGeometry();
    if(grow)setRootScroll(Math.max(0,lockScroll-Math.max(4,shrinkTravel()*.035)));
    schedule();
  }
  function normalStage(){
    const stage=$('stage'),ph=ensurePlaceholder();
    clearLockGeometry();clearStageInline(stage);hideCompactChrome();
    if(ph){ph.style.display='none';ph.style.height='';}
    document.documentElement.style.removeProperty('--sbb-sticky-video-bottom');
    document.body.classList.remove('sbb-stage-sticky-active','sbb-stage-minimized');
    active=false;
  }
  function resetGeometry(){normalStage();anchorTop=null;baseRect=null;upperReverseGesture=false;bindScrollRoot();}
  function applyClasses(){
    document.body.classList.toggle('sbb-keep-video-visible',keep);
    // v4.1.17: a wide fine-pointer PC always uses the embedded right-side Game
    // Center workspace. Mobile/tablet keeps the proven below-video behavior.
    const side=sideEligible();
    document.body.classList.toggle('sbb-game-center-side',side);
    document.body.classList.toggle('sbb-game-center-below',!side);
    resetGeometry();schedule();
  }
  function capture(stage){const y=rootScroll(),r=stage.getBoundingClientRect(),rootTop=rootViewportTop();anchorTop=y+(r.top-rootTop);baseRect={left:r.left,width:r.width,height:r.height};}
  function fullscreenContainsInfo(info){const fs=fullscreenRoot();return !fs||fs===document.documentElement||fs===document.body||fs.contains?.(info);}

  function setFixedStage(stage,top,width,height,left,p){
    stage.style.setProperty('position','fixed','important');
    stage.style.setProperty('top',`${Math.ceil(top)}px`,'important');
    stage.style.setProperty('left',`${Math.round(left)}px`,'important');
    stage.style.setProperty('right','auto','important');
    stage.style.setProperty('width',`${Math.round(width)}px`,'important');
    stage.style.setProperty('height',`${Math.round(height)}px`,'important');
    stage.style.setProperty('margin','0','important');stage.style.setProperty('z-index','1400','important');stage.style.borderRadius=p>.04?'12px':'';
  }
  function lockWorkspace(info,workspaceTop){
    if(minLocked||!info)return;
    lockScroll=rootScroll();
    const r=info.getBoundingClientRect();
    document.documentElement.style.setProperty('--sbb-gc-lock-top',`${Math.ceil(workspaceTop)}px`);
    document.documentElement.style.setProperty('--sbb-gc-lock-left',`${Math.max(6,Math.round(r.left))}px`);
    document.documentElement.style.setProperty('--sbb-gc-lock-width',`${Math.max(1,Math.round(r.width))}px`);
    document.documentElement.style.setProperty('--sbb-gc-lock-bottom','6px');
    document.body.classList.add('sbb-gc-scroll-locked');minLocked=true;
    const scroller=gameCenterScroller();if(scroller)scroller.scrollTop=Math.max(0,scroller.scrollTop||0);
  }

  function update(){
    raf=0;
    const stage=$('stage'),info=$('infoDrawer'),ph=ensurePlaceholder();if(!stage||!info||!ph)return;
    const gameCenterActive=(window.SBB_INFO_DRAWER?.activeTab||'game-center')==='game-center';
    const usable=keep&&gameCenterActive&&info.classList.contains('is-open')&&!document.body.classList.contains('sbb-game-center-side')&&fullscreenContainsInfo(info);
    if(!usable){normalStage();anchorTop=null;baseRect=null;return;}

    // Once handed off, the outer scroll coordinate is intentionally irrelevant to
    // Game Center navigation. Keep it at the exact handoff position so Android
    // cannot move the score ribbon behind a still-minimized fixed player.
    if(minLocked){
      const top=stickyTop();
      const baseWidth=Math.max(1,baseRect?.width||stage.getBoundingClientRect().width),baseHeight=Math.max(1,baseRect?.height||baseWidth*9/16);
      const width=baseWidth*minFraction(),height=baseHeight*minFraction();
      const margin=8,maxLeft=Math.max(margin,window.innerWidth-width-margin),left=clamp((baseRect?.left||margin)+(baseWidth-width)/2,margin,maxLeft);
      setFixedStage(stage,top,width,height,left,1);
      const videoBottom=top+height,workspaceExtent=setCompactChrome(left,width,videoBottom,1),workspaceTop=videoBottom+workspaceExtent;
      document.documentElement.style.setProperty('--sbb-sticky-video-bottom',`${Math.ceil(videoBottom)}px`);
      document.documentElement.style.setProperty('--sbb-gc-lock-top',`${Math.ceil(workspaceTop)}px`);
      return;
    }

    const top=stickyTop(),y=rootScroll();if(anchorTop==null||!baseRect)capture(stage);
    const consumed=Math.max(0,y+top-anchorTop);
    if(consumed<=.5){if(active)normalStage();return;}
    const travel=shrinkTravel(),p=clamp(consumed/travel,0,1);
    if(!active){const r=stage.getBoundingClientRect();baseRect={left:r.left,width:r.width,height:r.height};ph.style.display='block';active=true;document.body.classList.add('sbb-stage-sticky-active');}
    const baseWidth=Math.max(1,baseRect.width),baseHeight=Math.max(1,baseRect.height||baseWidth*9/16);
    const frac=1-p*(1-minFraction()),width=baseWidth*frac,height=baseHeight*frac;
    const margin=8,maxLeft=Math.max(margin,window.innerWidth-width-margin),left=clamp(baseRect.left+(baseWidth-width)/2,margin,maxLeft);
    setFixedStage(stage,top,width,height,left,p);

    // Exact attachment equation: original drawer flow position - outer scroll =
    // fixed video bottom + compact chrome + 8px. The compact chrome grows in as the
    // player shrinks, so there is no abrupt title/control jump at the sticky threshold.
    const flowTravel=Math.min(consumed,travel),videoBottom=top+height,workspaceExtent=setCompactChrome(left,width,videoBottom,p);
    ph.style.height=`${Math.max(1,Math.round(height+flowTravel+workspaceExtent))}px`;
    document.documentElement.style.setProperty('--sbb-sticky-video-bottom',`${Math.ceil(videoBottom)}px`);
    const atMin=p>=.999;document.body.classList.toggle('sbb-stage-minimized',atMin);
    if(atMin)lockWorkspace(info,videoBottom+workspaceExtent);
  }
  function schedule(){if(!raf)raf=requestAnimationFrame(update);}
  function onRootScroll(){
    if(minLocked&&!upperReverseGesture&&!correctingOuterScroll){
      const y=rootScroll();
      if(Math.abs(y-lockScroll)>1){
        correctingOuterScroll=true;setRootScroll(lockScroll);
        requestAnimationFrame(()=>{correctingOuterScroll=false;schedule();});
        return;
      }
    }
    schedule();
  }
  function bindScrollRoot(){
    const next=scrollRoot();if(boundRoot===next)return;
    if(boundRoot===window)window.removeEventListener('scroll',onRootScroll);else boundRoot?.removeEventListener?.('scroll',onRootScroll);
    if(rootIsDocument(next)){boundRoot=window;window.addEventListener('scroll',onRootScroll,{passive:true});}else{boundRoot=next;next.addEventListener('scroll',onRootScroll,{passive:true});}
  }

  function targetInsideInfo(target){return !!target?.closest?.('#infoDrawer');}
  function targetIsUpperInteractive(target){return !!target?.closest?.('button,a,input,select,textarea,video,iframe,[contenteditable="true"]');}
  function onUpperWheel(ev){
    if(targetInsideInfo(ev.target)||!minLocked)return;
    ev.preventDefault();
    if(ev.deltaY<0){
      const delta=Math.max(-Math.min(shrinkTravel()*.28,120),ev.deltaY);
      clearLockGeometry();upperReverseGesture=true;
      setRootScroll(Math.max(0,lockScroll+delta));schedule();
      requestAnimationFrame(()=>{upperReverseGesture=false;});
    }
  }
  function onUpperTouchStart(ev){
    if(!minLocked||targetInsideInfo(ev.target)||targetIsUpperInteractive(ev.target)){upperTouchActive=false;upperTouchLastY=null;return;}
    upperTouchActive=true;upperTouchLastY=ev.touches?.[0]?.clientY??null;upperReverseGesture=false;
  }
  function onUpperTouchMove(ev){
    if(!upperTouchActive||upperTouchLastY==null)return;
    const y=ev.touches?.[0]?.clientY??upperTouchLastY,delta=y-upperTouchLastY;upperTouchLastY=y;
    if(minLocked){
      ev.preventDefault();
      if(delta>0){
        clearLockGeometry();upperReverseGesture=true;
        setRootScroll(Math.max(0,lockScroll-delta));schedule();
      }
      return;
    }
    if(upperReverseGesture){
      ev.preventDefault();
      if(Math.abs(delta)>.2){setRootScroll(Math.max(0,rootScroll()-delta));schedule();}
    }
  }
  function onUpperTouchEnd(){upperTouchActive=false;upperTouchLastY=null;upperReverseGesture=false;}

  function onInfoWheel(ev){if(!minLocked||ev.deltaY>=0)return;const s=gameCenterScroller();if(s&&s.scrollTop<=1){ev.preventDefault();releaseMinLock({grow:true});}}
  function onInfoTouchStart(ev){touchStartY=ev.touches?.[0]?.clientY??null;}
  function onInfoTouchMove(ev){
    if(!minLocked||touchStartY==null)return;
    const y=ev.touches?.[0]?.clientY??touchStartY,delta=y-touchStartY,s=gameCenterScroller();
    if(delta>28&&s&&s.scrollTop<=1){releaseMinLock({grow:true});touchStartY=y;}
  }
  function setKeep(v){keep=!!v;localStorage.setItem(KEEP_KEY,keep?'1':'0');applyClasses();dispatch();}
  function setLayout(v){layout=v==='side'?'side':'below';localStorage.setItem(LAYOUT_KEY,layout);applyClasses();dispatch();}
  function dispatch(){window.dispatchEvent(new CustomEvent('sbb:view-prefs',{detail:{keepVideoVisible:keep,gameCenterLayout:layout,sideActive:document.body.classList.contains('sbb-game-center-side')}}));}
  function init(){
    ensurePlaceholder();ensureCompactChrome();observeCompactChrome();bindScrollRoot();applyClasses();stickyTop();
    window.addEventListener('resize',()=>{resetGeometry();applyClasses();stickyTop();},{passive:true});
    window.addEventListener('orientationchange',()=>setTimeout(()=>{resetGeometry();applyClasses();},160),{passive:true});
    document.addEventListener('fullscreenchange',()=>setTimeout(()=>{resetGeometry();bindScrollRoot();schedule();},100));
    window.addEventListener('sbb:drawer-state',()=>{resetGeometry();schedule();});
    document.addEventListener('wheel',onUpperWheel,{passive:false,capture:true});
    document.addEventListener('touchstart',onUpperTouchStart,{passive:true,capture:true});
    document.addEventListener('touchmove',onUpperTouchMove,{passive:false,capture:true});
    document.addEventListener('touchend',onUpperTouchEnd,{passive:true,capture:true});
    document.addEventListener('touchcancel',onUpperTouchEnd,{passive:true,capture:true});
    $('infoDrawer')?.addEventListener('wheel',onInfoWheel,{passive:false});
    $('infoDrawer')?.addEventListener('touchstart',onInfoTouchStart,{passive:true});
    $('infoDrawer')?.addEventListener('touchmove',onInfoTouchMove,{passive:true});
    dispatch();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
  window.SBB_VIEW_PREFS=Object.freeze({version:'1.6',setKeepVideoVisible:setKeep,setGameCenterLayout:setLayout,refresh:schedule,reset:resetGeometry,get keepVideoVisible(){return keep;},get gameCenterLayout(){return layout;},get sideActive(){return document.body.classList.contains('sbb-game-center-side');},get gameCenterScrollLocked(){return minLocked;}});
})();

/* Sports Big Board v4.5.0 — Media Intelligence + poisoned-media containment.
   One browser authority consumes persisted music intelligence and owns the hard
   quarantine boundary BEFORE media can be assigned to a native/YouTube player. */
(() => {
  'use strict';
  if (window.SBB_MEDIA_INTELLIGENCE) return;

  const registry=new Map(),quarantined=new Map(),blockedUrls=new Set(),blockedYoutubeIds=new Set(),listeners=new Set();
  const stats={registered:0,quarantineAborts:0,preloadBlocks:0,orphanedLoads:0,quarantines:0,soundtrackSuppressions:0,soundtrackAllows:0};
  let currentSession=null,lastSuppress=null,ytPatchTimer=0;
  const clean=(v,n=1000)=>String(v??'').trim().slice(0,n);
  const ACTIVE_AUDIO_STATES=new Set(['playing','buffering']);
  const ASSET_FAILURE_RE=/youtube error\s*(101|150)\b|media_err_decode|media_err_src_not_supported|http\s*(404|410)\b|\b(404|410)\b[^\n]*(not found|gone)|unsupported (media|source)|invalid (media|source) url|malformed (media|source)|stale historical media/i;

  function playbackKey(asset){
    if(typeof asset==='string')return clean(asset,1500);
    try{const key=window.SBB_PLAYBACK_TRANSPORTS?.playbackKey?.(asset);if(key&&key!=='unsupported')return clean(key,1500);}catch(_){ }
    const explicit=clean(asset?.mediaKey||asset?.manifestAssetKey||asset?.assetKey||'',1500);if(explicit)return explicit;
    if(asset?.youtubeId)return `youtube:${clean(asset.youtubeId,200)}`;
    if(asset?.mediaUrl)return `direct:${clean(asset.mediaUrl,1400)}`;
    return clean(asset?.id||asset?.mediaId||'',1500);
  }
  function musicStatus(asset){
    const raw=clean(asset?.musicStatus||asset?.music_status||asset?.mediaIntelligence?.musicStatus||'UNKNOWN',40).toUpperCase().replace(/[ -]/g,'_');
    return ['HAS_MUSIC','NO_MUSIC','UNKNOWN','SCAN_FAILED','PENDING'].includes(raw)?raw:'UNKNOWN';
  }
  function intelligenceFrom(asset,key=''){
    const status=musicStatus(asset),explicit=asset?.musicConflict;
    const conflict=typeof explicit==='boolean'?explicit:status!=='NO_MUSIC';
    return {key:key||playbackKey(asset),status,conflict,confidence:Number(asset?.musicConfidence||asset?.music_confidence||0)||0,
      ratio:Number(asset?.musicRatio||asset?.music_ratio||0)||0,scanVersion:Number(asset?.musicScanVersion||asset?.music_scan_version||0)||0,
      scannedAt:Number(asset?.musicScannedAt||asset?.music_scanned_at||0)||0,title:clean(asset?.title||'',180)};
  }
  function notify(type,detail={}){
    const payload={type,at:Date.now(),...detail};for(const fn of [...listeners]){try{fn(payload);}catch(_){ }}
    try{window.dispatchEvent(new CustomEvent('sbb:media-intelligence',{detail:payload}));}catch(_){ }
  }
  function register(asset){
    if(!asset)return null;const key=playbackKey(asset);if(!key)return null;
    const next=intelligenceFrom(asset,key),prev=registry.get(key);
    registry.set(key,{...(prev||{}),...next});
    // Add transport-stable aliases so session/media-manifest identities resolve to
    // the same database intelligence even when one path uses an explicit key.
    if(asset?.youtubeId)registry.set(`youtube:${clean(asset.youtubeId,200)}`,registry.get(key));
    if(asset?.mediaUrl)registry.set(`direct:${clean(asset.mediaUrl,1400)}`,registry.get(key));
    stats.registered=registry.size;notify('registered',{key,status:next.status,conflict:next.conflict});
    reconcileSoundtrack();return {...registry.get(key)};
  }
  function decisionForKey(rawKey){
    const key=clean(rawKey,1500),info=registry.get(key);
    if(info)return {...info};
    return {key,status:'UNKNOWN',conflict:true,confidence:0,ratio:0,scanVersion:0,scannedAt:0,title:''};
  }
  function soundtrackAudio(){return window.__SBB_SOUNDTRACK_SINGLETON__?.audio||null;}
  function soundtrackShouldSuppress(session=currentSession){
    const state=clean(session?.state||'',30).toLowerCase();
    const videoAudibleState=ACTIVE_AUDIO_STATES.has(state)&&!!session?.firstFrameAt;
    if(!videoAudibleState)return false;
    return decisionForKey(session?.mediaKey||session?.clipKey||'').conflict!==false;
  }
  function reconcileSoundtrack(session=currentSession){
    if(session)currentSession=session;const audio=soundtrackAudio();if(!audio)return false;
    const suppress=soundtrackShouldSuppress(currentSession);
    try{audio.muted=!!suppress;}catch(_){ }
    if(lastSuppress!==suppress){
      lastSuppress=suppress;if(suppress)stats.soundtrackSuppressions++;else stats.soundtrackAllows++;
      const info=decisionForKey(currentSession?.mediaKey||currentSession?.clipKey||'');
      notify('soundtrack-arbitration',{suppress,status:info.status,mediaKey:info.key});
    }
    try{window.SBB_PLAYBACK_SESSION?.setAudible?.('soundtrack','site',!suppress&&!audio.paused&&Number(audio.volume)>0);}catch(_){ }
    try{document.body?.setAttribute?.('data-sbb-media-music',decisionForKey(currentSession?.mediaKey||'').status);}catch(_){ }
    return suppress;
  }

  function decodeProxyUrl(value){
    const raw=clean(value,4000);if(!raw)return '';
    try{
      const u=new URL(raw,document.baseURI||location.href);
      if(u.pathname.endsWith('/api/media')&&u.searchParams.get('url'))return decodeURIComponent(u.searchParams.get('url'));
    }catch(_){ }
    return raw;
  }
  function youtubeIdFromValue(value){
    const raw=clean(value,4000);if(!raw)return '';
    const direct=raw.match(/(?:youtube(?:-nocookie)?\.com\/(?:embed|shorts)\/|youtu\.be\/)([A-Za-z0-9_-]{6,})/i);if(direct)return direct[1];
    try{const u=new URL(raw,document.baseURI||location.href);return clean(u.searchParams.get('v')||'',200);}catch(_){return '';}
  }
  function matchesBlockedSource(value){
    const raw=clean(value,4000);if(!raw)return false;const decoded=decodeProxyUrl(raw);
    if(blockedUrls.has(raw)||blockedUrls.has(decoded))return true;
    for(const url of blockedUrls){if(raw.includes(encodeURIComponent(url))||decoded===url)return true;}
    const yt=youtubeIdFromValue(raw);return !!yt&&blockedYoutubeIds.has(yt);
  }
  function targetFor(value){
    const key=playbackKey(value);let direct='',youtube='';
    if(typeof value==='object'&&value){direct=clean(value.mediaUrl||value.sourceUrl||'',3000);youtube=clean(value.youtubeId||'',200);}
    if(key.startsWith('direct:'))direct=key.slice(7);
    if(key.startsWith('youtube:'))youtube=key.slice(8);
    return {key,direct,youtube};
  }

  const mediaProto=(typeof HTMLMediaElement!=='undefined'&&HTMLMediaElement.prototype)||null;
  const nativeMedia={
    srcDesc:mediaProto?Object.getOwnPropertyDescriptor(mediaProto,'src'):null,
    setAttribute:mediaProto?.setAttribute,
    removeAttribute:mediaProto?.removeAttribute,
    load:mediaProto?.load,
    pause:mediaProto?.pause,
    play:mediaProto?.play
  };
  function elementSource(el){
    try{return clean(el?.currentSrc||el?.src||el?.getAttribute?.('src')||'',4000);}catch(_){return '';}
  }
  function abortNativeElement(el,reason='quarantine',{force=false}={}){
    if(!el)return false;const src=elementSource(el);if(!force&&src&&!matchesBlockedSource(src))return false;
    try{nativeMedia.pause?.call(el);}catch(_){try{el.pause?.();}catch(__){ }}
    try{nativeMedia.removeAttribute?.call(el,'src');}catch(_){try{el.removeAttribute?.('src');}catch(__){ }}
    try{nativeMedia.load?.call(el);}catch(_){ }
    try{el.dataset.sbbQuarantineAborted='1';el.dataset.sbbQuarantineReason=clean(reason,100);}catch(_){ }
    stats.quarantineAborts++;return true;
  }
  function stopYoutubeIframe(frame,id=''){
    if(!frame)return false;const src=clean(frame.src||frame.getAttribute?.('src')||'',4000),found=id||youtubeIdFromValue(src);
    if(found&&!blockedYoutubeIds.has(found))return false;
    try{
      const post=fn=>frame.contentWindow?.postMessage?.(JSON.stringify({event:'command',func:fn,args:[]}), '*');
      post('stopVideo');post('clearVideo');
      frame.dataset.sbbQuarantineAborted='1';stats.quarantineAborts++;return true;
    }catch(_){return false;}
  }
  function activeBlockedLoads(){
    let count=0;
    try{for(const el of document.querySelectorAll?.('video,audio')||[]){const src=elementSource(el);if(src&&matchesBlockedSource(src))count++;}}catch(_){ }
    try{for(const frame of document.querySelectorAll?.('iframe')||[]){const yt=youtubeIdFromValue(frame.src||'');if(yt&&blockedYoutubeIds.has(yt))count++;}}catch(_){ }
    return count;
  }
  function abortMatchingResources(reason='quarantine'){
    try{for(const el of document.querySelectorAll?.('video,audio')||[]){const src=elementSource(el);if(src&&matchesBlockedSource(src))abortNativeElement(el,reason);}}catch(_){ }
    try{for(const frame of document.querySelectorAll?.('iframe')||[]){const yt=youtubeIdFromValue(frame.src||'');if(yt&&blockedYoutubeIds.has(yt))stopYoutubeIframe(frame,yt);}}catch(_){ }
    const orphaned=activeBlockedLoads();stats.orphanedLoads=orphaned;return orphaned;
  }
  function installNativeGuards(){
    if(!mediaProto||mediaProto.__sbbMediaIntelligenceGuard)return;
    try{Object.defineProperty(mediaProto,'__sbbMediaIntelligenceGuard',{value:true,configurable:false});}catch(_){mediaProto.__sbbMediaIntelligenceGuard=true;}
    if(nativeMedia.srcDesc?.set){
      try{Object.defineProperty(mediaProto,'src',{configurable:nativeMedia.srcDesc.configurable,enumerable:nativeMedia.srcDesc.enumerable,get:nativeMedia.srcDesc.get,
        set:function(value){if(matchesBlockedSource(value)){stats.preloadBlocks++;abortNativeElement(this,'pre-assignment src block',{force:true});notify('preload-blocked',{source:clean(value,500)});return;}return nativeMedia.srcDesc.set.call(this,value);}});}catch(_){ }
    }
    if(nativeMedia.setAttribute){mediaProto.setAttribute=function(name,value){if(String(name).toLowerCase()==='src'&&matchesBlockedSource(value)){stats.preloadBlocks++;abortNativeElement(this,'pre-assignment attribute block',{force:true});notify('preload-blocked',{source:clean(value,500)});return;}return nativeMedia.setAttribute.call(this,name,value);};}
    if(nativeMedia.load){mediaProto.load=function(){const src=elementSource(this);if(src&&matchesBlockedSource(src)){stats.preloadBlocks++;abortNativeElement(this,'load block');return;}return nativeMedia.load.call(this);};}
    if(nativeMedia.play){mediaProto.play=function(){const src=elementSource(this);if(src&&matchesBlockedSource(src)){stats.preloadBlocks++;abortNativeElement(this,'play block');return Promise.reject(new Error('SBB_QUARANTINED_MEDIA'));}return nativeMedia.play.call(this);};}
  }
  function patchYouTubePlayer(){
    const proto=window.YT?.Player?.prototype;if(!proto||proto.__sbbMediaIntelligenceGuard)return false;
    try{Object.defineProperty(proto,'__sbbMediaIntelligenceGuard',{value:true});}catch(_){proto.__sbbMediaIntelligenceGuard=true;}
    for(const method of ['loadVideoById','cueVideoById']){
      const original=proto[method];if(typeof original!=='function')continue;
      proto[method]=function(arg,...rest){const id=clean(typeof arg==='object'?arg?.videoId:arg,200);if(id&&blockedYoutubeIds.has(id)){stats.preloadBlocks++;try{this.stopVideo?.();this.clearVideo?.();}catch(_){ }notify('preload-blocked',{youtubeId:id});return;}return original.call(this,arg,...rest);};
    }
    return true;
  }
  function installYouTubeGuard(){
    if(patchYouTubePlayer())return;let tries=0;ytPatchTimer=setInterval(()=>{tries++;if(patchYouTubePlayer()||tries>240){clearInterval(ytPatchTimer);ytPatchTimer=0;}},250);
  }
  function quarantine(value,reason='runtime-unplayable'){
    const target=targetFor(value);if(!target.key)return false;
    if(!quarantined.has(target.key)){stats.quarantines++;quarantined.set(target.key,{...target,reason:clean(reason,300),at:Date.now()});}
    if(target.direct)blockedUrls.add(target.direct);if(target.youtube)blockedYoutubeIds.add(target.youtube);
    // Preserve aliases so either app/session identity is hard-blocked.
    if(target.direct)quarantined.set(`direct:${target.direct}`,quarantined.get(target.key));
    if(target.youtube)quarantined.set(`youtube:${target.youtube}`,quarantined.get(target.key));
    abortMatchingResources(reason);setTimeout(()=>abortMatchingResources(reason),80);setTimeout(()=>abortMatchingResources(reason),350);
    notify('quarantined',{mediaKey:target.key,reason:clean(reason,300)});return true;
  }
  function isQuarantined(value){const target=targetFor(value);return !!target.key&&quarantined.has(target.key);}
  function snapshot(){return {...stats,registered:registry.size,quarantined:quarantined.size,blockedUrls:blockedUrls.size,blockedYoutubeIds:blockedYoutubeIds.size,activeBlockedLoads:activeBlockedLoads(),currentMediaKey:clean(currentSession?.mediaKey||'',1000),currentDecision:decisionForKey(currentSession?.mediaKey||'')};}
  function subscribe(fn){if(typeof fn!=='function')return()=>{};listeners.add(fn);return()=>listeners.delete(fn);}

  installNativeGuards();installYouTubeGuard();
  try{window.SBB_MEDIA_MANIFEST?.subscribe?.((manifest,evt)=>{if(evt?.asset)register(evt.asset);else for(const asset of manifest?.assets||[])register(asset);});}catch(_){ }
  try{window.SBB_PLAYBACK_SESSION?.subscribe?.(session=>{
    currentSession=session||null;
    if(session?.state==='failed'&&ASSET_FAILURE_RE.test(clean(session?.lastError||'',500))){quarantine({mediaKey:session.mediaKey,sourceUrl:session.sourceUrl},session.lastError);}
    reconcileSoundtrack(session);
  });}catch(_){ }
  try{new MutationObserver(()=>{abortMatchingResources('mutation guard');}).observe(document.documentElement,{subtree:true,attributes:true,attributeFilter:['src']});}catch(_){ }
  if(typeof window.markRuntimeMediaFailed!=='function')window.markRuntimeMediaFailed=(item,reason='runtime playback failure')=>{
    if(ASSET_FAILURE_RE.test(clean(reason,500)))return quarantine(item,reason);return false;
  };
  const api=Object.freeze({version:'1.0',register,decisionForKey,musicStatus,quarantine,isQuarantined,abortMatchingResources,reconcileSoundtrack,snapshot,subscribe});
  window.SBB_MEDIA_INTELLIGENCE=api;window.SBB_MEDIA_QUARANTINE=api;
  reconcileSoundtrack();
})();

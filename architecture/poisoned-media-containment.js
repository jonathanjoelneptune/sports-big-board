/* Sports Big Board v4.4.7 — asset-local poisoned-player containment.
   Purposefully separate from Media Intelligence. A quarantined native/YouTube
   asset is blocked BEFORE assignment, matching resources are torn down locally,
   and healthy playback is never reset because one asset is bad. */
(() => {
  'use strict';
  if (window.SBB_POISON_CONTAINMENT) return;

  const VERSION='1.0';
  const clean=(v,n=1800)=>String(v??'').trim().slice(0,n);
  const quarantined=new Map(),blockedUrls=new Set(),blockedYoutubeIds=new Set(),listeners=new Set();
  const stats={quarantines:0,quarantineAborts:0,preloadBlocks:0,orphanedLoads:0};
  let ytPatchTimer=0;
  const ASSET_FAILURE_RE=/youtube error\s*(101|150)\b|media_err_decode|media_err_src_not_supported|http\s*(404|410)\b|\b(404|410)\b[^\n]*(not found|gone)|unsupported (media|source)|invalid (media|source) url|malformed (media|source)|stale historical media|no first frame/i;

  function playbackKey(asset){
    if(typeof asset==='string')return clean(asset);
    try{const key=window.SBB_PLAYBACK_TRANSPORTS?.playbackKey?.(asset);if(key&&key!=='unsupported')return clean(key);}catch(_){}
    const explicit=clean(asset?.mediaKey||asset?.manifestAssetKey||asset?.assetKey||'');if(explicit)return explicit;
    if(asset?.youtubeId)return `youtube:${clean(asset.youtubeId,200)}`;
    if(asset?.mediaUrl)return `direct:${clean(asset.mediaUrl,1500)}`;
    return clean(asset?.id||asset?.mediaId||'');
  }
  function decodeProxyUrl(value){
    const raw=clean(value,4000);if(!raw)return '';
    try{
      const u=new URL(raw,document.baseURI||location.href);
      if(u.pathname.endsWith('/api/media')&&u.searchParams.get('url'))return decodeURIComponent(u.searchParams.get('url'));
    }catch(_){}
    return raw;
  }
  function youtubeIdFromValue(value){
    const raw=clean(value,4000);if(!raw)return '';
    const direct=raw.match(/(?:youtube(?:-nocookie)?\.com\/(?:embed|shorts)\/|youtu\.be\/)([A-Za-z0-9_-]{6,})/i);
    if(direct)return direct[1];
    try{const u=new URL(raw,document.baseURI||location.href);return clean(u.searchParams.get('v')||'',200);}catch(_){return '';}
  }
  function targetFor(value){
    const key=playbackKey(value);let direct='',youtube='';
    if(typeof value==='object'&&value){direct=clean(value.mediaUrl||value.sourceUrl||'',3000);youtube=clean(value.youtubeId||'',200);}
    if(key.startsWith('direct:'))direct=key.slice(7);
    if(key.startsWith('youtube:'))youtube=key.slice(8);
    return {key,direct,youtube};
  }
  function matchesBlockedSource(value){
    const raw=clean(value,4000);if(!raw)return false;const decoded=decodeProxyUrl(raw);
    if(blockedUrls.has(raw)||blockedUrls.has(decoded))return true;
    for(const url of blockedUrls){if(raw.includes(encodeURIComponent(url))||decoded===url)return true;}
    const yt=youtubeIdFromValue(raw);return !!yt&&blockedYoutubeIds.has(yt);
  }
  function notify(type,detail={}){
    const payload={type,at:Date.now(),...detail};
    for(const fn of [...listeners]){try{fn(payload);}catch(_){}}
    try{window.dispatchEvent(new CustomEvent('sbb:poison-containment',{detail:payload}));}catch(_){}
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
    if(!el)return false;const src=elementSource(el);
    if(!force&&src&&!matchesBlockedSource(src))return false;
    try{nativeMedia.pause?.call(el);}catch(_){try{el.pause?.();}catch(__){}}
    try{nativeMedia.removeAttribute?.call(el,'src');}catch(_){try{el.removeAttribute?.('src');}catch(__){}}
    try{nativeMedia.load?.call(el);}catch(_){}
    try{el.dataset.sbbQuarantineAborted='1';el.dataset.sbbQuarantineReason=clean(reason,120);}catch(_){}
    stats.quarantineAborts++;return true;
  }
  function stopYoutubeIframe(frame,id=''){
    if(!frame)return false;
    const src=clean(frame.src||frame.getAttribute?.('src')||'',4000),found=id||youtubeIdFromValue(src);
    if(found&&!blockedYoutubeIds.has(found))return false;
    try{
      const post=fn=>frame.contentWindow?.postMessage?.(JSON.stringify({event:'command',func:fn,args:[]}), '*');
      post('stopVideo');post('clearVideo');
      frame.dataset.sbbQuarantineAborted='1';stats.quarantineAborts++;return true;
    }catch(_){return false;}
  }
  function activeBlockedLoads(){
    let count=0;
    try{for(const el of document.querySelectorAll?.('video')||[]){const src=elementSource(el);if(src&&matchesBlockedSource(src))count++;}}catch(_){}
    try{for(const frame of document.querySelectorAll?.('iframe')||[]){const yt=youtubeIdFromValue(frame.src||'');if(yt&&blockedYoutubeIds.has(yt))count++;}}catch(_){}
    return count;
  }
  function abortMatchingResources(reason='quarantine'){
    try{for(const el of document.querySelectorAll?.('video')||[]){const src=elementSource(el);if(src&&matchesBlockedSource(src))abortNativeElement(el,reason);}}catch(_){}
    try{for(const frame of document.querySelectorAll?.('iframe')||[]){const yt=youtubeIdFromValue(frame.src||'');if(yt&&blockedYoutubeIds.has(yt))stopYoutubeIframe(frame,yt);}}catch(_){}
    stats.orphanedLoads=activeBlockedLoads();
    return stats.orphanedLoads;
  }
  function installNativeGuards(){
    if(!mediaProto||mediaProto.__sbbPoisonContainmentGuard)return;
    try{Object.defineProperty(mediaProto,'__sbbPoisonContainmentGuard',{value:true,configurable:false});}catch(_){mediaProto.__sbbPoisonContainmentGuard=true;}
    if(nativeMedia.srcDesc?.set){
      try{Object.defineProperty(mediaProto,'src',{
        configurable:nativeMedia.srcDesc.configurable,enumerable:nativeMedia.srcDesc.enumerable,get:nativeMedia.srcDesc.get,
        set:function(value){
          if(matchesBlockedSource(value)){
            stats.preloadBlocks++;abortNativeElement(this,'pre-assignment src block',{force:true});
            notify('preload-blocked',{source:clean(value,500)});return;
          }
          return nativeMedia.srcDesc.set.call(this,value);
        }
      });}catch(_){}
    }
    if(nativeMedia.setAttribute){
      mediaProto.setAttribute=function(name,value){
        if(String(name).toLowerCase()==='src'&&matchesBlockedSource(value)){
          stats.preloadBlocks++;abortNativeElement(this,'pre-assignment attribute block',{force:true});
          notify('preload-blocked',{source:clean(value,500)});return;
        }
        return nativeMedia.setAttribute.call(this,name,value);
      };
    }
    if(nativeMedia.load){
      mediaProto.load=function(){
        const src=elementSource(this);
        if(src&&matchesBlockedSource(src)){stats.preloadBlocks++;abortNativeElement(this,'load block');return;}
        return nativeMedia.load.call(this);
      };
    }
    if(nativeMedia.play){
      mediaProto.play=function(){
        const src=elementSource(this);
        if(src&&matchesBlockedSource(src)){
          stats.preloadBlocks++;abortNativeElement(this,'play block');
          return Promise.reject(new Error('SBB_QUARANTINED_MEDIA'));
        }
        return nativeMedia.play.call(this);
      };
    }
  }
  function patchYouTubePlayer(){
    const proto=window.YT?.Player?.prototype;if(!proto||proto.__sbbPoisonContainmentGuard)return false;
    try{Object.defineProperty(proto,'__sbbPoisonContainmentGuard',{value:true});}catch(_){proto.__sbbPoisonContainmentGuard=true;}
    for(const method of ['loadVideoById','cueVideoById']){
      const original=proto[method];if(typeof original!=='function')continue;
      proto[method]=function(arg,...rest){
        const id=clean(typeof arg==='object'?arg?.videoId:arg,200);
        if(id&&blockedYoutubeIds.has(id)){
          stats.preloadBlocks++;
          try{this.stopVideo?.();this.clearVideo?.();}catch(_){}
          notify('preload-blocked',{youtubeId:id});return;
        }
        return original.call(this,arg,...rest);
      };
    }
    return true;
  }
  function installYouTubeGuard(){
    if(patchYouTubePlayer())return;
    let tries=0;
    ytPatchTimer=setInterval(()=>{tries++;if(patchYouTubePlayer()||tries>240){clearInterval(ytPatchTimer);ytPatchTimer=0;}},250);
  }
  function quarantine(value,reason='runtime-unplayable'){
    const target=targetFor(value);if(!target.key)return false;
    if(!quarantined.has(target.key)){
      quarantined.set(target.key,{...target,reason:clean(reason,300),at:Date.now()});stats.quarantines++;
    }
    if(target.direct)blockedUrls.add(target.direct);
    if(target.youtube)blockedYoutubeIds.add(target.youtube);
    if(target.direct)quarantined.set(`direct:${target.direct}`,quarantined.get(target.key));
    if(target.youtube)quarantined.set(`youtube:${target.youtube}`,quarantined.get(target.key));
    abortMatchingResources(reason);
    setTimeout(()=>abortMatchingResources(reason),80);
    setTimeout(()=>abortMatchingResources(reason),350);
    notify('quarantined',{mediaKey:target.key,reason:clean(reason,300)});
    return true;
  }
  function noteFailure(value,reason='runtime playback failure'){
    return ASSET_FAILURE_RE.test(clean(reason,600))?quarantine(value,reason):false;
  }
  function isQuarantined(value){const target=targetFor(value);return !!target.key&&quarantined.has(target.key);}
  function snapshot(){
    const active=activeBlockedLoads();stats.orphanedLoads=active;
    return {...stats,quarantined:quarantined.size,blockedUrls:blockedUrls.size,blockedYoutubeIds:blockedYoutubeIds.size,activeBlockedLoads:active};
  }
  function subscribe(fn){if(typeof fn!=='function')return()=>{};listeners.add(fn);return()=>listeners.delete(fn);}

  installNativeGuards();installYouTubeGuard();
  try{
    window.SBB_PLAYBACK_SESSION?.subscribe?.(session=>{
      if(session?.state==='failed'&&ASSET_FAILURE_RE.test(clean(session?.lastError||'',600))){
        quarantine({mediaKey:session.mediaKey,sourceUrl:session.sourceUrl},session.lastError);
      }
    });
  }catch(_){}

  const api=Object.freeze({version:VERSION,quarantine,noteFailure,isQuarantined,abortMatchingResources,activeBlockedLoads,snapshot,subscribe});
  window.SBB_POISON_CONTAINMENT=api;
  window.SBB_MEDIA_QUARANTINE=api; // compatibility alias; no Media Intelligence exists.
})();

/* Sports Big Board v4.4.8 — recap physical-identity guard.
   Recap-version controls are allowed to switch only to a different physical
   playback asset. Different DB IDs/provenance rows pointing to one YouTube ID or
   direct URL are not separate Quick/Extended choices. */
(() => {
  'use strict';
  if(window.SBB_RECAP_IDENTITY_GUARD)return;
  const VERSION='1.0';
  const physicalKey=item=>{
    try{return window.SBB_PLAYBACK_TRANSPORTS?.playbackKey?.(item)||String(item?.youtubeId?`youtube:${item.youtubeId}`:(item?.mediaUrl?`direct:${item.mediaUrl}`:(item?.id||'')));}catch(_){return String(item?.youtubeId||item?.mediaUrl||item?.id||'');}
  };
  const originalTarget=typeof window.recapTargetForTier==='function'?window.recapTargetForTier:null;
  const originalSwitch=typeof window.switchRecapVersion==='function'?window.switchRecapVersion:null;

  function distinctTargetForTier(item,tier){
    if(!item)return null;
    const currentKey=physicalKey(item);
    let candidates=[];
    try{candidates=typeof recapAlternatesFor==='function'?recapAlternatesFor(item):[];}catch(_){candidates=[];}
    candidates=(candidates||[]).filter(x=>{
      let t='';try{t=window.SBB_MEDIA_CLASSIFIER?.tier?.(x)||'';}catch(_){}
      return t===tier && physicalKey(x) && physicalKey(x)!==currentKey;
    });
    try{
      candidates.sort((a,b)=>(typeof overviewQuality==='function'?overviewQuality(b)-overviewQuality(a):0)||
                              (typeof sourceQuality==='function'?sourceQuality(b)-sourceQuality(a):0));
    }catch(_){}
    return candidates[0]||null;
  }

  // Override the global function binding used by switchRecapVersion. If the legacy
  // target happens to be the same physical media, find a real distinct alternate.
  if(originalTarget){
    window.recapTargetForTier=function(item,tier){
      const candidate=originalTarget(item,tier);
      if(candidate && physicalKey(candidate)!==physicalKey(item))return candidate;
      return distinctTargetForTier(item,tier);
    };
  }
  if(originalSwitch){
    window.switchRecapVersion=function(targetTier=null){
      let current=null;try{current=typeof clip==='function'?clip(currentIndex):null;}catch(_){}
      if(current&&targetTier){
        const target=window.recapTargetForTier?.(current,targetTier);
        if(!target||physicalKey(target)===physicalKey(current)){
          try{setFeedNote?.('That recap tier does not have a different playable video.');}catch(_){}
          return false;
        }
      }
      return originalSwitch(targetTier);
    };
  }
  window.SBB_RECAP_IDENTITY_GUARD=Object.freeze({version:VERSION,physicalKey,distinctTargetForTier});
})();

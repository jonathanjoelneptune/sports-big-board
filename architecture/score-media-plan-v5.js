/* Sports Big Board v5.0.3 — Score Media Plan Builder.
   Score-card playback intent must never monopolize the browser main thread while
   resolving a large date/media pool. Exact event candidates are kept first; any
   date-wide fallback scan is chunked and cooperatively yields between bounded
   slices. This service is game-agnostic and never owns playback. */
(() => {
  'use strict';
  if(window.SBB_SCORE_MEDIA_PLAN?.version==='1.0')return;
  const VERSION='1.0';
  const DEFAULT_CHUNK_ITEMS=32;
  const DEFAULT_CHUNK_BUDGET_MS=7;
  const stats={builds:0,scanned:0,accepted:0,yields:0,maxChunkMs:0,maxBuildMs:0,last:null};
  const perfNow=()=>typeof performance!=='undefined'&&performance.now?performance.now():Date.now();
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const keyOfDefault=item=>String(item?.id||item?.youtubeId||item?.mediaUrl||item?.externalUrl||item?.assetKey||'');
  async function yieldToBrowser(){
    try{if(window.SBB_MAIN_THREAD_GUARD?.yieldToBrowser)return await window.SBB_MAIN_THREAD_GUARD.yieldToBrowser();}catch(_){}
    try{await new Promise(resolve=>requestAnimationFrame(()=>resolve()));}catch(_){await sleep(0);}
    return true;
  }
  function unique(items,keyFor=keyOfDefault){
    const out=[],seen=new Set();
    for(const item of items||[]){if(!item)continue;const key=String(keyFor(item)||'');if(!key||seen.has(key))continue;seen.add(key);out.push(item);}
    return out;
  }
  async function build({exactItems=[],dateItems=[],includeDateItem=()=>true,isUsable=()=>true,keyFor=keyOfDefault,chunkItems=DEFAULT_CHUNK_ITEMS,chunkBudgetMs=DEFAULT_CHUNK_BUDGET_MS}={}){
    const started=perfNow(),out=unique((exactItems||[]).filter(isUsable),keyFor),seen=new Set(out.map(x=>String(keyFor(x)||'')));let scanned=0,accepted=0,yields=0,maxChunkMs=0,chunkStart=perfNow(),chunkCount=0;
    for(const item of dateItems||[]){
      scanned++;chunkCount++;
      let keep=false;try{keep=!!item&&isUsable(item)&&includeDateItem(item);}catch(_){keep=false;}
      if(keep){const key=String(keyFor(item)||'');if(key&&!seen.has(key)){seen.add(key);out.push(item);accepted++;}}
      const elapsed=perfNow()-chunkStart;
      if(chunkCount>=Math.max(8,Number(chunkItems)||DEFAULT_CHUNK_ITEMS)||elapsed>=Math.max(2,Number(chunkBudgetMs)||DEFAULT_CHUNK_BUDGET_MS)){
        maxChunkMs=Math.max(maxChunkMs,elapsed);chunkCount=0;chunkStart=perfNow();yields++;await yieldToBrowser();chunkStart=perfNow();
      }
    }
    maxChunkMs=Math.max(maxChunkMs,perfNow()-chunkStart);
    const elapsedMs=perfNow()-started,row={at:Date.now(),exactCount:(exactItems||[]).length,dateCount:(dateItems||[]).length,scanned,accepted,total:out.length,yields,maxChunkMs,elapsedMs};
    stats.builds++;stats.scanned+=scanned;stats.accepted+=accepted;stats.yields+=yields;stats.maxChunkMs=Math.max(stats.maxChunkMs,maxChunkMs);stats.maxBuildMs=Math.max(stats.maxBuildMs,elapsedMs);stats.last=row;
    return {items:out,metrics:{...row}};
  }
  function snapshot(){return {version:VERSION,...stats,last:stats.last?{...stats.last}:null};}
  window.SBB_SCORE_MEDIA_PLAN=Object.freeze({version:VERSION,build,snapshot,yieldToBrowser});
})();

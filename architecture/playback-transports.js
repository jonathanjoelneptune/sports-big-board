/* Sports Big Board v4.2.1 — transport vocabulary.
   Discovery identifies media; transport decides how an already-selected asset is
   delivered. League names never decide playback implementation. */
(() => {
  const TYPE=Object.freeze({DIRECT_VIDEO:'DIRECT_VIDEO',YOUTUBE_EMBED:'YOUTUBE_EMBED',EXTERNAL:'EXTERNAL',CONTEXT:'CONTEXT',UNSUPPORTED:'UNSUPPORTED'});
  function transportForAsset(item){
    if(!item) return TYPE.UNSUPPORTED;
    if(item.transport&&Object.values(TYPE).includes(String(item.transport))) return String(item.transport);
    if(item.eventType||item.contextCard||item.contextType) return TYPE.CONTEXT;
    if(item.externalOnly&&item.externalUrl&&!item.mediaUrl&&!item.youtubeId) return TYPE.EXTERNAL;
    if(item.mediaUrl) return TYPE.DIRECT_VIDEO;
    if(item.youtubeId||(!item.mediaUrl&&item.id&&/^[A-Za-z0-9_-]{8,}$/.test(String(item.id)))) return TYPE.YOUTUBE_EMBED;
    if(item.externalUrl) return TYPE.EXTERNAL;
    return TYPE.UNSUPPORTED;
  }
  function playbackKey(item){
    const type=transportForAsset(item);
    if(type===TYPE.DIRECT_VIDEO)return `direct:${item?.mediaUrl||''}`;
    if(type===TYPE.YOUTUBE_EMBED)return `youtube:${item?.youtubeId||item?.id||''}`;
    if(type===TYPE.EXTERNAL)return `external:${item?.externalUrl||item?.id||''}`;
    if(type===TYPE.CONTEXT)return `context:${item?.id||item?.eventId||item?.title||''}`;
    return 'unsupported';
  }
  function inAppPlayable(item){const t=transportForAsset(item);return !!item?.verifiedPlayable&&(t===TYPE.DIRECT_VIDEO||t===TYPE.YOUTUBE_EMBED);}
  function externalAvailable(item){return !!item?.externalUrl;}
  window.SBB_PLAYBACK_TRANSPORTS=Object.freeze({version:'1.0',TYPE,transportForAsset,playbackKey,inAppPlayable,externalAvailable});
})();

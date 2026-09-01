/* Sports Big Board v5.0.5 — Curated Event Media Overrides.

   Automated discovery remains the default media authority.  This registry is a
   deliberately small, explicit correction layer for sporting events where a human
   has identified the exact recap that Sports Big Board should use.  Curated media
   is expressed as data, not playback conditionals, so the normal v5 transaction,
   readiness, fallback, quarantine and player-adapter rules still apply.
*/
(() => {
  'use strict';
  if(window.SBB_CURATED_MEDIA?.version==='1.0')return;

  const clean=v=>String(v??'').trim();
  const upper=v=>clean(v).toUpperCase();
  const norm=v=>clean(v).toLowerCase().normalize?.('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/&/g,' and ').replace(/[^a-z0-9]+/g,' ').trim()||clean(v).toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
  const teamText=v=>clean(v?.displayName||v?.name||v?.shortName||v?.abbreviation||v?.abbr||v);
  const eventTeams=event=>{
    const parts=Array.isArray(event?.participants)?event.participants:[];
    return {
      away:teamText(event?.awayTeam||event?.away||parts.find(x=>x?.side==='away')||parts[0]||{}),
      home:teamText(event?.homeTeam||event?.home||parts.find(x=>x?.side==='home')||parts[1]||{})
    };
  };
  const eventDate=event=>clean(event?.scheduledGameDate||event?.__sbbDate||event?.gameDate||event?.scheduledAt||event?.date).slice(0,10);
  const eventIds=event=>new Set([
    event?.gameCenterEventId,event?.scoreEventId,event?.espnEventId,event?.providerEventId,
    event?.eventId,event?.matchId,event?.gamePk,event?.id
  ].filter(v=>v!==undefined&&v!==null&&clean(v)).map(clean));
  const competition=event=>upper(event?.competitionId||event?.__sbbLeague||event?.league);
  const physicalKey=item=>{
    try{return window.SBB_PLAYBACK_TRANSPORTS?.playbackKey?.(item)||clean(item?.youtubeId?`youtube:${item.youtubeId}`:(item?.mediaUrl?`direct:${item.mediaUrl}`:item?.id));}
    catch(_){return clean(item?.youtubeId||item?.mediaUrl||item?.id);}
  };

  const ENTRIES=Object.freeze([
    Object.freeze({
      id:'cfb-2026-08-29-sjsu-usc-recap',
      competitionId:'CFB',
      date:'2026-08-29',
      providerEventIds:Object.freeze(['401864494']),
      awayTokens:Object.freeze(['san jose state','san jose state spartans','sjsu']),
      homeTokens:Object.freeze(['usc','usc trojans','southern california']),
      regressionFixture:true,
      assets:Object.freeze([
        Object.freeze({
          id:'curated:youtube:-tDiPDHU2fs',
          youtubeId:'-tDiPDHU2fs',
          curatedSourceUrl:'https://www.youtube.com/watch?v=-tDiPDHU2fs',
          title:'San Jose State at USC — Curated Game Recap',
          source:'YOUTUBE',provider:'YOUTUBE',sourceLabel:'CURATED YOUTUBE',
          verifiedPlayable:true,overview:true,programType:'recap',mediaObjective:'QUICK',
          recapTier:'green',displayTier:'green',mediaScope:'GAME',curatedPriority:100000
        })
      ])
    })
  ]);

  function tokenMatch(value,tokens=[]){
    const v=norm(value);if(!v)return false;
    return tokens.some(token=>{const t=norm(token);return !!t&&(v===t||v.includes(t)||t.includes(v));});
  }
  function matches(entry,event){
    if(!entry||!event||competition(event)!==upper(entry.competitionId))return false;
    const ids=eventIds(event),idMatch=(entry.providerEventIds||[]).some(id=>ids.has(clean(id)));
    if(idMatch)return true;
    if(entry.date&&eventDate(event)!==entry.date)return false;
    const teams=eventTeams(event);
    return tokenMatch(teams.away,entry.awayTokens)&&tokenMatch(teams.home,entry.homeTokens);
  }
  function entriesFor(event){return ENTRIES.filter(entry=>matches(entry,event));}
  function materialize(entry,event){
    const teams=eventTeams(event),date=eventDate(event)||entry.date,ids=eventIds(event),canonicalEventId=clean([...ids][0]||entry.providerEventIds?.[0]||'');
    return (entry.assets||[]).map(asset=>({
      ...asset,
      competitionId:upper(entry.competitionId),league:upper(entry.competitionId),
      date,gameDate:date,scheduledGameDate:date,
      eventId:canonicalEventId,scoreEventId:canonicalEventId,espnEventId:clean(event?.espnEventId||entry.providerEventIds?.[0]||canonicalEventId),
      matchId:clean(event?.matchId||event?.id||canonicalEventId),
      canonicalEventKey:`${upper(entry.competitionId)}:${clean(entry.providerEventIds?.[0]||canonicalEventId)}`,
      awayTeam:event?.awayTeam||event?.away||{name:teams.away,displayName:teams.away},
      homeTeam:event?.homeTeam||event?.home||{name:teams.home,displayName:teams.home},
      __sbbCuratedOverride:true,curatedOverrideId:entry.id,curatedRegressionFixture:!!entry.regressionFixture
    }));
  }
  function itemsFor(event){return entriesFor(event).flatMap(entry=>materialize(entry,event));}
  function apply(event,items=[]){
    const curated=itemsFor(event),out=[],seen=new Set();
    for(const item of [...curated,...(items||[])]){
      if(!item)continue;const key=physicalKey(item)||clean(item.id);if(key&&seen.has(key))continue;if(key)seen.add(key);out.push(item);
    }
    return out;
  }
  function preferred(event,items=[]){
    const curatedKeys=new Set(itemsFor(event).map(physicalKey).filter(Boolean));
    return (items||[]).find(item=>curatedKeys.has(physicalKey(item)))||null;
  }
  function regressionFixtures(){return ENTRIES.filter(x=>x.regressionFixture).map(entry=>({id:entry.id,competitionId:entry.competitionId,date:entry.date,providerEventIds:[...(entry.providerEventIds||[])],youtubeIds:(entry.assets||[]).map(x=>x.youtubeId).filter(Boolean)}));}
  function snapshot(){return {version:'1.0',entries:ENTRIES.length,regressionFixtures:regressionFixtures(),assetCount:ENTRIES.reduce((n,x)=>n+(x.assets?.length||0),0)};}

  window.SBB_CURATED_MEDIA=Object.freeze({version:'1.0',entries:ENTRIES,entriesFor,itemsFor,apply,preferred,regressionFixtures,snapshot});
})();

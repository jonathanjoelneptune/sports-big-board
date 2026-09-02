/* Sports Big Board v5.1.22 — thin tennis ribbon renderer.

   v5.1.22 moves tennis presentation authority to the backend Day State read model.
   Score rows arrive with final ribbon names, country-flag artwork and round labels.
   This browser module performs no name parsing, country mapping, provider lookup,
   score-store transformation, MutationObserver work, geometry reads or scroll-time
   reconciliation. Generic score cards render team.abbreviation + team.logo directly.
*/
(() => {
  'use strict';
  if(window.SBB_TENNIS_PRESENTATION?.version==='5.1.22')return;

  const VERSION='5.1.22';
  const clean=v=>String(v??'').trim();

  function isTennis(evt){
    return !!evt && (
      clean(evt.__sbbTennisPresentation).includes('backend-tennis-ribbon') ||
      clean(evt.sportId||evt?.event?.sportId).toLowerCase()==='tennis'
    );
  }
  function roundRibbonLabel(match){
    return clean(match?.ribbonContextLabel||match?.tennisRibbonLabel||match?.tennisRoundShort);
  }
  function countryCodeOf(team){return clean(team?.countryCode);}
  function flagEmoji(team){return clean(team?.flagEmoji);}

  // Round context is the only presentation field the legacy generic score-card
  // builder does not yet read directly. It is already computed by the backend;
  // this pass only copies one string into the existing top-right DOM node.
  function decorateCards(){
    const host=document.getElementById('scoreCells');
    if(!host)return;
    // Render-pipeline card banks are immutable for one event identity. Inspect each
    // newly-created card exactly once; repeated media/status renders do zero tennis
    // DOM work. Scrolling never calls this function.
    host.querySelectorAll(':scope > .score-card:not([data-sbb-tennis-v5122])').forEach(card=>{
      card.dataset.sbbTennisV5122='1';
      const match=card.__sbbMatch;
      if(!isTennis(match))return;
      card.classList.add('sbb-tennis-score-card');
      const label=roundRibbonLabel(match);
      const node=card.querySelector('.score-card-top small');
      if(node&&label&&node.textContent!==label){
        node.textContent=label;
        node.title=clean(match?.roundName||match?.round||match?.stage||label);
        node.dataset.sbbTennisRound='1';
      }
      // Flags already come from the backend and are lazy-loaded by the generic card
      // builder. Decode them asynchronously so a newly-visible flag cannot block a
      // wheel/drag frame on dense tournament ribbons.
      card.querySelectorAll('.score-team-logo').forEach(img=>{
        try{img.decoding='async';img.fetchPriority='low';}catch(_){}
      });
    });
  }

  function applySelected(evt){
    const tennis=isTennis(evt);
    document.body?.classList.toggle('sbb-tennis-game-center-active',tennis);
    const labels={overview:'OVERVIEW','team-stats':tennis?'MATCH STATS':'TEAM STATS',players:'PLAYERS',plays:tennis?'SETS':'PLAYS'};
    document.querySelectorAll('[data-gc-section]').forEach(btn=>{
      const key=btn.dataset.gcSection;if(labels[key])btn.textContent=labels[key];
    });
  }

  function style(){
    if(document.getElementById('sbbTennisPresentationStyle'))return;
    const el=document.createElement('style');
    el.id='sbbTennisPresentationStyle';
    el.textContent=`
      .score-card.sbb-tennis-score-card{contain:layout paint style}
      .score-card.sbb-tennis-score-card .score-card-top small{min-width:46px;text-align:right;white-space:nowrap;font-size:7px;letter-spacing:.02em}
      .score-card.sbb-tennis-score-card .score-team-abbr{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .score-card.sbb-tennis-score-card .score-team-logo-wrap{flex:0 0 auto}
      @media (min-width:900px){
        body.sbb-tennis-game-center-active #infoDrawer:not(.is-closed){height:auto!important;max-height:none!important;align-self:stretch!important;overflow:visible!important}
        body.sbb-tennis-game-center-active #gameCenterPane,body.sbb-tennis-game-center-active #gameCenterContent{height:auto!important;max-height:none!important;overflow:visible!important}
        body.sbb-tennis-game-center-active #gameCenterPane{min-height:calc(100vh - 235px)}
        body.sbb-tennis-game-center-active #gameCenterContent .gc-section{max-height:none!important;overflow:visible!important}
      }`;
    document.head.appendChild(el);
  }

  function onPipelineEvent(ev){
    if(clean(ev?.detail?.type)==='render')decorateCards();
  }
  function boot(){
    style();
    try{window.SBB_SELECTED_EVENT?.subscribe?.(evt=>applySelected(evt));applySelected(window.SBB_SELECTED_EVENT?.get?.());}catch(_){}
    window.addEventListener?.('sbb:render-pipeline',onPipelineEvent);
    decorateCards();
  }

  // Compatibility surface: these are identity/property lookups only. Runtime score
  // ingestion no longer calls prepareRows/preparedMatch or rewrites ScoreDateStore.
  window.SBB_TENNIS_PRESENTATION=Object.freeze({
    version:VERSION,
    authority:'BACKEND_DAY_STATE',
    isTennis,
    compactName:value=>clean(value),
    roundShort:value=>clean(value),
    roundRibbonLabel,
    countryCodeOf,
    flagEmoji,
    preparedMatch:match=>match,
    prepareRows:(_league,rows)=>rows,
    decorateCards,
    scheduleDecorate:decorateCards,
    captureAnchor:()=>null,
    restoreAnchor:()=>false,
    apply:applySelected,
    installScoreProjection:()=>true,
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

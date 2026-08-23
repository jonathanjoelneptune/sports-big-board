/* Sports Big Board v3.0.9 — sport-aware Game Center section policy. */
(() => {
  const clean=v=>String(v??'').trim();
  function categoryFromTitle(title,sportId=''){
    const t=clean(title).toLowerCase();
    const rules=[['passing',/pass/],['rushing',/rush/],['receiving',/receiv/],['defense',/defen/],['kicking',/kick/],['batting',/batt/],['pitching',/pitch/],['goalies',/goalie|goaltend/],['skaters',/skater/],['lineup',/lineup|roster/]];
    for(const [name,re] of rules)if(re.test(t))return name;
    return sportId==='basketball'?'players':'players';
  }
  function section(sec={},event={}){
    const parts=event?.participants||[];
    let side=clean(sec.teamSide).toLowerCase();
    if(side!=='away'&&side!=='home'){
      const title=clean(sec.title).toLowerCase();
      for(const p of parts){const tokens=[p?.id,p?.abbreviation,p?.shortName,p?.name,p?.displayName].map(x=>clean(x).toLowerCase()).filter(Boolean);if(tokens.some(x=>title.startsWith(x))){side=p?.side||'';break;}}
    }
    return {...sec,teamSide:side,teamId:clean(sec.teamId||(parts.find(x=>x.side===side)||{}).id),teamName:clean(sec.teamName||(parts.find(x=>x.side===side)||{}).name),teamAbbreviation:clean(sec.teamAbbreviation||(parts.find(x=>x.side===side)||{}).abbreviation),category:clean(sec.category||categoryFromTitle(sec.title,event?.sportId))};
  }
  function normalize(gc={}){const event=gc.event||{};return {...gc,playerStatSections:(gc.playerStatSections||[]).map(x=>section(x,event))};}
  window.SBB_GAME_CENTER_POLICY=Object.freeze({version:'1.0',section,normalize,categoryFromTitle});
})();

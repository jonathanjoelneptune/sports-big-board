/* v3.0.2 league-level editorial programming contracts.
   These packages belong to a league/programming desk, never to one selected game. */
(() => {
  const SERIES=Object.freeze({
    MLB_TOP_PLAYS_DAILY:Object.freeze({id:'MLB_TOP_PLAYS_DAILY',competitionId:'MLB',editorialType:'top_plays',scope:'league',cadence:'daily',label:'Top Plays of the Day',preferredSource:'MLB'}),
    NBA_TOP_PLAYS_NIGHTLY:Object.freeze({id:'NBA_TOP_PLAYS_NIGHTLY',competitionId:'NBA',editorialType:'top_plays',scope:'league',cadence:'nightly',label:'Top Plays of the Night',preferredSource:'NBA'}),
    NFL_TOP_PLAYS_WEEKLY:Object.freeze({id:'NFL_TOP_PLAYS_WEEKLY',competitionId:'NFL',editorialType:'top_plays',scope:'league',cadence:'weekly',label:'Top Plays of the Week',preferredSource:'NFL'})
  });
  const clean=v=>v==null?'':String(v).trim();
  function packageOf(input={}){
    const series=SERIES[clean(input.seriesId)]||null;
    const competitionId=clean(input.competitionId||input.league||series?.competitionId).toUpperCase();
    return {
      ...input,
      entityType:'editorial-package',
      editorialScope:clean(input.editorialScope||input.scope||series?.scope||'league'),
      editorialType:clean(input.editorialType||series?.editorialType||'top_plays'),
      cadence:clean(input.cadence||series?.cadence||'daily'),
      competitionId,
      league:competitionId||clean(input.league),
      seriesId:clean(input.seriesId||series?.id),
      seriesLabel:clean(input.seriesLabel||series?.label),
      editorialPeriodKey:clean(input.editorialPeriodKey||input.topPlaysDate||input.publishedAt).slice(0,10),
      programType:clean(input.programType||'top-plays'),
      eventType:clean(input.eventType||'TOP PLAYS')
    };
  }
  function isLeagueEditorial(item){ return !!(item && (item.editorialScope==='league'||item.entityType==='editorial-package')); }
  window.SBB_EDITORIAL_PACKAGES=Object.freeze({version:'1.0',SERIES,package:packageOf,isLeagueEditorial});
})();

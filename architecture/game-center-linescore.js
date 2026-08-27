/* Sports Big Board v4.3.5 — MLB linescore reconciliation.
   Some merged/provider snapshots expose the final total before the decisive extra-
   inning cell is populated. Reconcile only a blank final extra-inning cell from the
   authoritative game total; ordinary innings and zero-run cells are left alone. */
(() => {
  'use strict';
  const blank=v=>v===null||v===undefined||String(v).trim()==='';
  const num=v=>{if(blank(v))return null;const n=Number(v);return Number.isFinite(n)?n:null;};
  function reconcile(scoreboard,competitionId='MLB'){
    const innings=(scoreboard?.innings||[]).filter(x=>x&&typeof x==='object').map(x=>({...x}));
    if(String(competitionId||'').toUpperCase()!=='MLB'||!innings.length)return innings;
    const last=innings.reduce((best,row)=>Number(row?.num||0)>=Number(best?.num||0)?row:best,innings[0]);
    if(Number(last?.num||0)<=9)return innings;
    for(const side of ['away','home']){
      const total=num(scoreboard?.totals?.[side]?.runs??scoreboard?.[side]?.score);
      if(total===null||!blank(last?.[side]))continue;
      let known=0,complete=true;
      for(const row of innings){
        if(row===last)continue;
        const n=num(row?.[side]);
        if(n===null){complete=false;break;}
        known+=n;
      }
      if(!complete)continue;
      const missing=total-known;
      if(missing>0&&Number.isInteger(missing))last[side]=missing;
    }
    return innings;
  }
  window.SBB_GAME_CENTER_LINESCORE=Object.freeze({version:'1.0',reconcile});
})();

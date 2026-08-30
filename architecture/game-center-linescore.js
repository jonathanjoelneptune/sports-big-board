/* Sports Big Board v4.7.17 — normalized multisport Game Center linescore.
   MLB retains inning-by-inning R/H/E reconciliation. Football, basketball and
   hockey consume the normalized ESPN scoreboard.periods contract. */
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
  function label(index,competitionId='',raw=''){
    if(raw&&!/^[0-9]+$/.test(String(raw).trim()))return String(raw).trim().toUpperCase();
    const n=Number(index||0),comp=String(competitionId||'').toUpperCase();
    if(['NFL','CFB','NBA'].includes(comp))return n<=4?`Q${n}`:(n===5?'OT':`${n-4}OT`);
    if(comp==='NHL')return n<=3?`P${n}`:(n===4?'OT':(n===5?'SO':`${n-3}OT`));
    if(['MLS','EPL'].includes(comp))return n<=2?`H${n}`:(n===3?'ET':`ET${n-2}`);
    return String(raw||n||'');
  }
  function periods(scoreboard,competitionId=''){
    return (scoreboard?.periods||[]).filter(x=>x&&typeof x==='object').map((row,i)=>({
      ...row,
      num:Number(row.num||row.period||i+1),
      label:label(row.num||row.period||i+1,competitionId,row.label||row.ordinal||row.name||''),
      away:row.away??row.awayScore??'',
      home:row.home??row.homeScore??''
    }));
  }
  function model(scoreboard,competitionId=''){
    const comp=String(competitionId||'').toUpperCase();
    if(comp==='MLB'){
      const rows=reconcile(scoreboard,comp);
      return {kind:rows.length?'innings':'summary',rows};
    }
    const rows=periods(scoreboard,comp);
    return {kind:rows.length?'periods':'summary',rows};
  }
  window.SBB_GAME_CENTER_LINESCORE=Object.freeze({version:'2.0',reconcile,periods,label,model});
})();

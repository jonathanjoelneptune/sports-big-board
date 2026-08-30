/* Sports Big Board v4.7.12 — Future Date Navigation.
   The original score ribbon historically clamped all dates after today back to
   today. Scheduled tournaments/leagues need tomorrow and later dates to remain
   browsable. This layer owns only the pager/date-picker policy; Day State remains
   the source of the actual future schedule.
*/
(() => {
  'use strict';
  if(window.SBB_FUTURE_DATES?.version==='4.7.12')return;

  const VERSION='4.7.12';
  const clean=v=>String(v??'').trim();
  const day=v=>clean(v).slice(0,10);

  function unlockPager(){
    const picker=document.getElementById('scoreDatePicker');
    if(picker){
      picker.removeAttribute('max');
      picker.dataset.sbbFutureDates='enabled';
    }
    document.querySelectorAll('[data-score-date-step]').forEach(btn=>{
      const delta=Number(btn.dataset.scoreDateStep||0);
      if(delta>0){
        btn.disabled=false;
        btn.classList.remove('unavailable');
      }
    });
  }

  function installPager(){
    if(typeof window.updateScoreDayPager!=='function')return false;
    if(window.updateScoreDayPager.__sbbFutureDates)return true;
    const original=window.updateScoreDayPager;
    const wrapped=function(...args){
      const result=original(...args);
      unlockPager();
      return result;
    };
    wrapped.__sbbFutureDates=true;
    wrapped.__sbbOriginal=original;
    window.updateScoreDayPager=wrapped;
    unlockPager();
    return true;
  }

  function setFutureShell(date,{hold=9000}={}){
    date=day(date);
    if(!/^\d{4}-\d{2}-\d{2}$/.test(date))return false;
    try{scoreBrowseDate=date;}catch(_){window.scoreBrowseDate=date;}
    try{SCORE_DATE_STORE?.setBrowseDate?.(date,{notifyListeners:false});}catch(_){}
    try{scoreRibbonInteractionUntil=Date.now()+Number(hold||9000);}catch(_){}
    try{window.updateScoreDayPager?.();}catch(_){}
    try{window.updateReturnTodayButton?.();}catch(_){}
    unlockPager();
    return true;
  }

  function boot(){
    installPager();
    const timer=setInterval(()=>{
      if(installPager())clearInterval(timer);
    },250);
    setTimeout(()=>clearInterval(timer),5000);
  }

  window.SBB_FUTURE_DATES=Object.freeze({
    version:VERSION,
    unlockPager,
    setFutureShell,
    normalize:value=>{
      const d=day(value);
      return /^\d{4}-\d{2}-\d{2}$/.test(d)?d:'';
    }
  });

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

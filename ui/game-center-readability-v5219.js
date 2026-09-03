/* Sports Big Board v5.3.15 — Game Center readability post-processing.
   The provider renderer remains authoritative. This layer only enhances labels,
   accessibility state and standard stat abbreviations after a Game Center render. */
(() => {
  'use strict';
  if(window.SBB_GAME_CENTER_READABILITY?.version==='5.3.15')return;
  const VERSION='5.3.15';
  const $=id=>document.getElementById(id);
  let queued=false,observer=null;

  const STAT_ABBR=new Map(Object.entries({
    'player':'PLAYER','name':'PLAYER','position':'POS','pos':'POS',
    'at bat':'AB','at bats':'AB','total at bat':'AB','total at bats':'AB','ab':'AB',
    'runs':'R','run':'R','total runs':'R','total runs scored':'R','runs scored':'R','r':'R',
    'hits':'H','hit':'H','total hits':'H','h':'H',
    'runs batted in':'RBI','run batted in':'RBI','total runs batted in':'RBI','total rbis':'RBI','rbis':'RBI','rbi':'RBI',
    'home run':'HR','home runs':'HR','total home run':'HR','total home runs':'HR','hr':'HR',
    'walk':'BB','walks':'BB','total walks':'BB','base on balls':'BB','bb':'BB',
    'strikeout':'K','strikeouts':'K','total strikeouts':'K','k':'K','so':'K',
    'stolen base':'SB','stolen bases':'SB','total stolen bases':'SB','sb':'SB',
    'caught stealing':'CS','cs':'CS',
    'batting average':'AVG','average':'AVG','avg':'AVG',
    'on base percentage':'OBP','on-base percentage':'OBP','obp':'OBP',
    'slugging percentage':'SLG','slg':'SLG','on base plus slugging':'OPS','ops':'OPS',
    'total pitches':'P','pitches':'P','pitch count':'P',
    'innings pitched':'IP','inning pitched':'IP','ip':'IP',
    'hits allowed':'H','total hits allowed':'H',
    'runs allowed':'R','total runs allowed':'R',
    'earned runs':'ER','earned runs allowed':'ER','total earned runs':'ER','er':'ER',
    'walks allowed':'BB','total walks allowed':'BB',
    'home runs allowed':'HR','total home runs allowed':'HR',
    'earned run average':'ERA','era':'ERA',
    'wins':'W','win':'W','losses':'L','loss':'L','saves':'SV','save':'SV','holds':'HLD','hold':'HLD',
    'games':'G','games played':'G','total games played':'G','games started':'GS','total games started':'GS'
  }));

  function normalizeLabel(v){return String(v||'').trim().toLowerCase().replace(/[_-]+/g,' ').replace(/\s+/g,' ');}
  function statAbbr(text){
    const raw=String(text||'').trim();
    if(!raw)return raw;
    const key=normalizeLabel(raw);
    if(STAT_ABBR.has(key))return STAT_ABBR.get(key);
    // Provider labels often prepend "Total" to an otherwise standard stat.
    const noTotal=key.replace(/^total\s+/,'');
    if(STAT_ABBR.has(noTotal))return STAT_ABBR.get(noTotal);
    if(/runs?\s+batt?ed|runs?\s+bat\b/.test(key))return 'RBI';
    if(/home\s+runs?/.test(key))return 'HR';
    if(/innings?\s+pitched/.test(key))return 'IP';
    if(/earned\s+runs?/.test(key))return 'ER';
    if(/walks?/.test(key)&&/allow/.test(key))return 'BB';
    if(/strikeouts?/.test(key))return 'K';
    if(/pitches?/.test(key))return 'P';
    return raw.length<=5?raw.toUpperCase():raw;
  }

  function fullTeamNames(){
    const away=String($('gcAwayTeam')?.querySelector('.gc-team-name')?.textContent||'').trim();
    const home=String($('gcHomeTeam')?.querySelector('.gc-team-name')?.textContent||'').trim();
    return {away,home};
  }

  function polishSectionTabs(){
    document.querySelectorAll('#gcSections [data-gc-section]').forEach(btn=>{
      if(btn.dataset.gcSection==='plays'&&btn.textContent.trim()!=='KEY PLAYS')btn.textContent='KEY PLAYS';
      const active=btn.classList.contains('active');
      btn.setAttribute('aria-selected',active?'true':'false');
      btn.setAttribute('role','tab');
    });
    $('gcSections')?.setAttribute('role','tablist');
  }

  function polishPlayerTeams(){
    const {away,home}=fullTeamNames();
    document.querySelectorAll('#gcPlayers [data-gc-player-side]').forEach(btn=>{
      const side=btn.dataset.gcPlayerSide;
      const label=side==='home'?home:away;
      const span=btn.querySelector('span:last-child');
      if(span&&label&&span.textContent.trim()!==label)span.textContent=label;
      const active=btn.classList.contains('active');
      btn.setAttribute('aria-selected',active?'true':'false');
      btn.setAttribute('role','tab');
      if(label)btn.title=`${label} player statistics`;
    });
  }

  function abbreviatePlayerHeaders(){
    document.querySelectorAll('#gcPlayers .gc-player-table thead th').forEach(th=>{
      const original=String(th.dataset.sbbStatFull||th.textContent||'').trim();
      if(!original)return;
      if(!th.dataset.sbbStatFull)th.dataset.sbbStatFull=original;
      const short=statAbbr(original);
      if(th.textContent.trim()!==short)th.textContent=short;
      if(short!==original)th.title=original;
    });
  }

  function resetScrollOnTabChange(){
    const active=document.querySelector('#gameCenterContent [data-gc-pane]:not(.hidden)');
    if(active && active.dataset.sbbLastActive!=='1')active.scrollTop=0;
    document.querySelectorAll('#gameCenterContent [data-gc-pane]').forEach(p=>p.dataset.sbbLastActive=p===active?'1':'0');
  }

  function polish(){
    queued=false;
    polishSectionTabs();
    polishPlayerTeams();
    abbreviatePlayerHeaders();
    resetScrollOnTabChange();
  }
  function schedule(){
    if(queued)return;queued=true;
    queueMicrotask(()=>requestAnimationFrame(polish));
  }

  function bind(){
    const content=$('gameCenterContent');
    if(!content){setTimeout(bind,120);return;}
    observer?.disconnect?.();
    observer=new MutationObserver(schedule);
    observer.observe(content,{subtree:true,childList:true,attributes:true,attributeFilter:['class']});
    document.querySelectorAll('#gcSections [data-gc-section]').forEach(btn=>btn.addEventListener('click',()=>setTimeout(schedule,0)));
    window.SBB_SELECTED_EVENT?.subscribe?.(()=>{setTimeout(schedule,0);setTimeout(schedule,250);});
    schedule();
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
  window.SBB_GAME_CENTER_READABILITY=Object.freeze({version:VERSION,refresh:polish,statAbbr});
})();

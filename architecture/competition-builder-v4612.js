/* Sports Big Board v4.6.12 — reusable schedule template + playlist title matching.
   - COPY TEMPLATE JSON from the Competition Builder schedule step
   - required/excluded title phrases for Green/Purple/Blue playlist sources
   - playlist match rules editable from Historical Database > Game Media Playlists
*/
(() => {
  'use strict';
  if (window.SBB_COMPETITION_BUILDER_V4612) return;

  const $ = id => document.getElementById(id);
  const clean = value => String(value ?? '').trim();
  const lines = value => clean(value).split(/\r?\n/).map(x=>x.trim()).filter(Boolean);

  const GENERIC_SCHEDULE_TEMPLATE = Object.freeze([
    {
      date: "YYYY-MM-DD",
      scheduledAt: "YYYY-MM-DDTHH:MM:SS-04:00",
      away: {
        name: "Actual Team Name",
        displayName: "Actual Team Name",
        group: "Region / Conference / Division / Group",
        abbreviation: "ABC",
        aliases: [
          "Actual Team Name",
          "Alternate Team Name",
          "Region or Group Name"
        ]
      },
      home: {
        name: "Actual Team Name",
        displayName: "Actual Team Name",
        group: "Region / Conference / Division / Group",
        abbreviation: "XYZ",
        aliases: [
          "Actual Team Name",
          "Alternate Team Name",
          "Region or Group Name"
        ]
      },
      status: "FINAL",
      awayScore: 5,
      homeScore: 3,
      providerEventId: "",
      espnEventId: "",
      gameNumber: 1,
      round: "Opening Round",
      stage: "Tournament / Group / Conference / Bracket",
      venue: "Venue Name",
      city: "City",
      country: "Country",
      sourceUrl: "https://official-source.example/game"
    }
  ]);

  function injectStyle() {
    if ($('sbbCompetitionBuilderV4612Style')) return;
    const style=document.createElement('style');
    style.id='sbbCompetitionBuilderV4612Style';
    style.textContent=`
      .sbb-v4612-template-row{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:7px 0 10px}
      .sbb-v4612-template-row small{opacity:.6;font-size:9px;line-height:1.3;flex:1;min-width:220px}
      .sbb-v4612-template-btn{white-space:nowrap}
      .sbb-v4612-rule-box{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:6px 0 12px;padding:9px;border:1px solid rgba(255,255,255,.09);border-radius:9px;background:rgba(255,255,255,.025)}
      .sbb-v4612-rule-box label{display:flex;flex-direction:column;gap:4px;font-size:9px;letter-spacing:.04em}
      .sbb-v4612-rule-box textarea{min-height:58px!important}
      .sbb-v4612-rule-box small{opacity:.55;line-height:1.25;grid-column:1/-1}
      .sbb-v4612-media-playlist-rules{display:grid;grid-template-columns:1fr 1fr;gap:8px;grid-column:1/-1;padding-top:4px}
      .sbb-v4612-media-playlist-rules label{display:flex;flex-direction:column;gap:4px}
      .sbb-v4612-media-playlist-rules textarea{min-height:58px}
      .sbb-v4612-rule-status{grid-column:1/-1;font-size:9px;opacity:.65}
      @media(max-width:700px){.sbb-v4612-rule-box,.sbb-v4612-media-playlist-rules{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  async function copyText(text) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    const ta=document.createElement('textarea');
    ta.value=text;ta.style.position='fixed';ta.style.opacity='0';
    document.body.appendChild(ta);ta.select();
    const ok=document.execCommand('copy');
    ta.remove();
    return ok;
  }

  function templateText() {
    return JSON.stringify(GENERIC_SCHEDULE_TEMPLATE, null, 2);
  }

  function installTemplateButton() {
    const schedule=$('cbScheduleText');
    if (!schedule || $('cbCopyScheduleTemplate')) return;
    const row=document.createElement('div');
    row.className='sbb-v4612-template-row';
    const button=document.createElement('button');
    button.type='button';button.id='cbCopyScheduleTemplate';
    button.className='sbb-v4612-template-btn';
    button.textContent='COPY TEMPLATE JSON';
    const help=document.createElement('small');
    help.textContent='Copies the generic Sports Big Board import schema. Use actual participant names in name, alternate media-title identities in aliases, and leave eventId/canonical IDs to Sports Big Board.';
    row.append(button,help);
    schedule.parentElement?.insertBefore(row,schedule);
    button.addEventListener('click',async()=>{
      const prior=button.textContent;
      try{
        await copyText(templateText());
        button.textContent='COPIED ✓';
        const st=$('sbbBuilderStatus');
        if(st)st.textContent='Generic schedule JSON template copied to clipboard.';
      }catch(err){
        button.textContent='COPY FAILED';
      }
      setTimeout(()=>{if(button.isConnected)button.textContent=prior;},1800);
    });
  }

  const tierIds = Object.freeze({
    green:{area:'cbGreen',required:'cbGreenRequiredTitlePhrases',excluded:'cbGreenExcludedTitlePhrases',label:'GREEN / QUICK'},
    purple:{area:'cbPurple',required:'cbPurpleRequiredTitlePhrases',excluded:'cbPurpleExcludedTitlePhrases',label:'PURPLE / EXTENDED'},
    blue:{area:'cbBlue',required:'cbBlueRequiredTitlePhrases',excluded:'cbBlueExcludedTitlePhrases',label:'BLUE / COVERAGE'}
  });

  function installWizardRule(tier,cfg) {
    const source=$(cfg.area);
    if(!source || $(cfg.required))return;
    const box=document.createElement('div');box.className='sbb-v4612-rule-box';box.dataset.mediaTier=tier;
    const required=document.createElement('label');
    required.textContent=`${cfg.label} REQUIRED TITLE PHRASES`;
    const r=document.createElement('textarea');r.id=cfg.required;r.placeholder='Optional — one accepted phrase per line\nExample: Full Game Highlights';
    required.appendChild(r);
    const excluded=document.createElement('label');
    excluded.textContent=`${cfg.label} EXCLUDED TITLE PHRASES`;
    const e=document.createElement('textarea');e.id=cfg.excluded;e.placeholder='Optional — one rejected phrase per line\nExample: Top Plays';
    excluded.appendChild(e);
    const help=document.createElement('small');
    help.textContent='Required phrases are OR-based: a video must contain at least one. Any excluded phrase rejects it. Leave blank to use normal Sports Big Board matching.';
    box.append(required,excluded,help);
    source.insertAdjacentElement('afterend',box);
  }

  function installWizardRules() {
    for(const [tier,cfg] of Object.entries(tierIds))installWizardRule(tier,cfg);
  }

  function applyWizardMediaRules(comp) {
    if(!comp || typeof comp!=='object')return comp;
    const media={...(comp.mediaSources||{})};
    for(const [tier,cfg] of Object.entries(tierIds)){
      const required=lines($(cfg.required)?.value);
      const excluded=lines($(cfg.excluded)?.value);
      const sources=Array.isArray(media[tier])?media[tier]:[];
      media[tier]=sources.map(raw=>{
        const row=typeof raw==='string'?{url:raw}:{...(raw||{})};
        if(required.length)row.requiredTitlePhrases=required;else delete row.requiredTitlePhrases;
        if(excluded.length)row.excludedTitlePhrases=excluded;else delete row.excludedTitlePhrases;
        return row;
      });
    }
    return {...comp,mediaSources:media};
  }

  function applyLLWSMediaDefaults(kind) {
    if(clean(kind)!=='LLWS')return;
    setTimeout(()=>{
      const field=$('cbGreenRequiredTitlePhrases');
      if(field && !clean(field.value))field.value='Full Game Highlights';
    },0);
  }

  function installFetchBridge() {
    if(window.fetch?.__sbbV4612CompetitionMediaRules)return;
    const original=window.fetch.bind(window);
    const wrapped=async function(input,init={}){
      try{
        const url=typeof input==='string'?input:clean(input?.url);
        if(/\/api\/competition-builder(?:\?|$)/.test(url)&&typeof init?.body==='string'){
          const body=JSON.parse(init.body);
          if(['save','discover'].includes(clean(body?.action).toLowerCase())&&body?.competition&&typeof body.competition==='object'){
            body.competition=applyWizardMediaRules(body.competition);
            init={...init,body:JSON.stringify(body)};
          }
        }
      }catch(_){}
      return original(input,init);
    };
    wrapped.__sbbV4612CompetitionMediaRules=true;
    wrapped.__sbbOriginalFetch=original;
    window.fetch=wrapped;
  }

  async function competitionCatalog() {
    try{
      const r=await fetch(`/api/competition-builder/catalog?_=${Date.now()}`,{cache:'no-store'});
      if(!r.ok)return [];
      const p=await r.json();return p.competitions||[];
    }catch(_){return [];}
  }

  function playlistTierFromObjective(value) {
    return ({quick:'green',extended:'purple',coverage:'blue'})[clean(value).toLowerCase()]||'green';
  }

  function playlistRuleFields() {
    return {
      required:lines($('historyMediaPlaylistRequiredTitlePhrases')?.value),
      excluded:lines($('historyMediaPlaylistExcludedTitlePhrases')?.value)
    };
  }

  async function savePlaylistRules(values) {
    const league=clean(values.league).toUpperCase();
    if(!league||!values.url)return;
    const catalog=await competitionCatalog();
    if(!catalog.some(c=>clean(c.id).toUpperCase()===league))return;
    const r=await fetch('/api/competition-builder/media-rules',{
      method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        id:league,
        url:values.url,
        objective:values.objective,
        requiredTitlePhrases:values.required,
        excludedTitlePhrases:values.excluded
      })
    });
    const p=await r.json().catch(()=>({}));
    if(!r.ok||p.ok===false)throw new Error(p.message||p.error||`HTTP ${r.status}`);
    return p;
  }

  function installPlaylistRuleFields() {
    const form=$('historyMediaPlaylistForm');
    if(!form||$('historyMediaPlaylistRequiredTitlePhrases'))return;
    const host=document.createElement('div');host.className='sbb-v4612-media-playlist-rules';
    const required=document.createElement('label');
    required.innerHTML='<span>REQUIRED TITLE PHRASES</span>';
    const r=document.createElement('textarea');r.id='historyMediaPlaylistRequiredTitlePhrases';r.placeholder='Optional — one accepted phrase per line\nExample: Full Game Highlights';required.appendChild(r);
    const excluded=document.createElement('label');
    excluded.innerHTML='<span>EXCLUDED TITLE PHRASES</span>';
    const e=document.createElement('textarea');e.id='historyMediaPlaylistExcludedTitlePhrases';e.placeholder='Optional — one rejected phrase per line\nExample: Top Plays';excluded.appendChild(e);
    const status=document.createElement('small');status.id='historyMediaPlaylistRuleStatus';status.className='sbb-v4612-rule-status';
    status.textContent='Special-event rule: require one accepted phrase; reject any excluded phrase. Participant aliases from schedule JSON are also used during association.';
    host.append(required,excluded,status);
    const actions=form.querySelector('.history-media-playlist-form-actions');
    if(actions)form.insertBefore(host,actions);else form.appendChild(host);

    form.addEventListener('submit',()=>{
      const values={
        league:clean($('historyMediaPlaylistLeague')?.value),
        url:clean($('historyMediaPlaylistUrl')?.value),
        objective:clean($('historyMediaPlaylistObjective')?.value),
        ...playlistRuleFields()
      };
      setTimeout(async()=>{
        try{
          const result=await savePlaylistRules(values);
          if(result){
            status.textContent=`Rules saved for ${values.league}; playlist recrawl/reassociation started.`;
            $('historyMediaSourcesRefresh')?.click();
          }
        }catch(err){status.textContent=`Rule save failed: ${err?.message||err}`;}
      },700);
    },true);

    const grid=$('historyMediaSourcesGrid');
    grid?.addEventListener('click',ev=>{
      const button=ev.target?.closest?.('[data-v468-playlist-action="edit"]');
      if(!button)return;
      setTimeout(()=>populatePlaylistRulesFromCatalog(),60);
    },true);
  }

  async function populatePlaylistRulesFromCatalog() {
    const league=clean($('historyMediaPlaylistLeague')?.value).toUpperCase();
    const url=clean($('historyMediaPlaylistUrl')?.value);
    if(!league||!url)return;
    const pid=(()=>{try{return new URL(url).searchParams.get('list')||'';}catch(_){return clean(url);}})();
    const catalog=await competitionCatalog();
    const comp=catalog.find(c=>clean(c.id).toUpperCase()===league);
    if(!comp)return;
    const tier=playlistTierFromObjective($('historyMediaPlaylistObjective')?.value);
    const sources=comp.mediaSources?.[tier]||[];
    const row=sources.find(src=>{
      const x=typeof src==='string'?src:clean(src?.url||src?.playlistId);
      if(x===url)return true;
      try{return new URL(x).searchParams.get('list')===pid;}catch(_){return clean(x)===pid;}
    });
    const obj=typeof row==='string'?{}:(row||{});
    if($('historyMediaPlaylistRequiredTitlePhrases'))$('historyMediaPlaylistRequiredTitlePhrases').value=(obj.requiredTitlePhrases||[]).join('\n');
    if($('historyMediaPlaylistExcludedTitlePhrases'))$('historyMediaPlaylistExcludedTitlePhrases').value=(obj.excludedTitlePhrases||[]).join('\n');
  }

  function bindTemplateDefaults() {
    document.querySelectorAll('[data-builder-template]').forEach(button=>{
      if(button.dataset.v4612Bound==='1')return;
      button.dataset.v4612Bound='1';
      button.addEventListener('click',()=>applyLLWSMediaDefaults(button.dataset.builderTemplate));
    });
  }

  function augment() {
    injectStyle();
    installTemplateButton();
    installWizardRules();
    installPlaylistRuleFields();
    bindTemplateDefaults();
  }

  function boot() {
    injectStyle();
    installFetchBridge();
    const observer=new MutationObserver(augment);
    observer.observe(document.documentElement,{childList:true,subtree:true});
    augment();
  }

  window.SBB_COMPETITION_BUILDER_V4612=Object.freeze({
    version:'4.6.12',
    scheduleTemplate:GENERIC_SCHEDULE_TEMPLATE,
    templateText,
    applyWizardMediaRules
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});
  else boot();
})();

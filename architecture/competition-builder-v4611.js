/* Sports Big Board v4.6.11 — Competition Builder reusable event identity.
   Adds a persistent Event Icon selector, 2026 Little League World Series (LLWS) provider defaults, and special-menu icon rendering
   without changing the proven v4.6.6 builder's schedule/media workflow. */
(() => {
  'use strict';
  if (window.SBB_COMPETITION_BUILDER_V4611) return;

  const ICONS = Object.freeze([
    ['🏆','Trophy / Championship'],
    ['⚾','Baseball'],
    ['⚽','Soccer'],
    ['🏀','Basketball'],
    ['🏈','American Football'],
    ['🏒','Hockey'],
    ['🎾','Tennis'],
    ['🏎️','Motorsport'],
    ['🏃','Track / Running'],
    ['🥇','Gold Medal'],
    ['🏅','Medal'],
    ['🌎','World / International'],
    ['🌟','Showcase'],
    ['⭐','Featured Event'],
    ['🔥','Hot Event'],
    ['👑','Crown / Final'],
    ['🚩','Flag'],
    ['🎯','Target / Skills'],
    ['🛡️','Shield']
  ]);
  const $ = id => document.getElementById(id);
  const clean = v => String(v ?? '').trim();
  const sportIcons = Object.freeze({
    baseball:'⚾', football:'⚽', 'american-football':'🏈', basketball:'🏀',
    'ice-hockey':'🏒', tennis:'🎾', motorsport:'🏎️', athletics:'🏃',
    'action-sports':'🔥', 'multi-sport':'🏆'
  });

  function defaultIcon(compOrSport={}) {
    if (typeof compOrSport === 'string') return sportIcons[compOrSport] || '🏆';
    const c = compOrSport || {};
    if (clean(c.eventIcon)) return clean(c.eventIcon);
    const text = `${clean(c.id)} ${clean(c.shortName)} ${clean(c.name)}`.toLowerCase();
    if (/little league|\bllws\b|\bllbws\b/.test(text)) return '⚾';
    if (/world cup/.test(text) && clean(c.sportId) === 'football') return '🌎';
    return sportIcons[clean(c.sportId)] || '🏆';
  }

  function injectStyle() {
    if ($('sbbCompetitionBuilderV4611Style')) return;
    const style = document.createElement('style');
    style.id = 'sbbCompetitionBuilderV4611Style';
    style.textContent = `
      .sbb-builder-sport-icon-pair{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px;align-items:end}
      .sbb-builder-icon-label{display:flex!important;flex-direction:column;gap:5px}
      .sbb-builder-icon-select{font-size:15px}
      .sbb-builder-icon-help{font-size:9px;opacity:.58;line-height:1.25;margin-top:2px}
      @media(max-width:700px){.sbb-builder-sport-icon-pair{grid-template-columns:1fr 1fr}}
    `;
    document.head.appendChild(style);
  }

  function currentIcon() {
    const select = $('cbEventIcon');
    return clean(select?.value) || defaultIcon(clean($('cbSport')?.value));
  }

  function competitionDefaults(draft={}) {
    const d = {...draft};
    const text = `${clean(d.id)} ${clean(d.shortName)} ${clean(d.name)}`.toLowerCase();
    d.eventIcon = clean(d.eventIcon) || currentIcon() || defaultIcon(d);
    if ((/little league/.test(text) || /\bllws\b|\bllbws\b/.test(text)) && clean(d.sportId) === 'baseball') {
      d.providerLeagueSlug = clean(d.providerLeagueSlug) || 'llb';
      d.providerSport = clean(d.providerSport) || 'baseball';
      d.gameCenterProfile = clean(d.gameCenterProfile) || 'baseball';
    } else if (/world cup/.test(text) && clean(d.sportId) === 'football') {
      d.providerLeagueSlug = clean(d.providerLeagueSlug) || 'fifa.world';
      d.providerSport = clean(d.providerSport) || 'soccer';
      d.gameCenterProfile = clean(d.gameCenterProfile) || 'soccer';
    }
    return d;
  }

  function installFetchBridge() {
    if (window.fetch?.__sbbV4611CompetitionIcons) return;
    const original = window.fetch.bind(window);
    const wrapped = async function(input, init={}) {
      try {
        const url = typeof input === 'string' ? input : clean(input?.url);
        if (/\/api\/competition-builder(?:\?|$)/.test(url) && typeof init?.body === 'string') {
          const body = JSON.parse(init.body);
          if (['save','discover'].includes(clean(body?.action).toLowerCase()) && body?.competition && typeof body.competition === 'object') {
            body.competition = competitionDefaults(body.competition);
            init = {...init, body:JSON.stringify(body)};
          }
        }
      } catch (_) {}
      return original(input, init);
    };
    wrapped.__sbbV4611CompetitionIcons = true;
    wrapped.__sbbOriginalFetch = original;
    window.fetch = wrapped;
  }

  function iconSelect() {
    const select = document.createElement('select');
    select.id = 'cbEventIcon';
    select.className = 'sbb-builder-icon-select';
    for (const [icon,label] of ICONS) {
      const option = document.createElement('option');
      option.value = icon;
      option.textContent = `${icon}  ${label}`;
      select.appendChild(option);
    }
    return select;
  }

  function applyTemplateIcon(kind) {
    const select = $('cbEventIcon');
    if (!select) return;
    const icon = kind === 'LLWS' ? '⚾' : (kind === 'WORLD_CUP' ? '🌎' : defaultIcon(clean($('cbSport')?.value)));
    select.value = icon;
    select.dataset.manual = '1';
  }

  function augmentReview() {
    const review = $('cbReview');
    if (!review || !clean(review.textContent)) return;
    try {
      const obj = JSON.parse(review.textContent);
      const enriched = competitionDefaults(obj);
      if (obj.eventIcon === enriched.eventIcon && obj.providerLeagueSlug === enriched.providerLeagueSlug) return;
      review.textContent = JSON.stringify(enriched, null, 2);
    } catch (_) {}
  }

  function augmentWizard() {
    const modal = $('sbbBuilderModal');
    const sport = $('cbSport');
    if (!modal || !sport || $('cbEventIcon')) return;
    injectStyle();

    const sportLabel = sport.closest('label');
    const parent = sportLabel?.parentElement;
    if (!sportLabel || !parent) return;
    const pair = document.createElement('div');
    pair.className = 'sbb-builder-sport-icon-pair';
    parent.insertBefore(pair, sportLabel);
    pair.appendChild(sportLabel);

    const label = document.createElement('label');
    label.className = 'sbb-builder-icon-label';
    label.append(document.createTextNode('EVENT ICON'));
    const select = iconSelect();
    select.value = defaultIcon(clean(sport.value));
    label.appendChild(select);
    const help = document.createElement('small');
    help.className = 'sbb-builder-icon-help';
    help.textContent = 'Shown beside this event in the Special Events dropdown.';
    label.appendChild(help);
    pair.appendChild(label);

    sport.addEventListener('change', () => {
      if (select.dataset.manual !== '1') select.value = defaultIcon(clean(sport.value));
    });
    select.addEventListener('change', () => { select.dataset.manual = '1'; augmentReview(); });

    modal.querySelectorAll('[data-builder-template]').forEach(button => {
      if (button.dataset.v4611IconBound === '1') return;
      button.dataset.v4611IconBound = '1';
      button.addEventListener('click', () => setTimeout(() => applyTemplateIcon(clean(button.dataset.builderTemplate)), 0));
    });

    const review = $('cbReview');
    if (review) new MutationObserver(augmentReview).observe(review, {childList:true,characterData:true,subtree:true});
  }

  function applyMenuIcons() {
    const map = window.SBB_COMPETITION_BUILDER?.competitionMap?.() || {};
    const menu = $('sbbSpecialEventsMenu');
    if (!menu) return;
    menu.querySelectorAll('[data-special-competition]').forEach(button => {
      const id = clean(button.dataset.specialCompetition).toUpperCase();
      const comp = map[id] || {};
      const span = button.querySelector('.sbb-special-event-icon');
      const icon = defaultIcon(comp);
      if (span && span.textContent !== icon) span.textContent = icon;
      if (span) span.setAttribute('title', clean(comp.name) || id);
    });
  }

  function boot() {
    installFetchBridge();
    injectStyle();
    const bodyObserver = new MutationObserver(() => {
      augmentWizard();
      applyMenuIcons();
    });
    bodyObserver.observe(document.documentElement, {childList:true,subtree:true});
    document.addEventListener('click', () => setTimeout(applyMenuIcons, 0), true);
    setInterval(applyMenuIcons, 5000);
    augmentWizard();
    applyMenuIcons();
  }

  window.SBB_COMPETITION_BUILDER_V4611 = Object.freeze({
    version:'4.6.11', icons:ICONS.map(([icon,label])=>({icon,label})), defaultIcon, competitionDefaults,
    refreshIcons:applyMenuIcons
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true});
  else boot();
})();

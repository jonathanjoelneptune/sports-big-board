/* Sports Big Board v6.1.16 — overcomplete Media Audit operator report.
   One click captures the human-readable console plus complete fresh backend,
   Media Audit, current-inventory-page, and browser-state snapshots. */
(() => {
  'use strict';
  if (window.SBB_MEDIA_AUDIT_COPY?.version === '6.1.16-overkill') return;
  const VERSION = '6.1.16-overkill';
  const $ = id => document.getElementById(id);
  const apiBase = ((window.SBB_CONFIG && window.SBB_CONFIG.apiBase) || location.origin).replace(/\/$/, '');
  const auditApi = `${apiBase}/api/media-audit`;
  const text = id => String($(id)?.textContent || '—').replace(/\s+/g, ' ').trim() || '—';
  const value = id => String($(id)?.value || '').trim();
  const selected = id => {
    const el = $(id);
    if (!el) return '—';
    return String(el.options?.[el.selectedIndex]?.textContent || el.value || '—').trim() || '—';
  };
  const fmtNum = value => new Intl.NumberFormat().format(Number(value || 0));
  const fmtPct = (num, den) => den ? `${(100 * Number(num || 0) / Number(den)).toFixed(2)}%` : '—';
  const fmtDateTime = ts => {
    const n = Number(ts || 0);
    if (!n) return '—';
    try { return `${new Date(n * 1000).toLocaleString()} (${new Date(n * 1000).toISOString()})`; }
    catch (_) { return '—'; }
  };
  const section = (title, rows) => {
    const lines = [`\n## ${title}`];
    for (const [label, val] of rows) lines.push(`${label}: ${val == null || val === '' ? '—' : val}`);
    return lines.join('\n');
  };
  const jsonBlock = (title, payload) => `\n## ${title}\n${JSON.stringify(payload ?? null, null, 2)}`;
  const traceLines = id => {
    const el = $(id);
    if (!el) return ['—'];
    const rows = [...el.querySelectorAll('.trace-line,.trace-row,.event-line,.log-line,div')]
      .map(node => String(node.textContent || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean);
    if (rows.length) return [...new Set(rows)];
    const raw = String(el.innerText || el.textContent || '').trim();
    return raw ? raw.split(/\n+/).map(x => x.trim()).filter(Boolean) : ['—'];
  };
  const workersText = () => {
    const el = $('diagWorkers');
    if (!el) return '—';
    const rows = [...el.children].map(node => String(node.textContent || '').replace(/\s+/g, ' ').trim()).filter(Boolean);
    return rows.length ? rows.join(' | ') : text('diagWorkers');
  };

  async function fetchJson(url, timeoutMs = 12000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }
  async function safeFetch(label, url, timeoutMs) {
    try { return {ok: true, label, url, data: await fetchJson(url, timeoutMs)}; }
    catch (error) { return {ok: false, label, url, error: error?.message || String(error), data: null}; }
  }
  function inventoryQuery() {
    const page = text('pageLabel');
    const match = page.match(/([\d,]+)\s*[–-]\s*([\d,]+)\s+of/i);
    const first = match ? Number(match[1].replace(/,/g, '')) : 1;
    const limit = Number($('pageSize')?.value || 100) || 100;
    const q = new URLSearchParams({limit: String(limit), offset: String(Math.max(0, first - 1))});
    const league = value('filterLeague'), health = value('filterHealth'), search = value('filterSearch');
    if (league) q.set('league', league);
    if (health) q.set('health', health);
    if (search) q.set('search', search);
    return q;
  }
  function collectDomSnapshot() {
    const out = {};
    for (const el of document.querySelectorAll('[id]')) {
      const id = String(el.id || '').trim();
      if (!id) continue;
      const record = {};
      if ('value' in el && String(el.value || '').trim()) record.value = String(el.value);
      if ('checked' in el && typeof el.checked === 'boolean') record.checked = el.checked;
      if (el.tagName === 'SELECT') record.selectedText = String(el.options?.[el.selectedIndex]?.textContent || '').trim();
      const rendered = String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      if (rendered) record.text = rendered;
      if (Object.keys(record).length) out[id] = record;
    }
    return out;
  }
  function repairWorkers(status) {
    const repair = status?.repair || {};
    if (Array.isArray(repair.workers) && repair.workers.length) return repair.workers;
    return repair.worker ? [repair.worker] : [];
  }
  function repairTraces(status) {
    return repairWorkers(status).flatMap(worker => Array.isArray(worker?.trace) ? worker.trace : []);
  }
  function stageRollup(status) {
    const stages = {};
    const pattern = /^([A-Z0-9_]+):\s*(\d+) results\s*•\s*(\d+) new\s*•\s*(\d+) known\s*•\s*(\d+) rejected/i;
    for (const item of repairTraces(status)) {
      const message = String(item?.message || '');
      const match = message.match(pattern);
      if (!match) continue;
      const key = match[1].toUpperCase();
      const row = stages[key] ||= {attempts: 0, results: 0, new: 0, known: 0, rejected: 0, quotaBlocked: 0, retryAt: 0};
      row.attempts += 1;
      row.results += Number(match[2]); row.new += Number(match[3]); row.known += Number(match[4]); row.rejected += Number(match[5]);
      if (item?.details?.quotaBlocked) row.quotaBlocked += 1;
      row.retryAt = Math.max(row.retryAt, Number(item?.details?.retryAt || 0));
    }
    return stages;
  }
  function reasonRollup(status) {
    const counts = {};
    for (const item of repairTraces(status)) {
      const reason = String(item?.details?.reason || item?.details?.failureReason || '').trim();
      if (reason) counts[reason] = (counts[reason] || 0) + 1;
    }
    return Object.fromEntries(Object.entries(counts).sort((a, b) => b[1] - a[1]));
  }
  function teamSourceSnapshot(status) {
    const repair = status?.repair || {};
    const candidates = [repair.worker?.teamSources, ...(Array.isArray(repair.workers) ? repair.workers.map(w => w?.teamSources) : [])].filter(Boolean);
    return candidates[0] || {};
  }
  function appendStageRollup(lines, status) {
    const rollup = stageRollup(status);
    lines.push('\n## DISCOVERY STAGE ROLLUP — RECENT WORKER TRACE');
    const keys = Object.keys(rollup);
    if (!keys.length) lines.push('—');
    for (const key of keys.sort()) {
      const row = rollup[key];
      lines.push(`${key}: ${row.attempts} attempts • ${fmtNum(row.results)} results • ${fmtNum(row.new)} new • ${fmtNum(row.known)} known • ${fmtNum(row.rejected)} rejected • ${row.quotaBlocked} quota-blocked${row.retryAt ? ` • retry ${fmtDateTime(row.retryAt)}` : ''}`);
    }
  }
  function appendUnresolvedTeams(lines, status) {
    const teamSources = teamSourceSnapshot(status);
    const unresolved = Array.isArray(teamSources.recentUnresolvedTeams) ? teamSources.recentUnresolvedTeams : [];
    lines.push('\n## UNRESOLVED TEAM IDENTITIES — COMPLETE STATUS SAMPLE');
    if (!unresolved.length) lines.push('—');
    unresolved.forEach((team, index) => lines.push(`${index + 1}. ${team.entity_key || '—'} • ${team.team_name || '—'} • ${team.status || '—'} • attempts ${team.attempt_count ?? '—'} • next ${fmtDateTime(team.next_retry_at)} • ${team.reason || '—'}`));
  }

  async function buildReport() {
    const captured = new Date();
    const release = document.querySelector('.release')?.textContent?.trim() || VERSION;
    const inventoryUrl = `${auditApi}/inventory?${inventoryQuery().toString()}`;
    const [auditResult, backendResult, inventoryResult] = await Promise.all([
      safeFetch('Media Audit status', `${auditApi}/status`, 12000),
      safeFetch('Core backend status', `${apiBase}/api/status`, 12000),
      safeFetch('Current inventory page', inventoryUrl, 18000),
    ]);
    const status = auditResult.data || {};
    const backend = backendResult.data || {};
    const inventory = inventoryResult.data || {};
    const repair = status.repair || {};
    const primary = repair.worker || {};
    const stats = primary.stats || {};
    const circuit = repair.discoveryCircuit || status.discoveryCircuit || {};
    const teamSources = teamSourceSnapshot(status);
    const ytSearch = backend.youtubeGateway?.search || {};
    const dbw = status.dbWriter || {};
    const summary = status.summary || {};
    const lines = [
      'SPORTS BIG BOARD — MEDIA HEALTH AUDIT — OVERCOMPLETE DIAGNOSTIC COPY',
      `Captured: ${captured.toLocaleString()} (${captured.toISOString()})`,
      `Page: ${location.href}`,
      `Release: ${release}`,
      `Copy module: ${VERSION}`,
    ];

    lines.push(section('COPY CAPTURE HEALTH', [
      ['Media Audit status fetch', auditResult.ok ? 'OK' : `FAILED • ${auditResult.error}`],
      ['Core backend status fetch', backendResult.ok ? 'OK' : `FAILED • ${backendResult.error}`],
      ['Inventory page fetch', inventoryResult.ok ? `OK • ${fmtNum(inventory.rows?.length || 0)} rows` : `FAILED • ${inventoryResult.error}`],
      ['Raw snapshots appended', 'Media Audit status + core backend status + current inventory page + DOM state'],
    ]));
    lines.push(section('SUMMARY', [
      ['Catalog games', `${text('metricGames')} • ${text('metricGamesSub')}`],
      ['Games audited', `${text('metricAudited')} • ${text('metricAuditedSub')}`],
      ['Healthy', text('metricHealthy')], ['Degraded', text('metricDegraded')], ['Inconclusive', text('metricInconclusive')],
      ['Unplayable', text('metricUnplayable')], ['No media', text('metricNoMedia')],
      ['Repair queue', text('metricRepairQueue')], ['Repaired', text('metricRepaired')],
      ['Assets tested', `${text('metricAssets')} • ${text('metricAssetsSub')}`],
      ['Run status', `${text('metricRun')} • ${text('metricRunSub')}`],
    ]));
    lines.push(section('VIEW / PROGRESS', [
      ['League filter', selected('filterLeague')], ['Health filter', selected('filterHealth')], ['Search', value('filterSearch') || '—'],
      ['Rows', selected('pageSize')], ['Inventory range', text('pageLabel')], ['Inventory count', text('tableCount')],
      ['Progress', `${text('progressLabel')} • ${text('progressDetail')}`],
    ]));
    lines.push(section('OPERATOR CHANNEL HEALTH', [
      ['Console state', `${text('probeGame')} • ${text('probeState')}`], ['Wait condition', text('diagWaiting')],
      ['Service heartbeat', text('diagHeartbeat')], ['Status cache', text('diagStatusCacheAge')], ['Inventory', text('diagInventoryState')],
    ]));
    lines.push(section('CURRENT OPERATION', [
      ['Run', text('diagRun')], ['Queue', text('diagOrdinal')], ['Event', text('diagEvent')],
      ['Phase', text('diagPhase')], ['In phase', text('diagPhaseAge')], ['Last progress', text('diagProgressAge')],
    ]));
    lines.push(section('DATABASE + PRODUCTION PARITY', [
      ['DB state', text('diagDbState')], ['Lock retries', text('diagDbRetries')], ['DB operation', text('diagDbOp')],
      ['Writer state', dbw.state || '—'], ['Writer queue depth', dbw.queueDepth ?? '—'], ['Writer active run', dbw.activeRunId ?? '—'],
      ['Writer active ordinal', dbw.activeOrdinal ?? '—'], ['Writer active event', dbw.activeEvent || '—'], ['Writer active lane', dbw.activeLane ?? '—'],
      ['Writer last error', dbw.lastError || '—'], ['Writer last commit', fmtDateTime(dbw.lastCommitAt)], ['Writer completed writes', dbw.completedWrites ?? '—'],
      ['Media parity', text('diagParity')], ['Production plan', text('diagProductionState')], ['Recovered', text('diagRecovered')],
    ]));
    lines.push(section('MEDIA PROBE', [
      ['Candidates', text('diagCandidates')], ['Candidate', text('diagCandidate')], ['Probe attempt', text('diagProbe')],
      ['Asset', text('diagAsset')], ['Asset key', text('diagAssetKey')], ['Provider', text('diagProvider')],
      ['Probe result', text('diagProbeResult')], ['Discovery', text('diagDiscovery')], ['Browser', text('diagBrowser')], ['Probe origin', text('diagOrigin')],
    ]));
    lines.push(section('PARALLEL WORKER LANES', [['Workers', workersText()]]));
    lines.push(section('MEDIA REPAIR ENGINE', [
      ['Engine', text('repairState')], ['Queue', text('repairQueue')], ['Queue states', JSON.stringify(repair.states || {})],
      ['All repair rows', repair.allRows ?? '—'], ['Eligible now', repair.eligibleNow ?? '—'], ['Cooling down', repair.coolingDown ?? '—'],
      ['Running', repair.running ?? '—'], ['Blocked', repair.blocked ?? '—'], ['Next eligible', fmtDateTime(repair.nextEligibleAt)],
      ['Availability state', repair.availabilityState || '—'], ['Wait reason', repair.waitReason || '—'],
      ['Current game', text('repairGame')], ['Health / target', text('repairTarget')], ['Phase', text('repairPhase')], ['Attempt', text('repairAttempt')],
      ['Discovery stage', text('repairStage')], ['Stage yield', text('repairStageResult')], ['Candidate', text('repairCandidate')],
      ['Provider / result', text('repairResult')], ['Team source registry', text('repairTeamSources')],
      ['Team resolution queue', text('repairTeamResolution')], ['Team resolution states', text('repairTeamStates')],
      ['Source telemetry', text('repairSourceStats')], ['Repair totals', text('repairTotals')],
    ]));
    lines.push(section('REPAIR THROUGHPUT / YIELD', [
      ['Jobs attempted', fmtNum(stats.jobsAttempted)], ['Games promoted/repaired this worker lifetime', fmtNum(stats.gamesRepaired)],
      ['Discovery exhausted', fmtNum(stats.discoveryExhausted)], ['Promotion per job attempt', fmtPct(stats.gamesRepaired, stats.jobsAttempted)],
      ['New candidates', fmtNum(stats.newCandidates)], ['Candidates certified', fmtNum(stats.candidatesCertified)],
      ['Certification yield of new candidates', fmtPct(stats.candidatesCertified, stats.newCandidates)],
      ['Source attempts', fmtNum(stats.sourceAttempts)], ['Source results', fmtNum(stats.sourceResults)], ['Source new', fmtNum(stats.sourceNew)],
      ['New-candidate yield of source results', fmtPct(stats.sourceNew, stats.sourceResults)], ['Known results', fmtNum(stats.sourceDuplicates)],
      ['Eligible known', fmtNum(stats.sourceEligibleKnown)], ['Rejected', fmtNum(stats.sourceRejected)], ['YT search quota blocks', fmtNum(stats.youtubeSearchQuotaBlocks)],
      ['Catalog repaired total', fmtNum(repair.repaired)], ['Current repair queue', fmtNum(repair.queue)],
      ['Catalog unhealthy total', fmtNum((summary.health?.DEGRADED || 0) + (summary.health?.UNPLAYABLE || 0) + (summary.health?.NO_MEDIA || 0))],
    ]));
    lines.push(section('DISCOVERY CIRCUIT', [
      ['State', circuit.state || '—'], ['Threshold', circuit.threshold ?? '—'], ['Cooldown seconds', circuit.cooldownSeconds ?? '—'],
      ['Consecutive failures', circuit.consecutiveFailures ?? '—'], ['Open until', fmtDateTime(circuit.openUntil)], ['Retry in seconds', circuit.retryInSeconds ?? '—'],
      ['Last failure reason', circuit.lastFailureReason || '—'], ['Last failure at', fmtDateTime(circuit.lastFailureAt)],
      ['Last success at', fmtDateTime(circuit.lastSuccessAt)], ['Times opened', circuit.totalOpened ?? '—'],
    ]));
    lines.push(section('YOUTUBE GATEWAY / QUOTA', [
      ['YouTube configured', backend.youtubeConfigured ?? '—'], ['Search quota exhausted', ytSearch.quotaExhausted ?? '—'],
      ['Search cooldown seconds', ytSearch.cooldownSeconds ?? '—'], ['Search reset at', fmtDateTime(ytSearch.resetAt)],
      ['Search failures', ytSearch.failures ?? '—'], ['Search last error', ytSearch.lastError || '—'],
      ['Videos endpoint quota exhausted', backend.youtubeGateway?.videos?.quotaExhausted ?? '—'],
      ['Channels endpoint quota exhausted', backend.youtubeGateway?.channels?.quotaExhausted ?? '—'],
      ['Playlists endpoint quota exhausted', backend.youtubeGateway?.playlists?.quotaExhausted ?? '—'],
      ['Playlist items quota exhausted', backend.youtubeGateway?.playlistitems?.quotaExhausted ?? '—'],
    ]));
    lines.push(section('TEAM SOURCE RESOLUTION', [
      ['Generation', teamSources.generation || '—'], ['Identity matching', teamSources.identityMatching || '—'],
      ['Registry teams', teamSources.teams ?? '—'], ['Verified sources', teamSources.verifiedSources ?? '—'],
      ['Source types', JSON.stringify(teamSources.sourceTypes || {})], ['Directory leagues', teamSources.directoryLeagues ?? '—'],
      ['Directory links', teamSources.directoryLinks ?? '—'], ['Directory errors', teamSources.directoryErrors ?? '—'],
      ['League pages', teamSources.leagueTeamPages ?? '—'], ['Official sites', teamSources.leagueReferredOfficialSites ?? '—'],
      ['YouTube channels', teamSources.youtubeChannels ?? '—'], ['Indexed videos', teamSources.indexedVideos ?? '—'],
      ['Resolution states', JSON.stringify(teamSources.resolutionStates || {})], ['Resolved teams', teamSources.resolvedTeams ?? '—'],
      ['Unresolved teams', teamSources.unresolvedTeams ?? '—'], ['Due unresolved', teamSources.dueUnresolvedTeams ?? '—'],
      ['Cooling unresolved', teamSources.waitingUnresolvedTeams ?? '—'], ['Repair jobs requeued by resolution', teamSources.repairJobsRequeuedByResolution ?? '—'],
      ['Ownership scoping', teamSources.ownershipScoping || '—'],
    ]));
    appendStageRollup(lines, status);
    lines.push(section('TOP RECENT DISCOVERY FAILURE / BLOCK REASONS', Object.entries(reasonRollup(status)).slice(0, 30).map(([reason, count]) => [reason, count])));
    appendUnresolvedTeams(lines, status);

    lines.push('\n## REPAIR WORKERS — COMPLETE SNAPSHOTS');
    repairWorkers(status).forEach((worker, index) => {
      lines.push(`\n### REPAIR WORKER ${index + 1}`);
      lines.push(JSON.stringify(worker, null, 2));
    });
    lines.push('\n## AUDIT WORKERS — COMPLETE SNAPSHOTS');
    (Array.isArray(status.workers) ? status.workers : []).forEach((worker, index) => {
      lines.push(`\n### AUDIT WORKER ${index + 1}`);
      lines.push(JSON.stringify(worker, null, 2));
    });
    lines.push('\n## RECENT REPAIR TRACE — RENDERED');
    lines.push(...traceLines('repairTrace').map(line => `- ${line}`));
    lines.push('\n## SERVER TRACE — RENDERED');
    lines.push(...traceLines('diagTrace').map(line => `- ${line}`));
    lines.push('\n## CURRENT INVENTORY PAGE — HUMAN READABLE');
    const rows = Array.isArray(inventory.rows) ? inventory.rows : [];
    if (!rows.length) lines.push('—');
    rows.forEach((row, index) => lines.push(`${index + 1}. ${row.league || '—'} • ${row.date || row.gameDate || '—'} • ${row.away || row.away_name || row.awayName || '—'} @ ${row.home || row.home_name || row.homeName || '—'} • ${row.health || row.health_state || '—'} • ${row.eventKey || row.event_key || '—'}`));

    lines.push(jsonBlock('RAW MEDIA AUDIT STATUS — COMPLETE JSON', status));
    lines.push(jsonBlock('RAW CORE BACKEND STATUS — COMPLETE JSON', backend));
    lines.push(jsonBlock('RAW CURRENT FILTERED INVENTORY PAGE — COMPLETE JSON', inventory));
    lines.push(jsonBlock('RAW BROWSER / DOM STATE — ALL ELEMENTS WITH IDS', collectDomSnapshot()));
    lines.push(jsonBlock('COPY FETCH METADATA', {auditResult: {...auditResult, data: undefined}, backendResult: {...backendResult, data: undefined}, inventoryResult: {...inventoryResult, data: undefined}}));
    return lines.join('\n').replace(/\n{4,}/g, '\n\n\n').trim() + '\n';
  }

  async function writeClipboard(report) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(report);
        return true;
      }
    } catch (_) {}
    try {
      const ta = document.createElement('textarea');
      ta.value = report;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed'; ta.style.opacity = '0'; ta.style.pointerEvents = 'none';
      document.body.appendChild(ta); ta.focus(); ta.select();
      const ok = document.execCommand('copy'); ta.remove(); return !!ok;
    } catch (_) { return false; }
  }

  async function copyReport() {
    const button = $('copyAuditInfo');
    const old = button?.textContent || 'COPY IMPORTANT INFO';
    if (button) { button.disabled = true; button.textContent = 'BUILDING FULL COPY…'; }
    try {
      const report = await buildReport();
      if (!report || report.length < 100) throw new Error('Media Audit report is not ready');
      const ok = await writeClipboard(report);
      if (!ok) throw new Error('Clipboard write was rejected');
      if (button) {
        const kb = Math.max(1, Math.round(new Blob([report]).size / 1024));
        button.textContent = `COPIED ${kb} KB`;
        button.classList.add('success');
      }
    } catch (error) {
      if (button) button.textContent = 'COPY FAILED';
      console.error('Media Audit copy failed', error);
    } finally {
      setTimeout(() => {
        if (!button) return;
        button.disabled = false; button.textContent = old; button.classList.remove('success');
      }, 3500);
    }
  }

  function bind() { $('copyAuditInfo')?.addEventListener('click', copyReport); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind, {once:true}); else bind();
  window.SBB_MEDIA_AUDIT_COPY = Object.freeze({version:VERSION, buildReport, copy:copyReport});
})();

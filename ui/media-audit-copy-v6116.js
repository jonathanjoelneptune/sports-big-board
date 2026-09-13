/* Sports Big Board v6.1.16 — Media Audit copyable operator report.
   Mirrors the canonical validation-console workflow while keeping the payload
   focused on operator state rather than copying thousands of inventory rows. */
(() => {
  'use strict';
  if (window.SBB_MEDIA_AUDIT_COPY?.version === '6.1.16') return;
  const VERSION = '6.1.16';
  const $ = id => document.getElementById(id);
  const text = id => String($(id)?.textContent || '—').replace(/\s+/g, ' ').trim() || '—';
  const value = id => String($(id)?.value || '').trim();
  const selected = id => {
    const el = $(id);
    if (!el) return '—';
    return String(el.options?.[el.selectedIndex]?.textContent || el.value || '—').trim() || '—';
  };
  const section = (title, rows) => {
    const lines = [`\n## ${title}`];
    for (const [label, val] of rows) lines.push(`${label}: ${val || '—'}`);
    return lines.join('\n');
  };
  const traceLines = id => {
    const el = $(id);
    if (!el) return ['—'];
    const rows = [...el.querySelectorAll('.trace-line,.trace-row,.event-line,.log-line')]
      .map(node => String(node.textContent || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean);
    if (rows.length) return rows;
    const raw = String(el.innerText || el.textContent || '').trim();
    return raw ? raw.split(/\n+/).map(x => x.trim()).filter(Boolean) : ['—'];
  };
  const workers = () => {
    const el = $('diagWorkers');
    if (!el) return '—';
    const rows = [...el.children].map(node => String(node.textContent || '').replace(/\s+/g, ' ').trim()).filter(Boolean);
    return rows.length ? rows.join(' | ') : text('diagWorkers');
  };

  function buildReport() {
    const captured = new Date();
    const release = document.querySelector('.release')?.textContent?.trim() || VERSION;
    const lines = [
      'SPORTS BIG BOARD — MEDIA HEALTH AUDIT',
      `Captured: ${captured.toLocaleString()} (${captured.toISOString()})`,
      `Page: ${location.href}`,
      `Release: ${release}`,
    ];
    lines.push(section('SUMMARY', [
      ['Catalog games', `${text('metricGames')} • ${text('metricGamesSub')}`],
      ['Games audited', `${text('metricAudited')} • ${text('metricAuditedSub')}`],
      ['Healthy', text('metricHealthy')],
      ['Degraded', text('metricDegraded')],
      ['Inconclusive', text('metricInconclusive')],
      ['Unplayable', text('metricUnplayable')],
      ['No media', text('metricNoMedia')],
      ['Repair queue', text('metricRepairQueue')],
      ['Repaired', text('metricRepaired')],
      ['Assets tested', `${text('metricAssets')} • ${text('metricAssetsSub')}`],
      ['Run status', `${text('metricRun')} • ${text('metricRunSub')}`],
    ]));
    lines.push(section('VIEW / PROGRESS', [
      ['League filter', selected('filterLeague')],
      ['Health filter', selected('filterHealth')],
      ['Search', value('filterSearch') || '—'],
      ['Rows', selected('pageSize')],
      ['Inventory range', text('pageLabel')],
      ['Inventory count', text('tableCount')],
      ['Progress', `${text('progressLabel')} • ${text('progressDetail')}`],
    ]));
    lines.push(section('OPERATOR CHANNEL HEALTH', [
      ['Console state', `${text('probeGame')} • ${text('probeState')}`],
      ['Wait condition', text('diagWaiting')],
      ['Service heartbeat', text('diagHeartbeat')],
      ['Status cache', text('diagStatusCacheAge')],
      ['Inventory', text('diagInventoryState')],
    ]));
    lines.push(section('CURRENT OPERATION', [
      ['Run', text('diagRun')], ['Queue', text('diagOrdinal')], ['Event', text('diagEvent')],
      ['Phase', text('diagPhase')], ['In phase', text('diagPhaseAge')], ['Last progress', text('diagProgressAge')],
    ]));
    lines.push(section('DATABASE + PRODUCTION PARITY', [
      ['DB state', text('diagDbState')], ['Lock retries', text('diagDbRetries')], ['DB operation', text('diagDbOp')],
      ['Media parity', text('diagParity')], ['Production plan', text('diagProductionState')], ['Recovered', text('diagRecovered')],
    ]));
    lines.push(section('MEDIA PROBE', [
      ['Candidates', text('diagCandidates')], ['Candidate', text('diagCandidate')], ['Probe attempt', text('diagProbe')],
      ['Asset', text('diagAsset')], ['Asset key', text('diagAssetKey')], ['Provider', text('diagProvider')],
      ['Probe result', text('diagProbeResult')], ['Discovery', text('diagDiscovery')], ['Browser', text('diagBrowser')],
      ['Probe origin', text('diagOrigin')],
    ]));
    lines.push(section('PARALLEL WORKER LANES', [['Workers', workers()]]));
    lines.push(section('MEDIA REPAIR ENGINE', [
      ['Engine', text('repairState')], ['Queue', text('repairQueue')], ['Current game', text('repairGame')],
      ['Health / target', text('repairTarget')], ['Phase', text('repairPhase')], ['Attempt', text('repairAttempt')],
      ['Discovery stage', text('repairStage')], ['Stage yield', text('repairStageResult')], ['Candidate', text('repairCandidate')],
      ['Provider / result', text('repairResult')], ['Team source registry', text('repairTeamSources')],
      ['Team resolution queue', text('repairTeamResolution')], ['Team resolution states', text('repairTeamStates')],
      ['Source telemetry', text('repairSourceStats')], ['Repair totals', text('repairTotals')],
    ]));
    lines.push('\n## RECENT REPAIR TRACE');
    lines.push(...traceLines('repairTrace').map(line => `- ${line}`));
    lines.push('\n## SERVER TRACE');
    lines.push(...traceLines('diagTrace').map(line => `- ${line}`));
    return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n';
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
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      ta.style.pointerEvents = 'none';
      document.body.appendChild(ta);
      ta.focus(); ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      return !!ok;
    } catch (_) {
      return false;
    }
  }

  async function copyReport() {
    const button = $('copyAuditInfo');
    const old = button?.textContent || 'COPY IMPORTANT INFO';
    if (button) { button.disabled = true; button.textContent = 'BUILDING COPY…'; }
    try {
      const report = buildReport();
      if (!report || report.length < 100) throw new Error('Media Audit report is not ready');
      const ok = await writeClipboard(report);
      if (!ok) throw new Error('Clipboard write was rejected');
      if (button) {
        button.textContent = `COPIED ${Math.max(1, Math.round(report.length / 1024))} KB`;
        button.classList.add('success');
      }
    } catch (error) {
      if (button) button.textContent = 'COPY FAILED';
      console.error('Media Audit copy failed', error);
    } finally {
      setTimeout(() => {
        if (!button) return;
        button.disabled = false;
        button.textContent = old;
        button.classList.remove('success');
      }, 3500);
    }
  }

  function bind() { $('copyAuditInfo')?.addEventListener('click', copyReport); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind, {once:true}); else bind();
  window.SBB_MEDIA_AUDIT_COPY = Object.freeze({version:VERSION, buildReport, copy:copyReport});
})();

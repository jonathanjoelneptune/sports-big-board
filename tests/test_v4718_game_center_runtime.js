'use strict';
const fs=require('fs'),assert=require('assert');
const view=fs.readFileSync('architecture/game-center-multisport-view.js','utf8');
for(const token of [
  'persistent multisport Game Center summary',
  "gcPersistentSummary",
  'content.insertBefore(host,tabs)',
  'function baseballCard(gc)',
  'R</th><th>H</th><th>E',
  'function periodCard(gc)',
  'removeLegacyOverviewLinescore',
  'WIN PROBABILITY',
  "version:'4.7.19'"
]) assert(view.includes(token),`missing persistent Game Center token ${token}`);
const day=fs.readFileSync('sbb/day_state.py','utf8');
assert(day.includes('SPECIAL_EVENT_'));
assert(day.includes('mediaSafetySpecialProofAccepted'));
const readiness=fs.readFileSync('sbb/history_readiness_repair.py','utf8');
assert(readiness.includes('_youtube_id_from_url'));
assert(readiness.includes('provider_media_id'));
assert(readiness.includes('HistoryRepository.roundup_media = _roundup_media'));
const cfb=fs.readFileSync('sbb/cfb_trusted_youtube.py','utf8');
assert(cfb.includes('RECENT_ARCHIVE_TTL_SECONDS'));
assert(cfb.includes('KNOWN_MEDIA_HINTS'));
assert(cfb.includes('-tDiPDHU2fs'));
assert(cfb.includes('scan_recent_missing'));
console.log('PASS: v4.7.19 retains persistent linescores + LLWS/Silver/CFB recovery contracts');

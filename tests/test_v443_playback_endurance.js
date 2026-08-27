'use strict';
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const version=fs.readFileSync(path.join(root,'VERSION'),'utf8').trim();
const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
const terminal=fs.readFileSync(path.join(root,'architecture/playback-terminal.js'),'utf8');
const index=fs.readFileSync(path.join(root,'index.html'),'utf8');
const css=fs.readFileSync(path.join(root,'ui/playback-terminal.css'),'utf8');
const core=fs.readFileSync(path.join(root,'core-model.js'),'utf8');

assert(app.includes('PLAYBACK_ENGINE_FAILURE_THRESHOLD=3'),'systemic startup failure threshold missing');
assert(app.includes('TRANSIENT_UNPLAYABLE_MEDIA=new Map()'),'transient failure quarantine missing');
assert(app.includes("window.SBB_PLAYBACK_ENGINE=Object.freeze"),'playback engine authority missing');
assert(app.includes('RECENT_HISTORY_AUTOFILL_DAYS=3'),'three-day recent-history refill missing');
assert(app.includes('currentGameKey:()=>programGameIdentity'),'endurance current-game hook missing');
assert(app.includes('currentIsFullRecap:()=>isFullRecapCandidate'),'endurance recap hook missing');

const completion=app.slice(app.indexOf('function advanceAfterCompletedItem'),app.indexOf('function advance(direction=1)'));
assert(completion.includes('!isFullRecapCandidate(finished)'),'completion must use semantic recap classification');
assert(!completion.includes('!finished?.overview'),'raw overview flag must not control recap completion');
const queue=app.slice(app.indexOf('function nextVisibleQueueIndex'),app.indexOf('function renderQueue'));
assert(queue.includes('!isFullRecapCandidate(current)'),'next queue item must use semantic recap classification');
assert(app.includes('preferGameOverviews(expandMediaVersions'),'score-card recap selection must compare alternate versions');

assert(terminal.includes('FIRST_FRAME_WATCHDOG_MS=28_000'),'first-frame watchdog missing');
assert(terminal.includes('DUPLICATE_GAME_RECAP'),'same-game alternate recap failure guard missing');
assert(terminal.includes('UNRECOVERABLE_NO_FIRST_FRAME'),'unrecoverable no-frame failure guard missing');
assert(terminal.includes('chaosDisruptStandby'),'hammer standby disruption missing');
assert(terminal.includes('forcePlaybackEngineReset'),'automatic playback engine reset missing');
assert(index.includes('id="playbackEnduranceStart"'),'terminal endurance start control missing');
assert(index.includes('id="playbackEnduranceStop"'),'terminal endurance stop control missing');
assert(index.includes(`architecture/playback-terminal.js?v=${version}`),'terminal cache-bust version stale');
assert(index.includes(`app.js?v=${version}`),'app cache-bust version stale');
assert(css.includes('.pt-endurance'),'endurance terminal styling missing');
assert(core.includes(`version:'${version}'`),'core model version stale');
console.log(`PASS: v${version} retains the v4.4.3 playback-resilience baseline`);

'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const ROOT=path.resolve(__dirname,'..');
const VERSION=fs.readFileSync(path.join(ROOT,'VERSION'),'utf8').trim();
const cert=fs.readFileSync(path.join(ROOT,'architecture/comprehensive-site-certification.js'),'utf8');
const gc=fs.readFileSync(path.join(ROOT,'architecture/game-center-contract.js'),'utf8');
const index=fs.readFileSync(path.join(ROOT,'index.html'),'utf8');

// v4.8 supersedes the original v4.7.20 certification behavior while retaining
// the Game Center watchdog introduced by this gate. Worker recovery remains owned
// by its backend regression contracts rather than this browser certification gate.
assert(cert.includes('COMPREHENSIVE SITE CERTIFICATION'));
assert(cert.includes("window.SBB_EFFICIENCY?.runAutoTest?.()"));
assert(cert.includes("/api/history/worker-console?limit=320"));
assert(cert.includes("/api/history/audit?limit=1&offset=0"));
assert(cert.includes("/api/history/catalog/collections?limit=1&offset=0"));
assert(cert.includes("/api/history/media-sources"));
assert(cert.includes('gameCenterCensus'));
assert(cert.includes('playbackInteractionMatrix'));
assert(cert.includes('PLAYBACK INTERACTION MATRIX'));
assert(cert.includes('CERT_WINDOW_DELTA'));
assert(cert.includes('ACTION ITEMS'));
assert(cert.includes('SBB_PLAYBACK_PROGRESS_WATCHDOG'));
assert(!cert.includes('USC_EVENT_FOUND'));
assert(!cert.includes('401864494'));
assert(index.includes(`architecture/comprehensive-site-certification.js?v=${VERSION}`));

assert(gc.includes("watchdogVersion:'v4726'"));
assert(gc.includes('pending after ${polls} checks'));
assert(gc.includes('Game Center preparation exceeded the browser safety limit'));
assert(gc.includes('const inflight=new Map()'));
assert(gc.includes('boundPayload'));
assert(gc.includes('timeline.length>500'));


console.log('PASS: legacy v4.7.26 Game Center safeguards preserved under v4.8 comprehensive architecture');

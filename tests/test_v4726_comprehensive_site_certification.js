'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const ROOT=path.resolve(__dirname,'..');
const cert=fs.readFileSync(path.join(ROOT,'architecture/comprehensive-site-certification.js'),'utf8');
const gc=fs.readFileSync(path.join(ROOT,'architecture/game-center-contract.js'),'utf8');
const index=fs.readFileSync(path.join(ROOT,'index.html'),'utf8');
const runtime=fs.readFileSync(path.join(ROOT,'sbb/runtime_path_repair_v4720.py'),'utf8');

assert(cert.includes('COMPREHENSIVE SITE CERTIFICATION'));
assert(cert.includes("window.SBB_EFFICIENCY?.runAutoTest?.()"));
assert(cert.includes("/api/history/worker-console?limit=320"));
assert(cert.includes("/api/history/audit?limit=1&offset=0"));
assert(cert.includes("/api/history/catalog/collections?limit=1&offset=0"));
assert(cert.includes("/api/history/media-sources"));
assert(cert.includes("gameCenterCensus"));
assert(cert.includes("playbackObservation"));
assert(cert.includes("CERT_WINDOW_DELTA"));
assert(cert.includes("ACTION ITEMS"));
assert(cert.includes("USC_EVENT_FOUND"));
assert(index.includes('architecture/comprehensive-site-certification.js?v=4.7.20'));

assert(gc.includes("watchdogVersion:'v4726'"));
assert(gc.includes('pending after ${polls} checks'));
assert(gc.includes('Game Center preparation exceeded the browser safety limit'));
assert(gc.includes('const inflight=new Map()'));
assert(gc.includes('boundPayload'));
assert(gc.includes('timeline.length>500'));

assert(runtime.includes('__sbbAlwaysOnWorkersV4725'));
assert(runtime.includes('"workers":[1,2,3,4,5]'));
assert(runtime.includes('return True,""'));

console.log('PASS: v4.7.20 comprehensive site certification + Game Center watchdog + always-on workers');

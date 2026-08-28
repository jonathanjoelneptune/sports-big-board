const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync('architecture/media-intelligence-console.js','utf8');
assert(src.includes('SCAN CURRENT'),'operator console must expose current-media priority scan');
assert(src.includes('KNOWN HAS MUSIC')&&src.includes('KNOWN NO MUSIC'),'operator console must expose deterministic reference sets');
assert(src.includes('/api/media-intelligence/status')&&src.includes('/api/media-intelligence/scan'),'operator console must use server intelligence API');
assert(src.includes('registerDb'),'fresh persisted intelligence must be re-registered into browser arbitration');
assert(!src.includes('MutationObserver'),'visibility console must not add DOM observation churn');
new vm.Script(src);
console.log('PASS: v4.5.2 Media Intelligence operator console + priority scan contract');

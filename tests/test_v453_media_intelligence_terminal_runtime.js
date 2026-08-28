const fs=require('fs'),vm=require('vm'),assert=require('assert');
const term=fs.readFileSync('architecture/playback-terminal.js','utf8');
const con=fs.readFileSync('architecture/media-intelligence-console.js','utf8');
for(const token of ['MCONF=','MRATIO=','MSCAN=','SITE_MUSIC=','playback-terminal-auto','priority:250','enrichMediaIntel(row,{autoQueue:true})'])assert(term.includes(token),`missing terminal Media Intelligence token ${token}`);
assert(con.includes('window.SBB_API?.url?.(path)||path'),'console must explicitly route API calls through deployment-aware SBB_API');
new vm.Script(term);new vm.Script(con);
console.log('PASS: v4.5.3 Playback Terminal Media Intelligence columns + auto-priority scan contract');

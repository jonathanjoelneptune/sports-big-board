const fs=require('fs');
const path=require('path');
const root=path.resolve(__dirname,'..');
const src=fs.readFileSync(path.join(root,'architecture/key-info-current-v520.js'),'utf8');
function ok(cond,msg){if(!cond){console.error('FAIL',msg);process.exitCode=1;}else console.log('PASS',msg);}
ok(src.includes("const VERSION='5.2.5'"),'Sports Ticker module is v5.2.5');
ok(src.includes('const REFRESH_MS=20*60*1000'),'Sports Ticker refreshes three times per hour');
ok(src.includes('const MAX_ROWS=150'),'Sports Ticker can render 150 entries');
ok(!src.includes('scoreBrowseDate'),'Sports Ticker has no scoreBrowseDate dependency');
ok(src.includes('renderActiveSportKeyInformation=renderNoop'),'legacy active-sport/date render is a no-op');
ok(src.includes('refreshKeyInformation=refreshNoop'),'legacy date/news refresh entry point is a no-op');
ok(src.includes('const merged=dedupe([...newRows,...currentRows])'),'new ticker stories are prepended');
ok(src.includes('const desiredX=previous.x-prefixWidth'),'marquee position compensates for prepended story width');
ok(src.includes('belt.style.animationDelay='),'ticker resumes at a preserved animation position');
ok(src.includes('for(let offset=0;offset<rows.length;offset+=20)'),'established click renderer is batched beyond its old 20-item cap');
ok(src.includes("try{payload=await fetchJson('/api/sports-ticker',1800)"),'browser reads persisted Sports Ticker endpoint');
if(process.exitCode)process.exit(process.exitCode);

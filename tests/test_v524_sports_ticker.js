const fs=require('fs');
function need(path,token){const s=fs.readFileSync(path,'utf8');if(!s.includes(token))throw new Error(`${path} missing ${token}`);}
need('architecture/key-info-current-v520.js',"const VERSION='5.2.4'");
need('architecture/key-info-current-v520.js','SPORTS TICKER');
need('architecture/key-info-current-v520.js','20*60*1000');
need('architecture/key-info-current-v520.js',"/api/sports-ticker");
need('architecture/key-info-current-v520.js','data-score-filter="NCAAF"');
need('architecture/date-transition-coordinator.js',"const VERSION='5.2.4'");
need('architecture/date-transition-coordinator.js','maxSnapshotReadsPerTransition:5');
need('architecture/date-transition-coordinator.js','__sbbDateCoordinatorV524');
console.log('PASS v5.2.4 Sports Ticker + date ownership invariants');

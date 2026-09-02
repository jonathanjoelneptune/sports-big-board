const fs=require('fs');
const path=require('path');
const root=path.resolve(__dirname,'..');
const js=fs.readFileSync(path.join(root,'architecture','key-info-current-v520.js'),'utf8');
const dev=fs.readFileSync(path.join(root,'architecture','dev-mode.js'),'utf8');
const index=fs.readFileSync(path.join(root,'index.html'),'utf8');
function need(ok,msg){if(!ok){console.error('FAIL',msg);process.exitCode=1;}else console.log('PASS',msg);}

need(js.includes("const VERSION='5.2.8'"),'Sports Ticker module is v5.2.8');
need(js.includes("engine:'COMPOSITOR_WAAPI_LOOP'"),'ticker declares compositor-owned animation engine');
need(js.includes('mainThreadPerFrame:false')&&js.includes('forcedLayoutReadsPerFrame:0'),'ticker declares zero per-frame JS/layout work');
need(js.includes('tickerAnimation=conveyorGroup.animate(['),'ticker hands one transform animation to Web Animations/compositor');
need(js.includes('iterations:Infinity')&&js.includes("easing:'linear'"),'ticker animation is an infinite linear crawl');
need(!js.includes('function tickerFrame('),'v5.2.7 requestAnimationFrame hot loop is retired');
need(!js.includes('segmentStep()'),'per-frame story geometry helper is retired');
need(js.includes('getBoundingClientRect().width')&&js.includes('function buildGeometryAndStart'),'geometry is measured only during edition/tuning builds');
need(js.includes('const DEFAULT_TUNING=Object.freeze({height:40,fontSize:10.5,lines:1,speed:20,gap:18})'),'default crawl is reduced to 20px/s');
need(js.includes('speed:[4,60]'),'Dev speed tuning includes very calm speeds down to 4px/s');
need(js.includes('function ensureDevUtility()'),'Sports Ticker Dev Utility can self-inject at runtime');
need(js.includes("window.addEventListener('sbb:dev-mode'"),'ticker utility responds to the one global Dev Mode event');
need(js.includes("'/api/sports-ticker/refresh'"),'RUN SPORTS TICKER AI remains wired');
need(js.includes('.key-info-item.breaking .key-info-type'),'BREAKING pill color remains restored');
need(js.includes('.key-info-item.transaction .key-info-type'),'TRANSACTION pill color remains restored');
need(js.includes('.key-info-item.record .key-info-type'),'RECORD pill color remains restored');
need(js.includes('renderActiveSportKeyInformation=renderNoop')&&js.includes('refreshKeyInformation=refreshNoop'),'score-date changes remain isolated from Sports Ticker');

for(const control of ['sportsTickerHeight','sportsTickerFontSize','sportsTickerLines','sportsTickerSpeed','sportsTickerGap','sportsTickerPauseBtn','sportsTickerCopyTuningBtn','sportsTickerAiRefreshBtn']){
  need(index.includes(`id="${control}"`),`${control} is present in Settings HTML`);
}
need(index.includes('id="sportsTickerSpeed" type="range" min="4" max="60" step="1" value="20"'),'static Settings utility uses v5.2.8 speed range/default');
need(!index.includes('id="devModeToggleBtn"'),'nested Settings Dev switch remains removed');

need(dev.includes("const VERSION='5.2.8'"),'global Dev authority is v5.2.8');
need(dev.includes('const CLICK_TARGET=5'),'global Dev unlock is five brand clicks');
need(dev.includes('const CLICK_WINDOW_MS=6000'),'five-click window is forgiving enough for normal use');
need(dev.includes("document.addEventListener('click',onCapturedBrandClick,true)"),'brand gesture is captured at document level');
need(dev.includes("target.closest('.brand')"),'any visible Sports Big Board brand child counts');
need(dev.includes("const SESSION_KEY='sbb.dev.enabled.v528'"),'global Dev Mode persists for the browser session');
need(dev.includes("window.dispatchEvent(new CustomEvent('sbb:dev-mode'"),'all developer utilities receive one global event');
need(dev.includes('ALL DEV UTILITIES ENABLED'),'successful unlock gives visible confirmation');
if(process.exitCode)process.exit(process.exitCode);

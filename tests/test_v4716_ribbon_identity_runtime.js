const fs=require('fs');
const vm=require('vm');
const assert=require('assert');

class ClassList{
  constructor(...items){this.s=new Set(items)}
  contains(x){return this.s.has(x)} add(x){this.s.add(x)} remove(x){this.s.delete(x)}
  [Symbol.iterator](){return this.s[Symbol.iterator]()}
}
function card(match){
  const small={dataset:{},textContent:'YESTERDAY'};
  const attrs={'aria-label':'ARI at SF: full recap available'};
  return {
    __sbbMatch:match,dataset:{},classList:new ClassList('score-card','league-mlb'),title:'Play MLB quick full recap',
    querySelector(sel){return sel==='.score-card-top small'?small:null},
    getAttribute(k){return attrs[k]||''},setAttribute(k,v){attrs[k]=String(v)},
    _small:small,_attrs:attrs
  };
}
const cards=[
  card({competitionId:'MLB',id:'g1',date:'2026-08-29',scheduledAt:'2026-08-29T13:05:00-07:00',away:'ARI',home:'SF'}),
  card({competitionId:'MLB',id:'g2',date:'2026-08-29',scheduledAt:'2026-08-29T19:05:00-07:00',away:'ARI',home:'SF'}),
  card({competitionId:'MLB',id:'g2',date:'2026-08-29',scheduledAt:'2026-08-29T19:05:00-07:00',away:'ARI',home:'SF'}),
];
const host={children:cards};
const styleNodes=new Map();
global.window=global;
global.document={
  readyState:'complete',
  getElementById(id){return id==='scoreCells'?host:(styleNodes.get(id)||null)},
  createElement(tag){return {tagName:tag.toUpperCase(),id:'',textContent:''}},
  head:{appendChild(node){if(node.id)styleNodes.set(node.id,node)}},
  addEventListener(){}
};
global.CustomEvent=function(type,opts){this.type=type;this.detail=opts?.detail};
global.dispatchEvent=()=>true;
global.addEventListener=()=>{};
global.requestAnimationFrame=fn=>{fn();return 1};
global.setInterval=()=>1;global.clearInterval=()=>{};global.setTimeout=()=>1;global.clearTimeout=()=>{};

global.scoreCardPlayableItems=()=>[
  {id:'bad',title:'D-BACKS vs. GIANTS: Official Full Game Highlights (August 28) | 2026 MLB Season'},
  {id:'good',title:'D-BACKS vs. GIANTS: Official Full Game Highlights (August 29) | 2026 MLB Season'},
];
vm.runInThisContext(fs.readFileSync('architecture/score-ribbon-identity-guard.js','utf8'),{filename:'score-ribbon-identity-guard.js'});

const filtered=global.scoreCardPlayableItems({competitionId:'MLB',date:'2026-08-29',id:'g2'});
assert.deepStrictEqual(filtered.map(x=>x.id),['good'],'explicit Aug 28 title must not satisfy Aug 29 MLB game');
const snap=global.SBB_SCORE_RIBBON_IDENTITY_GUARD.reconcile();
assert.strictEqual(cards[0]._small.textContent,'YESTERDAY • GAME 1');
assert.strictEqual(cards[1]._small.textContent,'YESTERDAY • GAME 2');
assert(cards[2].classList.contains('sbb-exact-duplicate'),'same canonical event id is defensively suppressed');
assert.strictEqual(snap.doubleheaderGroups,1);
assert.strictEqual(snap.exactDuplicatesHidden,1);
console.log('PASS: v4.7.16 doubleheader identity + explicit MLB recap-date guard');

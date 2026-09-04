/* Sports Big Board v5.4.9 — WebHID controller bridge.
   Gamepad API remains primary. This read-only bridge exists for controllers and
   proprietary wireless receivers that Windows/vendor software can see but the
   browser Gamepad API does not expose. A one-time user gesture is required by
   WebHID to grant device access. No output/feature reports are sent. */
(() => {
  'use strict';
  if(window.SBB_CONTROLLER_HID_BRIDGE?.version==='5.4.9')return;
  const VERSION='5.4.9';
  const TURTLE_BEACH_VENDOR_ID=0x10f5;
  const STEALTH_ULTRA_WIRELESS_PID=0x7070;
  const STEALTH_ULTRA_WIRED_PID=0x7073;
  const BUTTON_COUNT=18;
  const AXIS_COUNT=4;
  const DEADZONE=.035;

  let device=null,connected=false,authorized=false,live=false,lastReportAt=0,reportCount=0;
  let lastReportId=0,lastBytes=[],lastParser='',lastError='',openAttempts=0,pairAttempts=0;
  let synthetic=null,buttonValues=Array(BUTTON_COUNT).fill(0),axes=Array(AXIS_COUNT).fill(0);
  let reportDescriptors=new Map();
  const listeners=new Set();

  const clean=v=>String(v??'').trim();
  const supported=()=>!!navigator?.hid;
  const now=()=>performance?.now?.()||Date.now();
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const makeButton=v=>({pressed:Number(v)>=.5,touched:Number(v)>0,value:clamp(Number(v)||0,0,1)});
  const notify=(reason='state')=>{
    buildSynthetic();
    const detail=snapshot();
    try{document.dispatchEvent(new CustomEvent('sbb:controller-hid-change',{detail:{...detail,reason}}));}catch(_){}
    for(const fn of listeners){try{fn(detail);}catch(_){}}
  };

  function stateLabel(){
    if(!supported())return 'WebHID unavailable';
    if(lastError)return `HID error: ${lastError}`;
    if(!authorized)return 'HID permission not granted';
    if(!device)return 'HID authorized • receiver not connected';
    if(!connected)return 'HID device closed';
    if(live)return `HID live • ${clean(device.productName)||'controller'}`;
    return `HID ready • ${clean(device.productName)||'controller'} • waiting for input`;
  }
  function productLabel(dev=device){
    if(!dev)return 'Turtle Beach Controller';
    const name=clean(dev.productName)||'Turtle Beach HID';
    const pid=Number(dev.productId||0).toString(16).padStart(4,'0');
    return `${name} [10f5:${pid}]`;
  }
  function buildSynthetic(){
    if(!device||!connected){synthetic=null;return null;}
    synthetic={
      id:`${productLabel(device)} • WebHID`,index:-543,connected:true,mapping:'standard',timestamp:now(),
      buttons:buttonValues.map(makeButton),axes:[...axes],vibrationActuator:null,hapticActuators:[]
    };
    return synthetic;
  }
  function gamepad(){return buildSynthetic();}

  function resetState(){
    buttonValues=Array(BUTTON_COUNT).fill(0);axes=Array(AXIS_COUNT).fill(0);live=false;lastParser='';
    buildSynthetic();
  }
  function setButton(index,value){if(index>=0&&index<BUTTON_COUNT)buttonValues[index]=clamp(Number(value)||0,0,1);}
  function setAxis(index,value){if(index>=0&&index<AXIS_COUNT)axes[index]=Math.abs(Number(value)||0)<DEADZONE?0:clamp(Number(value)||0,-1,1);}
  function u16le(bytes,o){return (bytes[o]||0)|((bytes[o+1]||0)<<8);}
  function i16le(bytes,o){const v=u16le(bytes,o);return v&0x8000?v-0x10000:v;}

  // Microsoft GIP gamepad payload. This is read-only parsing of already-delivered
  // upstream input. The bridge never attempts the vendor/Xbox initialization or
  // authentication handshake itself.
  function parseGip(bytes,reportId){
    let o=-1;
    if(bytes.length>=18&&bytes[0]===0x20)o=4;                 // full GIP packet
    else if(reportId===0x20&&bytes.length>=14)o=0;           // WebHID report-id stripped
    else if(bytes.length===14)o=0;                           // payload-only interface
    if(o<0||bytes.length<o+14)return false;
    const lo=bytes[o],hi=bytes[o+1];
    setButton(0,(lo&0x10)?1:0); // A
    setButton(1,(lo&0x20)?1:0); // B
    setButton(2,(lo&0x40)?1:0); // X
    setButton(3,(lo&0x80)?1:0); // Y
    setButton(8,(lo&0x08)?1:0); // View
    setButton(9,(lo&0x04)?1:0); // Menu
    setButton(4,(hi&0x10)?1:0); // LB
    setButton(5,(hi&0x20)?1:0); // RB
    setButton(10,(hi&0x40)?1:0);// LS
    setButton(11,(hi&0x80)?1:0);// RS
    setButton(12,(hi&0x01)?1:0);// Up
    setButton(13,(hi&0x02)?1:0);// Down
    setButton(14,(hi&0x04)?1:0);// Left
    setButton(15,(hi&0x08)?1:0);// Right
    setButton(6,u16le(bytes,o+2)/1023); // LT
    setButton(7,u16le(bytes,o+4)/1023); // RT
    setAxis(0,i16le(bytes,o+6)/32767);
    setAxis(1,-i16le(bytes,o+8)/32767);
    setAxis(2,i16le(bytes,o+10)/32767);
    setAxis(3,-i16le(bytes,o+12)/32767);
    lastParser='GIP';
    return true;
  }

  function usageParts(raw,fallbackPage=0){
    const n=Number(raw||0)>>>0;
    const page=(n>>>16)||Number(fallbackPage||0);
    return {page,id:n&0xffff};
  }
  function signExtend(value,bits){if(bits<=0||bits>=32)return value;const sign=1<<(bits-1),mask=(1<<bits)-1;value&=mask;return value&sign?value-(1<<bits):value;}
  function readBits(view,offset,bits,signed=false){
    if(bits<=0||bits>24)return 0;let value=0;
    for(let i=0;i<bits;i++){const bit=offset+i,byte=view.getUint8(bit>>3),v=(byte>>(bit&7))&1;value|=v<<i;}
    return signed?signExtend(value,bits):value;
  }
  function normalizeLogical(v,min,max){
    min=Number(min);max=Number(max);if(!Number.isFinite(min)||!Number.isFinite(max)||max===min)return 0;
    if(min<0&&max>0)return clamp(v/Math.max(Math.abs(min),Math.abs(max)),-1,1);
    return clamp(((v-min)/(max-min))*2-1,-1,1);
  }
  function descriptorReports(collections=[],out=[]){
    for(const c of collections||[]){
      for(const r of c?.inputReports||[])out.push({report:r,usagePage:Number(c?.usagePage||0),usage:Number(c?.usage||0)});
      descriptorReports(c?.children||[],out);
    }
    return out;
  }
  function rebuildDescriptors(){
    reportDescriptors=new Map();
    for(const entry of descriptorReports(device?.collections||[])){
      const id=Number(entry.report?.reportId||0);if(!reportDescriptors.has(id))reportDescriptors.set(id,[]);reportDescriptors.get(id).push(entry);
    }
  }
  function usageList(item,page){
    const direct=Array.isArray(item?.usages)?item.usages.map(u=>usageParts(u,page)):[];
    if(direct.length)return direct;
    const lo=Number(item?.usageMinimum);const hi=Number(item?.usageMaximum);
    if(Number.isFinite(lo)&&Number.isFinite(hi)&&hi>=lo&&hi-lo<128){const out=[];for(let u=lo;u<=hi;u++)out.push(usageParts(u,page));return out;}
    return [];
  }
  function parseGenericHid(dataView,reportId){
    const entries=reportDescriptors.get(Number(reportId||0))||reportDescriptors.get(0)||[];
    if(!entries.length)return false;
    let handled=false;
    for(const entry of entries){
      let bitOffset=0;
      for(const item of entry.report?.items||[]){
        const size=Number(item?.reportSize||0),count=Number(item?.reportCount||0);if(!size||!count)continue;
        const usages=usageList(item,entry.usagePage);const min=Number(item?.logicalMinimum??0),max=Number(item?.logicalMaximum??((1<<Math.min(size,16))-1));
        const signed=min<0;
        for(let i=0;i<count;i++){
          const value=readBits(dataView,bitOffset+i*size,size,signed);
          const usage=usages[Math.min(i,Math.max(0,usages.length-1))]||{page:entry.usagePage,id:0};
          if(usage.page===0x09&&usage.id>=1&&usage.id<=16){ // HID Button page
            const map=[0,1,2,3,4,5,8,9,10,11,16,17,12,13,14,15];
            const target=map[usage.id-1];if(target!=null)setButton(target,value!==0?1:0);handled=true;
          }else if(usage.page===0x01){
            if(usage.id===0x30){setAxis(0,normalizeLogical(value,min,max));handled=true;} // X
            else if(usage.id===0x31){setAxis(1,normalizeLogical(value,min,max));handled=true;} // Y
            else if(usage.id===0x33){setAxis(2,normalizeLogical(value,min,max));handled=true;} // Rx
            else if(usage.id===0x34){setAxis(3,normalizeLogical(value,min,max));handled=true;} // Ry
            else if(usage.id===0x32){setButton(6,(normalizeLogical(value,min,max)+1)/2);handled=true;} // Z/LT
            else if(usage.id===0x35){setButton(7,(normalizeLogical(value,min,max)+1)/2);handled=true;} // Rz/RT
            else if(usage.id===0x39){ // Hat switch 0..7, neutral commonly 8
              const h=Number(value);setButton(12,[0,1,7].includes(h)?1:0);setButton(15,[1,2,3].includes(h)?1:0);setButton(13,[3,4,5].includes(h)?1:0);setButton(14,[5,6,7].includes(h)?1:0);handled=true;
            }
          }
        }
        bitOffset+=size*count;
      }
    }
    if(handled)lastParser='HID DESCRIPTOR';
    return handled;
  }

  function onInputReport(event){
    try{
      const data=event?.data;if(!data)return;const bytes=Array.from(new Uint8Array(data.buffer,data.byteOffset,data.byteLength));
      lastReportId=Number(event.reportId||0);lastBytes=bytes.slice(0,48);lastReportAt=Date.now();reportCount++;lastError='';
      const parsed=parseGip(bytes,lastReportId)||parseGenericHid(data,lastReportId);
      if(parsed){live=true;buildSynthetic();notify('inputreport');}
      else{lastParser='RAW/UNMAPPED';notify('unmapped-inputreport');}
    }catch(err){lastError=clean(err?.message||err);notify('input-error');}
  }

  async function openDevice(dev,{reason='open'}={}){
    if(!dev)return false;openAttempts++;lastError='';
    try{
      if(!dev.opened)await dev.open();
      if(device&&device!==dev){try{device.removeEventListener('inputreport',onInputReport);}catch(_){}}
      device=dev;authorized=true;connected=!!dev.opened;resetState();rebuildDescriptors();
      dev.removeEventListener?.('inputreport',onInputReport);dev.addEventListener?.('inputreport',onInputReport);
      notify(reason);return connected;
    }catch(err){device=dev;authorized=true;connected=false;lastError=clean(err?.message||err);notify('open-error');return false;}
  }
  function chooseDevice(devices=[]){
    const all=[...devices];
    return all.find(d=>Number(d.vendorId)===TURTLE_BEACH_VENDOR_ID&&Number(d.productId)===STEALTH_ULTRA_WIRELESS_PID)
      ||all.find(d=>Number(d.vendorId)===TURTLE_BEACH_VENDOR_ID&&/stealth ultra/i.test(clean(d.productName)))
      ||all.find(d=>Number(d.vendorId)===TURTLE_BEACH_VENDOR_ID)
      ||null;
  }
  async function restore(){
    if(!supported())return false;
    try{const devices=await navigator.hid.getDevices();authorized=devices.some(d=>Number(d.vendorId)===TURTLE_BEACH_VENDOR_ID);const dev=chooseDevice(devices);if(dev)return openDevice(dev,{reason:'restore'});notify('restore-none');return false;}
    catch(err){lastError=clean(err?.message||err);notify('restore-error');return false;}
  }
  async function pair(){
    if(!supported()){lastError='WebHID is unavailable in this browser';notify('unsupported');return false;}
    pairAttempts++;lastError='';
    try{
      const devices=await navigator.hid.requestDevice({filters:[{vendorId:TURTLE_BEACH_VENDOR_ID}]});
      const dev=chooseDevice(devices);if(!dev){notify('pair-cancelled');return false;}
      return openDevice(dev,{reason:'paired'});
    }catch(err){
      const name=clean(err?.name);if(name!=='NotFoundError')lastError=clean(err?.message||err);notify(name==='NotFoundError'?'pair-cancelled':'pair-error');return false;
    }
  }
  async function forget(){
    if(device){try{device.removeEventListener('inputreport',onInputReport);}catch(_){}try{if(device.opened)await device.close();}catch(_){} }
    device=null;connected=false;live=false;resetState();notify('closed');return true;
  }
  function onConnect(event){const d=event?.device;if(Number(d?.vendorId)===TURTLE_BEACH_VENDOR_ID)openDevice(d,{reason:'hid-connect'});}
  function onDisconnect(event){if(device&&event?.device===device){connected=false;live=false;notify('hid-disconnect');}}
  function bindSettings(){
    const btn=document.getElementById('controllerHidPairBtn');if(btn&&!btn.dataset.bound){btn.dataset.bound='1';btn.addEventListener('click',pair);}
    const stat=document.getElementById('controllerHidStatus');if(stat)stat.textContent=stateLabel();
  }
  function snapshot(){return {
    version:VERSION,supported:supported(),authorized,connected,live,productName:clean(device?.productName),vendorId:Number(device?.vendorId||0),productId:Number(device?.productId||0),
    expectedVendorId:TURTLE_BEACH_VENDOR_ID,wirelessProductId:STEALTH_ULTRA_WIRELESS_PID,wiredProductId:STEALTH_ULTRA_WIRED_PID,
    opened:!!device?.opened,reportCount,lastReportAt,lastReportId,lastBytes:[...lastBytes],lastParser,lastError,openAttempts,pairAttempts,state:stateLabel(),
    collections:(device?.collections||[]).map(c=>({usagePage:c.usagePage,usage:c.usage,inputReports:(c.inputReports||[]).map(r=>r.reportId)}))
  };}
  function subscribe(fn){if(typeof fn!=='function')return()=>{};listeners.add(fn);return()=>listeners.delete(fn);}
  function init(){
    bindSettings();
    if(supported()){
      navigator.hid.addEventListener?.('connect',onConnect);navigator.hid.addEventListener?.('disconnect',onDisconnect);
      restore();
    }else notify('unsupported');
    document.addEventListener('sbb:controller-hid-change',bindSettings);
  }

  window.SBB_CONTROLLER_HID_BRIDGE=Object.freeze({
    version:VERSION,installed:true,vendorId:TURTLE_BEACH_VENDOR_ID,supported,gamepad,pair,restore,forget,snapshot,subscribe,
    get authorized(){return authorized;},get connected(){return connected;},get live(){return live;},get device(){return device;}
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();

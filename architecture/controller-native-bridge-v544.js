/* Sports Big Board v5.4.4 — Native Windows Controller Bridge transport.
   Browser Gamepad remains the preferred zero-install transport. When Chrome does
   not expose a Windows controller (notably the Turtle Beach Stealth Ultra 2.4GHz
   receiver), this module consumes normalized state from the loopback-only Sports
   Big Board Controller Bridge at ws://127.0.0.1:5410. No controller data leaves
   the local machine and the page sends no control commands to the helper. */
(() => {
  'use strict';
  if(window.SBB_CONTROLLER_NATIVE_BRIDGE?.version==='5.4.4')return;
  const VERSION='5.4.4';
  const PROTOCOL=1;
  const ENDPOINTS=['ws://127.0.0.1:5410/sbb-controller','ws://localhost:5410/sbb-controller'];
  const RECONNECT_MIN=700;
  const RECONNECT_MAX=5000;
  const STALE_MS=2500;
  const BUTTON_COUNT=18;
  const AXIS_COUNT=4;

  let socket=null,endpointIndex=0,reconnectTimer=0,reconnectDelay=RECONNECT_MIN;
  let transportConnected=false,controllerConnected=false,live=false;
  let controllerId='',controllerSource='',bridgeVersion='',lastMessageAt=0,lastInputAt=0;
  let sequence=0,lastError='',attempts=0,opens=0,closes=0,messages=0,permissionProbeAt=0,permissionProbeResult='';
  let buttons=Array(BUTTON_COUNT).fill(0),axes=Array(AXIS_COUNT).fill(0),lastFingerprint='';
  let synthetic=null;
  const listeners=new Set();

  const clean=v=>String(v??'').trim();
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const supported=()=>typeof window.WebSocket==='function';
  const makeButton=v=>({pressed:Number(v)>=.5,touched:Number(v)>0,value:clamp(Number(v)||0,0,1)});
  const normalizeButtons=input=>Array.from({length:BUTTON_COUNT},(_,i)=>clamp(Number(input?.[i]||0),0,1));
  const normalizeAxes=input=>Array.from({length:AXIS_COUNT},(_,i)=>clamp(Number(input?.[i]||0),-1,1));
  const fingerprint=(b,a)=>`${b.map(v=>v>=.5?1:Math.round(v*100)/100).join(',')}|${a.map(v=>Math.abs(v)<.015?0:Math.round(v*100)/100).join(',')}`;

  function buildSynthetic(){
    if(!transportConnected||!controllerConnected){synthetic=null;return null;}
    synthetic={
      id:`${controllerId||'Windows Controller'} • SBB Native Bridge (${controllerSource||'Windows'})`,
      index:-544,connected:true,mapping:'standard',timestamp:performance?.now?.()||Date.now(),
      buttons:buttons.map(makeButton),axes:[...axes],vibrationActuator:null,hapticActuators:[]
    };
    return synthetic;
  }
  function gamepad(){return buildSynthetic();}
  function stateLabel(){
    if(!supported())return 'Native bridge transport unavailable';
    if(lastError&&!transportConnected)return `Bridge offline • ${lastError}`;
    if(!transportConnected)return 'Windows bridge not running';
    if(!controllerConnected)return 'Windows bridge connected • waiting for controller';
    if(live)return `Native live • ${controllerId||'Windows controller'} • ${controllerSource||'Windows'}`;
    return `Native ready • ${controllerId||'Windows controller'} • ${controllerSource||'Windows'}`;
  }
  function snapshot(){return {
    version:VERSION,protocol:PROTOCOL,supported:supported(),transportConnected,controllerConnected,live,
    controllerId,controllerSource,bridgeVersion,endpoint:socket?.url||ENDPOINTS[endpointIndex]||'',
    lastMessageAt,lastInputAt,sequence,lastError,attempts,opens,closes,messages,permissionProbeAt,permissionProbeResult,state:stateLabel()
  };}
  function notify(reason='state'){
    buildSynthetic();const detail={...snapshot(),reason};
    try{document.dispatchEvent(new CustomEvent('sbb:controller-native-bridge-change',{detail}));}catch(_){}
    for(const fn of listeners){try{fn(detail);}catch(_){}}
    updateSettings();
  }
  function clearController(){controllerConnected=false;live=false;controllerId='';controllerSource='';buttons=Array(BUTTON_COUNT).fill(0);axes=Array(AXIS_COUNT).fill(0);lastFingerprint='';synthetic=null;}
  function resetTransport(reason='closed'){
    transportConnected=false;clearController();notify(reason);
  }
  function scheduleReconnect({fast=false}={}){
    if(reconnectTimer||!supported())return;
    const delay=fast?180:reconnectDelay;
    reconnectTimer=setTimeout(()=>{reconnectTimer=0;connect();},delay);
    reconnectDelay=Math.min(RECONNECT_MAX,Math.round(reconnectDelay*1.45));
  }
  function closeSocket(){
    if(reconnectTimer){clearTimeout(reconnectTimer);reconnectTimer=0;}
    const ws=socket;socket=null;
    if(ws){try{ws.onopen=ws.onmessage=ws.onerror=ws.onclose=null;ws.close();}catch(_){}}
    resetTransport('manual-close');
  }
  function handlePayload(payload){
    if(!payload||typeof payload!=='object')return;
    if(Number(payload.protocol||PROTOCOL)!==PROTOCOL)return;
    lastMessageAt=Date.now();messages++;
    if(payload.type==='hello'){
      bridgeVersion=clean(payload.bridgeVersion||payload.version);lastError='';notify('hello');return;
    }
    if(payload.type!=='state'&&payload.type!=='status')return;
    if(payload.bridgeVersion)bridgeVersion=clean(payload.bridgeVersion);
    sequence=Number(payload.sequence||sequence||0);
    const wasController=controllerConnected;
    controllerConnected=!!payload.connected;
    controllerId=clean(payload.id||payload.controllerId||controllerId||'Windows Controller');
    controllerSource=clean(payload.source||controllerSource||'Windows');
    if(!controllerConnected){clearController();notify(wasController?'controller-disconnected':'status');return;}
    const nextButtons=normalizeButtons(payload.buttons),nextAxes=normalizeAxes(payload.axes);
    const nextFingerprint=fingerprint(nextButtons,nextAxes);
    const changed=nextFingerprint!==lastFingerprint;
    buttons=nextButtons;axes=nextAxes;lastFingerprint=nextFingerprint;
    if(changed){lastInputAt=Date.now();live=true;}
    if(live&&Date.now()-lastInputAt>STALE_MS)live=false;
    buildSynthetic();notify(changed?'input':'state');
  }

  async function probeLoopbackPermission(){
    permissionProbeAt=Date.now();permissionProbeResult='checking';notify('loopback-permission-check');
    try{
      const init={method:'GET',mode:'cors',cache:'no-store'};
      try{init.targetAddressSpace='loopback';}catch(_){}
      const response=await fetch('http://127.0.0.1:5410/health',init);
      permissionProbeResult=response.ok?'granted':'http-'+response.status;
      notify('loopback-permission-result');return response.ok;
    }catch(err){permissionProbeResult=`blocked: ${clean(err?.message||err)}`;notify('loopback-permission-error');return false;}
  }

  function connect({force=false}={}){
    if(!supported()){lastError='WebSocket unavailable';notify('unsupported');return false;}
    if(force){if(reconnectTimer){clearTimeout(reconnectTimer);reconnectTimer=0;}try{socket?.close?.();}catch(_){}socket=null;transportConnected=false;}
    if(socket&&(socket.readyState===WebSocket.OPEN||socket.readyState===WebSocket.CONNECTING))return true;
    attempts++;lastError='';const endpoint=ENDPOINTS[endpointIndex%ENDPOINTS.length];
    let ws;try{ws=new WebSocket(endpoint);}catch(err){lastError=clean(err?.message||err);endpointIndex=(endpointIndex+1)%ENDPOINTS.length;scheduleReconnect();notify('connect-error');return false;}
    socket=ws;
    ws.onopen=()=>{
      if(socket!==ws)return;transportConnected=true;opens++;reconnectDelay=RECONNECT_MIN;lastError='';notify('open');
    };
    ws.onmessage=event=>{
      if(socket!==ws)return;try{handlePayload(JSON.parse(String(event.data||'')));}catch(err){lastError=`Bad bridge message: ${clean(err?.message||err)}`;notify('message-error');}
    };
    ws.onerror=()=>{if(socket!==ws)return;lastError='Cannot reach local Windows bridge';notify('socket-error');};
    ws.onclose=()=>{
      if(socket!==ws)return;socket=null;closes++;transportConnected=false;clearController();endpointIndex=(endpointIndex+1)%ENDPOINTS.length;notify('close');scheduleReconnect();
    };
    return true;
  }
  async function reconnect(){await probeLoopbackPermission();return connect({force:true});}
  function subscribe(fn){if(typeof fn!=='function')return()=>{};listeners.add(fn);return()=>listeners.delete(fn);}
  function updateSettings(){
    const status=document.getElementById('controllerNativeBridgeStatus');if(status)status.textContent=stateLabel();
    const btn=document.getElementById('controllerNativeReconnectBtn');if(btn){btn.disabled=false;btn.textContent=transportConnected?'RECHECK BRIDGE':'RECONNECT BRIDGE';}
  }
  function bindSettings(){
    const btn=document.getElementById('controllerNativeReconnectBtn');if(btn&&!btn.dataset.bound){btn.dataset.bound='1';btn.addEventListener('click',()=>reconnect());}
    updateSettings();
  }
  function onVisibility(){if(document.visibilityState==='visible'&&!transportConnected)connect();}
  function init(){
    bindSettings();document.addEventListener('visibilitychange',onVisibility);window.addEventListener('focus',()=>{if(!transportConnected)connect();});
    connect();notify('init');
  }

  window.SBB_CONTROLLER_NATIVE_BRIDGE=Object.freeze({
    version:VERSION,installed:true,protocol:PROTOCOL,supported,gamepad,connect,reconnect,probeLoopbackPermission,close:closeSocket,snapshot,subscribe,
    get transportConnected(){return transportConnected;},get controllerConnected(){return controllerConnected;},get live(){return live;}
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();

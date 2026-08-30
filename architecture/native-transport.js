/* Sports Big Board v4.7.13 — Native Transport Snapshot.
   Capture browser fetch before Request Broker replaces window.fetch.
   This is intentionally narrow: certification diagnostics may use it directly;
   normal Sports Big Board traffic continues through Request Broker.
*/
(() => {
  'use strict';
  if(window.SBB_NATIVE_TRANSPORT?.version==='4.7.13')return;
  const capturedFetch=typeof window.fetch==='function'?window.fetch.bind(window):null;
  const url=path=>window.SBB_API?.url?window.SBB_API.url(path):path;
  window.SBB_NATIVE_TRANSPORT=Object.freeze({
    version:'4.7.13',
    fetch:capturedFetch,
    url,
    available:()=>typeof capturedFetch==='function'
  });
})();

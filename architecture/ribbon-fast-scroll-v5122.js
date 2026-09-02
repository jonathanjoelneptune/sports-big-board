/* Sports Big Board v5.2.1 — native score-ribbon scroll compatibility bridge.

   v5.1.22 intercepted wheel/pointer events and wrote scrollLeft from JavaScript.
   That helped the old full-DOM ribbon, but it competes with v5.2 virtualization and
   can stall the main thread during long wheel gestures. v5.2.1 deliberately returns
   scrolling to the browser compositor. This filename remains as an inert compatibility
   bridge so older index/service-worker caches cannot resurrect a second scroll owner.
*/
(() => {
  'use strict';
  const VERSION='5.2.1-native-scroll';
  const state={installed:false,native:true,destroyed:true};
  function install(){return false;}
  function destroy(){return true;}
  function refreshMetrics(){return true;}
  window.SBB_RIBBON_FAST_SCROLL=Object.freeze({
    version:VERSION,install,destroy,refreshMetrics,
    snapshot:()=>({...state})
  });
})();

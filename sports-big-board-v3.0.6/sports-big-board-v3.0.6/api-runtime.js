/* v3.0.6 API-origin bridge.
   Lets the static frontend live on GitHub Pages while every /api request is
   routed to the persistent Sports Big Board cloud backend. */
(() => {
  const config = window.SBB_CONFIG || {};
  const base = String(config.apiBase || '').trim().replace(/\/+$/, '');
  const originalFetch = window.fetch.bind(window);
  function apiUrl(input){
    if(!base) return input;
    if(typeof input === 'string' && input.startsWith('/api/')) return base + input;
    if(input instanceof URL && input.pathname.startsWith('/api/') && input.origin === location.origin){
      return new URL(input.pathname + input.search + input.hash, base).toString();
    }
    return input;
  }
  window.SBB_API = Object.freeze({
    version: '1.0',
    base,
    deployment: String(config.deployment || (base ? 'remote' : 'local')),
    url: apiUrl,
    remote: !!base
  });
  window.fetch = function(input, init){ return originalFetch(apiUrl(input), init); };
})();

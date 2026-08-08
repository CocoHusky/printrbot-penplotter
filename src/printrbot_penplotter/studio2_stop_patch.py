"""Studio 2 UI patch for cancelling an in-flight browser render request.

The Stop button is always visible beside Generate/Save. It aborts the active
/api/studio2/render fetch immediately, returns the UI to an idle state, and
prevents stale results from replacing the current preview after the user stops.
"""
from __future__ import annotations

from fastapi.responses import HTMLResponse


def apply_stop_button(router) -> None:
    """Wrap the Studio GET endpoint so its HTML includes a persistent Stop button."""
    for route in router.routes:
        if getattr(route, "path", None) != "/studio2" or "GET" not in getattr(route, "methods", set()):
            continue
        original = route.endpoint

        async def endpoint(*args, __original=original, **kwargs):
            result = __original(*args, **kwargs)
            if hasattr(result, "__await__"):
                result = await result
            html = result.body.decode("utf-8") if isinstance(result, HTMLResponse) else str(result)
            marker = "studio2StopRender"
            if marker in html:
                return HTMLResponse(html)

            # Add Stop beside the existing persistent action controls.
            html = html.replace(
                '<button id="floatingGenerate" class="primary" type="button">Generate drawing</button>',
                '<button id="floatingGenerate" class="primary" type="button">Generate drawing</button>'
                '<button id="studio2StopRender" type="button" disabled '
                'style="background:#fff0f0;color:#9b0000;border-color:#d88">Stop</button>',
            )

            script = r'''
<script>
(()=>{
  const stop=document.getElementById('studio2StopRender');
  const floatingGenerate=document.getElementById('floatingGenerate');
  const mainGenerate=document.getElementById('generate');
  const status=document.getElementById('status');
  if(!stop)return;

  const priorFetch=window.fetch.bind(window);
  let controller=null;
  let stopped=false;

  window.fetch=async(...args)=>{
    const target=String(args[0]&&args[0].url?args[0].url:args[0]);
    if(!target.includes('/api/studio2/render')) return priorFetch(...args);

    if(controller) controller.abort();
    controller=new AbortController();
    stopped=false;
    stop.disabled=false;
    if(floatingGenerate) floatingGenerate.disabled=true;

    const options={...(args[1]||{}),signal:controller.signal};
    try{
      return await priorFetch(args[0],options);
    }catch(err){
      if(stopped || (err && err.name==='AbortError')){
        const abortError=new DOMException('Render stopped by user.','AbortError');
        throw abortError;
      }
      throw err;
    }finally{
      controller=null;
      setTimeout(()=>{
        stop.disabled=true;
        if(mainGenerate) mainGenerate.disabled=false;
        if(floatingGenerate) floatingGenerate.disabled=false;
        if(stopped && status){
          status.className='status';
          status.textContent='Stopped. Adjust settings and Generate again.';
        }
      },0);
    }
  };

  stop.addEventListener('click',()=>{
    if(!controller)return;
    stopped=true;
    stop.disabled=true;
    stop.textContent='Stopping…';
    controller.abort();
    window.__studioLast=null;
    const saveSvg=document.getElementById('saveSvg');
    const saveGcode=document.getElementById('saveGcode');
    if(saveSvg) saveSvg.disabled=true;
    if(saveGcode) saveGcode.disabled=true;
    if(status){
      status.className='status';
      status.textContent='Stopping current render…';
    }
    setTimeout(()=>{stop.textContent='Stop';},250);
  });
})();
</script>
'''
            html = html.replace("</body></html>", script + "</body></html>")
            return HTMLResponse(html)

        route.endpoint = endpoint
        return

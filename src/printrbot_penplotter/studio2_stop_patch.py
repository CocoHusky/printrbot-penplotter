"""Studio 2 UI patch for cancelling an in-flight browser render request.

The Stop button is always visible beside Generate/Save. It aborts the active
/api/studio2/render fetch immediately, returns the UI to an idle state, and
prevents stale results from replacing the current preview after the user stops.
"""
from __future__ import annotations

from fastapi.responses import HTMLResponse
from starlette.routing import request_response


def apply_stop_button(router) -> None:
    """Wrap the Studio GET endpoint so its HTML includes a persistent Stop button.

    FastAPI's APIRoute builds its ASGI ``app`` when the route is created. Merely
    assigning ``route.endpoint`` later does not change what is actually served.
    After replacing the endpoint we therefore rebuild ``route.app`` from the new
    handler. This is why the first version of the Stop patch existed in the repo
    but never appeared in the browser.
    """
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
    stop.textContent='Stop';
    if(floatingGenerate) floatingGenerate.disabled=true;

    const options={...(args[1]||{}),signal:controller.signal};
    try{
      return await priorFetch(args[0],options);
    }catch(err){
      if(stopped || (err && err.name==='AbortError')){
        throw new DOMException('Render stopped by user.','AbortError');
      }
      throw err;
    }finally{
      controller=null;
      setTimeout(()=>{
        stop.disabled=true;
        stop.textContent='Stop';
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
  });
})();
</script>
'''
            html = html.replace("</body></html>", script + "</body></html>")
            return HTMLResponse(html)

        route.endpoint = endpoint
        # Critical: APIRoute cached the old endpoint in its ASGI app when the
        # route was created. Rebuild it so requests actually execute the wrapper.
        route.app = request_response(route.get_route_handler())
        return

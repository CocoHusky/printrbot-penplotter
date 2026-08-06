"""Local web interface for text preview, G-code generation, and guarded plotting."""

from __future__ import annotations

import os
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .models import PageConfig, PenConfig, StyleConfig
from .pipeline import render_text_job
from .sender import MarlinSender

app = FastAPI(title="Printrbot Pen Plotter", version="0.1.0")


class RenderRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    preset: Literal["clean", "human", "cursive", "robot"] = "human"
    font_family: str = "DejaVu Sans"
    font_path: str | None = None
    seed: int = 7
    font_size_mm: float = Field(default=18.0, gt=1, le=100)
    z_up_mm: float = 5.0
    z_down_mm: float = 0.0


class PlotRequest(RenderRequest):
    confirmation: str


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Printrbot Pen Plotter</title>
<style>
:root { font-family: system-ui, sans-serif; color-scheme: dark; }
body { margin:0; background:#0b1017; color:#eef3f8; }
main { width:min(1100px,calc(100% - 28px)); margin:24px auto; }
h1 { margin-bottom:4px; } p { color:#aebdca; }
.grid { display:grid; grid-template-columns:minmax(280px,360px) 1fr; gap:16px; }
.card { background:#131b25; border:1px solid #263545; border-radius:16px; padding:16px; }
label { display:block; margin:12px 0 5px; color:#c7d3dd; }
textarea,input,select,button { width:100%; box-sizing:border-box; border-radius:10px; border:1px solid #34475b; padding:10px; font:inherit; }
textarea,input,select { background:#0c131b; color:#eef3f8; }
textarea { min-height:190px; resize:vertical; }
button { margin-top:12px; background:#2b74ad; color:white; font-weight:700; cursor:pointer; }
button.secondary { background:#304052; }
#preview { background:white; min-height:520px; display:grid; place-items:center; overflow:auto; }
#preview svg { width:100%; height:auto; max-height:75vh; }
pre { white-space:pre-wrap; max-height:220px; overflow:auto; color:#9ed1ff; }
.status { min-height:24px; color:#77e2a7; }
@media(max-width:800px){ .grid{grid-template-columns:1fr;} #preview{min-height:350px;} }
</style>
</head>
<body><main>
<h1>Printrbot Pen Plotter</h1>
<p>Type, vary, preview, export, then send the exact same geometry to Marlin.</p>
<div class="grid">
<section class="card">
<label for="text">Text</label>
<textarea id="text">Hello from Printrbot</textarea>
<label for="preset">Style</label>
<select id="preset"><option>human</option><option>clean</option><option>cursive</option><option>robot</option></select>
<label for="font">Font family</label><input id="font" value="DejaVu Sans">
<label for="seed">Variation seed</label><input id="seed" type="number" value="7">
<label for="size">Font size (mm before page fitting)</label><input id="size" type="number" value="18" min="2" max="100">
<button onclick="renderJob()">Render preview</button>
<button class="secondary" onclick="downloadGcode()">Download G-code</button>
<div class="status" id="status"></div>
<pre id="meta"></pre>
</section>
<section class="card" id="preview">Preview will appear here.</section>
</div>
<script>
let latestGcode = "";
function payload(){ return {text:text.value,preset:preset.value,font_family:font.value,seed:Number(seed.value),font_size_mm:Number(size.value),z_up_mm:5,z_down_mm:0}; }
async function renderJob(){
 status.textContent='Rendering…';
 const response=await fetch('/api/render',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload())});
 const data=await response.json();
 if(!response.ok){status.textContent=data.detail||'Render failed';return;}
 preview.innerHTML=data.preview_svg;
 latestGcode=data.gcode;
 meta.textContent=JSON.stringify(data.metadata,null,2);
 status.textContent='Ready: preview and G-code use the same paths.';
}
function downloadGcode(){
 if(!latestGcode){status.textContent='Render first.';return;}
 const blob=new Blob([latestGcode],{type:'text/plain'});
 const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download='plot.gcode'; link.click(); URL.revokeObjectURL(link.href);
}
renderJob();
</script>
</main></body></html>"""


def _render(request: RenderRequest):
    style = StyleConfig.for_preset(
        request.preset,
        font_family=request.font_family,
        font_path=request.font_path,
        font_size_mm=request.font_size_mm,
        seed=request.seed,
    )
    return render_text_job(
        request.text,
        page=PageConfig(),
        pen=PenConfig(z_up_mm=request.z_up_mm, z_down_mm=request.z_down_mm),
        style=style,
    )


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.post("/api/render")
def render(request: RenderRequest) -> dict[str, object]:
    try:
        job = _render(request)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "preview_svg": job.preview_svg,
        "gcode": job.gcode,
        "metadata": job.metadata,
    }


@app.post("/api/plot")
def plot(request: PlotRequest) -> dict[str, object]:
    if os.getenv("PLOTTER_ALLOW_HARDWARE") != "1":
        raise HTTPException(
            status_code=403,
            detail="Hardware plotting is disabled. Set PLOTTER_ALLOW_HARDWARE=1 after calibration.",
        )
    if request.confirmation != "DRAW":
        raise HTTPException(status_code=400, detail="confirmation must be DRAW")

    port = os.getenv("PLOTTER_SERIAL_PORT")
    if not port:
        raise HTTPException(status_code=500, detail="PLOTTER_SERIAL_PORT is not configured.")

    job = _render(request)
    try:
        with MarlinSender(port) as sender:
            commands = sender.send_gcode(job.gcode)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "commands_sent": commands, "metadata": job.metadata}

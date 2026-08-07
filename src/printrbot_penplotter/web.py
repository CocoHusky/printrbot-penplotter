"""Local web interface for physical-size preview and guarded plotting."""

from __future__ import annotations

import os
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .models import LayoutConfig, MachineConfig, PageConfig, PenConfig, StyleConfig
from .pipeline import render_calibration_job, render_text_job
from .sender import MarlinSender

app = FastAPI(title="Printrbot Pen Plotter", version="0.2.0")


class RenderRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    preset: Literal["clean", "human", "cursive", "robot"] = "human"
    font_family: str = "DejaVu Sans"
    font_path: str | None = None
    seed: int = 7
    font_size_mm: float = Field(default=18.0, gt=1, le=100)
    page_width_mm: float = Field(default=152.4, gt=1, le=1000)
    page_height_mm: float = Field(default=152.4, gt=1, le=1000)
    page_origin_x_mm: float = 0.0
    page_origin_y_mm: float = 0.0
    margin_mm: float = Field(default=8.0, ge=0, le=100)
    fit_mode: Literal["none", "downscale", "fit"] = "downscale"
    horizontal_align: Literal["left", "center", "right"] = "center"
    vertical_align: Literal["bottom", "center", "top"] = "center"
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    scale: float = Field(default=1.0, gt=0, le=20)
    z_up_mm: float = 5.0
    z_down_mm: float = 0.0
    air_plot: bool = False


class CalibrationRequest(BaseModel):
    size_mm: float = Field(default=10.0, gt=0, le=100)
    air_plot: bool = True


class PlotRequest(RenderRequest):
    confirmation: str


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Printrbot Pen Plotter 0.2</title>
<style>
:root { font-family: system-ui, sans-serif; color-scheme: dark; }
body { margin:0; background:#0b1017; color:#eef3f8; }
main { width:min(1180px,calc(100% - 28px)); margin:24px auto; }
h1 { margin-bottom:4px; } p { color:#aebdca; }
.grid { display:grid; grid-template-columns:minmax(300px,390px) 1fr; gap:16px; }
.card { background:#131b25; border:1px solid #263545; border-radius:16px; padding:16px; }
.row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
label { display:block; margin:12px 0 5px; color:#c7d3dd; }
textarea,input,select,button { width:100%; box-sizing:border-box; border-radius:10px; border:1px solid #34475b; padding:10px; font:inherit; }
textarea,input,select { background:#0c131b; color:#eef3f8; }
textarea { min-height:150px; resize:vertical; }
button { margin-top:12px; background:#2b74ad; color:white; font-weight:700; cursor:pointer; }
button.secondary { background:#304052; }
button.safe { background:#276847; }
#preview { background:#dce4eb; min-height:540px; display:grid; place-items:center; overflow:auto; }
#preview svg { width:100%; height:auto; max-height:78vh; }
pre { white-space:pre-wrap; max-height:220px; overflow:auto; color:#9ed1ff; }
.status { min-height:24px; color:#77e2a7; margin-top:10px; }
.check { display:flex; align-items:center; gap:8px; margin-top:12px; }
.check input { width:auto; }
@media(max-width:820px){ .grid{grid-template-columns:1fr;} #preview{min-height:350px;} }
</style>
</head>
<body><main>
<h1>Printrbot Pen Plotter 0.2</h1>
<p>Physical-size layout, machine-space preview, dashed pen-up travel, and air-plot calibration.</p>
<div class="grid">
<section class="card">
<label for="text">Text</label>
<textarea id="text">Hello from Printrbot</textarea>
<div class="row">
  <div><label for="preset">Style</label><select id="preset"><option>human</option><option>clean</option><option>cursive</option><option>robot</option></select></div>
  <div><label for="fontSize">Font size (mm)</label><input id="fontSize" type="number" value="18" min="2" max="100"></div>
</div>
<div class="row">
  <div><label for="font">Font family</label><input id="font" value="DejaVu Sans"></div>
  <div><label for="seed">Variation seed</label><input id="seed" type="number" value="7"></div>
</div>
<div class="row">
  <div><label for="fitMode">Fit behavior</label><select id="fitMode"><option value="downscale">Preserve size; shrink only</option><option value="none">Exact size or error</option><option value="fit">Fill page</option></select></div>
  <div><label for="align">Horizontal alignment</label><select id="align"><option>center</option><option>left</option><option>right</option></select></div>
</div>
<div class="row">
  <div><label for="pageWidth">Page width (mm)</label><input id="pageWidth" type="number" value="152.4"></div>
  <div><label for="pageHeight">Page height (mm)</label><input id="pageHeight" type="number" value="152.4"></div>
</div>
<div class="row">
  <div><label for="originX">Page origin X (mm)</label><input id="originX" type="number" value="0"></div>
  <div><label for="originY">Page origin Y (mm)</label><input id="originY" type="number" value="0"></div>
</div>
<div class="check"><input id="airPlot" type="checkbox"><label for="airPlot" style="margin:0">Generate air plot (never lower pen)</label></div>
<button onclick="renderJob()">Render physical preview</button>
<button class="safe" onclick="renderCalibration()">Generate 10 mm air calibration</button>
<button class="secondary" onclick="downloadGcode()">Download G-code</button>
<div class="status" id="status"></div>
<pre id="meta"></pre>
</section>
<section class="card" id="preview">Preview will appear here.</section>
</div>
<script>
let latestGcode = "";
const byId = id => document.getElementById(id);
function payload(){ return {
 text:byId('text').value,
 preset:byId('preset').value,
 font_family:byId('font').value,
 seed:Number(byId('seed').value),
 font_size_mm:Number(byId('fontSize').value),
 page_width_mm:Number(byId('pageWidth').value),
 page_height_mm:Number(byId('pageHeight').value),
 page_origin_x_mm:Number(byId('originX').value),
 page_origin_y_mm:Number(byId('originY').value),
 margin_mm:8,
 fit_mode:byId('fitMode').value,
 horizontal_align:byId('align').value,
 vertical_align:'center', offset_x_mm:0, offset_y_mm:0, scale:1,
 z_up_mm:5, z_down_mm:0, air_plot:byId('airPlot').checked
}; }
async function postJson(url, body){
 const response=await fetch(url,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
 const data=await response.json();
 if(!response.ok) throw new Error(data.detail||'Request failed');
 return data;
}
function showJob(data){
 byId('preview').innerHTML=data.preview_svg;
 latestGcode=data.gcode;
 byId('meta').textContent=JSON.stringify(data.metadata,null,2);
 byId('status').textContent='Ready: preview and G-code use the same machine-space paths.';
}
async function renderJob(){
 byId('status').textContent='Rendering…';
 try { showJob(await postJson('/api/render',payload())); }
 catch(error){ byId('status').textContent=error.message; }
}
async function renderCalibration(){
 byId('status').textContent='Generating safe calibration…';
 try { showJob(await postJson('/api/calibration',{size_mm:10,air_plot:true})); }
 catch(error){ byId('status').textContent=error.message; }
}
function downloadGcode(){
 if(!latestGcode){byId('status').textContent='Render first.';return;}
 const blob=new Blob([latestGcode],{type:'text/plain'});
 const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download='plot.gcode'; link.click(); URL.revokeObjectURL(link.href);
}
renderJob();
</script>
</main></body></html>"""


def _machine() -> MachineConfig:
    return MachineConfig()


def _render(request: RenderRequest):
    machine = _machine()
    page = PageConfig(
        width_mm=request.page_width_mm,
        height_mm=request.page_height_mm,
        margin_mm=request.margin_mm,
        origin_x_mm=request.page_origin_x_mm,
        origin_y_mm=request.page_origin_y_mm,
    )
    layout = LayoutConfig(
        fit_mode=request.fit_mode,
        horizontal_align=request.horizontal_align,
        vertical_align=request.vertical_align,
        scale=request.scale,
        offset_x_mm=request.offset_x_mm,
        offset_y_mm=request.offset_y_mm,
    )
    style = StyleConfig.for_preset(
        request.preset,
        font_family=request.font_family,
        font_path=request.font_path,
        font_size_mm=request.font_size_mm,
        seed=request.seed,
    )
    return render_text_job(
        request.text,
        page=page,
        machine=machine,
        pen=PenConfig(
            z_up_mm=request.z_up_mm,
            z_down_mm=request.z_down_mm,
            air_plot=request.air_plot,
        ),
        style=style,
        layout=layout,
    )


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.post("/api/render")
def render(request: RenderRequest) -> dict[str, object]:
    try:
        job = _render(request)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"preview_svg": job.preview_svg, "gcode": job.gcode, "metadata": job.metadata}


@app.post("/api/calibration")
def calibration(request: CalibrationRequest) -> dict[str, object]:
    try:
        job = render_calibration_job(
            size_mm=request.size_mm,
            machine=_machine(),
            pen=PenConfig(air_plot=request.air_plot),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"preview_svg": job.preview_svg, "gcode": job.gcode, "metadata": job.metadata}


@app.post("/api/plot")
def plot(request: PlotRequest) -> dict[str, object]:
    if os.getenv("PLOTTER_ALLOW_HARDWARE") != "1":
        raise HTTPException(
            status_code=403,
            detail="Hardware plotting is disabled. Complete preflight and calibration first.",
        )
    if request.confirmation != "DRAW":
        raise HTTPException(status_code=400, detail="confirmation must be DRAW")

    port = os.getenv("PLOTTER_SERIAL_PORT")
    if not port:
        raise HTTPException(status_code=500, detail="PLOTTER_SERIAL_PORT is not configured.")

    job = _render(request)
    try:
        with MarlinSender(port) as sender:
            commands = sender.send_gcode(job.gcode, safe_z_up_mm=request.z_up_mm)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "commands_sent": commands, "metadata": job.metadata}

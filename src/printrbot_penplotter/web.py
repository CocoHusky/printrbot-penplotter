"""Local web interface for writing preview and guarded plotting."""

from __future__ import annotations

import os
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .models import LayoutConfig, MachineConfig, PageConfig, PenConfig, StyleConfig
from .pipeline import render_calibration_job, render_text_job
from .sender import MarlinSender
from .stroke_fonts import available_stroke_fonts, get_builtin_stroke_font
from .ui_theme import LAB_THEME_CSS

app = FastAPI(title="Printrbot Pen Plotter", version="0.3.0")


class RenderRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    preset: Literal["standard", "clean", "human", "cursive", "robot"] = "human"
    engine: Literal["stroke", "outline"] = "stroke"  # outline is legacy API input only
    writing_backend: Literal["stroke", "neural"] = "stroke"
    neural_style: int = Field(default=9, ge=0, le=12)
    neural_bias: float = Field(default=0.75, ge=0, le=1)
    font_family: str = "DejaVu Sans"
    font_path: str | None = None
    stroke_font: str = "hand"
    stroke_font_path: str | None = None
    seed: int = 7
    font_size_mm: float = Field(default=18.0, gt=1, le=100)
    wrap_width_mm: float | None = Field(default=None, gt=0, le=1000)
    connect_letters: bool = False
    word_spacing_em: float = Field(default=0.42, gt=0, le=4)
    letter_spacing_mm: float = Field(default=0.55, ge=-10, le=20)
    variant_mode: Literal["first", "seeded", "cycle"] = "seeded"
    stroke_order: Literal["authored", "nearest"] = "authored"
    slant_deg: float = Field(default=3.0, ge=-45, le=45)
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
<title>Printrbot Pen Plotter 0.3</title>
<style>
:root { font-family: system-ui, sans-serif; color-scheme: light; }
body { margin:0; background:#f5f2ec; color:#20211f; }
main { width:min(1240px,calc(100% - 28px)); margin:24px auto; }
h1 { margin-bottom:4px; letter-spacing:-.03em; } p { color:#66706d; }
.app-tabs { display:flex; gap:6px; margin:0 0 20px; padding:5px; background:#e8e4dc; border-radius:12px; width:max-content; }
.app-tabs a { color:#59615d; text-decoration:none; padding:9px 15px; border-radius:8px; font-weight:700; font-size:13px; }
.app-tabs a:hover { background:#f8f6f1; color:#20211f; }
.app-tabs a.active { background:#20211f; color:#fff; }
.grid { display:grid; grid-template-columns:minmax(320px,430px) 1fr; gap:16px; }
.card { background:#fffdf9; border:1px solid #d9d4ca; border-radius:16px; padding:16px; box-shadow:0 8px 24px rgba(56,48,35,.06); }
.row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
label { display:block; margin:12px 0 5px; color:#414844; }
textarea,input,select,button { width:100%; box-sizing:border-box; border-radius:10px; border:1px solid #c9c5bc; padding:10px; font:inherit; }
textarea,input,select { background:#fff; color:#20211f; }
textarea { min-height:142px; resize:vertical; }
button { margin-top:12px; background:#2d6155; color:white; font-weight:700; cursor:pointer; }
button:disabled { opacity:.48; cursor:not-allowed; }
button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible, a:focus-visible { outline:3px solid #2d6155; outline-offset:2px; }
.lettering-choices { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:6px; }
.lettering-choice { margin:0; text-align:left; background:#0b1721; color:#c7d3dd; border:1px solid #2d6686; min-height:66px; }
.lettering-choice strong { display:block; color:#f0f6fa; }
.lettering-choice small { display:block; margin-top:4px; color:#9ab0c2; }
.lettering-choice.selected { background:#193a4f; border-color:#70cfff; box-shadow:0 0 0 2px rgba(112,207,255,.25); }
#preset { display:none; }
button.secondary { background:#6c756f; }
button.safe { background:#8a5a2b; }
#preview { background:#dce4eb; min-height:580px; display:grid; place-items:center; overflow:auto; }
#preview svg { width:100%; height:auto; max-height:80vh; }
pre { white-space:pre-wrap; max-height:250px; overflow:auto; color:#9ed1ff; }
.status { min-height:24px; color:#2d6155; margin-top:10px; }
.workflow-hint { margin:8px 0 14px; padding:10px 12px; background:#e9f1ed; border-radius:10px; color:#36574d; font-size:13px; }
.check { display:flex; align-items:center; gap:8px; margin-top:12px; }
.check input { width:auto; }
details { margin-top:12px; border-top:1px solid #263545; padding-top:8px; }
summary { cursor:pointer; font-weight:700; color:#c7d3dd; }
@media(max-width:860px){ .grid{grid-template-columns:1fr;} #preview{min-height:350px;} }
</style>
</head>
<body><main>
<nav class="app-tabs" aria-label="Printrbot tools"><a class="active" href="/">Test</a><a href="/studio2">Art</a></nav>
<h1>Write notes for the plotter</h1>
<p>Choose a human writing style, write your note, preview the exact strokes, then move to image or art workflows without leaving the app.</p>
<p class="workflow-hint"><strong>Simple flow:</strong> 1. Write your note → 2. Choose the lettering → 3. Generate the preview → 4. Export G-code.</p>
<div class="grid">
<section class="card workflow-card">
<div class="workflow-step"><div class="step-kicker">STEP 1</div><h2>Write your note</h2>
<label for="text">Text</label>
<textarea id="text">Today I need to remember:</textarea>
</div>
<div class="workflow-step"><div class="step-kicker">STEP 2</div><h2>Choose the lettering</h2>
<div><label>Lettering type</label><select id="preset" aria-hidden="true"><option value="standard">Typed centerline</option><option value="robot">Robot centerline</option><option value="human">Handwritten centerline</option></select><div class="lettering-choices" role="group" aria-label="Lettering type"><button type="button" class="lettering-choice" data-preset="standard"><strong>Typed centerline</strong><small>Single-stroke print lettering</small></button><button type="button" class="lettering-choice" data-preset="robot"><strong>Robot centerline</strong><small>Technical single-line strokes</small></button><button type="button" class="lettering-choice" data-preset="human"><strong>Handwritten centerline</strong><small>Natural pen trajectory</small></button></div><div class="hint" id="languageHint">Every mode draws centerlines only. Filled typefaces and unsupported characters are not silently converted.</div></div>
<div class="row">
  <div><label for="fontSize">Text size</label><select id="fontSize"><option value="6">Small · 6 mm</option><option value="9">Medium · 9 mm</option><option value="12">Large · 12 mm</option><option value="18" selected>Extra large · 18 mm</option><option value="24">Poster · 24 mm</option></select></div>
</div>
<div class="row">
  <div id="typefaceField"><label for="font">Centerline alphabet</label><select id="font"><option value="robot">Robot single-line</option><option value="hand">Hand single-line</option></select></div>
</div>
<div id="handwritingSummary" class="hint">Handwriting uses the model-based trajectory when it is installed.</div>
<details id="handwritingControls"><summary>Handwriting adjustments</summary><div class="row"><div><label for="neuralStyle">Handwriting style</label><input id="neuralStyle" type="number" value="9" min="0" max="12"></div><div><label for="neuralBias">Neatness (0–1)</label><input id="neuralBias" type="number" value="0.85" min="0" max="1" step="0.05"></div></div><div class="row"><div><label for="seed">Variation seed</label><input id="seed" type="number" value="7"></div><div><label for="slant">Slant (degrees)</label><input id="slant" type="number" value="3" min="-45" max="45"></div></div><div class="row"><div><label for="letterSpacing">Letter spacing (mm)</label><input id="letterSpacing" type="number" value="0.55" step="0.05"></div><div><label for="wordSpacing">Word spacing (em)</label><input id="wordSpacing" type="number" value="0.42" step="0.02"></div></div></details>
<details><summary>Layout</summary><div><label for="wrapWidth">Wrap width (mm; blank = none)</label><input id="wrapWidth" type="number" placeholder="e.g. 110"></div></details>
</div>
<details>
<summary>Page and machine placement</summary>
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
</details>
<div class="workflow-step"><div class="step-kicker">STEP 3</div><h2>Generate and export</h2>
<div class="check"><input id="airPlot" type="checkbox"><label for="airPlot" style="margin:0">Generate air plot (never lower pen)</label></div>
<button id="renderButton" onclick="renderJob()">Render writing preview</button>
<button class="secondary" onclick="saveNote()">Save note locally</button>
<button class="safe" onclick="renderCalibration()">Generate 10 mm air calibration</button>
<button id="downloadButton" class="secondary" onclick="downloadGcode()" disabled>Download G-code</button>
</div>
<div class="status" id="status" role="status" aria-live="polite">Example loaded. Edit your note, then render a new preview.</div>
<pre id="meta"></pre>
</section>
<section class="card" id="preview">Preview will appear here.</section>
</div>
<script>
let latestGcode = "";
let neuralAvailable = false;
let renderTimer = null;
const byId = id => document.getElementById(id);
const noteStorageKey = 'printrbot-note-draft';
function saveNote(){ localStorage.setItem(noteStorageKey,byId('text').value); byId('status').textContent='Note saved locally on this computer.'; }
const savedNote=localStorage.getItem(noteStorageKey); if(savedNote)byId('text').value=savedNote;
byId('text').addEventListener('input',()=>{localStorage.setItem(noteStorageKey,byId('text').value);syncTypefaceForText();byId('status').textContent='Draft saved locally.';});
function optionalNumber(id){ const value=byId(id).value.trim(); return value===''?null:Number(value); }
function hasCjk(text){ return /[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/u.test(text); }
function syncTypefaceForText(){
 byId('languageHint').textContent=hasCjk(byId('text').value)?'CJK detected. A compatible installed font is converted to centerlines; no outline fallback is used.':'Every mode draws centerlines only. Filled typefaces and unsupported characters are not silently converted.';
}
function applyPreset(){
 const value=byId('preset').value;
 if(value==='standard') { byId('font').value='robot'; byId('neuralStyle').value=9; byId('handwritingControls').open=false; }
 else if(value==='robot') { byId('slant').value=0; byId('letterSpacing').value=1.2; byId('handwritingControls').open=false; }
 else { byId('neuralStyle').value=9; byId('slant').value=3; byId('letterSpacing').value=0.55; byId('handwritingControls').open=true; }
 byId('typefaceField').style.display=value==='standard'?'block':'none';
 byId('handwritingSummary').textContent=value==='standard'?'Typed centerline lettering uses the robot single-stroke alphabet.':value==='human'?(neuralAvailable?'Model-based handwriting is active. Adjust neatness, slant, and variation below.':'Model handwriting is unavailable; the built-in hand lettering will be used.'):' ';
 document.querySelectorAll('.lettering-choice').forEach(button=>button.classList.toggle('selected',button.dataset.preset===value));
 syncTypefaceForText();
}
function payload(){ return {
 text:byId('text').value, preset:byId('preset').value, engine:'stroke',
 writing_backend:byId('preset').value==='human'&&neuralAvailable?'neural':'stroke', neural_style:Number(byId('neuralStyle').value), neural_bias:Number(byId('neuralBias').value),
 font_family:hasCjk(byId('text').value)?'Hiragino Sans GB':'DejaVu Sans', font_path:null, stroke_font:byId('preset').value==='standard'?byId('font').value:byId('preset').value==='robot'?'robot':'hand',
 stroke_font_path:null,
 seed:Number(byId('seed').value), font_size_mm:Number(byId('fontSize').value),
 wrap_width_mm:optionalNumber('wrapWidth'), connect_letters:false,
 word_spacing_em:Number(byId('wordSpacing').value), letter_spacing_mm:Number(byId('letterSpacing').value),
 variant_mode:byId('preset').value==='robot'?'first':'seeded', stroke_order:byId('preset').value==='robot'?'nearest':'authored', slant_deg:Number(byId('slant').value),
 page_width_mm:Number(byId('pageWidth').value), page_height_mm:Number(byId('pageHeight').value),
 page_origin_x_mm:Number(byId('originX').value), page_origin_y_mm:Number(byId('originY').value),
 margin_mm:8, fit_mode:byId('fitMode').value, horizontal_align:byId('align').value,
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
 byId('preview').innerHTML=data.preview_svg; latestGcode=data.gcode;
 byId('downloadButton').disabled=!latestGcode;
 byId('meta').textContent=JSON.stringify(data.metadata,null,2);
 byId('status').textContent='Ready: preview and G-code use the same machine-space paths.';
}
async function renderJob(){
 const button=byId('renderButton'); button.disabled=true; byId('downloadButton').disabled=true;
 const started=Date.now();
 const updateStatus=()=>byId('status').textContent='Rendering your note… '+((Date.now()-started)/1000).toFixed(1)+' s';
 updateStatus(); renderTimer=setInterval(updateStatus,250);
 try { showJob(await postJson('/api/render',payload())); }
 catch(error){ latestGcode=''; byId('status').textContent='Could not render this note: '+error.message; }
 finally { clearInterval(renderTimer); renderTimer=null; button.disabled=false; }
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
function syncNeuralState(available){
 neuralAvailable=available;
 applyPreset();
}
fetch('/api/handwriting/status').then(response=>response.json()).then(data=>syncNeuralState(Boolean(data.neural_available))).catch(()=>syncNeuralState(false));
document.querySelectorAll('.lettering-choice').forEach(button=>button.addEventListener('click',()=>{byId('preset').value=button.dataset.preset;applyPreset();}));
applyPreset();
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
        engine=request.engine,
        writing_backend=request.writing_backend,
        neural_style=request.neural_style,
        neural_bias=request.neural_bias,
        font_family=request.font_family,
        font_path=request.font_path,
        stroke_font=request.stroke_font,
        stroke_font_path=request.stroke_font_path,
        font_size_mm=request.font_size_mm,
        seed=request.seed,
        wrap_width_mm=request.wrap_width_mm,
        connect_letters=request.connect_letters,
        word_spacing_em=request.word_spacing_em,
        letter_spacing_mm=request.letter_spacing_mm,
        variant_mode=request.variant_mode,
        stroke_order=request.stroke_order,
        slant_deg=request.slant_deg,
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
    return HTML.replace("</head>", LAB_THEME_CSS + "</head>", 1)


@app.get("/api/fonts")
def fonts() -> dict[str, object]:
    return {
        "fonts": [
            {
                "name": name,
                "description": get_builtin_stroke_font(name).description,
                "glyphs": len(get_builtin_stroke_font(name).glyphs),
            }
            for name in available_stroke_fonts()
        ]
    }


@app.get("/api/handwriting/status")
def handwriting_status() -> dict[str, bool]:
    """Tell the notes UI whether the optional neural worker is configured."""
    worker = os.environ.get("PRINTRBOT_HANDWRITING_WORKER", "").strip()
    available = bool(worker) and (not worker.endswith(".py") or os.path.isfile(worker))
    return {"neural_available": available}


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

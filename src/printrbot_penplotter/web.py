"""Local web interface for writing preview and guarded plotting."""

from __future__ import annotations

import os
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import __version__
from .font_library import font_library_entries
from .models import LayoutConfig, MachineConfig, PageConfig, PenConfig, StyleConfig
from .pipeline import render_calibration_job, render_text_job
from .sender import MarlinSender
from .stroke_fonts import available_stroke_fonts, get_builtin_stroke_font
from .ui_theme import LAB_THEME_CSS

app = FastAPI(title="Printrbot Pen Plotter", version=__version__)


class RenderRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    preset: Literal["standard", "clean", "human", "cursive", "robot"] = "human"
    engine: Literal["stroke"] = "stroke"
    writing_backend: Literal["stroke", "neural"] = "stroke"
    experimental_outline_centerline: bool = False
    neural_style: int = Field(default=9, ge=0, le=12)
    neural_bias: float = Field(default=0.75, ge=0, le=1)
    font_family: str = "DejaVu Sans"
    font_path: str | None = None
    stroke_font: str = "hand"
    stroke_font_path: str | None = None
    seed: int = 7
    # A card-sized character height.  The value is the cap height of each
    # glyph, not the total height of the note.
    font_size_mm: float = Field(default=6.0, ge=1, le=100)
    line_spacing: float = Field(default=1.0, gt=0.1, le=4)
    # Keep long notes on readable lines by default.  The API still accepts
    # null when callers explicitly want an unwrapped single line.
    wrap_width_mm: float | None = Field(default=120.0, gt=0, le=1000)
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
    # The writing UI should always produce a reviewable preview.  Users can
    # change the page and scale afterward; overflow must not block generation.
    fit_mode: Literal["none", "downscale", "fit"] = "downscale"
    horizontal_align: Literal["left", "center", "right"] = "center"
    vertical_align: Literal["bottom", "center", "top"] = "center"
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    scale: float = Field(default=1.0, gt=0, le=20)
    z_up_mm: float = 5.0
    z_down_mm: float = 0.0
    pen_tip_mm: float = Field(default=0.5, gt=0, le=10)
    contact_compensation: bool = True
    home_before_plot: bool = True
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
<title>Printrbot Pen Plotter</title>
<style>
:root { font-family: system-ui, sans-serif; color-scheme: light; }
body { margin:0; background:#f5f2ec; color:#20211f; }
main { width:min(1240px,calc(100% - 28px)); margin:24px auto; }
h1 { margin-bottom:4px; letter-spacing:-.03em; } p { color:#66706d; }
.app-tabs { display:flex; gap:6px; margin:0 0 20px; padding:5px; background:#e8e4dc; border-radius:12px; width:max-content; }
.app-tabs a { color:#59615d; text-decoration:none; padding:9px 15px; border-radius:8px; font-weight:700; font-size:13px; }
.app-tabs a:hover { background:#f8f6f1; color:#20211f; }
.app-tabs a.active { background:#20211f; color:#fff; }
.grid { display:block; }
.card { background:#fffdf9; border:1px solid #d9d4ca; border-radius:16px; padding:16px; box-shadow:0 8px 24px rgba(56,48,35,.06); }
.row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.typed-font-controls { display:none; }
label { display:block; margin:12px 0 5px; color:#414844; }
textarea,input,select,button { width:100%; box-sizing:border-box; border-radius:10px; border:1px solid #c9c5bc; padding:10px; font:inherit; }
textarea,input,select { background:#fff; color:#20211f; }
textarea { min-height:142px; resize:vertical; }
button { margin-top:12px; background:#2d6155; color:white; font-weight:700; cursor:pointer; }
button:disabled { opacity:.48; cursor:not-allowed; }
button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible, a:focus-visible { outline:3px solid #2d6155; outline-offset:2px; }
.workflow-step { margin-top:16px; }
.step-columns { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; align-items:start; }
.generate-panel { min-width:0; }
.compact-row { display:grid; grid-template-columns:minmax(0,1fr) minmax(180px,.7fr); gap:12px; align-items:end; }
.compact-row .control-group { margin-top:10px; padding-top:10px; }
.compact-row label { margin-top:0; }
.compact-row .range-field { grid-template-columns:minmax(0,1fr) 72px; }
.compact-hint { margin:4px 0 0; font-size:12px; }
.settings-panel { margin-top:16px; padding:0 16px 16px; background:#fffdf9; border:1px solid #d9d4ca; border-radius:16px; }
.settings-panel > summary { padding:16px 0 4px; color:#20211f; list-style:none; }
.settings-panel > summary::-webkit-details-marker { display:none; }
.settings-panel > summary strong { display:block; margin-top:4px; font-size:24px; letter-spacing:-.03em; }
.settings-panel > summary::after { content:'Show less'; float:right; color:#66706d; font-size:13px; font-weight:600; margin-top:-28px; }
.settings-panel:not([open]) > summary::after { content:'Show settings'; }
.settings-panel .control-group { margin-top:14px; padding-top:14px; border-top:1px solid #e5e1d8; }
.step-kicker { color:#2d6155; font-size:12px; font-weight:800; letter-spacing:.16em; }
#preview { margin-top:16px; }
button.secondary { background:#6c756f; }
button.safe { background:#8a5a2b; }
#preview { background:#dce4eb; min-height:580px; display:grid; place-items:center; overflow:auto; }
#preview svg { width:100%; height:auto; max-height:80vh; }
.preview-legend { margin:8px 0 0; color:#66706d; font-size:12px; }
pre { white-space:pre-wrap; max-height:250px; overflow:auto; color:#9ed1ff; }
.status { min-height:24px; color:#2d6155; margin-top:10px; }
.workflow-hint { margin:8px 0 14px; padding:10px 12px; background:#e9f1ed; border-radius:10px; color:#36574d; font-size:13px; }
.check { display:flex; align-items:center; gap:8px; margin-top:12px; }
.check input { width:auto; }
.range-field { display:grid; grid-template-columns:minmax(0,1fr) 92px; gap:8px; align-items:end; }
.range-field input[type=range] { grid-column:1/-1; width:100%; padding:0; accent-color:#2d6155; }
.range-field input[type=number] { min-width:0; }
.control-note { margin:5px 0 0; color:#66706d; font-size:12px; }
details { margin-top:12px; border-top:1px solid #263545; padding-top:8px; }
summary { cursor:pointer; font-weight:700; color:#c7d3dd; }
@media(max-width:860px){ #preview{min-height:350px;} .row{grid-template-columns:1fr;} .step-columns{grid-template-columns:1fr;} }
</style>
</head>
<body><main>
<nav class="app-tabs" aria-label="Printrbot tools"><a class="active" href="/">Write</a><a href="/studio2">Art</a></nav>
<h1>Write notes for the plotter</h1>
<p>Choose a human writing style, write your note, preview the exact strokes, then switch to Art without leaving the app.</p>
<p class="workflow-hint"><strong>Simple flow:</strong> 1. Write your note → 2. Choose the lettering → 3. Generate the preview → 4. Export G-code.</p>
<div class="grid">
<section class="card workflow-card">
<div class="workflow-step"><div class="step-kicker">STEP 1</div><h2>Write your note</h2>
<label for="text">Text</label>
<textarea id="text">Today I need to remember:</textarea>
</div>
<div class="step-columns">
<details id="letteringSettings" class="settings-panel" open>
<summary><span class="step-kicker">STEP 2</span><strong>Choose the lettering</strong></summary>
<div><label for="preset">Lettering type</label><select id="preset"><option value="robot">Single-line robot</option><option value="human">Single-line handwriting</option></select><div class="hint" id="languageHint">Only authored stroke fonts are available. Every mark is drawn once; outline fonts are not used.</div></div>
<div id="strokeFontControls"><label for="strokeFont">Stroke font</label><select id="strokeFont"><option value="robot">Robot</option></select><div class="hint">These are vector centerline fonts. The pen traces each stroke once.</div></div>
<details class="control-group" id="experimentalControls"><summary>Experimental: convert outline fonts</summary><div class="check"><input id="experimentalOutline" type="checkbox"><label for="experimentalOutline" style="margin:0">Override with an installed outline font</label></div><p class="control-note">Exposes fonts such as Arial and Courier. This converts their outlines into plot paths; it is experimental and may produce doubled edges or imperfect joins.</p><div id="experimentalFontControls" style="display:none"><label for="font">Installed outline font</label><select id="font"><option value="DejaVu Sans">Loading…</option></select></div></details>
<div class="compact-row">
  <div class="control-group"><label for="fontSize">Size (pt)</label><div class="range-field"><input id="fontSizeRange" type="range" min="4" max="72" step="0.5" value="12" aria-label="Font size slider"><input id="fontSize" type="number" min="4" max="72" step="0.5" value="12" aria-label="Font size in points"></div></div>
</div>
<div id="handwritingSummary" class="hint compact-hint">Uses Hershey Script centerlines: clean single-line strokes designed for a pen plotter.</div>
<details id="handwritingControls" class="control-group"><summary>Experimental neural handwriting</summary><div class="check"><input id="neuralExperimental" type="checkbox"><label for="neuralExperimental" style="margin:0">Use the neural model instead</label></div><p class="control-note">The Graves model is stochastic handwriting generation, not a font. These controls change sampling style and randomness; high bias does not guarantee legibility. The normal mode stays with the cleaner authored centerline script.</p><div class="row"><div><label for="neuralStyle">Model style</label><input id="neuralStyle" type="number" value="9" min="0" max="12"></div><div><label for="neuralBias">Sampling bias (0–1)</label><input id="neuralBias" type="number" value="0.85" min="0" max="1" step="0.05"></div></div><div class="row"><div><label for="seed">Variation seed</label><input id="seed" type="number" value="7"></div><div><label for="slant">Slant (degrees)</label><input id="slant" type="number" value="3" min="-45" max="45"></div></div></details>
<details class="control-group"><summary>Spacing and wrapping</summary><div class="row"><div><label for="wrapMode">Wrap mode</label><select id="wrapMode"><option value="on" selected>Wrap to width</option><option value="off">No wrapping</option></select></div><div><label for="wrapWidth">Wrap width (mm)</label><input id="wrapWidth" type="number" min="1" max="1000" step="1" value="120" placeholder="e.g. 120"></div></div><div class="row"><div><label for="lineSpacing">Line spacing (× character height)</label><div class="range-field"><input id="lineSpacingRange" type="range" min="0.8" max="3" step="0.05" value="1" aria-label="Line spacing slider"><input id="lineSpacing" type="number" min="0.8" max="3" step="0.05" value="1" aria-label="Line spacing multiplier"></div></div><div><label for="letterSpacing">Letter spacing (mm)</label><div class="range-field"><input id="letterSpacingRange" type="range" min="-1" max="10" step="0.05" value="0.55" aria-label="Letter spacing slider"><input id="letterSpacing" type="number" min="-1" max="10" step="0.05" value="0.55" aria-label="Letter spacing in millimeters"></div></div></div><div class="row"><div><label for="wordSpacing">Word spacing (em)</label><div class="range-field"><input id="wordSpacingRange" type="range" min="0.2" max="2" step="0.02" value="0.42" aria-label="Word spacing slider"><input id="wordSpacing" type="number" min="0.2" max="2" step="0.02" value="0.42" aria-label="Word spacing in em"></div></div></div><p class="control-note">Words wrap to the selected physical width. Adjust the width or line spacing for the card.</p></details>
<details class="control-group">
<summary>Page and machine placement</summary>
<div class="row">
  <div><label for="fitMode">Fit behavior</label><select id="fitMode"><option value="none">Exact size or explain overflow</option><option value="downscale" selected>Preserve size; shrink only</option><option value="fit">Fill page</option></select><p class="control-note">Generate first even when the note is larger than the page. Adjust page size, font size, or fit behavior afterward.</p></div>
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
<details class="control-group"><summary>Plot settings</summary><div>
<div class="row"><div><label for="penTip">Pen tip width (mm)</label><input id="penTip" type="number" min="0.1" max="10" step="0.1" value="0.5"></div></div>
<p class="control-note">When ink-contact extension is enabled below, open stroke ends are extended by half this width. Closed loops are unchanged.</p>
<div class="check"><input id="contactCompensation" type="checkbox" checked><label for="contactCompensation" style="margin:0">Extend open stroke ends for pen ink contact</label></div><p class="control-note">Adds half the pen-tip width at the start and end of open strokes. Disable it for exact technical endpoints.</p>
<div class="check"><input id="homeBeforePlot" type="checkbox" checked><label for="homeBeforePlot" style="margin:0">Home before plot and re-home X/Y at the end</label></div>
<p class="control-note">Homing is enabled by default for hardware-safe G-code. The export adds a full G28 before movement, then a safe pen-up, M400, and X/Y re-home at the end. Turn it off only for diagnostic files.</p>
</div></details>
</details>
<div class="generate-panel"><div class="workflow-step"><div class="step-kicker">STEP 3</div><h2>Generate and export</h2>
<button id="renderButton" onclick="renderJob()">Render writing preview</button>
<button class="secondary" onclick="saveNote()">Save note locally</button>
<button id="downloadButton" class="secondary" onclick="downloadGcode()" disabled>Download G-code</button>
</div>
<div class="status" id="status" role="status" aria-live="polite">Example loaded. Edit your note, then render a new preview.</div>
<pre id="meta"></pre>
</div>
</div>
</section>
<section class="card" id="preview">Preview will appear here.</section>
<p class="preview-legend"><strong>Preview:</strong> black solid lines are ink paths; blue dashed lines show pen-up travel and are not drawn.</p>
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
function bindRange(numberId, rangeId){ const number=byId(numberId), range=byId(rangeId); const sync=value=>{ number.value=value; range.value=value; }; number.addEventListener('input',()=>sync(number.value)); range.addEventListener('input',()=>sync(range.value)); }
function setControl(id,value){ byId(id).value=value; const range=byId(id+'Range'); if(range) range.value=value; }
bindRange('fontSize','fontSizeRange'); bindRange('lineSpacing','lineSpacingRange'); bindRange('letterSpacing','letterSpacingRange'); bindRange('wordSpacing','wordSpacingRange');
function hasCjk(text){ return /[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/u.test(text); }
function syncTypefaceForText(){
 byId('languageHint').textContent=hasCjk(byId('text').value)?'CJK detected. A compatible installed font is converted to centerlines; no outline fallback is used.':'Every mode draws centerlines only. Filled typefaces and unsupported characters are not silently converted.';
}
function syncExperimental(){
 const human=byId('preset').value==='human';
 const outline=byId('experimentalOutline').checked;
 if(human) byId('experimentalOutline').checked=false;
 byId('experimentalFontControls').style.display=outline&&!human?'block':'none';
 byId('strokeFontControls').style.display=human||outline?'none':'block';
 byId('experimentalControls').style.display=human?'none':'block';
 byId('handwritingControls').style.display=human?'block':'none';
}
function applyPreset(){
 const value=byId('preset').value;
 if(value==='standard') { byId('neuralStyle').value=9; setControl('slant',0); setControl('letterSpacing',0); byId('handwritingControls').open=false; }
 else if(value==='robot') { setControl('slant',0); setControl('letterSpacing',1.2); byId('strokeFont').value='robot'; byId('neuralExperimental').checked=false; byId('handwritingControls').open=false; }
 else { byId('neuralStyle').value=9; setControl('slant',3); setControl('letterSpacing',0.55); byId('handwritingControls').open=false; }
 byId('handwritingSummary').textContent=value==='human'?'Uses Hershey Script centerlines: clean single-line strokes designed for a pen plotter.':'Built-in authored stroke font; installed outline fonts are not used.';
 byId('strokeFontControls').style.display=value==='human'?'none':'block';
 syncExperimental();
 byId('renderButton').disabled=false;
 syncTypefaceForText();
}
function payload(){ return {
 text:byId('text').value, preset:byId('preset').value, engine:'stroke',
 writing_backend:(byId('preset').value==='human'&&byId('neuralExperimental').checked)?'neural':'stroke', neural_style:Number(byId('neuralStyle').value), neural_bias:Number(byId('neuralBias').value),
 font_family:byId('experimentalOutline').checked?byId('font').value:'', font_path:null, stroke_font:byId('strokeFont').value,
 experimental_outline_centerline:byId('experimentalOutline').checked,
 stroke_font_path:null,
 seed:Number(byId('seed').value), font_size_mm:Number(byId('fontSize').value)*25.4/72,
 line_spacing:Number(byId('lineSpacing').value),
 wrap_width_mm:byId('wrapMode').value==='on'?optionalNumber('wrapWidth'):null, connect_letters:false,
 word_spacing_em:Number(byId('wordSpacing').value), letter_spacing_mm:Number(byId('letterSpacing').value),
 variant_mode:byId('preset').value==='robot'?'first':'seeded', stroke_order:byId('preset').value==='robot'?'nearest':'authored', slant_deg:Number(byId('slant').value),
 page_width_mm:Number(byId('pageWidth').value), page_height_mm:Number(byId('pageHeight').value),
 page_origin_x_mm:Number(byId('originX').value), page_origin_y_mm:Number(byId('originY').value),
 margin_mm:8, fit_mode:byId('fitMode').value, horizontal_align:byId('align').value,
 vertical_align:'center', offset_x_mm:0, offset_y_mm:0, scale:1,
 z_up_mm:5, z_down_mm:0, pen_tip_mm:Number(byId('penTip').value), contact_compensation:byId('contactCompensation').checked, home_before_plot:byId('homeBeforePlot').checked, air_plot:false
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
function downloadGcode(){
 if(!latestGcode){byId('status').textContent='Render first.';return;}
 const blob=new Blob([latestGcode],{type:'text/plain'});
 const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download='plot.gcode'; link.click(); URL.revokeObjectURL(link.href);
}
function syncNeuralState(available){
 neuralAvailable=available;
 byId('neuralExperimental').disabled=!available;
 applyPreset();
}
fetch('/api/handwriting/status').then(response=>response.json()).then(data=>syncNeuralState(Boolean(data.neural_available))).catch(()=>syncNeuralState(false));
fetch('/api/fonts').then(response=>response.json()).then(data=>{
 const select=byId('strokeFont'); select.innerHTML='';
 (data.fonts||[]).forEach(font=>{ const option=document.createElement('option'); option.value=font.name; option.textContent=font.name; option.title=font.description; select.appendChild(option); });
}).catch(()=>{});
byId('experimentalOutline').addEventListener('change',syncExperimental);
byId('preset').addEventListener('change',applyPreset);
fetch('/api/font-library').then(response=>response.json()).then(data=>{
 const select=byId('font'); select.innerHTML='';
 (data.fonts||[]).forEach(font=>{ const option=document.createElement('option'); option.value=font.name; option.textContent=font.name; option.title=font.description; select.appendChild(option); });
}).catch(()=>{});
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
    stroke_font = request.stroke_font
    if request.preset == "robot":
        stroke_font = "robot"
    if request.preset == "human":
        stroke_font = "hershey-script"
    writing_backend = request.writing_backend if request.preset == "human" else "stroke"
    style = StyleConfig.for_preset(
        request.preset,
        engine=request.engine,
        writing_backend=writing_backend,
        experimental_outline_centerline=request.experimental_outline_centerline if request.preset != "human" else False,
        neural_style=request.neural_style,
        neural_bias=request.neural_bias,
        font_family=request.font_family,
        font_path=request.font_path,
        stroke_font=stroke_font,
        stroke_font_path=request.stroke_font_path,
        font_size_mm=request.font_size_mm,
        line_spacing=request.line_spacing,
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
            pen_tip_mm=request.pen_tip_mm,
            contact_compensation=request.contact_compensation,
            z_up_mm=request.z_up_mm,
            z_down_mm=request.z_down_mm,
            home_before_plot=request.home_before_plot,
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


@app.get("/api/font-library")
def font_library() -> dict[str, object]:
    """List installed outline fonts for the explicit experimental override."""
    return {"fonts": font_library_entries()}


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

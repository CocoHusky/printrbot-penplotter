"""Browser raster/handwriting studio for Release 0.5.

The studio is deliberately upstream of machine control. Uploaded images are
traced into the same polyline model used by every other input, manual edits
modify those polylines, and the exact edited geometry is then used for both
machine preview and G-code generation.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import tempfile
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from PIL import Image
from pydantic import BaseModel, Field

from .gcode import polylines_to_gcode
from .geometry import place_on_page, preview_svg, simplify_polylines, validate_polylines
from .models import LayoutConfig, MachineConfig, PageConfig, PenConfig, Polylines, RenderedJob
from .raster import (
    RasterTraceConfig,
    _load_grayscale,
    _otsu_threshold,
    _remove_small_components,
    editable_trace_svg,
    trace_raster,
)

router = APIRouter()
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _data_uri(data: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def _mask_data_uri(source: Path, config: RasterTraceConfig) -> tuple[str, int]:
    gray, _, _ = _load_grayscale(source, config)
    threshold = config.threshold if config.threshold is not None else _otsu_threshold(gray)
    mask = gray > threshold if config.invert else gray <= threshold
    cleaned, _, _, _ = _remove_small_components(mask, config.min_component_px)
    display = np.where(cleaned, 0, 255).astype(np.uint8)
    image = Image.fromarray(display, mode="L")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return _data_uri(output.getvalue(), "image/png"), threshold


def _render_geometry(
    polylines: Polylines,
    *,
    page: PageConfig | None = None,
    machine: MachineConfig | None = None,
    pen: PenConfig | None = None,
    layout: LayoutConfig | None = None,
    title: str = "Raster studio plot",
) -> RenderedJob:
    machine = machine or MachineConfig()
    page = page or PageConfig()
    pen = pen or PenConfig(air_plot=True)
    layout = layout or LayoutConfig(fit_mode="fit")
    validate_polylines(polylines)
    placed = place_on_page(polylines, page, layout, machine)
    placed = simplify_polylines(placed, 0.02)
    return RenderedJob(
        polylines=placed,
        preview_svg=preview_svg(placed, page, machine),
        gcode=polylines_to_gcode(placed, page, pen, machine, title=title),
        metadata={
            "input_type": "edited-raster",
            "strokes": len(placed),
            "points": sum(len(line) for line in placed),
            "air_plot": pen.air_plot,
            "home_before_plot": pen.home_before_plot,
        },
    )


class FinalizeRequest(BaseModel):
    polylines: list[list[tuple[float, float]]]
    page_width_mm: float = Field(default=152.4, gt=1, le=1000)
    page_height_mm: float = Field(default=152.4, gt=1, le=1000)
    margin_mm: float = Field(default=8.0, ge=0, le=100)
    horizontal_align: Literal["left", "center", "right"] = "center"
    vertical_align: Literal["bottom", "center", "top"] = "center"
    air_plot: bool = True
    home_before_plot: bool = False
    z_up_mm: float = 5.0
    z_down_mm: float = 0.0


@router.get("/raster", response_class=HTMLResponse)
def raster_studio() -> str:
    return STUDIO_HTML


@router.post("/api/raster/trace")
async def raster_trace(
    file: UploadFile = File(...),
    mode: Literal["centerline", "contour"] = Form("centerline"),
    threshold: str = Form(""),
    invert: bool = Form(False),
    blur_radius_px: float = Form(0.0),
    min_component_px: int = Form(8),
    simplify_px: float = Form(0.8),
    air_plot: bool = Form(True),
    home_before_plot: bool = Form(False),
) -> dict[str, object]:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds the 20 MiB studio upload limit.")

    manual_threshold: int | None
    if threshold.strip():
        try:
            manual_threshold = int(threshold)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Threshold must be an integer 0–255.") from exc
    else:
        manual_threshold = None

    config = RasterTraceConfig(
        mode=mode,
        threshold=manual_threshold,
        invert=invert,
        blur_radius_px=blur_radius_px,
        min_component_px=min_component_px,
        simplify_px=simplify_px,
    )

    suffix = Path(file.filename or "upload.png").suffix or ".png"
    source_sha256 = hashlib.sha256(data).hexdigest()
    try:
        with tempfile.TemporaryDirectory(prefix="printrbot-raster-") as directory:
            source = Path(directory) / f"source{suffix}"
            source.write_bytes(data)
            result = trace_raster(source, config)
            mask_uri, effective_threshold = _mask_data_uri(source, config)
            job = _render_geometry(
                result.polylines,
                pen=PenConfig(
                    air_plot=air_plot,
                    home_before_plot=home_before_plot,
                ),
                title=f"Raster studio: {file.filename or 'upload'}",
            )
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    original_type = file.content_type if (file.content_type or "").startswith("image/") else "image/png"
    metadata = dict(result.metadata)
    metadata.update(
        {
            "source_filename": file.filename,
            "source_sha256": source_sha256,
            "source_bytes": len(data),
            "software_stage": "release-0.5-studio",
            "effective_threshold": effective_threshold,
            "recognition_performed": False,
        }
    )
    job_metadata = dict(job.metadata)
    job_metadata.update(metadata)

    return {
        "original_data_uri": _data_uri(data, original_type),
        "mask_data_uri": mask_uri,
        "raw_trace_svg": editable_trace_svg(result.polylines),
        "raw_polylines": result.polylines,
        "final_preview_svg": job.preview_svg,
        "gcode": job.gcode,
        "metadata": job_metadata,
        "job_sidecar": {
            "schema": "printrbot-raster-job/v1",
            "source": {
                "filename": file.filename,
                "sha256": source_sha256,
                "bytes": len(data),
            },
            "trace_config": {
                "mode": config.mode,
                "threshold": config.threshold,
                "effective_threshold": effective_threshold,
                "invert": config.invert,
                "blur_radius_px": config.blur_radius_px,
                "min_component_px": config.min_component_px,
                "simplify_px": config.simplify_px,
            },
            "raw_polylines": result.polylines,
            "final_machine_polylines": job.polylines,
            "metadata": job_metadata,
        },
    }


@router.post("/api/raster/finalize")
def finalize_raster(request: FinalizeRequest) -> dict[str, object]:
    try:
        polylines: Polylines = [
            [(float(x), float(y)) for x, y in line] for line in request.polylines
        ]
        validate_polylines(polylines)
        page = PageConfig(
            width_mm=request.page_width_mm,
            height_mm=request.page_height_mm,
            margin_mm=request.margin_mm,
        )
        layout = LayoutConfig(
            fit_mode="fit",
            horizontal_align=request.horizontal_align,
            vertical_align=request.vertical_align,
        )
        pen = PenConfig(
            air_plot=request.air_plot,
            home_before_plot=request.home_before_plot,
            z_up_mm=request.z_up_mm,
            z_down_mm=request.z_down_mm,
        )
        job = _render_geometry(polylines, page=page, layout=layout, pen=pen)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "final_preview_svg": job.preview_svg,
        "gcode": job.gcode,
        "machine_polylines": job.polylines,
        "metadata": job.metadata,
    }


STUDIO_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Printrbot Image & Handwriting Studio</title>
<style>
:root{font-family:system-ui,-apple-system,sans-serif;color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#091019;color:#eef5fb}main{width:min(1450px,calc(100% - 24px));margin:20px auto 50px}h1{margin:0 0 4px}p{color:#9db0c2}.layout{display:grid;grid-template-columns:340px 1fr;gap:14px}.card{background:#111b27;border:1px solid #26394c;border-radius:14px;padding:14px}.drop{border:2px dashed #527394;border-radius:14px;padding:26px;text-align:center;cursor:pointer}.drop.drag{border-color:#79d4ff;background:#132b3b}.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}label{display:block;font-size:13px;color:#b9c8d5;margin:10px 0 4px}input,select,button{width:100%;padding:9px;border-radius:9px;border:1px solid #344b60;background:#0b141e;color:#eef5fb}button{background:#296fa5;font-weight:700;cursor:pointer;margin-top:8px}.secondary{background:#34475a}.danger{background:#853f46}.views{display:grid;grid-template-columns:1fr 1fr;gap:10px}.view{background:#dce5ed;color:#111;min-height:280px;border-radius:12px;padding:8px;overflow:auto}.view h3{margin:0 0 6px;font-size:13px;color:#415365}.view img,.view svg{display:block;max-width:100%;max-height:430px;margin:auto;background:white}.editor-toolbar{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin:8px 0}.editor-toolbar button{font-size:12px;padding:8px}.selected{stroke:#e23b42!important;stroke-width:2.3!important}.endpoint{fill:#2d8cff;stroke:white;stroke-width:.8;cursor:grab}.status{min-height:22px;color:#77e4ad;margin-top:8px}.warning{color:#ffca6a;font-size:12px;margin-top:5px}pre{font-size:11px;max-height:220px;overflow:auto;white-space:pre-wrap}.full{grid-column:1/-1}@media(max-width:900px){.layout{grid-template-columns:1fr}.views{grid-template-columns:1fr}.editor-toolbar{grid-template-columns:1fr 1fr}}
</style></head><body><main>
<h1>Image & Handwriting Studio</h1><p>Drop a scan or photo, clean it, inspect the trace, edit the actual paths, then generate the exact machine preview and G-code.</p>
<div class="layout"><section class="card">
<div id="drop" class="drop">Drop image here<br><small>or click to choose PNG/JPEG/WebP/TIFF/BMP</small><input id="file" type="file" accept="image/*" hidden></div>
<div class="row"><div><label>Mode</label><select id="mode"><option value="centerline">Handwriting / centerline</option><option value="contour">Image / contour</option></select></div><div><label>Threshold</label><input id="threshold" placeholder="Auto (Otsu)" type="number" min="0" max="255"></div></div>
<div class="row"><div><label>Blur (px)</label><input id="blur" type="number" min="0" max="20" step="0.2" value="0"></div><div><label>Remove components smaller than</label><input id="component" type="number" min="1" value="8"></div></div>
<div class="row"><div><label>Simplify (px)</label><input id="simplify" type="number" min="0" max="20" step="0.1" value="0.8"></div><div><label>Output</label><select id="air"><option value="true">Air plot</option><option value="false">Pen plot</option></select></div></div>
<label><input id="home" type="checkbox" style="width:auto" checked> Home all axes before plot</label><div class="warning">Required for Wi-Fi hardware jobs so machine coordinates are known before movement.</div>
<label><input id="invert" type="checkbox" style="width:auto"> Light marks on dark background</label>
<button id="trace">Trace / refresh</button>
<div class="editor-toolbar"><button id="undo" class="secondary">Undo</button><button id="delete" class="danger">Delete</button><button id="reverse" class="secondary">Reverse</button><button id="split" class="secondary">Split</button><button id="join" class="secondary">Join 2</button></div>
<button id="finalize">Finalize edited paths</button><button id="downloadG" class="secondary">Download G-code</button><button id="downloadSvg" class="secondary">Download edited SVG</button><button id="downloadJob" class="secondary">Download job JSON</button>
<div id="status" class="status">Choose an image.</div><pre id="meta"></pre>
</section><section class="views">
<div class="view"><h3>1 — Original</h3><div id="original"></div></div>
<div class="view"><h3>2 — Cleaned mask</h3><div id="mask"></div></div>
<div class="view"><h3>3 — Editable raw trace</h3><div id="editor"></div></div>
<div class="view"><h3>4 — Final machine preview</h3><div id="final"></div></div>
</section></div>
<script>
const $=id=>document.getElementById(id);let chosen=null,polys=[],history=[],selected=new Set(),latestG='',sidecar=null;
const drop=$('drop'),file=$('file');drop.onclick=()=>file.click();file.onchange=()=>{chosen=file.files[0];trace()};
for(const e of ['dragenter','dragover'])drop.addEventListener(e,x=>{x.preventDefault();drop.classList.add('drag')});
for(const e of ['dragleave','drop'])drop.addEventListener(e,x=>{x.preventDefault();drop.classList.remove('drag')});
drop.addEventListener('drop',e=>{chosen=e.dataTransfer.files[0];trace()});
function snapshot(){history.push(JSON.stringify(polys));if(history.length>40)history.shift()}
function bounds(){const pts=polys.filter(Boolean).flat();if(!pts.length)return [0,0,1,1];const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);return [Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]}
function renderEditor(){const good=polys.map((p,i)=>[p,i]).filter(([p])=>p&&p.length>1);if(!good.length){$('editor').innerHTML='No paths';return}const [x0,y0,x1,y1]=bounds(),pad=4,w=Math.max(1,x1-x0),h=Math.max(1,y1-y0);let s=`<svg id="editSvg" viewBox="${x0-pad} ${-y1-pad} ${w+2*pad} ${h+2*pad}">`;
for(const [line,i] of good){const pts=line.map(p=>`${p[0]},${-p[1]}`).join(' ');s+=`<polyline data-i="${i}" class="${selected.has(i)?'selected':''}" points="${pts}" fill="none" stroke="black" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>`}
if(selected.size===1){const i=[...selected][0],line=polys[i];if(line&&line.length){for(const [kind,p] of [['start',line[0]],['end',line[line.length-1]]])s+=`<circle class="endpoint" data-i="${i}" data-kind="${kind}" cx="${p[0]}" cy="${-p[1]}" r="2.2"/>`}}
s+='</svg>';$('editor').innerHTML=s;document.querySelectorAll('#editSvg polyline').forEach(el=>el.onclick=e=>{const i=Number(el.dataset.i);if(!e.shiftKey)selected.clear();selected.has(i)?selected.delete(i):selected.add(i);renderEditor()});setupDrag()}
function setupDrag(){document.querySelectorAll('.endpoint').forEach(c=>{c.onpointerdown=e=>{e.preventDefault();snapshot();const svg=$('editSvg'),i=Number(c.dataset.i),kind=c.dataset.kind;c.setPointerCapture(e.pointerId);c.onpointermove=ev=>{const pt=svg.createSVGPoint();pt.x=ev.clientX;pt.y=ev.clientY;const local=pt.matrixTransform(svg.getScreenCTM().inverse());const line=polys[i];const idx=kind==='start'?0:line.length-1;line[idx]=[local.x,-local.y];renderEditor()}}})}
async function trace(){if(!chosen)return;$('status').textContent='Tracing…';const f=new FormData();f.append('file',chosen);f.append('mode',$('mode').value);f.append('threshold',$('threshold').value);f.append('invert',$('invert').checked);f.append('blur_radius_px',$('blur').value);f.append('min_component_px',$('component').value);f.append('simplify_px',$('simplify').value);f.append('air_plot',$('air').value);f.append('home_before_plot',$('home').checked);try{const r=await fetch('/api/raster/trace',{method:'POST',body:f}),d=await r.json();if(!r.ok)throw Error(d.detail||'Trace failed');polys=d.raw_polylines;history=[];selected.clear();latestG=d.gcode;sidecar=d.job_sidecar;$('original').innerHTML=`<img src="${d.original_data_uri}">`;$('mask').innerHTML=`<img src="${d.mask_data_uri}">`;$('final').innerHTML=d.final_preview_svg;$('meta').textContent=JSON.stringify(d.metadata,null,2);renderEditor();$('status').textContent=`Ready — ${polys.length} raw strokes. Click paths to edit; Shift-click selects two.`}catch(e){$('status').textContent=e.message}}
$('trace').onclick=trace;$('undo').onclick=()=>{if(history.length){polys=JSON.parse(history.pop());selected.clear();renderEditor()}};
$('delete').onclick=()=>{if(!selected.size)return;snapshot();for(const i of selected)polys[i]=null;selected.clear();renderEditor()};
$('reverse').onclick=()=>{if(!selected.size)return;snapshot();for(const i of selected)if(polys[i])polys[i].reverse();renderEditor()};
$('split').onclick=()=>{if(selected.size!==1)return;$('status').textContent='Select exactly one stroke to split.';const i=[...selected][0],p=polys[i];if(!p||p.length<4)return;snapshot();const m=Math.floor(p.length/2);polys[i]=p.slice(0,m+1);polys.push(p.slice(m));selected.clear();renderEditor()};
$('join').onclick=()=>{if(selected.size!==2){$('status').textContent='Shift-click exactly two strokes to join.';return}snapshot();const [a,b]=[...selected],A=polys[a],B=polys[b];if(!A||!B)return;const d=(p,q)=>Math.hypot(p[0]-q[0],p[1]-q[1]);const choices=[[A,B],[A,[...B].reverse()],[[...A].reverse(),B],[[...A].reverse(),[...B].reverse()]];choices.sort((x,y)=>d(x[0][x[0].length-1],x[1][0])-d(y[0][y[0].length-1],y[1][0]));polys[a]=choices[0][0].concat(choices[0][1]);polys[b]=null;selected.clear();renderEditor()};
$('finalize').onclick=async()=>{const clean=polys.filter(p=>p&&p.length>1);try{const r=await fetch('/api/raster/finalize',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({polylines:clean,air_plot:$('air').value==='true',home_before_plot:$('home').checked})}),d=await r.json();if(!r.ok)throw Error(d.detail||'Finalize failed');latestG=d.gcode;$('final').innerHTML=d.final_preview_svg;if(sidecar){sidecar.edited_raw_polylines=clean;sidecar.final_machine_polylines=d.machine_polylines;sidecar.final_metadata=d.metadata}$('status').textContent='Final preview regenerated from the edited paths.'}catch(e){$('status').textContent=e.message}};
function download(name,data,type){const b=new Blob([data],{type}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),500)}
$('downloadG').onclick=()=>latestG&&download('plot.gcode',latestG,'text/plain');$('downloadJob').onclick=()=>sidecar&&download('plotter-raster-job.json',JSON.stringify(sidecar,null,2),'application/json');
$('downloadSvg').onclick=()=>{const clean=polys.filter(p=>p&&p.length>1),[x0,y0,x1,y1]=bounds();let s=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${x0-2} ${-y1-2} ${Math.max(1,x1-x0)+4} ${Math.max(1,y1-y0)+4}">`;for(const line of clean)s+=`<polyline points="${line.map(p=>p[0]+','+(-p[1])).join(' ')}" fill="none" stroke="black"/>`;s+='</svg>';download('edited-trace.svg',s,'image/svg+xml')};
</script></main></body></html>"""

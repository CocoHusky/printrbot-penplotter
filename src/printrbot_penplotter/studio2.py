"""Studio 2.0: unified Steps 2-8 image-to-plot browser interface."""
from __future__ import annotations

import base64
import hashlib
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from .auto_optimize import AutoOptimizeConfig, optimize_image
from .gcode import polylines_to_gcode
from .geometry import place_on_page, preview_svg, validate_polylines
from .image_preprocess import ImagePreprocessConfig
from .image_understanding import ImageUnderstandingConfig
from .line_art import LineArtConfig, STYLE_NAMES, render_line_art
from .models import LayoutConfig, MachineConfig, PageConfig, PenConfig
from .pen_shading import PenShadingConfig, SHADING_STYLE_NAMES, render_pen_shading
from .physical_plot import PhysicalPlotConfig, prepare_physical_plot

router = APIRouter()
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_WORKING_DIMENSION = {"quick": 480, "balanced": 720, "best": 960}


@router.get("/studio2", response_class=HTMLResponse)
def studio2() -> str:
    return STUDIO2_HTML


def _render_pipeline(
    source: Path,
    *,
    filename: str,
    mode: str,
    style: str,
    quality: str,
    detail: str,
    background_mode: str,
    pen_tip_mm: float,
    air_plot: bool,
    home_before_plot: bool,
) -> tuple[str, str, list[list[tuple[float, float]]], dict[str, object], int, int]:
    """Run the CPU-heavy image pipeline outside the ASGI event loop."""
    preprocess = ImagePreprocessConfig(
        auto_levels=True,
        background_mode=background_mode,  # type: ignore[arg-type]
        max_dimension_px=_WORKING_DIMENSION[quality],
    )
    understanding = ImageUnderstandingConfig(detail_level=detail, min_region_px=4)  # type: ignore[arg-type]

    if mode == "auto":
        artistic = optimize_image(
            source,
            AutoOptimizeConfig(quality=quality),  # type: ignore[arg-type]
            preprocess=preprocess,
            understanding=understanding,
        )
        raw = artistic.polylines
        artistic_meta = artistic.metadata
    elif mode == "line_art":
        if style not in STYLE_NAMES:
            raise ValueError(f"Unknown line-art style: {style}")
        artistic = render_line_art(
            source,
            LineArtConfig(style=style),  # type: ignore[arg-type]
            preprocess=preprocess,
            understanding=understanding,
        )
        raw = artistic.polylines
        artistic_meta = artistic.metadata
    else:
        if style not in SHADING_STYLE_NAMES:
            raise ValueError(f"Unknown shading style: {style}")
        artistic = render_pen_shading(
            source,
            PenShadingConfig(style=style),  # type: ignore[arg-type]
            preprocess=preprocess,
            understanding=understanding,
        )
        raw = artistic.polylines
        artistic_meta = artistic.metadata

    machine = MachineConfig()
    page = PageConfig()
    layout = LayoutConfig(fit_mode="fit")
    placed = place_on_page(raw, page, layout, machine)
    pen = PenConfig(air_plot=air_plot, home_before_plot=home_before_plot)
    physical = prepare_physical_plot(
        placed,
        PhysicalPlotConfig(pen_tip_mm=pen_tip_mm, quality=quality),  # type: ignore[arg-type]
        pen=pen,
    )
    final = physical.polylines
    validate_polylines(final)
    preview = preview_svg(final, page, machine)
    gcode = polylines_to_gcode(final, page, pen, machine, title=f"Studio 2: {filename}")

    metadata = dict(artistic_meta)
    metadata.update(physical.metadata)
    metadata["studio_working_max_dimension_px"] = _WORKING_DIMENSION[quality]
    return preview, gcode, final, metadata, len(raw), len(final)


@router.post("/api/studio2/render")
async def render_studio2(
    file: UploadFile = File(...),
    mode: Literal["auto", "line_art", "shading"] = Form("auto"),
    style: str = Form("refined_pen_sketch"),
    quality: Literal["quick", "balanced", "best"] = Form("balanced"),
    detail: Literal["low", "medium", "high", "extreme"] = Form("high"),
    background_mode: Literal["none", "suppress", "remove"] = Form("suppress"),
    pen_tip_mm: float = Form(0.5),
    air_plot: bool = Form(True),
    home_before_plot: bool = Form(True),
) -> dict[str, object]:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(400, "Uploaded image is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image exceeds the 20 MiB studio upload limit.")
    suffix = Path(file.filename or "upload.png").suffix or ".png"
    filename = file.filename or "image"

    try:
        with tempfile.TemporaryDirectory(prefix="printrbot-studio2-") as directory:
            source = Path(directory) / f"source{suffix}"
            source.write_bytes(data)
            preview, gcode, final, pipeline_meta, raw_strokes, final_strokes = await run_in_threadpool(
                _render_pipeline,
                source,
                filename=filename,
                mode=mode,
                style=style,
                quality=quality,
                detail=detail,
                background_mode=background_mode,
                pen_tip_mm=pen_tip_mm,
                air_plot=air_plot,
                home_before_plot=home_before_plot,
            )
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc

    metadata = dict(pipeline_meta)
    metadata.update({
        "studio_schema": "printrbot-studio2/v1",
        "source_filename": file.filename,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "mode": mode,
        "requested_style": style,
        "quality": quality,
        "detail": detail,
        "background_mode": background_mode,
        "home_before_plot": home_before_plot,
        "air_plot": air_plot,
    })
    return {
        "preview_svg": preview,
        "gcode": gcode,
        "polylines": final,
        "metadata": metadata,
        "stages": {
            "source": f"data:{file.content_type or 'image/png'};base64,{base64.b64encode(data).decode('ascii')}",
            "artistic_strokes": raw_strokes,
            "physical_strokes": final_strokes,
        },
    }


STUDIO2_HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>Printrbot Studio 2.0</title>
<style>
body{font-family:system-ui;margin:24px;background:#f6f6f6;color:#111}main{max-width:1320px;margin:auto}.grid{display:grid;grid-template-columns:320px 1fr;gap:18px}.card{background:white;border:1px solid #ddd;border-radius:12px;padding:16px}label{display:block;margin:10px 0 4px}select,input,button{width:100%;padding:8px;box-sizing:border-box}button{margin-top:14px;font-weight:700}button:disabled{opacity:.55;cursor:wait}.tabs{font-size:12px;color:#555;margin-bottom:10px}pre{white-space:pre-wrap;max-height:220px;overflow:auto}.preview-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.pane{border:1px solid #e0e0e0;border-radius:10px;padding:10px;min-height:320px;background:#fafafa}.pane h3{margin:0 0 8px;font-size:15px}.pane img{display:block;width:100%;height:300px;object-fit:contain}.pane svg{width:100%;height:300px}.placeholder{height:300px;display:flex;align-items:center;justify-content:center;color:#777;text-align:center}.status{margin-top:12px;padding:10px;border-radius:8px;background:#f2f2f2;font-size:14px}.status.busy{background:#fff4cc}.status.error{background:#ffe2e2;color:#8b0000}.spinner{display:inline-block;width:12px;height:12px;border:2px solid #aaa;border-top-color:#111;border-radius:50%;animation:spin .8s linear infinite;margin-right:7px;vertical-align:-2px}@keyframes spin{to{transform:rotate(360deg)}}
</style></head>
<body><main><h1>Printrbot Studio 2.0</h1><div class="tabs">SOURCE · AUTO · STYLE · IMAGE · LINES · SHADING · MOTION · MACHINE</div>
<div class="grid"><form id="f" class="card">
<label>Source image</label><input id="file" name="file" type="file" accept="image/*" required>
<label>Pipeline</label><select name="mode"><option value="auto">Auto</option><option value="line_art">Line art</option><option value="shading">Pen shading</option></select>
<label>Style</label><select name="style">
<option>refined_pen_sketch</option><option>clean_outline</option><option>detailed_outline</option><option>continuous_contour</option><option>pet_portrait</option><option>comic_ink</option><option>crosshatch</option><option>dense_crosshatch</option><option>engraving</option><option>contour_hatch</option><option>fur_texture</option>
</select>
<label>Quality</label><select name="quality"><option>quick</option><option selected>balanced</option><option>best</option></select>
<label>Detail</label><select name="detail"><option>low</option><option>medium</option><option selected>high</option><option>extreme</option></select>
<label>Background</label><select name="background_mode"><option>none</option><option selected>suppress</option><option>remove</option></select>
<label>Pen tip (mm)</label><input name="pen_tip_mm" type="number" value="0.5" min="0.05" max="5" step="0.05">
<label><input name="air_plot" type="checkbox" checked style="width:auto"> Air plot</label>
<label><input name="home_before_plot" type="checkbox" checked style="width:auto"> Home before plot</label>
<button id="generate">Generate drawing</button><div id="status" class="status">Choose an image. The original will appear immediately.</div></form>
<section class="card"><h2>Preview</h2><div class="preview-grid"><div class="pane"><h3>Original</h3><div id="sourcePreview" class="placeholder">No image selected.</div></div><div class="pane"><h3>Exact machine preview</h3><div id="preview" class="placeholder">Generate a drawing to see the final pen paths.</div></div></div><h3>Pipeline metadata</h3><pre id="meta"></pre></section></div></main>
<script>
const form=document.getElementById('f');const fileInput=document.getElementById('file');const sourcePreview=document.getElementById('sourcePreview');const preview=document.getElementById('preview');const meta=document.getElementById('meta');const status=document.getElementById('status');const button=document.getElementById('generate');let objectUrl=null;
fileInput.addEventListener('change',()=>{const file=fileInput.files&&fileInput.files[0];if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=null;}if(!file){sourcePreview.className='placeholder';sourcePreview.textContent='No image selected.';return;}objectUrl=URL.createObjectURL(file);sourcePreview.className='';sourcePreview.innerHTML='';const img=document.createElement('img');img.src=objectUrl;img.alt='Selected source image';sourcePreview.appendChild(img);status.className='status';status.textContent='Image loaded. Click Generate drawing.';});
form.onsubmit=async(e)=>{e.preventDefault();const fd=new FormData(form);for(const n of ['air_plot','home_before_plot'])fd.set(n,form.elements[n].checked?'true':'false');button.disabled=true;const start=performance.now();status.className='status busy';status.innerHTML='<span class="spinner"></span>Generating drawing…';preview.className='placeholder';preview.textContent='Rendering… the page remains responsive while the image pipeline runs.';meta.textContent='';const timer=setInterval(()=>{status.innerHTML='<span class="spinner"></span>Generating drawing… '+((performance.now()-start)/1000).toFixed(1)+' s';},250);try{const r=await fetch('/api/studio2/render',{method:'POST',body:fd});const j=await r.json();if(!r.ok)throw new Error(j.detail||'Render failed');preview.className='';preview.innerHTML=j.preview_svg;meta.textContent=JSON.stringify(j.metadata,null,2);status.className='status';status.textContent='Done in '+((performance.now()-start)/1000).toFixed(1)+' s · '+j.stages.artistic_strokes+' artistic strokes → '+j.stages.physical_strokes+' plot strokes.';}catch(err){preview.className='placeholder';preview.textContent='No drawing generated.';status.className='status error';status.textContent=err instanceof Error?err.message:String(err);}finally{clearInterval(timer);button.disabled=false;}};
</script>
</body></html>'''

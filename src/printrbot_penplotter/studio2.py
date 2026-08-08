"""Studio 2.0: unified Steps 2-8 image-to-plot browser interface."""
from __future__ import annotations

import base64
import hashlib
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

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

@router.get("/studio2", response_class=HTMLResponse)
def studio2() -> str:
    return STUDIO2_HTML

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
    preprocess = ImagePreprocessConfig(auto_levels=True, background_mode=background_mode)
    understanding = ImageUnderstandingConfig(detail_level=detail, min_region_px=4)
    try:
        with tempfile.TemporaryDirectory(prefix="printrbot-studio2-") as directory:
            source = Path(directory) / f"source{suffix}"
            source.write_bytes(data)
            if mode == "auto":
                artistic = optimize_image(source, AutoOptimizeConfig(quality=quality), preprocess=preprocess, understanding=understanding)
                raw = artistic.polylines
                artistic_meta = artistic.metadata
            elif mode == "line_art":
                if style not in STYLE_NAMES:
                    raise ValueError(f"Unknown line-art style: {style}")
                artistic = render_line_art(source, LineArtConfig(style=style), preprocess=preprocess, understanding=understanding)
                raw = artistic.polylines
                artistic_meta = artistic.metadata
            else:
                if style not in SHADING_STYLE_NAMES:
                    raise ValueError(f"Unknown shading style: {style}")
                artistic = render_pen_shading(source, PenShadingConfig(style=style), preprocess=preprocess, understanding=understanding)
                raw = artistic.polylines
                artistic_meta = artistic.metadata

            machine = MachineConfig()
            page = PageConfig()
            layout = LayoutConfig(fit_mode="fit")
            placed = place_on_page(raw, page, layout, machine)
            physical = prepare_physical_plot(placed, PhysicalPlotConfig(pen_tip_mm=pen_tip_mm, quality=quality), pen=PenConfig(air_plot=air_plot, home_before_plot=home_before_plot))
            final = physical.polylines
            validate_polylines(final)
            pen = PenConfig(air_plot=air_plot, home_before_plot=home_before_plot)
            preview = preview_svg(final, page, machine)
            gcode = polylines_to_gcode(final, page, pen, machine, title=f"Studio 2: {file.filename or 'image'}")
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc

    metadata = dict(artistic_meta)
    metadata.update(physical.metadata)
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
            "artistic_strokes": len(raw),
            "physical_strokes": len(final),
        },
    }

STUDIO2_HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>Printrbot Studio 2.0</title>
<style>body{font-family:system-ui;margin:24px;background:#f6f6f6;color:#111}main{max-width:1180px;margin:auto}.grid{display:grid;grid-template-columns:320px 1fr;gap:18px}.card{background:white;border:1px solid #ddd;border-radius:12px;padding:16px}label{display:block;margin:10px 0 4px}select,input,button{width:100%;padding:8px;box-sizing:border-box}button{margin-top:14px;font-weight:700}#preview svg{width:100%;height:auto}.tabs{font-size:12px;color:#555;margin-bottom:10px}pre{white-space:pre-wrap;max-height:220px;overflow:auto}</style></head>
<body><main><h1>Printrbot Studio 2.0</h1><div class="tabs">SOURCE · AUTO · STYLE · IMAGE · LINES · SHADING · MOTION · MACHINE</div>
<div class="grid"><form id="f" class="card">
<label>Source image</label><input name="file" type="file" accept="image/*" required>
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
<button>Generate drawing</button></form>
<section class="card"><h2>Exact machine preview</h2><div id="preview">Drop an image and generate.</div><h3>Pipeline metadata</h3><pre id="meta"></pre></section></div></main>
<script>document.getElementById('f').onsubmit=async(e)=>{e.preventDefault();let fd=new FormData(e.target);for(const n of ['air_plot','home_before_plot'])fd.set(n,e.target.elements[n].checked?'true':'false');let r=await fetch('/api/studio2/render',{method:'POST',body:fd});let j=await r.json();if(!r.ok){document.getElementById('preview').textContent=j.detail;return;}document.getElementById('preview').innerHTML=j.preview_svg;document.getElementById('meta').textContent=JSON.stringify(j.metadata,null,2);};</script>
</body></html>'''

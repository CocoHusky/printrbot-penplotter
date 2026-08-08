"""Studio 2.1 wrapper: responsive auto preview, final sizing, saves, and orientation fix.

This module intentionally wraps the established Studio 2 rendering pipeline instead
of duplicating image-analysis/style logic. The returned final polylines are the
single source for both preview SVG and G-code after the optional final-size transform.
"""
from __future__ import annotations

import math
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

from . import studio2 as legacy
from .gcode import polylines_to_gcode
from .geometry import preview_svg, validate_polylines
from .models import MachineConfig, PageConfig, PenConfig, Polylines

router = APIRouter()

SizeMode = Literal["natural", "fit_box", "force_exact"]


def _bool(form: object, name: str, default: bool) -> bool:
    value = getattr(form, "get")(name)
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _str(form: object, name: str, default: str) -> str:
    value = getattr(form, "get")(name)
    return default if value is None else str(value)


def _float(form: object, name: str, default: float) -> float:
    value = getattr(form, "get")(name)
    try:
        return default if value is None or str(value).strip() == "" else float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc


def _int(form: object, name: str, default: int) -> int:
    value = getattr(form, "get")(name)
    try:
        return default if value is None or str(value).strip() == "" else int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _bounds(polylines: Polylines) -> tuple[float, float, float, float]:
    points = [point for line in polylines for point in line]
    if not points:
        raise ValueError("Drawing contains no geometry.")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _final_size_transform(
    polylines: Polylines,
    *,
    size_mode: SizeMode,
    target_width_mm: float,
    target_height_mm: float,
    keep_aspect: bool,
    final_scale_percent: float,
    clamp_to_bed: bool,
    correct_orientation: bool,
    page: PageConfig,
) -> tuple[Polylines, dict[str, object]]:
    if size_mode not in ("natural", "fit_box", "force_exact"):
        raise ValueError("Size mode must be natural, fit_box, or force_exact.")
    for name, value in (
        ("target_width_mm", target_width_mm),
        ("target_height_mm", target_height_mm),
        ("final_scale_percent", final_scale_percent),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite.")
    if target_width_mm > 1000 or target_height_mm > 1000 or final_scale_percent > 1000:
        raise ValueError("Requested final size is unreasonably large.")

    x0, y0, x1, y1 = _bounds(polylines)
    source_w = max(x1 - x0, 1e-9)
    source_h = max(y1 - y0, 1e-9)
    source_cx = (x0 + x1) * 0.5
    source_cy = (y0 + y1) * 0.5

    if size_mode == "natural":
        sx = sy = 1.0
    elif size_mode == "fit_box" or keep_aspect:
        uniform = min(target_width_mm / source_w, target_height_mm / source_h)
        sx = sy = uniform
    else:
        sx = target_width_mm / source_w
        sy = target_height_mm / source_h

    post = final_scale_percent / 100.0
    sx *= post
    sy *= post

    requested_w = source_w * sx
    requested_h = source_h * sy
    clamped = False
    if requested_w > page.drawable_width_mm or requested_h > page.drawable_height_mm:
        if not clamp_to_bed:
            raise ValueError(
                f"Final drawing would be {requested_w:.2f} × {requested_h:.2f} mm, "
                f"larger than the drawable area {page.drawable_width_mm:.2f} × "
                f"{page.drawable_height_mm:.2f} mm. Enable Clamp to bed or reduce size."
            )
        fit = min(page.drawable_width_mm / requested_w, page.drawable_height_mm / requested_h)
        sx *= fit
        sy *= fit
        clamped = True

    dest_cx = page.origin_x_mm + page.width_mm * 0.5
    dest_cy = page.origin_y_mm + page.height_mm * 0.5
    transformed: Polylines = []
    for line in polylines:
        out = []
        for x, y in line:
            dx = x - source_cx
            dy = y - source_cy
            # Raster images are top-left/Y-down; machine coordinates are Y-up.
            # Studio historically mapped the final image upside-down. Mirror once
            # around the source center before final placement.
            if correct_orientation:
                dy = -dy
            out.append((dest_cx + dx * sx, dest_cy + dy * sy))
        transformed.append(out)

    validate_polylines(transformed)
    fx0, fy0, fx1, fy1 = _bounds(transformed)
    return transformed, {
        "size_mode": size_mode,
        "target_width_mm": target_width_mm,
        "target_height_mm": target_height_mm,
        "keep_aspect": keep_aspect,
        "final_scale_percent": final_scale_percent,
        "clamp_to_bed": clamp_to_bed,
        "final_size_clamped": clamped,
        "orientation_corrected": correct_orientation,
        "pre_final_width_mm": round(source_w, 4),
        "pre_final_height_mm": round(source_h, 4),
        "final_width_mm": round(fx1 - fx0, 4),
        "final_height_mm": round(fy1 - fy0, 4),
    }


@router.get("/studio2", response_class=HTMLResponse)
def studio2() -> str:
    html = legacy.STUDIO2_HTML
    size_controls = r'''
<div class="group" id="finalSize"><h3>Final drawing size</h3>
<label>Size mode</label><select id="sizeMode" name="size_mode"><option value="fit_box" selected>Fit inside box</option><option value="force_exact">Force exact width × height</option><option value="natural">Keep current generated size</option></select>
<div class="row"><div><label>Width (mm)</label><input id="targetWidth" name="target_width_mm" type="number" min="1" max="152.4" step="0.1" value="120"></div><div><label>Height (mm)</label><input id="targetHeight" name="target_height_mm" type="number" min="1" max="152.4" step="0.1" value="120"></div></div>
<label class="check"><input id="keepAspect" name="keep_aspect" type="checkbox" checked> Keep aspect ratio</label>
<label>Final scale (%)</label><input name="final_scale_percent" type="number" min="1" max="1000" step="1" value="100">
<label class="check"><input name="clamp_to_bed" type="checkbox" checked> Clamp to drawable bed area</label>
<div class="hint">Sizing is applied after drawing generation, before the final preview and G-code export.</div>
</div>
'''
    html = html.replace(
        '<button id="advancedToggle" class="advanced-toggle" type="button">Advanced image & style controls ▾</button>',
        size_controls + '<button id="advancedToggle" class="advanced-toggle" type="button">Advanced image & style controls ▾</button>',
    )
    # Keep the original button as the form submit target but move actions into a
    # persistent bottom-right toolbar.
    html = html.replace('<button id="generate">Generate drawing</button>', '<button id="generate" style="display:none">Generate drawing</button>')
    html = html.replace(
        '</style></head>',
        '.floating-actions{position:fixed;right:18px;bottom:18px;z-index:9999;display:flex;gap:8px;padding:10px;background:rgba(255,255,255,.96);border:1px solid #d5d5d5;border-radius:12px;box-shadow:0 5px 22px rgba(0,0,0,.14)}.floating-actions button{width:auto;min-width:112px;margin:0}.floating-actions button.primary{background:#111;color:#fff;border-color:#111}@media(max-width:700px){.floating-actions{left:10px;right:10px}.floating-actions button{flex:1;min-width:0}}\n</style></head>',
    )
    pre_script = r'''<script>
window.__studioLast=null;
const __nativeFetch=window.fetch.bind(window);
window.fetch=async(...args)=>{const response=await __nativeFetch(...args);try{const url=String(args[0]||'');if(url.includes('/api/studio2/render')){const clone=response.clone();const body=await clone.json();if(response.ok)window.__studioLast=body;}}catch(_e){}return response;};
</script>
'''
    html = html.replace('<script>\nconst lineStyles=', pre_script + '<script>\nconst lineStyles=', 1)
    floating = r'''
<div class="floating-actions" id="studio2FloatingActions">
<button id="floatingGenerate" class="primary" type="button">Generate drawing</button>
<button id="floatingSaveSvg" type="button" disabled>Save SVG</button>
<button id="floatingSaveGcode" type="button" disabled>Save G-code</button>
</div>
<script>
const floatingGenerate=document.getElementById('floatingGenerate');
const saveSvg=document.getElementById('floatingSaveSvg');
const saveGcode=document.getElementById('floatingSaveGcode');
const sizeMode=document.getElementById('sizeMode');
const targetWidth=document.getElementById('targetWidth');
const targetHeight=document.getElementById('targetHeight');
const keepAspect=document.getElementById('keepAspect');
function updateSizeMode(){const natural=sizeMode.value==='natural';targetWidth.disabled=natural;targetHeight.disabled=natural;keepAspect.disabled=natural;}
sizeMode.addEventListener('change',updateSizeMode);updateSizeMode();
floatingGenerate.onclick=()=>document.getElementById('f').requestSubmit();
const observer=new MutationObserver(()=>{const busy=document.getElementById('generate').disabled;floatingGenerate.disabled=busy;const ready=!!window.__studioLast&&!busy;saveSvg.disabled=!ready;saveGcode.disabled=!ready;});
observer.observe(document.getElementById('status'),{childList:true,subtree:true,characterData:true,attributes:true});
async function saveText(name,text,type){const blob=new Blob([text],{type});if(window.showSaveFilePicker){try{const handle=await window.showSaveFilePicker({suggestedName:name,types:[{description:type,accept:{[type]:[name.endsWith('.svg')?'.svg':'.gcode']}}]});const writable=await handle.createWritable();await writable.write(blob);await writable.close();return;}catch(e){if(e&&e.name==='AbortError')return;}}const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},1000);}
saveSvg.onclick=()=>{const j=window.__studioLast;if(j)saveText('printrbot-drawing.svg',j.preview_svg,'image/svg+xml');};
saveGcode.onclick=()=>{const j=window.__studioLast;if(j)saveText('printrbot-drawing.gcode',j.gcode,'text/plain');};
</script>
'''
    html = html.replace('</body></html>', floating + '</body></html>')
    return html


@router.post("/api/studio2/render")
async def render_studio2(request: Request) -> dict[str, object]:
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise HTTPException(400, "A source image is required.")

    mode = _str(form, "mode", "auto")
    requested_quality = _str(form, "quality", "balanced")
    # Auto is a preview/selection pipeline. Running it at 720/960 px can make
    # normal photographs take a minute. Keep interactive Auto bounded; manual
    # line/shading modes still honor the requested quality exactly.
    effective_quality = "quick" if mode == "auto" and requested_quality != "best" else requested_quality

    try:
        result = await legacy.render_studio2(
            file=upload,
            mode=mode,  # type: ignore[arg-type]
            style=_str(form, "style", "refined_pen_sketch"),
            quality=effective_quality,  # type: ignore[arg-type]
            detail=_str(form, "detail", "high"),  # type: ignore[arg-type]
            background_mode=_str(form, "background_mode", "suppress"),  # type: ignore[arg-type]
            pen_tip_mm=_float(form, "pen_tip_mm", 0.5),
            z_up_mm=_float(form, "z_up_mm", 5.0),
            z_down_mm=_float(form, "z_down_mm", 0.0),
            air_plot=_bool(form, "air_plot", True),
            home_before_plot=_bool(form, "home_before_plot", True),
            grayscale_mode=_str(form, "grayscale_mode", "luminance"),
            rgb_red=_float(form, "rgb_red", 0.2126),
            rgb_green=_float(form, "rgb_green", 0.7152),
            rgb_blue=_float(form, "rgb_blue", 0.0722),
            exposure_ev=_float(form, "exposure_ev", 0.0),
            brightness=_float(form, "brightness", 0.0),
            contrast=_float(form, "contrast", 1.0),
            gamma=_float(form, "gamma", 1.0),
            black_point=_int(form, "black_point", 0),
            white_point=_int(form, "white_point", 255),
            auto_levels=_bool(form, "auto_levels", True),
            histogram_equalize=_bool(form, "histogram_equalize", False),
            clahe_clip_limit=_float(form, "clahe_clip_limit", 0.0),
            gaussian_blur_radius_px=_float(form, "gaussian_blur_radius_px", 0.0),
            median_radius_px=_int(form, "median_radius_px", 0),
            despeckle_radius_px=_int(form, "despeckle_radius_px", 0),
            background_radius_px=_float(form, "background_radius_px", 24.0),
            background_strength=_float(form, "background_strength", 1.0),
            threshold_mode=_str(form, "threshold_mode", "otsu"),
            threshold_value=_str(form, "threshold_value", ""),
            threshold_invert=_bool(form, "threshold_invert", False),
            threshold_window_px=_int(form, "threshold_window_px", 31),
            threshold_offset=_float(form, "threshold_offset", 5.0),
            edge_method=_str(form, "edge_method", "multiscale_canny"),
            edge_low=_float(form, "edge_low", 0.10),
            edge_high=_float(form, "edge_high", 0.24),
            min_component_px=_int(form, "min_component_px", 8),
            tonal_bands=_str(form, "tonal_bands", "42,84,126,168,210"),
            include_outline=_bool(form, "include_outline", True),
            outline_style=_str(form, "outline_style", "refined_pen_sketch"),
            hatch_spacing_px=_float(form, "hatch_spacing_px", 5.0),
            darkness_threshold=_float(form, "darkness_threshold", 0.22),
            shading_min_stroke_px=_float(form, "shading_min_stroke_px", 1.25),
            artistic_stroke_limit=_int(form, "artistic_stroke_limit", 20_000),
            artistic_point_limit=_int(form, "artistic_point_limit", 2_000_000),
            bypass_artistic_limit=_bool(form, "bypass_artistic_limit", False),
            max_skeleton_iterations=_int(form, "max_skeleton_iterations", 256),
            style_edge_threshold=_float(form, "style_edge_threshold", 0.58),
            style_strong_edge_threshold=_float(form, "style_strong_edge_threshold", 0.72),
            style_tone_threshold=_int(form, "style_tone_threshold", 170),
            style_dilation_passes=_int(form, "style_dilation_passes", 1),
            style_simplify_tolerance_px=_float(form, "style_simplify_tolerance_px", -1.0),
            style_smooth_passes=_int(form, "style_smooth_passes", -1),
            style_join_distance_px=_float(form, "style_join_distance_px", -1.0),
            shading_seed=_int(form, "shading_seed", 0),
            shading_angle_offset_deg=_float(form, "shading_angle_offset_deg", 0.0),
            shading_density_scale=_float(form, "shading_density_scale", 1.0),
            shading_outline_join_distance_px=_float(form, "shading_outline_join_distance_px", 0.0),
        )

        page = PageConfig()
        machine = MachineConfig()
        final, size_meta = _final_size_transform(
            result["polylines"],  # type: ignore[arg-type]
            size_mode=_str(form, "size_mode", "fit_box"),  # type: ignore[arg-type]
            target_width_mm=_float(form, "target_width_mm", 120.0),
            target_height_mm=_float(form, "target_height_mm", 120.0),
            keep_aspect=_bool(form, "keep_aspect", True),
            final_scale_percent=_float(form, "final_scale_percent", 100.0),
            clamp_to_bed=_bool(form, "clamp_to_bed", True),
            correct_orientation=True,
            page=page,
        )
        pen = PenConfig(
            z_up_mm=_float(form, "z_up_mm", 5.0),
            z_down_mm=_float(form, "z_down_mm", 0.0),
            air_plot=_bool(form, "air_plot", True),
            home_before_plot=_bool(form, "home_before_plot", True),
        )
        preview = preview_svg(final, page, machine)
        filename = str(result.get("metadata", {}).get("source_filename") or "image")
        gcode = polylines_to_gcode(final, page, pen, machine, title=f"Studio 2: {filename}")

        result["polylines"] = final
        result["preview_svg"] = preview
        result["gcode"] = gcode
        metadata = dict(result.get("metadata", {}))
        metadata.update(size_meta)
        metadata["studio_schema"] = "printrbot-studio2/v3"
        metadata["requested_quality"] = requested_quality
        metadata["effective_quality"] = effective_quality
        metadata["auto_interactive_preview"] = mode == "auto" and requested_quality != effective_quality
        result["metadata"] = metadata
        return result
    except HTTPException:
        raise
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc

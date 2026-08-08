"""Studio 2.1 wrapper: responsive auto preview, final sizing, saves, and orientation fix.

This module intentionally wraps the established Studio 2 rendering pipeline instead
of duplicating image-analysis/style logic. The returned final polylines are the
single source for both preview SVG and G-code after the optional final-size transform.
"""
from __future__ import annotations

import math
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

from . import studio2 as legacy
from .gcode import polylines_to_gcode
from .geometry import preview_svg, validate_polylines
from .models import MachineConfig, PageConfig, PenConfig, Polylines
from .optimize import motion_metrics

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
        '.control-section{margin-top:10px;border:1px solid #e2e2e2;border-radius:9px;background:#fff;overflow:hidden}.control-section>summary{padding:10px;cursor:pointer;font-size:14px;font-weight:700;list-style-position:inside}.control-section>summary:hover{background:#f7f7f7}.control-section>.group{margin:0;border:0;border-top:1px solid #eee;border-radius:0}.control-section[hidden]{display:none}.floating-actions{position:fixed;right:18px;bottom:18px;z-index:9999;display:flex;gap:8px;padding:10px;background:rgba(255,255,255,.96);border:1px solid #d5d5d5;border-radius:12px;box-shadow:0 5px 22px rgba(0,0,0,.14)}.floating-actions button{width:auto;min-width:112px;margin:0}.floating-actions button.primary{background:#111;color:#fff;border-color:#111}.studio-step-shell{display:grid;grid-template-columns:190px minmax(360px,460px) minmax(0,1fr);gap:16px;align-items:start}.studio-step-shell>.step-rail{position:sticky;top:16px}.step-rail{display:flex;flex-direction:column;gap:6px}.process-tab{text-align:left;margin:0;padding:12px;border:1px solid #ddd;background:#fff;border-radius:9px;font-size:13px}.process-tab strong{display:block;font-size:13px}.process-tab span{display:block;color:#777;font-size:11px;font-weight:400;margin-top:3px}.process-tab.active{background:#111;color:#fff;border-color:#111}.process-tab.active span{color:#ddd}.step-controls{min-width:0}.step-controls>.step-panel{display:none}.step-controls>.step-panel.active{display:block}.step-panel{background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px}.step-panel>h2{margin:0 0 4px;font-size:18px}.step-panel>p{margin:0 0 14px;color:#666;font-size:12px}.step-panel>.group,.step-panel>.control-section{margin-top:12px}.step-panel>#advancedToggle,.step-panel>#advanced{display:none}.step-visuals{min-width:0}.step-visual{display:none;background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px}.step-visual.active{display:block}.step-visual h2{margin:0 0 4px;font-size:18px}.step-visual .visual-subtitle{color:#666;font-size:12px;margin-bottom:14px}.before-after{display:grid;grid-template-columns:1fr 1fr;gap:12px}.before-after .pane{min-height:360px}.before-after .pane h3{font-size:13px}.before-after .pane img,.before-after .pane svg{height:320px}.step-visual pre{max-height:180px}.step-visual .placeholder{height:320px}.step-visuals .stage-tabs,.step-visuals+.card{display:none}.studio-step-shell>.step-controls>.card{box-shadow:none}.step-actions{margin-top:14px}.step-actions button{margin-top:0}.legacy-preview{display:none!important}@media(max-width:1000px){.studio-step-shell{grid-template-columns:150px minmax(320px,1fr)}.step-visuals{grid-column:1 / -1;grid-row:2}.studio-step-shell>.step-controls{grid-column:2}.studio-step-shell>.step-rail{grid-column:1;grid-row:1}.before-after .pane{min-height:280px}.before-after .pane img,.before-after .pane svg,.step-visual .placeholder{height:240px}}@media(max-width:700px){.studio-step-shell{display:block}.studio-step-shell>.step-rail{position:static;display:grid;grid-template-columns:1fr 1fr;margin-bottom:10px}.process-tab{padding:9px}.step-controls{margin-bottom:12px}.before-after{grid-template-columns:1fr}.before-after .pane{min-height:220px}.before-after .pane img,.before-after .pane svg,.step-visual .placeholder{height:220px}}\n</style></head>',
    )
    pre_script = r'''<script>
window.__studioLast=null;
const __nativeFetch=window.fetch.bind(window);
window.fetch=async(...args)=>{const response=await __nativeFetch(...args);try{const url=String(args[0]||'');if(url.includes('/api/studio2/render')){const clone=response.clone();const body=await clone.json();if(response.ok)window.__studioLast=body;}}catch(_e){}return response;};
</script>
'''
    html = html.replace('<script>\nconst lineStyles=', pre_script + '<script>\nconst lineStyles=', 1)
    step_editor = r'''
<script>
(()=>{
  const form=document.getElementById('f');
  const grid=form&&form.parentElement;
  const legacyPreview=form&&form.nextElementSibling;
  if(!form||!grid||!legacyPreview)return;

  const definitions=[
    ['source','1. Source & grayscale','Choose the image and control color-to-gray conversion.'],
    ['threshold','2. Black & white','Control foreground selection, thresholding, and cleanup.'],
    ['edges','3. Edge extraction','Control how contours are detected from the thresholded image.'],
    ['style','4. Style & vectorization','Choose the drawing recipe and control its geometry limits.'],
    ['machine','5. Machine & export','Set Z motion, bed sizing, and export behavior.']
  ];
  grid.className='studio-step-shell';
  form.classList.add('step-controls');
  const rail=document.createElement('nav');
  rail.className='step-rail';
  rail.setAttribute('aria-label','Processing steps');
  grid.insertBefore(rail,form);
  const panels={};
  for(const [id,title,description] of definitions){
    const tab=document.createElement('button');
    tab.type='button';tab.className='process-tab';tab.dataset.step=id;
    tab.innerHTML='<strong>'+title+'</strong><span>'+description+'</span>';
    rail.appendChild(tab);
    const panel=document.createElement('section');
    panel.className='step-panel';panel.dataset.stepPanel=id;
    panel.innerHTML='<h2>'+title+'</h2><p>'+description+'</p>';
    form.appendChild(panel);panels[id]=panel;
  }
  const directBlock=(selector)=>{
    const control=document.querySelector(selector);
    if(!control)return null;
    const parent=control.parentElement;
    if(parent&&parent.parentElement===form)return parent;
    if(parent===form){
      const label=control.previousElementSibling&&control.previousElementSibling.tagName==='LABEL'?control.previousElementSibling:null;
      const block=document.createElement('div');block.className='control-block';
      if(label){form.insertBefore(block,label);block.append(label,control);}else{form.insertBefore(block,control);block.append(control);}
      return block;
    }
    return null;
  };
  const moveField=(selector,step)=>{const node=directBlock(selector);if(node&&!panels[step].contains(node))panels[step].appendChild(node);};
  const moveGroup=(id,step)=>{const node=document.getElementById(id);const wrapper=node&&node.closest('.control-section');const target=wrapper||node;if(target&&!panels[step].contains(target))panels[step].appendChild(target);};

  ['#file','#grayMode','[name="background_mode"]'].forEach(selector=>moveField(selector,'source'));
  moveGroup('grayMode','source');
  ['#thresholdMode'].forEach(selector=>moveField(selector,'threshold'));
  moveGroup('thresholdMode','threshold');
  moveField('[name="edge_method"]','edges');
  const moveGroupSelector=(selector,step)=>{const node=document.querySelector(selector);const wrapper=node&&node.closest('.control-section');const target=wrapper||node;if(target&&!panels[step].contains(target))panels[step].appendChild(target);};
  moveGroupSelector('[name="edge_method"]','edges');
  ['#mode','#style','[name="quality"]','[name="detail"]'].forEach(selector=>moveField(selector,'style'));
  ['lineArtAdvanced','shadingAdvanced','geometryLimits'].forEach(id=>moveGroup(id,'style'));
  ['[name="pen_tip_mm"]','[name="z_up_mm"]','[name="z_down_mm"]','[name="air_plot"]','[name="home_before_plot"]'].forEach(selector=>moveField(selector,'machine'));
  moveGroup('finalSize','machine');
  ['#generate','#status','#selectedStyle'].forEach(selector=>moveField(selector,'machine'));
  Object.values(panels).forEach(panel=>panel.querySelectorAll('.control-section').forEach(section=>section.open=true));
  const advancedToggle=document.getElementById('advancedToggle');
  if(advancedToggle)advancedToggle.hidden=true;
  const advanced=document.getElementById('advanced');
  if(advanced)advanced.hidden=true;

  legacyPreview.classList.add('legacy-preview');
  const visuals=document.createElement('section');
  visuals.className='step-visuals';
  grid.appendChild(visuals);
  const content=(id)=>document.getElementById(id);
  const makePane=(title,id)=>{const pane=document.createElement('div');pane.className='pane';pane.innerHTML='<h3>'+title+'</h3>';const node=content(id);if(node)pane.appendChild(node);return pane;};
  const makeVisual=(id,title,subtitle,beforeTitle,beforeId,afterTitle,afterId)=>{
    const visual=document.createElement('section');visual.className='step-visual';visual.dataset.stepVisual=id;
    visual.innerHTML='<h2>'+title+'</h2><div class="visual-subtitle">'+subtitle+'</div>';
    const compare=document.createElement('div');compare.className='before-after';
    compare.appendChild(makePane(beforeTitle,beforeId));compare.appendChild(makePane(afterTitle,afterId));
    visual.appendChild(compare);visuals.appendChild(visual);return visual;
  };
  makeVisual('source','Source & grayscale','See the original image beside the current grayscale result.','Before · original','sourcePreview','After · grayscale','corrected');
  const sourceVisual=visuals.lastElementChild;
  const grayNote=document.createElement('div');grayNote.className='hint';grayNote.textContent='Quick raster preview is shown above the corrected grayscale when an image is selected.';sourceVisual.querySelector('.before-after .pane:last-child').appendChild(content('rasterPreview'));sourceVisual.querySelector('.before-after .pane:last-child').appendChild(grayNote);
  makeVisual('threshold','Black & white','See grayscale input beside the thresholded foreground mask.','Before · grayscale','corrected','After · black & white','mask');
  makeVisual('edges','Edge extraction','See the threshold mask beside the selected contour map.','Before · black & white','mask','After · edges','edges');
  makeVisual('style','Style & vectorization','See the detected input beside the generated artistic paths.','Before · detected input','edges','After · artistic paths','preview');
  const machineVisual=document.createElement('section');machineVisual.className='step-visual';machineVisual.dataset.stepVisual='machine';machineVisual.innerHTML='<h2>Machine & export</h2><div class="visual-subtitle">Review the generated paths beside the final machine-output view.</div>';
  const machineCompare=document.createElement('div');machineCompare.className='before-after';
  const machineBefore=document.createElement('div');machineBefore.className='pane';machineBefore.innerHTML='<h3>Before · artistic paths</h3>';machineBefore.insertAdjacentHTML('beforeend','<div id="machineInput" class="placeholder">Generate a drawing to see artistic paths.</div>');
  const machineAfter=document.createElement('div');machineAfter.className='pane';machineAfter.innerHTML='<h3>After · machine output</h3>';machineAfter.insertAdjacentHTML('beforeend','<div id="machinePreview" class="placeholder">Generate a drawing to see machine output.</div>');
  machineCompare.append(machineBefore,machineAfter);machineVisual.appendChild(machineCompare);visuals.appendChild(machineVisual);
  const machinePreview=document.getElementById('machinePreview');
  const machineInput=document.getElementById('machineInput');
  const preview=content('preview');
  const mirror=new MutationObserver(()=>{machinePreview.className=preview.className;machinePreview.innerHTML=preview.innerHTML;machineInput.className=preview.className;machineInput.innerHTML=preview.innerHTML;});
  mirror.observe(preview,{childList:true,subtree:true,attributes:true,characterData:true});
  const select=(id)=>{document.querySelectorAll('.process-tab').forEach(tab=>{const active=tab.dataset.step===id;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',active?'true':'false');});Object.values(panels).forEach(panel=>panel.classList.toggle('active',panel.dataset.stepPanel===id));document.querySelectorAll('.step-visual').forEach(visual=>visual.classList.toggle('active',visual.dataset.stepVisual===id));};
  rail.querySelectorAll('.process-tab').forEach(tab=>tab.addEventListener('click',()=>select(tab.dataset.step)));
  select('source');
})();
</script>
'''
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
    html = html.replace('</body></html>', step_editor + floating + '</body></html>')
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
            plot_stroke_limit=_int(form, "plot_stroke_limit", 5_000),
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

        finalization_started = time.perf_counter()
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
        final_motion = motion_metrics(final, pen)

        result["polylines"] = final
        result["preview_svg"] = preview
        result["gcode"] = gcode
        metadata = dict(result.get("metadata", {}))
        metadata.update(size_meta)
        metadata["studio_schema"] = "printrbot-studio2/v3"
        metadata["requested_quality"] = requested_quality
        metadata["effective_quality"] = effective_quality
        metadata["auto_interactive_preview"] = mode == "auto" and requested_quality != effective_quality
        metadata["estimated_print_time_seconds"] = round(final_motion.estimated_seconds, 2)
        metadata["estimated_print_time_minutes"] = round(final_motion.estimated_seconds / 60.0, 2)
        metadata["estimated_print_time"] = f"{int(final_motion.estimated_seconds // 60)}m {int(final_motion.estimated_seconds % 60):02d}s"
        stage_seconds = dict(metadata.get("studio_stage_seconds", {}))
        stage_seconds["final_size_and_export"] = round(time.perf_counter() - finalization_started, 4)
        metadata["studio_stage_seconds"] = stage_seconds
        metadata["studio_slowest_stage"] = max(stage_seconds, key=stage_seconds.get)
        result["metadata"] = metadata
        return result
    except HTTPException:
        raise
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc

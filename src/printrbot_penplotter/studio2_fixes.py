"""Runtime integration fixes for Studio 2.

This module keeps Studio-specific behavior cohesive without weakening the shared
machine safety contract. It fixes three integration issues:

1. Studio expert geometry limits must propagate through vector cleanup and
   shading outlines instead of being stopped by legacy 20k defaults.
2. Raster/style geometry uses image coordinates (Y down), while machine space
   uses Cartesian coordinates (Y up). Studio mirrors image geometry once before
   page placement so the physical plot and exact preview match the source image.
3. Studio keeps Generate / Save SVG / Save G-code actions visible while scrolling.
"""

from __future__ import annotations

from dataclasses import replace
from types import ModuleType

from . import fast_cleanup, line_art, pen_shading
from .geometry import MAX_POINTS, MAX_STROKES
from .line_art import LineArtConfig
from .models import Polylines
from .vector_cleanup import VectorCleanupConfig

_APPLIED = False


def _patch_large_job_limits() -> None:
    """Make legacy cleanup defaults act as hard guards inside Studio style rendering."""

    original_cleanup = fast_cleanup.cleanup_polylines_fast

    def studio_cleanup(polylines: Polylines, config: VectorCleanupConfig | None = None):
        cfg = config or VectorCleanupConfig()
        if cfg.max_strokes < MAX_STROKES or cfg.max_points < MAX_POINTS:
            cfg = replace(
                cfg,
                max_strokes=max(cfg.max_strokes, MAX_STROKES),
                max_points=max(cfg.max_points, MAX_POINTS),
            )
        return original_cleanup(polylines, cfg)

    # line_art imported this function directly, so patch that module reference.
    line_art.cleanup_polylines_fast = studio_cleanup

    def studio_outline(analysis, config, style: str | None = None):
        if not config.include_outline:
            return []
        result = line_art.render_line_art_from_analysis(
            analysis,
            LineArtConfig(
                style=style or config.outline_style,
                max_output_strokes=config.max_output_strokes,
                max_output_points=config.max_output_points,
            ),
        )
        return [stroke[:] for stroke in result.polylines]

    # Shading outlines previously recreated LineArtConfig with the old 20k
    # default, which defeated Studio's expert bypass.
    pen_shading._outline = studio_outline


def _patch_image_orientation(studio2: ModuleType) -> None:
    """Convert image-space Y-down geometry to machine-space Y-up exactly once."""

    original_place = studio2.place_on_page

    def place_image_geometry(polylines, page, layout=None, machine=None):
        drawable = [line for line in polylines if len(line) >= 2]
        if not drawable:
            return original_place(polylines, page, layout, machine)
        ys = [point[1] for line in drawable for point in line]
        min_y = min(ys)
        max_y = max(ys)
        axis = min_y + max_y
        upright = [[(x, axis - y) for x, y in line] for line in polylines]
        return original_place(upright, page, layout, machine)

    studio2.place_on_page = place_image_geometry


def _patch_studio_html(studio2: ModuleType) -> None:
    """Add always-visible render/save controls with native Save As support."""

    marker = "studio2FloatingActions"
    if marker in studio2.STUDIO2_HTML:
        return

    floating = r'''
<div id="studio2FloatingActions" style="position:fixed;right:18px;bottom:18px;z-index:9999;display:flex;gap:8px;align-items:center;padding:10px;background:rgba(255,255,255,.96);border:1px solid #cfcfcf;border-radius:12px;box-shadow:0 8px 28px rgba(0,0,0,.18);backdrop-filter:blur(8px)">
  <button id="floatingGenerate" type="button" style="width:auto;margin:0;padding:10px 16px">Generate drawing</button>
  <button id="floatingSaveSvg" type="button" disabled style="width:auto;margin:0;padding:10px 16px">Save SVG</button>
  <button id="floatingSaveGcode" type="button" disabled style="width:auto;margin:0;padding:10px 16px">Save G-code</button>
</div>
<script>
(()=>{
  const nativeFetch=window.fetch.bind(window);
  const floatingGenerate=document.getElementById('floatingGenerate');
  const saveSvg=document.getElementById('floatingSaveSvg');
  const saveGcode=document.getElementById('floatingSaveGcode');
  const mainGenerate=document.getElementById('generate');
  const fileInput=document.getElementById('file');
  window.__studio2LastRender=null;

  function baseName(){
    const name=(fileInput&&fileInput.files&&fileInput.files[0]&&fileInput.files[0].name)||'printrbot-drawing';
    return name.replace(/\.[^.]+$/,'')||'printrbot-drawing';
  }

  async function saveText(text,suggestedName,mime,description,extension){
    if(window.showSaveFilePicker){
      const handle=await window.showSaveFilePicker({
        suggestedName,
        types:[{description,accept:{[mime]:[extension]}}]
      });
      const writable=await handle.createWritable();
      await writable.write(text);
      await writable.close();
      return;
    }
    const blob=new Blob([text],{type:mime});
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a');
    a.href=url;a.download=suggestedName;document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

  window.fetch=async(...args)=>{
    const response=await nativeFetch(...args);
    try{
      const target=String(args[0]&&args[0].url?args[0].url:args[0]);
      if(target.includes('/api/studio2/render')&&response.ok){
        const data=await response.clone().json();
        window.__studio2LastRender=data;
        saveSvg.disabled=!data.preview_svg;
        saveGcode.disabled=!data.gcode;
      }
    }catch(_err){}
    return response;
  };

  floatingGenerate.addEventListener('click',()=>mainGenerate&&mainGenerate.click());
  saveSvg.addEventListener('click',async()=>{
    const data=window.__studio2LastRender;if(!data||!data.preview_svg)return;
    try{await saveText(data.preview_svg,baseName()+'.svg','image/svg+xml','SVG drawing','.svg');}catch(err){if(err&&err.name!=='AbortError')alert(String(err));}
  });
  saveGcode.addEventListener('click',async()=>{
    const data=window.__studio2LastRender;if(!data||!data.gcode)return;
    try{await saveText(data.gcode,baseName()+'.gcode','text/plain','G-code','.gcode');}catch(err){if(err&&err.name!=='AbortError')alert(String(err));}
  });

  setInterval(()=>{if(mainGenerate)floatingGenerate.disabled=mainGenerate.disabled;},150);
})();
</script>
'''
    studio2.STUDIO2_HTML = studio2.STUDIO2_HTML.replace("</body>", floating + "\n</body>")


def apply_studio2_fixes(studio2: ModuleType) -> None:
    global _APPLIED
    if _APPLIED:
        return
    _patch_large_job_limits()
    _patch_image_orientation(studio2)
    _patch_studio_html(studio2)
    _APPLIED = True

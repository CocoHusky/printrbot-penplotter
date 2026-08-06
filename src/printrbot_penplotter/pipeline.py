"""End-to-end rendering pipeline."""

from __future__ import annotations

from pathlib import Path

from .gcode import polylines_to_gcode
from .geometry import fit_to_page, preview_svg, simplify_polylines
from .inputs import svg_to_polylines, text_to_polylines
from .models import PageConfig, PenConfig, RenderedJob, StyleConfig


def render_text_job(
    text: str,
    *,
    page: PageConfig | None = None,
    pen: PenConfig | None = None,
    style: StyleConfig | None = None,
    simplify_tolerance_mm: float = 0.04,
) -> RenderedJob:
    page = page or PageConfig()
    pen = pen or PenConfig()
    style = style or StyleConfig.for_preset("human")

    raw = text_to_polylines(text, style)
    fitted = fit_to_page(raw, page)
    simplified = simplify_polylines(fitted, simplify_tolerance_mm)
    return RenderedJob(
        polylines=simplified,
        gcode=polylines_to_gcode(simplified, page, pen, title="Text plot"),
        preview_svg=preview_svg(simplified, page),
        metadata={
            "input_type": "text",
            "characters": len(text),
            "strokes": len(simplified),
            "preset": style.preset,
            "seed": style.seed,
        },
    )


def render_svg_job(
    source: str | Path,
    *,
    page: PageConfig | None = None,
    pen: PenConfig | None = None,
    simplify_tolerance_mm: float = 0.04,
) -> RenderedJob:
    page = page or PageConfig()
    pen = pen or PenConfig()

    raw = svg_to_polylines(source)
    fitted = fit_to_page(raw, page)
    simplified = simplify_polylines(fitted, simplify_tolerance_mm)
    return RenderedJob(
        polylines=simplified,
        gcode=polylines_to_gcode(simplified, page, pen, title="SVG plot"),
        preview_svg=preview_svg(simplified, page),
        metadata={
            "input_type": "svg",
            "source": str(source),
            "strokes": len(simplified),
        },
    )


def write_job(job: RenderedJob, gcode_path: str | Path, preview_path: str | Path) -> None:
    gcode_target = Path(gcode_path)
    preview_target = Path(preview_path)
    gcode_target.parent.mkdir(parents=True, exist_ok=True)
    preview_target.parent.mkdir(parents=True, exist_ok=True)
    gcode_target.write_text(job.gcode, encoding="utf-8")
    preview_target.write_text(job.preview_svg, encoding="utf-8")

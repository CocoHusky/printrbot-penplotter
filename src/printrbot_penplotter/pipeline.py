"""End-to-end rendering pipeline."""

from __future__ import annotations

from pathlib import Path

from .calibration import square_cross_pattern
from .gcode import polylines_to_gcode
from .geometry import bounds, place_on_page, preview_svg, simplify_polylines
from .inputs import svg_to_polylines, text_to_polylines_with_metadata
from .models import (
    LayoutConfig,
    MachineConfig,
    PageConfig,
    PenConfig,
    Polylines,
    RenderedJob,
    StyleConfig,
)


def _finish_job(
    raw: Polylines,
    *,
    title: str,
    input_type: str,
    page: PageConfig,
    machine: MachineConfig,
    pen: PenConfig,
    layout: LayoutConfig,
    simplify_tolerance_mm: float,
    metadata: dict[str, object] | None = None,
) -> RenderedJob:
    placed = place_on_page(raw, page, layout, machine)
    simplified = simplify_polylines(placed, simplify_tolerance_mm)
    min_x, min_y, max_x, max_y = bounds(simplified)
    complete_metadata: dict[str, object] = {
        "input_type": input_type,
        "strokes": len(simplified),
        "width_mm": round(max_x - min_x, 3),
        "height_mm": round(max_y - min_y, 3),
        "minimum_x_mm": round(min_x, 3),
        "minimum_y_mm": round(min_y, 3),
        "air_plot": pen.air_plot,
        "fit_mode": layout.fit_mode,
    }
    if metadata:
        complete_metadata.update(metadata)

    return RenderedJob(
        polylines=simplified,
        gcode=polylines_to_gcode(
            simplified,
            page,
            pen,
            machine,
            title=title,
        ),
        preview_svg=preview_svg(simplified, page, machine),
        metadata=complete_metadata,
    )


def render_text_job(
    text: str,
    *,
    page: PageConfig | None = None,
    machine: MachineConfig | None = None,
    pen: PenConfig | None = None,
    style: StyleConfig | None = None,
    layout: LayoutConfig | None = None,
    simplify_tolerance_mm: float = 0.04,
) -> RenderedJob:
    page = page or PageConfig()
    machine = machine or MachineConfig()
    pen = pen or PenConfig()
    style = style or StyleConfig.for_preset("human")
    layout = layout or LayoutConfig(fit_mode="downscale")

    raw, input_metadata = text_to_polylines_with_metadata(text, style)
    input_metadata.update(
        {
            "characters": len(text),
            "preset": style.preset,
            "seed": style.seed,
            "requested_font_size_mm": style.font_size_mm,
            "variant_mode": style.variant_mode,
            "connect_letters": style.connect_letters,
            "wrap_width_mm": style.wrap_width_mm,
            "stroke_order": style.stroke_order,
        }
    )
    return _finish_job(
        raw,
        title="Text plot",
        input_type="text",
        page=page,
        machine=machine,
        pen=pen,
        layout=layout,
        simplify_tolerance_mm=simplify_tolerance_mm,
        metadata=input_metadata,
    )


def render_svg_job(
    source: str | Path,
    *,
    page: PageConfig | None = None,
    machine: MachineConfig | None = None,
    pen: PenConfig | None = None,
    layout: LayoutConfig | None = None,
    simplify_tolerance_mm: float = 0.04,
) -> RenderedJob:
    page = page or PageConfig()
    machine = machine or MachineConfig()
    pen = pen or PenConfig()
    layout = layout or LayoutConfig(fit_mode="fit")

    raw = svg_to_polylines(source)
    return _finish_job(
        raw,
        title="SVG plot",
        input_type="svg",
        page=page,
        machine=machine,
        pen=pen,
        layout=layout,
        simplify_tolerance_mm=simplify_tolerance_mm,
        metadata={"source": str(source)},
    )


def render_calibration_job(
    *,
    size_mm: float = 10.0,
    page: PageConfig | None = None,
    machine: MachineConfig | None = None,
    pen: PenConfig | None = None,
    layout: LayoutConfig | None = None,
) -> RenderedJob:
    """Create the known-size Release 0.2 calibration job."""

    page = page or PageConfig()
    machine = machine or MachineConfig()
    pen = pen or PenConfig(air_plot=True)
    layout = layout or LayoutConfig(fit_mode="none")
    raw = square_cross_pattern(size_mm=size_mm)
    return _finish_job(
        raw,
        title=f"{size_mm:g} mm calibration pattern",
        input_type="calibration",
        page=page,
        machine=machine,
        pen=pen,
        layout=layout,
        simplify_tolerance_mm=0.0,
        metadata={"nominal_square_size_mm": size_mm},
    )


def write_job(job: RenderedJob, gcode_path: str | Path, preview_path: str | Path) -> None:
    gcode_target = Path(gcode_path)
    preview_target = Path(preview_path)
    gcode_target.parent.mkdir(parents=True, exist_ok=True)
    preview_target.parent.mkdir(parents=True, exist_ok=True)
    gcode_target.write_text(job.gcode, encoding="utf-8")
    preview_target.write_text(job.preview_svg, encoding="utf-8")

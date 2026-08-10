"""End-to-end rendering pipeline."""

from __future__ import annotations

from pathlib import Path

from .calibration import square_cross_pattern
from .gcode import polylines_to_gcode
from .geometry import bounds, place_on_page, preview_svg, simplify_polylines
from .inputs import (
    raster_to_polylines_with_metadata,
    svg_to_polylines,
    text_to_polylines_with_metadata,
)
from .models import (
    LayoutConfig,
    MachineConfig,
    PageConfig,
    PenConfig,
    Polylines,
    RenderedJob,
    StyleConfig,
)
from .optimize import MotionConfig, optimize_motion
from .raster import RasterTraceConfig


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
    motion: MotionConfig | None = None,
    metadata: dict[str, object] | None = None,
) -> RenderedJob:
    placed = place_on_page(raw, page, layout, machine)
    simplified = simplify_polylines(placed, simplify_tolerance_mm)
    motion_plan = optimize_motion(simplified, motion or MotionConfig(), pen=pen)
    final = motion_plan.polylines
    min_x, min_y, max_x, max_y = bounds(final)
    complete_metadata: dict[str, object] = {
        "input_type": input_type,
        "strokes": len(final),
        "width_mm": round(max_x - min_x, 3),
        "height_mm": round(max_y - min_y, 3),
        "minimum_x_mm": round(min_x, 3),
        "minimum_y_mm": round(min_y, 3),
        "air_plot": pen.air_plot,
        "fit_mode": layout.fit_mode,
        "corner_feed_mm_min": pen.corner_feed_mm_min,
        "corner_angle_deg": pen.corner_angle_deg,
    }
    complete_metadata.update(motion_plan.metadata())
    if metadata:
        complete_metadata.update(metadata)

    return RenderedJob(
        polylines=final,
        gcode=polylines_to_gcode(final, page, pen, machine, title=title),
        preview_svg=preview_svg(final, page, machine),
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
    motion: MotionConfig | None = None,
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
            "line_spacing": style.line_spacing,
            "letter_spacing_mm": style.letter_spacing_mm,
            "word_spacing_em": style.word_spacing_em,
            "slant_deg": style.slant_deg,
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
        motion=motion,
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
    motion: MotionConfig | None = None,
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
        motion=motion,
        simplify_tolerance_mm=simplify_tolerance_mm,
        metadata={"source": str(source)},
    )


def _render_raster_job(
    source: str | Path,
    *,
    input_type: str,
    title: str,
    trace: RasterTraceConfig,
    page: PageConfig | None,
    machine: MachineConfig | None,
    pen: PenConfig | None,
    layout: LayoutConfig | None,
    motion: MotionConfig | None,
    simplify_tolerance_mm: float,
    metadata: dict[str, object] | None = None,
) -> RenderedJob:
    page = page or PageConfig()
    machine = machine or MachineConfig()
    pen = pen or PenConfig()
    layout = layout or LayoutConfig(fit_mode="fit")

    raw, trace_metadata = raster_to_polylines_with_metadata(source, trace)
    if metadata:
        trace_metadata.update(metadata)
    return _finish_job(
        raw,
        title=title,
        input_type=input_type,
        page=page,
        machine=machine,
        pen=pen,
        layout=layout,
        motion=motion,
        simplify_tolerance_mm=simplify_tolerance_mm,
        metadata=trace_metadata,
    )


def render_image_job(
    source: str | Path,
    *,
    trace: RasterTraceConfig | None = None,
    page: PageConfig | None = None,
    machine: MachineConfig | None = None,
    pen: PenConfig | None = None,
    layout: LayoutConfig | None = None,
    motion: MotionConfig | None = None,
    simplify_tolerance_mm: float = 0.04,
) -> RenderedJob:
    """Trace a raster image as contours or centerlines and render one plot job."""

    trace = trace or RasterTraceConfig(mode="contour", min_component_px=8, simplify_px=1.0)
    return _render_raster_job(
        source,
        input_type="image",
        title="Raster image plot",
        trace=trace,
        page=page,
        machine=machine,
        pen=pen,
        layout=layout,
        motion=motion,
        simplify_tolerance_mm=simplify_tolerance_mm,
    )


def render_handwriting_job(
    source: str | Path,
    *,
    trace: RasterTraceConfig | None = None,
    page: PageConfig | None = None,
    machine: MachineConfig | None = None,
    pen: PenConfig | None = None,
    layout: LayoutConfig | None = None,
    motion: MotionConfig | None = None,
    simplify_tolerance_mm: float = 0.04,
) -> RenderedJob:
    """Trace photographed or scanned handwriting without recognizing/retyping it."""

    trace = trace or RasterTraceConfig(
        mode="centerline",
        blur_radius_px=0.3,
        min_component_px=4,
        simplify_px=0.6,
    )
    if trace.mode != "centerline":
        raise ValueError("Handwriting input uses centerline tracing; trace.mode must be centerline.")
    return _render_raster_job(
        source,
        input_type="handwriting",
        title="Handwriting trace plot",
        trace=trace,
        page=page,
        machine=machine,
        pen=pen,
        layout=layout,
        motion=motion,
        simplify_tolerance_mm=simplify_tolerance_mm,
        metadata={"handwriting_recognition": False},
    )


def render_calibration_job(
    *,
    size_mm: float = 10.0,
    page: PageConfig | None = None,
    machine: MachineConfig | None = None,
    pen: PenConfig | None = None,
    layout: LayoutConfig | None = None,
) -> RenderedJob:
    """Create the known-size Release 0.2 calibration job.

    Calibration intentionally bypasses Release 0.6 geometry optimization so a
    nominal test pattern cannot be changed by route joining/smoothing settings.
    """

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
        motion=MotionConfig(route_mode="authored"),
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

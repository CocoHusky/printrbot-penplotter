"""Printrbot pen-plotter software."""

from .esp32_client import BridgeError, Esp32BridgeClient
from .models import (
    LayoutConfig,
    MachineConfig,
    PageConfig,
    PenConfig,
    RenderedJob,
    StyleConfig,
)
from .optimize import optimize_stroke_order, pen_up_distance
from .pipeline import (
    render_calibration_job,
    render_handwriting_job,
    render_image_job,
    render_svg_job,
    render_text_job,
)
from .raster import RasterTraceConfig, RasterTraceResult, editable_trace_svg, trace_raster
from .stroke_fonts import (
    GlyphVariant,
    StrokeFont,
    available_stroke_fonts,
    get_builtin_stroke_font,
    load_stroke_font,
)
from .writing import WritingResult, stroke_text_to_polylines

__all__ = [
    "BridgeError",
    "Esp32BridgeClient",
    "GlyphVariant",
    "LayoutConfig",
    "MachineConfig",
    "PageConfig",
    "PenConfig",
    "RasterTraceConfig",
    "RasterTraceResult",
    "RenderedJob",
    "StrokeFont",
    "StyleConfig",
    "WritingResult",
    "available_stroke_fonts",
    "editable_trace_svg",
    "get_builtin_stroke_font",
    "load_stroke_font",
    "optimize_stroke_order",
    "pen_up_distance",
    "render_calibration_job",
    "render_handwriting_job",
    "render_image_job",
    "render_svg_job",
    "render_text_job",
    "stroke_text_to_polylines",
    "trace_raster",
]

__version__ = "0.5.0"

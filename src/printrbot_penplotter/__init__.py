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
from .neural_handwriting import NeuralWritingConfig, generate_neural_trajectories
from .optimize import (
    MotionConfig,
    MotionMetrics,
    MotionPlan,
    draw_distance,
    join_nearby_strokes,
    motion_metrics,
    optimize_motion,
    optimize_stroke_order,
    pen_up_distance,
    rdp_simplify,
    resample_polyline,
    smooth_polyline,
    two_opt_stroke_order,
)
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
    "MotionConfig",
    "MotionMetrics",
    "MotionPlan",
    "NeuralWritingConfig",
    "PageConfig",
    "PenConfig",
    "RasterTraceConfig",
    "RasterTraceResult",
    "RenderedJob",
    "StrokeFont",
    "StyleConfig",
    "WritingResult",
    "available_stroke_fonts",
    "draw_distance",
    "editable_trace_svg",
    "get_builtin_stroke_font",
    "generate_neural_trajectories",
    "join_nearby_strokes",
    "load_stroke_font",
    "motion_metrics",
    "optimize_motion",
    "optimize_stroke_order",
    "pen_up_distance",
    "rdp_simplify",
    "render_calibration_job",
    "render_handwriting_job",
    "render_image_job",
    "render_svg_job",
    "render_text_job",
    "resample_polyline",
    "smooth_polyline",
    "stroke_text_to_polylines",
    "trace_raster",
    "two_opt_stroke_order",
]

__version__ = "1.0.7"

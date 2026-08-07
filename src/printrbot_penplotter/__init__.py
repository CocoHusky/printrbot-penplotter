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
from .pipeline import render_calibration_job, render_svg_job, render_text_job
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
    "RenderedJob",
    "StrokeFont",
    "StyleConfig",
    "WritingResult",
    "available_stroke_fonts",
    "get_builtin_stroke_font",
    "load_stroke_font",
    "optimize_stroke_order",
    "pen_up_distance",
    "render_calibration_job",
    "render_svg_job",
    "render_text_job",
    "stroke_text_to_polylines",
]

__version__ = "0.4.0"

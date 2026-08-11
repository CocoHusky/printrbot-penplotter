"""Runtime integration fixes for Studio 2.

This module keeps Studio-specific behavior cohesive without weakening the shared
machine safety contract. It fixes three integration issues:

1. Studio expert geometry limits must propagate through vector cleanup and
   shading outlines instead of being stopped by legacy 20k defaults.
2. Raster/style geometry uses image coordinates (Y down), while machine space
   uses Cartesian coordinates (Y up). Studio mirrors image geometry once before
   page placement so the physical plot and exact preview match the source image.
"""

from __future__ import annotations

from dataclasses import replace
from types import ModuleType

from . import fast_cleanup, line_art, pen_shading
from .geometry import MAX_POINTS, MAX_STROKES
from .line_art import LineArtConfig
from .models import Polylines
from .vector_cleanup import VectorCleanupConfig

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

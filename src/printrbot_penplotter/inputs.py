"""Input adapters that turn text, vector art, and raster sources into polylines."""

from __future__ import annotations

import math
import random
from pathlib import Path

from .geometry import rotate_scale_translate
from .models import Polylines, StyleConfig
from .raster import RasterTraceConfig, trace_raster
from .writing import stroke_text_to_polylines

POINTS_PER_INCH = 72.0
MM_PER_INCH = 25.4
POINTS_TO_MM = MM_PER_INCH / POINTS_PER_INCH


def outline_text_to_polylines(text: str, style: StyleConfig) -> Polylines:
    """Convert conventional font outlines to millimeter-scale polylines.

    This compatibility engine traces the edges of filled TTF/OTF glyphs. It is
    useful for outlined lettering and logos, but the native stroke engine is the
    preferred path for handwriting because it draws each centerline once.
    """

    style.validate()
    if not text:
        raise ValueError("Text input cannot be empty.")
    if style.font_path is not None and not Path(style.font_path).is_file():
        raise FileNotFoundError(f"Font file not found: {style.font_path}")

    try:
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib.font_manager import FontProperties
        from matplotlib.textpath import TextPath, TextToPath
    except ImportError as exc:  # pragma: no cover - dependency error path
        raise RuntimeError("Outline text rendering requires matplotlib.") from exc

    font_size_points = style.font_size_mm / POINTS_TO_MM
    font = FontProperties(
        family=style.font_family,
        fname=style.font_path,
        size=font_size_points,
    )
    metrics = TextToPath()
    rng = random.Random(style.seed)

    lines: Polylines = []
    cursor_x_mm = 0.0
    cursor_y_mm = 0.0
    line_height_mm = style.font_size_mm * style.line_spacing

    for character in text:
        if character == "\n":
            cursor_x_mm = 0.0
            cursor_y_mm -= line_height_mm
            continue

        width_points, _, _ = metrics.get_text_width_height_descent(character, font, False)
        advance_mm = max(float(width_points) * POINTS_TO_MM, style.font_size_mm * 0.28)

        if character.isspace():
            cursor_x_mm += advance_mm + style.letter_spacing_mm
            continue

        glyph = TextPath((0.0, 0.0), character, prop=font, usetex=False)
        polygons = glyph.to_polygons(closed_only=False)

        rotation = rng.uniform(-style.rotation_jitter_deg, style.rotation_jitter_deg)
        baseline = rng.uniform(-style.baseline_jitter_mm, style.baseline_jitter_mm)
        x_jitter = rng.uniform(-style.x_jitter_mm, style.x_jitter_mm)
        scale = 1.0 + rng.uniform(-style.scale_jitter, style.scale_jitter)

        for polygon in polygons:
            if len(polygon) < 2:
                continue
            line = [
                (
                    float(point[0]) * POINTS_TO_MM + cursor_x_mm,
                    float(point[1]) * POINTS_TO_MM + cursor_y_mm,
                )
                for point in polygon
            ]
            lines.append(
                rotate_scale_translate(
                    line,
                    origin=(cursor_x_mm, cursor_y_mm),
                    rotation_deg=rotation,
                    scale=scale,
                    translate_x=x_jitter,
                    translate_y=baseline,
                )
            )

        cursor_x_mm += advance_mm + style.letter_spacing_mm

    if not lines:
        raise ValueError("The supplied text produced no drawable glyphs.")
    return lines


def text_to_polylines_with_metadata(
    text: str,
    style: StyleConfig,
) -> tuple[Polylines, dict[str, object]]:
    """Render text and return engine-specific metadata."""

    if style.engine == "stroke":
        result = stroke_text_to_polylines(text, style)
        return result.polylines, {
            "text_engine": "stroke",
            "stroke_font": result.font_name,
            "glyphs": result.glyph_count,
            "connectors": result.connector_count,
            "lines": result.line_count,
            "glyph_variants": list(result.variant_labels),
            "unsupported_characters": list(result.unsupported_characters),
        }
    return outline_text_to_polylines(text, style), {
        "text_engine": "outline",
        "font_family": style.font_family,
        "font_path": style.font_path,
    }


def text_to_polylines(text: str, style: StyleConfig) -> Polylines:
    """Compatibility wrapper returning geometry only."""

    polylines, _ = text_to_polylines_with_metadata(text, style)
    return polylines


def svg_to_polylines(path: str | Path, curve_step: float = 0.01) -> Polylines:
    """Convert SVG paths into sampled polylines.

    SVG is the bridge format for sketches, handwriting traces, and image-vector
    conversion. SVG geometry is scaled and placed by the shared layout stage.
    """

    try:
        from svgpathtools import svg2paths2
    except ImportError as exc:  # pragma: no cover - dependency error path
        raise RuntimeError("SVG rendering requires svgpathtools.") from exc

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if curve_step <= 0 or curve_step > 1:
        raise ValueError("curve_step must be in the interval (0, 1].")

    paths, _, _ = svg2paths2(str(source))
    polylines: Polylines = []

    for path_item in paths:
        for subpath in path_item.continuous_subpaths():
            try:
                length = float(subpath.length(error=1e-4))
            except Exception:
                length = 100.0
            samples = max(8, min(4000, int(math.ceil(length / max(length * curve_step, 0.5)))))
            line = []
            for index in range(samples + 1):
                point = subpath.point(index / samples)
                line.append((float(point.real), float(-point.imag)))
            if len(line) >= 2:
                polylines.append(line)

    if not polylines:
        raise ValueError("The SVG contains no drawable path geometry.")
    return polylines


def raster_to_polylines_with_metadata(
    path: str | Path,
    config: RasterTraceConfig | None = None,
) -> tuple[Polylines, dict[str, object]]:
    """Trace a raster image and return the shared geometry plus trace metadata."""

    result = trace_raster(path, config)
    return result.polylines, result.metadata


def raster_to_polylines(
    path: str | Path,
    config: RasterTraceConfig | None = None,
) -> Polylines:
    """Compatibility wrapper returning raster trace geometry only."""

    polylines, _ = raster_to_polylines_with_metadata(path, config)
    return polylines

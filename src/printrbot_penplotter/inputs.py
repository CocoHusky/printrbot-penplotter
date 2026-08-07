"""Input adapters that turn text and vector art into polylines."""

from __future__ import annotations

import math
import random
from pathlib import Path

from .geometry import rotate_scale_translate
from .models import Polylines, StyleConfig

POINTS_PER_INCH = 72.0
MM_PER_INCH = 25.4
POINTS_TO_MM = MM_PER_INCH / POINTS_PER_INCH


def text_to_polylines(text: str, style: StyleConfig) -> Polylines:
    """Convert text glyph outlines to millimeter-scale polylines.

    Matplotlib defines font sizes and returned path coordinates in typographic
    points. The adapter converts those values into millimeters before the
    geometry reaches layout. Therefore ``font_size_mm`` now controls physical
    output size instead of merely acting as a relative value later expanded to
    fill the page.
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
        raise RuntimeError("Text rendering requires matplotlib.") from exc

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

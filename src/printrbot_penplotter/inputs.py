"""Input adapters that turn text and vector art into polylines."""

from __future__ import annotations

import math
import random
from pathlib import Path

from .geometry import rotate_scale_translate
from .models import Polylines, StyleConfig


def text_to_polylines(text: str, style: StyleConfig) -> Polylines:
    """Convert text glyph outlines to deterministic polylines.

    The output is deliberately font-agnostic. A user can point to any installed
    TTF/OTF file, including handwriting and cursive fonts. Per-character
    variation is deterministic for a given seed.
    """

    style.validate()
    if not text:
        raise ValueError("Text input cannot be empty.")

    try:
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib.font_manager import FontProperties
        from matplotlib.textpath import TextPath, TextToPath
    except ImportError as exc:  # pragma: no cover - dependency error path
        raise RuntimeError("Text rendering requires matplotlib.") from exc

    font = FontProperties(
        family=style.font_family,
        fname=style.font_path,
        size=style.font_size_mm,
    )
    metrics = TextToPath()
    rng = random.Random(style.seed)

    lines: Polylines = []
    cursor_x = 0.0
    cursor_y = 0.0
    line_height = style.font_size_mm * style.line_spacing

    for character in text:
        if character == "\n":
            cursor_x = 0.0
            cursor_y -= line_height
            continue

        width, _, _ = metrics.get_text_width_height_descent(character, font, False)
        advance = max(float(width), style.font_size_mm * 0.28)

        if character.isspace():
            cursor_x += advance + style.letter_spacing_mm
            continue

        glyph = TextPath((cursor_x, cursor_y), character, prop=font, usetex=False)
        polygons = glyph.to_polygons(closed_only=False)

        rotation = rng.uniform(-style.rotation_jitter_deg, style.rotation_jitter_deg)
        baseline = rng.uniform(-style.baseline_jitter_mm, style.baseline_jitter_mm)
        x_jitter = rng.uniform(-style.x_jitter_mm, style.x_jitter_mm)
        scale = 1.0 + rng.uniform(-style.scale_jitter, style.scale_jitter)

        for polygon in polygons:
            if len(polygon) < 2:
                continue
            line = [(float(point[0]), float(point[1])) for point in polygon]
            lines.append(
                rotate_scale_translate(
                    line,
                    origin=(cursor_x, cursor_y),
                    rotation_deg=rotation,
                    scale=scale,
                    translate_x=x_jitter,
                    translate_y=baseline,
                )
            )

        cursor_x += advance + style.letter_spacing_mm

    if not lines:
        raise ValueError("The supplied text produced no drawable glyphs.")
    return lines


def svg_to_polylines(path: str | Path, curve_step: float = 0.01) -> Polylines:
    """Convert SVG paths into sampled polylines.

    SVG is the bridge format for sketches, handwriting traces, and image-vector
    conversion. The geometry is normalized later, so SVG units do not need to
    be millimeters.
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

"""Input adapters that turn text, vector art, and raster sources into polylines."""

from __future__ import annotations

import math
import random
from pathlib import Path

from .geometry import rotate_scale_translate
from .centerline_fonts import text_to_centerline_polylines, text_to_mixed_centerlines
from .font_library import FONT_ALIASES, resolve_font_family
from .image_preprocess import ImagePreprocessConfig
from .image_understanding import ImageUnderstandingConfig
from .line_art import LineArtConfig, render_line_art
from .models import Polylines, StyleConfig
from .neural_handwriting import NeuralWritingConfig, generate_neural_trajectories
from .raster import RasterTraceConfig, trace_raster
from .vector_cleanup import VectorCleanupConfig, cleanup_polylines
from .writing import stroke_text_to_polylines

POINTS_PER_INCH = 72.0
MM_PER_INCH = 25.4
POINTS_TO_MM = MM_PER_INCH / POINTS_PER_INCH

# Matplotlib does not always see the macOS font aliases used in the UI (most
# notably PingFang). Keep the aliases here so a CJK selection resolves to a
# real installed font instead of silently falling back to DejaVu Sans.
def _resolve_outline_font(font_family: str, font_path: str | None, text: str):
    """Resolve a font without permitting silent glyph substitution.

    ``TextPath`` otherwise accepts a missing family and quietly draws the
    default font. That is especially dangerous for CJK text because the
    resulting geometry can be blank or replacement glyphs while the request
    still appears successful.
    """

    from matplotlib.font_manager import FontProperties, findfont
    from matplotlib.ft2font import FT2Font

    resolved_path = font_path
    if resolved_path is None:
        alias_path = FONT_ALIASES.get(font_family)
        if alias_path and Path(alias_path).is_file():
            resolved_path = alias_path
        else:
            try:
                resolved_path = resolve_font_family(font_family)
                if resolved_path is None:
                    raise ValueError(f"Typeface '{font_family}' is not installed.")
            except (OSError, ValueError) as exc:
                raise ValueError(
                    f"Typeface '{font_family}' is not installed. "
                    "Choose an installed typeface or install the requested font."
                ) from exc

    if not Path(resolved_path).is_file():
        raise FileNotFoundError(f"Font file not found: {resolved_path}")

    try:
        charmap = FT2Font(resolved_path).get_charmap()
    except Exception as exc:
        raise ValueError(f"Could not read typeface '{font_family}'.") from exc

    missing = sorted({character for character in text if not character.isspace() and ord(character) not in charmap})
    if missing:
        sample = " ".join(repr(character) for character in missing[:8])
        more = "" if len(missing) <= 8 else f" (+{len(missing) - 8} more)"
        raise ValueError(
            f"Typeface '{font_family}' cannot draw {sample}{more}. "
            "Choose a typeface that supports every character in the text."
        )
    return resolved_path


def outline_text_to_polylines(text: str, style: StyleConfig) -> Polylines:
    """Convert conventional font outlines to millimeter-scale polylines.

    This compatibility engine traces the edges of filled TTF/OTF glyphs. It is
    useful for outlined lettering and logos, but the native stroke engine is the
    preferred path for handwriting because it draws each centerline once.
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
        raise RuntimeError("Outline text rendering requires matplotlib.") from exc

    font_size_points = style.font_size_mm / POINTS_TO_MM
    resolved_font_path = _resolve_outline_font(style.font_family, style.font_path, text)
    font = FontProperties(
        family=style.font_family,
        fname=resolved_font_path,
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

    if style.writing_backend == "neural":
        return generate_neural_trajectories(
            text,
            config=NeuralWritingConfig(style=style.neural_style, bias=style.neural_bias),
        )
    has_cjk = any(
        0x3400 <= ord(character) <= 0x4DBF
        or 0x4E00 <= ord(character) <= 0x9FFF
        or 0x3040 <= ord(character) <= 0x30FF
        or 0xAC00 <= ord(character) <= 0xD7AF
        for character in text
    )
    if has_cjk:
        raise ValueError(
            "This lettering mode only supports the built-in stroke-font alphabet; "
            "CJK characters do not have a single-line font yet."
        )
    if style.experimental_outline_centerline:
        resolved_font_path = _resolve_outline_font(style.font_family, style.font_path, text)
        return outline_text_to_polylines(text, style), {
            "text_engine": "experimental-outline-centerline",
            "font_family": style.font_family,
            "font_path": resolved_font_path,
            "font_note": "Experimental outline conversion; not an authored single-line font.",
        }
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
    # ``outline`` is accepted only as a legacy request value. Never use it in
    # the product pipeline: all text must be emitted as centerline strokes.
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
    *,
    cleanup: VectorCleanupConfig | None = None,
) -> tuple[Polylines, dict[str, object]]:
    """Trace raster input and optionally apply Step 4 vector cleanup.

    Cleanup remains opt-in because smoothing, joining, pruning, and duplicate
    suppression can change physical ink geometry.  When enabled, the cleaned
    polylines become the single geometry source returned to the shared pipeline.
    """

    result = trace_raster(path, config)
    metadata = dict(result.metadata)
    if cleanup is None:
        metadata["vector_cleanup_schema"] = None
        return result.polylines, metadata
    cleaned = cleanup_polylines(result.polylines, cleanup)
    metadata.update(cleaned.metadata)
    return cleaned.polylines, metadata


def raster_to_polylines(
    path: str | Path,
    config: RasterTraceConfig | None = None,
    *,
    cleanup: VectorCleanupConfig | None = None,
) -> Polylines:
    """Compatibility wrapper returning raster trace geometry only."""

    polylines, _ = raster_to_polylines_with_metadata(path, config, cleanup=cleanup)
    return polylines


def styled_raster_to_polylines_with_metadata(
    path: str | Path,
    style: LineArtConfig | None = None,
    *,
    preprocess: ImagePreprocessConfig | None = None,
    understanding: ImageUnderstandingConfig | None = None,
) -> tuple[Polylines, dict[str, object]]:
    """Render raster input through the Step 5 line-art style library."""

    result = render_line_art(path, style, preprocess=preprocess, understanding=understanding)
    return result.polylines, result.metadata


def styled_raster_to_polylines(
    path: str | Path,
    style: LineArtConfig | None = None,
    *,
    preprocess: ImagePreprocessConfig | None = None,
    understanding: ImageUnderstandingConfig | None = None,
) -> Polylines:
    """Compatibility wrapper returning styled raster geometry only."""

    polylines, _ = styled_raster_to_polylines_with_metadata(
        path,
        style,
        preprocess=preprocess,
        understanding=understanding,
    )
    return polylines

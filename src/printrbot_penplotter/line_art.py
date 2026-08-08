"""Deterministic Step 5 line-art styles upstream of machine placement."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import numpy as np

from .geometry import validate_polylines
from .image_preprocess import ImagePreprocessConfig
from .image_understanding import ImageUnderstandingConfig, ImageUnderstandingResult, analyze_image
from .models import Polylines
from .raster import _skeletonize, _trace_contours, _trace_skeleton
from .vector_cleanup import VectorCleanupConfig, cleanup_polylines

LineArtStyle = Literal[
    "minimal_outline", "clean_outline", "detailed_outline", "continuous_contour",
    "one_line_art", "loose_sketch", "refined_pen_sketch", "pet_portrait",
    "portrait", "comic_ink", "architectural_pen", "technical_drawing",
    "silhouette", "topographic",
]
STYLE_NAMES: tuple[str, ...] = (
    "minimal_outline", "clean_outline", "detailed_outline", "continuous_contour",
    "one_line_art", "loose_sketch", "refined_pen_sketch", "pet_portrait",
    "portrait", "comic_ink", "architectural_pen", "technical_drawing",
    "silhouette", "topographic",
)


@dataclass(frozen=True)
class LineArtConfig:
    style: LineArtStyle = "refined_pen_sketch"
    max_skeleton_iterations: int = 256
    max_output_strokes: int = 20_000
    max_output_points: int = 2_000_000

    def validate(self) -> None:
        if self.style not in STYLE_NAMES:
            raise ValueError(f"Unsupported line-art style: {self.style}")
        if not isinstance(self.max_skeleton_iterations, int) or self.max_skeleton_iterations < 1:
            raise ValueError("max_skeleton_iterations must be positive.")
        if self.max_output_strokes < 1 or self.max_output_points < 2:
            raise ValueError("Line-art geometry limits must be positive.")


@dataclass(frozen=True)
class LineArtResult:
    polylines: Polylines
    metadata: dict[str, object]


def _boundary(mask: np.ndarray) -> np.ndarray:
    mask = mask.astype(bool)
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    eroded = np.ones_like(mask, dtype=bool)
    for row in range(3):
        for col in range(3):
            eroded &= padded[row:row + mask.shape[0], col:col + mask.shape[1]]
    return mask & ~eroded


def _tone_boundaries(labels: np.ndarray, delta: int = 1) -> np.ndarray:
    labels = labels.astype(np.int16)
    out = np.zeros(labels.shape, dtype=bool)
    horizontal = np.abs(labels[:, 1:] - labels[:, :-1]) >= delta
    vertical = np.abs(labels[1:, :] - labels[:-1, :]) >= delta
    out[:, 1:] |= horizontal
    out[:, :-1] |= horizontal
    out[1:, :] |= vertical
    out[:-1, :] |= vertical
    return out


def _dilate(mask: np.ndarray, passes: int = 1) -> np.ndarray:
    result = mask.astype(bool).copy()
    for _ in range(passes):
        padded = np.pad(result, 1, mode="constant")
        grown = np.zeros_like(result)
        for row in range(3):
            for col in range(3):
                grown |= padded[row:row + result.shape[0], col:col + result.shape[1]]
        result = grown
    return result


def _strokes(mask: np.ndarray, iterations: int) -> Polylines:
    if not np.any(mask):
        return []
    skeleton, _, _ = _skeletonize(mask.astype(bool), iterations)
    return _trace_skeleton(skeleton)


def _outlines(mask: np.ndarray) -> Polylines:
    return [] if not np.any(mask) else _trace_contours(mask.astype(bool))


def _combine(*groups: Polylines) -> Polylines:
    return [line[:] for group in groups for line in group if len(line) >= 2]


def _ordered_one_line(lines: Polylines) -> tuple[Polylines, int, float]:
    """Build a deterministic linear-time-ish artistic chain.

    Open strokes are normalized to lexicographically smaller start endpoints,
    sorted spatially, then connected in that order. This intentionally inserts
    visible bridge ink and reports it. Closed loops remain separate.
    """
    open_lines: Polylines = []
    closed_lines: Polylines = []
    for source in lines:
        line = source[:]
        if len(line) >= 3 and line[0] == line[-1]:
            closed_lines.append(line)
            continue
        if line[-1] < line[0]:
            line.reverse()
        open_lines.append(line)
    open_lines.sort(key=lambda line: (line[0], line[-1], len(line)))
    if not open_lines:
        return closed_lines, 0, 0.0
    chain = open_lines[0][:]
    bridges = 0
    bridge_length = 0.0
    for line in open_lines[1:]:
        gap = float(np.hypot(chain[-1][0] - line[0][0], chain[-1][1] - line[0][1]))
        if chain[-1] != line[0]:
            chain.append(line[0])
            bridges += 1
            bridge_length += gap
        chain.extend(line[1:])
    return [chain] + closed_lines, bridges, bridge_length


def _recipe(analysis: ImageUnderstandingResult, style: str, iterations: int) -> tuple[Polylines, VectorCleanupConfig, dict[str, object]]:
    fg = analysis.foreground_mask
    outer = _boundary(fg)
    edges = analysis.selected_edges
    strong = analysis.edge_mask & (analysis.edge_strength >= 0.58)
    very_strong = analysis.edge_mask & (analysis.edge_strength >= 0.72)
    tones = _tone_boundaries(analysis.tone_labels)
    dark_boundary = _boundary(analysis.gray <= 96)
    meta: dict[str, object] = {}

    if style == "silhouette":
        return _outlines(fg), VectorCleanupConfig.for_quality("smooth"), meta
    if style == "minimal_outline":
        raw = _combine(_strokes(outer, iterations), _strokes(very_strong & fg, iterations))
        return raw, VectorCleanupConfig.for_quality("smooth"), meta
    if style == "clean_outline":
        raw = _combine(_strokes(outer, iterations), _strokes(strong & _dilate(fg), iterations))
        return raw, VectorCleanupConfig.for_quality("smooth"), meta
    if style == "detailed_outline":
        raw = _combine(_strokes(outer, iterations), _strokes(edges, iterations), _strokes(tones & fg, iterations))
        return raw, VectorCleanupConfig.for_quality("clean"), meta
    if style == "continuous_contour":
        return _strokes(outer | strong, iterations), VectorCleanupConfig.for_quality("flowing"), meta
    if style == "one_line_art":
        raw, bridges, length = _ordered_one_line(_strokes(outer | strong, iterations))
        meta.update({"artistic_bridges": bridges, "artistic_bridge_length_px": round(length, 6)})
        cleanup = VectorCleanupConfig(
            min_segment_px=0.25, min_stroke_length_px=0.8, simplify_tolerance_px=0.35,
            preserve_corner_deg=42.0, smoothing="chaikin", smooth_passes=1,
            smooth_strength=0.22, duplicate_tolerance_px=0.3,
        )
        return raw, cleanup, meta
    if style == "loose_sketch":
        raw = _combine(_strokes(outer | edges, iterations), _strokes(dark_boundary & fg, iterations))
        return raw, VectorCleanupConfig.for_quality("flowing"), meta
    if style in ("refined_pen_sketch", "pet_portrait", "portrait"):
        threshold = 150 if style == "pet_portrait" else 170
        raw = _combine(
            _strokes(outer, iterations),
            _strokes(edges & fg, iterations),
            _strokes(tones & fg & (analysis.gray < threshold), iterations),
        )
        meta["semantic_recognition"] = False
        return raw, VectorCleanupConfig.for_quality("smooth"), meta
    if style == "comic_ink":
        raw = _combine(_strokes(_dilate(outer | very_strong), iterations), _strokes(dark_boundary, iterations))
        return raw, VectorCleanupConfig.for_quality("clean"), meta
    if style == "architectural_pen":
        raw = _strokes(strong | tones, iterations)
        cleanup = VectorCleanupConfig(
            min_segment_px=0.2, min_stroke_length_px=2.0, simplify_tolerance_px=0.55,
            preserve_corner_deg=78.0, duplicate_tolerance_px=0.35,
        )
        return raw, cleanup, meta
    if style == "technical_drawing":
        raw = _combine(_strokes(very_strong, iterations), _strokes(outer, iterations))
        cleanup = VectorCleanupConfig(
            min_segment_px=0.15, min_stroke_length_px=1.5, simplify_tolerance_px=0.65,
            preserve_corner_deg=88.0, duplicate_tolerance_px=0.25,
        )
        return raw, cleanup, meta
    if style == "topographic":
        raw = _combine(_strokes(tones, iterations), _strokes(outer, iterations))
        return raw, VectorCleanupConfig.for_quality("smooth"), meta
    raise ValueError(style)  # pragma: no cover


def render_line_art_from_analysis(analysis: ImageUnderstandingResult, config: LineArtConfig | None = None) -> LineArtResult:
    config = config or LineArtConfig()
    config.validate()
    raw, cleanup_config, extra = _recipe(analysis, config.style, config.max_skeleton_iterations)
    if not raw:
        raise ValueError("Line-art style produced no drawable geometry.")

    # Closed contours currently bypass Step 4 RDP simplification because the
    # Step 4 closed-loop simplifier is intentionally not required by these style
    # recipes. Other cleanup operations remain active and deterministic.
    if any(len(line) >= 3 and line[0] == line[-1] for line in raw) and cleanup_config.simplify_tolerance_px > 0:
        cleanup_config = replace(cleanup_config, simplify_tolerance_px=0.0)
        extra["closed_loop_simplification_bypassed"] = True

    cleaned = cleanup_polylines(raw, cleanup_config)
    polylines = cleaned.polylines
    points = sum(len(line) for line in polylines)
    if len(polylines) > config.max_output_strokes or points > config.max_output_points:
        raise ValueError("Line-art style output exceeds configured geometry limits.")
    validate_polylines(polylines)
    metadata: dict[str, object] = {
        "line_art_schema": "printrbot-line-art/v1",
        "line_art_style": config.style,
        "input_selected_edge_pixels": int(np.count_nonzero(analysis.selected_edges)),
        "input_foreground_pixels": int(np.count_nonzero(analysis.foreground_mask)),
        "raw_style_strokes": len(raw),
        "output_style_strokes": len(polylines),
        "output_style_points": points,
        "cleanup": cleaned.metadata,
    }
    metadata.update(extra)
    return LineArtResult(polylines=polylines, metadata=metadata)


def render_line_art(
    source: str | Path,
    config: LineArtConfig | None = None,
    *,
    preprocess: ImagePreprocessConfig | None = None,
    understanding: ImageUnderstandingConfig | None = None,
) -> LineArtResult:
    config = config or LineArtConfig()
    config.validate()
    analysis = analyze_image(source, preprocess=preprocess, understanding=understanding)
    result = render_line_art_from_analysis(analysis, config)
    metadata = dict(analysis.metadata)
    metadata.update(result.metadata)
    return LineArtResult(polylines=result.polylines, metadata=metadata)

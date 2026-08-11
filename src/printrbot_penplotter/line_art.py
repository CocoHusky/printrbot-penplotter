"""Deterministic Step 5 line-art styles upstream of machine placement."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import numpy as np

from .fast_cleanup import cleanup_polylines_fast
from .geometry import validate_polylines
from .image_preprocess import ImagePreprocessConfig
from .image_understanding import ImageUnderstandingConfig, ImageUnderstandingResult, analyze_image
from .models import Polylines
from .raster import _skeletonize, _trace_contours, _trace_skeleton
from .vector_cleanup import VectorCleanupConfig

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
    edge_threshold: float = 0.58
    strong_edge_threshold: float = 0.72
    tone_threshold: int = 170
    dilation_passes: int = 1
    simplify_tolerance_px: float | None = None
    smooth_passes: int | None = None
    join_distance_px: float | None = None
    min_stroke_length_px: float = 0.0
    max_kept_strokes: int = 0
    one_line_bridge_distance_px: float = 6.0

    def validate(self) -> None:
        if self.style not in STYLE_NAMES:
            raise ValueError(f"Unsupported line-art style: {self.style}")
        if not isinstance(self.max_skeleton_iterations, int) or self.max_skeleton_iterations < 1:
            raise ValueError("max_skeleton_iterations must be positive.")
        if self.max_output_strokes < 1 or self.max_output_points < 2:
            raise ValueError("Line-art geometry limits must be positive.")
        for name, value in (("edge_threshold", self.edge_threshold), ("strong_edge_threshold", self.strong_edge_threshold)):
            if not np.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1.")
        if self.edge_threshold > self.strong_edge_threshold:
            raise ValueError("edge_threshold must not exceed strong_edge_threshold.")
        if not isinstance(self.tone_threshold, int) or not 0 <= self.tone_threshold <= 255:
            raise ValueError("tone_threshold must be between 0 and 255.")
        if not isinstance(self.dilation_passes, int) or not 0 <= self.dilation_passes <= 4:
            raise ValueError("dilation_passes must be between 0 and 4.")
        if self.simplify_tolerance_px is not None and (not np.isfinite(self.simplify_tolerance_px) or self.simplify_tolerance_px < 0):
            raise ValueError("simplify_tolerance_px must be non-negative.")
        if self.smooth_passes is not None and (not isinstance(self.smooth_passes, int) or not 0 <= self.smooth_passes <= 8):
            raise ValueError("smooth_passes must be between 0 and 8.")
        if self.join_distance_px is not None and (not np.isfinite(self.join_distance_px) or not 0 <= self.join_distance_px <= 20):
            raise ValueError("join_distance_px must be between 0 and 20.")
        if not np.isfinite(self.min_stroke_length_px) or self.min_stroke_length_px < 0:
            raise ValueError("min_stroke_length_px must be non-negative.")
        if not isinstance(self.max_kept_strokes, int) or self.max_kept_strokes < 0:
            raise ValueError("max_kept_strokes must be a non-negative integer.")
        if not np.isfinite(self.one_line_bridge_distance_px) or not 0 <= self.one_line_bridge_distance_px <= 20:
            raise ValueError("one_line_bridge_distance_px must be between 0 and 20.")


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
    return _trace_skeleton(skeleton, image_coordinates=True)


def _outlines(mask: np.ndarray) -> Polylines:
    return [] if not np.any(mask) else _trace_contours(mask.astype(bool), image_coordinates=True)


def _combine(*groups: Polylines) -> Polylines:
    return [line[:] for group in groups for line in group if len(line) >= 2]


def _polyline_length(line: list[tuple[float, float]]) -> float:
    return sum(float(np.hypot(b[0] - a[0], b[1] - a[1])) for a, b in zip(line, line[1:]))


def _select_useful_strokes(
    lines: Polylines,
    *,
    min_length_px: float,
    max_strokes: int,
) -> tuple[Polylines, int, int]:
    """Drop tiny traces and optionally keep the longest useful contours."""
    candidates = [line[:] for line in lines if len(line) >= 2 and _polyline_length(line) >= min_length_px]
    removed_short = len(lines) - len(candidates)
    if max_strokes and len(candidates) > max_strokes:
        ranked = sorted(enumerate(candidates), key=lambda item: (-_polyline_length(item[1]), item[0]))
        keep_indices = {index for index, _ in ranked[:max_strokes]}
        candidates = [line for index, line in enumerate(candidates) if index in keep_indices]
        return candidates, removed_short, len(ranked) - max_strokes
    return candidates, removed_short, 0


def _ordered_one_line(lines: Polylines, *, max_bridge_px: float = 6.0) -> tuple[Polylines, int, float, int]:
    """Route nearby strokes into long chains without crossing blank paper."""
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
    if not open_lines:
        return closed_lines, 0, 0.0, 0
    remaining = [line[:] for line in open_lines]
    chains: Polylines = []
    bridges = 0
    bridge_length = 0.0
    skipped = 0

    # Dense raster traces can contain tens of thousands of fragments. Avoid
    # an all-pairs search there; a stable spatially ordered pass still joins
    # adjacent fragments when they are genuinely close and remains linear-ish.
    if len(remaining) > 5_000:
        remaining.sort(key=lambda line: (line[0], line[-1], len(line)))
        chain = remaining.pop(0)
        for candidate in remaining:
            gap = float(np.hypot(chain[-1][0] - candidate[0][0], chain[-1][1] - candidate[0][1]))
            if gap <= max_bridge_px:
                chain.append(candidate[0])
                chain.extend(candidate[1:])
                bridges += 1
                bridge_length += gap
            else:
                chains.append(chain)
                skipped += 1
                chain = candidate
        chains.append(chain)
        return chains + closed_lines, bridges, bridge_length, skipped

    while remaining:
        chain = remaining.pop(0)
        while remaining:
            best_index = -1
            best_reverse = False
            best_gap = float("inf")
            for index, candidate in enumerate(remaining):
                forward = float(np.hypot(chain[-1][0] - candidate[0][0], chain[-1][1] - candidate[0][1]))
                reverse = float(np.hypot(chain[-1][0] - candidate[-1][0], chain[-1][1] - candidate[-1][1]))
                if forward < best_gap:
                    best_index, best_reverse, best_gap = index, False, forward
                if reverse < best_gap:
                    best_index, best_reverse, best_gap = index, True, reverse
            if best_index < 0 or best_gap > max_bridge_px:
                break
            candidate = remaining.pop(best_index)
            if best_reverse:
                candidate.reverse()
            if chain[-1] != candidate[0]:
                chain.append(candidate[0])
                bridges += 1
                bridge_length += best_gap
            chain.extend(candidate[1:])
        chains.append(chain)
        if remaining:
            skipped += 1
    return chains + closed_lines, bridges, bridge_length, skipped


def _looks_like_line_drawing(analysis: ImageUnderstandingResult) -> bool:
    """Detect sparse ink on a light background before adding derived edges.

    A photograph needs edges extracted from tone regions.  A scanned/inked
    illustration already contains the marks we want, so extracting another
    edge on both sides of each mark creates doubled contours and a busy plot.
    This deliberately conservative test only changes the sparse, high-key
    case and leaves filled subjects and photographs on the existing path.
    """
    gray = analysis.gray.astype(np.float32)
    light_background = float(np.mean(gray >= 235.0)) >= 0.68
    sparse_ink = float(np.mean(analysis.foreground_mask)) <= 0.28
    has_edges = float(np.mean(analysis.selected_edges)) >= 0.008
    return light_background and sparse_ink and has_edges


def _recipe(analysis: ImageUnderstandingResult, config: LineArtConfig) -> tuple[Polylines, VectorCleanupConfig, dict[str, object]]:
    style = config.style
    iterations = config.max_skeleton_iterations
    fg = analysis.foreground_mask
    outer = _boundary(fg)
    edges = analysis.selected_edges
    strong = analysis.edge_mask & (analysis.edge_strength >= config.edge_threshold)
    very_strong = analysis.edge_mask & (analysis.edge_strength >= config.strong_edge_threshold)
    tones = _tone_boundaries(analysis.tone_labels)
    dark_boundary = _boundary(analysis.gray <= config.tone_threshold)
    meta: dict[str, object] = {}
    source_is_line_drawing = _looks_like_line_drawing(analysis)
    meta["source_is_line_drawing"] = source_is_line_drawing

    # For an already-inked illustration, the threshold mask is the artwork.
    # Skeletonizing it once preserves the original centerline and avoids the
    # doubled contours produced when Canny edges are layered on top of it.
    if source_is_line_drawing and style in {
        "minimal_outline", "clean_outline", "continuous_contour",
        "refined_pen_sketch", "pet_portrait", "portrait", "comic_ink",
    }:
        cleanup = VectorCleanupConfig(
            # Screenshot/scanner antialiasing breaks long ink marks into
            # tiny islands.  Removing those islands is what keeps a nest,
            # branch, or pen illustration from turning into visual noise.
            min_segment_px=0.35,
            min_stroke_length_px=3.5,
            min_closed_area_px2=1.0,
            simplify_tolerance_px=0.70,
            preserve_corner_deg=48.0,
            duplicate_tolerance_px=0.35,
            join_distance_px=1.5,
            join_angle_deg=32.0,
        )
        meta["line_drawing_trace"] = "foreground_centerline"
        return _strokes(fg, iterations), cleanup, meta

    if style == "silhouette":
        return _outlines(fg), VectorCleanupConfig.for_quality("smooth"), meta
    if style == "minimal_outline":
        raw = _combine(_strokes(outer, iterations), _strokes(very_strong & fg, iterations))
        return raw, VectorCleanupConfig.for_quality("smooth"), meta
    if style == "clean_outline":
        raw = _combine(_strokes(outer, iterations), _strokes(strong & _dilate(fg, config.dilation_passes), iterations))
        return raw, VectorCleanupConfig.for_quality("smooth"), meta
    if style == "detailed_outline":
        raw = _combine(_strokes(outer, iterations), _strokes(edges, iterations), _strokes(tones & fg, iterations))
        return raw, VectorCleanupConfig.for_quality("clean"), meta
    if style == "continuous_contour":
        return _strokes(outer | strong, iterations), VectorCleanupConfig.for_quality("flowing"), meta
    if style == "one_line_art":
        max_bridge = config.one_line_bridge_distance_px
        raw, bridges, length, skipped = _ordered_one_line(
            _strokes(outer | strong, iterations), max_bridge_px=max_bridge
        )
        meta.update({
            "artistic_bridges": bridges,
            "artistic_bridge_length_px": round(length, 6),
            "artistic_unconnected_chains": skipped,
            "artistic_max_bridge_px": max_bridge,
        })
        cleanup = VectorCleanupConfig(
            min_segment_px=0.25, min_stroke_length_px=0.8, simplify_tolerance_px=0.65,
            preserve_corner_deg=55.0, smoothing="chaikin", smooth_passes=1,
            smooth_strength=0.22, duplicate_tolerance_px=0.3,
        )
        return raw, cleanup, meta
    if style == "loose_sketch":
        raw = _combine(_strokes(outer | edges, iterations), _strokes(dark_boundary & fg, iterations))
        return raw, VectorCleanupConfig.for_quality("flowing"), meta
    if style in ("refined_pen_sketch", "pet_portrait", "portrait"):
        threshold = config.tone_threshold if style != "pet_portrait" else min(config.tone_threshold, 150)
        raw = _combine(
            _strokes(outer, iterations),
            _strokes(edges & fg, iterations),
            _strokes(tones & fg & (analysis.gray < threshold), iterations),
        )
        meta["semantic_recognition"] = False
        return raw, VectorCleanupConfig.for_quality("smooth"), meta
    if style == "comic_ink":
        raw = _combine(_strokes(_dilate(outer | very_strong, config.dilation_passes), iterations), _strokes(dark_boundary, iterations))
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
        # Topographic contours come directly from grayscale tone bands. Do not
        # add a binary foreground outline: that would make this style depend
        # on the black/white stage and produce an unrelated border.
        raw = _strokes(_tone_boundaries(tones), iterations)
        return raw, VectorCleanupConfig.for_quality("smooth"), meta
    raise ValueError(style)


def render_line_art_from_analysis(analysis: ImageUnderstandingResult, config: LineArtConfig | None = None) -> LineArtResult:
    config = config or LineArtConfig()
    config.validate()
    raw, cleanup_config, extra = _recipe(analysis, config)
    raw, removed_short, cap_dropped = _select_useful_strokes(
        raw,
        min_length_px=config.min_stroke_length_px,
        max_strokes=config.max_kept_strokes,
    )
    extra.update({
        "line_art_removed_short_strokes": removed_short,
        "line_art_rank_cap_dropped": cap_dropped,
    })
    if config.simplify_tolerance_px is not None:
        cleanup_config = replace(cleanup_config, simplify_tolerance_px=config.simplify_tolerance_px)
    if config.smooth_passes is not None:
        cleanup_config = replace(cleanup_config, smooth_passes=config.smooth_passes)
    if config.join_distance_px is not None:
        cleanup_config = replace(cleanup_config, join_distance_px=config.join_distance_px)
    if not raw:
        raise ValueError("Line-art style produced no drawable geometry.")

    if any(len(line) >= 3 and line[0] == line[-1] for line in raw) and cleanup_config.simplify_tolerance_px > 0:
        cleanup_config = replace(cleanup_config, simplify_tolerance_px=0.0)
        extra["closed_loop_simplification_bypassed"] = True

    cleaned = cleanup_polylines_fast(raw, cleanup_config)
    polylines = cleaned.polylines
    points = sum(len(line) for line in polylines)
    if len(polylines) > config.max_output_strokes or points > config.max_output_points:
        raise ValueError("Line-art style output exceeds configured geometry limits.")
    validate_polylines(polylines)
    metadata: dict[str, object] = dict(analysis.metadata)
    metadata.update({
        "line_art_schema": "printrbot-line-art/v1",
        "line_art_style": config.style,
        "input_selected_edge_pixels": int(np.count_nonzero(analysis.selected_edges)),
        "input_foreground_pixels": int(np.count_nonzero(analysis.foreground_mask)),
        "raw_style_strokes": len(raw),
        "output_style_strokes": len(polylines),
        "output_style_points": points,
        "style_edge_threshold": config.edge_threshold,
        "style_strong_edge_threshold": config.strong_edge_threshold,
        "style_tone_threshold": config.tone_threshold,
        "style_dilation_passes": config.dilation_passes,
        "style_simplify_tolerance_px": config.simplify_tolerance_px,
        "style_smooth_passes": config.smooth_passes,
        "style_join_distance_px": config.join_distance_px,
        "style_min_stroke_length_px": config.min_stroke_length_px,
        "style_max_kept_strokes": config.max_kept_strokes,
        "one_line_bridge_distance_px": config.one_line_bridge_distance_px,
        "cleanup": cleaned.metadata,
    })
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

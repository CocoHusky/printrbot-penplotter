"""Deterministic line-art style rendering from Step 3 image understanding.

Step 5 converts analyzed raster features into intentional pen-line geometry.
It remains upstream of machine placement, motion planning, preview, and G-code.
No semantic recognition is claimed: portrait/pet presets are deterministic
feature-weighting presets, not object detectors.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    "minimal_outline",
    "clean_outline",
    "detailed_outline",
    "continuous_contour",
    "one_line_art",
    "loose_sketch",
    "refined_pen_sketch",
    "pet_portrait",
    "portrait",
    "comic_ink",
    "architectural_pen",
    "technical_drawing",
    "silhouette",
    "topographic",
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
    """Return a one-pixel inner boundary for a boolean region mask."""
    mask = mask.astype(bool)
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    eroded = np.ones_like(mask, dtype=bool)
    for r in range(3):
        for c in range(3):
            eroded &= padded[r:r + mask.shape[0], c:c + mask.shape[1]]
    return mask & ~eroded


def _tone_boundaries(labels: np.ndarray, minimum_band_delta: int = 1) -> np.ndarray:
    labels = labels.astype(np.int16)
    edges = np.zeros(labels.shape, dtype=bool)
    horizontal = np.abs(labels[:, 1:] - labels[:, :-1]) >= minimum_band_delta
    vertical = np.abs(labels[1:, :] - labels[:-1, :]) >= minimum_band_delta
    edges[:, 1:] |= horizontal
    edges[:, :-1] |= horizontal
    edges[1:, :] |= vertical
    edges[:-1, :] |= vertical
    return edges


def _dilate(mask: np.ndarray, passes: int = 1) -> np.ndarray:
    result = mask.astype(bool).copy()
    for _ in range(passes):
        padded = np.pad(result, 1, mode="constant")
        grown = np.zeros_like(result)
        for r in range(3):
            for c in range(3):
                grown |= padded[r:r + result.shape[0], c:c + result.shape[1]]
        result = grown
    return result


def _vectorize_strokes(mask: np.ndarray, iterations: int) -> Polylines:
    if not np.any(mask):
        return []
    skeleton, _, _ = _skeletonize(mask.astype(bool), iterations)
    return _trace_skeleton(skeleton)


def _vectorize_outline(mask: np.ndarray) -> Polylines:
    if not np.any(mask):
        return []
    return _trace_contours(mask.astype(bool))


def _combine(*groups: Polylines) -> Polylines:
    output: Polylines = []
    for group in groups:
        output.extend([line[:] for line in group if len(line) >= 2])
    return output


def _nearest_chain(lines: Polylines) -> tuple[Polylines, int, float]:
    """Join all open strokes with explicit artistic bridge lines.

    This is used only by the intentionally stylized one_line_art preset. Closed
    loops remain separate because opening them would alter their topology.
    """
    open_lines = [line[:] for line in lines if len(line) >= 2 and line[0] != line[-1]]
    closed_lines = [line[:] for line in lines if len(line) >= 3 and line[0] == line[-1]]
    if not open_lines:
        return closed_lines, 0, 0.0
    chain = open_lines.pop(0)
    bridges = 0
    bridge_length = 0.0
    while open_lines:
        candidates: list[tuple[float, int, bool]] = []
        for index, line in enumerate(open_lines):
            direct = float(np.hypot(chain[-1][0] - line[0][0], chain[-1][1] - line[0][1]))
            reverse = float(np.hypot(chain[-1][0] - line[-1][0], chain[-1][1] - line[-1][1]))
            candidates.append((direct, index, False))
            candidates.append((reverse, index, True))
        gap, index, reverse = min(candidates)
        line = open_lines.pop(index)
        if reverse:
            line.reverse()
        if chain[-1] != line[0]:
            chain.append(line[0])
            bridges += 1
            bridge_length += gap
        chain.extend(line[1:])
    return [chain] + closed_lines, bridges, bridge_length


def _style_recipe(analysis: ImageUnderstandingResult, style: str) -> tuple[Polylines, VectorCleanupConfig, dict[str, object]]:
    fg = analysis.foreground_mask
    silhouette_boundary = _boundary(fg)
    edges = analysis.selected_edges
    strong = analysis.edge_mask & (analysis.edge_strength >= 0.58)
    very_strong = analysis.edge_mask & (analysis.edge_strength >= 0.72)
    tones = _tone_boundaries(analysis.tone_labels)
    dark = analysis.gray <= 96
    dark_boundary = _boundary(dark)

    meta: dict[str, object] = {}

    if style == "silhouette":
        raw = _vectorize_outline(fg)
        cleanup = VectorCleanupConfig.for_quality("smooth")
    elif style == "minimal_outline":
        raw = _combine(_vectorize_strokes(silhouette_boundary, 256), _vectorize_strokes(very_strong & fg, 256))
        cleanup = VectorCleanupConfig.for_quality("smooth")
    elif style == "clean_outline":
        raw = _combine(_vectorize_strokes(silhouette_boundary, 256), _vectorize_strokes(strong & _dilate(fg, 1), 256))
        cleanup = VectorCleanupConfig.for_quality("smooth")
    elif style == "detailed_outline":
        raw = _combine(_vectorize_strokes(silhouette_boundary, 256), _vectorize_strokes(edges, 256), _vectorize_strokes(tones & fg, 256))
        cleanup = VectorCleanupConfig.for_quality("clean")
    elif style == "continuous_contour":
        raw = _combine(_vectorize_strokes(silhouette_boundary | strong, 256))
        cleanup = VectorCleanupConfig.for_quality("flowing")
    elif style == "one_line_art":
        raw = _combine(_vectorize_strokes(silhouette_boundary | strong, 256))
        raw, bridges, bridge_length = _nearest_chain(raw)
        meta.update({"artistic_bridges": bridges, "artistic_bridge_length_px": round(bridge_length, 6)})
        cleanup = VectorCleanupConfig(
            min_segment_px=0.25, min_stroke_length_px=0.8, simplify_tolerance_px=0.35,
            preserve_corner_deg=42.0, smoothing="chaikin", smooth_passes=1,
            smooth_strength=0.22, duplicate_tolerance_px=0.3,
        )
    elif style == "loose_sketch":
        raw = _combine(_vectorize_strokes(silhouette_boundary | edges, 256), _vectorize_strokes(dark_boundary & fg, 256))
        cleanup = VectorCleanupConfig.for_quality("flowing")
    elif style in ("refined_pen_sketch", "pet_portrait", "portrait"):
        # Pet/portrait are deterministic emphasis presets, not semantic detectors.
        detail = edges & fg
        tonal = tones & fg & (analysis.gray < (150 if style == "pet_portrait" else 170))
        raw = _combine(
            _vectorize_strokes(silhouette_boundary, 256),
            _vectorize_strokes(detail, 256),
            _vectorize_strokes(tonal, 256),
        )
        cleanup = VectorCleanupConfig.for_quality("smooth")
        meta["semantic_recognition"] = False
    elif style == "comic_ink":
        raw = _combine(_vectorize_strokes(_dilate(silhouette_boundary | very_strong, 1), 256), _vectorize_strokes(dark_boundary, 256))
        cleanup = VectorCleanupConfig.for_quality("clean")
    elif style == "architectural_pen":
        raw = _combine(_vectorize_strokes(strong | tones, 256))
        cleanup = VectorCleanupConfig(
            min_segment_px=0.2, min_stroke_length_px=2.0, simplify_tolerance_px=0.55,
            preserve_corner_deg=78.0, duplicate_tolerance_px=0.35,
        )
    elif style == "technical_drawing":
        raw = _combine(_vectorize_strokes(very_strong, 256), _vectorize_strokes(silhouette_boundary, 256))
        cleanup = VectorCleanupConfig(
            min_segment_px=0.15, min_stroke_length_px=1.5, simplify_tolerance_px=0.65,
            preserve_corner_deg=88.0, duplicate_tolerance_px=0.25,
        )
    elif style == "topographic":
        raw = _combine(_vectorize_strokes(tones, 256), _vectorize_strokes(silhouette_boundary, 256))
        cleanup = VectorCleanupConfig.for_quality("smooth")
    else:  # pragma: no cover - guarded by config validation
        raise ValueError(style)

    return raw, cleanup, meta


def render_line_art_from_analysis(
    analysis: ImageUnderstandingResult,
    config: LineArtConfig | None = None,
) -> LineArtResult:
    """Render analyzed image features into deterministic line-art polylines."""
    config = config or LineArtConfig()
    config.validate()
    raw, cleanup_config, extra = _style_recipe(analysis, config.style)
    if not raw:
        raise ValueError("Line-art style produced no drawable geometry.")
    cleaned = cleanup_polylines(raw, cleanup_config)
    polylines = cleaned.polylines
    point_count = sum(len(line) for line in polylines)
    if len(polylines) > config.max_output_strokes or point_count > config.max_output_points:
        raise ValueError("Line-art style output exceeds configured geometry limits.")
    validate_polylines(polylines)
    metadata: dict[str, object] = {
        "line_art_schema": "printrbot-line-art/v1",
        "line_art_style": config.style,
        "input_selected_edge_pixels": int(np.count_nonzero(analysis.selected_edges)),
        "input_foreground_pixels": int(np.count_nonzero(analysis.foreground_mask)),
        "raw_style_strokes": len(raw),
        "output_style_strokes": len(polylines),
        "output_style_points": point_count,
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
    """Preprocess, analyze, and render an image using a named line-art style."""
    config = config or LineArtConfig()
    config.validate()
    analysis = analyze_image(source, preprocess=preprocess, understanding=understanding)
    result = render_line_art_from_analysis(analysis, config)
    metadata = dict(analysis.metadata)
    metadata.update(result.metadata)
    return LineArtResult(polylines=result.polylines, metadata=metadata)

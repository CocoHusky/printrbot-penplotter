"""Deterministic Step 6 pen-shading and texture styles.

This module converts Step 3 tonal/edge analysis into ordinary polyline geometry.
It never emits G-code and remains upstream of machine placement, motion planning,
preview, and the Step 1 hardware safety contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Literal

import numpy as np

from .geometry import validate_polylines
from .image_preprocess import ImagePreprocessConfig
from .image_understanding import ImageUnderstandingConfig, ImageUnderstandingResult, analyze_image
from .line_art import LineArtConfig, STYLE_NAMES, render_line_art_from_analysis
from .models import Point, Polyline, Polylines

PenShadingStyle = Literal[
    "parallel_hatch",
    "crosshatch",
    "dense_crosshatch",
    "curved_hatch",
    "contour_hatch",
    "directional_hatch",
    "scribble",
    "stipple",
    "pointillism",
    "halftone",
    "engraving",
    "etching",
    "woodcut",
    "scratchboard",
    "fur_texture",
    "hair_texture",
]

SHADING_STYLE_NAMES: tuple[str, ...] = (
    "parallel_hatch", "crosshatch", "dense_crosshatch", "curved_hatch",
    "contour_hatch", "directional_hatch", "scribble", "stipple",
    "pointillism", "halftone", "engraving", "etching", "woodcut",
    "scratchboard", "fur_texture", "hair_texture",
)


@dataclass(frozen=True)
class PenShadingConfig:
    style: PenShadingStyle = "crosshatch"
    include_outline: bool = True
    outline_style: str = "refined_pen_sketch"
    hatch_spacing_px: float = 5.0
    min_stroke_length_px: float = 1.25
    darkness_threshold: float = 0.22
    max_output_strokes: int = 30_000
    max_output_points: int = 2_000_000
    seed: int = 0
    angle_offset_deg: float = 0.0
    density_scale: float = 1.0

    def validate(self) -> None:
        if self.style not in SHADING_STYLE_NAMES:
            raise ValueError(f"Unsupported pen-shading style: {self.style}")
        if self.outline_style not in STYLE_NAMES:
            raise ValueError(f"Unsupported outline style: {self.outline_style}")
        if not math.isfinite(self.hatch_spacing_px) or not 1.0 <= self.hatch_spacing_px <= 100.0:
            raise ValueError("hatch_spacing_px must be between 1 and 100 pixels.")
        if not math.isfinite(self.min_stroke_length_px) or self.min_stroke_length_px < 0:
            raise ValueError("min_stroke_length_px must be finite and non-negative.")
        if not math.isfinite(self.darkness_threshold) or not 0.0 <= self.darkness_threshold <= 1.0:
            raise ValueError("darkness_threshold must be between 0 and 1.")
        if self.max_output_strokes < 1 or self.max_output_points < 2:
            raise ValueError("Pen-shading geometry limits must be positive.")
        if not isinstance(self.seed, int):
            raise ValueError("seed must be an integer.")
        if not math.isfinite(self.angle_offset_deg) or not -180 <= self.angle_offset_deg <= 180:
            raise ValueError("angle_offset_deg must be between -180 and 180 degrees.")
        if not math.isfinite(self.density_scale) or not 0.25 <= self.density_scale <= 4:
            raise ValueError("density_scale must be between 0.25 and 4.")


@dataclass(frozen=True)
class PenShadingResult:
    polylines: Polylines
    metadata: dict[str, object]


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _length(line: Polyline) -> float:
    return sum(_distance(a, b) for a, b in zip(line, line[1:]))


def _darkness(gray: np.ndarray) -> np.ndarray:
    return 1.0 - gray.astype(np.float64) / 255.0


def _hash01(x: int, y: int, seed: int) -> float:
    value = (x * 0x1F123BB5) ^ (y * 0x5F356495) ^ (seed * 0x6C8E9CF5)
    value = (value ^ (value >> 16)) * 0x45D9F3B
    value = (value ^ (value >> 16)) * 0x45D9F3B
    value = value ^ (value >> 16)
    return (value & 0xFFFFFFFF) / 0xFFFFFFFF


def _inside(mask: np.ndarray, x: float, y: float) -> bool:
    ix = int(round(x))
    iy = int(round(y))
    return 0 <= iy < mask.shape[0] and 0 <= ix < mask.shape[1] and bool(mask[iy, ix])


def _clip_parametric_lines(
    mask: np.ndarray,
    *,
    angle_deg: float,
    spacing: float,
    min_length: float,
    wave_amplitude: float = 0.0,
    wave_period: float = 24.0,
) -> Polylines:
    """Clip a deterministic family of parallel (optionally curved) lines to a mask."""
    if not np.any(mask):
        return []
    theta = math.radians(angle_deg)
    dx, dy = math.cos(theta), math.sin(theta)
    nx, ny = -dy, dx
    h, w = mask.shape
    corners = [(0.0, 0.0), (w - 1.0, 0.0), (0.0, h - 1.0), (w - 1.0, h - 1.0)]
    s_values = [x * nx + y * ny for x, y in corners]
    t_values = [x * dx + y * dy for x, y in corners]
    s_start = math.floor(min(s_values) / spacing) * spacing
    s_stop = math.ceil(max(s_values) / spacing) * spacing
    t_start = math.floor(min(t_values)) - 2.0
    t_stop = math.ceil(max(t_values)) + 2.0

    lines: Polylines = []
    s = s_start
    while s <= s_stop + 1e-9:
        run: Polyline = []
        t = t_start
        while t <= t_stop + 1e-9:
            offset = wave_amplitude * math.sin((2.0 * math.pi * t / max(wave_period, 1.0)) + s * 0.071)
            x = dx * t + nx * (s + offset)
            y = dy * t + ny * (s + offset)
            if _inside(mask, x, y):
                if not run or _distance(run[-1], (x, y)) >= 1.0:
                    run.append((x, y))
            else:
                if len(run) >= 2 and _length(run) >= min_length:
                    lines.append([run[0], run[-1]] if wave_amplitude == 0 else run)
                run = []
            t += 1.0
        if len(run) >= 2 and _length(run) >= min_length:
            lines.append([run[0], run[-1]] if wave_amplitude == 0 else run)
        s += spacing
    return lines


def _layer_mask(analysis: ImageUnderstandingResult, threshold: float, *, inverse: bool = False) -> np.ndarray:
    darkness = _darkness(analysis.gray)
    tone = darkness <= (1.0 - threshold) if inverse else darkness >= threshold
    return analysis.foreground_mask.astype(bool) & tone


def _hatch_layers(
    analysis: ImageUnderstandingResult,
    layers: list[tuple[float, float, float]],
    config: PenShadingConfig,
    *,
    curved: bool = False,
) -> Polylines:
    lines: Polylines = []
    for threshold, angle, spacing_scale in layers:
        mask = _layer_mask(analysis, max(config.darkness_threshold, threshold))
        lines.extend(
            _clip_parametric_lines(
                mask,
                angle_deg=angle + config.angle_offset_deg,
                spacing=max(1.0, config.hatch_spacing_px * spacing_scale / config.density_scale),
                min_length=config.min_stroke_length_px,
                wave_amplitude=(0.75 if curved else 0.0),
                wave_period=max(12.0, config.hatch_spacing_px * 5.0),
            )
        )
    return lines


def _tone_boundary_strokes(analysis: ImageUnderstandingResult) -> Polylines:
    labels = analysis.tone_labels.astype(np.int16)
    mask = np.zeros(labels.shape, dtype=bool)
    diff_x = labels[:, 1:] != labels[:, :-1]
    diff_y = labels[1:, :] != labels[:-1, :]
    mask[:, 1:] |= diff_x
    mask[:, :-1] |= diff_x
    mask[1:, :] |= diff_y
    mask[:-1, :] |= diff_y
    mask &= analysis.foreground_mask.astype(bool)
    from .raster import _skeletonize, _trace_skeleton

    skeleton, _, _ = _skeletonize(mask, 256)
    return _trace_skeleton(skeleton)


def _flow_strokes(
    analysis: ImageUnderstandingResult,
    config: PenShadingConfig,
    *,
    spacing_scale: float,
    length_scale: float,
    tangent: bool = True,
    threshold: float | None = None,
) -> Polylines:
    """Generate short strokes aligned to the local grayscale gradient field."""
    gray = analysis.gray.astype(np.float64)
    gy, gx = np.gradient(gray)
    darkness = _darkness(gray)
    spacing = max(2, int(round(config.hatch_spacing_px * spacing_scale / config.density_scale)))
    threshold = max(config.darkness_threshold, threshold if threshold is not None else 0.25)
    h, w = gray.shape
    lines: Polylines = []
    for y in range(spacing // 2, h, spacing):
        for x in range(spacing // 2, w, spacing):
            if not analysis.foreground_mask[y, x] or darkness[y, x] < threshold:
                continue
            angle = math.atan2(float(gy[y, x]), float(gx[y, x]))
            if tangent:
                angle += math.pi / 2.0 + math.radians(config.angle_offset_deg)
            if abs(gx[y, x]) + abs(gy[y, x]) < 1e-9:
                angle = math.radians(25.0 + ((_hash01(x, y, config.seed) - 0.5) * 20.0))
            length = max(config.min_stroke_length_px, config.hatch_spacing_px * length_scale * (0.55 + darkness[y, x]))
            dx = math.cos(angle) * length * 0.5
            dy = math.sin(angle) * length * 0.5
            a, b = (x - dx, y - dy), (x + dx, y + dy)
            if _inside(analysis.foreground_mask, *a) and _inside(analysis.foreground_mask, *b):
                lines.append([a, b])
    return lines


def _scribble_strokes(analysis: ImageUnderstandingResult, config: PenShadingConfig) -> Polylines:
    mask = _layer_mask(analysis, max(config.darkness_threshold, 0.28))
    spacing = max(2.0, config.hatch_spacing_px * 0.9 / config.density_scale)
    lines: Polylines = []
    y = spacing * 0.5
    while y < mask.shape[0]:
        run: Polyline = []
        for x in np.arange(0.0, mask.shape[1], 1.0):
            yy = y + math.sin(x * 0.42 + y * 0.11) * min(1.8, spacing * 0.35)
            point = (float(x), float(yy))
            if _inside(mask, *point):
                run.append(point)
            else:
                if len(run) >= 2 and _length(run) >= config.min_stroke_length_px:
                    lines.append(run)
                run = []
        if len(run) >= 2 and _length(run) >= config.min_stroke_length_px:
            lines.append(run)
        y += spacing
    return lines


def _stipple_strokes(analysis: ImageUnderstandingResult, config: PenShadingConfig, *, round_marks: bool) -> Polylines:
    darkness = _darkness(analysis.gray)
    spacing = max(2, int(round(config.hatch_spacing_px / config.density_scale)))
    lines: Polylines = []
    for y in range(spacing // 2, analysis.gray.shape[0], spacing):
        for x in range(spacing // 2, analysis.gray.shape[1], spacing):
            if not analysis.foreground_mask[y, x]:
                continue
            d = float(darkness[y, x])
            if d < config.darkness_threshold or _hash01(x, y, config.seed) > d:
                continue
            radius = max(0.22, min(spacing * 0.28, 0.25 + d * spacing * 0.20))
            if round_marks:
                points: Polyline = []
                for index in range(9):
                    angle = 2.0 * math.pi * index / 8.0
                    points.append((x + radius * math.cos(angle), y + radius * math.sin(angle)))
                lines.append(points)
            else:
                angle = math.radians(35.0 + 55.0 * _hash01(y, x, config.seed + 17))
                dx, dy = math.cos(angle) * radius, math.sin(angle) * radius
                lines.append([(x - dx, y - dy), (x + dx, y + dy)])
    return lines


def _halftone_strokes(analysis: ImageUnderstandingResult, config: PenShadingConfig) -> Polylines:
    darkness = _darkness(analysis.gray)
    spacing = max(3, int(round(config.hatch_spacing_px * 1.35 / config.density_scale)))
    lines: Polylines = []
    for y in range(spacing // 2, analysis.gray.shape[0], spacing):
        for x in range(spacing // 2, analysis.gray.shape[1], spacing):
            if not analysis.foreground_mask[y, x]:
                continue
            d = float(darkness[y, x])
            if d < config.darkness_threshold:
                continue
            radius = min(spacing * 0.44, max(0.3, d * spacing * 0.42))
            diamond = [(x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y), (x, y - radius)]
            if all(_inside(analysis.foreground_mask, *point) for point in diamond):
                lines.append(diamond)
    return lines


def _outline(analysis: ImageUnderstandingResult, config: PenShadingConfig, style: str | None = None) -> Polylines:
    if not config.include_outline:
        return []
    result = render_line_art_from_analysis(analysis, LineArtConfig(style=style or config.outline_style))
    return [line[:] for line in result.polylines]


def _recipe(analysis: ImageUnderstandingResult, config: PenShadingConfig) -> tuple[Polylines, dict[str, object]]:
    style = config.style
    meta: dict[str, object] = {"semantic_recognition": False}

    if style == "parallel_hatch":
        shading = _hatch_layers(analysis, [(0.28, 28.0, 1.0)], config)
    elif style == "crosshatch":
        shading = _hatch_layers(analysis, [(0.25, 28.0, 1.0), (0.52, 118.0, 1.0)], config)
    elif style == "dense_crosshatch":
        shading = _hatch_layers(analysis, [(0.22, 25.0, 1.0), (0.45, 115.0, 1.0), (0.68, 70.0, 0.9), (0.82, 160.0, 0.9)], config)
    elif style == "curved_hatch":
        shading = _hatch_layers(analysis, [(0.25, 18.0, 1.0), (0.62, 108.0, 1.15)], config, curved=True)
    elif style == "contour_hatch":
        shading = _tone_boundary_strokes(analysis) + _flow_strokes(analysis, config, spacing_scale=1.0, length_scale=1.6, tangent=True, threshold=0.35)
    elif style == "directional_hatch":
        shading = _flow_strokes(analysis, config, spacing_scale=0.9, length_scale=1.8, tangent=True)
    elif style == "scribble":
        shading = _scribble_strokes(analysis, config)
    elif style == "stipple":
        shading = _stipple_strokes(analysis, config, round_marks=False)
    elif style == "pointillism":
        shading = _stipple_strokes(analysis, config, round_marks=True)
    elif style == "halftone":
        shading = _halftone_strokes(analysis, config)
    elif style == "engraving":
        shading = _hatch_layers(analysis, [(0.20, 24.0, 0.9), (0.42, 114.0, 0.95), (0.67, 70.0, 0.85)], config)
        return _outline(analysis, config, "detailed_outline") + shading, meta
    elif style == "etching":
        shading = _hatch_layers(analysis, [(0.26, 33.0, 1.05), (0.58, 123.0, 1.2)], config, curved=True)
        shading += _flow_strokes(analysis, config, spacing_scale=1.5, length_scale=1.1, tangent=True, threshold=0.48)
        return _outline(analysis, config, "loose_sketch") + shading, meta
    elif style == "woodcut":
        shading = _hatch_layers(analysis, [(0.38, 18.0, 1.55), (0.72, 108.0, 1.7)], config)
        return _outline(analysis, config, "comic_ink") + shading, meta
    elif style == "scratchboard":
        bright_mask = analysis.foreground_mask.astype(bool) & (_darkness(analysis.gray) <= 0.42)
        shading = _clip_parametric_lines(bright_mask, angle_deg=32.0, spacing=config.hatch_spacing_px, min_length=config.min_stroke_length_px)
        meta["inverse_tone_shading"] = True
        return _outline(analysis, config, "clean_outline") + shading, meta
    elif style == "fur_texture":
        shading = _flow_strokes(analysis, config, spacing_scale=0.70, length_scale=0.85, tangent=True, threshold=0.30)
        meta["texture_is_semantic"] = False
        return _outline(analysis, config, "pet_portrait") + shading, meta
    elif style == "hair_texture":
        shading = _flow_strokes(analysis, config, spacing_scale=0.85, length_scale=2.4, tangent=True, threshold=0.28)
        meta["texture_is_semantic"] = False
        return _outline(analysis, config, "portrait") + shading, meta
    else:
        raise ValueError(style)

    return _outline(analysis, config) + shading, meta


def render_pen_shading_from_analysis(
    analysis: ImageUnderstandingResult,
    config: PenShadingConfig | None = None,
) -> PenShadingResult:
    """Render deterministic tonal pen geometry from an analyzed image."""
    config = config or PenShadingConfig()
    config.validate()
    polylines, extra = _recipe(analysis, config)
    polylines = [line for line in polylines if len(line) >= 2 and _length(line) >= config.min_stroke_length_px]
    if not polylines:
        raise ValueError("Pen-shading style produced no drawable geometry.")
    points = sum(len(line) for line in polylines)
    if len(polylines) > config.max_output_strokes or points > config.max_output_points:
        raise ValueError("Pen-shading style output exceeds configured geometry limits.")
    validate_polylines(polylines)
    metadata: dict[str, object] = dict(analysis.metadata)
    metadata.update({
        "pen_shading_schema": "printrbot-pen-shading/v1",
        "pen_shading_style": config.style,
        "include_outline": config.include_outline,
        "outline_style": config.outline_style,
        "hatch_spacing_px": config.hatch_spacing_px,
        "darkness_threshold": config.darkness_threshold,
        "min_stroke_length_px": config.min_stroke_length_px,
        "output_shading_strokes": len(polylines),
        "output_shading_points": points,
        "seed": config.seed,
        "angle_offset_deg": config.angle_offset_deg,
        "density_scale": config.density_scale,
    })
    metadata.update(extra)
    return PenShadingResult(polylines=polylines, metadata=metadata)


def render_pen_shading(
    source: str | Path,
    config: PenShadingConfig | None = None,
    *,
    preprocess: ImagePreprocessConfig | None = None,
    understanding: ImageUnderstandingConfig | None = None,
) -> PenShadingResult:
    """Run Steps 2-3 and render Step 6 pen shading from a raster source."""
    config = config or PenShadingConfig()
    config.validate()
    analysis = analyze_image(source, preprocess=preprocess, understanding=understanding)
    result = render_pen_shading_from_analysis(analysis, config)
    metadata = dict(analysis.metadata)
    metadata.update(result.metadata)
    return PenShadingResult(polylines=result.polylines, metadata=metadata)

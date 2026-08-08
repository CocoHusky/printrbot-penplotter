"""Deterministic Step 7 image-to-drawing auto selection.

This module analyzes the normalized Step 3 feature maps, builds a small bounded
set of candidate line-art / shading recipes, renders them through Steps 5-6,
and chooses the lowest-cost candidate. It never emits machine commands.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import math

import numpy as np

from .image_preprocess import ImagePreprocessConfig
from .image_understanding import ImageUnderstandingConfig, ImageUnderstandingResult, analyze_image
from .line_art import LineArtConfig, render_line_art_from_analysis
from .pen_shading import PenShadingConfig, render_pen_shading_from_analysis
from .models import Polylines

AutoQuality = Literal["quick", "balanced", "best"]

@dataclass(frozen=True)
class AutoOptimizeConfig:
    quality: AutoQuality = "balanced"
    max_candidates: int = 8
    prefer_shading: bool = True
    seed: int = 0

    def validate(self) -> None:
        if self.quality not in ("quick", "balanced", "best"):
            raise ValueError("quality must be quick, balanced, or best")
        if not 1 <= self.max_candidates <= 24:
            raise ValueError("max_candidates must be between 1 and 24")
        if not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")

@dataclass(frozen=True)
class AutoCandidate:
    kind: Literal["line_art", "shading"]
    style: str
    score: float
    strokes: int
    points: int
    metadata: dict[str, object]

@dataclass(frozen=True)
class AutoOptimizeResult:
    polylines: Polylines
    selected: AutoCandidate
    candidates: tuple[AutoCandidate, ...]
    metadata: dict[str, object]

def _image_metrics(a: ImageUnderstandingResult) -> dict[str, float]:
    gray = a.gray.astype(np.float64)
    return {
        "brightness": float(gray.mean() / 255.0),
        "contrast": float(gray.std() / 255.0),
        "edge_density": float(np.mean(a.selected_edges)),
        "foreground_fraction": float(np.mean(a.foreground_mask)),
        "dark_fraction": float(np.mean(gray < 128)),
        "region_density": min(1.0, len(a.regions) / 200.0),
    }

def _candidate_specs(metrics: dict[str, float], cfg: AutoOptimizeConfig) -> list[tuple[str, str]]:
    edge = metrics["edge_density"]
    dark = metrics["dark_fraction"]
    contrast = metrics["contrast"]
    specs: list[tuple[str, str]] = []
    # Always include robust outline/sketch baselines.
    specs += [("line_art", "clean_outline"), ("line_art", "refined_pen_sketch")]
    if edge < 0.16:
        specs += [("line_art", "detailed_outline"), ("line_art", "continuous_contour")]
    else:
        specs += [("line_art", "minimal_outline"), ("line_art", "comic_ink")]
    if cfg.prefer_shading and (dark > 0.12 or contrast > 0.12):
        specs += [("shading", "parallel_hatch"), ("shading", "crosshatch")]
        if cfg.quality == "best":
            specs += [("shading", "engraving"), ("shading", "contour_hatch")]
    if cfg.quality == "quick":
        specs = specs[:4]
    return specs[: cfg.max_candidates]

def _geometry_stats(lines: Polylines) -> tuple[int, int, float]:
    strokes = len(lines)
    points = sum(len(line) for line in lines)
    length = 0.0
    for line in lines:
        for a, b in zip(line, line[1:]):
            length += math.hypot(b[0]-a[0], b[1]-a[1])
    return strokes, points, length

def _score(metrics: dict[str, float], strokes: int, points: int, length: float, kind: str, style: str, quality: str) -> float:
    # Lower is better. Penalize pathological complexity and reward tonal styles
    # only when the input actually contains useful tone/contrast.
    complexity_target = {"quick": 450.0, "balanced": 1300.0, "best": 3200.0}[quality]
    complexity = strokes + points / 20.0 + length / 80.0
    complexity_penalty = abs(complexity - complexity_target) / complexity_target
    tiny_penalty = max(0.0, strokes - 5000) / 5000.0
    tonal_fit = 0.0
    if kind == "shading":
        tonal_signal = metrics["dark_fraction"] + metrics["contrast"]
        tonal_fit = max(0.0, 0.28 - tonal_signal) * 2.0
    edge_fit = 0.0
    if style in ("detailed_outline", "comic_ink") and metrics["edge_density"] > 0.30:
        edge_fit += 0.35
    if style == "minimal_outline" and metrics["edge_density"] < 0.05:
        edge_fit += 0.25
    return round(complexity_penalty + tiny_penalty + tonal_fit + edge_fit, 8)

def optimize_analysis(analysis: ImageUnderstandingResult, config: AutoOptimizeConfig | None = None) -> AutoOptimizeResult:
    cfg = config or AutoOptimizeConfig(); cfg.validate()
    metrics = _image_metrics(analysis)
    candidates: list[AutoCandidate] = []
    geometries: dict[tuple[str,str], Polylines] = {}
    for kind, style in _candidate_specs(metrics, cfg):
        try:
            if kind == "line_art":
                result = render_line_art_from_analysis(analysis, LineArtConfig(style=style))
            else:
                result = render_pen_shading_from_analysis(analysis, PenShadingConfig(style=style, seed=cfg.seed))
        except ValueError:
            continue
        strokes, points, length = _geometry_stats(result.polylines)
        score = _score(metrics, strokes, points, length, kind, style, cfg.quality)
        candidates.append(AutoCandidate(kind=kind, style=style, score=score, strokes=strokes, points=points, metadata=result.metadata))
        geometries[(kind, style)] = result.polylines
    if not candidates:
        raise ValueError("Auto optimizer produced no valid drawing candidates.")
    candidates.sort(key=lambda c: (c.score, c.kind, c.style, c.strokes, c.points))
    chosen = candidates[0]
    metadata: dict[str, object] = dict(analysis.metadata)
    metadata.update({
        "auto_optimizer_schema": "printrbot-auto-optimizer/v1",
        "auto_quality": cfg.quality,
        "auto_metrics": {k: round(v, 6) for k,v in metrics.items()},
        "auto_selected_kind": chosen.kind,
        "auto_selected_style": chosen.style,
        "auto_selected_score": chosen.score,
        "auto_candidates": [
            {"kind": c.kind, "style": c.style, "score": c.score, "strokes": c.strokes, "points": c.points}
            for c in candidates
        ],
    })
    return AutoOptimizeResult(polylines=geometries[(chosen.kind, chosen.style)], selected=chosen, candidates=tuple(candidates), metadata=metadata)

def optimize_image(source: str | Path, config: AutoOptimizeConfig | None = None, *, preprocess: ImagePreprocessConfig | None = None, understanding: ImageUnderstandingConfig | None = None) -> AutoOptimizeResult:
    analysis = analyze_image(source, preprocess=preprocess, understanding=understanding)
    return optimize_analysis(analysis, config)

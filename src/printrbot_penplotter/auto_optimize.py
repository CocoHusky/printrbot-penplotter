"""Deterministic Step 7 image-to-drawing auto selection.

Auto selection is intentionally two-stage: inexpensive image metrics rank a
bounded candidate set, then only the winning Step 5/6 recipe is rendered at full
quality. This keeps interactive Auto mode from fully vectorizing every candidate.
It never emits machine commands.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
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
    specs: list[tuple[str, str]] = [
        ("line_art", "clean_outline"),
        ("line_art", "refined_pen_sketch"),
    ]
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


def _heuristic_score(metrics: dict[str, float], kind: str, style: str, quality: str) -> float:
    """Rank style fit without rendering geometry. Lower is better."""
    edge = metrics["edge_density"]
    contrast = metrics["contrast"]
    dark = metrics["dark_fraction"]
    foreground = metrics["foreground_fraction"]
    region = metrics["region_density"]
    tonal = min(1.0, contrast + dark)

    # Robust defaults start near the front but can be displaced by image fit.
    base = {
        "clean_outline": 0.28,
        "refined_pen_sketch": 0.20,
        "detailed_outline": 0.26,
        "continuous_contour": 0.42,
        "minimal_outline": 0.34,
        "comic_ink": 0.38,
        "parallel_hatch": 0.34,
        "crosshatch": 0.31,
        "engraving": 0.39,
        "contour_hatch": 0.44,
    }.get(style, 0.5)

    score = base
    if kind == "shading":
        score += max(0.0, 0.30 - tonal) * 1.6
        score -= min(0.18, tonal * 0.16)
        if foreground > 0.82:
            score += 0.10
    else:
        score += max(0.0, 0.035 - edge) * 2.0

    if style == "minimal_outline":
        score += abs(edge - 0.22) * 0.9
    elif style == "clean_outline":
        score += abs(edge - 0.12) * 0.55
    elif style == "refined_pen_sketch":
        score += abs(edge - 0.16) * 0.35
        score -= min(0.10, contrast * 0.20)
    elif style == "detailed_outline":
        score += max(0.0, 0.08 - edge) * 1.4
        score += max(0.0, edge - 0.32) * 0.7
    elif style == "continuous_contour":
        score += region * 0.16
    elif style == "comic_ink":
        score -= min(0.12, contrast * 0.22)
        score += max(0.0, 0.10 - dark) * 0.8
    elif style == "parallel_hatch":
        score += max(0.0, 0.14 - tonal) * 0.8
    elif style == "crosshatch":
        score -= min(0.10, dark * 0.18)
    elif style == "engraving":
        score -= min(0.12, tonal * 0.14)
        score += 0.05 if quality != "best" else 0.0
    elif style == "contour_hatch":
        score += max(0.0, 0.08 - edge) * 0.8
        score += 0.04 if quality != "best" else 0.0

    # Prefer simpler visual recipes in interactive modes when fit is otherwise close.
    if quality == "quick" and style not in ("clean_outline", "minimal_outline", "refined_pen_sketch"):
        score += 0.08
    elif quality == "balanced" and style in ("engraving", "contour_hatch"):
        score += 0.05
    return round(score, 8)


def _estimated_complexity(analysis: ImageUnderstandingResult, kind: str, style: str) -> tuple[int, int]:
    """Return deterministic display-only estimates for unrendered candidates."""
    edge_pixels = int(np.count_nonzero(analysis.selected_edges))
    foreground_pixels = int(np.count_nonzero(analysis.foreground_mask))
    if kind == "shading":
        factor = {
            "parallel_hatch": 0.010,
            "crosshatch": 0.017,
            "engraving": 0.024,
            "contour_hatch": 0.020,
        }.get(style, 0.015)
        strokes = max(1, int(round(foreground_pixels * factor)))
        points = max(2, strokes * (3 if style == "contour_hatch" else 2))
    else:
        factor = {
            "minimal_outline": 0.018,
            "clean_outline": 0.024,
            "refined_pen_sketch": 0.035,
            "detailed_outline": 0.045,
            "continuous_contour": 0.025,
            "comic_ink": 0.030,
        }.get(style, 0.03)
        strokes = max(1, int(round(max(edge_pixels, 1) * factor)))
        points = max(2, strokes * 4)
    return strokes, points


def _render_candidate(
    analysis: ImageUnderstandingResult,
    candidate: AutoCandidate,
    cfg: AutoOptimizeConfig,
):
    if candidate.kind == "line_art":
        return render_line_art_from_analysis(analysis, LineArtConfig(style=candidate.style))
    return render_pen_shading_from_analysis(
        analysis,
        PenShadingConfig(style=candidate.style, seed=cfg.seed),
    )


def _geometry_stats(lines: Polylines) -> tuple[int, int]:
    return len(lines), sum(len(line) for line in lines)


def optimize_analysis(
    analysis: ImageUnderstandingResult,
    config: AutoOptimizeConfig | None = None,
) -> AutoOptimizeResult:
    cfg = config or AutoOptimizeConfig()
    cfg.validate()
    metrics = _image_metrics(analysis)

    ranked: list[AutoCandidate] = []
    for kind, style in _candidate_specs(metrics, cfg):
        estimated_strokes, estimated_points = _estimated_complexity(analysis, kind, style)
        ranked.append(
            AutoCandidate(
                kind=kind,
                style=style,
                score=_heuristic_score(metrics, kind, style, cfg.quality),
                strokes=estimated_strokes,
                points=estimated_points,
                metadata={"auto_evaluation": "heuristic", "geometry_estimated": True},
            )
        )
    if not ranked:
        raise ValueError("Auto optimizer produced no candidate recipes.")
    ranked.sort(key=lambda c: (c.score, c.kind, c.style))

    # Render only the best-ranked recipe. If a recipe unexpectedly produces no
    # geometry, fall through deterministically to the next ranked candidate.
    rendered_result = None
    selected_index = -1
    for index, candidate in enumerate(ranked):
        try:
            rendered_result = _render_candidate(analysis, candidate, cfg)
        except ValueError:
            continue
        selected_index = index
        break
    if rendered_result is None or selected_index < 0:
        raise ValueError("Auto optimizer produced no valid drawing candidates.")

    selected = ranked[selected_index]
    strokes, points = _geometry_stats(rendered_result.polylines)
    selected = replace(
        selected,
        strokes=strokes,
        points=points,
        metadata=dict(rendered_result.metadata),
    )
    ranked[selected_index] = selected

    metadata: dict[str, object] = dict(analysis.metadata)
    metadata.update({
        "auto_optimizer_schema": "printrbot-auto-optimizer/v2",
        "auto_evaluation_mode": "two_stage_heuristic_then_render_winner",
        "auto_full_renders": 1,
        "auto_quality": cfg.quality,
        "auto_metrics": {k: round(v, 6) for k, v in metrics.items()},
        "auto_selected_kind": selected.kind,
        "auto_selected_style": selected.style,
        "auto_selected_score": selected.score,
        "auto_candidates": [
            {
                "kind": c.kind,
                "style": c.style,
                "score": c.score,
                "strokes": c.strokes,
                "points": c.points,
                "geometry_estimated": bool(c.metadata.get("geometry_estimated", False)),
            }
            for c in ranked
        ],
    })
    return AutoOptimizeResult(
        polylines=rendered_result.polylines,
        selected=selected,
        candidates=tuple(ranked),
        metadata=metadata,
    )


def optimize_image(
    source: str | Path,
    config: AutoOptimizeConfig | None = None,
    *,
    preprocess: ImagePreprocessConfig | None = None,
    understanding: ImageUnderstandingConfig | None = None,
) -> AutoOptimizeResult:
    analysis = analyze_image(source, preprocess=preprocess, understanding=understanding)
    return optimize_analysis(analysis, config)

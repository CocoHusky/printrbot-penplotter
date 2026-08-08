"""Step 8 pen/plot-size-aware physical geometry preparation.

Consumes ordinary millimeter polylines after artwork creation. It removes detail
below the configured physical pen resolution, applies bounded motion routing,
and reports estimated physical complexity. It never creates artwork or G-code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import math

from .geometry import validate_polylines
from .models import PenConfig, Point, Polyline, Polylines
from .optimize import MotionConfig, MotionMetrics, optimize_motion, polyline_length

PhysicalQuality = Literal["quick", "balanced", "best"]

@dataclass(frozen=True)
class PhysicalPlotConfig:
    pen_tip_mm: float = 0.5
    quality: PhysicalQuality = "balanced"
    min_feature_factor: float = 1.25
    min_gap_factor: float = 0.85
    route_mode: Literal["authored", "nearest", "two_opt"] = "two_opt"
    allow_reverse: bool = True
    max_strokes: int = 20_000
    max_points: int = 2_000_000

    def validate(self) -> None:
        if not math.isfinite(self.pen_tip_mm) or not 0.05 <= self.pen_tip_mm <= 5.0:
            raise ValueError("pen_tip_mm must be between 0.05 and 5.0 mm")
        if self.quality not in ("quick", "balanced", "best"):
            raise ValueError("quality must be quick, balanced, or best")
        if not math.isfinite(self.min_feature_factor) or self.min_feature_factor <= 0:
            raise ValueError("min_feature_factor must be positive")
        if not math.isfinite(self.min_gap_factor) or self.min_gap_factor < 0:
            raise ValueError("min_gap_factor must be non-negative")
        if self.route_mode not in ("authored", "nearest", "two_opt"):
            raise ValueError("invalid route_mode")
        if self.max_strokes < 1 or self.max_points < 2:
            raise ValueError("geometry limits must be positive")

@dataclass(frozen=True)
class PhysicalPlotResult:
    polylines: Polylines
    before: MotionMetrics
    after: MotionMetrics
    metadata: dict[str, object]

def _distance(a: Point, b: Point) -> float:
    return math.hypot(b[0]-a[0], b[1]-a[1])

def _dedupe_close_points(line: Polyline, minimum_spacing: float) -> Polyline:
    if len(line) < 2:
        return line[:]
    result = [line[0]]
    for point in line[1:-1]:
        if _distance(result[-1], point) >= minimum_spacing:
            result.append(point)
    if line[-1] != result[-1]:
        result.append(line[-1])
    return result

def _filter_physical(lines: Polylines, cfg: PhysicalPlotConfig) -> tuple[Polylines, int, int]:
    min_feature = cfg.pen_tip_mm * cfg.min_feature_factor
    point_spacing = max(0.02, cfg.pen_tip_mm * {"quick": 0.70, "balanced": 0.40, "best": 0.22}[cfg.quality])
    out: Polylines = []
    removed_strokes = 0
    removed_points = 0
    for source in lines:
        if len(source) < 2 or polyline_length(source) < min_feature:
            removed_strokes += 1
            removed_points += len(source)
            continue
        cleaned = _dedupe_close_points(source, point_spacing)
        removed_points += max(0, len(source) - len(cleaned))
        if len(cleaned) >= 2 and polyline_length(cleaned) >= min_feature:
            out.append(cleaned)
        else:
            removed_strokes += 1
            removed_points += len(cleaned)
    return out, removed_strokes, removed_points

def prepare_physical_plot(polylines: Polylines, config: PhysicalPlotConfig | None = None, *, pen: PenConfig | None = None) -> PhysicalPlotResult:
    cfg = config or PhysicalPlotConfig(); cfg.validate()
    pen = pen or PenConfig()
    validate_polylines(polylines)
    filtered, removed_strokes, removed_points = _filter_physical(polylines, cfg)
    if not filtered:
        raise ValueError("Physical filtering removed all drawable geometry.")
    points = sum(len(line) for line in filtered)
    if len(filtered) > cfg.max_strokes or points > cfg.max_points:
        raise ValueError("Physical plot exceeds configured geometry limits.")
    join_tolerance = cfg.pen_tip_mm * cfg.min_gap_factor if cfg.quality == "quick" else 0.0
    rdp = cfg.pen_tip_mm * {"quick": 0.45, "balanced": 0.20, "best": 0.08}[cfg.quality]
    motion_cfg = MotionConfig(
        route_mode=cfg.route_mode,
        allow_reverse=cfg.allow_reverse,
        join_tolerance_mm=join_tolerance,
        rdp_tolerance_mm=rdp,
        resample_spacing_mm=0.0,
        smooth_passes=0,
        two_opt_passes={"quick": 2, "balanced": 6, "best": 12}[cfg.quality],
    )
    plan = optimize_motion(filtered, motion_cfg, pen=pen)
    metadata = {
        "physical_plot_schema": "printrbot-physical-plot/v1",
        "pen_tip_mm": cfg.pen_tip_mm,
        "physical_quality": cfg.quality,
        "minimum_feature_mm": round(cfg.pen_tip_mm * cfg.min_feature_factor, 4),
        "minimum_gap_mm": round(cfg.pen_tip_mm * cfg.min_gap_factor, 4),
        "removed_strokes": removed_strokes,
        "removed_points": removed_points,
        "input_strokes": len(polylines),
        "output_strokes": len(plan.polylines),
        "output_points": sum(len(line) for line in plan.polylines),
        "motion": plan.metadata(),
    }
    return PhysicalPlotResult(polylines=plan.polylines, before=plan.before, after=plan.after, metadata=metadata)

"""Deterministic motion-quality helpers for plotter geometry.

The optimizer never generates artwork or machine commands. It only transforms
already-created polylines, measures the resulting path, and returns deterministic
geometry for the shared preview/G-code stages.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from .geometry import validate_polylines
from .models import PenConfig, Point, Polyline, Polylines

RouteMode = Literal["authored", "nearest", "two_opt"]


@dataclass(frozen=True)
class MotionConfig:
    """Optional geometry optimization applied after artwork creation.

    All shape-changing operations are off by default. `authored` preserves the
    incoming stroke order. Text/cursive should normally keep authored order;
    independent SVG/raster artwork can opt into nearest/two-opt routing.
    """

    route_mode: RouteMode = "authored"
    allow_reverse: bool = True
    join_tolerance_mm: float = 0.0
    rdp_tolerance_mm: float = 0.0
    resample_spacing_mm: float = 0.0
    smooth_passes: int = 0
    two_opt_passes: int = 8

    def validate(self) -> None:
        if self.route_mode not in ("authored", "nearest", "two_opt"):
            raise ValueError("route_mode must be authored, nearest, or two_opt.")
        for name, value in (
            ("join_tolerance_mm", self.join_tolerance_mm),
            ("rdp_tolerance_mm", self.rdp_tolerance_mm),
            ("resample_spacing_mm", self.resample_spacing_mm),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative.")
        if self.smooth_passes < 0 or self.smooth_passes > 8:
            raise ValueError("smooth_passes must be between 0 and 8.")
        if self.two_opt_passes < 0 or self.two_opt_passes > 100:
            raise ValueError("two_opt_passes must be between 0 and 100.")


@dataclass(frozen=True)
class MotionMetrics:
    strokes: int
    points: int
    draw_distance_mm: float
    travel_distance_mm: float
    pen_lifts: int
    estimated_seconds: float

    def to_dict(self) -> dict[str, object]:
        return {
            "strokes": self.strokes,
            "points": self.points,
            "draw_distance_mm": round(self.draw_distance_mm, 3),
            "travel_distance_mm": round(self.travel_distance_mm, 3),
            "pen_lifts": self.pen_lifts,
            "estimated_seconds": round(self.estimated_seconds, 2),
        }


@dataclass(frozen=True)
class MotionPlan:
    polylines: Polylines
    before: MotionMetrics
    after: MotionMetrics
    config: MotionConfig

    def metadata(self) -> dict[str, object]:
        before = self.before.to_dict()
        after = self.after.to_dict()
        saved = self.before.travel_distance_mm - self.after.travel_distance_mm
        percent = 0.0
        if self.before.travel_distance_mm > 1e-9:
            percent = saved / self.before.travel_distance_mm * 100.0
        return {
            "motion_route_mode": self.config.route_mode,
            "motion_allow_reverse": self.config.allow_reverse,
            "motion_join_tolerance_mm": self.config.join_tolerance_mm,
            "motion_rdp_tolerance_mm": self.config.rdp_tolerance_mm,
            "motion_resample_spacing_mm": self.config.resample_spacing_mm,
            "motion_smooth_passes": self.config.smooth_passes,
            "motion_before": before,
            "motion_after": after,
            "travel_saved_mm": round(saved, 3),
            "travel_saved_percent": round(percent, 2),
        }


def _distance(first: Point, second: Point) -> float:
    return math.hypot(second[0] - first[0], second[1] - first[1])


def polyline_length(line: Polyline) -> float:
    return sum(_distance(first, second) for first, second in zip(line, line[1:]))


def draw_distance(polylines: Polylines) -> float:
    validate_polylines(polylines)
    return sum(polyline_length(line) for line in polylines if len(line) >= 2)


def pen_up_distance(polylines: Polylines, start: Point | None = None) -> float:
    """Return travel distance between disconnected strokes."""

    validate_polylines(polylines)
    total = 0.0
    previous = start
    for stroke in polylines:
        if len(stroke) < 2:
            continue
        if previous is not None:
            total += _distance(previous, stroke[0])
        previous = stroke[-1]
    return total


def optimize_stroke_order(
    polylines: Polylines,
    *,
    start: Point | None = None,
    allow_reverse: bool = True,
) -> Polylines:
    """Greedily choose the nearest remaining stroke endpoint.

    Ties retain source order and prefer authored direction. This remains a
    useful standalone API and is also the first stage of two-opt routing.
    """

    validate_polylines(polylines)
    remaining: list[tuple[int, Polyline]] = [
        (index, stroke[:]) for index, stroke in enumerate(polylines) if len(stroke) >= 2
    ]
    if not remaining:
        return []

    ordered: Polylines = []
    current = start
    while remaining:
        if current is None:
            _, chosen = remaining.pop(0)
            ordered.append(chosen)
            current = chosen[-1]
            continue

        best_position = 0
        best_reverse = False
        best_key: tuple[float, int, int] | None = None
        for position, (source_index, stroke) in enumerate(remaining):
            forward_key = (_distance(current, stroke[0]), source_index, 0)
            if best_key is None or forward_key < best_key:
                best_key = forward_key
                best_position = position
                best_reverse = False
            if allow_reverse:
                reverse_key = (_distance(current, stroke[-1]), source_index, 1)
                if best_key is None or reverse_key < best_key:
                    best_key = reverse_key
                    best_position = position
                    best_reverse = True

        _, chosen = remaining.pop(best_position)
        if best_reverse:
            chosen = list(reversed(chosen))
        ordered.append(chosen)
        current = chosen[-1]

    return ordered


def _route_cost(polylines: Polylines, start: Point | None = None) -> float:
    return pen_up_distance(polylines, start=start)


def two_opt_stroke_order(
    polylines: Polylines,
    *,
    start: Point | None = None,
    allow_reverse: bool = True,
    passes: int = 8,
) -> Polylines:
    """Refine nearest-neighbor routing with deterministic open-path 2-opt.

    Reversing a route subsection also reverses each stroke in that subsection,
    preserving each drawn segment while changing only direction/order.
    """

    ordered = optimize_stroke_order(polylines, start=start, allow_reverse=allow_reverse)
    if len(ordered) < 3 or passes <= 0:
        return ordered

    best = [stroke[:] for stroke in ordered]
    best_cost = _route_cost(best, start)
    for _ in range(passes):
        improvement: tuple[float, int, int, Polylines] | None = None
        for left in range(len(best) - 1):
            for right in range(left + 1, len(best)):
                block = best[left : right + 1]
                if allow_reverse:
                    replacement = [list(reversed(stroke)) for stroke in reversed(block)]
                else:
                    replacement = list(reversed(block))
                candidate = best[:left] + replacement + best[right + 1 :]
                cost = _route_cost(candidate, start)
                gain = best_cost - cost
                if gain <= 1e-9:
                    continue
                key = (gain, -left, -right)
                if improvement is None or key > (improvement[0], -improvement[1], -improvement[2]):
                    improvement = (gain, left, right, candidate)
        if improvement is None:
            break
        _, _, _, best = improvement
        best_cost = _route_cost(best, start)
    return best


def join_nearby_strokes(polylines: Polylines, tolerance_mm: float) -> Polylines:
    """Join consecutive ordered strokes whose endpoints are very close.

    A non-zero gap becomes a short drawn connector, so this operation is
    intentionally opt-in and should not be used blindly for text.
    """

    validate_polylines(polylines)
    if tolerance_mm <= 0:
        return [line[:] for line in polylines if len(line) >= 2]
    result: Polylines = []
    for stroke in polylines:
        if len(stroke) < 2:
            continue
        if result and _distance(result[-1][-1], stroke[0]) <= tolerance_mm:
            if result[-1][-1] == stroke[0]:
                result[-1].extend(stroke[1:])
            else:
                result[-1].extend(stroke)
        else:
            result.append(stroke[:])
    return result


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    px, py = point
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    denominator = dx * dx + dy * dy
    if denominator <= 1e-18:
        return _distance(point, start)
    position = ((px - sx) * dx + (py - sy) * dy) / denominator
    position = max(0.0, min(1.0, position))
    projection = (sx + position * dx, sy + position * dy)
    return _distance(point, projection)


def rdp_simplify(line: Polyline, tolerance_mm: float) -> Polyline:
    """Ramer-Douglas-Peucker simplification preserving endpoints."""

    if len(line) <= 2 or tolerance_mm <= 0:
        return line[:]
    keep = {0, len(line) - 1}
    stack = [(0, len(line) - 1)]
    while stack:
        left, right = stack.pop()
        if right - left <= 1:
            continue
        start, end = line[left], line[right]
        best_distance = -1.0
        best_index = -1
        for index in range(left + 1, right):
            distance = _point_segment_distance(line[index], start, end)
            if distance > best_distance:
                best_distance = distance
                best_index = index
        if best_index >= 0 and best_distance > tolerance_mm:
            keep.add(best_index)
            stack.append((left, best_index))
            stack.append((best_index, right))
    return [line[index] for index in sorted(keep)]


def resample_polyline(line: Polyline, spacing_mm: float) -> Polyline:
    """Resample a path so long segments are split at approximately fixed spacing."""

    if len(line) <= 1 or spacing_mm <= 0:
        return line[:]
    result = [line[0]]
    for start, end in zip(line, line[1:]):
        distance = _distance(start, end)
        if distance <= spacing_mm:
            result.append(end)
            continue
        pieces = max(1, int(math.ceil(distance / spacing_mm)))
        for index in range(1, pieces + 1):
            fraction = index / pieces
            result.append(
                (
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                )
            )
    return result


def smooth_polyline(line: Polyline, passes: int) -> Polyline:
    """Apply conservative endpoint-preserving three-point smoothing."""

    result = line[:]
    for _ in range(passes):
        if len(result) < 3:
            break
        smoothed = [result[0]]
        for previous, current, following in zip(result, result[1:], result[2:]):
            smoothed.append(
                (
                    previous[0] * 0.2 + current[0] * 0.6 + following[0] * 0.2,
                    previous[1] * 0.2 + current[1] * 0.6 + following[1] * 0.2,
                )
            )
        smoothed.append(result[-1])
        result = smoothed
    return result


def _corner_angle_degrees(previous: Point, current: Point, following: Point) -> float:
    first = (previous[0] - current[0], previous[1] - current[1])
    second = (following[0] - current[0], following[1] - current[1])
    first_length = math.hypot(*first)
    second_length = math.hypot(*second)
    if first_length <= 1e-12 or second_length <= 1e-12:
        return 180.0
    cosine = (first[0] * second[0] + first[1] * second[1]) / (first_length * second_length)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


def segment_is_corner_slowed(line: Polyline, segment_index: int, threshold_deg: float) -> bool:
    """Return whether a segment touches a corner sharper than the threshold.

    `segment_index` identifies the segment from point i to point i+1.
    """

    if len(line) < 3:
        return False
    if segment_index > 0:
        angle = _corner_angle_degrees(
            line[segment_index - 1], line[segment_index], line[segment_index + 1]
        )
        if angle <= threshold_deg:
            return True
    if segment_index + 2 < len(line):
        angle = _corner_angle_degrees(
            line[segment_index], line[segment_index + 1], line[segment_index + 2]
        )
        if angle <= threshold_deg:
            return True
    return False


def motion_metrics(
    polylines: Polylines,
    pen: PenConfig | None = None,
    *,
    start: Point | None = None,
) -> MotionMetrics:
    """Estimate path length, pen lifts, and idealized motion time."""

    pen = pen or PenConfig()
    validate_polylines(polylines)
    pen.validate()
    strokes = [line for line in polylines if len(line) >= 2]
    draw_mm = draw_distance(strokes)
    travel_mm = pen_up_distance(strokes, start=start)
    draw_seconds = 0.0
    for line in strokes:
        for segment_index, (first, second) in enumerate(zip(line, line[1:])):
            feed = pen.draw_feed_mm_min
            if segment_is_corner_slowed(line, segment_index, pen.corner_angle_deg):
                feed = min(feed, pen.corner_feed_mm_min)
            draw_seconds += _distance(first, second) / feed * 60.0
    travel_seconds = travel_mm / pen.travel_feed_mm_min * 60.0
    z_distance = 0.0 if pen.air_plot else abs(pen.z_up_mm - pen.z_down_mm) * 2 * len(strokes)
    z_seconds = z_distance / pen.z_feed_mm_min * 60.0
    return MotionMetrics(
        strokes=len(strokes),
        points=sum(len(line) for line in strokes),
        draw_distance_mm=draw_mm,
        travel_distance_mm=travel_mm,
        pen_lifts=len(strokes),
        estimated_seconds=draw_seconds + travel_seconds + z_seconds,
    )


def optimize_motion(
    polylines: Polylines,
    config: MotionConfig | None = None,
    *,
    pen: PenConfig | None = None,
    start: Point | None = None,
) -> MotionPlan:
    """Apply deterministic routing and optional path-quality transforms."""

    config = config or MotionConfig()
    config.validate()
    validate_polylines(polylines)
    pen = pen or PenConfig()
    before = motion_metrics(polylines, pen, start=start)

    result = [line[:] for line in polylines if len(line) >= 2]
    if config.rdp_tolerance_mm > 0:
        result = [rdp_simplify(line, config.rdp_tolerance_mm) for line in result]
    if config.resample_spacing_mm > 0:
        result = [resample_polyline(line, config.resample_spacing_mm) for line in result]
    if config.smooth_passes > 0:
        result = [smooth_polyline(line, config.smooth_passes) for line in result]

    if config.route_mode == "nearest":
        result = optimize_stroke_order(result, start=start, allow_reverse=config.allow_reverse)
    elif config.route_mode == "two_opt":
        result = two_opt_stroke_order(
            result,
            start=start,
            allow_reverse=config.allow_reverse,
            passes=config.two_opt_passes,
        )

    result = join_nearby_strokes(result, config.join_tolerance_mm)
    validate_polylines(result)
    after = motion_metrics(result, pen, start=start)
    return MotionPlan(polylines=result, before=before, after=after, config=config)

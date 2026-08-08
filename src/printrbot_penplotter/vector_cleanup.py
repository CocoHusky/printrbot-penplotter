"""Deterministic raster-vector cleanup upstream of machine placement.

Step 4 improves raw raster traces without generating styles, route ordering, or
machine commands.  Every operation is explicit and reproducible.  Shape-changing
operations default to off so legacy tracing remains unchanged unless requested.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from .geometry import validate_polylines
from .models import Point, Polyline, Polylines

SmoothingMode = Literal["none", "moving_average", "chaikin"]


@dataclass(frozen=True)
class VectorCleanupConfig:
    """Controls for deterministic trace cleanup in source-pixel coordinates."""

    min_segment_px: float = 0.0
    min_stroke_length_px: float = 0.0
    min_closed_area_px2: float = 0.0
    simplify_tolerance_px: float = 0.0
    preserve_corner_deg: float = 55.0
    smoothing: SmoothingMode = "none"
    smooth_passes: int = 0
    smooth_strength: float = 0.25
    duplicate_tolerance_px: float = 0.0
    duplicate_samples: int = 16
    join_distance_px: float = 0.0
    join_angle_deg: float = 35.0
    max_strokes: int = 20_000
    max_points: int = 2_000_000

    @classmethod
    def for_quality(cls, preset: str) -> "VectorCleanupConfig":
        """Return conservative named cleanup presets for later style/UI layers."""

        presets = {
            "raw": cls(),
            "clean": cls(
                min_segment_px=0.20,
                min_stroke_length_px=1.2,
                min_closed_area_px2=1.0,
                simplify_tolerance_px=0.35,
                duplicate_tolerance_px=0.30,
            ),
            "smooth": cls(
                min_segment_px=0.20,
                min_stroke_length_px=1.2,
                min_closed_area_px2=1.0,
                simplify_tolerance_px=0.30,
                preserve_corner_deg=50.0,
                smoothing="moving_average",
                smooth_passes=2,
                smooth_strength=0.35,
                duplicate_tolerance_px=0.30,
                join_distance_px=0.9,
                join_angle_deg=28.0,
            ),
            "flowing": cls(
                min_segment_px=0.25,
                min_stroke_length_px=1.5,
                min_closed_area_px2=1.5,
                simplify_tolerance_px=0.40,
                preserve_corner_deg=45.0,
                smoothing="chaikin",
                smooth_passes=1,
                smooth_strength=0.25,
                duplicate_tolerance_px=0.35,
                join_distance_px=1.4,
                join_angle_deg=38.0,
            ),
        }
        try:
            return presets[preset]
        except KeyError as exc:
            raise ValueError(f"Unknown vector-cleanup preset: {preset}") from exc

    def validate(self) -> None:
        for name, value in (
            ("min_segment_px", self.min_segment_px),
            ("min_stroke_length_px", self.min_stroke_length_px),
            ("min_closed_area_px2", self.min_closed_area_px2),
            ("simplify_tolerance_px", self.simplify_tolerance_px),
            ("duplicate_tolerance_px", self.duplicate_tolerance_px),
            ("join_distance_px", self.join_distance_px),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative.")
        if not math.isfinite(self.preserve_corner_deg) or not 0 <= self.preserve_corner_deg <= 180:
            raise ValueError("preserve_corner_deg must be between 0 and 180.")
        if self.smoothing not in ("none", "moving_average", "chaikin"):
            raise ValueError("Unsupported smoothing mode.")
        if not isinstance(self.smooth_passes, int) or not 0 <= self.smooth_passes <= 8:
            raise ValueError("smooth_passes must be an integer from 0 to 8.")
        if not math.isfinite(self.smooth_strength) or not 0 <= self.smooth_strength <= 0.5:
            raise ValueError("smooth_strength must be between 0 and 0.5.")
        if not isinstance(self.duplicate_samples, int) or not 4 <= self.duplicate_samples <= 128:
            raise ValueError("duplicate_samples must be an integer from 4 to 128.")
        if not math.isfinite(self.join_angle_deg) or not 0 <= self.join_angle_deg <= 180:
            raise ValueError("join_angle_deg must be between 0 and 180.")
        if not isinstance(self.max_strokes, int) or self.max_strokes < 1:
            raise ValueError("max_strokes must be positive.")
        if not isinstance(self.max_points, int) or self.max_points < 2:
            raise ValueError("max_points must be at least two.")


@dataclass(frozen=True)
class VectorCleanupResult:
    polylines: Polylines
    metadata: dict[str, object]


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _length(line: Polyline) -> float:
    return sum(_distance(a, b) for a, b in zip(line, line[1:]))


def _closed(line: Polyline) -> bool:
    return len(line) >= 3 and _distance(line[0], line[-1]) <= 1e-9


def _area(line: Polyline) -> float:
    points = line[:-1] if _closed(line) else line
    if len(points) < 3:
        return 0.0
    total = 0.0
    for a, b in zip(points, points[1:] + points[:1]):
        total += a[0] * b[1] - b[0] * a[1]
    return abs(total) * 0.5


def _dedupe_points(line: Polyline, minimum: float) -> Polyline:
    if len(line) < 2 or minimum <= 0:
        return line[:]
    closed = _closed(line)
    source = line[:-1] if closed else line
    if not source:
        return []
    result = [source[0]]
    for point in source[1:]:
        if _distance(result[-1], point) >= minimum:
            result.append(point)
    if not closed and len(result) >= 2 and result[-1] != source[-1]:
        if _distance(result[-1], source[-1]) > 1e-12:
            result.append(source[-1])
    if closed and len(result) >= 3:
        result.append(result[0])
    return result


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    denom = dx * dx + dy * dy
    if denom <= 1e-18:
        return _distance(point, start)
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denom
    t = max(0.0, min(1.0, t))
    projection = (start[0] + t * dx, start[1] + t * dy)
    return _distance(point, projection)


def _rdp(line: Polyline, epsilon: float) -> Polyline:
    if len(line) <= 2 or epsilon <= 0:
        return line[:]
    keep = {0, len(line) - 1}
    stack = [(0, len(line) - 1)]
    while stack:
        start_index, end_index = stack.pop()
        if end_index - start_index <= 1:
            continue
        best_index = -1
        best_distance = -1.0
        for index in range(start_index + 1, end_index):
            distance = _point_segment_distance(line[index], line[start_index], line[end_index])
            if distance > best_distance:
                best_distance = distance
                best_index = index
        if best_index >= 0 and best_distance > epsilon:
            keep.add(best_index)
            stack.append((start_index, best_index))
            stack.append((best_index, end_index))
    return [line[index] for index in sorted(keep)]


def _interior_angle(a: Point, b: Point, c: Point) -> float:
    first = (a[0] - b[0], a[1] - b[1])
    second = (c[0] - b[0], c[1] - b[1])
    first_norm = math.hypot(*first)
    second_norm = math.hypot(*second)
    if first_norm <= 1e-12 or second_norm <= 1e-12:
        return 180.0
    cosine = max(-1.0, min(1.0, (first[0] * second[0] + first[1] * second[1]) / (first_norm * second_norm)))
    return math.degrees(math.acos(cosine))


def _corner_indices(line: Polyline, threshold_deg: float) -> list[int]:
    if len(line) < 3 or threshold_deg <= 0:
        return []
    result: list[int] = []
    for index in range(1, len(line) - 1):
        if _interior_angle(line[index - 1], line[index], line[index + 1]) <= threshold_deg:
            result.append(index)
    return result


def _simplify_corner_aware(line: Polyline, epsilon: float, preserve_corner_deg: float) -> Polyline:
    if epsilon <= 0 or len(line) <= 2:
        return line[:]
    if _closed(line):
        points = line[:-1]
        if len(points) <= 3:
            return line[:]
        # Rotate a closed contour to its sharpest corner, then simplify as an open loop.
        angles = [
            _interior_angle(points[index - 1], points[index], points[(index + 1) % len(points)])
            for index in range(len(points))
        ]
        anchor = min(range(len(points)), key=lambda index: (angles[index], index))
        rotated = points[anchor:] + points[:anchor] + [points[anchor]]
        simplified = _simplify_corner_aware(rotated, epsilon, preserve_corner_deg)
        if len(simplified) >= 4 and simplified[0] != simplified[-1]:
            simplified.append(simplified[0])
        return simplified

    corners = _corner_indices(line, preserve_corner_deg)
    boundaries = [0] + corners + [len(line) - 1]
    result: Polyline = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= start:
            continue
        segment = _rdp(line[start : end + 1], epsilon)
        if result and segment and result[-1] == segment[0]:
            result.extend(segment[1:])
        else:
            result.extend(segment)
    return result if len(result) >= 2 else line[:]


def _smooth_moving(line: Polyline, strength: float, corner_deg: float) -> Polyline:
    if len(line) < 3 or strength <= 0:
        return line[:]
    closed = _closed(line)
    points = line[:-1] if closed else line[:]
    if len(points) < 3:
        return line[:]
    result = points[:]
    for index in range(len(points)):
        if not closed and index in (0, len(points) - 1):
            continue
        previous = points[index - 1]
        current = points[index]
        following = points[(index + 1) % len(points)]
        if _interior_angle(previous, current, following) <= corner_deg:
            continue
        average = ((previous[0] + following[0]) * 0.5, (previous[1] + following[1]) * 0.5)
        result[index] = (
            current[0] * (1.0 - strength) + average[0] * strength,
            current[1] * (1.0 - strength) + average[1] * strength,
        )
    if closed:
        result.append(result[0])
    return result


def _smooth_chaikin(line: Polyline, strength: float, corner_deg: float) -> Polyline:
    if len(line) < 3 or strength <= 0:
        return line[:]
    closed = _closed(line)
    points = line[:-1] if closed else line[:]
    if len(points) < 3:
        return line[:]
    output: Polyline = [] if closed else [points[0]]
    pair_count = len(points) if closed else len(points) - 1
    for index in range(pair_count):
        a = points[index]
        b = points[(index + 1) % len(points)]
        preserve_a = index > 0 and _interior_angle(points[index - 1], a, b) <= corner_deg
        preserve_b = _interior_angle(a, b, points[(index + 2) % len(points)]) <= corner_deg if (closed or index + 2 < len(points)) else False
        if preserve_a or preserve_b:
            if not output or output[-1] != a:
                output.append(a)
            output.append(b)
            continue
        q = (a[0] * (1.0 - strength) + b[0] * strength, a[1] * (1.0 - strength) + b[1] * strength)
        r = (a[0] * strength + b[0] * (1.0 - strength), a[1] * strength + b[1] * (1.0 - strength))
        if not output or output[-1] != q:
            output.append(q)
        output.append(r)
    if not closed and output[-1] != points[-1]:
        output.append(points[-1])
    if closed and output:
        if output[-1] != output[0]:
            output.append(output[0])
    return output


def _resample(line: Polyline, samples: int) -> Polyline:
    if len(line) < 2:
        return line[:]
    lengths = [0.0]
    for a, b in zip(line, line[1:]):
        lengths.append(lengths[-1] + _distance(a, b))
    total = lengths[-1]
    if total <= 1e-12:
        return [line[0]] * samples
    result: Polyline = []
    segment = 0
    for index in range(samples):
        target = total * index / max(samples - 1, 1)
        while segment + 1 < len(lengths) and lengths[segment + 1] < target:
            segment += 1
        if segment + 1 >= len(line):
            result.append(line[-1])
            continue
        span = lengths[segment + 1] - lengths[segment]
        t = 0.0 if span <= 1e-12 else (target - lengths[segment]) / span
        a, b = line[segment], line[segment + 1]
        result.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return result


def _sample_distance(first: Polyline, second: Polyline, samples: int) -> float:
    a = _resample(first, samples)
    b = _resample(second, samples)
    forward = sum(_distance(x, y) for x, y in zip(a, b)) / samples
    reverse = sum(_distance(x, y) for x, y in zip(a, reversed(b))) / samples
    return min(forward, reverse)


def _remove_duplicates(lines: Polylines, tolerance: float, samples: int) -> tuple[Polylines, int]:
    if tolerance <= 0:
        return [line[:] for line in lines], 0
    result: Polylines = []
    removed = 0
    for line in lines:
        length = _length(line)
        duplicate = False
        for existing in result:
            existing_length = _length(existing)
            if abs(length - existing_length) > max(tolerance * 4.0, 0.05 * max(length, existing_length, 1.0)):
                continue
            if _sample_distance(line, existing, samples) <= tolerance:
                duplicate = True
                break
        if duplicate:
            removed += 1
        else:
            result.append(line[:])
    return result, removed


def _tangent(line: Polyline, at_start: bool) -> Point:
    if len(line) < 2:
        return (0.0, 0.0)
    a, b = (line[0], line[1]) if at_start else (line[-2], line[-1])
    return (b[0] - a[0], b[1] - a[1])


def _angle_between(first: Point, second: Point) -> float:
    first_norm = math.hypot(*first)
    second_norm = math.hypot(*second)
    if first_norm <= 1e-12 or second_norm <= 1e-12:
        return 180.0
    cosine = max(-1.0, min(1.0, (first[0] * second[0] + first[1] * second[1]) / (first_norm * second_norm)))
    return math.degrees(math.acos(cosine))


def _join_candidate(first: Polyline, second: Polyline, max_distance: float, max_angle: float) -> tuple[float, Polyline] | None:
    if _closed(first) or _closed(second):
        return None
    options = [
        (first, second),
        (first, list(reversed(second))),
        (list(reversed(first)), second),
        (list(reversed(first)), list(reversed(second))),
    ]
    best: tuple[float, Polyline] | None = None
    for left, right in options:
        gap = _distance(left[-1], right[0])
        if gap > max_distance:
            continue
        incoming = _tangent(left, False)
        outgoing = _tangent(right, True)
        if _angle_between(incoming, outgoing) > max_angle:
            continue
        joined = left[:] + ([] if left[-1] == right[0] else [right[0]]) + right[1:]
        candidate = (gap, joined)
        if best is None or (candidate[0], tuple(candidate[1])) < (best[0], tuple(best[1])):
            best = candidate
    return best


def _join_lines(lines: Polylines, distance: float, angle: float) -> tuple[Polylines, int, float]:
    if distance <= 0 or len(lines) < 2:
        return [line[:] for line in lines], 0, 0.0
    work = [line[:] for line in lines]
    joins = 0
    bridge_length = 0.0
    while True:
        best: tuple[float, int, int, Polyline] | None = None
        for first_index in range(len(work)):
            for second_index in range(first_index + 1, len(work)):
                candidate = _join_candidate(work[first_index], work[second_index], distance, angle)
                if candidate is None:
                    continue
                gap, joined = candidate
                record = (gap, first_index, second_index, joined)
                if best is None or record[:3] < best[:3]:
                    best = record
        if best is None:
            break
        gap, first_index, second_index, joined = best
        work[first_index] = joined
        del work[second_index]
        joins += 1
        bridge_length += gap
    return work, joins, bridge_length


def cleanup_polylines(polylines: Polylines, config: VectorCleanupConfig | None = None) -> VectorCleanupResult:
    """Clean raw trace geometry deterministically without route reordering."""

    config = config or VectorCleanupConfig()
    config.validate()
    validate_polylines(polylines)
    if len(polylines) > config.max_strokes:
        raise ValueError(f"Vector cleanup exceeds the {config.max_strokes} stroke limit.")
    input_points = sum(len(line) for line in polylines)
    if input_points > config.max_points:
        raise ValueError(f"Vector cleanup exceeds the {config.max_points} point limit.")

    lines: Polylines = []
    removed_short = 0
    removed_loops = 0
    removed_points = 0
    for source in polylines:
        line = _dedupe_points(source, config.min_segment_px)
        removed_points += max(0, len(source) - len(line))
        if len(line) < 2:
            removed_short += 1
            continue
        if _closed(line) and config.min_closed_area_px2 > 0 and _area(line) < config.min_closed_area_px2:
            removed_loops += 1
            continue
        if not _closed(line) and config.min_stroke_length_px > 0 and _length(line) < config.min_stroke_length_px:
            removed_short += 1
            continue
        line = _simplify_corner_aware(line, config.simplify_tolerance_px, config.preserve_corner_deg)
        for _ in range(config.smooth_passes):
            if config.smoothing == "moving_average":
                line = _smooth_moving(line, config.smooth_strength, config.preserve_corner_deg)
            elif config.smoothing == "chaikin":
                line = _smooth_chaikin(line, config.smooth_strength, config.preserve_corner_deg)
        if len(line) >= 2:
            lines.append(line)

    lines, duplicates_removed = _remove_duplicates(lines, config.duplicate_tolerance_px, config.duplicate_samples)
    lines, joins_made, bridge_length = _join_lines(lines, config.join_distance_px, config.join_angle_deg)

    output_points = sum(len(line) for line in lines)
    if len(lines) > config.max_strokes or output_points > config.max_points:
        raise ValueError("Vector cleanup output exceeds configured geometry limits.")
    if not lines:
        raise ValueError("Vector cleanup removed all drawable geometry.")
    validate_polylines(lines)

    metadata: dict[str, object] = {
        "vector_cleanup_schema": "printrbot-vector-cleanup/v1",
        "input_strokes": len(polylines),
        "output_strokes": len(lines),
        "input_points": input_points,
        "output_points": output_points,
        "input_length_px": round(sum(_length(line) for line in polylines), 6),
        "output_length_px": round(sum(_length(line) for line in lines), 6),
        "points_removed_by_min_segment": removed_points,
        "short_strokes_removed": removed_short,
        "tiny_loops_removed": removed_loops,
        "duplicates_removed": duplicates_removed,
        "joins_made": joins_made,
        "bridge_length_px": round(bridge_length, 6),
        "min_segment_px": config.min_segment_px,
        "min_stroke_length_px": config.min_stroke_length_px,
        "min_closed_area_px2": config.min_closed_area_px2,
        "simplify_tolerance_px": config.simplify_tolerance_px,
        "preserve_corner_deg": config.preserve_corner_deg,
        "smoothing": config.smoothing,
        "smooth_passes": config.smooth_passes,
        "smooth_strength": config.smooth_strength,
        "duplicate_tolerance_px": config.duplicate_tolerance_px,
        "join_distance_px": config.join_distance_px,
        "join_angle_deg": config.join_angle_deg,
    }
    return VectorCleanupResult(polylines=lines, metadata=metadata)

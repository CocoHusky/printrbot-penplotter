"""Spatially bounded vector cleanup for image/style rendering.

The public Step 4 cleanup implementation intentionally stays simple and exact for
its standalone API and tests.  Style rendering can contain hundreds or thousands
of short traces, where repeated all-pairs duplicate/join scans become quadratic
or worse.  This module preserves the same duplicate-distance and join-candidate
semantics while limiting comparisons to spatially nearby candidates.
"""

from __future__ import annotations

from dataclasses import replace
import math

from .geometry import validate_polylines
from .models import Point, Polyline, Polylines
from .vector_cleanup import (
    VectorCleanupConfig,
    VectorCleanupResult,
    _closed,
    _join_candidate,
    _length,
    _sample_distance,
    cleanup_polylines,
)


def _cell(point: Point, size: float) -> tuple[int, int]:
    return (math.floor(point[0] / size), math.floor(point[1] / size))


def _neighbor_cells(cell: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    x, y = cell
    return tuple((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))


def _centroid(line: Polyline) -> Point:
    count = max(1, len(line))
    return (
        sum(point[0] for point in line) / count,
        sum(point[1] for point in line) / count,
    )


def _remove_duplicates_spatial(
    lines: Polylines,
    tolerance: float,
    samples: int,
) -> tuple[Polylines, int]:
    if tolerance <= 0:
        return [line[:] for line in lines], 0

    # A duplicate whose mean sampled distance is <= tolerance must occupy the
    # same local region.  A 4*tolerance cell plus neighboring-cell lookup keeps
    # the candidate set bounded while the exact _sample_distance remains the
    # final decision rule.
    cell_size = max(1.0, tolerance * 4.0)
    buckets: dict[tuple[int, int], list[int]] = {}
    result: Polylines = []
    lengths: list[float] = []
    removed = 0

    for line in lines:
        length = _length(line)
        center_cell = _cell(_centroid(line), cell_size)
        candidates: set[int] = set()
        for key in _neighbor_cells(center_cell):
            candidates.update(buckets.get(key, ()))

        duplicate = False
        for index in sorted(candidates):
            existing = result[index]
            existing_length = lengths[index]
            if abs(length - existing_length) > max(
                tolerance * 4.0,
                0.05 * max(length, existing_length, 1.0),
            ):
                continue
            if _sample_distance(line, existing, samples) <= tolerance:
                duplicate = True
                break

        if duplicate:
            removed += 1
            continue

        index = len(result)
        result.append(line[:])
        lengths.append(length)
        buckets.setdefault(center_cell, []).append(index)

    return result, removed


def _endpoint_index(lines: Polylines, distance: float) -> dict[tuple[int, int], set[int]]:
    buckets: dict[tuple[int, int], set[int]] = {}
    for index, line in enumerate(lines):
        if len(line) < 2 or _closed(line):
            continue
        for point in (line[0], line[-1]):
            buckets.setdefault(_cell(point, distance), set()).add(index)
    return buckets


def _join_lines_spatial(
    lines: Polylines,
    distance: float,
    angle: float,
) -> tuple[Polylines, int, float]:
    if distance <= 0 or len(lines) < 2:
        return [line[:] for line in lines], 0, 0.0

    work = [line[:] for line in lines]
    joins = 0
    bridge_length = 0.0

    while True:
        buckets = _endpoint_index(work, distance)
        best: tuple[float, int, int, Polyline] | None = None
        seen_pairs: set[tuple[int, int]] = set()

        for first_index, first in enumerate(work):
            if len(first) < 2 or _closed(first):
                continue
            nearby: set[int] = set()
            for endpoint in (first[0], first[-1]):
                for key in _neighbor_cells(_cell(endpoint, distance)):
                    nearby.update(buckets.get(key, ()))

            for second_index in sorted(nearby):
                if second_index <= first_index:
                    continue
                pair = (first_index, second_index)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                candidate = _join_candidate(
                    first,
                    work[second_index],
                    distance,
                    angle,
                )
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


def cleanup_polylines_fast(
    polylines: Polylines,
    config: VectorCleanupConfig | None = None,
) -> VectorCleanupResult:
    """Run Step 4 cleanup with spatially bounded duplicate/join passes.

    Shape transforms, thresholds, and exact duplicate/join acceptance rules are
    unchanged.  Only candidate discovery is accelerated.
    """

    config = config or VectorCleanupConfig()
    config.validate()

    base_config = replace(
        config,
        duplicate_tolerance_px=0.0,
        join_distance_px=0.0,
    )
    base = cleanup_polylines(polylines, base_config)

    lines, duplicates_removed = _remove_duplicates_spatial(
        base.polylines,
        config.duplicate_tolerance_px,
        config.duplicate_samples,
    )
    lines, joins_made, bridge_length = _join_lines_spatial(
        lines,
        config.join_distance_px,
        config.join_angle_deg,
    )
    validate_polylines(lines)

    output_points = sum(len(line) for line in lines)
    if len(lines) > config.max_strokes or output_points > config.max_points:
        raise ValueError("Vector cleanup output exceeds configured geometry limits.")

    metadata = dict(base.metadata)
    metadata.update(
        {
            "output_strokes": len(lines),
            "output_points": output_points,
            "output_length_px": round(sum(_length(line) for line in lines), 6),
            "duplicates_removed": duplicates_removed,
            "joins_made": joins_made,
            "bridge_length_px": round(bridge_length, 6),
            "duplicate_tolerance_px": config.duplicate_tolerance_px,
            "join_distance_px": config.join_distance_px,
            "join_angle_deg": config.join_angle_deg,
            "cleanup_candidate_index": "spatial-v1",
        }
    )
    return VectorCleanupResult(polylines=lines, metadata=metadata)

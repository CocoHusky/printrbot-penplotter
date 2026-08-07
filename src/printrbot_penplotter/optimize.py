"""Deterministic stroke-order helpers for reducing pen-up travel."""

from __future__ import annotations

import math

from .geometry import validate_polylines
from .models import Point, Polyline, Polylines


def _distance(first: Point, second: Point) -> float:
    return math.hypot(second[0] - first[0], second[1] - first[1])


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

    This is intentionally deterministic: ties retain source order and prefer the
    authored direction. It is useful for independent artwork and within a
    multi-stroke glyph. Whole-word handwriting should normally retain authored
    character order so joins and legibility remain predictable.
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
            source_index, chosen = remaining.pop(0)
            del source_index
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

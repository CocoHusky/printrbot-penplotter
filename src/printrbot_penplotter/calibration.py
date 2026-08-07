"""Known-size calibration geometry for safe machine validation."""

from __future__ import annotations

import math

from .models import Polylines


def square_cross_pattern(size_mm: float = 10.0, gap_mm: float = 4.0) -> Polylines:
    """Return a known-size square, cross, octagon, and pen-lift test.

    The pattern intentionally contains several disconnected strokes so an air
    plot can verify scale, axis direction, corner behavior, and pen-up travel
    before generated artwork is sent to the machine.
    """

    for name, value in (("size_mm", size_mm), ("gap_mm", gap_mm)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive.")

    square = [
        (0.0, 0.0),
        (size_mm, 0.0),
        (size_mm, size_mm),
        (0.0, size_mm),
        (0.0, 0.0),
    ]

    cross_x = size_mm + gap_mm
    cross = [
        (cross_x, 0.0),
        (cross_x + size_mm, size_mm),
        (cross_x + size_mm / 2.0, size_mm / 2.0),
        (cross_x + size_mm, 0.0),
        (cross_x, size_mm),
    ]

    center_x = size_mm / 2.0
    center_y = size_mm + gap_mm + size_mm / 2.0
    radius = size_mm / 2.0
    octagon = [
        (
            center_x + radius * math.cos(math.radians(22.5 + index * 45.0)),
            center_y + radius * math.sin(math.radians(22.5 + index * 45.0)),
        )
        for index in range(8)
    ]
    octagon.append(octagon[0])

    lift_y = size_mm + gap_mm
    pen_lift_left = [(cross_x, lift_y), (cross_x + size_mm * 0.35, lift_y)]
    pen_lift_right = [
        (cross_x + size_mm * 0.65, lift_y),
        (cross_x + size_mm, lift_y),
    ]

    return [square, cross, octagon, pen_lift_left, pen_lift_right]

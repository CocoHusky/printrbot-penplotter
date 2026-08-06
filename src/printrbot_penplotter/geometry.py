"""Geometry transforms shared by every input type."""

from __future__ import annotations

import html
import math
from collections.abc import Iterable

from .models import PageConfig, Point, Polyline, Polylines


def bounds(polylines: Iterable[Polyline]) -> tuple[float, float, float, float]:
    points = [point for line in polylines for point in line]
    if not points:
        raise ValueError("No drawable geometry was produced.")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def fit_to_page(
    polylines: Polylines,
    page: PageConfig,
    *,
    allow_upscale: bool = True,
) -> Polylines:
    """Scale and center geometry inside the configured page margin."""

    page.validate()
    min_x, min_y, max_x, max_y = bounds(polylines)
    source_width = max(max_x - min_x, 1e-9)
    source_height = max(max_y - min_y, 1e-9)
    target_width = page.width_mm - 2 * page.margin_mm
    target_height = page.height_mm - 2 * page.margin_mm
    scale = min(target_width / source_width, target_height / source_height)
    if not allow_upscale:
        scale = min(scale, 1.0)

    drawn_width = source_width * scale
    drawn_height = source_height * scale
    offset_x = page.margin_mm + (target_width - drawn_width) / 2
    offset_y = page.margin_mm + (target_height - drawn_height) / 2

    fitted: Polylines = []
    for line in polylines:
        if len(line) < 2:
            continue
        fitted.append(
            [
                (
                    (x - min_x) * scale + offset_x,
                    (y - min_y) * scale + offset_y,
                )
                for x, y in line
            ]
        )
    if not fitted:
        raise ValueError("No drawable polylines remained after processing.")
    return fitted


def simplify_polyline(line: Polyline, tolerance_mm: float = 0.04) -> Polyline:
    """Remove consecutive points that are closer than the given tolerance."""

    if len(line) <= 2:
        return line[:]
    simplified = [line[0]]
    for point in line[1:]:
        previous = simplified[-1]
        if math.hypot(point[0] - previous[0], point[1] - previous[1]) >= tolerance_mm:
            simplified.append(point)
    if simplified[-1] != line[-1]:
        simplified.append(line[-1])
    return simplified


def simplify_polylines(polylines: Polylines, tolerance_mm: float = 0.04) -> Polylines:
    return [
        simplified
        for line in polylines
        if len(simplified := simplify_polyline(line, tolerance_mm)) >= 2
    ]


def rotate_scale_translate(
    line: Polyline,
    *,
    origin: Point,
    rotation_deg: float,
    scale: float,
    translate_x: float,
    translate_y: float,
) -> Polyline:
    radians = math.radians(rotation_deg)
    cos_value = math.cos(radians)
    sin_value = math.sin(radians)
    ox, oy = origin
    transformed: Polyline = []
    for x, y in line:
        local_x = (x - ox) * scale
        local_y = (y - oy) * scale
        transformed.append(
            (
                ox + local_x * cos_value - local_y * sin_value + translate_x,
                oy + local_x * sin_value + local_y * cos_value + translate_y,
            )
        )
    return transformed


def preview_svg(polylines: Polylines, page: PageConfig) -> str:
    """Create a dependency-free SVG preview using the exact machine geometry."""

    page.validate()
    path_parts: list[str] = []
    for line in polylines:
        if len(line) < 2:
            continue
        commands = [f"M {line[0][0]:.3f} {page.height_mm - line[0][1]:.3f}"]
        commands.extend(
            f"L {x:.3f} {page.height_mm - y:.3f}" for x, y in line[1:]
        )
        path_parts.append(
            f'<path d="{html.escape(" ".join(commands), quote=True)}" '
            'fill="none" stroke="black" stroke-width="0.35" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {page.width_mm:.3f} {page.height_mm:.3f}" '
        f'width="{page.width_mm:.3f}mm" height="{page.height_mm:.3f}mm">'
        '<rect width="100%" height="100%" fill="white"/>'
        + "".join(path_parts)
        + "</svg>"
    )

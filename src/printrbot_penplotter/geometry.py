"""Geometry transforms shared by every input type."""

from __future__ import annotations

import html
import math
from collections.abc import Iterable

from .models import LayoutConfig, MachineConfig, PageConfig, Point, Polyline, Polylines

# Core geometry limits are hard memory guards, not normal artistic quality limits.
# Studio 2 applies its own adjustable soft limits before geometry reaches this layer.
# Keeping the hard guard higher allows an explicitly raised/bypassed Studio soft limit
# to pass through placement, preview, and G-code validation without disabling bounds.
MAX_STROKES = 200_000
MAX_POINTS = 20_000_000


def validate_polylines(polylines: Iterable[Polyline]) -> None:
    """Reject malformed, non-finite, or unreasonably large geometry."""

    stroke_count = 0
    point_count = 0
    for stroke_index, line in enumerate(polylines, start=1):
        stroke_count += 1
        if stroke_count > MAX_STROKES:
            raise ValueError(f"Geometry exceeds the {MAX_STROKES} stroke safety limit.")
        for point_index, point in enumerate(line, start=1):
            if len(point) != 2:
                raise ValueError(f"Stroke {stroke_index}, point {point_index} is not an XY pair.")
            x, y = point
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError(
                    f"Stroke {stroke_index}, point {point_index} contains a non-finite coordinate."
                )
            point_count += 1
            if point_count > MAX_POINTS:
                raise ValueError(f"Geometry exceeds the {MAX_POINTS} point safety limit.")


def bounds(polylines: Iterable[Polyline]) -> tuple[float, float, float, float]:
    materialized = list(polylines)
    validate_polylines(materialized)
    points = [point for line in materialized for point in line]
    if not points:
        raise ValueError("No drawable geometry was produced.")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def compensate_pen_contact(polylines: Polylines, radius_mm: float) -> Polylines:
    """Extend open stroke ends by the pen-contact radius.

    A ball-point's ink contact is approximately its tip radius beyond the
    carriage's mathematical centerline. Extending each open endpoint along
    its tangent lets adjacent strokes meet instead of leaving a tiny gap.
    Closed loops are unchanged, and the returned geometry is a new list.
    """

    if not math.isfinite(radius_mm) or radius_mm < 0:
        raise ValueError("Pen contact radius must be finite and non-negative.")
    validate_polylines(polylines)
    if radius_mm == 0:
        return [line[:] for line in polylines]

    compensated: Polylines = []
    for line in polylines:
        if len(line) < 2 or line[0] == line[-1]:
            compensated.append(line[:])
            continue
        start_x, start_y = line[0]
        next_x, next_y = line[1]
        end_x, end_y = line[-1]
        previous_x, previous_y = line[-2]
        start_length = math.hypot(next_x - start_x, next_y - start_y)
        end_length = math.hypot(end_x - previous_x, end_y - previous_y)
        updated = line[:]
        if start_length > 1e-9:
            updated[0] = (
                start_x - radius_mm * (next_x - start_x) / start_length,
                start_y - radius_mm * (next_y - start_y) / start_length,
            )
        if end_length > 1e-9:
            updated[-1] = (
                end_x + radius_mm * (end_x - previous_x) / end_length,
                end_y + radius_mm * (end_y - previous_y) / end_length,
            )
        compensated.append(updated)
    validate_polylines(compensated)
    return compensated


def place_on_page(
    polylines: Polylines,
    page: PageConfig,
    layout: LayoutConfig | None = None,
    machine: MachineConfig | None = None,
) -> Polylines:
    """Place millimeter geometry on paper in absolute machine coordinates.

    ``downscale`` is the safe default: requested physical size is preserved
    unless the drawing would exceed the drawable paper rectangle. ``none``
    refuses oversize geometry. ``fit`` expands or shrinks geometry to fill the
    available rectangle, matching the original prototype behavior.
    """

    machine = machine or MachineConfig()
    layout = layout or LayoutConfig()
    machine.validate()
    page.validate(machine)
    layout.validate()
    validate_polylines(polylines)

    min_x, min_y, max_x, max_y = bounds(polylines)
    source_width = max(max_x - min_x, 1e-9)
    source_height = max(max_y - min_y, 1e-9)
    target_width = page.drawable_width_mm
    target_height = page.drawable_height_mm
    maximum_fit_scale = min(target_width / source_width, target_height / source_height)

    if layout.fit_mode == "fit":
        scale = maximum_fit_scale
    elif layout.fit_mode == "downscale":
        scale = min(layout.scale, maximum_fit_scale)
    else:
        scale = layout.scale

    drawn_width = source_width * scale
    drawn_height = source_height * scale
    tolerance = 1e-6
    if drawn_width > target_width + tolerance or drawn_height > target_height + tolerance:
        raise ValueError(
            "Drawing does not fit the configured paper area. Use fit_mode='downscale' "
            "or reduce the physical size."
        )

    drawable_x = page.origin_x_mm + page.margin_mm
    drawable_y = page.origin_y_mm + page.margin_mm

    if layout.horizontal_align == "left":
        target_min_x = drawable_x
    elif layout.horizontal_align == "right":
        target_min_x = drawable_x + target_width - drawn_width
    else:
        target_min_x = drawable_x + (target_width - drawn_width) / 2

    if layout.vertical_align == "bottom":
        target_min_y = drawable_y
    elif layout.vertical_align == "top":
        target_min_y = drawable_y + target_height - drawn_height
    else:
        target_min_y = drawable_y + (target_height - drawn_height) / 2

    target_min_x += layout.offset_x_mm
    target_min_y += layout.offset_y_mm

    placed: Polylines = []
    for line in polylines:
        if len(line) < 2:
            continue
        placed.append(
            [
                (
                    (x - min_x) * scale + target_min_x,
                    (y - min_y) * scale + target_min_y,
                )
                for x, y in line
            ]
        )

    if not placed:
        raise ValueError("No drawable polylines remained after processing.")
    validate_polylines(placed)
    return placed


def flip_y_in_page(polylines: Polylines, page: PageConfig) -> Polylines:
    """Mirror machine-space paths vertically within a page rectangle.

    Raster-derived geometry is produced in image coordinates (origin at the
    top-left, Y increasing downward), while the plotter uses Cartesian
    coordinates (origin at the bottom-left, Y increasing upward).  Interactive
    Studio previews may already be placed on the page before the final-size
    transform runs, so this small shared transform keeps those previews in the
    same orientation as the final machine output.
    """

    page.validate()
    validate_polylines(polylines)
    page_center_y = page.origin_y_mm + page.height_mm * 0.5
    mirrored = [
        [(x, 2.0 * page_center_y - y) for x, y in line]
        for line in polylines
    ]
    validate_polylines(mirrored)
    return mirrored


def fit_to_page(
    polylines: Polylines,
    page: PageConfig,
    *,
    allow_upscale: bool = True,
) -> Polylines:
    """Compatibility wrapper for the pre-0.2 layout API."""

    mode = "fit" if allow_upscale else "downscale"
    return place_on_page(polylines, page, LayoutConfig(fit_mode=mode))


def simplify_polyline(line: Polyline, tolerance_mm: float = 0.04) -> Polyline:
    """Remove consecutive points that are closer than the given tolerance."""

    if not math.isfinite(tolerance_mm) or tolerance_mm < 0:
        raise ValueError("Simplification tolerance must be finite and non-negative.")
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
    validate_polylines(polylines)
    result = [
        simplified
        for line in polylines
        if len(simplified := simplify_polyline(line, tolerance_mm)) >= 2
    ]
    validate_polylines(result)
    return result


def rotate_scale_translate(
    line: Polyline,
    *,
    origin: Point,
    rotation_deg: float,
    scale: float,
    translate_x: float,
    translate_y: float,
) -> Polyline:
    for name, value in (
        ("rotation_deg", rotation_deg),
        ("scale", scale),
        ("translate_x", translate_x),
        ("translate_y", translate_y),
    ):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite.")
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
                ox * 0 + oy + local_x * sin_value + local_y * cos_value + translate_y,
            )
        )
    return transformed


def preview_svg(
    polylines: Polylines,
    page: PageConfig,
    machine: MachineConfig | None = None,
    *,
    show_travel: bool = True,
) -> str:
    """Create an exact machine-space preview with paper and travel moves."""

    machine = machine or MachineConfig()
    machine.validate()
    page.validate(machine)
    validate_polylines(polylines)

    def svg_y(machine_y: float) -> float:
        return machine.y_min_mm + machine.y_max_mm - machine_y

    path_parts: list[str] = []
    travel_parts: list[str] = []
    previous_end: Point | None = None

    for line in polylines:
        if len(line) < 2:
            continue
        start = line[0]
        if show_travel and previous_end is not None:
            travel_parts.append(
                f'<path d="M {previous_end[0]:.3f} {svg_y(previous_end[1]):.3f} '
                f'L {start[0]:.3f} {svg_y(start[1]):.3f}" '
                'fill="none" stroke="#8aa0b5" stroke-width="0.18" '
                'stroke-dasharray="1.2 1.2"/>'
            )
        commands = [f"M {start[0]:.3f} {svg_y(start[1]):.3f}"]
        commands.extend(f"L {x:.3f} {svg_y(y):.3f}" for x, y in line[1:])
        path_parts.append(
            f'<path d="{html.escape(" ".join(commands), quote=True)}" '
            'fill="none" stroke="black" stroke-width="0.35" '
            'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        previous_end = line[-1]

    page_top = svg_y(page.origin_y_mm + page.height_mm)
    margin_top = svg_y(page.origin_y_mm + page.height_mm - page.margin_mm)
    # A light 10 mm grid makes the text size and placement understandable in
    # the preview without putting labels inside the drawable area.
    grid_parts: list[str] = []
    tick_parts: list[str] = []
    for x in range(0, int(page.width_mm) + 1, 10):
        grid_parts.append(
            f'<path d="M {page.origin_x_mm + x:.3f} {page_top:.3f} '
            f'V {page_top + page.height_mm:.3f}" '
            'stroke="#d9e1e8" stroke-width="0.16"/>'
        )
        tick_parts.append(
            f'<text x="{page.origin_x_mm + x:.3f}" y="{page_top - 1.5:.3f}" '
            'text-anchor="middle" font-size="2.5" fill="#718394">'
            f'{x}</text>'
        )
    for y in range(0, int(page.height_mm) + 1, 10):
        grid_parts.append(
            f'<path d="M {page.origin_x_mm:.3f} {page_top + y:.3f} '
            f'H {page.origin_x_mm + page.width_mm:.3f}" '
            'stroke="#d9e1e8" stroke-width="0.16"/>'
        )
        tick_parts.append(
            f'<text x="{page.origin_x_mm - 1.5:.3f}" y="{page_top + y + 0.9:.3f}" '
            'text-anchor="end" font-size="2.5" fill="#718394">'
            f'{y}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{machine.x_min_mm:.3f} {machine.y_min_mm:.3f} '
        f'{machine.width_mm:.3f} {machine.height_mm:.3f}" '
        f'width="{machine.width_mm:.3f}mm" height="{machine.height_mm:.3f}mm">'
        '<rect width="100%" height="100%" fill="#e7edf2"/>'
        f'<rect x="{page.origin_x_mm:.3f}" y="{page_top:.3f}" '
        f'width="{page.width_mm:.3f}" height="{page.height_mm:.3f}" '
        'fill="white" stroke="#506578" stroke-width="0.35"/>'
        + "".join(grid_parts)
        + "".join(tick_parts)
        + f'<rect x="{page.origin_x_mm + page.margin_mm:.3f}" y="{margin_top:.3f}" '
        f'width="{page.drawable_width_mm:.3f}" height="{page.drawable_height_mm:.3f}" '
        'fill="none" stroke="#b5c0ca" stroke-width="0.2" stroke-dasharray="1.5 1.5"/>'
        + "".join(travel_parts)
        + "".join(path_parts)
        + "</svg>"
    )

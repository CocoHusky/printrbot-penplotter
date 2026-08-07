"""Raster image and handwriting tracing into the shared polyline model."""

from __future__ import annotations

import html
import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .geometry import validate_polylines
from .models import Point, Polyline, Polylines

TraceMode = Literal["centerline", "contour"]


@dataclass(frozen=True)
class RasterTraceConfig:
    """Deterministic preprocessing and tracing controls for raster inputs."""

    mode: TraceMode = "centerline"
    threshold: int | None = None
    invert: bool = False
    blur_radius_px: float = 0.0
    min_component_px: int = 8
    max_dimension_px: int = 1200
    max_input_pixels: int = 40_000_000
    max_processed_pixels: int = 1_500_000
    skeleton_max_iterations: int = 256
    simplify_px: float = 0.8

    def validate(self) -> None:
        if self.mode not in ("centerline", "contour"):
            raise ValueError("Raster trace mode must be 'centerline' or 'contour'.")
        if self.threshold is not None and not 0 <= self.threshold <= 255:
            raise ValueError("Raster threshold must be between 0 and 255.")
        if not math.isfinite(self.blur_radius_px) or self.blur_radius_px < 0:
            raise ValueError("Raster blur radius must be finite and non-negative.")
        if self.min_component_px < 1:
            raise ValueError("Minimum raster component size must be at least one pixel.")
        if self.max_dimension_px < 16:
            raise ValueError("Maximum raster dimension must be at least 16 pixels.")
        if self.max_input_pixels < 256:
            raise ValueError("Maximum raster input pixels is unreasonably small.")
        if self.max_processed_pixels < 256:
            raise ValueError("Maximum processed raster pixels is unreasonably small.")
        if self.skeleton_max_iterations < 1:
            raise ValueError("Skeleton iteration limit must be positive.")
        if not math.isfinite(self.simplify_px) or self.simplify_px < 0:
            raise ValueError("Raster simplification tolerance must be finite and non-negative.")


@dataclass(frozen=True)
class RasterTraceResult:
    polylines: Polylines
    metadata: dict[str, object]


def _otsu_threshold(gray: np.ndarray) -> int:
    histogram = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = float(gray.size)
    weighted_total = float(np.dot(np.arange(256, dtype=np.float64), histogram))
    background_weight = 0.0
    background_sum = 0.0
    best_variance = -1.0
    best_threshold = 127

    for threshold in range(256):
        count = histogram[threshold]
        background_weight += count
        if background_weight <= 0:
            continue
        foreground_weight = total - background_weight
        if foreground_weight <= 0:
            break
        background_sum += threshold * count
        background_mean = background_sum / background_weight
        foreground_mean = (weighted_total - background_sum) / foreground_weight
        variance = (
            background_weight
            * foreground_weight
            * (background_mean - foreground_mean) ** 2
        )
        if variance > best_variance:
            best_variance = variance
            best_threshold = threshold

    return int(best_threshold)


def _load_grayscale(
    source: Path,
    config: RasterTraceConfig,
) -> tuple[np.ndarray, tuple[int, int], float]:
    if not source.is_file():
        raise FileNotFoundError(source)

    try:
        image = Image.open(source)
    except Exception as exc:
        raise ValueError(f"Raster image could not be opened: {source}") from exc

    with image:
        image = ImageOps.exif_transpose(image)
        original_width, original_height = image.size
        if original_width < 1 or original_height < 1:
            raise ValueError("Raster image has invalid dimensions.")
        if original_width * original_height > config.max_input_pixels:
            raise ValueError(
                f"Raster image exceeds the {config.max_input_pixels:,}-pixel input limit."
            )

        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            white.alpha_composite(rgba)
            image = white.convert("L")
        else:
            image = image.convert("L")

        longest = max(image.size)
        scale = min(1.0, config.max_dimension_px / float(longest))
        if scale < 1.0:
            resized = (
                max(1, int(round(image.width * scale))),
                max(1, int(round(image.height * scale))),
            )
            image = image.resize(resized, Image.Resampling.LANCZOS)

        if image.width * image.height > config.max_processed_pixels:
            secondary_scale = math.sqrt(
                config.max_processed_pixels / float(image.width * image.height)
            )
            resized = (
                max(1, int(math.floor(image.width * secondary_scale))),
                max(1, int(math.floor(image.height * secondary_scale))),
            )
            image = image.resize(resized, Image.Resampling.LANCZOS)
            scale *= secondary_scale

        if config.blur_radius_px > 0:
            image = image.filter(ImageFilter.GaussianBlur(config.blur_radius_px))

        gray = np.asarray(image, dtype=np.uint8)

    return gray, (original_width, original_height), scale


_NEIGHBORS_8 = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)


def _remove_small_components(
    mask: np.ndarray,
    minimum_pixels: int,
) -> tuple[np.ndarray, int, int, int]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    cleaned = np.zeros_like(mask, dtype=bool)
    kept_components = 0
    removed_components = 0
    removed_pixels = 0

    for row, column in zip(*np.nonzero(mask)):
        row = int(row)
        column = int(column)
        if visited[row, column]:
            continue

        queue: deque[tuple[int, int]] = deque([(row, column)])
        visited[row, column] = True
        component: list[tuple[int, int]] = []

        while queue:
            current_row, current_column = queue.popleft()
            component.append((current_row, current_column))
            for delta_row, delta_column in _NEIGHBORS_8:
                neighbor_row = current_row + delta_row
                neighbor_column = current_column + delta_column
                if (
                    0 <= neighbor_row < height
                    and 0 <= neighbor_column < width
                    and mask[neighbor_row, neighbor_column]
                    and not visited[neighbor_row, neighbor_column]
                ):
                    visited[neighbor_row, neighbor_column] = True
                    queue.append((neighbor_row, neighbor_column))

        if len(component) >= minimum_pixels:
            kept_components += 1
            rows, columns = zip(*component)
            cleaned[np.asarray(rows), np.asarray(columns)] = True
        else:
            removed_components += 1
            removed_pixels += len(component)

    return cleaned, kept_components, removed_components, removed_pixels


def _neighbor_planes(image: np.ndarray) -> tuple[np.ndarray, ...]:
    padded = np.pad(image, 1, mode="constant", constant_values=False)
    return (
        padded[:-2, 1:-1],
        padded[:-2, 2:],
        padded[1:-1, 2:],
        padded[2:, 2:],
        padded[2:, 1:-1],
        padded[2:, :-2],
        padded[1:-1, :-2],
        padded[:-2, :-2],
    )


def _skeletonize(
    mask: np.ndarray,
    maximum_iterations: int,
) -> tuple[np.ndarray, int, bool]:
    image = mask.astype(bool, copy=True)
    if not image.any():
        return image, 0, True

    for iteration in range(1, maximum_iterations + 1):
        changed = False
        for phase in (0, 1):
            p2, p3, p4, p5, p6, p7, p8, p9 = _neighbor_planes(image)
            neighbor_count = (
                p2.astype(np.uint8)
                + p3.astype(np.uint8)
                + p4.astype(np.uint8)
                + p5.astype(np.uint8)
                + p6.astype(np.uint8)
                + p7.astype(np.uint8)
                + p8.astype(np.uint8)
                + p9.astype(np.uint8)
            )
            transitions = (
                ((~p2) & p3).astype(np.uint8)
                + ((~p3) & p4).astype(np.uint8)
                + ((~p4) & p5).astype(np.uint8)
                + ((~p5) & p6).astype(np.uint8)
                + ((~p6) & p7).astype(np.uint8)
                + ((~p7) & p8).astype(np.uint8)
                + ((~p8) & p9).astype(np.uint8)
                + ((~p9) & p2).astype(np.uint8)
            )
            remove = (
                image
                & (neighbor_count >= 2)
                & (neighbor_count <= 6)
                & (transitions == 1)
            )
            if phase == 0:
                remove &= ~(p2 & p4 & p6)
                remove &= ~(p4 & p6 & p8)
            else:
                remove &= ~(p2 & p4 & p8)
                remove &= ~(p2 & p6 & p8)

            if remove.any():
                image[remove] = False
                changed = True

        if not changed:
            return image, iteration, True

    return image, maximum_iterations, False


def _edge_key(
    first: tuple[int, int],
    second: tuple[int, int],
) -> tuple[tuple[int, int], tuple[int, int]]:
    return (first, second) if first <= second else (second, first)


def _trace_skeleton(mask: np.ndarray) -> Polylines:
    points = {(int(row), int(column)) for row, column in zip(*np.nonzero(mask))}
    if not points:
        return []

    def neighbors(point: tuple[int, int]) -> list[tuple[int, int]]:
        row, column = point
        result: list[tuple[int, int]] = []
        for delta_row, delta_column in _NEIGHBORS_8:
            candidate = (row + delta_row, column + delta_column)
            if candidate in points:
                result.append(candidate)
        result.sort()
        return result

    degree = {point: len(neighbors(point)) for point in points}
    visited_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    pixel_lines: list[list[tuple[int, int]]] = []

    def walk(
        start: tuple[int, int],
        first_neighbor: tuple[int, int],
        *,
        stop_at_branch: bool,
    ) -> list[tuple[int, int]]:
        line = [start]
        previous = start
        current = first_neighbor
        visited_edges.add(_edge_key(previous, current))

        while True:
            line.append(current)
            if stop_at_branch and degree[current] != 2:
                break
            candidates = [
                candidate
                for candidate in neighbors(current)
                if candidate != previous
                and _edge_key(current, candidate) not in visited_edges
            ]
            if not candidates:
                break
            next_point = candidates[0]
            visited_edges.add(_edge_key(current, next_point))
            previous, current = current, next_point
            if current == start:
                line.append(current)
                break

        return line

    starts = sorted(point for point, point_degree in degree.items() if point_degree != 2)
    for start in starts:
        for neighbor in neighbors(start):
            if _edge_key(start, neighbor) in visited_edges:
                continue
            line = walk(start, neighbor, stop_at_branch=True)
            if len(line) >= 2:
                pixel_lines.append(line)

    for start in sorted(points):
        for neighbor in neighbors(start):
            if _edge_key(start, neighbor) in visited_edges:
                continue
            line = walk(start, neighbor, stop_at_branch=False)
            if len(line) >= 2:
                pixel_lines.append(line)

    height = mask.shape[0]
    return [
        [
            (float(column) + 0.5, float(height - 1 - row) + 0.5)
            for row, column in line
        ]
        for line in pixel_lines
    ]


def _trace_contours(mask: np.ndarray) -> Polylines:
    height, width = mask.shape
    outgoing: dict[tuple[int, int], list[tuple[int, int]]] = {}
    all_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()

    def add_edge(start: tuple[int, int], end: tuple[int, int]) -> None:
        outgoing.setdefault(start, []).append(end)
        all_edges.add((start, end))

    for row, column in zip(*np.nonzero(mask)):
        row = int(row)
        column = int(column)
        if row == 0 or not mask[row - 1, column]:
            add_edge((column, row), (column + 1, row))
        if column == width - 1 or not mask[row, column + 1]:
            add_edge((column + 1, row), (column + 1, row + 1))
        if row == height - 1 or not mask[row + 1, column]:
            add_edge((column + 1, row + 1), (column, row + 1))
        if column == 0 or not mask[row, column - 1]:
            add_edge((column, row + 1), (column, row))

    for candidates in outgoing.values():
        candidates.sort()

    visited: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    contours: Polylines = []
    for edge in sorted(all_edges):
        if edge in visited:
            continue
        start, end = edge
        visited.add(edge)
        line = [start, end]
        current = end

        while current != start:
            candidates = [
                candidate
                for candidate in outgoing.get(current, ())
                if (current, candidate) not in visited
            ]
            if not candidates:
                break
            next_point = candidates[0]
            visited.add((current, next_point))
            line.append(next_point)
            current = next_point

        if len(line) >= 3:
            contours.append([(float(x), float(height - y)) for x, y in line])

    return contours


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    px, py = point
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    denominator = dx * dx + dy * dy
    if denominator <= 1e-18:
        return math.hypot(px - sx, py - sy)
    position = ((px - sx) * dx + (py - sy) * dy) / denominator
    position = max(0.0, min(1.0, position))
    projection_x = sx + position * dx
    projection_y = sy + position * dy
    return math.hypot(px - projection_x, py - projection_y)


def _rdp_open(line: Polyline, epsilon: float) -> Polyline:
    if len(line) <= 2 or epsilon <= 0:
        return line[:]

    keep = {0, len(line) - 1}
    stack = [(0, len(line) - 1)]
    while stack:
        start_index, end_index = stack.pop()
        if end_index - start_index <= 1:
            continue
        start = line[start_index]
        end = line[end_index]
        best_distance = -1.0
        best_index: int | None = None
        for index in range(start_index + 1, end_index):
            distance = _point_segment_distance(line[index], start, end)
            if distance > best_distance:
                best_distance = distance
                best_index = index
        if best_index is not None and best_distance > epsilon:
            keep.add(best_index)
            stack.append((start_index, best_index))
            stack.append((best_index, end_index))

    return [line[index] for index in sorted(keep)]


def _rdp_closed(line: Polyline, epsilon: float) -> Polyline:
    points = line[:-1] if len(line) >= 2 and line[0] == line[-1] else line[:]
    if len(points) <= 3 or epsilon <= 0:
        result = points[:]
        if result and result[0] != result[-1]:
            result.append(result[0])
        return result

    first_split = max(
        range(len(points)),
        key=lambda index: math.hypot(
            points[index][0] - points[0][0],
            points[index][1] - points[0][1],
        ),
    )
    second_split = max(
        range(len(points)),
        key=lambda index: math.hypot(
            points[index][0] - points[first_split][0],
            points[index][1] - points[first_split][1],
        ),
    )
    first_split, second_split = sorted((first_split, second_split))
    if first_split == second_split:
        result = points[:]
        result.append(result[0])
        return result

    arc_one = points[first_split : second_split + 1]
    arc_two = points[second_split:] + points[: first_split + 1]
    simplified_one = _rdp_open(arc_one, epsilon)
    simplified_two = _rdp_open(arc_two, epsilon)
    combined = simplified_one[:-1] + simplified_two[:-1]
    if len(combined) < 3:
        combined = points[:]
    combined.append(combined[0])
    return combined


def _simplify_trace(polylines: Polylines, epsilon: float) -> Polylines:
    result: Polylines = []
    for line in polylines:
        if len(line) < 2:
            continue
        closed = len(line) >= 3 and line[0] == line[-1]
        simplified = _rdp_closed(line, epsilon) if closed else _rdp_open(line, epsilon)
        if len(simplified) >= 2:
            result.append(simplified)
    return result


def trace_raster(
    source: str | Path,
    config: RasterTraceConfig | None = None,
) -> RasterTraceResult:
    """Trace an image into centerlines or contours before machine placement."""

    config = config or RasterTraceConfig()
    config.validate()
    source_path = Path(source)
    gray, original_size, resize_scale = _load_grayscale(source_path, config)
    threshold = config.threshold if config.threshold is not None else _otsu_threshold(gray)
    mask = gray > threshold if config.invert else gray <= threshold
    initial_foreground = int(np.count_nonzero(mask))
    if initial_foreground == 0:
        raise ValueError(
            "Raster preprocessing found no foreground pixels. Adjust threshold or inversion."
        )

    cleaned, kept_components, removed_components, removed_pixels = _remove_small_components(
        mask,
        config.min_component_px,
    )
    cleaned_foreground = int(np.count_nonzero(cleaned))
    if cleaned_foreground == 0:
        raise ValueError(
            "Raster cleanup removed every foreground component. Reduce min_component_px."
        )

    skeleton_iterations = 0
    skeleton_converged = True
    traced_mask = cleaned
    if config.mode == "centerline":
        traced_mask, skeleton_iterations, skeleton_converged = _skeletonize(
            cleaned,
            config.skeleton_max_iterations,
        )
        polylines = _trace_skeleton(traced_mask)
    else:
        polylines = _trace_contours(cleaned)

    polylines = _simplify_trace(polylines, config.simplify_px)
    if not polylines:
        raise ValueError("Raster tracing produced no drawable polylines.")
    validate_polylines(polylines)

    metadata: dict[str, object] = {
        "source": str(source_path),
        "trace_mode": config.mode,
        "threshold": threshold,
        "threshold_mode": "manual" if config.threshold is not None else "otsu",
        "invert": config.invert,
        "blur_radius_px": config.blur_radius_px,
        "min_component_px": config.min_component_px,
        "original_width_px": original_size[0],
        "original_height_px": original_size[1],
        "processed_width_px": int(gray.shape[1]),
        "processed_height_px": int(gray.shape[0]),
        "resize_scale": round(float(resize_scale), 6),
        "foreground_pixels_before_cleanup": initial_foreground,
        "foreground_pixels_after_cleanup": cleaned_foreground,
        "components_kept": kept_components,
        "components_removed": removed_components,
        "pixels_removed": removed_pixels,
        "trace_strokes": len(polylines),
        "trace_points": sum(len(line) for line in polylines),
        "simplify_px": config.simplify_px,
    }
    if config.mode == "centerline":
        metadata.update(
            {
                "skeleton_pixels": int(np.count_nonzero(traced_mask)),
                "skeleton_iterations": skeleton_iterations,
                "skeleton_converged": skeleton_converged,
            }
        )

    return RasterTraceResult(polylines=polylines, metadata=metadata)


def editable_trace_svg(polylines: Polylines) -> str:
    """Export raw traced paths as simple SVG for optional manual correction."""

    validate_polylines(polylines)
    points = [point for line in polylines for point in line]
    if not points:
        raise ValueError("No traced geometry is available for SVG export.")

    min_x = min(x for x, _ in points)
    min_y = min(y for _, y in points)
    max_x = max(x for x, _ in points)
    max_y = max(y for _, y in points)
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    padding = 2.0

    paths: list[str] = []
    for line in polylines:
        display = [(x, min_y + max_y - y) for x, y in line]
        commands = [f"M {display[0][0]:.3f} {display[0][1]:.3f}"]
        commands.extend(f"L {x:.3f} {y:.3f}" for x, y in display[1:])
        paths.append(
            '<path d="'
            + html.escape(" ".join(commands), quote=True)
            + '" fill="none" stroke="black" stroke-width="1" '
            + 'stroke-linecap="round" stroke-linejoin="round"/>'
        )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{min_x - padding:.3f} {min_y - padding:.3f} '
        f'{width + padding * 2:.3f} {height + padding * 2:.3f}">'
        '<rect width="100%" height="100%" fill="white"/>'
        + "".join(paths)
        + "</svg>"
    )

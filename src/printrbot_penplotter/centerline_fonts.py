"""Raster-font to single-centerline conversion for scripts without stroke packs."""

from __future__ import annotations

from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .models import Point, Polylines, StyleConfig


def _skeletonize(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen thinning, kept local to avoid a heavyweight CV dependency."""

    image = mask.astype(bool).copy()
    height, width = image.shape
    changed = True
    while changed:
        changed = False
        for phase in (0, 1):
            remove: list[tuple[int, int]] = []
            for row in range(1, height - 1):
                for col in range(1, width - 1):
                    if not image[row, col]:
                        continue
                    p = [
                        image[row - 1, col], image[row - 1, col + 1],
                        image[row, col + 1], image[row + 1, col + 1],
                        image[row + 1, col], image[row + 1, col - 1],
                        image[row, col - 1], image[row - 1, col - 1],
                    ]
                    neighbors = sum(p)
                    transitions = sum(not p[index] and p[(index + 1) % 8] for index in range(8))
                    if not (2 <= neighbors <= 6 and transitions == 1):
                        continue
                    if phase == 0:
                        allowed = not (p[0] and p[2] and p[4]) and not (p[2] and p[4] and p[6])
                    else:
                        allowed = not (p[0] and p[2] and p[6]) and not (p[0] and p[4] and p[6])
                    if allowed:
                        remove.append((row, col))
            if remove:
                changed = True
                for row, col in remove:
                    image[row, col] = False
    return image


def _skeleton_paths(skeleton: np.ndarray) -> list[list[tuple[int, int]]]:
    pixels = {tuple(point) for point in np.argwhere(skeleton)}
    neighbors = {
        point: [
            (point[0] + row_delta, point[1] + col_delta)
            for row_delta in (-1, 0, 1)
            for col_delta in (-1, 0, 1)
            if (row_delta or col_delta)
            and (point[0] + row_delta, point[1] + col_delta) in pixels
        ]
        for point in pixels
    }
    nodes = {point for point, adjacent in neighbors.items() if len(adjacent) != 2}
    used: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    paths: list[list[tuple[int, int]]] = []

    def edge(a: tuple[int, int], b: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
        return (a, b) if a <= b else (b, a)

    for node in sorted(nodes):
        for first in neighbors[node]:
            if edge(node, first) in used:
                continue
            path = [node]
            previous, current = node, first
            used.add(edge(previous, current))
            path.append(current)
            while current not in nodes:
                options = [candidate for candidate in neighbors[current] if candidate != previous]
                if not options:
                    break
                previous, current = current, options[0]
                if edge(previous, current) in used:
                    break
                used.add(edge(previous, current))
                path.append(current)
            if len(path) >= 3:
                paths.append(path)

    # Closed loops have no endpoint/junction node.
    for start in sorted(pixels):
        for first in neighbors[start]:
            if edge(start, first) in used:
                continue
            path = [start, first]
            used.add(edge(start, first))
            previous, current = start, first
            while True:
                options = [candidate for candidate in neighbors[current] if candidate != previous]
                if not options:
                    break
                candidate = options[0]
                if edge(current, candidate) in used:
                    break
                used.add(edge(current, candidate))
                path.append(candidate)
                previous, current = current, candidate
            if len(path) >= 3:
                paths.append(path)
    # Thinning can split one glyph into tiny graph edges at a junction. Join
    # only the globally nearest one-pixel endpoints; a broad radius or greedy
    # path-order join creates chords that look like random marks.
    while len(paths) > 1:
        closest: tuple[int, int, int, int, int] | None = None
        for first_index, first in enumerate(paths):
            for second_index in range(first_index + 1, len(paths)):
                second = paths[second_index]
                for first_end, first_point in enumerate((first[0], first[-1])):
                    for second_end, second_point in enumerate((second[0], second[-1])):
                        distance = max(
                            abs(first_point[0] - second_point[0]),
                            abs(first_point[1] - second_point[1]),
                        )
                        candidate = (distance, first_index, second_index, first_end, second_end)
                        if closest is None or candidate < closest:
                            closest = candidate
        # At the higher raster resolution used by the converter, diagonal
        # joins can be several pixels apart even when they are one glyph
        # stroke. Join only close endpoints; the deterministic tie-breaker
        # prevents random-looking bridges between unrelated parts.
        if closest is None or closest[0] > 8:
            break
        _, first_index, second_index, first_end, second_end = closest
        first = paths[first_index]
        second = paths[second_index]
        if first_end == 0:
            first = list(reversed(first))
        if second_end == 1:
            second = list(reversed(second))
        paths[first_index] = first + second
        paths.pop(second_index)
    return paths


def _glyph_paths(character: str, font_path: str, pixel_size: int = 192) -> tuple[list[list[Point]], float]:
    font = ImageFont.truetype(font_path, pixel_size)
    padding = 10
    ascent, descent = font.getmetrics()
    width = max(24, int(font.getlength(character)) + 2 * padding)
    height = max(24, ascent + descent + 2 * padding)
    baseline_row = padding + ascent
    image = Image.new("L", (width, height), 0)
    # Render every glyph against the same font baseline. Rendering each glyph
    # in its own bbox makes descenders such as p and g jump upward.
    ImageDraw.Draw(image).text(
        (padding, baseline_row),
        character,
        font=font,
        fill=255,
        anchor="ls",
    )
    paths = _skeleton_paths(_skeletonize(np.asarray(image) > 0))
    scale = pixel_size / 1.0
    converted = [
        [((col - padding) / scale, (baseline_row - row) / scale) for row, col in path]
        for path in paths
        if len(path) >= 3
    ]
    advance = float(font.getlength(character)) / scale
    return converted, max(advance, 0.5)


def text_to_centerline_polylines(text: str, style: StyleConfig, font_path: str) -> Polylines:
    """Render arbitrary installed-font glyphs as thinned centerline paths."""

    if not Path(font_path).is_file():
        raise FileNotFoundError(font_path)
    if not text:
        raise ValueError("Text input cannot be empty.")
    scale_mm = style.font_size_mm
    # More pixels make diagonal strokes (K, X, 4, k) smoother before thinning.
    px_size = 192
    font = ImageFont.truetype(font_path, px_size)
    line_height = style.font_size_mm * style.line_spacing * 1.35
    cursor_x = 0.0
    cursor_y = 0.0
    output: Polylines = []
    tokens = re.findall(r"\n|[ \t]+|[^\s]+", text)
    for token in tokens:
        if token == "\n":
            cursor_x = 0.0
            cursor_y -= line_height
            continue
        if token.isspace():
            space_width = max(float(font.getlength(token)) / px_size * scale_mm, scale_mm * style.word_spacing_em)
            cursor_x += space_width
            continue

        word_width = sum(float(font.getlength(character)) / px_size * scale_mm for character in token)
        word_width += max(0, len(token) - 1) * style.letter_spacing_mm
        if style.wrap_width_mm is not None and cursor_x > 0 and cursor_x + word_width > style.wrap_width_mm:
            cursor_x = 0.0
            cursor_y -= line_height

        for character in token:
            advance_width = float(font.getlength(character)) / px_size * scale_mm
            if style.wrap_width_mm is not None and cursor_x > 0 and cursor_x + advance_width > style.wrap_width_mm:
                cursor_x = 0.0
                cursor_y -= line_height
            paths, advance = _glyph_paths(character, font_path, px_size)
            for path in paths:
                output.append([(x * scale_mm + cursor_x, y * scale_mm + cursor_y) for x, y in path])
            cursor_x += advance * scale_mm + style.letter_spacing_mm
    if not output:
        raise ValueError("The supplied text produced no centerline glyphs.")
    return output


def text_to_mixed_centerlines(text: str, style: StyleConfig, font_path: str) -> Polylines:
    """Use authored single-stroke Latin and skeletonized paths only for CJK."""

    from .writing import stroke_text_to_polylines

    output: Polylines = []
    cursor_x = 0.0
    cursor_y = 0.0
    line_height = style.font_size_mm * style.line_spacing * 1.35
    font = ImageFont.truetype(font_path, 96)

    def is_cjk(character: str) -> bool:
        codepoint = ord(character)
        return (
            0x3400 <= codepoint <= 0x4DBF
            or 0x4E00 <= codepoint <= 0x9FFF
            or 0x3040 <= codepoint <= 0x30FF
            or 0xAC00 <= codepoint <= 0xD7AF
        )

    for character in text:
        if character == "\n":
            cursor_x = 0.0
            cursor_y -= line_height
            continue
        if character.isspace():
            cursor_x += max(
                float(font.getlength(character)) / 96 * style.font_size_mm,
                style.font_size_mm * style.word_spacing_em,
            )
            continue

        if is_cjk(character):
            paths, advance = _glyph_paths(character, font_path)
            for path in paths:
                output.append([(x * style.font_size_mm + cursor_x, y * style.font_size_mm + cursor_y) for x, y in path])
            cursor_x += advance * style.font_size_mm + style.letter_spacing_mm
            continue

        glyph_lines = stroke_text_to_polylines(character, style).polylines
        max_x = 0.0
        min_x = 0.0
        for path in glyph_lines:
            shifted = [(x + cursor_x, y + cursor_y) for x, y in path]
            output.append(shifted)
            min_x = min(min_x, min(point[0] for point in path))
            max_x = max(max_x, max(point[0] for point in path))
        cursor_x += max(max_x - min_x, style.font_size_mm * 0.28) + style.letter_spacing_mm

    if not output:
        raise ValueError("The supplied text produced no centerline glyphs.")
    return output

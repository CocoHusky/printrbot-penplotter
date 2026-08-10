"""Raster-font to single-centerline conversion for scripts without stroke packs."""

from __future__ import annotations

from pathlib import Path

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

    for node in nodes:
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
    for start in pixels:
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
    # A junction is allowed to continue into another branch. Pairing paths at
    # shared endpoints turns the many tiny graph edges produced by thinning
    # into long pen strokes without drawing across empty glyph space.
    def close(first: tuple[int, int], second: tuple[int, int]) -> bool:
        # Small raster gaps are artifacts of thinning, not intentional pen
        # lifts. Joining within this radius keeps CJK glyphs compact while
        # avoiding long bridges across separate components.
        return max(abs(first[0] - second[0]), abs(first[1] - second[1])) <= 7

    changed = True
    while changed:
        changed = False
        for first_index, first in enumerate(paths):
            joined = False
            for second_index in range(first_index + 1, len(paths)):
                second = paths[second_index]
                if close(first[-1], second[0]):
                    paths[first_index] = first + second[1:]
                elif close(first[-1], second[-1]):
                    paths[first_index] = first + list(reversed(second[:-1]))
                elif close(first[0], second[0]):
                    paths[first_index] = list(reversed(first[1:])) + second
                elif close(first[0], second[-1]):
                    paths[first_index] = second + first[1:]
                else:
                    continue
                paths.pop(second_index)
                changed = True
                joined = True
                break
            if joined:
                break
    return paths


def _glyph_paths(character: str, font_path: str, pixel_size: int = 96) -> tuple[list[list[Point]], float]:
    font = ImageFont.truetype(font_path, pixel_size)
    left, top, right, bottom = font.getbbox(character)
    padding = 10
    width = max(24, right - left + 2 * padding)
    height = max(24, bottom - top + 2 * padding)
    image = Image.new("L", (width, height), 0)
    ImageDraw.Draw(image).text((padding - left, padding - top), character, font=font, fill=255)
    paths = _skeleton_paths(_skeletonize(np.asarray(image) > 0))
    scale = pixel_size / 1.0
    converted = [
        [((col - padding) / scale, (height - row - padding) / scale) for row, col in path]
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
    px_size = 96
    font = ImageFont.truetype(font_path, px_size)
    line_height = style.font_size_mm * style.line_spacing * 1.35
    cursor_x = 0.0
    cursor_y = 0.0
    output: Polylines = []
    for character in text:
        if character == "\n":
            cursor_x = 0.0
            cursor_y -= line_height
            continue
        if character.isspace():
            cursor_x += max(float(font.getlength(character)) / px_size * scale_mm, scale_mm * style.word_spacing_em)
            continue
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

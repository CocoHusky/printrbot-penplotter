"""Single-line stroke-font data model, built-in fonts, and JSON loading.

Coordinates are normalized so one unit equals the font cap height. Glyphs are
made from authored centerline strokes rather than outlines, allowing a real pen
to draw each mark once instead of tracing both sides of a filled font.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .models import Point

Stroke = tuple[Point, ...]
GlyphStrokes = tuple[Stroke, ...]


def _finite_point(name: str, point: Point) -> None:
    if len(point) != 2 or not all(math.isfinite(value) for value in point):
        raise ValueError(f"{name} must be a finite XY point.")


@dataclass(frozen=True)
class GlyphVariant:
    """One authored way to draw a character."""

    strokes: GlyphStrokes
    advance: float
    entry: Point | None = None
    exit: Point | None = None
    label: str = "base"

    def validate(self) -> None:
        if not math.isfinite(self.advance) or self.advance <= 0:
            raise ValueError("Glyph advance must be finite and positive.")
        if not self.strokes:
            raise ValueError("A glyph variant must contain at least one stroke.")
        for stroke_index, stroke in enumerate(self.strokes, start=1):
            if len(stroke) < 2:
                raise ValueError(f"Glyph stroke {stroke_index} needs at least two points.")
            for point_index, point in enumerate(stroke, start=1):
                _finite_point(f"Glyph stroke {stroke_index}, point {point_index}", point)
        if self.entry is not None:
            _finite_point("Glyph entry", self.entry)
        if self.exit is not None:
            _finite_point("Glyph exit", self.exit)


@dataclass(frozen=True)
class StrokeFont:
    """A collection of centerline glyphs in normalized cap-height units."""

    name: str
    glyphs: Mapping[str, tuple[GlyphVariant, ...]]
    cap_height: float = 1.0
    line_height: float = 1.35
    fallback: str = "?"
    description: str = ""

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Stroke font name cannot be empty.")
        if not math.isfinite(self.cap_height) or self.cap_height <= 0:
            raise ValueError("Stroke font cap height must be finite and positive.")
        if not math.isfinite(self.line_height) or self.line_height <= 0:
            raise ValueError("Stroke font line height must be finite and positive.")
        if self.fallback not in self.glyphs:
            raise ValueError(f"Stroke font fallback glyph {self.fallback!r} is missing.")
        for character, variants in self.glyphs.items():
            if len(character) != 1:
                raise ValueError(f"Glyph keys must be one character, got {character!r}.")
            if not variants:
                raise ValueError(f"Glyph {character!r} has no variants.")
            for variant in variants:
                variant.validate()

    def variants_for(self, character: str) -> tuple[GlyphVariant, ...]:
        return self.glyphs.get(character, self.glyphs[self.fallback])


def _stroke(*points: Point) -> Stroke:
    return tuple(points)


def _dot(center: Point, radius: float = 0.035) -> Stroke:
    """Make a small closed circular mark that a ball-point pen can ink.

    A two-point "dot" has effectively zero travel, so many plotters will
    barely touch the paper and leave no visible mark.  A tiny closed circle
    gives the pen measurable motion while remaining a single minimal stroke.
    """

    x, y = center
    points = tuple(
        (x + math.cos(angle) * radius, y + math.sin(angle) * radius)
        for angle in tuple(2.0 * math.pi * index / 8.0 for index in range(9))
    )
    return _stroke(*points)


def _glyph(
    *strokes: Stroke,
    advance: float = 1.0,
    entry: Point | None = None,
    exit: Point | None = None,
    label: str = "base",
) -> GlyphVariant:
    return GlyphVariant(tuple(strokes), advance, entry, exit, label)


def _transform_variant(
    source: GlyphVariant,
    *,
    key: str,
    label: str,
    width_scale: float,
    slant: float,
    wobble: float,
) -> GlyphVariant:
    """Create a stable authored alternate from a base centerline glyph."""

    digest = hashlib.sha256(key.encode("utf-8")).digest()

    def transform(point: Point, index: int) -> Point:
        x, y = point
        byte = digest[index % len(digest)]
        signed = (byte / 255.0) * 2.0 - 1.0
        return (
            x * width_scale + slant * y + signed * wobble,
            y + signed * wobble * 0.55,
        )

    transformed: list[Stroke] = []
    point_index = 0
    for stroke in source.strokes:
        points: list[Point] = []
        for point in stroke:
            points.append(transform(point, point_index))
            point_index += 1
        transformed.append(tuple(points))

    def anchor(point: Point | None) -> Point | None:
        if point is None:
            return None
        x, y = point
        return (x * width_scale + slant * y, y)

    return GlyphVariant(
        strokes=tuple(transformed),
        advance=source.advance * width_scale,
        entry=anchor(source.entry),
        exit=anchor(source.exit),
        label=label,
    )


def _hand_variants(character: str, base: GlyphVariant) -> tuple[GlyphVariant, ...]:
    return (
        base,
        _transform_variant(
            base,
            key=f"{character}:alternate-1",
            label="alternate-1",
            width_scale=0.96,
            slant=0.045,
            wobble=0.018,
        ),
        _transform_variant(
            base,
            key=f"{character}:alternate-2",
            label="alternate-2",
            width_scale=1.045,
            slant=-0.018,
            wobble=0.014,
        ),
    )


# A compact monoline alphabet. Strokes are intentionally simple so the first
# physical validation remains easy to inspect and does not depend on a large
# third-party font data file.
_ROBOT_BASE: dict[str, GlyphVariant] = {
    "A": _glyph(_stroke((0.05, 0.0), (0.45, 1.0), (0.85, 0.0)), _stroke((0.2, 0.42), (0.7, 0.42)), advance=0.95),
    "B": _glyph(_stroke((0.05, 0.0), (0.05, 1.0), (0.5, 1.0), (0.75, 0.82), (0.5, 0.55), (0.05, 0.55)), _stroke((0.05, 0.55), (0.55, 0.55), (0.8, 0.3), (0.55, 0.0), (0.05, 0.0)), advance=0.9),
    "C": _glyph(_stroke((0.82, 0.86), (0.62, 1.0), (0.2, 0.95), (0.05, 0.55), (0.18, 0.1), (0.62, 0.0), (0.84, 0.16)), advance=0.95),
    "D": _glyph(_stroke((0.05, 0.0), (0.05, 1.0), (0.46, 1.0), (0.82, 0.72), (0.82, 0.28), (0.46, 0.0), (0.05, 0.0)), advance=0.95),
    "E": _glyph(_stroke((0.82, 1.0), (0.05, 1.0), (0.05, 0.0), (0.82, 0.0)), _stroke((0.05, 0.52), (0.65, 0.52)), advance=0.9),
    "F": _glyph(_stroke((0.05, 0.0), (0.05, 1.0), (0.82, 1.0)), _stroke((0.05, 0.52), (0.65, 0.52)), advance=0.88),
    "G": _glyph(_stroke((0.83, 0.84), (0.62, 1.0), (0.2, 0.95), (0.05, 0.55), (0.18, 0.1), (0.62, 0.0), (0.85, 0.18), (0.85, 0.48), (0.55, 0.48)), advance=0.98),
    "H": _glyph(_stroke((0.05, 0.0), (0.05, 1.0)), _stroke((0.82, 0.0), (0.82, 1.0)), _stroke((0.05, 0.5), (0.82, 0.5)), advance=0.95),
    "I": _glyph(_stroke((0.08, 1.0), (0.72, 1.0)), _stroke((0.4, 1.0), (0.4, 0.0)), _stroke((0.08, 0.0), (0.72, 0.0)), advance=0.8),
    "J": _glyph(_stroke((0.05, 0.2), (0.2, 0.0), (0.55, 0.0), (0.72, 0.22), (0.72, 1.0)), advance=0.82),
    "K": _glyph(_stroke((0.05, 0.0), (0.05, 1.0)), _stroke((0.82, 1.0), (0.05, 0.45), (0.85, 0.0)), advance=0.95),
    "L": _glyph(_stroke((0.05, 1.0), (0.05, 0.0), (0.82, 0.0)), advance=0.88),
    "M": _glyph(_stroke((0.05, 0.0), (0.05, 1.0), (0.45, 0.45), (0.85, 1.0), (0.85, 0.0)), advance=1.0),
    "N": _glyph(_stroke((0.05, 0.0), (0.05, 1.0), (0.85, 0.0), (0.85, 1.0)), advance=1.0),
    "O": _glyph(_stroke((0.45, 1.0), (0.15, 0.9), (0.05, 0.5), (0.15, 0.1), (0.45, 0.0), (0.75, 0.1), (0.85, 0.5), (0.75, 0.9), (0.45, 1.0)), advance=0.98),
    "P": _glyph(_stroke((0.05, 0.0), (0.05, 1.0), (0.5, 1.0), (0.78, 0.78), (0.5, 0.54), (0.05, 0.54)), advance=0.9),
    "Q": _glyph(_stroke((0.45, 1.0), (0.15, 0.9), (0.05, 0.5), (0.15, 0.1), (0.45, 0.0), (0.75, 0.1), (0.85, 0.5), (0.75, 0.9), (0.45, 1.0)), _stroke((0.52, 0.28), (0.9, -0.08)), advance=1.0),
    "R": _glyph(_stroke((0.05, 0.0), (0.05, 1.0), (0.5, 1.0), (0.78, 0.78), (0.5, 0.54), (0.05, 0.54)), _stroke((0.42, 0.54), (0.84, 0.0)), advance=0.95),
    "S": _glyph(_stroke((0.8, 0.85), (0.62, 1.0), (0.22, 0.95), (0.08, 0.72), (0.25, 0.52), (0.65, 0.46), (0.82, 0.25), (0.65, 0.02), (0.2, 0.05), (0.05, 0.18)), advance=0.9),
    "T": _glyph(_stroke((0.05, 1.0), (0.85, 1.0)), _stroke((0.45, 1.0), (0.45, 0.0)), advance=0.92),
    "U": _glyph(_stroke((0.05, 1.0), (0.05, 0.25), (0.2, 0.02), (0.65, 0.02), (0.82, 0.25), (0.82, 1.0)), advance=0.95),
    "V": _glyph(_stroke((0.05, 1.0), (0.45, 0.0), (0.85, 1.0)), advance=0.95),
    "W": _glyph(_stroke((0.05, 1.0), (0.22, 0.0), (0.5, 0.62), (0.78, 0.0), (0.95, 1.0)), advance=1.08),
    "X": _glyph(_stroke((0.05, 1.0), (0.85, 0.0)), _stroke((0.05, 0.0), (0.85, 1.0)), advance=0.95),
    "Y": _glyph(_stroke((0.05, 1.0), (0.45, 0.55), (0.85, 1.0)), _stroke((0.45, 0.55), (0.45, 0.0)), advance=0.95),
    "Z": _glyph(_stroke((0.05, 1.0), (0.85, 1.0), (0.05, 0.0), (0.85, 0.0)), advance=0.95),
    "0": _glyph(_stroke((0.42, 1.0), (0.14, 0.9), (0.05, 0.5), (0.14, 0.1), (0.42, 0.0), (0.7, 0.1), (0.8, 0.5), (0.7, 0.9), (0.42, 1.0)), _stroke((0.18, 0.12), (0.66, 0.88)), advance=0.88),
    "1": _glyph(_stroke((0.18, 0.78), (0.42, 1.0), (0.42, 0.0)), _stroke((0.15, 0.0), (0.7, 0.0)), advance=0.78),
    "2": _glyph(_stroke((0.08, 0.78), (0.25, 0.98), (0.62, 0.98), (0.78, 0.76), (0.08, 0.0), (0.82, 0.0)), advance=0.9),
    "3": _glyph(_stroke((0.08, 0.88), (0.28, 1.0), (0.65, 0.94), (0.78, 0.7), (0.55, 0.5), (0.78, 0.28), (0.65, 0.04), (0.25, 0.0), (0.06, 0.14)), advance=0.88),
    "4": _glyph(_stroke((0.62, 0.0), (0.62, 1.0), (0.05, 0.3), (0.82, 0.3)), advance=0.9),
    "5": _glyph(_stroke((0.78, 1.0), (0.15, 1.0), (0.08, 0.55), (0.55, 0.55), (0.78, 0.34), (0.67, 0.06), (0.24, 0.0), (0.06, 0.15)), advance=0.88),
    "6": _glyph(_stroke((0.72, 0.9), (0.52, 1.0), (0.2, 0.86), (0.05, 0.45), (0.18, 0.08), (0.55, 0.0), (0.78, 0.22), (0.65, 0.5), (0.2, 0.52), (0.05, 0.38)), advance=0.9),
    "7": _glyph(_stroke((0.05, 1.0), (0.82, 1.0), (0.28, 0.0)), advance=0.9),
    "8": _glyph(_stroke((0.42, 1.0), (0.15, 0.86), (0.2, 0.58), (0.42, 0.5), (0.68, 0.62), (0.7, 0.88), (0.42, 1.0), (0.15, 0.86)), _stroke((0.42, 0.5), (0.15, 0.34), (0.18, 0.08), (0.42, 0.0), (0.7, 0.12), (0.68, 0.38), (0.42, 0.5)), advance=0.88),
    "9": _glyph(_stroke((0.72, 0.62), (0.58, 0.94), (0.22, 1.0), (0.05, 0.72), (0.2, 0.48), (0.65, 0.5), (0.78, 0.72), (0.65, 0.15), (0.45, 0.0), (0.18, 0.08)), advance=0.9),
    ".": _glyph(_dot((0.3, 0.035), 0.035), advance=0.42),
    ",": _glyph(_stroke((0.3, 0.08), (0.23, -0.16)), advance=0.42),
    "!": _glyph(_stroke((0.35, 1.0), (0.35, 0.25)), _dot((0.35, 0.035), 0.035), advance=0.7),
    "?": _glyph(_stroke((0.08, 0.78), (0.22, 0.98), (0.58, 1.0), (0.76, 0.8), (0.64, 0.6), (0.38, 0.48), (0.38, 0.28)), _dot((0.38, 0.035), 0.035), advance=0.84),
    "-": _glyph(_stroke((0.08, 0.45), (0.7, 0.45)), advance=0.78),
    "_": _glyph(_stroke((0.05, -0.08), (0.82, -0.08)), advance=0.9),
    ":": _glyph(_dot((0.3, 0.68), 0.035), _dot((0.3, 0.15), 0.035), advance=0.45),
    ";": _glyph(_dot((0.3, 0.68), 0.035), _stroke((0.31, 0.16), (0.22, -0.12)), advance=0.45),
    "/": _glyph(_stroke((0.05, -0.08), (0.82, 1.05)), advance=0.88),
    "\\": _glyph(_stroke((0.05, 1.05), (0.82, -0.08)), advance=0.88),
    "(": _glyph(_stroke((0.55, 1.05), (0.28, 0.78), (0.18, 0.48), (0.28, 0.18), (0.55, -0.08)), advance=0.62),
    ")": _glyph(_stroke((0.12, 1.05), (0.39, 0.78), (0.49, 0.48), (0.39, 0.18), (0.12, -0.08)), advance=0.62),
    "+": _glyph(_stroke((0.1, 0.45), (0.72, 0.45)), _stroke((0.41, 0.76), (0.41, 0.14)), advance=0.82),
    "=": _glyph(_stroke((0.08, 0.62), (0.72, 0.62)), _stroke((0.08, 0.32), (0.72, 0.32)), advance=0.82),
    "'": _glyph(_stroke((0.3, 1.0), (0.24, 0.72)), advance=0.42),
    '"': _glyph(_stroke((0.2, 1.0), (0.16, 0.72)), _stroke((0.48, 1.0), (0.44, 0.72)), advance=0.64),
}


# Lowercase handwriting-style centerlines. Entry and exit anchors allow the
# writing engine to add baseline joins between neighboring letters.
_HAND_LOWER: dict[str, GlyphVariant] = {
    "a": _glyph(_stroke((0.02, 0.0), (0.12, 0.34), (0.38, 0.42), (0.58, 0.25), (0.48, 0.03), (0.2, 0.0), (0.08, 0.2), (0.2, 0.4), (0.52, 0.38), (0.58, 0.0)), advance=0.68, entry=(0.02, 0.0), exit=(0.62, 0.0)),
    "b": _glyph(_stroke((0.02, 0.0), (0.12, 0.85), (0.2, 1.0), (0.22, 0.08), (0.38, 0.42), (0.62, 0.35), (0.65, 0.12), (0.48, 0.0), (0.22, 0.08)), advance=0.72, entry=(0.02, 0.0), exit=(0.68, 0.0)),
    "c": _glyph(_stroke((0.02, 0.0), (0.12, 0.3), (0.36, 0.42), (0.58, 0.3), (0.47, 0.05), (0.18, 0.0), (0.08, 0.16)), advance=0.64, entry=(0.02, 0.0), exit=(0.6, 0.0)),
    "d": _glyph(_stroke((0.02, 0.0), (0.12, 0.32), (0.38, 0.42), (0.58, 0.24), (0.48, 0.02), (0.2, 0.0), (0.08, 0.2), (0.2, 0.4), (0.54, 0.36), (0.58, 1.0), (0.62, 0.0)), advance=0.7, entry=(0.02, 0.0), exit=(0.65, 0.0)),
    "e": _glyph(_stroke((0.02, 0.0), (0.12, 0.22), (0.52, 0.23), (0.4, 0.42), (0.16, 0.38), (0.08, 0.15), (0.24, 0.0), (0.56, 0.05)), advance=0.64, entry=(0.02, 0.0), exit=(0.6, 0.0)),
    "f": _glyph(_stroke((0.02, 0.0), (0.18, 0.84), (0.36, 1.0), (0.48, 0.86), (0.22, -0.25)), _stroke((0.02, 0.42), (0.52, 0.48)), advance=0.58, entry=(0.02, 0.0), exit=(0.54, 0.0)),
    "g": _glyph(_stroke((0.02, 0.0), (0.12, 0.32), (0.38, 0.42), (0.58, 0.23), (0.47, 0.02), (0.19, 0.0), (0.08, 0.2), (0.22, 0.4), (0.58, 0.34), (0.54, -0.25), (0.32, -0.36), (0.08, -0.22)), advance=0.68, entry=(0.02, 0.0), exit=(0.62, 0.0)),
    "h": _glyph(_stroke((0.02, 0.0), (0.13, 1.0), (0.2, 0.0), (0.25, 0.3), (0.44, 0.42), (0.6, 0.3), (0.61, 0.0)), advance=0.68, entry=(0.02, 0.0), exit=(0.64, 0.0)),
    "i": _glyph(_stroke((0.02, 0.0), (0.18, 0.4), (0.21, 0.0)), _dot((0.2, 0.66), 0.035), advance=0.34, entry=(0.02, 0.0), exit=(0.3, 0.0)),
    "j": _glyph(_stroke((0.02, 0.0), (0.22, 0.42), (0.2, -0.24), (0.05, -0.36), (-0.08, -0.25)), _dot((0.22, 0.68), 0.035), advance=0.36, entry=(0.02, 0.0), exit=(0.31, 0.0)),
    "k": _glyph(_stroke((0.02, 0.0), (0.13, 1.0), (0.2, 0.0)), _stroke((0.2, 0.2), (0.56, 0.46), (0.28, 0.22), (0.62, 0.0)), advance=0.68, entry=(0.02, 0.0), exit=(0.64, 0.0)),
    "l": _glyph(_stroke((0.02, 0.0), (0.16, 1.0), (0.23, 0.0)), advance=0.34, entry=(0.02, 0.0), exit=(0.3, 0.0)),
    "m": _glyph(_stroke((0.02, 0.0), (0.12, 0.4), (0.18, 0.0), (0.24, 0.31), (0.42, 0.4), (0.5, 0.0), (0.56, 0.31), (0.74, 0.4), (0.82, 0.0)), advance=0.9, entry=(0.02, 0.0), exit=(0.86, 0.0)),
    "n": _glyph(_stroke((0.02, 0.0), (0.12, 0.4), (0.18, 0.0), (0.25, 0.31), (0.46, 0.4), (0.58, 0.0)), advance=0.66, entry=(0.02, 0.0), exit=(0.62, 0.0)),
    "o": _glyph(_stroke((0.02, 0.0), (0.1, 0.28), (0.32, 0.42), (0.55, 0.3), (0.58, 0.1), (0.4, 0.0), (0.16, 0.05), (0.08, 0.25), (0.28, 0.42), (0.58, 0.05)), advance=0.66, entry=(0.02, 0.0), exit=(0.62, 0.0)),
    "p": _glyph(_stroke((0.02, 0.0), (0.12, 0.42), (0.12, -0.34)), _stroke((0.13, 0.32), (0.38, 0.42), (0.58, 0.25), (0.5, 0.04), (0.2, 0.02), (0.13, 0.16)), advance=0.66, entry=(0.02, 0.0), exit=(0.62, 0.0)),
    "q": _glyph(_stroke((0.02, 0.0), (0.12, 0.32), (0.38, 0.42), (0.58, 0.24), (0.48, 0.02), (0.2, 0.0), (0.08, 0.2), (0.2, 0.4), (0.58, 0.34), (0.58, -0.34)), advance=0.68, entry=(0.02, 0.0), exit=(0.63, 0.0)),
    "r": _glyph(_stroke((0.02, 0.0), (0.12, 0.4), (0.18, 0.0), (0.25, 0.3), (0.44, 0.42), (0.57, 0.32)), advance=0.62, entry=(0.02, 0.0), exit=(0.58, 0.0)),
    "s": _glyph(_stroke((0.02, 0.0), (0.12, 0.2), (0.48, 0.3), (0.42, 0.42), (0.16, 0.38), (0.1, 0.24), (0.48, 0.12), (0.42, 0.0), (0.12, 0.02)), advance=0.58, entry=(0.02, 0.0), exit=(0.54, 0.0)),
    "t": _glyph(_stroke((0.02, 0.0), (0.2, 0.8), (0.28, 0.0)), _stroke((0.02, 0.48), (0.48, 0.48)), advance=0.54, entry=(0.02, 0.0), exit=(0.5, 0.0)),
    "u": _glyph(_stroke((0.02, 0.4), (0.08, 0.08), (0.26, 0.0), (0.48, 0.14), (0.56, 0.42), (0.58, 0.0)), advance=0.66, entry=(0.02, 0.0), exit=(0.62, 0.0)),
    "v": _glyph(_stroke((0.02, 0.4), (0.25, 0.0), (0.54, 0.42), (0.58, 0.0)), advance=0.64, entry=(0.02, 0.0), exit=(0.6, 0.0)),
    "w": _glyph(_stroke((0.02, 0.4), (0.18, 0.0), (0.38, 0.36), (0.55, 0.0), (0.76, 0.42), (0.8, 0.0)), advance=0.88, entry=(0.02, 0.0), exit=(0.84, 0.0)),
    "x": _glyph(_stroke((0.02, 0.38), (0.56, 0.0)), _stroke((0.08, 0.0), (0.54, 0.42)), advance=0.62, entry=(0.02, 0.0), exit=(0.58, 0.0)),
    "y": _glyph(_stroke((0.02, 0.4), (0.24, 0.0), (0.5, 0.42), (0.4, -0.24), (0.18, -0.36), (0.02, -0.24)), advance=0.62, entry=(0.02, 0.0), exit=(0.58, 0.0)),
    "z": _glyph(_stroke((0.02, 0.36), (0.52, 0.4), (0.08, 0.0), (0.58, 0.02)), advance=0.64, entry=(0.02, 0.0), exit=(0.6, 0.0)),
}


def _freeze_glyphs(mapping: dict[str, tuple[GlyphVariant, ...]]) -> Mapping[str, tuple[GlyphVariant, ...]]:
    return MappingProxyType(dict(mapping))


def _build_robot_font() -> StrokeFont:
    glyphs: dict[str, tuple[GlyphVariant, ...]] = {
        character: (variant,) for character, variant in _ROBOT_BASE.items()
    }
    for character in "abcdefghijklmnopqrstuvwxyz":
        glyphs[character] = glyphs[character.upper()]
    font = StrokeFont(
        name="robot",
        glyphs=_freeze_glyphs(glyphs),
        description="Geometric single-line lettering with fixed glyph forms.",
    )
    font.validate()
    return font


def _build_hand_font() -> StrokeFont:
    glyphs: dict[str, tuple[GlyphVariant, ...]] = {}
    for character, variant in _ROBOT_BASE.items():
        glyphs[character] = _hand_variants(character, variant)
    for character, variant in _HAND_LOWER.items():
        glyphs[character] = _hand_variants(character, variant)
    font = StrokeFont(
        name="hand",
        glyphs=_freeze_glyphs(glyphs),
        line_height=1.45,
        description=(
            "Built-in monoline handwriting foundation with three deterministic "
            "variants per glyph and baseline connection anchors."
        ),
    )
    font.validate()
    return font


def _build_hershey_font(mapping: str, name: str, description: str) -> StrokeFont:
    """Adapt Hershey vector glyphs into the native centerline model."""

    from pyhershey import glyph_factory

    glyphs: dict[str, tuple[GlyphVariant, ...]] = {}
    for codepoint in range(33, 127):
        character = chr(codepoint)
        glyph = glyph_factory.from_ascii(character, mapping)
        strokes = tuple(
            tuple((x / 21.0, y / 21.0) for x, y in segment)
            for segment in glyph.segments
            if len(segment) >= 2
        )
        if strokes:
            glyphs[character] = (_glyph(*strokes, advance=max(glyph.advance_width / 21.0, 0.2)),)

    font = StrokeFont(
        name=name,
        glyphs=_freeze_glyphs(glyphs),
        line_height=1.35,
        fallback="?",
        description=description,
    )
    font.validate()
    return font


_BUILTINS: Mapping[str, StrokeFont] = MappingProxyType(
    {
        "robot": _build_robot_font(),
        "hand": _build_hand_font(),
        "hershey-roman-simplex": _build_hershey_font(
            "roman_simplex", "Hershey Roman Simplex", "Public-domain Hershey single-line Roman strokes."
        ),
        "hershey-roman-duplex": _build_hershey_font(
            "roman_duplex", "Hershey Roman Duplex", "Hershey Roman double-stroke centerline lettering."
        ),
        "hershey-script": _build_hershey_font(
            "script_simplex", "Hershey Script", "Hershey single-line script strokes."
        ),
        "hershey-roman-plain": _build_hershey_font(
            "roman_plain", "Hershey Roman Plain", "Hershey compact plain single-line strokes."
        ),
    }
)


def available_stroke_fonts() -> tuple[str, ...]:
    return tuple(sorted(_BUILTINS))


def get_builtin_stroke_font(name: str) -> StrokeFont:
    try:
        return _BUILTINS[name]
    except KeyError as exc:
        choices = ", ".join(available_stroke_fonts())
        raise ValueError(f"Unknown built-in stroke font {name!r}. Available: {choices}.") from exc


def _parse_point(raw: object, *, name: str) -> Point:
    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError(f"{name} must be a two-item JSON array.")
    point = (float(raw[0]), float(raw[1]))
    _finite_point(name, point)
    return point


def load_stroke_font(path: str | Path) -> StrokeFont:
    """Load and validate a user-authored JSON stroke-font pack."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Stroke font file not found: {source}")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid stroke-font JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Stroke-font JSON root must be an object.")
    glyph_data = raw.get("glyphs")
    if not isinstance(glyph_data, dict):
        raise ValueError("Stroke-font JSON requires a glyphs object.")

    glyphs: dict[str, tuple[GlyphVariant, ...]] = {}
    for character, variants_raw in glyph_data.items():
        if not isinstance(character, str) or len(character) != 1:
            raise ValueError(f"Invalid glyph key: {character!r}.")
        if not isinstance(variants_raw, list) or not variants_raw:
            raise ValueError(f"Glyph {character!r} requires a non-empty variant list.")
        variants: list[GlyphVariant] = []
        for variant_index, variant_raw in enumerate(variants_raw):
            if not isinstance(variant_raw, dict):
                raise ValueError(f"Glyph {character!r} variant {variant_index} must be an object.")
            strokes_raw = variant_raw.get("strokes")
            if not isinstance(strokes_raw, list) or not strokes_raw:
                raise ValueError(f"Glyph {character!r} variant {variant_index} needs strokes.")
            strokes: list[Stroke] = []
            for stroke_index, stroke_raw in enumerate(strokes_raw):
                if not isinstance(stroke_raw, list) or len(stroke_raw) < 2:
                    raise ValueError(
                        f"Glyph {character!r} variant {variant_index}, stroke {stroke_index} "
                        "needs at least two points."
                    )
                strokes.append(
                    tuple(
                        _parse_point(
                            point,
                            name=(
                                f"Glyph {character!r} variant {variant_index}, "
                                f"stroke {stroke_index} point"
                            ),
                        )
                        for point in stroke_raw
                    )
                )
            entry_raw = variant_raw.get("entry")
            exit_raw = variant_raw.get("exit")
            variant = GlyphVariant(
                strokes=tuple(strokes),
                advance=float(variant_raw.get("advance", 1.0)),
                entry=_parse_point(entry_raw, name="Glyph entry") if entry_raw is not None else None,
                exit=_parse_point(exit_raw, name="Glyph exit") if exit_raw is not None else None,
                label=str(variant_raw.get("label", f"variant-{variant_index}")),
            )
            variant.validate()
            variants.append(variant)
        glyphs[character] = tuple(variants)

    font = StrokeFont(
        name=str(raw.get("name", source.stem)),
        glyphs=_freeze_glyphs(glyphs),
        cap_height=float(raw.get("cap_height", 1.0)),
        line_height=float(raw.get("line_height", 1.35)),
        fallback=str(raw.get("fallback", "?")),
        description=str(raw.get("description", "")),
    )
    font.validate()
    return font


def resolve_stroke_font(name: str, path: str | Path | None = None) -> StrokeFont:
    return load_stroke_font(path) if path is not None else get_builtin_stroke_font(name)

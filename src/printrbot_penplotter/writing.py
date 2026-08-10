"""Single-line text layout with glyph variants, wrapping, and cursive joins."""

from __future__ import annotations

import hashlib
import math
import random
import re
import unicodedata
from dataclasses import dataclass

from .models import Point, Polylines, StyleConfig
from .optimize import optimize_stroke_order
from .stroke_fonts import GlyphVariant, StrokeFont, resolve_stroke_font


@dataclass(frozen=True)
class WritingResult:
    polylines: Polylines
    font_name: str
    glyph_count: int
    connector_count: int
    line_count: int
    variant_labels: tuple[str, ...]
    unsupported_characters: tuple[str, ...]


def _seed_value(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _variant_for(
    font: StrokeFont,
    character: str,
    glyph_index: int,
    style: StyleConfig,
) -> GlyphVariant:
    variants = font.variants_for(character)
    if style.variant_mode == "first" or len(variants) == 1:
        return variants[0]
    if style.variant_mode == "cycle":
        return variants[glyph_index % len(variants)]
    return variants[_seed_value(style.seed, glyph_index, character, "variant") % len(variants)]


def _stroke_compatible_character(character: str) -> str:
    """Use the base Latin glyph for accents in the compact stroke alphabets."""
    normalized = unicodedata.normalize("NFKD", character)
    base = "".join(part for part in normalized if not unicodedata.combining(part))
    return base if len(base) == 1 and base in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789?" else character


def _transform_point(
    point: Point,
    *,
    origin_x: float,
    origin_y: float,
    unit_mm: float,
    character_scale: float,
    rotation_deg: float,
    slant_deg: float,
    offset_x: float,
    offset_y: float,
) -> Point:
    x = point[0] * unit_mm * character_scale
    y = point[1] * unit_mm * character_scale
    x += math.tan(math.radians(slant_deg)) * y
    radians = math.radians(rotation_deg)
    rotated_x = x * math.cos(radians) - y * math.sin(radians)
    rotated_y = x * math.sin(radians) + y * math.cos(radians)
    return origin_x + rotated_x + offset_x, origin_y + rotated_y + offset_y


def _connector(start: Point, end: Point) -> list[Point] | None:
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    if distance < 0.03:
        return None
    dx = end[0] - start[0]
    lift = min(0.35, abs(dx) * 0.08)
    return [
        start,
        (start[0] + dx * 0.33, start[1] + lift),
        (start[0] + dx * 0.67, end[1] + lift),
        end,
    ]


def _word_width(
    selected: list[tuple[str, GlyphVariant, int]],
    *,
    unit_mm: float,
    style: StyleConfig,
) -> float:
    if not selected:
        return 0.0
    width = 0.0
    for position, (_, variant, glyph_index) in enumerate(selected):
        rng = random.Random(_seed_value(style.seed, glyph_index, "jitter"))
        character_scale = 1.0 + rng.uniform(-style.scale_jitter, style.scale_jitter)
        width += variant.advance * unit_mm * character_scale
        if position < len(selected) - 1:
            width += style.letter_spacing_mm
    return width


def stroke_text_to_polylines(text: str, style: StyleConfig) -> WritingResult:
    """Render text with a centerline font at physical millimeter scale."""

    style.validate()
    if not text:
        raise ValueError("Text input cannot be empty.")
    font = resolve_stroke_font(style.stroke_font, style.stroke_font_path)
    font.validate()
    unit_mm = style.font_size_mm / font.cap_height
    line_height_mm = font.line_height * unit_mm * style.line_spacing
    space_width_mm = style.word_spacing_em * unit_mm

    glyph_index = 0
    line_index = 0
    cursor_x = 0.0
    cursor_y = 0.0
    polylines: Polylines = []
    variant_labels: list[str] = []
    unsupported: set[str] = set()
    connector_count = 0
    previous_exit: Point | None = None

    paragraphs = text.split("\n")
    for paragraph_index, paragraph in enumerate(paragraphs):
        tokens = re.findall(r"\S+|[ \t]+", paragraph)
        for token in tokens:
            if token.isspace():
                cursor_x += space_width_mm * len(token.expandtabs(4))
                previous_exit = None
                continue

            selected: list[tuple[str, GlyphVariant, int]] = []
            for character in token:
                glyph_character = _stroke_compatible_character(character)
                if glyph_character not in font.glyphs:
                    unsupported.add(character)
                variant = _variant_for(font, glyph_character, glyph_index, style)
                selected.append((character, variant, glyph_index))
                glyph_index += 1

            width = _word_width(selected, unit_mm=unit_mm, style=style)
            if (
                style.wrap_width_mm is not None
                and cursor_x > 0
                and cursor_x + width > style.wrap_width_mm
            ):
                cursor_x = 0.0
                cursor_y -= line_height_mm
                line_index += 1
                previous_exit = None

            for character, variant, selected_index in selected:
                rng = random.Random(_seed_value(style.seed, selected_index, character, "jitter"))
                rotation = rng.uniform(-style.rotation_jitter_deg, style.rotation_jitter_deg)
                baseline = rng.uniform(-style.baseline_jitter_mm, style.baseline_jitter_mm)
                x_jitter = rng.uniform(-style.x_jitter_mm, style.x_jitter_mm)
                character_scale = 1.0 + rng.uniform(-style.scale_jitter, style.scale_jitter)

                source_strokes = [list(stroke) for stroke in variant.strokes]
                if style.stroke_order == "nearest" and len(source_strokes) > 1:
                    source_strokes = optimize_stroke_order(
                        source_strokes,
                        start=variant.entry,
                        allow_reverse=True,
                    )

                transformed_strokes = [
                    [
                        _transform_point(
                            point,
                            origin_x=cursor_x,
                            origin_y=cursor_y,
                            unit_mm=unit_mm,
                            character_scale=character_scale,
                            rotation_deg=rotation,
                            slant_deg=style.slant_deg,
                            offset_x=x_jitter,
                            offset_y=baseline,
                        )
                        for point in stroke
                    ]
                    for stroke in source_strokes
                ]
                transformed_entry = (
                    _transform_point(
                        variant.entry,
                        origin_x=cursor_x,
                        origin_y=cursor_y,
                        unit_mm=unit_mm,
                        character_scale=character_scale,
                        rotation_deg=rotation,
                        slant_deg=style.slant_deg,
                        offset_x=x_jitter,
                        offset_y=baseline,
                    )
                    if variant.entry is not None
                    else None
                )
                transformed_exit = (
                    _transform_point(
                        variant.exit,
                        origin_x=cursor_x,
                        origin_y=cursor_y,
                        unit_mm=unit_mm,
                        character_scale=character_scale,
                        rotation_deg=rotation,
                        slant_deg=style.slant_deg,
                        offset_x=x_jitter,
                        offset_y=baseline,
                    )
                    if variant.exit is not None
                    else None
                )

                if style.connect_letters and previous_exit is not None and transformed_entry is not None:
                    join = _connector(previous_exit, transformed_entry)
                    if join is not None:
                        polylines.append(join)
                        connector_count += 1

                polylines.extend(stroke for stroke in transformed_strokes if len(stroke) >= 2)
                variant_labels.append(variant.label)
                cursor_x += variant.advance * unit_mm * character_scale + style.letter_spacing_mm
                previous_exit = transformed_exit

        if paragraph_index < len(paragraphs) - 1:
            cursor_x = 0.0
            cursor_y -= line_height_mm
            line_index += 1
            previous_exit = None

    if not polylines:
        raise ValueError("The supplied text produced no drawable glyphs.")
    return WritingResult(
        polylines=polylines,
        font_name=font.name,
        glyph_count=glyph_index,
        connector_count=connector_count,
        line_count=line_index + 1,
        variant_labels=tuple(variant_labels),
        unsupported_characters=tuple(sorted(unsupported)),
    )

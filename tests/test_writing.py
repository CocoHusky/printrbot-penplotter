from pathlib import Path

import pytest

from printrbot_penplotter.models import LayoutConfig, PageConfig, StyleConfig
from printrbot_penplotter.optimize import optimize_stroke_order, pen_up_distance
from printrbot_penplotter.pipeline import render_text_job
from printrbot_penplotter.stroke_fonts import (
    available_stroke_fonts,
    get_builtin_stroke_font,
    load_stroke_font,
)
from printrbot_penplotter.writing import stroke_text_to_polylines
from printrbot_penplotter.inputs import text_to_polylines_with_metadata


def test_builtin_fonts_validate_and_cover_core_characters() -> None:
    assert available_stroke_fonts() == ("hand", "robot")
    for name in available_stroke_fonts():
        font = get_builtin_stroke_font(name)
        font.validate()
        for character in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789?":
            assert character in font.glyphs


def test_robot_l_is_one_centerline_stroke_not_an_outline() -> None:
    job = render_text_job(
        "L",
        style=StyleConfig.for_preset("robot", font_size_mm=12),
        layout=LayoutConfig(fit_mode="none"),
    )
    assert job.metadata["text_engine"] == "stroke"
    assert job.metadata["stroke_font"] == "robot"
    assert job.metadata["strokes"] == 1


def test_standard_preset_uses_a_typed_font_outline() -> None:
    style = StyleConfig.for_preset("standard", font_size_mm=12)
    job = render_text_job("Times", style=style, layout=LayoutConfig(fit_mode="none"))
    assert style.engine == "outline"
    assert style.font_family == "Arial"
    assert job.metadata["text_engine"] == "outline"


def test_cjk_typed_text_uses_real_mac_font_when_available() -> None:
    cjk_font = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
    if not cjk_font.is_file():
        pytest.skip("macOS CJK font is not available on this host")
    style = StyleConfig.for_preset(
        "standard",
        font_family="PingFang SC",
        font_size_mm=10,
    )
    polylines, metadata = text_to_polylines_with_metadata(
        "Hello 你好 こんにちは Hola!",
        style,
    )
    assert polylines
    assert metadata["font_path"] == str(cjk_font)


def test_typed_text_rejects_missing_glyphs_instead_of_falling_back() -> None:
    style = StyleConfig.for_preset("standard", font_family="Arial", font_size_mm=10)
    with pytest.raises(ValueError, match="cannot draw"):
        text_to_polylines_with_metadata("你好", style)


def test_seeded_glyph_selection_is_reproducible() -> None:
    style = StyleConfig.for_preset("human", seed=42, font_size_mm=10)
    first = render_text_job("aaaaaaaa", style=style)
    second = render_text_job("aaaaaaaa", style=style)
    assert first.gcode == second.gcode
    assert first.metadata["glyph_variants"] == second.metadata["glyph_variants"]
    assert len(set(first.metadata["glyph_variants"])) > 1


def test_cycle_mode_guarantees_visible_alternate_glyphs() -> None:
    style = StyleConfig.for_preset(
        "human",
        variant_mode="cycle",
        rotation_jitter_deg=0,
        baseline_jitter_mm=0,
        x_jitter_mm=0,
        scale_jitter=0,
    )
    result = stroke_text_to_polylines("aaaa", style)
    assert result.variant_labels[:3] == ("base", "alternate-1", "alternate-2")


def test_cursive_preset_adds_baseline_connectors() -> None:
    job = render_text_job(
        "minimum",
        style=StyleConfig.for_preset("cursive", font_size_mm=9),
        layout=LayoutConfig(fit_mode="none"),
    )
    assert job.metadata["connect_letters"] is True
    assert job.metadata["connectors"] >= 5


def test_word_wrap_uses_physical_millimeter_width() -> None:
    job = render_text_job(
        "hello hello",
        style=StyleConfig.for_preset(
            "clean",
            font_size_mm=10,
            wrap_width_mm=33,
        ),
        page=PageConfig(width_mm=100, height_mm=100, margin_mm=5),
        layout=LayoutConfig(fit_mode="none", horizontal_align="left"),
    )
    assert job.metadata["lines"] == 2
    assert job.metadata["width_mm"] <= 33.1


def test_custom_json_stroke_font_loads_and_renders() -> None:
    fixture = Path(__file__).parent / "fixtures" / "minimal-stroke-font.json"
    font = load_stroke_font(fixture)
    assert font.name == "fixture-font"
    assert len(font.variants_for("x")) == 2
    result = stroke_text_to_polylines(
        "xxx",
        StyleConfig.for_preset(
            "human",
            stroke_font_path=str(fixture),
            variant_mode="cycle",
            connect_letters=True,
            rotation_jitter_deg=0,
            baseline_jitter_mm=0,
            x_jitter_mm=0,
            scale_jitter=0,
        ),
    )
    assert result.font_name == "fixture-font"
    assert result.connector_count == 2


def test_unsupported_character_uses_fallback_and_is_reported() -> None:
    job = render_text_job("ok🙂", style=StyleConfig.for_preset("clean"))
    assert job.metadata["unsupported_characters"] == ["🙂"]
    assert job.metadata["glyphs"] == 3


def test_nearest_stroke_order_never_increases_pen_up_travel() -> None:
    strokes = [
        [(20.0, 0.0), (21.0, 0.0)],
        [(1.0, 0.0), (2.0, 0.0)],
        [(10.0, 0.0), (11.0, 0.0)],
    ]
    optimized = optimize_stroke_order(strokes, start=(0.0, 0.0))
    assert pen_up_distance(optimized, start=(0.0, 0.0)) <= pen_up_distance(
        strokes,
        start=(0.0, 0.0),
    )

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
    assert available_stroke_fonts() == (
        "hand",
        "hershey-roman-duplex",
        "hershey-roman-plain",
        "hershey-roman-simplex",
        "hershey-script",
        "robot",
    )
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


def test_robot_centerline_dots_have_real_drawable_motion() -> None:
    font = get_builtin_stroke_font("robot")

    def length(stroke: tuple[tuple[float, float], ...]) -> float:
        return sum(
            ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            for a, b in zip(stroke, stroke[1:])
        )

    for character in ".!?:;":
        assert all(length(stroke) >= 0.1 for stroke in font.glyphs[character][0].strokes)


def test_robot_centerline_dots_are_closed_circular_strokes() -> None:
    font = get_builtin_stroke_font("robot")
    for character in ".!?:;":
        for stroke in font.glyphs[character][0].strokes:
            if len(stroke) >= 8:
                assert stroke[0][0] == pytest.approx(stroke[-1][0])
                assert stroke[0][1] == pytest.approx(stroke[-1][1])


def test_robot_letter_shapes_remain_centerline_strokes() -> None:
    font = get_builtin_stroke_font("robot")
    assert len(font.glyphs["L"][0].strokes) == 1
    assert len(font.glyphs["l"][0].strokes) == 1
    assert len(font.glyphs["W"][0].strokes) == 1
    assert len(font.glyphs["O"][0].strokes) == 1


def test_robot_alphabet_keeps_every_letter_to_three_strokes_or_fewer() -> None:
    font = get_builtin_stroke_font("robot")
    assert max(len(font.glyphs[character][0].strokes) for character in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz") <= 3


def test_centerline_text_supports_micro_physical_sizes() -> None:
    job = render_text_job(
        "o W",
        style=StyleConfig.for_preset("standard", font_size_mm=2),
        layout=LayoutConfig(fit_mode="none"),
    )
    assert job.metadata["text_engine"] == "stroke"
    assert job.metadata["stroke_font"] == "robot"


def test_typed_centerlines_are_repeatable() -> None:
    style = StyleConfig.for_preset("standard", font_size_mm=10, wrap_width_mm=120)
    first = render_text_job("Happy 60th Birthday, Dad!", style=style)
    second = render_text_job("Happy 60th Birthday, Dad!", style=style)
    assert first.gcode == second.gcode


def test_typed_glyphs_share_a_baseline_for_descenders() -> None:
    from printrbot_penplotter.centerline_fonts import _glyph_paths
    from printrbot_penplotter.font_library import resolve_font_family

    font_path = resolve_font_family("DejaVu Sans")
    assert font_path is not None
    p_paths, _ = _glyph_paths("p", font_path)
    o_paths, _ = _glyph_paths("o", font_path)
    p_min_y = min(point[1] for path in p_paths for point in path)
    o_min_y = min(point[1] for path in o_paths for point in path)
    assert p_min_y < o_min_y - 0.1


def test_common_typed_glyphs_do_not_remain_split_into_tiny_fragments() -> None:
    from printrbot_penplotter.centerline_fonts import _glyph_paths
    from printrbot_penplotter.font_library import resolve_font_family

    font_path = resolve_font_family("DejaVu Sans")
    assert font_path is not None
    for character in "4pga":
        paths, _ = _glyph_paths(character, font_path)
        assert len(paths) <= 5


def test_typed_centerline_text_wraps_words_to_physical_width() -> None:
    style = StyleConfig.for_preset(
        "standard",
        font_size_mm=10,
        wrap_width_mm=25,
    )
    from printrbot_penplotter.font_library import resolve_font_family
    from printrbot_penplotter.centerline_fonts import text_to_centerline_polylines

    polylines = text_to_centerline_polylines(
        "This is a longer typed note that should wrap.",
        style,
        resolve_font_family("Arial") or resolve_font_family("DejaVu Sans"),
    )
    y_values = {round(point[1], 2) for path in polylines for point in path}
    assert len(y_values) > 2


def test_standard_preset_uses_typed_centerline_strokes() -> None:
    style = StyleConfig.for_preset("standard", font_size_mm=12)
    job = render_text_job("Times", style=style, layout=LayoutConfig(fit_mode="none"))
    assert style.engine == "stroke"
    assert style.font_family == "Arial"
    assert job.metadata["text_engine"] == "stroke"


def test_standard_typed_preset_is_centerline_only() -> None:
    style = StyleConfig.for_preset("standard", font_size_mm=10)
    job = render_text_job("Hello", style=style)
    assert style.engine == "stroke"
    assert job.metadata["text_engine"] == "stroke"
    assert job.metadata["stroke_font"] == "robot"


def test_experimental_outline_font_override_is_explicit() -> None:
    style = StyleConfig.for_preset(
        "robot",
        font_family="DejaVu Sans",
        experimental_outline_centerline=True,
        font_size_mm=10,
    )
    job = render_text_job("Arial", style=style)
    assert job.metadata["text_engine"] == "experimental-outline-centerline"
    assert "thinned" in job.metadata["font_note"]


def test_fullwidth_cjk_punctuation_uses_centerline_equivalents() -> None:
    style = StyleConfig.for_preset("standard", font_size_mm=10)
    fullwidth = stroke_text_to_polylines("，！", style).polylines
    ascii_equivalent = stroke_text_to_polylines(",!", style).polylines
    assert fullwidth == ascii_equivalent


def test_centerline_text_rejects_unsupported_non_latin_instead_of_falling_back() -> None:
    style = StyleConfig.for_preset("standard", font_family="Arial", font_size_mm=10)
    with pytest.raises(ValueError, match="only supports the built-in stroke-font alphabet"):
        text_to_polylines_with_metadata("你好", style)


def test_cjk_text_is_rejected_until_a_stroke_font_exists() -> None:
    style = StyleConfig.for_preset(
        "standard",
        font_family="PingFang SC",
        font_size_mm=10,
    )
    with pytest.raises(ValueError, match="only supports the built-in stroke-font alphabet"):
        text_to_polylines_with_metadata("你好 世界", style)


def test_seeded_glyph_selection_is_reproducible() -> None:
    style = StyleConfig.for_preset("human", seed=42, font_size_mm=10)
    first = render_text_job("aaaaaaaa", style=style)
    second = render_text_job("aaaaaaaa", style=style)
    assert first.gcode == second.gcode
    assert first.metadata["glyph_variants"] == second.metadata["glyph_variants"]
    assert len(set(first.metadata["glyph_variants"])) > 1


def test_human_preset_keeps_variation_controlled_for_readable_notes() -> None:
    style = StyleConfig.for_preset("human")

    assert style.variant_mode == "seeded"
    assert style.rotation_jitter_deg <= 0.5
    assert style.baseline_jitter_mm <= 0.15
    assert style.x_jitter_mm <= 0.1
    assert style.scale_jitter <= 0.01


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


def test_card_note_defaults_wrap_without_shrinking_character_height() -> None:
    text = (
        "Happy 60th Birthday, Dad. You fathered 4 kids and 3 dogs. "
        "At work you did the impossible — building next-generation silicon wafers and chips. "
        "Thank you for being our dad. We are proud of you and glad you are in our lives. Love, "
        "Your son and family"
    )
    job = render_text_job(
        text,
        style=StyleConfig.for_preset("clean", font_size_mm=6, wrap_width_mm=120),
        page=PageConfig(width_mm=152.4, height_mm=152.4, margin_mm=8),
        layout=LayoutConfig(fit_mode="none", horizontal_align="left"),
    )

    assert job.metadata["lines"] > 1
    assert job.metadata["requested_font_size_mm"] == 6
    assert job.metadata["width_mm"] <= 120.1


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

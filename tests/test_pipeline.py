import math

import pytest

from printrbot_penplotter.calibration import square_cross_pattern
from printrbot_penplotter.gcode import polylines_to_gcode
from printrbot_penplotter.geometry import bounds, place_on_page
from printrbot_penplotter.models import (
    LayoutConfig,
    MachineConfig,
    PageConfig,
    PenConfig,
    StyleConfig,
)
from printrbot_penplotter.pipeline import render_calibration_job, render_text_job


def test_text_pipeline_is_deterministic() -> None:
    style = StyleConfig.for_preset("human", seed=42)
    first = render_text_job("Hello", style=style)
    second = render_text_job("Hello", style=style)
    assert first.gcode == second.gcode
    assert first.preview_svg == second.preview_svg


def test_rendered_geometry_stays_inside_page() -> None:
    page = PageConfig(width_mm=152.4, height_mm=152.4, margin_mm=8)
    job = render_text_job("Plot me", page=page)
    min_x, min_y, max_x, max_y = bounds(job.polylines)
    assert min_x >= page.origin_x_mm + page.margin_mm - 0.01
    assert min_y >= page.origin_y_mm + page.margin_mm - 0.01
    assert max_x <= page.origin_x_mm + page.width_mm - page.margin_mm + 0.01
    assert max_y <= page.origin_y_mm + page.height_mm - page.margin_mm + 0.01


def test_page_origin_offsets_final_machine_coordinates() -> None:
    machine = MachineConfig(x_max_mm=200, y_max_mm=200)
    page = PageConfig(width_mm=100, height_mm=80, margin_mm=5, origin_x_mm=20, origin_y_mm=30)
    job = render_text_job(
        "A",
        machine=machine,
        page=page,
        style=StyleConfig.for_preset("clean", font_size_mm=10),
        layout=LayoutConfig(fit_mode="none", horizontal_align="left", vertical_align="bottom"),
        simplify_tolerance_mm=0,
    )
    min_x, min_y, _, _ = bounds(job.polylines)
    assert min_x == pytest.approx(25.0)
    assert min_y == pytest.approx(35.0)


def test_font_size_is_physical_instead_of_always_filling_page() -> None:
    layout = LayoutConfig(fit_mode="none")
    small = render_text_job(
        "H",
        style=StyleConfig.for_preset("clean", font_size_mm=10),
        layout=layout,
        simplify_tolerance_mm=0,
    )
    large = render_text_job(
        "H",
        style=StyleConfig.for_preset("clean", font_size_mm=20),
        layout=layout,
        simplify_tolerance_mm=0,
    )
    small_height = float(small.metadata["height_mm"])
    large_height = float(large.metadata["height_mm"])
    assert large_height / small_height == pytest.approx(2.0, rel=0.03)


def test_line_spacing_changes_multiline_physical_height() -> None:
    layout = LayoutConfig(fit_mode="none")
    tight = render_text_job(
        "A\nA",
        style=StyleConfig.for_preset("standard", font_size_mm=10, line_spacing=1.0),
        layout=layout,
        simplify_tolerance_mm=0,
    )
    loose = render_text_job(
        "A\nA",
        style=StyleConfig.for_preset("standard", font_size_mm=10, line_spacing=2.0),
        layout=layout,
        simplify_tolerance_mm=0,
    )
    assert float(loose.metadata["height_mm"]) > float(tight.metadata["height_mm"])


def test_fit_mode_none_rejects_oversize_geometry() -> None:
    page = PageConfig(width_mm=20, height_mm=20, margin_mm=2)
    with pytest.raises(ValueError, match="does not fit"):
        place_on_page(
            [[(0.0, 0.0), (100.0, 100.0)]],
            page,
            LayoutConfig(fit_mode="none"),
            MachineConfig(),
        )


def test_non_finite_coordinates_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        polylines_to_gcode(
            [[(0.0, 0.0), (math.nan, 1.0)]],
            PageConfig(),
            PenConfig(),
            MachineConfig(),
        )


def test_gcode_contains_guarded_pen_sequence_without_automatic_homing() -> None:
    pen = PenConfig(z_up_mm=4.0, z_down_mm=0.25, home_before_plot=False)
    job = render_text_job("A", pen=pen, style=StyleConfig.for_preset("clean"))
    assert "G28" not in job.gcode
    assert "G0 Z4.000" in job.gcode
    assert "G0 Z0.250" in job.gcode
    assert "G21" in job.gcode
    assert "G90" in job.gcode


def test_gcode_adds_home_and_safe_end_when_enabled() -> None:
    job = render_text_job(
        "A",
        pen=PenConfig(home_before_plot=True, z_up_mm=5.0, z_down_mm=0.25),
        style=StyleConfig.for_preset("clean"),
    )
    assert "G28 ; home X/Y/Z before plot" in job.gcode
    assert "G28 X Y ; re-home X/Y with pen safely raised" in job.gcode
    assert job.metadata["home_before_plot"] is True
    assert job.metadata["end_sequence"] == "pen-up + M400 + X/Y re-home"


def test_air_plot_never_lowers_pen() -> None:
    job = render_calibration_job(pen=PenConfig(z_up_mm=5.0, z_down_mm=0.25, air_plot=True))
    assert "pen down" not in job.gcode
    assert "G0 Z0.250" not in job.gcode
    assert "; mode: AIR PLOT" in job.gcode


def test_calibration_square_is_exactly_ten_millimeters() -> None:
    square = square_cross_pattern(size_mm=10.0)[0]
    min_x, min_y, max_x, max_y = bounds([square])
    assert max_x - min_x == pytest.approx(10.0)
    assert max_y - min_y == pytest.approx(10.0)


def test_pen_z_limits_are_enforced() -> None:
    with pytest.raises(ValueError, match="outside the machine Z limits"):
        render_text_job(
            "A",
            machine=MachineConfig(z_min_mm=0, z_max_mm=10),
            pen=PenConfig(z_up_mm=12, z_down_mm=0),
        )


def test_different_seed_changes_humanized_geometry() -> None:
    first = render_text_job("Variation", style=StyleConfig.for_preset("human", seed=1))
    second = render_text_job("Variation", style=StyleConfig.for_preset("human", seed=2))
    assert first.gcode != second.gcode

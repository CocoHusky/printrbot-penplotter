from printrbot_penplotter.geometry import bounds
from printrbot_penplotter.models import PageConfig, PenConfig, StyleConfig
from printrbot_penplotter.pipeline import render_text_job


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
    assert min_x >= page.margin_mm - 0.01
    assert min_y >= page.margin_mm - 0.01
    assert max_x <= page.width_mm - page.margin_mm + 0.01
    assert max_y <= page.height_mm - page.margin_mm + 0.01


def test_gcode_contains_guarded_pen_sequence_without_automatic_homing() -> None:
    pen = PenConfig(z_up_mm=4.0, z_down_mm=0.25, home_before_plot=False)
    job = render_text_job("A", pen=pen, style=StyleConfig.for_preset("clean"))
    assert "G28" not in job.gcode
    assert "G0 Z4.000" in job.gcode
    assert "G0 Z0.250" in job.gcode
    assert "G21" in job.gcode
    assert "G90" in job.gcode


def test_different_seed_changes_humanized_geometry() -> None:
    first = render_text_job("Variation", style=StyleConfig.for_preset("human", seed=1))
    second = render_text_job("Variation", style=StyleConfig.for_preset("human", seed=2))
    assert first.gcode != second.gcode

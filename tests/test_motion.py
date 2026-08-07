from __future__ import annotations

import pytest

from printrbot_penplotter.gcode import polylines_to_gcode
from printrbot_penplotter.models import MachineConfig, PageConfig, PenConfig
from printrbot_penplotter.optimize import (
    MotionConfig,
    join_nearby_strokes,
    motion_metrics,
    optimize_motion,
    optimize_stroke_order,
    pen_up_distance,
    rdp_simplify,
    resample_polyline,
    smooth_polyline,
    two_opt_stroke_order,
)
from printrbot_penplotter.pipeline import render_text_job


def test_nearest_route_reduces_pen_up_travel() -> None:
    strokes = [
        [(0.0, 0.0), (1.0, 0.0)],
        [(100.0, 0.0), (101.0, 0.0)],
        [(3.0, 0.0), (2.0, 0.0)],
    ]
    optimized = optimize_stroke_order(strokes, start=(0.0, 0.0), allow_reverse=True)
    assert pen_up_distance(optimized, start=(0.0, 0.0)) < pen_up_distance(
        strokes, start=(0.0, 0.0)
    )


def test_two_opt_is_deterministic_and_not_worse_than_nearest() -> None:
    strokes = [
        [(0.0, 0.0), (1.0, 0.0)],
        [(9.0, 9.0), (10.0, 9.0)],
        [(2.0, 8.0), (2.0, 9.0)],
        [(8.0, 1.0), (9.0, 1.0)],
        [(4.0, 4.0), (5.0, 4.0)],
    ]
    nearest = optimize_stroke_order(strokes, start=(0.0, 0.0), allow_reverse=True)
    first = two_opt_stroke_order(strokes, start=(0.0, 0.0), allow_reverse=True, passes=12)
    second = two_opt_stroke_order(strokes, start=(0.0, 0.0), allow_reverse=True, passes=12)
    assert first == second
    assert pen_up_distance(first, start=(0.0, 0.0)) <= pen_up_distance(
        nearest, start=(0.0, 0.0)
    ) + 1e-9


def test_join_nearby_strokes_reduces_pen_lifts() -> None:
    strokes = [
        [(0.0, 0.0), (5.0, 0.0)],
        [(5.2, 0.0), (10.0, 0.0)],
        [(30.0, 0.0), (40.0, 0.0)],
    ]
    joined = join_nearby_strokes(strokes, 0.25)
    assert len(joined) == 2
    assert joined[0][-1] == (10.0, 0.0)


def test_rdp_simplification_removes_nearly_collinear_points() -> None:
    line = [(0.0, 0.0), (1.0, 0.01), (2.0, -0.01), (3.0, 0.0)]
    simplified = rdp_simplify(line, 0.05)
    assert simplified == [(0.0, 0.0), (3.0, 0.0)]


def test_resampling_limits_long_segment_spacing() -> None:
    line = resample_polyline([(0.0, 0.0), (10.0, 0.0)], 2.0)
    assert len(line) == 6
    assert line[0] == (0.0, 0.0)
    assert line[-1] == (10.0, 0.0)


def test_smoothing_preserves_endpoints() -> None:
    source = [(0.0, 0.0), (2.0, 3.0), (4.0, -2.0), (6.0, 0.0)]
    smoothed = smooth_polyline(source, 2)
    assert smoothed[0] == source[0]
    assert smoothed[-1] == source[-1]
    assert smoothed != source


def test_motion_plan_reports_before_and_after_metrics() -> None:
    strokes = [
        [(0.0, 0.0), (1.0, 0.0)],
        [(50.0, 0.0), (51.0, 0.0)],
        [(3.0, 0.0), (2.0, 0.0)],
    ]
    plan = optimize_motion(
        strokes,
        MotionConfig(route_mode="two_opt", two_opt_passes=6),
        start=(0.0, 0.0),
    )
    assert plan.after.travel_distance_mm <= plan.before.travel_distance_mm
    metadata = plan.metadata()
    assert metadata["motion_route_mode"] == "two_opt"
    assert "travel_saved_mm" in metadata


def test_motion_metrics_estimate_pen_lifts_and_time() -> None:
    metrics = motion_metrics(
        [[(0.0, 0.0), (10.0, 0.0)], [(20.0, 0.0), (30.0, 0.0)]],
        PenConfig(),
        start=(0.0, 0.0),
    )
    assert metrics.strokes == 2
    assert metrics.pen_lifts == 2
    assert metrics.draw_distance_mm == pytest.approx(20.0)
    assert metrics.travel_distance_mm == pytest.approx(10.0)
    assert metrics.estimated_seconds > 0


def test_corner_feed_is_emitted_around_sharp_turn() -> None:
    polylines = [[(10.0, 10.0), (20.0, 10.0), (20.0, 20.0)]]
    pen = PenConfig(
        draw_feed_mm_min=1200.0,
        corner_feed_mm_min=400.0,
        corner_angle_deg=100.0,
    )
    gcode = polylines_to_gcode(polylines, PageConfig(), pen, MachineConfig())
    assert "F400.0" in gcode
    assert "; corner feed: 400.0 below 100.0 deg" in gcode


def test_pipeline_preserves_authored_motion_by_default() -> None:
    job = render_text_job("abc")
    assert job.metadata["motion_route_mode"] == "authored"
    assert job.metadata["motion_after"]["strokes"] == job.metadata["strokes"]


def test_motion_config_rejects_negative_join_tolerance() -> None:
    with pytest.raises(ValueError):
        MotionConfig(join_tolerance_mm=-0.1).validate()

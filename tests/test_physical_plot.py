import time

import pytest
from printrbot_penplotter.models import PenConfig
from printrbot_penplotter.optimize import polyline_length
from printrbot_penplotter.physical_plot import PhysicalPlotConfig, prepare_physical_plot


def test_removes_sub_pen_features() -> None:
    lines = [[(0.0,0.0),(0.1,0.0)], [(0.0,0.0),(10.0,0.0),(20.0,0.0)]]
    result = prepare_physical_plot(lines, PhysicalPlotConfig(pen_tip_mm=0.5, quality="balanced"), pen=PenConfig())
    assert len(result.polylines) >= 1
    assert result.metadata["removed_strokes"] >= 1
    assert result.metadata["physical_plot_schema"] == "printrbot-physical-plot/v1"


def test_is_deterministic() -> None:
    lines = [[(0.0,0.0),(10.0,0.0)],[(12.0,0.0),(20.0,0.0)],[(5.0,5.0),(15.0,8.0)]]
    cfg = PhysicalPlotConfig(pen_tip_mm=0.4, quality="best")
    a = prepare_physical_plot(lines, cfg)
    b = prepare_physical_plot(lines, cfg)
    assert a.polylines == b.polylines
    assert a.metadata == b.metadata


def test_quick_can_join_small_gap() -> None:
    lines = [[(0.0,0.0),(10.0,0.0)],[(10.2,0.0),(20.0,0.0)]]
    result = prepare_physical_plot(lines, PhysicalPlotConfig(pen_tip_mm=0.5, quality="quick", route_mode="authored"))
    assert len(result.polylines) == 1


def test_balanced_bounds_requested_two_opt_to_nearest() -> None:
    lines = [[(float(i), 0.0), (float(i), 4.0)] for i in range(40)]
    result = prepare_physical_plot(lines, PhysicalPlotConfig(quality="balanced", route_mode="two_opt"))
    assert result.metadata["requested_route_mode"] == "two_opt"
    assert result.metadata["effective_route_mode"] == "nearest"
    assert result.metadata["route_fallback_reason"] == "two_opt_bounded_for_balanced_quality"
    assert result.metadata["motion"]["motion_route_mode"] == "nearest"


def test_best_large_job_bounds_two_opt_to_nearest() -> None:
    lines = [[(float(i), 0.0), (float(i), 4.0)] for i in range(200)]
    result = prepare_physical_plot(
        lines,
        PhysicalPlotConfig(quality="best", route_mode="two_opt", max_two_opt_strokes=180),
    )
    assert result.metadata["effective_route_mode"] == "nearest"
    assert result.metadata["route_fallback_reason"] == "two_opt_bounded_for_large_job"


def test_best_small_job_can_still_use_two_opt() -> None:
    lines = [[(0.0,0.0),(10.0,0.0)],[(12.0,0.0),(20.0,0.0)],[(5.0,5.0),(15.0,8.0)]]
    result = prepare_physical_plot(lines, PhysicalPlotConfig(quality="best", route_mode="two_opt"))
    assert result.metadata["effective_route_mode"] == "two_opt"
    assert result.metadata["route_fallback_reason"] is None


def test_stroke_cap_keeps_longest_lines_and_reports_drops() -> None:
    lines = [[(0.0, 0.0), (1.0, 0.0)], [(0.0, 0.0), (4.0, 0.0)], [(0.0, 0.0), (2.0, 0.0)]]
    result = prepare_physical_plot(lines, PhysicalPlotConfig(stroke_cap=2), pen=PenConfig())
    lengths = sorted(round(polyline_length(line), 3) for line in result.polylines)
    assert lengths == [2.0, 4.0]
    assert result.metadata["stroke_cap_dropped"] == 1


def test_balanced_large_stroke_job_stays_interactive() -> None:
    lines = [[(float(i % 40), float(i // 40)), (float(i % 40) + 0.8, float(i // 40) + 0.3)] for i in range(800)]
    started = time.perf_counter()
    result = prepare_physical_plot(lines, PhysicalPlotConfig(quality="balanced", route_mode="two_opt"))
    elapsed = time.perf_counter() - started
    assert result.polylines
    assert result.metadata["effective_route_mode"] == "nearest"
    assert elapsed < 5.0, f"balanced physical routing took {elapsed:.3f}s for 800 strokes"


def test_invalid_pen_tip_rejected() -> None:
    with pytest.raises(ValueError):
        PhysicalPlotConfig(pen_tip_mm=0.0).validate()

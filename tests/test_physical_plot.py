import pytest
from printrbot_penplotter.models import PenConfig
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


def test_invalid_pen_tip_rejected() -> None:
    with pytest.raises(ValueError):
        PhysicalPlotConfig(pen_tip_mm=0.0).validate()

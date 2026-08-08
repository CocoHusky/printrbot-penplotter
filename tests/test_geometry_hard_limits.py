import pytest

from printrbot_penplotter.geometry import MAX_POINTS, MAX_STROKES, validate_polylines
from printrbot_penplotter.physical_plot import PhysicalPlotConfig


def _strokes(count: int):
    for index in range(count):
        x = float(index % 100)
        yield [(x, 0.0), (x, 1.0)]


def test_core_geometry_guard_allows_jobs_above_old_20k_soft_limit() -> None:
    validate_polylines(_strokes(20_001))
    assert MAX_STROKES == 200_000
    assert MAX_POINTS == 20_000_000


def test_core_geometry_guard_still_rejects_unbounded_jobs() -> None:
    with pytest.raises(ValueError, match="200000 stroke safety limit"):
        validate_polylines(_strokes(MAX_STROKES + 1))


def test_physical_defaults_match_core_hard_guard() -> None:
    config = PhysicalPlotConfig()
    assert config.max_strokes == MAX_STROKES
    assert config.max_points == MAX_POINTS

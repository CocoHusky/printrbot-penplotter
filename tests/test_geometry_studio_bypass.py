from printrbot_penplotter.geometry import MAX_POINTS, MAX_STROKES, validate_polylines


def _many_strokes(count: int):
    return [[(0.0, 0.0), (1.0, 1.0)] for _ in range(count)]


def test_shared_geometry_allows_studio_expert_range_above_20k() -> None:
    assert MAX_STROKES >= 200_000
    assert MAX_POINTS >= 20_000_000
    validate_polylines(_many_strokes(20_001))


def test_shared_geometry_error_reports_hard_limit_not_legacy_20k() -> None:
    try:
        validate_polylines(_many_strokes(MAX_STROKES + 1))
    except ValueError as exc:
        message = str(exc)
        assert str(MAX_STROKES) in message
        assert "20000 stroke safety limit" not in message
    else:
        raise AssertionError("Expected hard guard to reject oversized geometry")

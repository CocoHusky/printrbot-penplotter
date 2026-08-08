from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import pytest

from printrbot_penplotter.inputs import raster_to_polylines_with_metadata
from printrbot_penplotter.raster import RasterTraceConfig
from printrbot_penplotter.vector_cleanup import VectorCleanupConfig, cleanup_polylines


def test_default_cleanup_is_exact_noop() -> None:
    source = [[(0.0, 0.0), (1.0, 0.2), (2.0, 0.0)], [(5.0, 5.0), (6.0, 5.0)]]
    result = cleanup_polylines(source)
    assert result.polylines == source
    assert result.metadata["vector_cleanup_schema"] == "printrbot-vector-cleanup/v1"


def test_min_segment_and_short_stroke_pruning() -> None:
    source = [
        [(0.0, 0.0), (0.05, 0.0), (1.0, 0.0), (2.0, 0.0)],
        [(4.0, 4.0), (4.2, 4.0)],
    ]
    result = cleanup_polylines(
        source,
        VectorCleanupConfig(min_segment_px=0.1, min_stroke_length_px=0.5),
    )
    assert len(result.polylines) == 1
    assert result.polylines[0][0] == (0.0, 0.0)
    assert result.polylines[0][-1] == (2.0, 0.0)
    assert result.metadata["short_strokes_removed"] == 1


def test_tiny_closed_loop_is_removed() -> None:
    tiny = [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2), (0.0, 0.0)]
    large = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)]
    result = cleanup_polylines([tiny, large], VectorCleanupConfig(min_closed_area_px2=1.0))
    assert result.polylines == [large]
    assert result.metadata["tiny_loops_removed"] == 1


def test_corner_aware_simplification_preserves_sharp_corner() -> None:
    line = [(0.0, 0.0), (1.0, 0.02), (2.0, 0.0), (2.0, 1.0), (2.0, 2.0)]
    result = cleanup_polylines(
        [line],
        VectorCleanupConfig(simplify_tolerance_px=0.2, preserve_corner_deg=100.0),
    )
    assert (2.0, 0.0) in result.polylines[0]
    assert result.polylines[0][0] == line[0]
    assert result.polylines[0][-1] == line[-1]


def test_moving_average_smoothing_preserves_open_endpoints() -> None:
    line = [(0.0, 0.0), (1.0, 0.7), (2.0, -0.6), (3.0, 0.5), (4.0, 0.0)]
    result = cleanup_polylines(
        [line],
        VectorCleanupConfig(
            smoothing="moving_average",
            smooth_passes=2,
            smooth_strength=0.4,
            preserve_corner_deg=20.0,
        ),
    )
    assert result.polylines[0][0] == line[0]
    assert result.polylines[0][-1] == line[-1]
    assert result.polylines[0] != line


def test_chaikin_keeps_closed_contour_closed() -> None:
    square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)]
    result = cleanup_polylines(
        [square],
        VectorCleanupConfig(
            smoothing="chaikin",
            smooth_passes=1,
            smooth_strength=0.25,
            preserve_corner_deg=0.0,
        ),
    )
    assert result.polylines[0][0] == result.polylines[0][-1]
    assert len(result.polylines[0]) > len(square)


def test_duplicate_suppression_handles_reverse_direction() -> None:
    first = [(0.0, 0.0), (1.0, 0.2), (2.0, 0.0), (3.0, 0.0)]
    second = list(reversed([(0.02, 0.01), (1.0, 0.21), (2.0, -0.01), (3.01, 0.0)]))
    result = cleanup_polylines(
        [first, second],
        VectorCleanupConfig(duplicate_tolerance_px=0.08),
    )
    assert len(result.polylines) == 1
    assert result.metadata["duplicates_removed"] == 1


def test_joining_connects_only_directionally_compatible_endpoints() -> None:
    compatible = [
        [(0.0, 0.0), (1.0, 0.0)],
        [(1.4, 0.05), (2.4, 0.05)],
    ]
    joined = cleanup_polylines(
        compatible,
        VectorCleanupConfig(join_distance_px=0.6, join_angle_deg=15.0),
    )
    assert len(joined.polylines) == 1
    assert joined.metadata["joins_made"] == 1
    assert 0 < joined.metadata["bridge_length_px"] <= 0.6

    incompatible = [
        [(0.0, 0.0), (1.0, 0.0)],
        [(1.2, 0.0), (1.2, 1.0)],
    ]
    separate = cleanup_polylines(
        incompatible,
        VectorCleanupConfig(join_distance_px=0.6, join_angle_deg=20.0),
    )
    assert len(separate.polylines) == 2


def test_cleanup_is_deterministic() -> None:
    source = [
        [(0.0, 0.0), (0.6, 0.1), (1.2, -0.1), (2.0, 0.0)],
        [(2.4, 0.02), (3.0, 0.0), (4.0, 0.0)],
    ]
    config = VectorCleanupConfig.for_quality("smooth")
    first = cleanup_polylines(source, config)
    second = cleanup_polylines(source, config)
    assert first.polylines == second.polylines
    assert first.metadata == second.metadata


def test_quality_presets_are_explicit_and_valid() -> None:
    for name in ("raw", "clean", "smooth", "flowing"):
        config = VectorCleanupConfig.for_quality(name)
        config.validate()
    with pytest.raises(ValueError):
        VectorCleanupConfig.for_quality("unknown")


def test_geometry_limits_fail_closed() -> None:
    source = [[(0.0, 0.0), (1.0, 0.0)], [(2.0, 0.0), (3.0, 0.0)]]
    with pytest.raises(ValueError, match="stroke limit"):
        cleanup_polylines(source, VectorCleanupConfig(max_strokes=1))
    with pytest.raises(ValueError, match="point limit"):
        cleanup_polylines(source, VectorCleanupConfig(max_points=3))


def test_raster_adapter_can_promote_cleaned_geometry_to_source_of_truth(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    image = Image.new("L", (80, 60), 255)
    draw = ImageDraw.Draw(image)
    draw.line((8, 30, 70, 30), fill=0, width=5)
    image.save(path)

    raw_lines, raw_metadata = raster_to_polylines_with_metadata(
        path,
        RasterTraceConfig(mode="centerline", simplify_px=0.0, min_component_px=2),
    )
    assert raw_metadata["vector_cleanup_schema"] is None

    cleaned_lines, cleaned_metadata = raster_to_polylines_with_metadata(
        path,
        RasterTraceConfig(mode="centerline", simplify_px=0.0, min_component_px=2),
        cleanup=VectorCleanupConfig.for_quality("clean"),
    )
    assert cleaned_metadata["vector_cleanup_schema"] == "printrbot-vector-cleanup/v1"
    assert cleaned_metadata["input_strokes"] == len(raw_lines)
    assert cleaned_metadata["output_strokes"] == len(cleaned_lines)
    assert cleaned_lines


def test_smooth_preset_reduces_jagged_variance() -> None:
    line = [(float(x), 0.8 if x % 2 else -0.8) for x in range(20)]
    cleaned = cleanup_polylines([line], VectorCleanupConfig.for_quality("smooth")).polylines[0]
    raw_y = np.array([point[1] for point in line])
    cleaned_y = np.array([point[1] for point in cleaned])
    assert float(np.var(cleaned_y)) < float(np.var(raw_y))

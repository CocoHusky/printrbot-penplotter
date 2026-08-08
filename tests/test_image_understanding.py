from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from printrbot_penplotter.image_preprocess import ImagePreprocessConfig
from printrbot_penplotter.image_understanding import (
    ImageUnderstandingConfig,
    analyze_gray,
    analyze_image,
)


def _synthetic_scene() -> np.ndarray:
    image = Image.new("L", (96, 72), 245)
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 10, 40, 58), fill=42)
    draw.ellipse((50, 14, 86, 52), fill=125)
    draw.line((4, 66, 92, 4), fill=10, width=2)
    return np.asarray(image, dtype=np.uint8)


def test_all_edge_detectors_return_bounded_deterministic_maps() -> None:
    gray = _synthetic_scene()
    methods = (
        "canny",
        "sobel",
        "scharr",
        "laplacian",
        "dog",
        "morphological",
        "multiscale_canny",
    )
    for method in methods:
        config = ImageUnderstandingConfig(edge_method=method, detail_level="high", min_region_px=4)
        first = analyze_gray(gray, config)
        second = analyze_gray(gray, config)
        assert first.edge_strength.shape == gray.shape
        assert first.edge_mask.shape == gray.shape
        assert first.selected_edges.shape == gray.shape
        assert first.edge_strength.dtype == np.float32
        assert np.min(first.edge_strength) >= 0
        assert np.max(first.edge_strength) <= 1
        assert np.array_equal(first.edge_mask, second.edge_mask)
        assert np.array_equal(first.selected_edges, second.selected_edges)
        assert first.metadata == second.metadata


def test_detail_levels_monotonically_retain_more_selected_edges() -> None:
    gray = _synthetic_scene()
    counts = []
    for level in ("low", "medium", "high", "extreme"):
        result = analyze_gray(
            gray,
            ImageUnderstandingConfig(
                edge_method="multiscale_canny",
                detail_level=level,
                edge_low=0.05,
                edge_high=0.12,
                min_region_px=4,
            ),
        )
        counts.append(int(np.count_nonzero(result.selected_edges)))
    assert counts == sorted(counts)
    assert counts[-1] > 0


def test_tonal_bands_partition_every_pixel() -> None:
    gray = np.array([[0, 40, 80, 120, 160, 200, 255]], dtype=np.uint8)
    result = analyze_gray(
        gray,
        ImageUnderstandingConfig(
            edge_method="sobel",
            tonal_bands=(42, 84, 126, 168, 210),
            min_region_px=1,
        ),
    )
    assert result.tone_labels.tolist() == [[0, 0, 1, 2, 3, 4, 5]]
    assert sum(result.metadata["tone_histogram"]) == gray.size


def test_foreground_regions_are_measured_and_sorted_by_area() -> None:
    gray = np.full((40, 60), 255, dtype=np.uint8)
    gray[4:20, 5:25] = 30
    gray[25:33, 40:49] = 70
    result = analyze_gray(
        gray,
        ImageUnderstandingConfig(
            edge_method="sobel",
            foreground_threshold=100,
            min_region_px=4,
        ),
    )
    assert len(result.regions) == 2
    assert result.regions[0].area_px == 16 * 20
    assert result.regions[1].area_px == 8 * 9
    assert result.regions[0].bbox == (5, 4, 25, 20)
    assert result.regions[0].mean_gray == pytest.approx(30.0)
    assert result.regions[0].touches_border is False


def test_tiny_regions_are_excluded() -> None:
    gray = np.full((24, 24), 255, dtype=np.uint8)
    gray[4:12, 4:12] = 20
    gray[20, 20] = 0
    result = analyze_gray(
        gray,
        ImageUnderstandingConfig(foreground_threshold=80, min_region_px=8),
    )
    assert len(result.regions) == 1
    assert result.regions[0].area_px == 64


def test_foreground_inversion_is_explicit() -> None:
    gray = np.full((20, 20), 20, dtype=np.uint8)
    gray[5:15, 5:15] = 240
    normal = analyze_gray(
        gray,
        ImageUnderstandingConfig(foreground_threshold=100, foreground_invert=False, min_region_px=1),
    )
    inverted = analyze_gray(
        gray,
        ImageUnderstandingConfig(foreground_threshold=100, foreground_invert=True, min_region_px=1),
    )
    assert np.count_nonzero(normal.foreground_mask) == 300
    assert np.count_nonzero(inverted.foreground_mask) == 100


def test_analyze_image_uses_step2_preprocessing_and_records_metadata(tmp_path: Path) -> None:
    source = tmp_path / "scene.png"
    Image.fromarray(_synthetic_scene(), mode="L").save(source)
    result = analyze_image(
        source,
        preprocess=ImagePreprocessConfig(
            crop_box=(0.05, 0.05, 0.95, 0.95),
            contrast=1.2,
            auto_levels=True,
            gaussian_blur_radius_px=0.4,
        ),
        understanding=ImageUnderstandingConfig(
            edge_method="scharr",
            detail_level="medium",
            min_region_px=4,
        ),
    )
    assert result.metadata["understanding_schema"] == "printrbot-image-understanding/v1"
    assert result.metadata["crop_box"] == [0.05, 0.05, 0.95, 0.95]
    assert result.metadata["edge_method"] == "scharr"
    assert result.gray.shape == result.edge_mask.shape
    assert result.metadata["processed_width_px"] == result.gray.shape[1]


def test_input_validation_rejects_invalid_controls() -> None:
    with pytest.raises(ValueError, match="edge_low"):
        ImageUnderstandingConfig(edge_low=0.8, edge_high=0.2).validate()
    with pytest.raises(ValueError, match="strictly increasing"):
        ImageUnderstandingConfig(tonal_bands=(100, 50)).validate()
    with pytest.raises(ValueError, match="dog_sigma_large"):
        ImageUnderstandingConfig(dog_sigma_small=2, dog_sigma_large=1).validate()
    with pytest.raises(ValueError, match="2-D"):
        analyze_gray(np.zeros((4, 4, 3), dtype=np.uint8))


def test_region_limit_is_enforced() -> None:
    gray = np.full((20, 20), 255, dtype=np.uint8)
    for row in range(1, 20, 3):
        for col in range(1, 20, 3):
            gray[row, col] = 0
    with pytest.raises(ValueError, match="region limit"):
        analyze_gray(
            gray,
            ImageUnderstandingConfig(
                foreground_threshold=100,
                min_region_px=1,
                max_regions=5,
            ),
        )


def test_selected_edges_are_subset_of_detector_edges() -> None:
    result = analyze_gray(
        _synthetic_scene(),
        ImageUnderstandingConfig(edge_method="multiscale_canny", detail_level="extreme", min_region_px=4),
    )
    assert np.all(~result.selected_edges | result.edge_mask)

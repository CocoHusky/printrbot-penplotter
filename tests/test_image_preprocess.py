from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from printrbot_penplotter.image_preprocess import (
    ImagePreprocessConfig,
    ThresholdConfig,
    preprocess_image,
    threshold_image,
)
from printrbot_penplotter.raster import RasterTraceConfig, trace_raster


def _gradient_document(path: Path) -> None:
    width, height = 180, 100
    x = np.linspace(150, 245, width, dtype=np.float32)
    background = np.tile(x, (height, 1))
    image = Image.fromarray(background.astype(np.uint8), mode="L").convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.line((18, 28, 160, 28), fill=(45, 45, 45), width=5)
    draw.line((25, 62, 145, 72), fill=(60, 60, 60), width=4)
    image.save(path)


def _color_target(path: Path) -> None:
    image = Image.new("RGB", (80, 50), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 32, 42), fill=(40, 220, 220))
    draw.rectangle((46, 8, 72, 42), fill=(220, 40, 40))
    image.save(path)


def test_preprocessing_is_deterministic_and_records_every_stage(tmp_path: Path) -> None:
    source = tmp_path / "doc.png"
    _gradient_document(source)
    config = ImagePreprocessConfig(
        crop_box=(0.05, 0.05, 0.95, 0.95),
        rotate_deg=1.5,
        grayscale_mode="auto",
        exposure_ev=0.2,
        contrast=1.15,
        gamma=0.95,
        auto_levels=True,
        gaussian_blur_radius_px=0.4,
        median_radius_px=1,
        background_mode="suppress",
        background_radius_px=14,
        background_strength=0.8,
    )

    first = preprocess_image(source, config)
    second = preprocess_image(source, config)

    assert np.array_equal(first.gray, second.gray)
    assert first.metadata == second.metadata
    assert first.metadata["crop_box"] == [0.05, 0.05, 0.95, 0.95]
    assert first.metadata["rotate_deg"] == 1.5
    assert first.metadata["background_mode"] == "suppress"
    assert first.metadata["auto_levels"] is True
    assert first.metadata["effective_grayscale_mode"] in {"luminance", "red", "green", "blue"}


def test_crop_rotation_and_identity_perspective_are_bounded(tmp_path: Path) -> None:
    source = tmp_path / "shape.png"
    image = Image.new("RGB", (120, 80), "white")
    ImageDraw.Draw(image).rectangle((25, 18, 95, 62), fill="black")
    image.save(source)

    result = preprocess_image(
        source,
        ImagePreprocessConfig(
            crop_box=(0.1, 0.1, 0.9, 0.9),
            perspective_quad=(0, 0, 1, 0, 1, 1, 0, 1),
            rotate_deg=5,
            max_dimension_px=100,
            max_processed_pixels=10_000,
        ),
    )

    assert result.gray.ndim == 2
    assert result.gray.shape[0] <= 100 and result.gray.shape[1] <= 100
    assert result.metadata["cropped_width_px"] < 120
    assert result.metadata["perspective_quad"] == [0, 0, 1, 0, 1, 1, 0, 1]


def test_deskew_estimates_small_rotation(tmp_path: Path) -> None:
    source = tmp_path / "skew.png"
    image = Image.new("L", (180, 90), 255)
    draw = ImageDraw.Draw(image)
    draw.line((20, 45, 160, 45), fill=0, width=6)
    image = image.rotate(7, expand=True, fillcolor=255)
    image.save(source)

    result = preprocess_image(source, ImagePreprocessConfig(deskew=True, deskew_max_deg=12))

    assert abs(float(result.metadata["deskew_angle_deg"])) >= 4
    assert abs(float(result.metadata["deskew_angle_deg"])) <= 12


def test_grayscale_channel_selection_changes_color_separation(tmp_path: Path) -> None:
    source = tmp_path / "color.png"
    _color_target(source)

    red = preprocess_image(source, ImagePreprocessConfig(grayscale_mode="red"))
    green = preprocess_image(source, ImagePreprocessConfig(grayscale_mode="green"))
    custom = preprocess_image(
        source,
        ImagePreprocessConfig(grayscale_mode="custom", rgb_weights=(1.0, 0.0, 0.0)),
    )

    assert not np.array_equal(red.gray, green.gray)
    assert np.array_equal(red.gray, custom.gray)


def test_tone_controls_expand_low_contrast_input(tmp_path: Path) -> None:
    source = tmp_path / "flat.png"
    values = np.tile(np.linspace(100, 145, 120, dtype=np.uint8), (60, 1))
    Image.fromarray(values, mode="L").save(source)

    plain = preprocess_image(source)
    tuned = preprocess_image(
        source,
        ImagePreprocessConfig(
            exposure_ev=0.2,
            brightness=-0.05,
            contrast=1.4,
            gamma=0.9,
            auto_levels=True,
            histogram_equalize=True,
            clahe_clip_limit=2.0,
            clahe_grid_size=4,
        ),
    )

    assert tuned.metadata["effective_black_point"] < tuned.metadata["effective_white_point"]
    assert float(np.std(tuned.gray)) > float(np.std(plain.gray))


def test_denoise_filters_reduce_impulse_noise(tmp_path: Path) -> None:
    source = tmp_path / "noise.png"
    rng = np.random.default_rng(4)
    array = np.full((60, 80), 160, dtype=np.uint8)
    ys = rng.integers(0, 60, 250)
    xs = rng.integers(0, 80, 250)
    array[ys, xs] = rng.choice([0, 255], size=250)
    Image.fromarray(array, mode="L").save(source)

    plain = preprocess_image(source)
    cleaned = preprocess_image(
        source,
        ImagePreprocessConfig(
            median_radius_px=1,
            bilateral_radius_px=1,
            bilateral_sigma_color=35,
            bilateral_sigma_space=1.5,
            gaussian_blur_radius_px=0.4,
            despeckle_radius_px=1,
        ),
    )

    assert float(np.std(cleaned.gray)) < float(np.std(plain.gray))


def test_background_suppression_flattens_uneven_illumination(tmp_path: Path) -> None:
    source = tmp_path / "gradient.png"
    _gradient_document(source)

    plain = preprocess_image(source)
    suppressed = preprocess_image(
        source,
        ImagePreprocessConfig(
            background_mode="suppress",
            background_radius_px=18,
            background_strength=1.0,
        ),
    )

    top_plain = float(np.mean(plain.gray[:12]))
    top_suppressed = float(np.mean(suppressed.gray[:12]))
    assert top_suppressed > top_plain
    assert suppressed.metadata["background_mode"] == "suppress"


@pytest.mark.parametrize(
    "mode",
    [
        "otsu",
        "manual",
        "mean",
        "triangle",
        "adaptive_mean",
        "adaptive_gaussian",
        "sauvola",
        "niblack",
    ],
)
def test_all_threshold_modes_are_deterministic(mode: str) -> None:
    gray = np.full((50, 90), 225, dtype=np.uint8)
    gray[12:38, 18:72] = 65
    config = ThresholdConfig(
        mode=mode,
        manual_threshold=140 if mode == "manual" else None,
        window_px=15,
        offset=4,
    )

    first = threshold_image(gray, config)
    second = threshold_image(gray, config)

    assert np.array_equal(first.mask, second.mask)
    assert first.metadata == second.metadata
    assert 0 < np.count_nonzero(first.mask) < gray.size
    assert first.metadata["threshold_mode"] == mode


def test_adaptive_threshold_handles_illumination_gradient() -> None:
    width, height = 150, 60
    background = np.tile(np.linspace(115, 245, width, dtype=np.float32), (height, 1))
    gray = background.astype(np.uint8)
    gray[18:24, 12:135] = np.clip(gray[18:24, 12:135].astype(np.int16) - 55, 0, 255).astype(np.uint8)

    result = threshold_image(
        gray,
        ThresholdConfig(mode="sauvola", window_px=21, offset=2, sauvola_k=0.15),
    )

    assert result.metadata["threshold_min"] < result.metadata["threshold_max"]
    assert np.count_nonzero(result.mask[18:24, 12:135]) > 100


def test_raster_trace_uses_step2_preprocess_and_threshold_records(tmp_path: Path) -> None:
    source = tmp_path / "doc.png"
    _gradient_document(source)
    result = trace_raster(
        source,
        RasterTraceConfig(
            mode="centerline",
            min_component_px=4,
            simplify_px=0.7,
            preprocess=ImagePreprocessConfig(
                grayscale_mode="luminance",
                auto_levels=True,
                background_mode="suppress",
                background_radius_px=12,
            ),
            thresholding=ThresholdConfig(
                mode="adaptive_mean",
                window_px=21,
                offset=8,
            ),
        ),
    )

    assert result.polylines
    assert result.metadata["preprocessing_schema"] == "printrbot-image-preprocess/v2"
    assert result.metadata["threshold_mode"] == "adaptive_mean"
    assert result.metadata["background_mode"] == "suppress"
    assert result.metadata["auto_levels"] is True


def test_invalid_preprocess_and_threshold_settings_fail_early() -> None:
    with pytest.raises(ValueError, match="crop_box"):
        ImagePreprocessConfig(crop_box=(0.8, 0.1, 0.2, 0.9)).validate()
    with pytest.raises(ValueError, match="odd integer"):
        ThresholdConfig(mode="adaptive_mean", window_px=20).validate()
    with pytest.raises(ValueError, match="manual_threshold"):
        ThresholdConfig(mode="manual").validate()

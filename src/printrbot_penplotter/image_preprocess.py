"""Deterministic image normalization for raster-to-plotter workflows.

This module is deliberately upstream of tracing and machine geometry.  It turns
untrusted raster input into a bounded grayscale working image and, separately,
a deterministic foreground mask.  No function here emits plotter geometry or
G-code.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps

GrayscaleMode = Literal[
    "auto",
    "luminance",
    "average",
    "desaturate",
    "red",
    "green",
    "blue",
    "max",
    "min",
    "custom",
]
BackgroundMode = Literal["keep", "suppress", "remove"]
ThresholdMode = Literal[
    "otsu",
    "manual",
    "mean",
    "triangle",
    "adaptive_mean",
    "adaptive_gaussian",
    "sauvola",
    "niblack",
]


@dataclass(frozen=True)
class ImagePreprocessConfig:
    """Reproducible image-normalization settings.

    Crop and perspective coordinates are normalized fractions of the image
    available at that stage, so a saved configuration is independent of the
    source's absolute pixel dimensions.
    """

    crop_box: tuple[float, float, float, float] | None = None
    rotate_deg: float = 0.0
    deskew: bool = False
    deskew_max_deg: float = 15.0
    perspective_quad: tuple[float, float, float, float, float, float, float, float] | None = None

    grayscale_mode: GrayscaleMode = "luminance"
    rgb_weights: tuple[float, float, float] = (0.2126, 0.7152, 0.0722)

    exposure_ev: float = 0.0
    brightness: float = 0.0
    contrast: float = 1.0
    gamma: float = 1.0
    black_point: int = 0
    white_point: int = 255
    auto_levels: bool = False
    auto_levels_low_percentile: float = 1.0
    auto_levels_high_percentile: float = 99.0
    histogram_equalize: bool = False
    clahe_clip_limit: float = 0.0
    clahe_grid_size: int = 8

    gaussian_blur_radius_px: float = 0.0
    median_radius_px: int = 0
    bilateral_radius_px: int = 0
    bilateral_sigma_color: float = 24.0
    bilateral_sigma_space: float = 2.0
    despeckle_radius_px: int = 0

    background_mode: BackgroundMode = "keep"
    background_radius_px: float = 24.0
    background_strength: float = 1.0
    background_remove_threshold: float = 8.0

    max_dimension_px: int = 1200
    max_input_pixels: int = 40_000_000
    max_processed_pixels: int = 1_500_000

    def validate(self) -> None:
        if self.crop_box is not None:
            if len(self.crop_box) != 4 or not all(math.isfinite(v) for v in self.crop_box):
                raise ValueError("crop_box must contain four finite normalized values.")
            left, top, right, bottom = self.crop_box
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                raise ValueError("crop_box must satisfy 0<=left<right<=1 and 0<=top<bottom<=1.")
        if not math.isfinite(self.rotate_deg):
            raise ValueError("Rotation must be finite.")
        if not math.isfinite(self.deskew_max_deg) or not 0 <= self.deskew_max_deg <= 45:
            raise ValueError("deskew_max_deg must be between 0 and 45 degrees.")
        if self.perspective_quad is not None:
            if len(self.perspective_quad) != 8 or not all(math.isfinite(v) for v in self.perspective_quad):
                raise ValueError("perspective_quad must contain eight finite normalized values.")
            if not all(0 <= v <= 1 for v in self.perspective_quad):
                raise ValueError("perspective_quad coordinates must be normalized to 0..1.")
        if self.grayscale_mode not in (
            "auto", "luminance", "average", "desaturate", "red", "green", "blue", "max", "min", "custom"
        ):
            raise ValueError("Unsupported grayscale mode.")
        if len(self.rgb_weights) != 3 or not all(math.isfinite(v) for v in self.rgb_weights):
            raise ValueError("rgb_weights must contain three finite values.")
        if not all(0 <= weight <= 1 for weight in self.rgb_weights):
            raise ValueError("rgb_weights must use normalized 0..1 values.")
        if self.grayscale_mode == "custom" and abs(sum(self.rgb_weights)) < 1e-12:
            raise ValueError("Custom RGB weights must not sum to zero.")
        if not math.isfinite(self.exposure_ev) or not -8 <= self.exposure_ev <= 8:
            raise ValueError("exposure_ev must be between -8 and 8.")
        if not math.isfinite(self.brightness) or not -1 <= self.brightness <= 1:
            raise ValueError("brightness must be between -1 and 1.")
        if not math.isfinite(self.contrast) or not 0.05 <= self.contrast <= 10:
            raise ValueError("contrast must be between 0.05 and 10.")
        if not math.isfinite(self.gamma) or not 0.1 <= self.gamma <= 10:
            raise ValueError("gamma must be between 0.1 and 10.")
        if not 0 <= self.black_point < self.white_point <= 255:
            raise ValueError("black_point and white_point must satisfy 0<=black<white<=255.")
        if not (0 <= self.auto_levels_low_percentile < self.auto_levels_high_percentile <= 100):
            raise ValueError("Auto-level percentiles must be ordered inside 0..100.")
        if not math.isfinite(self.clahe_clip_limit) or self.clahe_clip_limit < 0:
            raise ValueError("clahe_clip_limit must be non-negative.")
        if not 2 <= self.clahe_grid_size <= 64:
            raise ValueError("clahe_grid_size must be between 2 and 64.")
        if not math.isfinite(self.gaussian_blur_radius_px) or not 0 <= self.gaussian_blur_radius_px <= 50:
            raise ValueError("Gaussian blur radius must be between 0 and 50 px.")
        for name, value in (
            ("median_radius_px", self.median_radius_px),
            ("bilateral_radius_px", self.bilateral_radius_px),
            ("despeckle_radius_px", self.despeckle_radius_px),
        ):
            if not isinstance(value, int) or not 0 <= value <= 8:
                raise ValueError(f"{name} must be an integer from 0 to 8.")
        if not math.isfinite(self.bilateral_sigma_color) or self.bilateral_sigma_color <= 0:
            raise ValueError("bilateral_sigma_color must be positive.")
        if not math.isfinite(self.bilateral_sigma_space) or self.bilateral_sigma_space <= 0:
            raise ValueError("bilateral_sigma_space must be positive.")
        if self.background_mode not in ("keep", "suppress", "remove"):
            raise ValueError("background_mode must be keep, suppress, or remove.")
        if not math.isfinite(self.background_radius_px) or self.background_radius_px <= 0:
            raise ValueError("background_radius_px must be positive.")
        if not math.isfinite(self.background_strength) or not 0 <= self.background_strength <= 1:
            raise ValueError("background_strength must be between 0 and 1.")
        if not math.isfinite(self.background_remove_threshold) or not 0 <= self.background_remove_threshold <= 255:
            raise ValueError("background_remove_threshold must be between 0 and 255.")
        if self.max_dimension_px < 16:
            raise ValueError("Maximum raster dimension must be at least 16 pixels.")
        if self.max_input_pixels < 256 or self.max_processed_pixels < 256:
            raise ValueError("Raster pixel limits are unreasonably small.")


@dataclass(frozen=True)
class ThresholdConfig:
    mode: ThresholdMode = "otsu"
    manual_threshold: int | None = None
    invert: bool = False
    window_px: int = 31
    offset: float = 5.0
    sauvola_k: float = 0.2
    sauvola_r: float = 128.0
    niblack_k: float = -0.2

    def validate(self) -> None:
        if self.mode not in (
            "otsu", "manual", "mean", "triangle", "adaptive_mean", "adaptive_gaussian", "sauvola", "niblack"
        ):
            raise ValueError("Unsupported threshold mode.")
        if self.manual_threshold is not None and not 0 <= self.manual_threshold <= 255:
            raise ValueError("Manual threshold must be between 0 and 255.")
        if self.mode == "manual" and self.manual_threshold is None:
            raise ValueError("manual threshold mode requires manual_threshold.")
        if not isinstance(self.window_px, int) or self.window_px < 3 or self.window_px > 501 or self.window_px % 2 == 0:
            raise ValueError("Adaptive threshold window must be an odd integer from 3 to 501.")
        if not math.isfinite(self.offset) or not -255 <= self.offset <= 255:
            raise ValueError("Threshold offset must be finite and within -255..255.")
        if not math.isfinite(self.sauvola_k) or not -2 <= self.sauvola_k <= 2:
            raise ValueError("sauvola_k must be between -2 and 2.")
        if not math.isfinite(self.sauvola_r) or self.sauvola_r <= 0:
            raise ValueError("sauvola_r must be positive.")
        if not math.isfinite(self.niblack_k) or not -2 <= self.niblack_k <= 2:
            raise ValueError("niblack_k must be between -2 and 2.")


@dataclass(frozen=True)
class ImagePreprocessResult:
    gray: np.ndarray
    metadata: dict[str, object]


@dataclass(frozen=True)
class ThresholdResult:
    mask: np.ndarray
    metadata: dict[str, object]


def _composite_white(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        white.alpha_composite(rgba)
        return white.convert("RGB")
    return image.convert("RGB")


def _normalized_crop(image: Image.Image, box: tuple[float, float, float, float] | None) -> Image.Image:
    if box is None:
        return image
    left, top, right, bottom = box
    x0 = max(0, min(image.width - 1, int(round(left * image.width))))
    y0 = max(0, min(image.height - 1, int(round(top * image.height))))
    x1 = max(x0 + 1, min(image.width, int(round(right * image.width))))
    y1 = max(y0 + 1, min(image.height, int(round(bottom * image.height))))
    return image.crop((x0, y0, x1, y1))


def _projective_coefficients(
    destination: list[tuple[float, float]],
    source: list[tuple[float, float]],
) -> tuple[float, ...]:
    rows: list[list[float]] = []
    values: list[float] = []
    for (u, v), (x, y) in zip(destination, source, strict=True):
        rows.append([u, v, 1, 0, 0, 0, -u * x, -v * x])
        values.append(x)
        rows.append([0, 0, 0, u, v, 1, -u * y, -v * y])
        values.append(y)
    try:
        solved = np.linalg.solve(np.asarray(rows, dtype=np.float64), np.asarray(values, dtype=np.float64))
    except np.linalg.LinAlgError as exc:
        raise ValueError("Perspective quadrilateral is degenerate.") from exc
    return tuple(float(value) for value in solved)


def _perspective_correct(
    image: Image.Image,
    quad: tuple[float, float, float, float, float, float, float, float] | None,
) -> Image.Image:
    if quad is None:
        return image
    normalized = [(quad[index], quad[index + 1]) for index in range(0, 8, 2)]
    source = [(x * (image.width - 1), y * (image.height - 1)) for x, y in normalized]
    tl, tr, br, bl = source
    width = max(
        2,
        int(round((math.dist(tl, tr) + math.dist(bl, br)) / 2.0)),
    )
    height = max(
        2,
        int(round((math.dist(tl, bl) + math.dist(tr, br)) / 2.0)),
    )
    destination = [(0.0, 0.0), (width - 1.0, 0.0), (width - 1.0, height - 1.0), (0.0, height - 1.0)]
    coefficients = _projective_coefficients(destination, source)
    return image.transform(
        (width, height),
        Image.Transform.PERSPECTIVE,
        coefficients,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(255, 255, 255),
    )


def _rgb_to_gray(
    image: Image.Image,
    mode: GrayscaleMode,
    weights: tuple[float, float, float],
) -> tuple[np.ndarray, str]:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    channels = [rgb[..., index] for index in range(3)]
    if mode == "auto":
        candidates: dict[str, np.ndarray] = {
            "luminance": 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2],
            "red": channels[0],
            "green": channels[1],
            "blue": channels[2],
        }
        def robust_range(array: np.ndarray) -> float:
            return float(np.percentile(array, 95) - np.percentile(array, 5))
        effective = max(candidates, key=lambda name: (robust_range(candidates[name]), name))
        return np.clip(candidates[effective], 0, 255).astype(np.uint8), effective
    if mode == "luminance":
        gray = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    elif mode == "average":
        gray = np.mean(rgb, axis=2)
    elif mode == "desaturate":
        gray = (np.max(rgb, axis=2) + np.min(rgb, axis=2)) / 2.0
    elif mode == "red":
        gray = channels[0]
    elif mode == "green":
        gray = channels[1]
    elif mode == "blue":
        gray = channels[2]
    elif mode == "max":
        gray = np.max(rgb, axis=2)
    elif mode == "min":
        gray = np.min(rgb, axis=2)
    else:
        total = sum(weights)
        normalized = tuple(weight / total for weight in weights)
        gray = normalized[0] * channels[0] + normalized[1] * channels[1] + normalized[2] * channels[2]
    return np.clip(gray, 0, 255).astype(np.uint8), mode


def otsu_threshold(gray: np.ndarray) -> int:
    histogram = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = float(gray.size)
    weighted_total = float(np.dot(np.arange(256, dtype=np.float64), histogram))
    background_weight = 0.0
    background_sum = 0.0
    best_variance = -1.0
    best_threshold = 127
    for threshold in range(256):
        count = histogram[threshold]
        background_weight += count
        if background_weight <= 0:
            continue
        foreground_weight = total - background_weight
        if foreground_weight <= 0:
            break
        background_sum += threshold * count
        background_mean = background_sum / background_weight
        foreground_mean = (weighted_total - background_sum) / foreground_weight
        variance = background_weight * foreground_weight * (background_mean - foreground_mean) ** 2
        if variance > best_variance:
            best_variance = variance
            best_threshold = threshold
    return int(best_threshold)


def triangle_threshold(gray: np.ndarray) -> int:
    histogram = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    nonzero = np.flatnonzero(histogram)
    if nonzero.size == 0:
        return 127
    left = int(nonzero[0])
    right = int(nonzero[-1])
    peak = int(np.argmax(histogram))
    if peak - left < right - peak:
        xs = np.arange(peak, right + 1, dtype=np.float64)
        ys = histogram[peak : right + 1]
        x1, y1, x2, y2 = float(peak), histogram[peak], float(right), histogram[right]
    else:
        xs = np.arange(left, peak + 1, dtype=np.float64)
        ys = histogram[left : peak + 1]
        x1, y1, x2, y2 = float(left), histogram[left], float(peak), histogram[peak]
    denominator = math.hypot(y2 - y1, x2 - x1)
    if denominator <= 1e-12:
        return peak
    distances = np.abs((y2 - y1) * xs - (x2 - x1) * ys + x2 * y1 - y2 * x1) / denominator
    return int(round(float(xs[int(np.argmax(distances))])))


def _estimate_skew_deg(image: Image.Image, max_deg: float) -> float:
    gray, _ = _rgb_to_gray(image, "luminance", (0.2126, 0.7152, 0.0722))
    threshold = otsu_threshold(gray)
    rows, columns = np.nonzero(gray <= threshold)
    if len(rows) < 20:
        return 0.0
    x = columns.astype(np.float64)
    y = -rows.astype(np.float64)
    x -= np.mean(x)
    y -= np.mean(y)
    xx = float(np.mean(x * x))
    yy = float(np.mean(y * y))
    xy = float(np.mean(x * y))
    if xx + yy <= 1e-9:
        return 0.0
    angle = math.degrees(0.5 * math.atan2(2.0 * xy, xx - yy))
    while angle > 45:
        angle -= 90
    while angle < -45:
        angle += 90
    if abs(angle) > max_deg:
        return 0.0
    return float(angle)


def _bounded_resize(image: Image.Image, config: ImagePreprocessConfig) -> tuple[Image.Image, float]:
    scale = min(1.0, config.max_dimension_px / float(max(image.size)))
    if scale < 1.0:
        image = image.resize(
            (max(1, int(round(image.width * scale))), max(1, int(round(image.height * scale)))),
            Image.Resampling.LANCZOS,
        )
    if image.width * image.height > config.max_processed_pixels:
        secondary = math.sqrt(config.max_processed_pixels / float(image.width * image.height))
        image = image.resize(
            (max(1, int(math.floor(image.width * secondary))), max(1, int(math.floor(image.height * secondary)))),
            Image.Resampling.LANCZOS,
        )
        scale *= secondary
    return image, scale


def _pil_median(gray: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return gray
    return np.asarray(Image.fromarray(gray, mode="L").filter(ImageFilter.MedianFilter(2 * radius + 1)), dtype=np.uint8)


def _bilateral(gray: np.ndarray, radius: int, sigma_color: float, sigma_space: float) -> np.ndarray:
    if radius <= 0:
        return gray
    center = gray.astype(np.float32)
    padded = np.pad(center, radius, mode="reflect")
    numerator = np.zeros_like(center, dtype=np.float64)
    denominator = np.zeros_like(center, dtype=np.float64)
    two_color = 2.0 * sigma_color * sigma_color
    two_space = 2.0 * sigma_space * sigma_space
    height, width = gray.shape
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            neighbor = padded[radius + dy : radius + dy + height, radius + dx : radius + dx + width]
            spatial = math.exp(-(dx * dx + dy * dy) / two_space)
            difference = neighbor - center
            weight = spatial * np.exp(-(difference * difference) / two_color)
            numerator += neighbor * weight
            denominator += weight
    return np.clip(numerator / np.maximum(denominator, 1e-12), 0, 255).astype(np.uint8)


def _histogram_equalize(gray: np.ndarray) -> np.ndarray:
    histogram = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    cdf = histogram.cumsum()
    nonzero = cdf[cdf > 0]
    if nonzero.size == 0 or cdf[-1] <= nonzero[0]:
        return gray.copy()
    lut = np.clip((cdf - nonzero[0]) * 255.0 / (cdf[-1] - nonzero[0]), 0, 255).astype(np.uint8)
    return lut[gray]


def _clahe(gray: np.ndarray, clip_limit: float, grid_size: int) -> np.ndarray:
    if clip_limit <= 0:
        return gray
    height, width = gray.shape
    y_edges = np.linspace(0, height, grid_size + 1, dtype=int)
    x_edges = np.linspace(0, width, grid_size + 1, dtype=int)
    output = np.empty_like(gray)
    for gy in range(grid_size):
        y0, y1 = int(y_edges[gy]), int(y_edges[gy + 1])
        if y1 <= y0:
            continue
        for gx in range(grid_size):
            x0, x1 = int(x_edges[gx]), int(x_edges[gx + 1])
            if x1 <= x0:
                continue
            tile = gray[y0:y1, x0:x1]
            histogram = np.bincount(tile.ravel(), minlength=256).astype(np.int64)
            limit = max(1, int(round(clip_limit * tile.size / 256.0)))
            excess = int(np.sum(np.maximum(histogram - limit, 0)))
            histogram = np.minimum(histogram, limit)
            if excess:
                histogram += excess // 256
                histogram[: excess % 256] += 1
            cdf = histogram.cumsum().astype(np.float64)
            positive = cdf[cdf > 0]
            if positive.size == 0 or cdf[-1] <= positive[0]:
                output[y0:y1, x0:x1] = tile
                continue
            lut = np.clip((cdf - positive[0]) * 255.0 / (cdf[-1] - positive[0]), 0, 255).astype(np.uint8)
            output[y0:y1, x0:x1] = lut[tile]
    return output


def _background_adjust(gray: np.ndarray, config: ImagePreprocessConfig) -> np.ndarray:
    if config.background_mode == "keep":
        return gray
    background = np.asarray(
        Image.fromarray(gray, mode="L").filter(ImageFilter.GaussianBlur(config.background_radius_px)),
        dtype=np.float32,
    )
    source = gray.astype(np.float32)
    normalized = np.clip(source * 255.0 / np.maximum(background, 1.0), 0, 255)
    blended = source * (1.0 - config.background_strength) + normalized * config.background_strength
    if config.background_mode == "remove":
        local_darkness = background - source
        blended = np.where(local_darkness >= config.background_remove_threshold, blended, 255.0)
    return np.clip(blended, 0, 255).astype(np.uint8)


def _apply_tone(gray: np.ndarray, config: ImagePreprocessConfig) -> tuple[np.ndarray, dict[str, object]]:
    work = gray.astype(np.float32)
    work *= float(2.0 ** config.exposure_ev)
    work += config.brightness * 255.0
    work = np.clip(work, 0, 255)

    effective_black = float(config.black_point)
    effective_white = float(config.white_point)
    if config.auto_levels:
        effective_black = float(np.percentile(work, config.auto_levels_low_percentile))
        effective_white = float(np.percentile(work, config.auto_levels_high_percentile))
        if effective_white - effective_black < 1.0:
            effective_black = float(config.black_point)
            effective_white = float(config.white_point)
    work = np.clip((work - effective_black) * 255.0 / max(effective_white - effective_black, 1e-6), 0, 255)
    work = np.clip((work - 127.5) * config.contrast + 127.5, 0, 255)
    work = np.clip(255.0 * np.power(work / 255.0, config.gamma), 0, 255)
    result = work.astype(np.uint8)
    if config.histogram_equalize:
        result = _histogram_equalize(result)
    if config.clahe_clip_limit > 0:
        result = _clahe(result, config.clahe_clip_limit, config.clahe_grid_size)
    return result, {
        "effective_black_point": round(effective_black, 4),
        "effective_white_point": round(effective_white, 4),
    }


def preprocess_image(
    source: str | Path,
    config: ImagePreprocessConfig | None = None,
) -> ImagePreprocessResult:
    """Normalize a raster image into a bounded deterministic grayscale array."""

    config = config or ImagePreprocessConfig()
    config.validate()
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        opened = Image.open(path)
    except Exception as exc:
        raise ValueError(f"Raster image could not be opened: {path}") from exc

    with opened:
        oriented = ImageOps.exif_transpose(opened)
        original_size = oriented.size
        if original_size[0] < 1 or original_size[1] < 1:
            raise ValueError("Raster image has invalid dimensions.")
        if original_size[0] * original_size[1] > config.max_input_pixels:
            raise ValueError(f"Raster image exceeds the {config.max_input_pixels:,}-pixel input limit.")
        image = _composite_white(oriented)

    image = _normalized_crop(image, config.crop_box)
    cropped_size = image.size
    image = _perspective_correct(image, config.perspective_quad)
    perspective_size = image.size
    if abs(config.rotate_deg) > 1e-9:
        image = image.rotate(
            config.rotate_deg,
            resample=Image.Resampling.BICUBIC,
            expand=True,
            fillcolor=(255, 255, 255),
        )
    deskew_angle = 0.0
    if config.deskew:
        deskew_angle = _estimate_skew_deg(image, config.deskew_max_deg)
        if abs(deskew_angle) >= 0.05:
            image = image.rotate(
                -deskew_angle,
                resample=Image.Resampling.BICUBIC,
                expand=True,
                fillcolor=(255, 255, 255),
            )

    transformed_size = image.size
    image, resize_scale = _bounded_resize(image, config)
    gray, effective_grayscale_mode = _rgb_to_gray(image, config.grayscale_mode, config.rgb_weights)

    if config.median_radius_px:
        gray = _pil_median(gray, config.median_radius_px)
    if config.bilateral_radius_px:
        gray = _bilateral(gray, config.bilateral_radius_px, config.bilateral_sigma_color, config.bilateral_sigma_space)
    if config.gaussian_blur_radius_px > 0:
        gray = np.asarray(
            Image.fromarray(gray, mode="L").filter(ImageFilter.GaussianBlur(config.gaussian_blur_radius_px)),
            dtype=np.uint8,
        )
    if config.despeckle_radius_px:
        gray = _pil_median(gray, config.despeckle_radius_px)

    gray = _background_adjust(gray, config)
    gray, tone_metadata = _apply_tone(gray, config)

    metadata: dict[str, object] = {
        "source": str(path),
        "original_width_px": original_size[0],
        "original_height_px": original_size[1],
        "crop_box": list(config.crop_box) if config.crop_box is not None else None,
        "cropped_width_px": cropped_size[0],
        "cropped_height_px": cropped_size[1],
        "perspective_quad": list(config.perspective_quad) if config.perspective_quad is not None else None,
        "perspective_width_px": perspective_size[0],
        "perspective_height_px": perspective_size[1],
        "rotate_deg": config.rotate_deg,
        "deskew": config.deskew,
        "deskew_angle_deg": round(deskew_angle, 6),
        "transformed_width_px": transformed_size[0],
        "transformed_height_px": transformed_size[1],
        "processed_width_px": int(gray.shape[1]),
        "processed_height_px": int(gray.shape[0]),
        "resize_scale": round(float(resize_scale), 6),
        "grayscale_mode": config.grayscale_mode,
        "effective_grayscale_mode": effective_grayscale_mode,
        "rgb_weights": list(config.rgb_weights),
        "exposure_ev": config.exposure_ev,
        "brightness": config.brightness,
        "contrast": config.contrast,
        "gamma": config.gamma,
        "black_point": config.black_point,
        "white_point": config.white_point,
        "auto_levels": config.auto_levels,
        "auto_levels_low_percentile": config.auto_levels_low_percentile,
        "auto_levels_high_percentile": config.auto_levels_high_percentile,
        "histogram_equalize": config.histogram_equalize,
        "clahe_clip_limit": config.clahe_clip_limit,
        "clahe_grid_size": config.clahe_grid_size,
        "gaussian_blur_radius_px": config.gaussian_blur_radius_px,
        "median_radius_px": config.median_radius_px,
        "bilateral_radius_px": config.bilateral_radius_px,
        "bilateral_sigma_color": config.bilateral_sigma_color,
        "bilateral_sigma_space": config.bilateral_sigma_space,
        "despeckle_radius_px": config.despeckle_radius_px,
        "background_mode": config.background_mode,
        "background_radius_px": config.background_radius_px,
        "background_strength": config.background_strength,
        "background_remove_threshold": config.background_remove_threshold,
        "input_mean": round(float(np.mean(gray)), 6),
        "input_std": round(float(np.std(gray)), 6),
    }
    metadata.update(tone_metadata)
    return ImagePreprocessResult(gray=gray, metadata=metadata)


def _box_mean_std(gray: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    radius = window // 2
    padded = np.pad(gray.astype(np.float64), radius, mode="reflect")
    integral = np.pad(padded.cumsum(axis=0).cumsum(axis=1), ((1, 0), (1, 0)), mode="constant")
    squared = padded * padded
    integral_sq = np.pad(squared.cumsum(axis=0).cumsum(axis=1), ((1, 0), (1, 0)), mode="constant")

    def window_sum(table: np.ndarray) -> np.ndarray:
        return table[window:, window:] - table[:-window, window:] - table[window:, :-window] + table[:-window, :-window]

    count = float(window * window)
    mean = window_sum(integral) / count
    variance = np.maximum(window_sum(integral_sq) / count - mean * mean, 0.0)
    return mean, np.sqrt(variance)


def threshold_image(gray: np.ndarray, config: ThresholdConfig | None = None) -> ThresholdResult:
    """Convert normalized grayscale into a deterministic foreground mask."""

    config = config or ThresholdConfig()
    config.validate()
    if gray.ndim != 2 or gray.size == 0:
        raise ValueError("Threshold input must be a non-empty 2-D grayscale image.")
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)

    scalar: float | None = None
    local: np.ndarray | None = None
    if config.mode == "manual":
        scalar = float(config.manual_threshold)
    elif config.mode == "otsu":
        scalar = float(otsu_threshold(gray))
    elif config.mode == "mean":
        scalar = float(np.mean(gray) - config.offset)
    elif config.mode == "triangle":
        scalar = float(triangle_threshold(gray))
    elif config.mode == "adaptive_mean":
        mean, _ = _box_mean_std(gray, config.window_px)
        local = mean - config.offset
    elif config.mode == "adaptive_gaussian":
        radius = max(0.5, config.window_px / 6.0)
        local = np.asarray(
            Image.fromarray(gray, mode="L").filter(ImageFilter.GaussianBlur(radius)),
            dtype=np.float64,
        ) - config.offset
    elif config.mode == "sauvola":
        mean, std = _box_mean_std(gray, config.window_px)
        local = mean * (1.0 + config.sauvola_k * (std / config.sauvola_r - 1.0)) - config.offset
    else:
        mean, std = _box_mean_std(gray, config.window_px)
        local = mean + config.niblack_k * std - config.offset

    threshold = scalar if local is None else local
    mask = gray > threshold if config.invert else gray <= threshold
    metadata: dict[str, object] = {
        "threshold_mode": config.mode,
        "manual_threshold": config.manual_threshold,
        "invert": config.invert,
        "threshold_window_px": config.window_px,
        "threshold_offset": config.offset,
        "sauvola_k": config.sauvola_k,
        "sauvola_r": config.sauvola_r,
        "niblack_k": config.niblack_k,
    }
    if scalar is not None:
        metadata["effective_threshold"] = round(float(scalar), 6)
        metadata["threshold_min"] = round(float(scalar), 6)
        metadata["threshold_max"] = round(float(scalar), 6)
    else:
        assert local is not None
        metadata["effective_threshold"] = round(float(np.mean(local)), 6)
        metadata["threshold_min"] = round(float(np.min(local)), 6)
        metadata["threshold_max"] = round(float(np.max(local)), 6)
    metadata["foreground_pixels"] = int(np.count_nonzero(mask))
    return ThresholdResult(mask=mask.astype(bool), metadata=metadata)

"""Deterministic image feature analysis upstream of vectorization.

Step 3 converts the bounded grayscale output from :mod:`image_preprocess` into
feature maps and descriptive regions.  It does not generate plotter geometry,
styles, or G-code.  Every detector is local, deterministic, and bounded by the
Step 2 preprocessing limits.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter

from .image_preprocess import ImagePreprocessConfig, otsu_threshold, preprocess_image

EdgeMethod = Literal[
    "canny",
    "sobel",
    "scharr",
    "laplacian",
    "dog",
    "morphological",
    "multiscale_canny",
]
DetailLevel = Literal["low", "medium", "high", "extreme"]


@dataclass(frozen=True)
class ImageUnderstandingConfig:
    """Controls for deterministic feature, tone, and region analysis."""

    edge_method: EdgeMethod = "multiscale_canny"
    detail_level: DetailLevel = "medium"
    edge_low: float = 0.10
    edge_high: float = 0.24
    dog_sigma_small: float = 1.0
    dog_sigma_large: float = 2.2
    tonal_bands: tuple[int, ...] = (42, 84, 126, 168, 210)
    min_region_px: int = 12
    foreground_threshold: int | None = None
    foreground_invert: bool = False
    max_regions: int = 4096

    def validate(self) -> None:
        if self.edge_method not in (
            "canny", "sobel", "scharr", "laplacian", "dog", "morphological", "multiscale_canny"
        ):
            raise ValueError("Unsupported edge method.")
        if self.detail_level not in ("low", "medium", "high", "extreme"):
            raise ValueError("detail_level must be low, medium, high, or extreme.")
        if not math.isfinite(self.edge_low) or not 0 <= self.edge_low <= 1:
            raise ValueError("edge_low must be between 0 and 1.")
        if not math.isfinite(self.edge_high) or not 0 <= self.edge_high <= 1:
            raise ValueError("edge_high must be between 0 and 1.")
        if self.edge_low > self.edge_high:
            raise ValueError("edge_low must not exceed edge_high.")
        if not math.isfinite(self.dog_sigma_small) or self.dog_sigma_small <= 0:
            raise ValueError("dog_sigma_small must be positive.")
        if not math.isfinite(self.dog_sigma_large) or self.dog_sigma_large <= self.dog_sigma_small:
            raise ValueError("dog_sigma_large must exceed dog_sigma_small.")
        if not self.tonal_bands or len(self.tonal_bands) > 15:
            raise ValueError("tonal_bands must contain between 1 and 15 thresholds.")
        if tuple(sorted(set(self.tonal_bands))) != self.tonal_bands:
            raise ValueError("tonal_bands must be strictly increasing and unique.")
        if not all(isinstance(v, int) and 1 <= v <= 254 for v in self.tonal_bands):
            raise ValueError("tonal band thresholds must be integers from 1 to 254.")
        if not isinstance(self.min_region_px, int) or self.min_region_px < 1:
            raise ValueError("min_region_px must be a positive integer.")
        if self.foreground_threshold is not None and not 0 <= self.foreground_threshold <= 255:
            raise ValueError("foreground_threshold must be between 0 and 255.")
        if not isinstance(self.max_regions, int) or not 1 <= self.max_regions <= 100_000:
            raise ValueError("max_regions must be between 1 and 100000.")


@dataclass(frozen=True)
class RegionRecord:
    label: int
    area_px: int
    bbox: tuple[int, int, int, int]
    centroid: tuple[float, float]
    mean_gray: float
    mean_edge_strength: float
    touches_border: bool


@dataclass(frozen=True)
class ImageUnderstandingResult:
    gray: np.ndarray
    edge_strength: np.ndarray
    edge_mask: np.ndarray
    selected_edges: np.ndarray
    foreground_mask: np.ndarray
    tone_labels: np.ndarray
    regions: tuple[RegionRecord, ...]
    metadata: dict[str, object]


def _as_gray(gray: np.ndarray) -> np.ndarray:
    if gray.ndim != 2 or gray.size == 0:
        raise ValueError("Image understanding requires a non-empty 2-D grayscale image.")
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    return gray


def _convolve3(gray: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    work = gray.astype(np.float64)
    padded = np.pad(work, 1, mode="reflect")
    out = np.zeros_like(work, dtype=np.float64)
    for row in range(3):
        for col in range(3):
            coefficient = float(kernel[row, col])
            if coefficient:
                out += coefficient * padded[row : row + work.shape[0], col : col + work.shape[1]]
    return out


def _normalize_strength(values: np.ndarray) -> np.ndarray:
    values = np.abs(values).astype(np.float64)
    scale = float(np.percentile(values, 99.5)) if values.size else 0.0
    if scale <= 1e-12:
        scale = float(np.max(values)) if values.size else 0.0
    if scale <= 1e-12:
        return np.zeros(values.shape, dtype=np.float32)
    return np.clip(values / scale, 0.0, 1.0).astype(np.float32)


def _gradient(gray: np.ndarray, *, scharr: bool = False) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if scharr:
        kx = np.array([[-3, 0, 3], [-10, 0, 10], [-3, 0, 3]], dtype=np.float64)
    else:
        kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float64)
    ky = kx.T
    gx = _convolve3(gray, kx)
    gy = _convolve3(gray, ky)
    magnitude = np.hypot(gx, gy)
    return gx, gy, magnitude


def _nonmax_suppression(magnitude: np.ndarray, gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
    angle = (np.rad2deg(np.arctan2(gy, gx)) + 180.0) % 180.0
    padded = np.pad(magnitude, 1, mode="constant")
    center = padded[1:-1, 1:-1]
    left = padded[1:-1, :-2]
    right = padded[1:-1, 2:]
    up = padded[:-2, 1:-1]
    down = padded[2:, 1:-1]
    up_left = padded[:-2, :-2]
    down_right = padded[2:, 2:]
    up_right = padded[:-2, 2:]
    down_left = padded[2:, :-2]

    keep = np.zeros_like(center, dtype=bool)
    horizontal = (angle < 22.5) | (angle >= 157.5)
    diagonal_one = (angle >= 22.5) & (angle < 67.5)
    vertical = (angle >= 67.5) & (angle < 112.5)
    diagonal_two = (angle >= 112.5) & (angle < 157.5)
    keep |= horizontal & (center >= left) & (center >= right)
    keep |= diagonal_one & (center >= up_right) & (center >= down_left)
    keep |= vertical & (center >= up) & (center >= down)
    keep |= diagonal_two & (center >= up_left) & (center >= down_right)
    return np.where(keep, magnitude, 0.0)


def _hysteresis(strength: np.ndarray, low: float, high: float) -> np.ndarray:
    strong = strength >= high
    weak = strength >= low
    if not strong.any():
        return np.zeros_like(strong)
    connected = strong.copy()
    frontier = strong.copy()
    for _ in range(max(strength.shape)):
        padded = np.pad(frontier, 1, mode="constant")
        grown = np.zeros_like(frontier)
        for dr in range(3):
            for dc in range(3):
                if dr == 1 and dc == 1:
                    continue
                grown |= padded[dr : dr + frontier.shape[0], dc : dc + frontier.shape[1]]
        new = grown & weak & ~connected
        if not new.any():
            break
        connected |= new
        frontier = new
    return connected


def _canny(gray: np.ndarray, low: float, high: float, blur: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    if blur > 0:
        work = np.asarray(Image.fromarray(gray, mode="L").filter(ImageFilter.GaussianBlur(blur)), dtype=np.uint8)
    else:
        work = gray
    gx, gy, magnitude = _gradient(work)
    suppressed = _nonmax_suppression(magnitude, gx, gy)
    strength = _normalize_strength(suppressed)
    return strength, _hysteresis(strength, low, high)


def _detector(gray: np.ndarray, config: ImageUnderstandingConfig) -> tuple[np.ndarray, np.ndarray]:
    if config.edge_method == "canny":
        return _canny(gray, config.edge_low, config.edge_high, 1.0)
    if config.edge_method == "multiscale_canny":
        strengths: list[np.ndarray] = []
        masks: list[np.ndarray] = []
        for radius in (0.7, 1.4, 2.4):
            strength, mask = _canny(gray, config.edge_low, config.edge_high, radius)
            strengths.append(strength)
            masks.append(mask)
        return np.maximum.reduce(strengths), np.logical_or.reduce(masks)
    if config.edge_method in ("sobel", "scharr"):
        _, _, magnitude = _gradient(gray, scharr=config.edge_method == "scharr")
        strength = _normalize_strength(magnitude)
        return strength, strength >= config.edge_high
    if config.edge_method == "laplacian":
        kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
        strength = _normalize_strength(_convolve3(gray, kernel))
        return strength, strength >= config.edge_high
    if config.edge_method == "dog":
        small = np.asarray(Image.fromarray(gray, mode="L").filter(ImageFilter.GaussianBlur(config.dog_sigma_small)), dtype=np.float64)
        large = np.asarray(Image.fromarray(gray, mode="L").filter(ImageFilter.GaussianBlur(config.dog_sigma_large)), dtype=np.float64)
        strength = _normalize_strength(small - large)
        return strength, strength >= config.edge_high

    padded = np.pad(gray, 1, mode="edge")
    neighborhoods = [
        padded[r : r + gray.shape[0], c : c + gray.shape[1]].astype(np.int16)
        for r in range(3) for c in range(3)
    ]
    gradient = np.maximum.reduce(neighborhoods) - np.minimum.reduce(neighborhoods)
    strength = _normalize_strength(gradient)
    return strength, strength >= config.edge_high


def _detail_threshold(level: DetailLevel) -> float:
    return {"low": 0.62, "medium": 0.43, "high": 0.28, "extreme": 0.14}[level]


def _neighbor_count(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, mode="constant")
    count = np.zeros(mask.shape, dtype=np.uint8)
    for dr in range(3):
        for dc in range(3):
            if dr == 1 and dc == 1:
                continue
            count += padded[dr : dr + mask.shape[0], dc : dc + mask.shape[1]]
    return count


def _select_edges(edge_strength: np.ndarray, edge_mask: np.ndarray, level: DetailLevel) -> np.ndarray:
    threshold = _detail_threshold(level)
    neighbors = _neighbor_count(edge_mask)
    continuity_bonus = np.clip(neighbors.astype(np.float32) / 5.0, 0.0, 1.0)
    score = 0.78 * edge_strength + 0.22 * continuity_bonus
    selected = edge_mask & (score >= threshold)
    # Keep junction-connected pixels so a selected feature does not acquire obvious one-pixel holes.
    selected |= edge_mask & (neighbors >= 4) & (edge_strength >= threshold * 0.6)
    return selected


def _foreground(gray: np.ndarray, config: ImageUnderstandingConfig) -> tuple[np.ndarray, int]:
    threshold = config.foreground_threshold
    if threshold is None:
        threshold = int(otsu_threshold(gray))
    mask = gray > threshold if config.foreground_invert else gray <= threshold
    return mask.astype(bool), threshold


def _tone_labels(gray: np.ndarray, bands: tuple[int, ...]) -> np.ndarray:
    return np.digitize(gray, np.asarray(bands, dtype=np.uint8), right=False).astype(np.uint8)


def _regions(mask: np.ndarray, gray: np.ndarray, edge_strength: np.ndarray, config: ImageUnderstandingConfig) -> tuple[RegionRecord, ...]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    records: list[RegionRecord] = []
    label = 0
    neighbors = ((-1, 0), (0, -1), (0, 1), (1, 0))

    for start_row, start_col in zip(*np.nonzero(mask)):
        start_row = int(start_row)
        start_col = int(start_col)
        if visited[start_row, start_col]:
            continue
        queue: deque[tuple[int, int]] = deque([(start_row, start_col)])
        visited[start_row, start_col] = True
        pixels: list[tuple[int, int]] = []
        while queue:
            row, col = queue.popleft()
            pixels.append((row, col))
            for dr, dc in neighbors:
                nr, nc = row + dr, col + dc
                if 0 <= nr < height and 0 <= nc < width and mask[nr, nc] and not visited[nr, nc]:
                    visited[nr, nc] = True
                    queue.append((nr, nc))
        if len(pixels) < config.min_region_px:
            continue
        if len(records) >= config.max_regions:
            raise ValueError(f"Image understanding exceeded the {config.max_regions} region limit.")
        label += 1
        rows = np.fromiter((p[0] for p in pixels), dtype=np.int32)
        cols = np.fromiter((p[1] for p in pixels), dtype=np.int32)
        records.append(
            RegionRecord(
                label=label,
                area_px=len(pixels),
                bbox=(int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1),
                centroid=(round(float(cols.mean()), 4), round(float(rows.mean()), 4)),
                mean_gray=round(float(np.mean(gray[rows, cols])), 4),
                mean_edge_strength=round(float(np.mean(edge_strength[rows, cols])), 6),
                touches_border=bool(rows.min() == 0 or cols.min() == 0 or rows.max() == height - 1 or cols.max() == width - 1),
            )
        )
    records.sort(key=lambda record: (-record.area_px, record.bbox, record.label))
    return tuple(records)


def analyze_gray(gray: np.ndarray, config: ImageUnderstandingConfig | None = None) -> ImageUnderstandingResult:
    """Analyze an already-normalized grayscale image into deterministic feature maps."""

    config = config or ImageUnderstandingConfig()
    config.validate()
    gray = _as_gray(gray)
    edge_strength, edge_mask = _detector(gray, config)
    selected = _select_edges(edge_strength, edge_mask, config.detail_level)
    foreground, effective_foreground_threshold = _foreground(gray, config)
    tones = _tone_labels(gray, config.tonal_bands)
    regions = _regions(foreground, gray, edge_strength, config)

    histogram = np.bincount(tones.ravel(), minlength=len(config.tonal_bands) + 1)
    metadata: dict[str, object] = {
        "understanding_schema": "printrbot-image-understanding/v1",
        "edge_method": config.edge_method,
        "detail_level": config.detail_level,
        "edge_low": config.edge_low,
        "edge_high": config.edge_high,
        "edge_pixels": int(np.count_nonzero(edge_mask)),
        "selected_edge_pixels": int(np.count_nonzero(selected)),
        "mean_edge_strength": round(float(np.mean(edge_strength)), 6),
        "foreground_threshold": effective_foreground_threshold,
        "foreground_invert": config.foreground_invert,
        "foreground_pixels": int(np.count_nonzero(foreground)),
        "foreground_fraction": round(float(np.mean(foreground)), 6),
        "tonal_bands": list(config.tonal_bands),
        "tone_histogram": histogram.astype(int).tolist(),
        "regions": len(regions),
        "region_pixels": int(sum(region.area_px for region in regions)),
        "min_region_px": config.min_region_px,
        "max_regions": config.max_regions,
    }
    return ImageUnderstandingResult(
        gray=gray,
        edge_strength=edge_strength,
        edge_mask=edge_mask,
        selected_edges=selected,
        foreground_mask=foreground,
        tone_labels=tones,
        regions=regions,
        metadata=metadata,
    )


def analyze_image(
    source: str | Path,
    *,
    preprocess: ImagePreprocessConfig | None = None,
    understanding: ImageUnderstandingConfig | None = None,
) -> ImageUnderstandingResult:
    """Run Step 2 normalization and then Step 3 feature analysis on a source image."""

    normalized = preprocess_image(source, preprocess)
    result = analyze_gray(normalized.gray, understanding)
    metadata = dict(normalized.metadata)
    metadata.update(result.metadata)
    return ImageUnderstandingResult(
        gray=result.gray,
        edge_strength=result.edge_strength,
        edge_mask=result.edge_mask,
        selected_edges=result.selected_edges,
        foreground_mask=result.foreground_mask,
        tone_labels=result.tone_labels,
        regions=result.regions,
        metadata=metadata,
    )

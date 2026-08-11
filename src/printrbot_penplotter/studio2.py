"""Studio 2.0: unified image-to-plot browser interface with advanced controls."""
from __future__ import annotations

import base64
import hashlib
import io
import tempfile
import time
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from PIL import Image
from starlette.concurrency import run_in_threadpool

from .auto_optimize import AutoOptimizeConfig, optimize_analysis
from .gcode import polylines_to_gcode
from .geometry import compensate_pen_contact, flip_y_in_page, place_on_page, preview_svg, validate_polylines
from .image_preprocess import ImagePreprocessConfig, ThresholdConfig, preprocess_image, threshold_image
from .image_understanding import ImageUnderstandingConfig, ImageUnderstandingResult, analyze_gray, analyze_image
from .line_art import LineArtConfig, STYLE_NAMES, render_line_art_from_analysis
from .models import LayoutConfig, MachineConfig, PageConfig, PenConfig
from .pen_shading import PenShadingConfig, SHADING_STYLE_NAMES, render_pen_shading_from_analysis
from .physical_plot import PhysicalPlotConfig, polyline_length, prepare_physical_plot
from .raster import _remove_small_components

router = APIRouter()
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# Quick is the interactive preview path. Keeping it below 360 px materially
# reduces skeletonization/edge-tracing cost for camera-sized uploads while
# balanced and best retain their existing quality ceilings.
_WORKING_DIMENSION = {"quick": 320, "balanced": 720, "best": 960}
_AUTO_WORKING_DIMENSION = {"quick": 192, "balanced": 320, "best": 960}
_DEFAULT_ART_STROKES = 20_000
_DEFAULT_ART_POINTS = 2_000_000
_DEFAULT_PLOT_STROKES = 5_000
_HARD_ART_STROKES = 200_000
_HARD_ART_POINTS = 20_000_000


@router.get("/studio2", response_class=HTMLResponse)
def studio2() -> str:
    return STUDIO2_HTML


def _png_data_uri(array: np.ndarray) -> str:
    image = Image.fromarray(np.asarray(array, dtype=np.uint8), mode="L")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def _mask_data_uri(mask: np.ndarray) -> str:
    return _png_data_uri(np.where(mask, 0, 255).astype(np.uint8))


def _parse_tonal_bands(value: str) -> tuple[int, ...]:
    try:
        bands = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise ValueError("Tonal bands must be comma-separated integers from 1 to 254.") from exc
    if not bands:
        return (42, 84, 126, 168, 210)
    if tuple(sorted(set(bands))) != bands or not all(1 <= item <= 254 for item in bands):
        raise ValueError("Tonal bands must be unique, strictly increasing integers from 1 to 254.")
    if len(bands) > 15:
        raise ValueError("At most 15 tonal bands are allowed.")
    return bands


def _topographic_analysis(gray: np.ndarray, tonal_bands: tuple[int, ...]) -> ImageUnderstandingResult:
    """Build the grayscale-only input used by topographic contours.

    Topographic art is a set of tone boundaries, not an edge detector or a
    thresholded foreground fill. Keeping this path independent makes the UI
    honest and avoids paying for threshold cleanup, connected regions, and
    edge detection that the recipe never consumes.
    """
    normalized = np.asarray(gray, dtype=np.uint8)
    tones = np.digitize(normalized, np.asarray(tonal_bands, dtype=np.uint8), right=False).astype(np.uint8)
    zeros = np.zeros(normalized.shape, dtype=bool)
    return ImageUnderstandingResult(
        gray=normalized,
        edge_strength=np.zeros(normalized.shape, dtype=np.float32),
        edge_mask=zeros,
        selected_edges=zeros,
        foreground_mask=zeros,
        tone_labels=tones,
        regions=(),
        metadata={
            "understanding_schema": "printrbot-image-understanding/v1",
            "edge_analysis_skipped": True,
            "threshold_analysis_skipped": True,
            "topographic_input": "grayscale",
            "tonal_bands": list(tonal_bands),
        },
    )


def _effective_art_limits(strokes: int, points: int, bypass: bool) -> tuple[int, int]:
    if strokes < 1 or points < 2:
        raise ValueError("Artistic geometry limits must be positive.")
    if strokes > _HARD_ART_STROKES or points > _HARD_ART_POINTS:
        raise ValueError(
            f"Requested artistic limit exceeds the hard memory guard "
            f"({_HARD_ART_STROKES:,} strokes / {_HARD_ART_POINTS:,} points)."
        )
    if bypass:
        return _HARD_ART_STROKES, _HARD_ART_POINTS
    return strokes, points


def _keep_longest_lines(lines: list[list[tuple[float, float]]], limit: int) -> list[list[tuple[float, float]]]:
    """Keep the longest strokes for the interactive preview and plot cap."""

    if len(lines) <= limit:
        return lines
    return sorted(lines, key=lambda line: (-polyline_length(line), tuple(line[0]), len(line)))[:limit]


def _stage_optional_number(form: object, name: str, *, integer: bool = False) -> float | int | None:
    value = str(_stage_form_value(form, name, "")).strip()
    if not value or value == "-1":
        return None
    return int(value) if integer else float(value)


def _apply_threshold_and_component_cleanup(
    analysis: ImageUnderstandingResult,
    *,
    threshold_mode: str,
    threshold_value: str,
    threshold_invert: bool,
    threshold_window_px: int,
    threshold_offset: float,
    min_component_px: int,
) -> ImageUnderstandingResult:
    manual: int | None = None
    if threshold_mode == "manual":
        if threshold_value.strip() == "":
            raise ValueError("Manual threshold mode requires a threshold value from 0 to 255.")
        try:
            manual = int(threshold_value)
        except ValueError as exc:
            raise ValueError("Manual threshold must be an integer from 0 to 255.") from exc

    threshold = threshold_image(
        analysis.gray,
        ThresholdConfig(
            mode=threshold_mode,  # type: ignore[arg-type]
            manual_threshold=manual,
            invert=threshold_invert,
            window_px=threshold_window_px,
            offset=threshold_offset,
        ),
    )
    foreground, kept_components, removed_components, removed_pixels = _remove_small_components(
        threshold.mask, min_component_px
    )
    selected_edges, edge_kept, edge_removed, edge_removed_pixels = _remove_small_components(
        analysis.selected_edges, min_component_px
    )
    metadata = dict(analysis.metadata)
    metadata.update(threshold.metadata)
    metadata.update(
        {
            "studio_component_min_px": min_component_px,
            "studio_foreground_components_kept": kept_components,
            "studio_foreground_components_removed": removed_components,
            "studio_foreground_pixels_removed": removed_pixels,
            "studio_edge_components_kept": edge_kept,
            "studio_edge_components_removed": edge_removed,
            "studio_edge_pixels_removed": edge_removed_pixels,
        }
    )
    return ImageUnderstandingResult(
        gray=analysis.gray,
        edge_strength=analysis.edge_strength,
        edge_mask=analysis.edge_mask,
        selected_edges=selected_edges,
        foreground_mask=foreground,
        tone_labels=analysis.tone_labels,
        regions=analysis.regions,
        metadata=metadata,
    )


def _stage_form_value(form: object, name: str, default: object) -> object:
    value = getattr(form, "get")(name)
    return default if value is None or str(value).strip() == "" else value


def _stage_form_bool(form: object, name: str, default: bool = False) -> bool:
    return str(_stage_form_value(form, name, str(default))).lower() in {"1", "true", "yes", "on"}


def _stage_form_float(form: object, name: str, default: float) -> float:
    return float(_stage_form_value(form, name, default))


def _stage_form_int(form: object, name: str, default: int) -> int:
    return int(_stage_form_value(form, name, default))


def render_studio2_stage(source: Path, *, stage: str, form: object) -> dict[str, object]:
    """Run one interactive image stage without vectorizing later stages."""

    if stage not in {"source", "threshold", "edges", "style"}:
        raise ValueError("Interactive stage must be source, threshold, edges, or style.")
    requested_quality = str(_stage_form_value(form, "quality", "balanced"))
    mode = str(_stage_form_value(form, "mode", "auto"))
    quality = "quick" if mode == "auto" and requested_quality != "best" else requested_quality
    if quality not in _WORKING_DIMENSION:
        raise ValueError("Unsupported quality.")
    preprocess = ImagePreprocessConfig(
        grayscale_mode=str(_stage_form_value(form, "grayscale_mode", "luminance")),  # type: ignore[arg-type]
        rgb_weights=(
            _stage_form_float(form, "rgb_red", 0.2126),
            _stage_form_float(form, "rgb_green", 0.7152),
            _stage_form_float(form, "rgb_blue", 0.0722),
        ),
        exposure_ev=_stage_form_float(form, "exposure_ev", 0.0),
        brightness=_stage_form_float(form, "brightness", 0.0),
        contrast=_stage_form_float(form, "contrast", 1.0),
        gamma=_stage_form_float(form, "gamma", 1.0),
        black_point=_stage_form_int(form, "black_point", 0),
        white_point=_stage_form_int(form, "white_point", 255),
        auto_levels=_stage_form_bool(form, "auto_levels", True),
        histogram_equalize=_stage_form_bool(form, "histogram_equalize"),
        clahe_clip_limit=_stage_form_float(form, "clahe_clip_limit", 0.0),
        gaussian_blur_radius_px=_stage_form_float(form, "gaussian_blur_radius_px", 0.0),
        median_radius_px=_stage_form_int(form, "median_radius_px", 0),
        despeckle_radius_px=_stage_form_int(form, "despeckle_radius_px", 0),
        background_mode=("keep" if str(_stage_form_value(form, "background_mode", "suppress")) == "none" else str(_stage_form_value(form, "background_mode", "suppress"))),  # type: ignore[arg-type]
        background_radius_px=_stage_form_float(form, "background_radius_px", 24.0),
        background_strength=_stage_form_float(form, "background_strength", 1.0),
        max_dimension_px=_AUTO_WORKING_DIMENSION[quality] if mode == "auto" else _WORKING_DIMENSION[quality],
    )
    started = time.perf_counter()
    normalized = preprocess_image(source, preprocess)
    timings = {"grayscale": round(time.perf_counter() - started, 4)}
    if stage == "source":
        return {
            "stage": stage,
            "stages": {"corrected": _png_data_uri(normalized.gray)},
            "metadata": {**normalized.metadata, "studio_stage_seconds": timings},
        }

    style = str(_stage_form_value(form, "style", "refined_pen_sketch"))
    topographic_direct = stage == "style" and mode == "line_art" and style == "topographic"
    understanding = ImageUnderstandingConfig(
        edge_method=str(_stage_form_value(form, "edge_method", "multiscale_canny")),  # type: ignore[arg-type]
        detail_level=str(_stage_form_value(form, "detail", "high")),  # type: ignore[arg-type]
        edge_low=_stage_form_float(form, "edge_low", 0.10),
        edge_high=_stage_form_float(form, "edge_high", 0.24),
        tonal_bands=_parse_tonal_bands(str(_stage_form_value(form, "tonal_bands", "42,84,126,168,210"))),
        min_region_px=max(1, _stage_form_int(form, "min_component_px", 8)),
        compute_edges=stage == "edges" or (stage == "style" and _style_needs_edges(
            mode, style, include_outline=_stage_form_bool(form, "include_outline", True)
        )),
    )
    started = time.perf_counter()
    if topographic_direct:
        analysis = _topographic_analysis(normalized.gray, understanding.tonal_bands)
        timings["grayscale_tones"] = round(time.perf_counter() - started, 4)
    else:
        analysis = analyze_gray(normalized.gray, understanding)
        analysis = _apply_threshold_and_component_cleanup(
            analysis,
            threshold_mode=str(_stage_form_value(form, "threshold_mode", "otsu")),
            threshold_value=str(_stage_form_value(form, "threshold_value", "")),
            threshold_invert=_stage_form_bool(form, "threshold_invert"),
            threshold_window_px=_stage_form_int(form, "threshold_window_px", 31),
            threshold_offset=_stage_form_float(form, "threshold_offset", 5.0),
            min_component_px=_stage_form_int(form, "min_component_px", 8),
        )
        timings["threshold" if stage == "threshold" else "edges"] = round(time.perf_counter() - started, 4)
    stages = {
        "corrected": _png_data_uri(analysis.gray),
        "mask": _mask_data_uri(analysis.foreground_mask),
    }
    if stage == "edges":
        stages["edges"] = _mask_data_uri(analysis.selected_edges)
    if stage == "style":
        max_strokes, max_points = _effective_art_limits(
            _stage_form_int(form, "artistic_stroke_limit", _DEFAULT_ART_STROKES),
            _stage_form_int(form, "artistic_point_limit", _DEFAULT_ART_POINTS),
            _stage_form_bool(form, "bypass_artistic_limit"),
        )
        style = str(_stage_form_value(form, "style", "refined_pen_sketch"))
        plot_stroke_limit = max(1, _stage_form_int(form, "plot_stroke_limit", _DEFAULT_PLOT_STROKES))
        if mode == "auto":
            artistic = optimize_analysis(
                analysis,
                AutoOptimizeConfig(
                    quality=quality,
                    max_output_strokes=max_strokes,
                    max_output_points=max_points,
                    max_skeleton_iterations=64 if quality == "quick" else 256,
                ),
            )
            raw = artistic.polylines
            artistic_meta = artistic.metadata
        elif mode == "line_art":
            simplify_tolerance = _stage_optional_number(form, "style_simplify_tolerance_px")
            smooth_passes = _stage_optional_number(form, "style_smooth_passes", integer=True)
            join_distance = _stage_optional_number(form, "style_join_distance_px")
            min_stroke_length = _stage_form_float(form, "style_min_stroke_length_px", 3.5)
            max_kept_strokes = _stage_form_int(form, "style_max_kept_strokes", 0)
            bridge_distance = _stage_form_float(form, "one_line_bridge_distance_px", 6.0)
            if quality == "quick":
                simplify_tolerance = 0.8 if simplify_tolerance is None else simplify_tolerance
                smooth_passes = 0 if smooth_passes is None else smooth_passes
                join_distance = 0.0 if join_distance is None else join_distance
            artistic = render_line_art_from_analysis(
                analysis,
                LineArtConfig(
                    style=style,
                    max_output_strokes=max_strokes,
                    max_output_points=max_points,
                    max_skeleton_iterations=_stage_form_int(form, "max_skeleton_iterations", 256),
                    edge_threshold=_stage_form_float(form, "style_edge_threshold", 0.58),
                    strong_edge_threshold=_stage_form_float(form, "style_strong_edge_threshold", 0.72),
                    tone_threshold=_stage_form_int(form, "style_tone_threshold", 170),
                    dilation_passes=_stage_form_int(form, "style_dilation_passes", 1),
                    simplify_tolerance_px=simplify_tolerance,
                    smooth_passes=smooth_passes,
                    join_distance_px=join_distance,
                    min_stroke_length_px=min_stroke_length,
                    max_kept_strokes=max_kept_strokes,
                    one_line_bridge_distance_px=bridge_distance,
                ),
            )
            raw = artistic.polylines
            artistic_meta = artistic.metadata
        else:
            outline_style = str(_stage_form_value(form, "outline_style", "refined_pen_sketch"))
            artistic = render_pen_shading_from_analysis(
                analysis,
                PenShadingConfig(
                    style=style,
                    include_outline=_stage_form_bool(form, "include_outline", True),
                    outline_style=outline_style,
                    hatch_spacing_px=_stage_form_float(form, "hatch_spacing_px", 5.0),
                    darkness_threshold=_stage_form_float(form, "darkness_threshold", 0.22),
                    min_stroke_length_px=_stage_form_float(form, "shading_min_stroke_px", 1.25),
                    max_output_strokes=max_strokes,
                    max_output_points=max_points,
                    seed=_stage_form_int(form, "shading_seed", 0),
                    angle_offset_deg=_stage_form_float(form, "shading_angle_offset_deg", 0.0),
                    density_scale=_stage_form_float(form, "shading_density_scale", 1.0),
                    outline_join_distance_px=_stage_form_float(form, "shading_outline_join_distance_px", 0.0),
                ),
            )
            raw = artistic.polylines
            artistic_meta = artistic.metadata
        raw_before_plot_cap = len(raw)
        raw = _keep_longest_lines(raw, plot_stroke_limit)
        artistic_meta = {
            **artistic_meta,
            "plot_stroke_limit": plot_stroke_limit,
            "plot_strokes_dropped_before_preview": raw_before_plot_cap - len(raw),
        }
        placed = place_on_page(raw, PageConfig(), LayoutConfig(fit_mode="fit"), MachineConfig())
        # The stage preview is rendered before Studio 2's final-size transform.
        # Convert the image-space Y orientation here so it matches the final
        # preview and G-code instead of showing an upside-down hatch layer.
        preview_page = PageConfig()
        preview_placed = flip_y_in_page(placed, preview_page)
        stages["edges"] = _mask_data_uri(analysis.selected_edges) if not analysis.metadata.get("edge_analysis_skipped") else ""
        return {
            "stage": stage,
            "preview_svg": preview_svg(preview_placed, preview_page, MachineConfig()),
            "stages": stages,
            "metadata": {
                **analysis.metadata,
                **artistic_meta,
                "artistic_strokes": len(raw),
                "studio_stage_orientation_corrected": True,
                "studio_stage_seconds": timings,
            },
        }
    return {
        "stage": stage,
        "stages": stages,
        "metadata": {**analysis.metadata, "studio_stage_seconds": timings},
    }


def _style_needs_edges(mode: str, style: str, *, include_outline: bool) -> bool:
    """Return whether the selected recipe actually consumes edge maps."""

    if mode == "auto":
        return True
    if mode == "shading":
        # Fill/texture recipes can work from grayscale and the foreground mask
        # alone. An optional outline is the only shading dependency on edges.
        return include_outline
    # These recipes use foreground/tone maps directly and never read edges.
    return style not in {"silhouette", "topographic"}


def _render_pipeline(
    source: Path,
    *,
    filename: str,
    mode: str,
    style: str,
    quality: str,
    detail: str,
    background_mode: str,
    pen_tip_mm: float,
    contact_compensation: bool,
    z_up_mm: float,
    z_down_mm: float,
    air_plot: bool,
    home_before_plot: bool,
    grayscale_mode: str,
    rgb_red: float,
    rgb_green: float,
    rgb_blue: float,
    exposure_ev: float,
    brightness: float,
    contrast: float,
    gamma: float,
    black_point: int,
    white_point: int,
    auto_levels: bool,
    histogram_equalize: bool,
    clahe_clip_limit: float,
    gaussian_blur_radius_px: float,
    median_radius_px: int,
    despeckle_radius_px: int,
    background_radius_px: float,
    background_strength: float,
    threshold_mode: str,
    threshold_value: str,
    threshold_invert: bool,
    threshold_window_px: int,
    threshold_offset: float,
    edge_method: str,
    edge_low: float,
    edge_high: float,
    min_component_px: int,
    tonal_bands: str,
    include_outline: bool,
    outline_style: str,
    hatch_spacing_px: float,
    darkness_threshold: float,
    shading_min_stroke_px: float,
    artistic_stroke_limit: int,
    artistic_point_limit: int,
    plot_stroke_limit: int,
    bypass_artistic_limit: bool,
    max_skeleton_iterations: int,
    style_edge_threshold: float,
    style_strong_edge_threshold: float,
    style_tone_threshold: int,
    style_dilation_passes: int,
    style_simplify_tolerance_px: float | None,
    style_smooth_passes: int | None,
    style_join_distance_px: float | None,
    style_min_stroke_length_px: float,
    style_max_kept_strokes: int,
    one_line_bridge_distance_px: float,
    shading_seed: int,
    shading_angle_offset_deg: float,
    shading_density_scale: float,
    shading_outline_join_distance_px: float,
    shading_hatch_gap_tolerance_px: float,
) -> tuple[str, str, list[list[tuple[float, float]]], dict[str, object], int, int, dict[str, str]]:
    if mode == "line_art" and style not in STYLE_NAMES:
        raise ValueError(f"Style '{style}' is not valid for the Line art pipeline.")
    if mode == "shading" and style not in SHADING_STYLE_NAMES:
        raise ValueError(f"Style '{style}' is not valid for the Pen shading pipeline.")
    if mode not in ("auto", "line_art", "shading"):
        raise ValueError(f"Unknown pipeline: {mode}")

    max_strokes, max_points = _effective_art_limits(
        artistic_stroke_limit, artistic_point_limit, bypass_artistic_limit
    )
    if not 1 <= plot_stroke_limit <= _HARD_ART_STROKES:
        raise ValueError(f"Plot line cap must be between 1 and {_HARD_ART_STROKES:,}.")
    working_dimension = (_AUTO_WORKING_DIMENSION if mode == "auto" else _WORKING_DIMENSION)[quality]
    preprocess = ImagePreprocessConfig(
        grayscale_mode=grayscale_mode,  # type: ignore[arg-type]
        rgb_weights=(rgb_red, rgb_green, rgb_blue),
        exposure_ev=exposure_ev,
        brightness=brightness,
        contrast=contrast,
        gamma=gamma,
        black_point=black_point,
        white_point=white_point,
        auto_levels=auto_levels,
        histogram_equalize=histogram_equalize,
        clahe_clip_limit=clahe_clip_limit,
        gaussian_blur_radius_px=gaussian_blur_radius_px,
        median_radius_px=median_radius_px,
        despeckle_radius_px=despeckle_radius_px,
        background_mode=("keep" if background_mode == "none" else background_mode),  # type: ignore[arg-type]
        background_radius_px=background_radius_px,
        background_strength=background_strength,
        max_dimension_px=working_dimension,
    )
    understanding = ImageUnderstandingConfig(
        edge_method=edge_method,  # type: ignore[arg-type]
        detail_level=detail,  # type: ignore[arg-type]
        edge_low=edge_low,
        edge_high=edge_high,
        tonal_bands=_parse_tonal_bands(tonal_bands),
        min_region_px=max(1, min_component_px),
        compute_edges=_style_needs_edges(mode, style, include_outline=include_outline),
    )
    timings: dict[str, float] = {}
    started = time.perf_counter()
    if mode == "line_art" and style == "topographic":
        analysis = _topographic_analysis(preprocess_image(source, preprocess).gray, understanding.tonal_bands)
        timings["analysis_and_threshold"] = time.perf_counter() - started
    else:
        analysis = analyze_image(source, preprocess=preprocess, understanding=understanding)
        analysis = _apply_threshold_and_component_cleanup(
            analysis,
            threshold_mode=threshold_mode,
            threshold_value=threshold_value,
            threshold_invert=threshold_invert,
            threshold_window_px=threshold_window_px,
            threshold_offset=threshold_offset,
            min_component_px=min_component_px,
        )
        timings["analysis_and_threshold"] = time.perf_counter() - started

    started = time.perf_counter()
    if mode == "auto":
        artistic = optimize_analysis(
            analysis,
            AutoOptimizeConfig(
                quality=quality,
                max_output_strokes=max_strokes,
                max_output_points=max_points,
                max_skeleton_iterations=64 if quality == "quick" else 256,
            ),
        )  # type: ignore[arg-type]
        raw = artistic.polylines
        artistic_meta = artistic.metadata
        effective_style = str(artistic.metadata.get("auto_selected_style", "auto"))
        effective_pipeline = str(artistic.metadata.get("auto_selected_kind", "auto"))
    elif mode == "line_art":
        if quality == "quick":
            # Avoid the quadratic join pass during interactive/full quick
            # renders unless the user explicitly supplied cleanup controls.
            style_simplify_tolerance_px = 0.8 if style_simplify_tolerance_px is None else style_simplify_tolerance_px
            style_smooth_passes = 0 if style_smooth_passes is None else style_smooth_passes
            style_join_distance_px = 0.0 if style_join_distance_px is None else style_join_distance_px
        artistic = render_line_art_from_analysis(
            analysis,
            LineArtConfig(
                style=style,
                max_output_strokes=max_strokes,
                max_output_points=max_points,
                max_skeleton_iterations=max_skeleton_iterations,
                edge_threshold=style_edge_threshold,
                strong_edge_threshold=style_strong_edge_threshold,
                tone_threshold=style_tone_threshold,
                dilation_passes=style_dilation_passes,
                simplify_tolerance_px=style_simplify_tolerance_px,
                smooth_passes=style_smooth_passes,
                join_distance_px=style_join_distance_px,
                min_stroke_length_px=style_min_stroke_length_px,
                max_kept_strokes=style_max_kept_strokes,
                one_line_bridge_distance_px=one_line_bridge_distance_px,
            ),  # type: ignore[arg-type]
        )
        raw = artistic.polylines
        artistic_meta = artistic.metadata
        effective_style = style
        effective_pipeline = "line_art"
    else:
        if outline_style not in STYLE_NAMES:
            raise ValueError(f"Outline style '{outline_style}' is not valid for Pen shading.")
        artistic = render_pen_shading_from_analysis(
            analysis,
            PenShadingConfig(
                style=style,  # type: ignore[arg-type]
                include_outline=include_outline,
                outline_style=outline_style,
                hatch_spacing_px=hatch_spacing_px,
                darkness_threshold=darkness_threshold,
                min_stroke_length_px=shading_min_stroke_px,
                max_output_strokes=max_strokes,
                max_output_points=max_points,
                seed=shading_seed,
                angle_offset_deg=shading_angle_offset_deg,
                density_scale=shading_density_scale,
                outline_join_distance_px=shading_outline_join_distance_px,
                hatch_gap_tolerance_px=shading_hatch_gap_tolerance_px,
            ),
        )
        raw = artistic.polylines
        artistic_meta = artistic.metadata
        effective_style = style
        effective_pipeline = "shading"
    timings["style_vectorization"] = time.perf_counter() - started

    # Always preserve preprocessing/threshold metadata even for from-analysis style APIs.
    metadata = dict(analysis.metadata)
    metadata.update(artistic_meta)

    started = time.perf_counter()
    machine = MachineConfig()
    page = PageConfig()
    layout = LayoutConfig(fit_mode="fit")
    placed = place_on_page(raw, page, layout, machine)
    pen = PenConfig(z_up_mm=z_up_mm, z_down_mm=z_down_mm, air_plot=air_plot, home_before_plot=home_before_plot)
    physical = prepare_physical_plot(
        placed,
        PhysicalPlotConfig(pen_tip_mm=pen_tip_mm, quality=quality, stroke_cap=plot_stroke_limit),  # type: ignore[arg-type]
        pen=pen,
    )
    # A ball-point begins and ends inking roughly half a tip width away from
    # the carriage center.  This is intentionally optional: technical art can
    # prefer mathematically exact endpoints, while text and hand-drawn art
    # benefit from the small extension closing visible joins.
    contact_radius = pen_tip_mm / 2.0 if contact_compensation else 0.0
    final = compensate_pen_contact(physical.polylines, contact_radius)
    validate_polylines(final)
    timings["placement_and_physical_filter"] = time.perf_counter() - started
    started = time.perf_counter()
    preview = preview_svg(final, page, machine)
    gcode = polylines_to_gcode(final, page, pen, machine, title=f"Studio 2: {filename}")
    timings["svg_and_gcode"] = time.perf_counter() - started

    metadata.update(physical.metadata)
    metadata.update(
        {
            "studio_working_max_dimension_px": working_dimension,
            "effective_pipeline": effective_pipeline,
            "effective_style": effective_style,
            "artistic_stroke_limit_requested": artistic_stroke_limit,
            "artistic_point_limit_requested": artistic_point_limit,
            "artistic_limit_bypassed": bypass_artistic_limit,
            "artistic_stroke_limit_effective": max_strokes,
            "artistic_point_limit_effective": max_points,
            "plot_stroke_limit": plot_stroke_limit,
            "plot_strokes_dropped_for_cap": physical.metadata["stroke_cap_dropped"],
            "contact_compensation": contact_compensation,
            "contact_compensation_radius_mm": round(contact_radius, 4),
            "studio_edge_analysis_skipped": bool(metadata.get("edge_analysis_skipped", False)),
            "estimated_print_time_seconds": round(physical.after.estimated_seconds, 2),
            "estimated_print_time_minutes": round(physical.after.estimated_seconds / 60.0, 2),
            "artistic_hard_stroke_guard": _HARD_ART_STROKES,
            "artistic_hard_point_guard": _HARD_ART_POINTS,
            "studio_stage_seconds": {name: round(seconds, 4) for name, seconds in timings.items()},
            "studio_slowest_stage": max(timings, key=timings.get),
        }
    )
    stages = {
        "corrected": _png_data_uri(analysis.gray),
        "mask": _mask_data_uri(analysis.foreground_mask),
        "edges": "" if metadata.get("edge_analysis_skipped", False) else _mask_data_uri(analysis.selected_edges),
    }
    return preview, gcode, final, metadata, len(raw), len(final), stages


@router.post("/api/studio2/render")
async def render_studio2(
    file: UploadFile = File(...),
    mode: Literal["auto", "line_art", "shading"] = Form("auto"),
    style: str = Form("refined_pen_sketch"),
    quality: Literal["quick", "balanced", "best"] = Form("balanced"),
    detail: Literal["low", "medium", "high", "extreme"] = Form("high"),
    background_mode: Literal["none", "suppress", "remove"] = Form("suppress"),
    pen_tip_mm: float = Form(0.5),
    contact_compensation: bool = Form(True),
    z_up_mm: float = Form(5.0),
    z_down_mm: float = Form(0.0),
    air_plot: bool = Form(True),
    home_before_plot: bool = Form(True),
    grayscale_mode: str = Form("luminance"),
    rgb_red: float = Form(0.2126),
    rgb_green: float = Form(0.7152),
    rgb_blue: float = Form(0.0722),
    exposure_ev: float = Form(0.0),
    brightness: float = Form(0.0),
    contrast: float = Form(1.0),
    gamma: float = Form(1.0),
    black_point: int = Form(0),
    white_point: int = Form(255),
    auto_levels: bool = Form(True),
    histogram_equalize: bool = Form(False),
    clahe_clip_limit: float = Form(0.0),
    gaussian_blur_radius_px: float = Form(0.0),
    median_radius_px: int = Form(0),
    despeckle_radius_px: int = Form(0),
    background_radius_px: float = Form(24.0),
    background_strength: float = Form(1.0),
    threshold_mode: str = Form("otsu"),
    threshold_value: str = Form(""),
    threshold_invert: bool = Form(False),
    threshold_window_px: int = Form(31),
    threshold_offset: float = Form(5.0),
    edge_method: str = Form("multiscale_canny"),
    edge_low: float = Form(0.10),
    edge_high: float = Form(0.24),
    min_component_px: int = Form(8),
    tonal_bands: str = Form("42,84,126,168,210"),
    include_outline: bool = Form(True),
    outline_style: str = Form("refined_pen_sketch"),
    hatch_spacing_px: float = Form(5.0),
    darkness_threshold: float = Form(0.22),
    shading_min_stroke_px: float = Form(1.25),
    artistic_stroke_limit: int = Form(_DEFAULT_ART_STROKES),
    artistic_point_limit: int = Form(_DEFAULT_ART_POINTS),
    plot_stroke_limit: int = Form(_DEFAULT_PLOT_STROKES),
    bypass_artistic_limit: bool = Form(False),
    max_skeleton_iterations: int = Form(256),
    style_edge_threshold: float = Form(0.58),
    style_strong_edge_threshold: float = Form(0.72),
    style_tone_threshold: int = Form(170),
    style_dilation_passes: int = Form(1),
    style_simplify_tolerance_px: float = Form(-1.0),
    style_smooth_passes: int = Form(-1),
    style_join_distance_px: float = Form(-1.0),
    style_min_stroke_length_px: float = Form(3.5),
    style_max_kept_strokes: int = Form(0),
    one_line_bridge_distance_px: float = Form(6.0),
    shading_seed: int = Form(0),
    shading_angle_offset_deg: float = Form(0.0),
    shading_density_scale: float = Form(1.0),
    shading_outline_join_distance_px: float = Form(0.0),
    shading_hatch_gap_tolerance_px: float = Form(0.0),
) -> dict[str, object]:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(400, "Uploaded image is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image exceeds the 20 MiB studio upload limit.")
    suffix = Path(file.filename or "upload.png").suffix or ".png"
    filename = file.filename or "image"

    try:
        with tempfile.TemporaryDirectory(prefix="printrbot-studio2-") as directory:
            source = Path(directory) / f"source{suffix}"
            source.write_bytes(data)
            preview, gcode, final, pipeline_meta, raw_strokes, final_strokes, rendered_stages = await run_in_threadpool(
                _render_pipeline,
                source,
                filename=filename,
                mode=mode,
                style=style,
                quality=quality,
                detail=detail,
                background_mode=background_mode,
                pen_tip_mm=pen_tip_mm,
                contact_compensation=contact_compensation,
                z_up_mm=z_up_mm,
                z_down_mm=z_down_mm,
                air_plot=air_plot,
                home_before_plot=home_before_plot,
                grayscale_mode=grayscale_mode,
                rgb_red=rgb_red,
                rgb_green=rgb_green,
                rgb_blue=rgb_blue,
                exposure_ev=exposure_ev,
                brightness=brightness,
                contrast=contrast,
                gamma=gamma,
                black_point=black_point,
                white_point=white_point,
                auto_levels=auto_levels,
                histogram_equalize=histogram_equalize,
                clahe_clip_limit=clahe_clip_limit,
                gaussian_blur_radius_px=gaussian_blur_radius_px,
                median_radius_px=median_radius_px,
                despeckle_radius_px=despeckle_radius_px,
                background_radius_px=background_radius_px,
                background_strength=background_strength,
                threshold_mode=threshold_mode,
                threshold_value=threshold_value,
                threshold_invert=threshold_invert,
                threshold_window_px=threshold_window_px,
                threshold_offset=threshold_offset,
                edge_method=edge_method,
                edge_low=edge_low,
                edge_high=edge_high,
                min_component_px=min_component_px,
                tonal_bands=tonal_bands,
                include_outline=include_outline,
                outline_style=outline_style,
                hatch_spacing_px=hatch_spacing_px,
                darkness_threshold=darkness_threshold,
                shading_min_stroke_px=shading_min_stroke_px,
                artistic_stroke_limit=artistic_stroke_limit,
                artistic_point_limit=artistic_point_limit,
                plot_stroke_limit=plot_stroke_limit,
                bypass_artistic_limit=bypass_artistic_limit,
                max_skeleton_iterations=max_skeleton_iterations,
                style_edge_threshold=style_edge_threshold,
                style_strong_edge_threshold=style_strong_edge_threshold,
                style_tone_threshold=style_tone_threshold,
                style_dilation_passes=style_dilation_passes,
                style_simplify_tolerance_px=(None if style_simplify_tolerance_px < 0 else style_simplify_tolerance_px),
                style_smooth_passes=(None if style_smooth_passes < 0 else style_smooth_passes),
                style_join_distance_px=(None if style_join_distance_px < 0 else style_join_distance_px),
                style_min_stroke_length_px=style_min_stroke_length_px,
                style_max_kept_strokes=style_max_kept_strokes,
                one_line_bridge_distance_px=one_line_bridge_distance_px,
                shading_seed=shading_seed,
                shading_angle_offset_deg=shading_angle_offset_deg,
                shading_density_scale=shading_density_scale,
                shading_outline_join_distance_px=shading_outline_join_distance_px,
                shading_hatch_gap_tolerance_px=shading_hatch_gap_tolerance_px,
            )
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc

    metadata = dict(pipeline_meta)
    metadata.update(
        {
            "studio_schema": "printrbot-studio2/v2",
            "source_filename": file.filename,
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "mode": mode,
            "requested_style": None if mode == "auto" else style,
            "quality": quality,
            "detail": detail,
            "background_mode": background_mode,
            "home_before_plot": home_before_plot,
            "air_plot": air_plot,
            "z_up_mm": z_up_mm,
            "z_down_mm": z_down_mm,
            "contact_compensation": contact_compensation,
        }
    )
    return {
        "preview_svg": preview,
        "gcode": gcode,
        "polylines": final,
        "metadata": metadata,
        "stages": {
            "source": f"data:{file.content_type or 'image/png'};base64,{base64.b64encode(data).decode('ascii')}",
            **rendered_stages,
            "artistic_strokes": raw_strokes,
            "physical_strokes": final_strokes,
        },
    }


STUDIO2_HTML = r'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Printrbot Studio 2.0</title>
<style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#111;background:#f6f6f6}*{box-sizing:border-box}body{margin:0}main{width:min(1540px,calc(100% - 28px));margin:18px auto 50px}.grid{display:grid;grid-template-columns:360px 1fr;gap:18px}.card{background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px}h1{margin:0 0 4px}.tabs{font-size:12px;color:#666;margin-bottom:12px}label{display:block;margin:9px 0 4px;font-size:13px;font-weight:600}select,input,button{width:100%;padding:8px;box-sizing:border-box;border:1px solid #bbb;border-radius:7px;background:#fff}button{margin-top:12px;font-weight:700;cursor:pointer}button:disabled,select:disabled,input:disabled{opacity:.5;cursor:not-allowed}.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}.check{display:flex;align-items:center;gap:7px;font-weight:500}.check input{width:auto}.hint{font-size:12px;color:#666;margin:4px 0 8px}.advanced-toggle{background:#f3f3f3}.advanced{display:none;border-top:1px solid #ddd;margin-top:12px;padding-top:4px}.advanced.open{display:block}.group{border:1px solid #e2e2e2;border-radius:9px;padding:10px;margin-top:10px}.group h3{font-size:14px;margin:0 0 7px}.group.hidden{display:none}.warning{background:#fff4d6;border:1px solid #ebcf7a;border-radius:8px;padding:8px;font-size:12px;margin-top:8px}.stage-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 12px}.stage-tab{width:auto;margin:0;padding:7px 11px;font-size:12px}.stage-tab.active{background:#111;color:#fff;border-color:#111}.preview-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.stage-pane{display:none}.stage-pane.active{display:block}.pane{border:1px solid #e0e0e0;border-radius:10px;padding:10px;min-height:270px;background:#fafafa}.pane h3{margin:0 0 7px;font-size:14px}.pane img{display:block;width:100%;height:250px;object-fit:contain}.pane svg{width:100%;height:250px}.placeholder{height:250px;display:flex;align-items:center;justify-content:center;color:#777;text-align:center}.status{margin-top:10px;padding:10px;border-radius:8px;background:#f2f2f2;font-size:13px}.status.busy{background:#fff4cc}.status.error{background:#ffe2e2;color:#8b0000}.selected-style{font-weight:700;margin-top:8px;padding:8px;border-radius:8px;background:#eef6ff}.spinner{display:inline-block;width:12px;height:12px;border:2px solid #aaa;border-top-color:#111;border-radius:50%;animation:spin .8s linear infinite;margin-right:7px;vertical-align:-2px}@keyframes spin{to{transform:rotate(360deg)}}pre{white-space:pre-wrap;max-height:260px;overflow:auto;font-size:11px}@media(max-width:900px){.grid{grid-template-columns:1fr}.preview-grid{grid-template-columns:1fr}}
</style></head>
<body><main><h1>Printrbot Studio 2.0</h1><div class="tabs">SOURCE · AUTO · STYLE · IMAGE · DETECTION · LINES · SHADING · MOTION · MACHINE</div>
<div class="grid"><form id="f" class="card">
<label>Source image</label><input id="file" name="file" type="file" accept="image/*" required>
<label>Pipeline</label><select id="mode" name="mode"><option value="auto">Auto</option><option value="line_art">Line art</option><option value="shading">Pen shading</option></select>
<div><label>Style</label><select id="style" name="style"></select><div id="styleHint" class="hint"></div></div>
<label>Quality</label><select name="quality"><option>quick</option><option selected>balanced</option><option>best</option></select>
<label>Detail</label><select name="detail"><option>low</option><option>medium</option><option selected>high</option><option>extreme</option></select>
<label>Background</label><select name="background_mode"><option>none</option><option selected>suppress</option><option>remove</option></select>
<label>Pen tip (mm)</label><input name="pen_tip_mm" type="number" value="0.5" min="0.05" max="5" step="0.05">
<div id="contactCompensationControl"><label class="check"><input name="contact_compensation" type="checkbox" checked> Extend open stroke ends for pen ink contact</label><div class="hint">Adds half the pen-tip width to each end of an open stroke. Turn it off for exact technical endpoints.</div></div>
<label>Pen lift height (mm)</label><input name="z_up_mm" type="number" value="5.0" min="0" max="20" step="0.1">
<label class="check"><input name="air_plot" type="checkbox" checked> Air plot</label>
<label class="check"><input name="home_before_plot" type="checkbox" checked> Home before plot</label>
<button id="advancedToggle" class="advanced-toggle" type="button">Advanced image & style controls ▾</button>
<div id="advanced" class="advanced">
<div class="group"><h3>Preprocessing / color → black & white</h3>
<label>Grayscale source</label><select id="grayMode" name="grayscale_mode"><option>luminance</option><option>auto</option><option>average</option><option>desaturate</option><option>red</option><option>green</option><option>blue</option><option>max</option><option>min</option><option>custom</option></select>
<div id="rgbWeights" class="row"><div><label>Red weight (0–1)</label><input name="rgb_red" type="number" min="0" max="1" step="0.01" value="0.2126"></div><div><label>Green weight (0–1)</label><input name="rgb_green" type="number" min="0" max="1" step="0.01" value="0.7152"></div><div><label>Blue weight (0–1)</label><input name="rgb_blue" type="number" min="0" max="1" step="0.01" value="0.0722"></div></div>
<div class="row"><div><label>Exposure (EV)</label><input name="exposure_ev" type="number" min="-8" max="8" step="0.1" value="0"></div><div><label>Brightness</label><input name="brightness" type="number" min="-1" max="1" step="0.05" value="0"></div></div>
<div class="row"><div><label>Contrast</label><input name="contrast" type="number" min="0.05" max="10" step="0.05" value="1"></div><div><label>Gamma</label><input name="gamma" type="number" min="0.1" max="10" step="0.05" value="1"></div></div>
<div class="row"><div><label>Black point</label><input name="black_point" type="number" min="0" max="254" value="0"></div><div><label>White point</label><input name="white_point" type="number" min="1" max="255" value="255"></div></div>
<label class="check"><input name="auto_levels" type="checkbox" checked> Auto levels</label><label class="check"><input name="histogram_equalize" type="checkbox"> Histogram equalization</label>
<div class="row"><div><label>CLAHE clip</label><input name="clahe_clip_limit" type="number" min="0" step="0.1" value="0"></div><div><label>Gaussian blur</label><input name="gaussian_blur_radius_px" type="number" min="0" max="50" step="0.2" value="0"></div></div>
<div class="row"><div><label>Median radius</label><input name="median_radius_px" type="number" min="0" max="8" value="0"></div><div><label>Despeckle radius</label><input name="despeckle_radius_px" type="number" min="0" max="8" value="0"></div></div>
<div class="row"><div><label>Background radius</label><input name="background_radius_px" type="number" min="1" step="1" value="24"></div><div><label>Background strength</label><input name="background_strength" type="number" min="0" max="1" step="0.05" value="1"></div></div>
</div>
<div class="group"><h3>Threshold / foreground</h3>
<label>Threshold method</label><select id="thresholdMode" name="threshold_mode"><option value="otsu">Otsu auto</option><option value="manual">Manual</option><option value="mean">Global mean</option><option value="triangle">Triangle</option><option value="adaptive_mean">Adaptive mean</option><option value="adaptive_gaussian">Adaptive Gaussian</option><option value="sauvola">Sauvola</option><option value="niblack">Niblack</option></select>
<div class="row"><div><label>Manual threshold 0–255</label><input id="thresholdValue" name="threshold_value" type="number" min="0" max="255" placeholder="Auto"></div><div><label>Remove components smaller than (px)</label><input name="min_component_px" type="number" min="1" value="8"></div></div>
<div class="row"><div><label>Adaptive window</label><input name="threshold_window_px" type="number" min="3" max="501" step="2" value="31"></div><div><label>Threshold offset</label><input name="threshold_offset" type="number" min="-255" max="255" step="0.5" value="5"></div></div>
<label class="check"><input name="threshold_invert" type="checkbox"> Invert foreground (light marks on dark)</label>
</div>
<div class="group"><h3>Edges / contours</h3>
<label>Edge method</label><select name="edge_method"><option>multiscale_canny</option><option>canny</option><option>sobel</option><option>scharr</option><option>laplacian</option><option>dog</option><option>morphological</option></select>
<div class="row"><div><label>Edge low</label><input name="edge_low" type="number" min="0" max="1" step="0.01" value="0.10"></div><div><label>Edge high</label><input name="edge_high" type="number" min="0" max="1" step="0.01" value="0.24"></div></div>
<label>Tonal bands (dark → light cut points)</label><input name="tonal_bands" value="42,84,126,168,210"><div class="hint">Move these thresholds to control which grayscale ranges become distinct drawing tones.</div>
</div>
<div id="lineArtAdvanced" class="group hidden"><h3>Line-art style controls</h3>
<div class="row"><div><label>Skeleton iterations</label><input name="max_skeleton_iterations" type="number" min="1" max="1024" value="256"></div><div><label>Dilation passes</label><input name="style_dilation_passes" type="number" min="0" max="4" value="1"></div></div>
<div class="row"><div><label>Edge threshold</label><input name="style_edge_threshold" type="number" min="0" max="1" step="0.01" value="0.58"></div><div><label>Strong edge threshold</label><input name="style_strong_edge_threshold" type="number" min="0" max="1" step="0.01" value="0.72"></div></div>
<div class="row"><div><label>Style tone cutoff</label><input name="style_tone_threshold" type="number" min="0" max="255" value="170"></div><div><label>Simplify tolerance (px)</label><input name="style_simplify_tolerance_px" type="number" min="0" max="20" step="0.05" placeholder="Style default"></div></div>
<div class="row"><div><label>Smoothing passes (blank = default)</label><input name="style_smooth_passes" type="number" min="0" max="8" placeholder="Style default"></div><div><label>Join distance (px)</label><input name="style_join_distance_px" type="number" min="0" max="20" step="0.1" placeholder="Style default"></div></div>
<div class="row"><div><label>Minimum contour length (px)</label><input name="style_min_stroke_length_px" type="number" min="0" max="1000" step="0.25" value="3.5"></div><div><label>Keep longest contours (0 = all)</label><input name="style_max_kept_strokes" type="number" min="0" max="200000" step="1" value="0"></div></div>
<label>One-line bridge distance (px)</label><input name="one_line_bridge_distance_px" type="number" min="0" max="20" step="0.5" value="6"><div class="hint">Only nearby endpoints are connected. Use 0 for no pen-down bridges; larger values can scratch across blank paper.</div>
<div class="hint">These controls apply to every line-art style; the selected style determines which masks use them.</div>
</div>
<div id="shadingAdvanced" class="group hidden"><h3>Pen shading style controls</h3>
<label class="check"><input name="include_outline" type="checkbox" checked> Include outline</label>
<label>Outline style</label><select id="outlineStyle" name="outline_style"></select>
<div class="row"><div><label>Hatch / texture spacing (px)</label><input name="hatch_spacing_px" type="number" min="1" max="100" step="0.5" value="5"></div><div><label>Darkness cutoff</label><input name="darkness_threshold" type="number" min="0" max="1" step="0.01" value="0.22"></div></div>
<div class="row"><div><label>Minimum shading stroke (px)</label><input name="shading_min_stroke_px" type="number" min="0" step="0.25" value="1.25"></div><div><label>Variation seed</label><input name="shading_seed" type="number" step="1" value="0"></div></div>
<div class="row"><div><label>Angle offset (degrees)</label><input name="shading_angle_offset_deg" type="number" min="-180" max="180" step="1" value="0"></div><div><label>Density scale</label><input name="shading_density_scale" type="number" min="0.25" max="4" step="0.05" value="1"></div></div>
<label>Outline join distance (px)</label><input name="shading_outline_join_distance_px" type="number" min="0" max="20" step="0.1" value="0"><div class="hint">Zero is the fast default for dense texture outlines.</div>
<label>Bridge tiny hatch gaps (px)</label><input name="shading_hatch_gap_tolerance_px" type="number" min="0" max="4" step="0.5" value="0"><div class="hint">Use 1–2 px to turn fragmented hatch marks into longer strokes. It may draw across tiny white pinholes; leave at 0 when boundaries must stay exact.</div>
</div>
<div id="geometryLimits" class="group"><h3>Artistic geometry limit</h3>
<div class="row"><div><label>Max artistic strokes</label><input id="strokeLimit" name="artistic_stroke_limit" type="number" min="1" max="200000" value="20000"></div><div><label>Max artistic points</label><input id="pointLimit" name="artistic_point_limit" type="number" min="2" max="20000000" value="2000000"></div></div>
<label>Max plotted lines (longest kept)</label><input name="plot_stroke_limit" type="number" min="1" max="200000" value="5000"><div class="hint">Shorter lines are dropped first to reduce pen travel and Z lifts.</div>
<label class="check"><input id="bypassLimit" name="bypass_artistic_limit" type="checkbox"> Bypass soft artistic limit (expert)</label>
<div class="warning">Bypass raises the soft limit to a hard memory guard of 200,000 strokes / 20,000,000 points. This can be slow and can create very large plot jobs.</div>
</div>
</div>
<button id="generate">Generate drawing</button><div id="status" class="status">Choose an image. The original will appear immediately.</div><div id="selectedStyle" class="selected-style" style="display:none"></div></form>
<section class="card"><h2>Preview stages</h2><div class="stage-tabs" role="tablist" aria-label="Processing stages"><button type="button" class="stage-tab active" data-stage="source">Source</button><button type="button" class="stage-tab" data-stage="gray">Grayscale</button><button type="button" class="stage-tab" data-stage="mask">Black &amp; white</button><button type="button" class="stage-tab" data-stage="edges">Edges</button><button type="button" class="stage-tab" data-stage="final">Final plot</button></div><div class="preview-grid">
<div class="pane stage-pane" data-stage-pane="source"><h3>Original</h3><div id="sourcePreview" class="placeholder">No image selected.</div></div>
<div class="pane stage-pane" data-stage-pane="gray"><h3>Quick raster preview</h3><div id="rasterPreview" class="placeholder">Select an image. This preview does not vectorize.</div><h3>Corrected grayscale</h3><div id="corrected" class="placeholder">Generate to inspect preprocessing.</div></div>
<div class="pane stage-pane" data-stage-pane="mask"><h3>Foreground / threshold mask</h3><div id="mask" class="placeholder">Generate to inspect thresholding.</div></div>
<div class="pane stage-pane" data-stage-pane="edges"><h3>Selected edges</h3><div id="edges" class="placeholder">Generate to inspect edge detection.</div><div class="hint">Edge analysis is skipped automatically when the selected style does not use it.</div></div>
<div class="pane stage-pane" data-stage-pane="final"><h3>Exact machine preview</h3><div id="preview" class="placeholder">Generate a drawing to see final pen paths.</div></div>
</div><h3>Pipeline metadata</h3><pre id="meta"></pre></section></div></main>
<script>
const lineStyles=['minimal_outline','clean_outline','detailed_outline','continuous_contour','one_line_art','loose_sketch','refined_pen_sketch','pet_portrait','portrait','comic_ink','architectural_pen','technical_drawing','silhouette','topographic'];
const shadingStyles=['parallel_hatch','crosshatch','dense_crosshatch','curved_hatch','contour_hatch','directional_hatch','scribble','stipple','pointillism','halftone','engraving','etching','woodcut','scratchboard','fur_texture','hair_texture'];
const form=document.getElementById('f'),mode=document.getElementById('mode'),style=document.getElementById('style'),styleHint=document.getElementById('styleHint'),fileInput=document.getElementById('file'),sourcePreview=document.getElementById('sourcePreview'),rasterPreview=document.getElementById('rasterPreview'),preview=document.getElementById('preview'),corrected=document.getElementById('corrected'),mask=document.getElementById('mask'),edges=document.getElementById('edges'),meta=document.getElementById('meta'),status=document.getElementById('status'),button=document.getElementById('generate'),selectedStyle=document.getElementById('selectedStyle'),advanced=document.getElementById('advanced'),advancedToggle=document.getElementById('advancedToggle'),lineArtAdvanced=document.getElementById('lineArtAdvanced'),shadingAdvanced=document.getElementById('shadingAdvanced'),geometryLimits=document.getElementById('geometryLimits'),outlineStyle=document.getElementById('outlineStyle'),grayMode=document.getElementById('grayMode'),rgbWeights=document.getElementById('rgbWeights'),thresholdMode=document.getElementById('thresholdMode'),thresholdValue=document.getElementById('thresholdValue'),bypassLimit=document.getElementById('bypassLimit'),strokeLimit=document.getElementById('strokeLimit'),pointLimit=document.getElementById('pointLimit');let objectUrl=null;let rendering=false;let renderGeneration=0;
function options(select,values,current){select.innerHTML='';for(const value of values){const o=document.createElement('option');o.value=value;o.textContent=value.replaceAll('_',' ');if(value===current)o.selected=true;select.appendChild(o);}}
options(outlineStyle,lineStyles,'refined_pen_sketch');
function setupControlSections(){const groups=[...document.querySelectorAll('#advanced>.group')];const size=document.getElementById('finalSize');if(size)groups.unshift(size);for(const group of groups){if(group.parentElement.classList.contains('control-section'))continue;const section=document.createElement('details');section.className='control-section';section.open=group.id==='finalSize';const heading=group.querySelector('h3');const summary=document.createElement('summary');summary.textContent=heading?heading.textContent:'Controls';section.appendChild(summary);group.replaceWith(section);section.appendChild(group);}syncControlSections();}
function syncControlSections(){document.querySelectorAll('.control-section').forEach(section=>{const group=section.querySelector(':scope>.group');section.hidden=!!group&&group.classList.contains('hidden');});}
setupControlSections();
function setupStageTabs(){const tabs=[...document.querySelectorAll('.stage-tab')];const panes=[...document.querySelectorAll('.stage-pane')];function select(stage){tabs.forEach(tab=>{const active=tab.dataset.stage===stage;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',active?'true':'false');});panes.forEach(pane=>pane.classList.toggle('active',pane.dataset.stagePane===stage));}tabs.forEach(tab=>tab.addEventListener('click',()=>select(tab.dataset.stage)));select('source');}
setupStageTabs();
function updatePipeline(){const m=mode.value;if(m==='auto'){options(style,['Auto chooses after analysis'],'Auto chooses after analysis');style.disabled=true;style.name='';styleHint.textContent='Auto ranks compatible recipes and renders the winner. Limits still apply to the selected recipe.';lineArtAdvanced.classList.add('hidden');shadingAdvanced.classList.add('hidden');geometryLimits.classList.remove('hidden');}else if(m==='line_art'){style.disabled=false;style.name='style';options(style,lineStyles,'refined_pen_sketch');styleHint.textContent='Only valid line-art styles are shown.';lineArtAdvanced.classList.remove('hidden');shadingAdvanced.classList.add('hidden');geometryLimits.classList.remove('hidden');}else{style.disabled=false;style.name='style';options(style,shadingStyles,'crosshatch');styleHint.textContent='Only valid pen-shading styles are shown.';lineArtAdvanced.classList.add('hidden');shadingAdvanced.classList.remove('hidden');geometryLimits.classList.remove('hidden');}syncControlSections();}
mode.addEventListener('change',updatePipeline);updatePipeline();
advancedToggle.onclick=()=>{advanced.classList.toggle('open');advancedToggle.textContent=advanced.classList.contains('open')?'Advanced image & style controls ▴':'Advanced image & style controls ▾';};
function updateGray(){rgbWeights.style.display=grayMode.value==='custom'?'grid':'none';}grayMode.addEventListener('change',updateGray);updateGray();
function updateThreshold(){thresholdValue.disabled=thresholdMode.value!=='manual';}thresholdMode.addEventListener('change',updateThreshold);updateThreshold();
function updateLimit(){strokeLimit.disabled=bypassLimit.checked;pointLimit.disabled=bypassLimit.checked;}bypassLimit.addEventListener('change',updateLimit);updateLimit();
function clearGeneratedResult(){window.__studioLast=null;preview.className='placeholder';preview.textContent='Generate a drawing to see final pen paths.';for(const target of [corrected,mask,edges]){target.className='placeholder';target.textContent=target===corrected?'Generate to inspect preprocessing.':target===mask?'Generate to inspect thresholding.':'Generate to inspect edge detection.';}meta.textContent='';selectedStyle.style.display='none';for(const id of ['floatingSaveSvg','floatingSaveGcode','saveSvg','saveGcode']){const save=document.getElementById(id);if(save)save.disabled=true;}}
fileInput.addEventListener('change',()=>{renderGeneration++;clearGeneratedResult();const file=fileInput.files&&fileInput.files[0];if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=null;}if(!file){sourcePreview.className='placeholder';sourcePreview.textContent='No image selected.';rasterPreview.className='placeholder';rasterPreview.textContent='Select an image. This preview does not vectorize.';return;}objectUrl=URL.createObjectURL(file);sourcePreview.className='';sourcePreview.innerHTML='';const img=document.createElement('img');img.src=objectUrl;img.alt='Selected source image';sourcePreview.appendChild(img);const rasterImage=new Image();rasterImage.onload=()=>{const scale=Math.min(1,320/Math.max(rasterImage.naturalWidth,rasterImage.naturalHeight));const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(rasterImage.naturalWidth*scale));canvas.height=Math.max(1,Math.round(rasterImage.naturalHeight*scale));canvas.setAttribute('aria-label','Quick raster preview');canvas.getContext('2d').drawImage(rasterImage,0,0,canvas.width,canvas.height);rasterPreview.className='';rasterPreview.innerHTML='';rasterPreview.appendChild(canvas);};rasterImage.src=objectUrl;status.className='status';status.textContent='Image loaded. Quick raster preview is ready; click Generate drawing to create plot paths.';});
function stageImage(target,uri){target.innerHTML='';if(!uri){target.className='placeholder';target.textContent='Not required for this style.';return;}target.className='';const img=document.createElement('img');img.src=uri;target.appendChild(img);}
form.onsubmit=async(e)=>{e.preventDefault();if(rendering)return;const requestId=++renderGeneration;rendering=true;clearGeneratedResult();const fd=new FormData(form);for(const n of ['style_simplify_tolerance_px','style_smooth_passes','style_join_distance_px'])if(String(fd.get(n)||'').trim()==='')fd.set(n,'-1');if(mode.value==='auto')fd.set('style','');for(const n of ['air_plot','home_before_plot','auto_levels','histogram_equalize','threshold_invert','include_outline','bypass_artistic_limit'])fd.set(n,form.elements[n]&&form.elements[n].checked?'true':'false');if(bypassLimit.checked){fd.set('artistic_stroke_limit','20000');fd.set('artistic_point_limit','2000000');}button.disabled=true;const start=performance.now();status.className='status busy';status.innerHTML='<span class="spinner"></span>Generating drawing…';preview.className='placeholder';preview.textContent='Rendering plot paths…';const timer=setInterval(()=>{if(requestId===renderGeneration)status.innerHTML='<span class="spinner"></span>Generating drawing… '+((performance.now()-start)/1000).toFixed(1)+' s';},250);try{const r=await fetch('/api/studio2/render',{method:'POST',body:fd});const j=await r.json();if(!r.ok)throw new Error(j.detail||'Render failed');if(requestId!==renderGeneration)return;preview.className='';preview.innerHTML=j.preview_svg;stageImage(corrected,j.stages.corrected);stageImage(mask,j.stages.mask);stageImage(edges,j.stages.edges);const stageTimes=j.metadata.studio_stage_seconds||{};const timingText=Object.entries(stageTimes).map(([name,seconds])=>name.replaceAll('_',' ')+': '+Number(seconds).toFixed(2)+'s').join(' · ');meta.textContent=JSON.stringify(j.metadata,null,2);const effective=(j.metadata.effective_pipeline||j.metadata.mode)+' · '+(j.metadata.effective_style||'');selectedStyle.style.display='block';selectedStyle.textContent=(mode.value==='auto'?'Auto selected: ':'Selected: ')+effective;status.className='status';status.textContent='Done in '+((performance.now()-start)/1000).toFixed(1)+' s · '+j.stages.artistic_strokes+' artistic strokes → '+j.stages.physical_strokes+' plot strokes · estimated plot time '+(j.metadata.estimated_print_time||'unknown')+(timingText?' · '+timingText:'')+'. Ready for another image.';}catch(err){if(requestId!==renderGeneration)return;preview.className='placeholder';preview.textContent='No drawing generated.';status.className='status error';status.textContent=err instanceof Error?err.message:String(err);}finally{clearInterval(timer);if(requestId===renderGeneration){rendering=false;button.disabled=false;}}};
</script></body></html>'''

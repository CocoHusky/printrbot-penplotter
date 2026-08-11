from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import pytest

from printrbot_penplotter.image_preprocess import ImagePreprocessConfig
from printrbot_penplotter.image_understanding import ImageUnderstandingConfig, analyze_image
from printrbot_penplotter.line_art import (
    STYLE_NAMES,
    LineArtConfig,
    _select_useful_strokes,
    render_line_art,
    render_line_art_from_analysis,
)


def _fixture(path: Path) -> None:
    image = Image.new("L", (64, 48), 245)
    draw = ImageDraw.Draw(image)
    draw.ellipse((6, 5, 57, 42), fill=180, outline=35, width=2)
    draw.ellipse((19, 16, 24, 21), fill=20)
    draw.ellipse((40, 16, 45, 21), fill=20)
    draw.polygon([(27, 25), (37, 25), (32, 31)], fill=30)
    draw.arc((20, 23, 44, 38), 20, 160, fill=60, width=1)
    image.save(path)


def _line_drawing_fixture(path: Path) -> None:
    image = Image.new("L", (96, 72), 255)
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 8, 82, 62), outline=0, width=2)
    draw.line((18, 48, 38, 30, 56, 48, 78, 24), fill=0, width=2)
    draw.arc((30, 20, 64, 54), 205, 335, fill=0, width=2)
    image.save(path)


def _analysis(path: Path):
    return analyze_image(
        path,
        preprocess=ImagePreprocessConfig(auto_levels=True),
        understanding=ImageUnderstandingConfig(
            edge_method="multiscale_canny",
            detail_level="medium",
            min_region_px=3,
        ),
    )


def test_all_named_styles_produce_valid_geometry(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    analysis = _analysis(path)
    for name in STYLE_NAMES:
        result = render_line_art_from_analysis(analysis, LineArtConfig(style=name))
        assert result.polylines
        assert all(len(line) >= 2 for line in result.polylines)
        assert result.metadata["line_art_style"] == name
        assert result.metadata["line_art_schema"] == "printrbot-line-art/v1"
        assert result.metadata["output_style_points"] >= 2


def test_render_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    kwargs = dict(
        config=LineArtConfig(style="refined_pen_sketch"),
        preprocess=ImagePreprocessConfig(auto_levels=True, background_mode="suppress"),
        understanding=ImageUnderstandingConfig(edge_method="multiscale_canny", detail_level="medium", min_region_px=3),
    )
    first = render_line_art(path, **kwargs)
    second = render_line_art(path, **kwargs)
    assert first.polylines == second.polylines
    assert first.metadata == second.metadata
    assert first.metadata["understanding_schema"] == "printrbot-image-understanding/v1"
    assert first.metadata["line_art_schema"] == "printrbot-line-art/v1"


def test_minimal_has_no_more_strokes_than_detailed(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    analysis = _analysis(path)
    minimal = render_line_art_from_analysis(analysis, LineArtConfig(style="minimal_outline"))
    detailed = render_line_art_from_analysis(analysis, LineArtConfig(style="detailed_outline"))
    assert len(minimal.polylines) <= len(detailed.polylines)


def test_silhouette_is_closed_contour_geometry(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    result = render_line_art_from_analysis(_analysis(path), LineArtConfig(style="silhouette"))
    assert any(line[0] == line[-1] for line in result.polylines)


def test_one_line_art_records_intentional_bridges(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    result = render_line_art_from_analysis(_analysis(path), LineArtConfig(style="one_line_art"))
    assert "artistic_bridges" in result.metadata
    assert result.metadata["artistic_bridges"] >= 0
    assert result.metadata["artistic_max_bridge_px"] <= 6.0
    assert result.metadata["artistic_unconnected_chains"] >= 0


def test_line_art_can_drop_short_traces_and_keep_longest() -> None:
    lines = [
        [(0.0, 0.0), (1.0, 0.0)],
        [(0.0, 2.0), (8.0, 2.0)],
        [(0.0, 4.0), (5.0, 4.0)],
    ]
    selected, removed_short, cap_dropped = _select_useful_strokes(
        lines, min_length_px=2.0, max_strokes=1
    )
    assert selected == [[(0.0, 2.0), (8.0, 2.0)]]
    assert removed_short == 1
    assert cap_dropped == 1


def test_pet_and_portrait_presets_do_not_claim_semantic_recognition(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    analysis = _analysis(path)
    for style in ("pet_portrait", "portrait"):
        result = render_line_art_from_analysis(analysis, LineArtConfig(style=style))
        assert result.metadata["semantic_recognition"] is False


def test_invalid_style_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported line-art style"):
        LineArtConfig(style="watercolor").validate()  # type: ignore[arg-type]


def test_output_limits_enforced(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    analysis = _analysis(path)
    with pytest.raises(ValueError, match="geometry limits"):
        render_line_art_from_analysis(
            analysis,
            LineArtConfig(style="detailed_outline", max_output_strokes=1, max_output_points=10),
        )


def test_style_controls_are_applied_and_recorded(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    result = render_line_art_from_analysis(
        _analysis(path),
        LineArtConfig(
            style="clean_outline",
            max_skeleton_iterations=64,
            edge_threshold=0.35,
            strong_edge_threshold=0.65,
            tone_threshold=120,
            dilation_passes=2,
            simplify_tolerance_px=0.8,
            smooth_passes=1,
        ),
    )
    assert result.metadata["style_edge_threshold"] == 0.35
    assert result.metadata["style_strong_edge_threshold"] == 0.65
    assert result.metadata["style_tone_threshold"] == 120
    assert result.metadata["style_dilation_passes"] == 2
    assert result.metadata["style_simplify_tolerance_px"] == 0.8
    assert result.metadata["style_smooth_passes"] == 1


def test_sparse_ink_uses_one_centerline_trace_instead_of_doubled_edges(tmp_path: Path) -> None:
    path = tmp_path / "ink.png"
    _line_drawing_fixture(path)
    result = render_line_art(
        path,
        LineArtConfig(style="clean_outline", max_skeleton_iterations=64),
        preprocess=ImagePreprocessConfig(auto_levels=True),
        understanding=ImageUnderstandingConfig(
            edge_method="multiscale_canny", detail_level="low", min_region_px=3
        ),
    )
    assert result.metadata["source_is_line_drawing"] is True
    assert result.metadata["line_drawing_trace"] == "foreground_centerline"
    assert result.metadata["output_style_strokes"] > 0


def test_styles_preserve_finite_geometry(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    result = render_line_art_from_analysis(_analysis(path), LineArtConfig(style="comic_ink"))
    values = np.asarray([point for line in result.polylines for point in line], dtype=float)
    assert np.isfinite(values).all()

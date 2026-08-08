from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import pytest

from printrbot_penplotter.image_preprocess import ImagePreprocessConfig
from printrbot_penplotter.image_understanding import ImageUnderstandingConfig, analyze_image
from printrbot_penplotter.pen_shading import (
    SHADING_STYLE_NAMES,
    PenShadingConfig,
    render_pen_shading,
    render_pen_shading_from_analysis,
)


def _fixture(path: Path) -> None:
    image = Image.new("L", (84, 64), 248)
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 6, 76, 58), fill=188, outline=38, width=2)
    draw.ellipse((22, 20, 30, 28), fill=24)
    draw.ellipse((54, 20, 62, 28), fill=24)
    draw.polygon([(36, 34), (48, 34), (42, 43)], fill=34)
    draw.rectangle((18, 44, 66, 53), fill=112)
    draw.line((14, 50, 70, 18), fill=78, width=2)
    image.save(path)


def _analysis(path: Path):
    return analyze_image(
        path,
        preprocess=ImagePreprocessConfig(auto_levels=True),
        understanding=ImageUnderstandingConfig(
            edge_method="multiscale_canny",
            detail_level="high",
            min_region_px=3,
        ),
    )


def test_all_named_shading_styles_produce_finite_geometry(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    analysis = _analysis(path)
    for name in SHADING_STYLE_NAMES:
        result = render_pen_shading_from_analysis(
            analysis,
            PenShadingConfig(style=name, hatch_spacing_px=7.0),
        )
        assert result.polylines
        values = np.asarray([point for line in result.polylines for point in line], dtype=float)
        assert np.isfinite(values).all()
        assert result.metadata["pen_shading_schema"] == "printrbot-pen-shading/v1"
        assert result.metadata["pen_shading_style"] == name


def test_shading_render_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    kwargs = dict(
        config=PenShadingConfig(style="crosshatch", hatch_spacing_px=6.0, seed=17),
        preprocess=ImagePreprocessConfig(auto_levels=True, background_mode="suppress"),
        understanding=ImageUnderstandingConfig(detail_level="medium", min_region_px=3),
    )
    first = render_pen_shading(path, **kwargs)
    second = render_pen_shading(path, **kwargs)
    assert first.polylines == second.polylines
    assert first.metadata == second.metadata
    assert first.metadata["understanding_schema"] == "printrbot-image-understanding/v1"
    assert first.metadata["pen_shading_schema"] == "printrbot-pen-shading/v1"


def test_crosshatch_adds_tonal_layers(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    analysis = _analysis(path)
    parallel = render_pen_shading_from_analysis(
        analysis,
        PenShadingConfig(style="parallel_hatch", include_outline=False, hatch_spacing_px=6.0),
    )
    cross = render_pen_shading_from_analysis(
        analysis,
        PenShadingConfig(style="crosshatch", include_outline=False, hatch_spacing_px=6.0),
    )
    dense = render_pen_shading_from_analysis(
        analysis,
        PenShadingConfig(style="dense_crosshatch", include_outline=False, hatch_spacing_px=6.0),
    )
    assert len(cross.polylines) >= len(parallel.polylines)
    assert len(dense.polylines) >= len(cross.polylines)


def test_scratchboard_records_inverse_tone_behavior(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    result = render_pen_shading_from_analysis(
        _analysis(path),
        PenShadingConfig(style="scratchboard", hatch_spacing_px=6.0),
    )
    assert result.metadata["inverse_tone_shading"] is True


def test_texture_presets_do_not_claim_semantic_recognition(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    analysis = _analysis(path)
    for style in ("fur_texture", "hair_texture"):
        result = render_pen_shading_from_analysis(
            analysis,
            PenShadingConfig(style=style, hatch_spacing_px=7.0),
        )
        assert result.metadata["semantic_recognition"] is False
        assert result.metadata["texture_is_semantic"] is False


def test_outline_can_be_disabled(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    result = render_pen_shading_from_analysis(
        _analysis(path),
        PenShadingConfig(style="parallel_hatch", include_outline=False, hatch_spacing_px=6.0),
    )
    assert result.metadata["include_outline"] is False


def test_invalid_shading_style_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported pen-shading style"):
        PenShadingConfig(style="watercolor").validate()  # type: ignore[arg-type]


def test_geometry_limits_enforced(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    with pytest.raises(ValueError, match="geometry limits"):
        render_pen_shading_from_analysis(
            _analysis(path),
            PenShadingConfig(style="dense_crosshatch", hatch_spacing_px=4.0, max_output_strokes=1),
        )

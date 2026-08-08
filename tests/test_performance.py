from __future__ import annotations

from pathlib import Path
import time

from PIL import Image, ImageDraw

from printrbot_penplotter.auto_optimize import AutoOptimizeConfig, optimize_image
from printrbot_penplotter.image_preprocess import ImagePreprocessConfig
from printrbot_penplotter.image_understanding import ImageUnderstandingConfig, analyze_image
from printrbot_penplotter.line_art import LineArtConfig, render_line_art_from_analysis
from printrbot_penplotter.pen_shading import PenShadingConfig, render_pen_shading_from_analysis


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


def test_refined_pen_sketch_small_fixture_stays_interactive(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    analysis = _analysis(path)
    started = time.perf_counter()
    result = render_line_art_from_analysis(analysis, LineArtConfig(style="refined_pen_sketch"))
    elapsed = time.perf_counter() - started
    assert result.polylines
    assert elapsed < 5.0, f"refined_pen_sketch took {elapsed:.3f}s on the small fixture"


def test_crosshatch_small_fixture_stays_interactive(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    analysis = _analysis(path)
    started = time.perf_counter()
    result = render_pen_shading_from_analysis(
        analysis,
        PenShadingConfig(style="crosshatch", hatch_spacing_px=7.0),
    )
    elapsed = time.perf_counter() - started
    assert result.polylines
    assert elapsed < 5.0, f"crosshatch took {elapsed:.3f}s on the small fixture"


def test_best_auto_small_fixture_has_bounded_runtime(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"
    _fixture(path)
    started = time.perf_counter()
    result = optimize_image(path, AutoOptimizeConfig(quality="best", max_candidates=8, seed=7))
    elapsed = time.perf_counter() - started
    assert result.polylines
    assert elapsed < 12.0, f"best auto optimization took {elapsed:.3f}s on the small fixture"

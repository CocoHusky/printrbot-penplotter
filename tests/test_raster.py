from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from printrbot_penplotter.cli import main as cli_main
from printrbot_penplotter.models import PenConfig
from printrbot_penplotter.pipeline import render_handwriting_job, render_image_job
from printrbot_penplotter.raster import RasterTraceConfig, editable_trace_svg, trace_raster


def _save_line(path: Path, *, dark_on_light: bool = True) -> None:
    background = 255 if dark_on_light else 0
    ink = 0 if dark_on_light else 255
    image = Image.new("L", (80, 40), background)
    draw = ImageDraw.Draw(image)
    draw.line((10, 20, 70, 20), fill=ink, width=5)
    image.save(path)


def _save_rectangle(path: Path) -> None:
    image = Image.new("L", (64, 48), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 10, 51, 37), fill=0)
    image.save(path)


def test_centerline_trace_reduces_thick_stroke_to_single_path(tmp_path: Path) -> None:
    source = tmp_path / "line.png"
    _save_line(source)

    result = trace_raster(
        source,
        RasterTraceConfig(mode="centerline", min_component_px=2, simplify_px=0.8),
    )

    assert result.metadata["trace_mode"] == "centerline"
    assert result.metadata["threshold_mode"] == "otsu"
    assert result.metadata["skeleton_converged"] is True
    assert len(result.polylines) == 1
    assert len(result.polylines[0]) == 2
    xs = [point[0] for point in result.polylines[0]]
    assert max(xs) - min(xs) > 40


def test_contour_trace_produces_closed_outline(tmp_path: Path) -> None:
    source = tmp_path / "rectangle.png"
    _save_rectangle(source)

    result = trace_raster(
        source,
        RasterTraceConfig(mode="contour", min_component_px=2, simplify_px=0.8),
    )

    assert len(result.polylines) == 1
    outline = result.polylines[0]
    assert outline[0] == outline[-1]
    assert len(outline) == 5


def test_small_components_are_removed_and_reported(tmp_path: Path) -> None:
    source = tmp_path / "speckled.png"
    image = Image.new("L", (40, 30), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 10, 28, 14), fill=0)
    image.putpixel((35, 3), 0)
    image.save(source)

    result = trace_raster(
        source,
        RasterTraceConfig(mode="centerline", min_component_px=4, simplify_px=0.5),
    )

    assert result.metadata["components_kept"] == 1
    assert result.metadata["components_removed"] == 1
    assert result.metadata["pixels_removed"] == 1


def test_invert_traces_light_ink_on_dark_background(tmp_path: Path) -> None:
    source = tmp_path / "inverse.png"
    _save_line(source, dark_on_light=False)

    result = trace_raster(
        source,
        RasterTraceConfig(
            mode="centerline",
            invert=True,
            min_component_px=2,
            simplify_px=0.8,
        ),
    )

    assert result.metadata["invert"] is True
    assert result.polylines


def test_raster_is_downsampled_before_tracing(tmp_path: Path) -> None:
    source = tmp_path / "large.png"
    image = Image.new("L", (400, 200), 255)
    draw = ImageDraw.Draw(image)
    draw.line((20, 100, 380, 100), fill=0, width=12)
    image.save(source)

    result = trace_raster(
        source,
        RasterTraceConfig(
            mode="centerline",
            max_dimension_px=100,
            max_processed_pixels=20_000,
            min_component_px=2,
        ),
    )

    assert result.metadata["original_width_px"] == 400
    assert result.metadata["processed_width_px"] == 100
    assert result.metadata["processed_height_px"] == 50
    assert result.metadata["resize_scale"] == pytest.approx(0.25)


def test_blank_image_fails_before_geometry_generation(tmp_path: Path) -> None:
    source = tmp_path / "blank.png"
    Image.new("L", (32, 32), 255).save(source)

    with pytest.raises(ValueError, match="no foreground"):
        trace_raster(source, RasterTraceConfig(min_component_px=1))


def test_image_pipeline_uses_shared_preview_and_gcode_path(tmp_path: Path) -> None:
    source = tmp_path / "shape.png"
    _save_rectangle(source)

    job = render_image_job(
        source,
        trace=RasterTraceConfig(mode="contour", min_component_px=2, simplify_px=1.0),
        pen=PenConfig(air_plot=True),
    )

    assert job.metadata["input_type"] == "image"
    assert job.metadata["trace_mode"] == "contour"
    assert job.metadata["air_plot"] is True
    assert job.polylines
    assert "<svg" in job.preview_svg
    assert "; mode: AIR PLOT" in job.gcode


def test_handwriting_pipeline_centerlines_without_recognition(tmp_path: Path) -> None:
    source = tmp_path / "handwriting.png"
    _save_line(source)

    job = render_handwriting_job(
        source,
        trace=RasterTraceConfig(mode="centerline", min_component_px=2, simplify_px=0.8),
        pen=PenConfig(air_plot=True),
    )

    assert job.metadata["input_type"] == "handwriting"
    assert job.metadata["trace_mode"] == "centerline"
    assert job.metadata["handwriting_recognition"] is False


def test_handwriting_rejects_contour_mode(tmp_path: Path) -> None:
    source = tmp_path / "handwriting.png"
    _save_line(source)

    with pytest.raises(ValueError, match="centerline"):
        render_handwriting_job(source, trace=RasterTraceConfig(mode="contour"))


def test_editable_trace_svg_contains_only_trace_geometry(tmp_path: Path) -> None:
    source = tmp_path / "line.png"
    _save_line(source)
    result = trace_raster(
        source,
        RasterTraceConfig(mode="centerline", min_component_px=2, simplify_px=0.8),
    )

    svg = editable_trace_svg(result.polylines)

    assert svg.startswith("<svg")
    assert "<path" in svg
    assert "stroke=\"black\"" in svg


def test_image_cli_writes_job_preview_and_editable_trace(tmp_path: Path) -> None:
    source = tmp_path / "shape.png"
    _save_rectangle(source)
    gcode = tmp_path / "image.gcode"
    preview = tmp_path / "image.svg"
    trace_svg = tmp_path / "trace.svg"

    code = cli_main(
        [
            "image",
            str(source),
            "--trace-mode",
            "contour",
            "--min-component",
            "2",
            "--air-plot",
            "--output",
            str(gcode),
            "--preview",
            str(preview),
            "--trace-svg",
            str(trace_svg),
        ]
    )

    assert code == 0
    assert gcode.stat().st_size > 0
    assert preview.stat().st_size > 0
    assert trace_svg.stat().st_size > 0

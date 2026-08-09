import io
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from printrbot_penplotter.studio_server import app

client = TestClient(app)


def _png() -> bytes:
    image = Image.new("L", (48, 36), 245)
    draw = ImageDraw.Draw(image)
    draw.ellipse((5, 4, 43, 32), fill=170, outline=25, width=2)
    draw.ellipse((14, 12, 18, 16), fill=10)
    draw.ellipse((30, 12, 34, 16), fill=10)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_studio2_page_exposes_advanced_controls_pipeline_locks_and_sizing() -> None:
    response = client.get("/studio2")
    assert response.status_code == 200
    text = response.text
    assert "Printrbot Studio 2.0" in text
    assert "Advanced image &amp; style controls" in text or "Advanced image & style controls" in text
    assert "Threshold method" in text
    assert "Remove components smaller than" in text
    assert "Edge method" in text
    assert "Tonal bands" in text
    assert "Grayscale source" in text
    assert "Auto chooses after analysis" in text
    assert "lineStyles" in text and "shadingStyles" in text
    assert "Home before plot" in text
    assert "Max artistic strokes" in text
    assert "Bypass soft artistic limit" in text
    assert "Final drawing size" in text
    assert "Fit inside box" in text
    assert "Force exact width" in text
    assert "Final scale (%)" in text
    assert "Save SVG" in text and "Save G-code" in text
    assert "Skeleton iterations" in text
    assert "Variation seed" in text
    assert "Angle offset (degrees)" in text
    assert "Density scale" in text
    assert "Outline join distance (px)" in text
    assert "Pen lift height (mm)" in text
    assert 'name="z_down_mm"' not in text
    assert "Max plotted lines (longest kept)" in text
    assert "Limits still apply to the selected recipe." in text


def test_studio2_line_art_render_has_safe_home_envelope_and_stage_previews() -> None:
    response = client.post(
        "/api/studio2/render",
        files={"file": ("fixture.png", _png(), "image/png")},
        data={
            "mode": "line_art",
            "style": "clean_outline",
            "quality": "quick",
            "detail": "medium",
            "background_mode": "suppress",
            "pen_tip_mm": "0.5",
            "z_up_mm": "2.5",
            "z_down_mm": "0.15",
            "plot_stroke_limit": "2",
            "air_plot": "false",
            "home_before_plot": "true",
            "threshold_mode": "manual",
            "threshold_value": "190",
            "min_component_px": "4",
            "contrast": "1.2",
            "black_point": "5",
            "white_point": "250",
            "edge_method": "sobel",
            "edge_low": "0.08",
            "edge_high": "0.20",
            "size_mode": "fit_box",
            "target_width_mm": "80",
            "target_height_mm": "60",
            "keep_aspect": "true",
            "final_scale_percent": "100",
            "clamp_to_bed": "true",
            "max_skeleton_iterations": "64",
            "style_edge_threshold": "0.35",
            "style_strong_edge_threshold": "0.65",
            "style_tone_threshold": "120",
            "style_dilation_passes": "2",
            "style_simplify_tolerance_px": "0.8",
            "style_smooth_passes": "1",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["studio_schema"] == "printrbot-studio2/v3"
    assert body["metadata"]["home_before_plot"] is True
    assert body["metadata"]["z_up_mm"] == 2.5
    assert body["metadata"]["z_down_mm"] == 0.15
    assert body["metadata"]["plot_stroke_limit"] == 2
    assert body["metadata"]["estimated_print_time_seconds"] > 0
    assert body["metadata"]["estimated_print_time"]
    timings = body["metadata"]["studio_stage_seconds"]
    assert {"analysis_and_threshold", "style_vectorization", "placement_and_physical_filter", "svg_and_gcode", "final_size_and_export"} <= set(timings)
    assert body["metadata"]["studio_slowest_stage"] in timings
    assert body["metadata"]["studio_working_max_dimension_px"] == 320
    assert body["metadata"]["effective_pipeline"] == "line_art"
    assert body["metadata"]["effective_style"] == "clean_outline"
    assert body["metadata"]["style_edge_threshold"] == 0.35
    assert body["metadata"]["style_tone_threshold"] == 120
    assert body["metadata"]["style_dilation_passes"] == 2
    assert body["metadata"]["style_simplify_tolerance_px"] == 0.8
    assert body["metadata"]["style_smooth_passes"] == 1
    assert body["metadata"]["threshold_mode"] == "manual"
    assert body["metadata"]["studio_component_min_px"] == 4
    assert body["metadata"]["artistic_stroke_limit_effective"] == 20_000
    assert body["metadata"]["artistic_limit_bypassed"] is False
    assert body["metadata"]["size_mode"] == "fit_box"
    assert body["metadata"]["final_width_mm"] <= 80.0001
    assert body["metadata"]["final_height_mm"] <= 60.0001
    assert body["stages"]["source"].startswith("data:image/png;base64,")
    assert body["stages"]["corrected"].startswith("data:image/png;base64,")
    assert body["stages"]["mask"].startswith("data:image/png;base64,")
    assert body["stages"]["edges"].startswith("data:image/png;base64,")
    assert "G28" in body["gcode"]
    assert "G28 X Y" in body["gcode"]
    assert "G0 Z2.500" in body["gcode"]
    assert "G0 Z0.150" in body["gcode"]
    assert body["polylines"]


def test_studio2_skips_unused_edge_stage_for_fill_style() -> None:
    response = client.post(
        "/api/studio2/render",
        files={"file": ("fixture.png", _png(), "image/png")},
        data={
            "mode": "shading",
            "style": "stipple",
            "quality": "quick",
            "detail": "low",
            "include_outline": "false",
            "plot_stroke_limit": "100",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["studio_edge_analysis_skipped"] is True
    assert body["metadata"]["edge_analysis_skipped"] is True
    assert body["stages"]["edges"] == ""


def test_studio2_interactive_stages_run_independently() -> None:
    for stage, expected in (("source", "corrected"), ("threshold", "mask"), ("edges", "edges")):
        response = client.post(
            "/api/studio2/stage",
            files={"file": ("fixture.png", _png(), "image/png")},
            data={"stage": stage, "quality": "quick", "detail": "low"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["metadata"]["stage"] == stage
        assert body["stages"][expected].startswith("data:image/png;base64,")


def test_studio2_interactive_style_honors_fast_cleanup_and_plot_line_cap() -> None:
    response = client.post(
        "/api/studio2/stage",
        files={"file": ("fixture.png", _png(), "image/png")},
        data={
            "stage": "style",
            "mode": "line_art",
            "style": "clean_outline",
            "quality": "quick",
            "detail": "low",
            "max_skeleton_iterations": "32",
            "plot_stroke_limit": "3",
            "style_simplify_tolerance_px": "-1",
            "style_smooth_passes": "-1",
            "style_join_distance_px": "-1",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["stage"] == "style"
    assert body["metadata"]["plot_stroke_limit"] == 3
    assert body["metadata"]["artistic_strokes"] <= 3
    assert body["metadata"]["plot_strokes_dropped_before_preview"] >= 0
    assert body["preview_svg"].startswith("<svg")


def test_studio2_topographic_stage_uses_grayscale_directly() -> None:
    response = client.post(
        "/api/studio2/stage",
        files={"file": ("fixture.png", _png(), "image/png")},
        data={
            "stage": "style",
            "mode": "line_art",
            "style": "topographic",
            "quality": "quick",
            "detail": "high",
            "tonal_bands": "40,80,120,160,200",
            "max_skeleton_iterations": "32",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["topographic_input"] == "grayscale"
    assert body["metadata"]["threshold_analysis_skipped"] is True
    assert body["metadata"]["edge_analysis_skipped"] is True
    assert body["stages"]["edges"] == ""
    assert body["preview_svg"].startswith("<svg")


def test_studio2_force_exact_size_and_final_scale() -> None:
    response = client.post(
        "/api/studio2/render",
        files={"file": ("fixture.png", _png(), "image/png")},
        data={
            "mode": "line_art",
            "style": "clean_outline",
            "quality": "quick",
            "detail": "medium",
            "background_mode": "suppress",
            "size_mode": "force_exact",
            "target_width_mm": "50",
            "target_height_mm": "30",
            "keep_aspect": "false",
            "final_scale_percent": "80",
            "clamp_to_bed": "true",
        },
    )
    assert response.status_code == 200, response.text
    metadata = response.json()["metadata"]
    assert abs(metadata["final_width_mm"] - 40.0) < 0.05
    assert abs(metadata["final_height_mm"] - 24.0) < 0.05
    assert metadata["keep_aspect"] is False
    assert metadata["final_scale_percent"] == 80.0


def test_studio2_expert_bypass_raises_soft_artistic_limit_but_keeps_hard_guard() -> None:
    response = client.post(
        "/api/studio2/render",
        files={"file": ("fixture.png", _png(), "image/png")},
        data={
            "mode": "line_art",
            "style": "detailed_outline",
            "quality": "quick",
            "detail": "medium",
            "background_mode": "suppress",
            "bypass_artistic_limit": "true",
            "artistic_stroke_limit": "20000",
            "artistic_point_limit": "2000000",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["artistic_limit_bypassed"] is True
    assert body["metadata"]["artistic_stroke_limit_effective"] == 200_000
    assert body["metadata"]["artistic_point_limit_effective"] == 20_000_000
    assert body["metadata"]["artistic_hard_stroke_guard"] == 200_000


def test_studio2_rejects_invalid_pipeline_style_combination() -> None:
    response = client.post(
        "/api/studio2/render",
        files={"file": ("fixture.png", _png(), "image/png")},
        data={
            "mode": "line_art",
            "style": "crosshatch",
            "quality": "quick",
            "detail": "medium",
            "background_mode": "suppress",
        },
    )
    assert response.status_code == 400
    assert "not valid for the Line art pipeline" in response.json()["detail"]


def test_studio2_auto_ignores_manual_style_and_reports_effective_choice() -> None:
    response = client.post(
        "/api/studio2/render",
        files={"file": ("fixture.png", _png(), "image/png")},
        data={
            "mode": "auto",
            "style": "fur_texture",
            "quality": "balanced",
            "detail": "medium",
            "background_mode": "suppress",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["requested_style"] is None
    assert body["metadata"]["effective_style"]
    assert body["metadata"]["effective_pipeline"] in ("line_art", "shading")
    assert body["metadata"]["requested_quality"] == "balanced"
    assert body["metadata"]["effective_quality"] == "quick"
    assert body["metadata"]["auto_interactive_preview"] is True

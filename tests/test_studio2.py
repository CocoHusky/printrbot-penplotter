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


def test_studio2_page_exposes_advanced_controls_and_pipeline_locks() -> None:
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
            "air_plot": "true",
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
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["studio_schema"] == "printrbot-studio2/v2"
    assert body["metadata"]["home_before_plot"] is True
    assert body["metadata"]["studio_working_max_dimension_px"] == 480
    assert body["metadata"]["effective_pipeline"] == "line_art"
    assert body["metadata"]["effective_style"] == "clean_outline"
    assert body["metadata"]["threshold_mode"] == "manual"
    assert body["metadata"]["studio_component_min_px"] == 4
    assert body["metadata"]["artistic_stroke_limit_effective"] == 20_000
    assert body["metadata"]["artistic_limit_bypassed"] is False
    assert body["stages"]["source"].startswith("data:image/png;base64,")
    assert body["stages"]["corrected"].startswith("data:image/png;base64,")
    assert body["stages"]["mask"].startswith("data:image/png;base64,")
    assert body["stages"]["edges"].startswith("data:image/png;base64,")
    assert "G28" in body["gcode"]
    assert "G28 X Y" in body["gcode"]
    assert body["polylines"]


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
            "quality": "quick",
            "detail": "medium",
            "background_mode": "suppress",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["requested_style"] is None
    assert body["metadata"]["effective_style"]
    assert body["metadata"]["effective_pipeline"] in ("line_art", "shading")

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from printrbot_penplotter.studio_server import app


client = TestClient(app)


def _handwriting_png() -> bytes:
    image = Image.new("L", (120, 70), 255)
    draw = ImageDraw.Draw(image)
    draw.line([(12, 52), (28, 18), (38, 52), (49, 20), (58, 52)], fill=0, width=7)
    draw.line([(70, 45), (102, 45)], fill=0, width=6)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_raster_studio_page_is_available() -> None:
    response = client.get("/raster")
    assert response.status_code == 200
    assert "Image & Handwriting Studio" in response.text
    assert "Editable raw trace" in response.text
    assert "Home all axes before plot" in response.text


def test_trace_endpoint_returns_four_stage_workflow() -> None:
    response = client.post(
        "/api/raster/trace",
        files={"file": ("note.png", _handwriting_png(), "image/png")},
        data={
            "mode": "centerline",
            "threshold": "",
            "invert": "false",
            "blur_radius_px": "0",
            "min_component_px": "4",
            "simplify_px": "0.5",
            "air_plot": "true",
            "home_before_plot": "true",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["original_data_uri"].startswith("data:image/png;base64,")
    assert data["mask_data_uri"].startswith("data:image/png;base64,")
    assert "<svg" in data["raw_trace_svg"]
    assert "<svg" in data["final_preview_svg"]
    assert "; mode: AIR PLOT" in data["gcode"]
    assert "G28 ; home all configured axes" in data["gcode"]
    assert "pen down" not in data["gcode"]
    assert data["raw_polylines"]
    assert len(data["job_sidecar"]["source"]["sha256"]) == 64
    assert data["metadata"]["recognition_performed"] is False
    assert data["metadata"]["home_before_plot"] is True


def test_finalize_uses_edited_geometry_for_preview_and_gcode() -> None:
    request = {
        "polylines": [
            [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]],
            [[20.0, 20.0], [30.0, 20.0]],
        ],
        "air_plot": True,
        "home_before_plot": True,
    }
    response = client.post("/api/raster/finalize", json=request)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["metadata"]["strokes"] == 2
    assert len(data["machine_polylines"]) == 2
    assert "<svg" in data["final_preview_svg"]
    assert "; mode: AIR PLOT" in data["gcode"]
    assert "G28 ; home all configured axes" in data["gcode"]
    assert "pen down" not in data["gcode"]
    assert data["metadata"]["home_before_plot"] is True


def test_finalize_can_explicitly_leave_homing_out_for_non_bridge_workflows() -> None:
    response = client.post(
        "/api/raster/finalize",
        json={
            "polylines": [[[0.0, 0.0], [10.0, 10.0]]],
            "air_plot": True,
            "home_before_plot": False,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "G28" not in data["gcode"]
    assert data["metadata"]["home_before_plot"] is False


def test_finalize_rejects_empty_geometry() -> None:
    response = client.post(
        "/api/raster/finalize",
        json={"polylines": [], "air_plot": True},
    )
    assert response.status_code == 400

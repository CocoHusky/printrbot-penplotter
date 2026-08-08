import io
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from printrbot_penplotter.studio_server import app

client = TestClient(app)


def _png() -> bytes:
    image = Image.new("L", (48, 36), 245)
    draw = ImageDraw.Draw(image)
    draw.ellipse((5,4,43,32), fill=170, outline=25, width=2)
    draw.ellipse((14,12,18,16), fill=10)
    draw.ellipse((30,12,34,16), fill=10)
    out = io.BytesIO(); image.save(out, format="PNG"); return out.getvalue()


def test_studio2_page() -> None:
    response = client.get("/studio2")
    assert response.status_code == 200
    assert "Printrbot Studio 2.0" in response.text
    assert "Home before plot" in response.text


def test_studio2_line_art_render_has_safe_home_envelope() -> None:
    response = client.post(
        "/api/studio2/render",
        files={"file": ("fixture.png", _png(), "image/png")},
        data={
            "mode": "line_art", "style": "clean_outline", "quality": "quick",
            "detail": "medium", "background_mode": "suppress", "pen_tip_mm": "0.5",
            "air_plot": "true", "home_before_plot": "true",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metadata"]["studio_schema"] == "printrbot-studio2/v1"
    assert body["metadata"]["home_before_plot"] is True
    assert "G28" in body["gcode"]
    assert "G28 X Y" in body["gcode"]
    assert body["polylines"]

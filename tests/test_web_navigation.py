from fastapi.testclient import TestClient

from printrbot_penplotter.studio_server import app


client = TestClient(app)


def test_unified_tool_navigation_is_present_on_each_workspace() -> None:
    for path, active in (("/", "Write"), ("/studio2", "Art")):
        response = client.get(path)
        assert response.status_code == 200
        text = response.text
        assert 'aria-label="Printrbot tools"' in text
        assert text.count('class="app-tabs"') == 1
        assert "Image trace" not in text
        assert 'href="/"' in text
        assert 'href="/studio2"' in text
        assert text.count('href="/') == 2
        assert active in text
        assert 'id="printrbot-lab-theme"' in text


def test_notes_workspace_has_simple_lettering_choices() -> None:
    text = client.get("/").text
    assert "Write notes for the plotter" in text
    assert "Robot centerline" in text
    assert "Typed centerline" in text
    assert "Handwritten centerline" in text
    assert 'id="preset"' in text
    assert 'class="lettering-choices"' in text
    assert "Handwriting adjustments" in text
    assert "Every mode draws centerlines only" in text
    assert 'id="typedFontControls"' in text
    assert "api/font-library" in text
    assert "Font size (pt)" in text
    assert "Generate 10 mm air calibration" in text
    assert "printrbot-note-draft" in text
    assert "Save note locally" in text
    assert "Rendering your note…" in text
    assert "STEP 1" in text and "STEP 2" in text and "STEP 3" in text
    assert 'id="handwritingControls"' in text
    assert 'id="homeBeforePlot"' in text
    assert "re-home X/Y at the end" in text


def test_font_library_endpoint_returns_ui_safe_installed_fonts() -> None:
    response = client.get("/api/font-library")
    assert response.status_code == 200
    fonts = response.json()["fonts"]
    assert fonts
    assert all(set(font) == {"name", "description"} for font in fonts)
    assert all("/" not in font["name"] for font in fonts)


def test_notes_api_rejects_legacy_outline_text() -> None:
    response = client.post("/api/render", json={"text": "Centerline only", "engine": "outline"})
    assert response.status_code == 422

from fastapi.testclient import TestClient

from printrbot_penplotter.studio_server import app


client = TestClient(app)


def test_unified_tool_navigation_is_present_on_each_workspace() -> None:
    for path, active in (("/", "Test"), ("/raster", "Test"), ("/studio2", "Art")):
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
    assert "Typed font" in text
    assert "Robot / plotter" in text
    assert "Handwritten" in text
    assert 'class="lettering-choices"' in text
    assert "Handwriting adjustments" in text
    assert "Choose one simple lettering mode" in text
    assert "printrbot-note-draft" in text
    assert "Save note locally" in text
    assert "Rendering your note…" in text
    assert "STEP 1" in text and "STEP 2" in text and "STEP 3" in text
    assert 'id="handwritingControls"' in text

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


def test_notes_workspace_has_local_draft_and_human_preset_controls() -> None:
    text = client.get("/").text
    assert "Write notes for the plotter" in text
    assert "Natural notes" in text
    assert "Cursive notes" in text
    assert "Font and authored-glyph controls are disabled" in text
    assert "printrbot-note-draft" in text
    assert "Save note locally" in text
    assert "Rendering your note…" in text
    assert "STEP 1" in text and "STEP 2" in text and "STEP 3" in text
    assert 'id="neuralControls"' in text

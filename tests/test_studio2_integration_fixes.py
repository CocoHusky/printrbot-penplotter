from fastapi.testclient import TestClient

from printrbot_penplotter import line_art, studio2
from printrbot_penplotter import __version__
from printrbot_penplotter.geometry import flip_y_in_page, place_on_page
from printrbot_penplotter.models import LayoutConfig, MachineConfig, PageConfig
from printrbot_penplotter.studio_server import app
from printrbot_penplotter.vector_cleanup import VectorCleanupConfig

client = TestClient(app)


def test_studio2_has_always_visible_generate_and_save_actions() -> None:
    response = client.get("/studio2")
    assert response.status_code == 200
    text = response.text
    assert 'id="studio2FloatingActions"' in text
    assert 'id="floatingGenerate"' in text
    assert 'id="floatingSaveSvg"' in text
    assert 'id="floatingSaveGcode"' in text
    assert "showSaveFilePicker" in text
    assert 'id="rasterPreview"' in text
    assert "Quick raster preview is ready" in text
    assert "let rendering=false" in text
    assert "let renderGeneration=0" in text
    assert "function clearGeneratedResult" in text
    assert "Ready for another image." in text
    assert "form.addEventListener('submit'" not in text
    assert "fd.set(n,'-1')" in text
    assert "window.__studioAbortController" in text
    assert "window.__studioStageAbort" in text
    assert "if(stop)stop.disabled=false" in text
    assert "setupControlSections" in text
    assert "className='control-section'" in text
    assert 'class="stage-tabs"' in text
    assert 'data-stage="gray"' in text
    assert "Not required for this style." in text
    assert "studio-step-shell" in text
    assert "process-tab" in text
    assert "before-after" in text
    assert "Source & grayscale" in text
    assert "Black & white" in text
    assert "Edge extraction" in text
    assert "Vectorization" in text
    assert "Machine & export" in text
    assert "stageData" in text
    assert "stageStale" in text
    assert "Current style path" in text
    assert "Art style goal" in text
    assert "This choice stays visible while you process the image." in text
    assert "4. Vectorization" in text
    assert "Dependent stages remain cached" in text
    assert "Standard reference image" in text
    assert "loadStandardExample" in text
    assert "studio-reference.png" in text
    assert "needsThreshold" in text
    assert "setTimeout(()=>" in text
    assert "studio-value-slider" in text
    assert "normalized 0–1 weights" in text
    assert 'id="studioVersion"' in text
    assert f"v{__version__}" in text


def test_studio2_version_endpoint_identifies_running_build() -> None:
    response = client.get("/api/studio2/version")
    assert response.status_code == 200
    body = response.json()
    assert body["software"] == "printrbot-penplotter"
    assert body["version"] == __version__
    assert body["commit"]


def test_studio2_image_geometry_is_mirrored_into_cartesian_y_before_placement() -> None:
    # Image coordinates are Y-down: the first point is visually above the second.
    image_line = [[(0.0, 0.0), (0.0, 10.0)]]
    placed = studio2.place_on_page(
        image_line,
        PageConfig(),
        LayoutConfig(fit_mode="fit"),
        MachineConfig(),
    )
    # Machine coordinates are Y-up, so the visually upper source point must have
    # the larger machine Y. preview_svg flips machine Y back for browser display.
    assert placed[0][0][1] > placed[0][1][1]


def test_studio_stage_preview_mirrors_placed_image_geometry_once() -> None:
    page = PageConfig()
    placed = place_on_page(
        [[(0.0, 0.0), (0.0, 10.0)]],
        page,
        LayoutConfig(fit_mode="fit"),
        MachineConfig(),
    )
    mirrored = flip_y_in_page(placed, page)
    # The stage preview receives image-space geometry from the legacy renderer;
    # after the shared conversion, its visually upper source point is machine-up.
    assert mirrored[0][0][1] > mirrored[0][1][1]


def test_studio_cleanup_no_longer_stops_at_legacy_20k_soft_limit() -> None:
    lines = [[(float(index), 0.0), (float(index), 1.0)] for index in range(20_001)]
    result = line_art.cleanup_polylines_fast(
        lines,
        VectorCleanupConfig(max_strokes=20_000, max_points=2_000_000),
    )
    assert len(result.polylines) == 20_001

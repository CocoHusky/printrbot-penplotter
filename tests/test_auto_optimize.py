from pathlib import Path
from PIL import Image, ImageDraw
import pytest
from printrbot_penplotter.auto_optimize import AutoOptimizeConfig, optimize_image


def _fixture(path: Path) -> None:
    image = Image.new("L", (96, 72), 245)
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 8, 86, 64), fill=165, outline=25, width=3)
    draw.ellipse((28, 24, 36, 32), fill=10)
    draw.ellipse((60, 24, 68, 32), fill=10)
    draw.polygon([(43, 38), (53, 38), (48, 48)], fill=25)
    image.save(path)


def test_auto_optimizer_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"; _fixture(path)
    cfg = AutoOptimizeConfig(quality="balanced", max_candidates=6, seed=7)
    first = optimize_image(path, cfg)
    second = optimize_image(path, cfg)
    assert first.polylines == second.polylines
    assert first.metadata == second.metadata
    assert first.selected == second.selected
    assert first.metadata["auto_optimizer_schema"] == "printrbot-auto-optimizer/v2"
    assert first.metadata["auto_evaluation_mode"] == "two_stage_heuristic_then_render_winner"
    assert first.metadata["auto_full_renders"] == 1
    assert 1 <= len(first.candidates) <= 6


def test_quick_limits_candidate_count(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"; _fixture(path)
    result = optimize_image(path, AutoOptimizeConfig(quality="quick", max_candidates=8))
    assert len(result.candidates) <= 4
    assert result.polylines


def test_selected_candidate_is_min_score(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"; _fixture(path)
    result = optimize_image(path, AutoOptimizeConfig(quality="best", max_candidates=8))
    assert result.selected.score == min(candidate.score for candidate in result.candidates)


def test_only_selected_candidate_has_rendered_geometry_metadata(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"; _fixture(path)
    result = optimize_image(path, AutoOptimizeConfig(quality="best", max_candidates=8))
    rendered = [c for c in result.candidates if not c.metadata.get("geometry_estimated", False)]
    assert rendered == [result.selected]
    assert result.metadata["auto_full_renders"] == 1


def test_auto_optimizer_honors_output_limits(tmp_path: Path) -> None:
    path = tmp_path / "fixture.png"; _fixture(path)
    with pytest.raises(ValueError, match="no valid drawing candidates"):
        optimize_image(
            path,
            AutoOptimizeConfig(quality="quick", max_output_strokes=1, max_output_points=2),
        )


def test_auto_optimizer_validates_skeleton_budget() -> None:
    with pytest.raises(ValueError, match="max_skeleton_iterations"):
        AutoOptimizeConfig(max_skeleton_iterations=0).validate()

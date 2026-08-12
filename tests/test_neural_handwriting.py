from __future__ import annotations

from pathlib import Path

import pytest

from printrbot_penplotter.models import StyleConfig
from printrbot_penplotter.neural_handwriting import (
    NeuralWritingConfig,
    generate_neural_trajectories,
)
from printrbot_penplotter.pipeline import render_text_job


def _worker(path: Path) -> None:
    path.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "assert request['text'] == 'hello'\n"
        "json.dump({'backend': 'test-neural', 'strokes': [[[0, 0], [1, 1], [2, 0]]]}, sys.stdout)\n",
        encoding="utf-8",
    )


def _image_y_worker(path: Path) -> None:
    path.write_text(
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "json.dump({'backend': 'image-y-test', 'coordinate_system': 'image-y-down', "
        "'strokes': [[[0, 2], [1, 3], [2, 2]]]}, sys.stdout)\n",
        encoding="utf-8",
    )


def test_neural_worker_protocol_returns_shared_polylines(tmp_path: Path) -> None:
    worker = tmp_path / "worker.py"
    _worker(worker)
    strokes, metadata = generate_neural_trajectories(
        "hello",
        config=NeuralWritingConfig(command=str(worker)),
    )
    assert strokes == [[(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]]
    assert metadata["writing_backend"] == "test-neural"


def test_neural_worker_normalizes_image_y_down_coordinates(tmp_path: Path) -> None:
    worker = tmp_path / "image-y-worker.py"
    _image_y_worker(worker)
    strokes, metadata = generate_neural_trajectories(
        "hello",
        config=NeuralWritingConfig(command=str(worker)),
    )
    assert strokes == [[(0.0, -2.0), (1.0, -3.0), (2.0, -2.0)]]
    assert metadata["neural_coordinate_system"] == "image-y-down"


def test_neural_worker_normalizes_latin_accents(tmp_path: Path) -> None:
    worker = tmp_path / "accent-worker.py"
    worker.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "assert request['text'] == 'Cafe manana'\n"
        "json.dump({'strokes': [[[0, 0], [1, 1]]]}, sys.stdout)\n",
        encoding="utf-8",
    )
    strokes, _ = generate_neural_trajectories(
        "Café mañana",
        config=NeuralWritingConfig(command=str(worker)),
    )
    assert strokes == [[(0.0, 0.0), (1.0, 1.0)]]


def test_neural_worker_normalizes_pasted_typography(tmp_path: Path) -> None:
    worker = tmp_path / "punctuation-worker.py"
    worker.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "assert request['text'] == \"You've got it - really...\"\n"
        "json.dump({'strokes': [[[0, 0], [1, 1]]]}, sys.stdout)\n",
        encoding="utf-8",
    )
    strokes, _ = generate_neural_trajectories(
        "You’ve got it — really…",
        config=NeuralWritingConfig(command=str(worker)),
    )
    assert strokes == [[(0.0, 0.0), (1.0, 1.0)]]


def test_neural_worker_warns_when_removing_unsupported_punctuation(tmp_path: Path) -> None:
    worker = tmp_path / "cleanup-worker.py"
    worker.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "assert request['text'] == 'hello world'\n"
        "json.dump({'strokes': [[[0, 0], [1, 1]]]}, sys.stdout)\n",
        encoding="utf-8",
    )
    strokes, metadata = generate_neural_trajectories(
        "hello @ world",
        config=NeuralWritingConfig(command=str(worker)),
    )
    assert strokes == [[(0.0, 0.0), (1.0, 1.0)]]
    assert "'@'" in metadata["neural_text_warnings"][0]


def test_neural_worker_receives_seed_and_applies_slant(tmp_path: Path) -> None:
    worker = tmp_path / "parameter-worker.py"
    worker.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "assert request['seed'] == 23\n"
        "assert request['slant_deg'] == 10\n"
        "json.dump({'coordinate_system': 'image-y-down', 'strokes': [[[0, 0], [1, -2]]]}, sys.stdout)\n",
        encoding="utf-8",
    )
    strokes, metadata = generate_neural_trajectories(
        "hello",
        config=NeuralWritingConfig(command=str(worker), seed=23, slant_deg=10),
    )
    assert strokes[0][1][0] > 1.3
    assert metadata["neural_seed"] == 23
    assert metadata["neural_slant_deg"] == 10


def test_neural_backend_flows_through_layout_and_gcode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    worker = tmp_path / "worker.py"
    _worker(worker)
    monkeypatch.setenv("PRINTRBOT_HANDWRITING_WORKER", str(worker))
    job = render_text_job(
        "hello",
        style=StyleConfig.for_preset("human", writing_backend="neural"),
    )
    assert job.metadata["writing_backend"] == "test-neural"
    assert job.polylines
    assert "G1" in job.gcode


def test_neural_backend_requires_explicit_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRINTRBOT_HANDWRITING_WORKER", raising=False)
    with pytest.raises(RuntimeError, match="Neural handwriting is not installed"):
        render_text_job("hello", style=StyleConfig.for_preset("human", writing_backend="neural"))

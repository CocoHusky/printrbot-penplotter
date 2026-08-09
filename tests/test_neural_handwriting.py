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


def test_neural_worker_protocol_returns_shared_polylines(tmp_path: Path) -> None:
    worker = tmp_path / "worker.py"
    _worker(worker)
    strokes, metadata = generate_neural_trajectories(
        "hello",
        config=NeuralWritingConfig(command=str(worker)),
    )
    assert strokes == [[(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]]
    assert metadata["writing_backend"] == "test-neural"


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

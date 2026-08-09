"""Optional online-handwriting trajectory backend.

The neural model is deliberately external because the original Graves
checkpoint has no declared redistribution license and requires a large ML
runtime. Printrbot owns the stable worker protocol and all layout/G-code code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import shlex
from dataclasses import dataclass

from .models import Point, Polylines


@dataclass(frozen=True)
class NeuralWritingConfig:
    command: str | None = None
    style: int = 9
    bias: float = 0.75
    timeout_seconds: float = 90.0

    def validate(self) -> None:
        if not 0 <= self.style <= 12:
            raise ValueError("Neural style must be between 0 and 12.")
        if not 0 <= self.bias <= 1:
            raise ValueError("Neural bias must be between 0 and 1.")
        if self.timeout_seconds <= 0:
            raise ValueError("Neural timeout must be positive.")


def generate_neural_trajectories(text: str, *, config: NeuralWritingConfig) -> tuple[Polylines, dict[str, object]]:
    """Run a worker using JSON stdin/stdout and validate its stroke output."""
    config.validate()
    if not text.strip():
        raise ValueError("Text input cannot be empty.")
    command = config.command or os.environ.get("PRINTRBOT_HANDWRITING_WORKER")
    if not command:
        raise RuntimeError(
            "Neural handwriting is not installed. Set "
            "PRINTRBOT_HANDWRITING_WORKER to a compatible trajectory worker."
        )
    python = os.environ.get("PRINTRBOT_HANDWRITING_PYTHON", sys.executable)
    argv = [python, command] if command.endswith(".py") else shlex.split(command)
    worker_env = os.environ.copy()
    worker_env.setdefault("TF_USE_LEGACY_KERAS", "1")
    worker_env.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    try:
        result = subprocess.run(
            argv,
            input=json.dumps({"text": text, "style": config.style, "bias": config.bias}),
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            check=False,
            env=worker_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Neural handwriting generation timed out.") from exc
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Neural handwriting worker failed.")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Neural handwriting worker returned invalid JSON.") from exc
    strokes: Polylines = []
    for raw_stroke in payload.get("strokes", []):
        if not isinstance(raw_stroke, list) or len(raw_stroke) < 2:
            continue
        stroke: list[Point] = []
        for raw_point in raw_stroke:
            if not isinstance(raw_point, list) or len(raw_point) != 2:
                raise RuntimeError("Neural handwriting worker returned an invalid point.")
            stroke.append((float(raw_point[0]), float(raw_point[1])))
        if len(stroke) >= 2:
            strokes.append(stroke)
    if not strokes:
        raise RuntimeError("Neural handwriting worker returned no drawable strokes.")
    return strokes, {
        "writing_backend": payload.get("backend", "neural"),
        "neural_style": config.style,
        "neural_bias": config.bias,
    }

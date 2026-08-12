"""Optional online-handwriting trajectory backend.

The neural model is deliberately external because the original Graves
checkpoint has no declared redistribution license and requires a large ML
runtime. Printrbot owns the stable worker protocol and all layout/G-code code.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import shlex
import unicodedata
from dataclasses import dataclass

from .models import Point, Polylines


_NEURAL_PUNCTUATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2026": "...",
        "\u00a0": " ",
    }
)
_NEURAL_ALLOWED = set("\x00 !\"#'(),-.0123456789:;?ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


@dataclass(frozen=True)
class NeuralWritingConfig:
    command: str | None = None
    style: int = 9
    bias: float = 0.75
    seed: int = 7
    slant_deg: float = 0.0
    timeout_seconds: float = 90.0

    def validate(self) -> None:
        if not 0 <= self.style <= 12:
            raise ValueError("Neural style must be between 0 and 12.")
        if not 0 <= self.bias <= 1:
            raise ValueError("Neural bias must be between 0 and 1.")
        if not -45 <= self.slant_deg <= 45:
            raise ValueError("Neural slant must be between -45 and 45 degrees.")
        if self.timeout_seconds <= 0:
            raise ValueError("Neural timeout must be positive.")


def generate_neural_trajectories(text: str, *, config: NeuralWritingConfig) -> tuple[Polylines, dict[str, object]]:
    """Run a worker using JSON stdin/stdout and validate its stroke output."""
    config.validate()
    if not text.strip():
        raise ValueError("Text input cannot be empty.")
    # Graves was trained on a small ASCII alphabet. Normalize common pasted
    # typography first so smart quotes, dashes, and non-breaking spaces do not
    # make an otherwise valid Latin note fail.
    normalized_text = unicodedata.normalize("NFKD", text).translate(_NEURAL_PUNCTUATION)
    normalized_text = "".join(
        character for character in normalized_text if not unicodedata.combining(character)
    )
    unsupported_letters = sorted(
        {character for character in normalized_text if character not in _NEURAL_ALLOWED and character.isalpha()}
    )
    if unsupported_letters:
        raise RuntimeError(
            "Neural handwriting currently supports Latin characters and accents. "
            "For Chinese, Japanese, Korean, or other scripts, choose Typed font "
            "and select a matching Unicode/CJK typeface."
        )
    removed_characters = sorted(
        {character for character in normalized_text if character not in _NEURAL_ALLOWED and not character.isspace()}
    )
    text_warnings: list[str] = []
    if removed_characters:
        normalized_text = "".join(
            character for character in normalized_text if character in _NEURAL_ALLOWED or character.isspace()
        )
        normalized_text = "\n".join(" ".join(line.split()) for line in normalized_text.splitlines())
        shown = " ".join(repr(character) for character in removed_characters[:8])
        more = "" if len(removed_characters) <= 8 else f" (+{len(removed_characters) - 8} more)"
        text_warnings.append(f"Removed unsupported Graves punctuation: {shown}{more}.")
    if not normalized_text.strip():
        raise ValueError("Text contains no drawable Graves characters after cleanup.")
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
            input=json.dumps(
                {
                    "text": normalized_text,
                    "style": config.style,
                    "bias": config.bias,
                    "seed": config.seed,
                    "slant_deg": config.slant_deg,
                }
            ),
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
    coordinate_system = payload.get("coordinate_system", "cartesian-y-up")
    if coordinate_system not in {"cartesian-y-up", "image-y-down"}:
        raise RuntimeError(
            "Neural handwriting worker returned an unsupported coordinate system: "
            f"{coordinate_system!r}."
        )
    strokes: Polylines = []
    for raw_stroke in payload.get("strokes", []):
        if not isinstance(raw_stroke, list) or len(raw_stroke) < 2:
            continue
        stroke: list[Point] = []
        for raw_point in raw_stroke:
            if not isinstance(raw_point, list) or len(raw_point) != 2:
                raise RuntimeError("Neural handwriting worker returned an invalid point.")
            x, y = float(raw_point[0]), float(raw_point[1])
            # Keep Cartesian workers upright. Image-coordinate workers are
            # flipped exactly once here so preview SVG and G-code share one
            # machine-space orientation.
            cartesian_y = -y if coordinate_system == "image-y-down" else y
            slant = math.tan(math.radians(config.slant_deg))
            stroke.append((x + slant * cartesian_y, cartesian_y))
        if len(stroke) >= 2:
            strokes.append(stroke)
    if not strokes:
        raise RuntimeError("Neural handwriting worker returned no drawable strokes.")
    return strokes, {
        "writing_backend": payload.get("backend", "neural"),
        "neural_coordinate_system": coordinate_system,
        "neural_style": config.style,
        "neural_bias": config.bias,
        "neural_seed": config.seed,
        "neural_slant_deg": config.slant_deg,
        "neural_text_warnings": text_warnings,
    }

#!/usr/bin/env python3
"""JSON worker for the optional sjvasquez Graves checkpoint.

Run with PRINTRBOT_GRAVES_SOURCE pointing at a checkout of the reference
repository. The reference model and its ML dependencies stay outside the main
Printrbot installation.
"""

from __future__ import annotations

import json
import os
import random
import sys
import textwrap
from pathlib import Path

# The published Graves checkpoint uses TensorFlow 1-era RNNCell APIs.  Keep
# the compatibility switch in the worker itself so direct worker invocation
# behaves the same as invocation through the Studio subprocess wrapper.
os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

import numpy as np


def main() -> int:
    source = Path(os.environ.get("PRINTRBOT_GRAVES_SOURCE", "")).expanduser()
    if not source.is_dir():
        print("PRINTRBOT_GRAVES_SOURCE is not set to a model checkout.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(source))
    os.chdir(source)
    from demo import Hand  # type: ignore[import-not-found]
    from drawing import align, denoise, offsets_to_coords  # type: ignore[import-not-found]

    request = json.load(sys.stdin)
    text = str(request.get("text", ""))
    style = int(request.get("style", 9))
    bias = float(request.get("bias", 0.75))
    seed = int(request.get("seed", 7))
    font_size_mm = float(request.get("font_size_mm", 6.0))
    line_spacing = float(request.get("line_spacing", 1.0))
    wrap_width_mm = request.get("wrap_width_mm", 120.0)
    if not text.strip():
        print("text is empty", file=sys.stderr)
        return 2

    random.seed(seed)
    np.random.seed(seed)
    try:
        import tensorflow.compat.v1 as tf

        tf.set_random_seed(seed)
    except ImportError:
        pass
    hand = Hand()
    strokes: list[list[list[float]]] = []
    if wrap_width_mm is None:
        max_chars = 75
    else:
        max_chars = max(12, min(75, int(float(wrap_width_mm) / max(font_size_mm, 1.0) * 2.5)))
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        if not paragraph.strip():
            lines.append("")
        else:
            lines.extend(
                textwrap.wrap(
                    paragraph,
                    width=max_chars,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
    baseline_y = 0.0
    for line in lines:
        if not line:
            baseline_y -= font_size_mm * line_spacing * 1.5
            continue
        samples = hand._sample([line], biases=[bias], styles=[style])
        offsets = samples[0]
        # Match the reference renderer's cleanup before converting the model's
        # pen-state stream into separate Printrbot polylines. Keep the model's
        # native trajectory scale here; physical sizing belongs to Printrbot's
        # later page/layout stage.
        offsets = np.asarray(offsets, dtype=float).copy()
        coords = offsets_to_coords(offsets)
        coords = denoise(coords)
        coords[:, :2] = align(coords[:, :2])
        line_min_y = float(np.min(coords[:, 1]))
        line_max_y = float(np.max(coords[:, 1]))
        line_height = max(line_max_y - line_min_y, 1.0)
        coords[:, 1] += baseline_y - line_min_y
        baseline_y -= line_height * line_spacing * 1.35
        # The reference renderer plots these coordinates directly in a
        # Cartesian graph. The shared client will flip only when a worker
        # explicitly declares image coordinates.
        current: list[list[float]] = []
        for point, eos in zip(coords, coords[:, 2]):
            current.append([float(point[0]), float(point[1])])
            if eos >= 0.5:
                if len(current) >= 2:
                    strokes.append(current)
                current = []
        if len(current) >= 2:
            strokes.append(current)

    json.dump(
        {
            "backend": "graves-rnn",
            "coordinate_system": "cartesian-y-up",
            "seed": seed,
            "style": style,
            "bias": bias,
            "strokes": strokes,
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    for line in text.splitlines() or [text]:
        if not line:
            continue
        samples = hand._sample([line], biases=[bias], styles=[style])
        offsets = samples[0]
        # Match the reference renderer's cleanup before converting the model's
        # pen-state stream into separate Printrbot polylines.  Without this,
        # raw recurrent-model jitter is visible as doubled loops and slanted
        # baselines in the plotter preview.
        offsets = np.asarray(offsets, dtype=float).copy()
        offsets[:, :2] *= 1.5
        coords = offsets_to_coords(offsets)
        coords = denoise(coords)
        coords[:, :2] = align(coords[:, :2])
        # The Graves checkpoint emits image-style coordinates (Y grows down).
        # Declare that contract in the worker response; the shared client
        # converts it once to Printrbot's Cartesian machine coordinates.
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
            "coordinate_system": "image-y-down",
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

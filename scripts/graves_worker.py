#!/usr/bin/env python3
"""JSON worker for the optional sjvasquez Graves checkpoint.

Run with PRINTRBOT_GRAVES_SOURCE pointing at a checkout of the reference
repository. The reference model and its ML dependencies stay outside the main
Printrbot installation.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np


def main() -> int:
    source = Path(os.environ.get("PRINTRBOT_GRAVES_SOURCE", "")).expanduser()
    if not source.is_dir():
        print("PRINTRBOT_GRAVES_SOURCE is not set to a model checkout.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(source))
    os.chdir(source)
    from demo import Hand  # type: ignore[import-not-found]

    request = json.load(sys.stdin)
    text = str(request.get("text", ""))
    style = int(request.get("style", 9))
    bias = float(request.get("bias", 0.75))
    if not text.strip():
        print("text is empty", file=sys.stderr)
        return 2

    hand = Hand()
    strokes: list[list[list[float]]] = []
    for line in text.splitlines() or [text]:
        if not line:
            continue
        samples = hand._sample([line], biases=[bias], styles=[style])
        offsets = samples[0]
        coords = np.cumsum(offsets[:, :2], axis=0)
        current: list[list[float]] = []
        for point, eos in zip(coords, offsets[:, 2]):
            current.append([float(point[0]), float(-point[1])])
            if eos >= 0.5:
                if len(current) >= 2:
                    strokes.append(current)
                current = []
        if len(current) >= 2:
            strokes.append(current)

    json.dump({"backend": "graves-rnn", "strokes": strokes}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

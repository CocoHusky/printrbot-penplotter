#!/usr/bin/env python3
"""Port the reference Graves checkout to TensorFlow 2 compatibility mode."""

from __future__ import annotations

import sys
from pathlib import Path


REPLACEMENTS = {
    "tf_base_model.py": [("import tensorflow as tf", "import tensorflow.compat.v1 as tf\ntf.disable_v2_behavior()")],
    "rnn.py": [("import tensorflow as tf", "import tensorflow.compat.v1 as tf\ntf.disable_v2_behavior()")],
    "tf_utils.py": [
        ("import tensorflow as tf", "import tensorflow.compat.v1 as tf\ntf.disable_v2_behavior()"),
        ("tf.contrib.layers.variance_scaling_initializer()", "tf.variance_scaling_initializer()"),
    ],
    "rnn_cell.py": [
        ("import tensorflow as tf", "import tensorflow.compat.v1 as tf\ntf.disable_v2_behavior()"),
        ("import tensorflow.contrib.distributions as tfd", "import tensorflow_probability as tfp\ntfd = tfp.distributions"),
        ("tf.contrib.rnn.LSTMCell", "tf.nn.rnn_cell.LSTMCell"),
        ("np.ones_like(es)", "tf.ones_like(es)"),
    ],
    "rnn_ops.py": [
        ("from tensorflow.python.framework import constant_op", "import tensorflow.compat.v1 as tf\ntf.disable_v2_behavior()\n\nfrom tensorflow.python.framework import constant_op"),
        ("from tensorflow.python.ops.rnn_cell_impl import _concat, _like_rnncell", "from tensorflow.python.ops.rnn_cell_impl import _concat"),
        ("if not _like_rnncell(cell):", "if not isinstance(cell, tf.compat.v1.nn.rnn_cell.RNNCell):"),
        ("context.in_graph_mode()", "not context.executing_eagerly()"),
        ("control_flow_ops.cond(", "tf.cond("),
        ("control_flow_ops.while_loop(", "tf.while_loop("),
    ],
}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: prepare_graves_checkout.py /path/to/handwriting-synthesis", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).expanduser().resolve()
    if not (root / "demo.py").is_file():
        print(f"Not a Graves handwriting-synthesis checkout: {root}", file=sys.stderr)
        return 2
    for filename, replacements in REPLACEMENTS.items():
        path = root / filename
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")
    print(f"Prepared {root} for TensorFlow 2 compatibility.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

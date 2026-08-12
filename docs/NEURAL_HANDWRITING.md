# Neural handwriting backend

Printrbot accepts online handwriting trajectories through a small worker
protocol. The base installation stays lightweight; the optional backend uses
the Graves-style RNN reference model in a separate Python 3.12 environment.

## Install the optional backend

```bash
git clone https://github.com/sjvasquez/handwriting-synthesis.git .external/handwriting-synthesis
python3.12 scripts/prepare_graves_checkout.py .external/handwriting-synthesis
python3.12 -m venv .venv-neural
.venv-neural/bin/pip install -e '.[neural]'
```

The reference repository is used as an external model checkout because its
pretrained checkpoint does not declare a redistribution license. The adapter
does not copy the model into Printrbot.

## Run

```bash
export PRINTRBOT_HANDWRITING_WORKER="$PWD/scripts/graves_worker.py"
export PRINTRBOT_HANDWRITING_PYTHON="$PWD/.venv-neural/bin/python"
export PRINTRBOT_GRAVES_SOURCE="$PWD/.external/handwriting-synthesis"
printrbot-studio
```

The normal Write notes handwriting mode uses the legible, authored Hershey
Script centerline font. To test the neural backend, open **Experimental neural
handwriting** and enable **Use the neural model instead**, then set style 0–12
and bias 0–1. The model can be more variable and less legible than the default.
Its points are converted to the same internal polylines used by authored
strokes, so layout, preview, optimization, Z motion, and G-code are shared.

Diffusion models such as DiffInk are not enabled yet: they are research-scale
models with different model assets and style-reference requirements, not a
drop-in trajectory generator for this application.

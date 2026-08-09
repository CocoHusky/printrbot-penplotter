# Neural handwriting backend

Printrbot accepts online handwriting trajectories through a small worker
protocol. The base installation stays lightweight; the optional backend uses
the Graves-style RNN reference model in a separate Python 3.12 environment.

## Install the optional backend

```bash
git clone https://github.com/sjvasquez/handwriting-synthesis.git ~/handwriting-synthesis
python scripts/prepare_graves_checkout.py ~/handwriting-synthesis
python3.12 -m venv ~/.venvs/printrbot-neural
~/.venvs/printrbot-neural/bin/pip install -e '.[neural]'
```

The reference repository is used as an external model checkout because its
pretrained checkpoint does not declare a redistribution license. The adapter
does not copy the model into Printrbot.

## Run

```bash
export PRINTRBOT_HANDWRITING_WORKER="$PWD/scripts/graves_worker.py"
export PRINTRBOT_HANDWRITING_PYTHON="$HOME/.venvs/printrbot-neural/bin/python"
export PRINTRBOT_GRAVES_SOURCE="$HOME/handwriting-synthesis"
printrbot-studio
```

In Write notes, choose `Neural trajectory (Graves)`, set style 0–12 and bias
0–1, then render. The resulting points are converted to the same internal
polylines used by authored strokes, so layout, preview, optimization, Z
motion, and G-code are shared.

Diffusion models such as DiffInk are not enabled yet: they are research-scale
models with different model assets and style-reference requirements, not a
drop-in trajectory generator for this application.

# Printrbot Pen Plotter

Printrbot Pen Plotter turns typed text, handwriting, sketches, and images into physical marker drawings. It is being built to create clean lettering, seeded human variation, cursive writing, alternate glyphs, technical robot-like styles, traced artwork, and reproducible drawings controlled from a browser or command line.

The software uses one geometry pipeline from input to preview to G-code, so the image shown on screen is generated from the same final paths sent to the plotter.

## What the project will do

- Type a message and convert it into a real pen drawing.
- Use installed fonts or custom TTF/OTF files, including handwriting and cursive fonts.
- Vary repeated characters in a controlled, reproducible way rather than drawing identical copies.
- Create clean, humanized, cursive-oriented, and deliberately robotic presets.
- Import vector sketches and handwriting through SVG.
- Trace raster images and photographed handwriting into editable drawing paths.
- Preview the exact path, page placement, and pen lifts before motion.
- Generate heaterless Marlin G-code for X/Y drawing and Z pen lift.
- Send reviewed jobs directly over USB or through an ESP32 Wi-Fi bridge.
- Preserve job settings and random seeds so a drawing can be reproduced or varied intentionally.

## Current foundation

The first working software layer now includes:

- text-to-vector conversion;
- custom font selection;
- deterministic per-character rotation, scale, spacing, and baseline variation;
- `clean`, `human`, `cursive`, and `robot` style presets;
- SVG path ingestion;
- automatic page fitting and bounds validation;
- an SVG preview generated from final machine paths;
- Marlin G-code output with configurable Z pen-up and pen-down values;
- a guarded serial sender that waits for Marlin acknowledgements;
- a local browser interface;
- CLI commands and tests.

Raster image tracing, automatic handwriting cleanup, connected cursive stroke planning, glyph-alternate libraries, motion-order optimization, and production ESP32 firmware are planned next rather than presented as complete.

## Install

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Run the test suite:

```bash
pytest
```

## Type text and create a plot job

```bash
printrbot-plotter text "Hello from Printrbot"
```

This creates:

```text
out/plot.svg      exact visual preview
out/plot.gcode    Marlin movement commands
```

Create reproducible humanized lettering:

```bash
printrbot-plotter text "Thank you" \
  --preset human \
  --seed 42 \
  --font-size 20 \
  --output out/thank-you.gcode \
  --preview out/thank-you.svg
```

Using the same text, font, settings, and seed produces the same drawing. Changing the seed produces another controlled variation.

## Use a custom handwriting or cursive font

```bash
printrbot-plotter text "Alex" \
  --preset cursive \
  --font-path /absolute/path/to/handwriting-font.ttf \
  --seed 12
```

The project does not commit or redistribute font files. Supply a font you are licensed to use.

## Convert an SVG sketch

```bash
printrbot-plotter svg artwork.svg \
  --output out/artwork.gcode \
  --preview out/artwork-preview.svg
```

SVG is the current interchange format for traced handwriting, line art, and externally vectorized images.

## Run the browser interface

```bash
printrbot-plotter serve
```

Open:

```text
http://127.0.0.1:8000
```

The page lets you type text, select a style and font, change the variation seed, preview the result, and download the generated G-code.

The browser's hardware endpoint is disabled by default. Rendering and downloading remain available without a printer.

## Send a reviewed job to Marlin

First inspect the generated SVG and G-code. Confirm that the machine is clear, the pen is up, and Z values are calibrated. Then send the file with an explicit confirmation:

```bash
printrbot-plotter send out/plot.gcode \
  --port /dev/cu.usbmodemPrintrbot123451 \
  --confirm DRAW
```

The sender strips comments, sends one command at a time, waits for Marlin's `ok`, and stops on an error or timeout.

## Enable the browser hardware endpoint

Only after direct serial plotting has been calibrated:

```bash
export PLOTTER_ALLOW_HARDWARE=1
export PLOTTER_SERIAL_PORT=/dev/cu.usbmodemPrintrbot123451
printrbot-plotter serve
```

The `/api/plot` endpoint additionally requires the literal confirmation value `DRAW`. The initial browser page intentionally exposes preview and download first; automatic job sending will be added after the physical calibration workflow is validated.

## Software flow

```text
input adapter
  text or SVG
      ↓
shared polyline geometry
      ↓
variation, fitting, simplification, bounds check
      ↓
exact SVG preview + Marlin G-code
      ↓
guarded serial or future ESP32 transport
```

Core modules:

```text
src/printrbot_penplotter/inputs.py     text and SVG input adapters
src/printrbot_penplotter/geometry.py   transforms, fitting, preview
src/printrbot_penplotter/gcode.py      Marlin command generation
src/printrbot_penplotter/sender.py     acknowledged serial transport
src/printrbot_penplotter/pipeline.py   end-to-end job composition
src/printrbot_penplotter/web.py        local browser UI and API
src/printrbot_penplotter/cli.py        command-line interface
```

## Safety defaults

- Homing is off unless `--home` is explicitly supplied.
- Every generated X/Y point is checked against the configured page.
- The first and final pen state is up.
- Heater and extrusion commands are never generated.
- Physical serial sending requires `--confirm DRAW`.
- The browser cannot move hardware unless an environment variable explicitly enables it.
- Pen heights and feed rates remain configuration, not hidden assumptions.

Start with a pen-up air plot and scrap paper. The software cannot detect a loose pen, reversed motor, incorrect endstop direction, wiring fault, or obstruction.

## Project direction

`AGENTS.md` defines the non-negotiable final vision, architecture boundaries, development order, and safety rules for coding agents and contributors.

Hardware inventory, firmware state, wiring, sources, power choices, and the physical validation checklist are maintained in [`docs/HARDWARE.md`](docs/HARDWARE.md).

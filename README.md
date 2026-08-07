# Printrbot Pen Plotter

Printrbot Pen Plotter turns typed text, handwriting, sketches, and images into physical marker drawings. It is being built to create clean lettering, seeded human variation, cursive writing, alternate glyphs, technical robot-like styles, traced artwork, and reproducible drawings controlled from a browser or command line.

The software uses one geometry pipeline from input to preview to G-code, so the paths shown on screen are the same paths sent to the plotter.

## What the project will do

- Type a message and convert it into a real pen drawing.
- Use installed fonts or custom TTF/OTF files, including handwriting and cursive fonts.
- Vary repeated characters in a controlled, reproducible way rather than drawing identical copies.
- Create clean, humanized, cursive-oriented, and deliberately robotic presets.
- Import vector sketches and handwriting through SVG.
- Trace raster images and photographed handwriting into editable drawing paths.
- Preview exact machine-space placement, paper boundaries, margins, drawing paths, and pen-up travel.
- Generate heaterless Marlin G-code for X/Y drawing and Z pen lift.
- Send reviewed jobs directly over USB or through an ESP32 Wi-Fi bridge.
- Preserve job settings and random seeds so a drawing can be reproduced or varied intentionally.

## Current Release 0.2 foundation

The software currently includes:

- text-to-vector conversion;
- font sizes converted into real millimeter-scale geometry;
- custom TTF/OTF font selection;
- deterministic per-character rotation, scale, spacing, and baseline variation;
- `clean`, `human`, `cursive`, and `robot` presets;
- SVG path ingestion;
- explicit machine limits and paper origin;
- `none`, `downscale`, and `fit` placement modes;
- left, center, and right positioning;
- finite-coordinate, page-bound, machine-bound, Z-bound, point-count, and command-count validation;
- machine-space SVG previews showing paper, margins, drawing paths, and dashed pen-up travel;
- a known-size square/cross/octagon calibration pattern;
- air-plot G-code that never lowers the pen;
- non-moving Marlin preflight checks using `M115`, `M119`, `M114`, and `M503`;
- acknowledged serial sending with orderly pen-up attempts on cancellation or Marlin error;
- a local browser interface;
- CLI commands and automated tests.

Raster-image tracing, automatic handwriting cleanup, true connected single-line cursive, glyph-alternate libraries, full background job control, production ESP32 bridge firmware, and motion-order optimization remain planned rather than presented as complete.

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

## Generate text at physical size

```bash
printrbot-plotter text "Hello from Printrbot" \
  --font-size 18
```

This creates:

```text
out/plot.svg      exact machine-space preview
out/plot.gcode    Marlin movement commands
```

`--font-size 18` now produces geometry based on an 18 mm font request. The default `downscale` mode preserves that requested size unless the result would exceed the page.

Create reproducible humanized lettering:

```bash
printrbot-plotter text "Thank you" \
  --preset human \
  --seed 42 \
  --font-size 20 \
  --fit-mode none \
  --horizontal-align left \
  --output out/thank-you.gcode \
  --preview out/thank-you.svg
```

Using the same text, font, settings, and seed produces the same drawing. Changing the seed produces another controlled variation.

## Placement modes

```text
none       preserve exact requested scale and fail if it does not fit
downscale  preserve requested scale but shrink oversized work
fit        expand or shrink artwork to fill the drawable paper area
```

The page can be placed inside machine coordinates:

```bash
printrbot-plotter text "Placed text" \
  --font-size 12 \
  --page-width 100 \
  --page-height 80 \
  --page-origin-x 20 \
  --page-origin-y 30 \
  --margin 5 \
  --fit-mode none \
  --horizontal-align left \
  --vertical-align bottom
```

The preview shows the full machine area, paper rectangle, usable margin, ink paths, and dashed pen-up travel.

## Use a custom handwriting or cursive font

```bash
printrbot-plotter text "Alex" \
  --preset cursive \
  --font-path /absolute/path/to/handwriting-font.ttf \
  --seed 12
```

The project does not commit or redistribute font files. Supply a font you are licensed to use.

Current font rendering follows glyph outlines. True single-line handwriting and connected cursive are a later writing-engine milestone.

## Convert an SVG sketch

```bash
printrbot-plotter svg artwork.svg \
  --fit-mode fit \
  --output out/artwork.gcode \
  --preview out/artwork-preview.svg
```

SVG is the current interchange format for traced handwriting, line art, and externally vectorized images.

## Generate the safe calibration pattern

Create a known-size 10 mm square/cross/octagon pattern that keeps the pen raised:

```bash
printrbot-plotter calibrate
```

Outputs:

```text
out/calibration.svg
out/calibration.gcode
```

The default calibration job is an **air plot**. Inspect the preview, then send it only after machine direction and available travel have been checked.

A pen-down calibration file can be generated later:

```bash
printrbot-plotter calibrate --pen-plot
```

Do not use `--pen-plot` until the air plot has completed safely and Z-up/Z-down values are physically calibrated.

## Generate any job as an air plot

```bash
printrbot-plotter text "Air test" \
  --air-plot \
  --z-up 5
```

In air-plot mode, every XY path is traced while Z remains at the configured pen-up height.

## Run the non-moving Marlin preflight

```bash
printrbot-plotter preflight \
  --port /dev/cu.usbmodemPrintrbot123451
```

The preflight performs only these queries:

```text
M115  firmware identity
M119  endstop state report
M114  current position
M503  stored settings
```

It does not home or move an axis. Passing preflight confirms communication and reporting, not correct motor direction or pen calibration.

## Run the browser interface

```bash
printrbot-plotter serve
```

Open:

```text
http://127.0.0.1:8000
```

The page lets you:

- type text;
- select style, font, seed, and physical font size;
- set page size and origin;
- select fit behavior and alignment;
- preview paper, margins, drawing paths, and pen-up travel;
- generate a 10 mm air-calibration job;
- download G-code.

The browser's hardware endpoint is disabled by default. Rendering and downloading remain available without a printer.

## Send a reviewed job to Marlin

First inspect the SVG and G-code. Confirm that the machine is clear, the pen is raised, coordinates are valid, and Z-up is calibrated. Then send the file with an explicit confirmation:

```bash
printrbot-plotter send out/calibration.gcode \
  --port /dev/cu.usbmodemPrintrbot123451 \
  --safe-z-up 5 \
  --confirm DRAW
```

The sender:

- strips comments;
- sends one command at a time;
- waits for Marlin's `ok`;
- stops on error or timeout;
- attempts `M400`, pen-up, and `M400` after ordinary cancellation or Marlin failure.

Pressing `Ctrl+C` during CLI sending attempts the same orderly pen-up stop. Physical power removal must still remain reachable during first tests.

## Enable the browser hardware endpoint

Only after direct serial preflight and air-plot calibration:

```bash
export PLOTTER_ALLOW_HARDWARE=1
export PLOTTER_SERIAL_PORT=/dev/cu.usbmodemPrintrbot123451
printrbot-plotter serve
```

The `/api/plot` endpoint additionally requires the literal confirmation value `DRAW`. A full background job manager with pause, resume, progress, and emergency-stop controls remains part of Release 0.2 follow-up work.

## Software flow

```text
input adapter
  text or SVG
      ↓
millimeter polyline geometry
      ↓
physical layout + finite validation
      ↓
absolute machine-space paths
      ↓
exact SVG preview + bounds-checked Marlin G-code
      ↓
guarded serial or future ESP32 transport
```

Core modules:

```text
src/printrbot_penplotter/inputs.py       text and SVG input adapters
src/printrbot_penplotter/geometry.py     validation, layout, transforms, preview
src/printrbot_penplotter/calibration.py  known-size test geometry
src/printrbot_penplotter/gcode.py        Marlin command generation
src/printrbot_penplotter/preflight.py    non-moving controller checks
src/printrbot_penplotter/sender.py       acknowledged serial transport
src/printrbot_penplotter/pipeline.py     end-to-end job composition
src/printrbot_penplotter/web.py          local browser UI and API
src/printrbot_penplotter/cli.py          command-line interface
```

## Safety defaults

- Homing is off unless `--home` is explicitly supplied.
- Text preserves physical size by default rather than filling the page.
- Every generated coordinate must be finite.
- Every X/Y point is checked against paper and machine limits.
- Pen-up and pen-down Z values are checked against machine Z limits.
- The first and final pen state is up.
- Air-plot mode never emits a pen-down Z move.
- Heater and extrusion commands are never generated.
- Physical serial sending requires `--confirm DRAW`.
- The browser cannot move hardware unless an environment variable explicitly enables it.
- Pen heights, page origin, machine bounds, alignment, and feed rates remain explicit configuration.

Start with non-moving preflight, then a pen-up calibration air plot, then scrap paper. The software cannot detect a loose pen, reversed motor, incorrect endstop direction, wiring fault, shifted paper, or obstruction.

## Project direction

[`AGENTS.md`](AGENTS.md) defines the non-negotiable final vision, architecture boundaries, development order, and safety rules.

[`docs/RELEASE_0.2.md`](docs/RELEASE_0.2.md) tracks completed and remaining safe-machine work.

Hardware inventory, firmware state, wiring, sources, power choices, and the physical validation checklist are maintained in [`docs/HARDWARE.md`](docs/HARDWARE.md).

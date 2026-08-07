# Printrbot Pen Plotter

Printrbot Pen Plotter turns typed text, handwriting-style strokes, sketches, and vector artwork into physical marker drawings. It is being built to create clean lettering, seeded human variation, connected cursive, deliberately robotic writing, traced artwork, and reproducible drawings controlled from a browser or command line.

The software uses one geometry pipeline from input to preview to G-code, so the paths shown on screen are the same absolute machine-space paths sent to Marlin.

## What the project is designed to do

- Type a message and convert it into a physical pen drawing.
- Draw letters as single centerlines instead of tracing both edges of a filled font.
- Use reproducible alternate glyphs so repeated characters do not have to look identical.
- Create clean, humanized, cursive-oriented, and technical robot styles.
- Load custom JSON stroke-font packs with authored paths and cursive anchors.
- Preserve conventional TTF/OTF outline rendering when outlined lettering is desired.
- Wrap text to a physical width measured in millimeters.
- Import vector sketches and handwriting through SVG.
- Preview exact machine placement, paper boundaries, margins, ink paths, and pen-up travel.
- Generate heaterless Marlin G-code for X/Y drawing and Z pen lift.
- Send reviewed jobs directly over USB or through a future ESP32 Wi-Fi bridge.
- Preserve settings and random seeds so a drawing can be reproduced or intentionally varied.

## Current Release 0.3 foundation

The current software includes:

- native single-line `StrokeFont` and `GlyphVariant` models;
- built-in `hand` and `robot` centerline fonts;
- uppercase A–Z, lowercase a–z, digits, and common punctuation;
- three deterministic variants for built-in hand glyphs;
- `first`, `seeded`, and `cycle` variant-selection modes;
- lowercase entry/exit anchors and simple cursive baseline joins;
- millimeter cap height, tracking, word spacing, slant, and word wrapping;
- optional nearest-endpoint ordering for independent multi-stroke glyphs;
- a validated custom JSON stroke-font format;
- explicit `stroke` and `outline` text engines;
- custom TTF/OTF outline rendering;
- explicit machine limits, paper origin, margins, scale, and placement;
- `none`, `downscale`, and `fit` placement modes;
- finite-coordinate, paper-bound, machine-bound, Z-bound, point-count, and command-count validation;
- machine-space SVG previews showing paper, margins, ink paths, and dashed pen-up travel;
- a known-size square/cross/octagon calibration pattern;
- air-plot G-code that never lowers the pen;
- non-moving Marlin preflight checks using `M115`, `M119`, `M114`, and `M503`;
- acknowledged serial sending with orderly pen-up attempts on cancellation or Marlin error;
- CLI, local browser interface, metadata reporting, and automated tests.

The built-in hand alphabet is an initial engineering font, not a finished calligraphy family. Current cursive uses simple connector curves between compatible lowercase anchors. Contextual forms, ligatures, collision detection, interactive glyph editing, image tracing, full background job control, and production ESP32 firmware remain planned.

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

## Generate single-line handwriting

```bash
printrbot-plotter text "Hello from Printrbot" \
  --preset human \
  --font-size 18
```

This creates:

```text
out/plot.svg      exact machine-space preview
out/plot.gcode    Marlin movement commands
```

The default human preset uses the built-in `hand` centerline font. `--font-size 18` requests an 18 mm cap height before page placement. The default `downscale` mode keeps that physical size unless the drawing must shrink to fit.

## Create reproducible letter variation

```bash
printrbot-plotter text "banana" \
  --preset human \
  --variant-mode seeded \
  --seed 42 \
  --font-size 16
```

The same text, font, settings, and seed produce the same glyph choices and jitter. Changing the seed produces another controlled variation.

Variant modes:

```text
first    always use the first authored glyph form
seeded   choose a deterministic form from character, position, and seed
cycle    rotate through every authored form in order
```

Inspect alternate forms directly:

```bash
printrbot-plotter text "aaaaaaaaa" \
  --preset human \
  --variant-mode cycle \
  --font-size 18
```

## Generate connected cursive-style writing

```bash
printrbot-plotter text "minimum motion" \
  --preset cursive \
  --font-size 14 \
  --wrap-width 110
```

The cursive preset uses:

- the built-in `hand` centerline font;
- seeded alternate glyphs;
- lowercase entry and exit anchors;
- baseline connectors;
- a stronger writing slant;
- tighter tracking.

The current engine connects letters where both neighboring glyphs define anchors. It does not yet perform contextual substitutions, ligatures, or collision-aware calligraphy.

Connection behavior can be overridden:

```bash
printrbot-plotter text "connected" \
  --preset human \
  --connect-letters \
  --slant 7 \
  --letter-spacing 0
```

## Generate robot lettering

```bash
printrbot-plotter text "ROBOT 03" \
  --preset robot \
  --font-size 16
```

The robot preset uses fixed geometric centerline glyphs, no random jitter, and no cursive joins.

## Wrap text using physical width

```bash
printrbot-plotter text "This sentence wraps to a measured text box." \
  --preset human \
  --font-size 10 \
  --wrap-width 95 \
  --fit-mode none \
  --horizontal-align left
```

`--wrap-width` is measured in millimeters before final page alignment. Explicit newline characters remain supported.

## Use the outline compatibility engine

Conventional fonts describe filled outlines. Choose the outline engine when that is the intended effect:

```bash
printrbot-plotter text "Outlined title" \
  --engine outline \
  --font-family "DejaVu Sans" \
  --font-size 18
```

Use a custom TTF/OTF file:

```bash
printrbot-plotter text "Outlined script" \
  --engine outline \
  --font-path /absolute/path/to/font.ttf \
  --font-size 18
```

The outline engine traces glyph edges and can create double-line letters. It is not the single-line handwriting engine.

## Inspect built-in stroke fonts

```bash
printrbot-plotter fonts
```

Inspect one font and its variant counts:

```bash
printrbot-plotter fonts --font hand
```

Built-ins:

```text
hand   lowercase handwriting centerlines plus uppercase, digits, punctuation, and three variants
robot  fixed geometric centerlines
```

## Use a custom stroke-font pack

Validate and inspect the included example:

```bash
printrbot-plotter fonts \
  --file fonts/example-stroke-font.json
```

Render with it:

```bash
printrbot-plotter text "Aaa" \
  --engine stroke \
  --stroke-font-path fonts/example-stroke-font.json \
  --variant-mode cycle \
  --connect-letters \
  --font-size 18
```

Unsupported characters use the font's fallback glyph and are listed in job metadata rather than silently removed.

The complete format is documented in [`docs/STROKE_FONT_FORMAT.md`](docs/STROKE_FONT_FORMAT.md).

## Placement modes

```text
none       preserve exact requested scale and fail if it does not fit
downscale  preserve requested scale but shrink oversized work
fit        expand or shrink artwork to fill the drawable paper area
```

Place a text box inside machine coordinates:

```bash
printrbot-plotter text "Placed text" \
  --preset human \
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

## Convert an SVG sketch

```bash
printrbot-plotter svg artwork.svg \
  --fit-mode fit \
  --output out/artwork.gcode \
  --preview out/artwork-preview.svg
```

SVG is the current interchange format for line art, handwriting traces, and externally vectorized images.

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

## Generate any writing job as an air plot

```bash
printrbot-plotter text "Air test" \
  --preset human \
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

The page provides controls for:

- single-line or outline text engines;
- human, clean, cursive, and robot presets;
- stroke font, glyph variants, and random seed;
- cursive joins, slant, tracking, and word spacing;
- physical cap height and wrapping width;
- page size, origin, fit behavior, and alignment;
- exact preview, calibration generation, and G-code download.

The browser's hardware endpoint remains disabled by default. Rendering and downloading work without a printer.

## Send a reviewed job to Marlin

First inspect the SVG and G-code. Confirm that the machine is clear, the pen is raised, coordinates are valid, and Z-up is calibrated. Then send with explicit confirmation:

```bash
printrbot-plotter send out/calibration.gcode \
  --port /dev/cu.usbmodemPrintrbot123451 \
  --safe-z-up 5 \
  --confirm DRAW
```

The sender:

- blocks heater, extrusion, and tool-change commands;
- strips comments;
- sends one command at a time;
- waits for Marlin's `ok`;
- stops on error or timeout;
- attempts `M400`, pen-up, and `M400` after ordinary cancellation or serial/Marlin failure.

Pressing `Ctrl+C` during CLI sending attempts the same orderly pen-up stop. Physical power removal must still remain reachable during first tests.

## Enable the browser hardware endpoint

Only after direct serial preflight and air-plot calibration:

```bash
export PLOTTER_ALLOW_HARDWARE=1
export PLOTTER_SERIAL_PORT=/dev/cu.usbmodemPrintrbot123451
printrbot-plotter serve
```

The `/api/plot` endpoint additionally requires the literal confirmation value `DRAW`. Background job states, pause/resume, live logs, and emergency-stop controls remain unfinished Release 0.2 work.

## Software flow

```text
typed text
    ↓
stroke font + deterministic glyph variants
    ↓
word wrapping + optional cursive connectors
    ↓
millimeter centerline geometry
    ↓
physical page layout + finite validation
    ↓
absolute machine-space paths
    ↓
exact SVG preview + bounds-checked Marlin G-code
    ↓
guarded serial or future ESP32 transport
```

Core modules:

```text
src/printrbot_penplotter/stroke_fonts.py  centerline font model, built-ins, JSON loader
src/printrbot_penplotter/writing.py       variants, wrapping, joins, physical writing layout
src/printrbot_penplotter/optimize.py      deterministic pen-travel ordering helpers
src/printrbot_penplotter/inputs.py        stroke/outline text and SVG adapters
src/printrbot_penplotter/geometry.py      validation, layout, transforms, preview
src/printrbot_penplotter/calibration.py   known-size test geometry
src/printrbot_penplotter/gcode.py         Marlin command generation
src/printrbot_penplotter/preflight.py     non-moving controller checks
src/printrbot_penplotter/sender.py        acknowledged serial transport
src/printrbot_penplotter/pipeline.py      end-to-end job composition
src/printrbot_penplotter/web.py           local browser UI and API
src/printrbot_penplotter/cli.py           command-line interface
```

## Safety defaults

- Homing is off unless `--home` is explicitly supplied.
- Text preserves physical size by default rather than filling the page.
- Every generated coordinate must be finite.
- Every X/Y point is checked against paper and machine limits.
- Pen-up and pen-down Z values are checked against machine Z limits.
- The first and final pen state is up.
- Air-plot mode never emits a pen-down Z move.
- Heater, extrusion, and tool-change commands are blocked from normal serial sending.
- Physical serial sending requires `--confirm DRAW`.
- The browser cannot move hardware unless an environment variable explicitly enables it.
- Pen heights, page origin, machine bounds, alignment, feed rates, font engine, and variation seed remain explicit configuration.

Start with non-moving preflight, then a pen-up calibration air plot, then scrap paper. The software cannot detect a loose pen, reversed motor, incorrect endstop direction, wiring fault, shifted paper, or obstruction.

## Project direction

[`AGENTS.md`](AGENTS.md) defines the non-negotiable final vision, architecture boundaries, development order, and safety rules.

[`docs/RELEASE_0.2.md`](docs/RELEASE_0.2.md) tracks safe-machine work that remains physically incomplete.

[`docs/RELEASE_0.3.md`](docs/RELEASE_0.3.md) tracks native writing-engine work and its current limitations.

Hardware inventory, firmware state, wiring, sources, power choices, and the physical validation checklist are maintained in [`docs/HARDWARE.md`](docs/HARDWARE.md).

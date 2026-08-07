# Printrbot Pen Plotter

Printrbot Pen Plotter converts typed text, photographed or scanned handwriting, raster images, and vector artwork into reproducible physical marker drawings. The software generates centerline handwriting, seeded glyph variations, connected cursive-style writing, geometric robot lettering, raster centerlines or contours, exact machine-space previews, and guarded Marlin G-code. Jobs can be sent directly over USB or uploaded to an ESP32-C3 Wi-Fi bridge.

The preview and G-code are always generated from the same final absolute polylines.

## Current capabilities

### Writing and geometry

- Native single-line `hand` and `robot` stroke fonts.
- Uppercase, lowercase, digits, and common punctuation.
- Deterministic alternate glyphs using a saved random seed.
- Simple lowercase cursive joins.
- Physical cap height, tracking, word spacing, slant, and wrapping in millimeters.
- Custom JSON stroke-font packs.
- Conventional TTF/OTF outline rendering when double-line outlined lettering is desired.
- SVG path import.
- Raster image and handwriting tracing from PNG, JPEG, WebP, TIFF, and BMP files.
- Explicit centerline and contour trace modes.
- Deterministic Otsu or manual thresholding, inversion, blur, size limiting, and small-component cleanup.
- Browser drag-and-drop raster workflow with original, cleaned-mask, editable-trace, and final-machine views.
- In-browser path deletion, reversal, midpoint splitting, two-stroke joining, endpoint dragging, and undo.
- Editable SVG, G-code, and reproducible raster-job JSON downloads.
- Explicit machine limits, paper origin, margins, scale, and placement.
- Exact SVG preview showing paper, ink strokes, and dashed pen-up travel.
- Bounds-checked heaterless Marlin G-code.

### Release 0.5 — Image & Handwriting Studio

- EXIF-aware image loading and transparent-background handling.
- Bounded preprocessing so large phone photos are downsampled before tracing.
- `centerline` tracing using skeletonization and graph paths for stroke-like input.
- `contour` tracing for filled shapes, logos, and silhouettes.
- `printrbot-plotter image` for general raster artwork.
- `printrbot-plotter handwriting` for centerline tracing of photographed or scanned writing.
- Trace metadata recording threshold, cleanup, resize, skeleton, stroke, and point counts.
- `--trace-svg` for exporting a plain editable SVG that can be corrected and re-imported.
- `printrbot-studio` browser application with drag-and-drop input and live preprocessing controls.
- Four-stage inspection: original image → cleaned binary mask → editable raw trace → exact machine preview.
- Manual geometry correction remains upstream of machine preview and G-code, preserving one geometry source of truth.
- Every browser job includes source SHA-256, trace settings, raw geometry, and final machine geometry in a downloadable JSON sidecar.

Release 0.5 traces visible handwriting marks; it does not perform OCR, infer characters, or retype notes.

### Safety and calibration

- Non-moving `M115`, `M119`, `M114`, and `M503` preflight.
- Known-size square/cross/octagon calibration pattern.
- Air-plot mode that never emits a pen-down move.
- Finite-coordinate, machine-bound, paper-bound, Z-bound, point-count, and command-count validation.
- USB serial sending one command at a time with Marlin `ok` acknowledgement.
- Heater, extrusion, tool-change, and `E`-axis commands blocked from normal jobs.
- Separate orderly cancellation and immediate emergency stop behavior.

### Release 0.4 ESP32 transport

- PlatformIO firmware for the ESP32-C3-DevKitC-02.
- Setup Wi-Fi access point and optional home-network connection.
- GPIO6 RX / GPIO7 TX Marlin UART at 115200 baud.
- G-code upload to ESP32 LittleFS.
- Full-file safety validation before a job becomes runnable.
- One active hardware job at a time.
- Ready, running, paused, cancelling, cancelled, completed, failed, and emergency states.
- Acknowledgement-based progress and UART activity log.
- Browser upload, start, pause, resume, orderly cancel, emergency stop, and non-moving queries.
- Python `printrbot-bridge` client for scripted upload and control.
- Native firmware protocol tests and reproducible ESP32 build artifacts in CI.

Release 0.2 physical machine validation is still required before a real pen-down drawing. Release 0.4 firmware is a development bridge and does not yet provide authenticated HTTP sessions.

## Install the Python application

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
pytest
```

## Generate single-line handwriting

```bash
printrbot-plotter text "Hello from Printrbot" \
  --preset human \
  --font-size 18
```

Outputs:

```text
out/plot.svg      exact machine-space preview
out/plot.gcode    Marlin movement commands
```

Create reproducible variation:

```bash
printrbot-plotter text "banana" \
  --preset human \
  --variant-mode seeded \
  --seed 42 \
  --font-size 16
```

Cycle through authored forms:

```bash
printrbot-plotter text "aaaaaaaaa" \
  --preset human \
  --variant-mode cycle \
  --font-size 18
```

## Generate cursive-style writing

```bash
printrbot-plotter text "minimum motion" \
  --preset cursive \
  --font-size 14 \
  --wrap-width 110
```

Current cursive uses authored entry/exit anchors and simple connector curves. It does not yet implement contextual forms, ligatures, or collision-aware calligraphy.

## Generate robot lettering

```bash
printrbot-plotter text "ROBOT 05" \
  --preset robot \
  --font-size 16
```

## Use the outline compatibility engine

```bash
printrbot-plotter text "Outlined title" \
  --engine outline \
  --font-family "DejaVu Sans" \
  --font-size 18
```

A custom TTF/OTF can be supplied with `--font-path`. Outline fonts trace glyph edges and are intentionally different from the single-line stroke engine.

## Inspect or load stroke fonts

```bash
printrbot-plotter fonts
printrbot-plotter fonts --font hand
printrbot-plotter fonts --file fonts/example-stroke-font.json
```

Custom font format: [`docs/STROKE_FONT_FORMAT.md`](docs/STROKE_FONT_FORMAT.md)

## Trace a raster image from the CLI

```bash
printrbot-plotter image sketch.png \
  --trace-mode contour \
  --air-plot \
  --output out/sketch.gcode \
  --preview out/sketch.svg
```

Use `--trace-mode centerline` when the raster contains stroke-like line art rather than filled regions. The default threshold is deterministic global Otsu thresholding. Override it when needed:

```bash
printrbot-plotter image sketch.jpg \
  --threshold 145 \
  --min-component 12 \
  --simplify-px 1.2 \
  --air-plot
```

For light artwork on a dark background, add `--invert`.

## Trace photographed or scanned handwriting

```bash
printrbot-plotter handwriting note.jpg \
  --air-plot \
  --output out/note.gcode \
  --preview out/note.svg
```

The handwriting command uses centerline tracing so a thick marker stroke is reduced toward one drawable path instead of producing both sides of an outline. It traces the marks as geometry; it does not recognize or retype the writing.

Export the raw pre-placement trace for manual cleanup:

```bash
printrbot-plotter handwriting note.jpg \
  --trace-svg out/note-trace.svg \
  --air-plot
```

Edit `out/note-trace.svg` in a vector editor, then re-import it:

```bash
printrbot-plotter svg out/note-trace.svg \
  --air-plot \
  --output out/note-corrected.gcode \
  --preview out/note-corrected.svg
```

## Run the Image & Handwriting Studio

```bash
printrbot-studio
```

Open:

```text
http://127.0.0.1:8000/raster
```

The browser studio lets you:

1. drag in an image or handwriting photograph;
2. choose centerline or contour tracing;
3. adjust threshold, inversion, blur, noise removal, and simplification;
4. compare the original, cleaned mask, raw vector trace, and final machine preview;
5. click paths to select them, Shift-click to select two, delete/reverse/split/join paths, and drag selected path endpoints;
6. regenerate the final preview from those exact edited paths;
7. download edited SVG, G-code, or a JSON sidecar containing the source SHA-256, trace settings, and geometry.

The original writing interface remains available at `http://127.0.0.1:8000/` in the same process.

Release 0.5 details: [`docs/RELEASE_0.5.md`](docs/RELEASE_0.5.md)

## Generate an air-plot calibration

```bash
printrbot-plotter calibrate
```

This creates:

```text
out/calibration.svg
out/calibration.gcode
```

The default calibration file is an air plot. Do not use `--pen-plot` until motor direction, homing, machine origin, travel, and Z-up/Z-down have been physically validated.

## Run direct USB preflight

```bash
printrbot-plotter preflight \
  --port /dev/cu.usbmodemPrintrbot123451
```

This only queries firmware identity, endstops, position, and stored settings. It does not move the machine.

## Send a reviewed job directly over USB

```bash
printrbot-plotter send out/calibration.gcode \
  --port /dev/cu.usbmodemPrintrbot123451 \
  --safe-z-up 5 \
  --confirm DRAW
```

The sender waits for Marlin `ok` after every command and attempts `M400 → pen up → M400` after an ordinary cancellation or communication failure.

## Run the writing browser application only

```bash
printrbot-plotter serve
```

Open `http://127.0.0.1:8000`. For writing plus raster routes in one server, use `printrbot-studio` instead.

## Build and flash the ESP32 bridge

```bash
cd firmware/esp32
python -m pip install platformio==6.1.19
pio test -e native
pio run -e esp32-c3-devkitc-02
pio run -e esp32-c3-devkitc-02 -t upload
```

During USB flashing, disconnect external 5 V from the ESP32. The Printrboard UART can remain disconnected for the first Wi-Fi test.

After flashing:

```text
Wi-Fi:    Printrbot-Bridge
Password: plotter123
Page:     http://192.168.4.1
```

Firmware guide: [`firmware/esp32/README.md`](firmware/esp32/README.md)

HTTP API: [`docs/ESP32_API.md`](docs/ESP32_API.md)

## Use the Python ESP32 client

```bash
printrbot-bridge status
printrbot-bridge upload out/calibration.gcode
printrbot-bridge start
printrbot-bridge pause
printrbot-bridge resume
printrbot-bridge cancel
printrbot-bridge query M119
printrbot-bridge emergency --confirm STOP
```

Use another bridge address with `--url`:

```bash
printrbot-bridge --url http://printrbot.local status
```

## ESP32 and Printrboard responsibilities

```text
Python application
  text / stroke fonts / SVG / raster tracing
  variation and wrapping
  manual raster correction
  machine-space layout
  exact preview
  G-code generation
            ↓ HTTP upload
ESP32-C3 bridge
  Wi-Fi and browser UI
  stored job validation
  one-command-at-a-time forwarding
  progress, pause, cancel, emergency
            ↓ translated UART
Printrboard Rev F4
  Marlin parser
  motion planning
  endstops
  stepper control
            ↓
physical pen drawing
```

The ESP32 does not generate handwriting, trace images, or create motion geometry. The Printrboard remains the real-time motion controller.

## UART requirement

The Printrboard uses 5 V logic and the ESP32-C3 GPIO domain uses 3.3 V logic. A proper level translator is required.

```text
Printrboard EXP1 pin 7 TX1
  → translated to 3.3 V
  → ESP32 GPIO6 RX

ESP32 GPIO7 TX
  → translated to 5 V
  → Printrboard EXP1 pin 5 RX1

EXP1 pin 14 GND ↔ ESP32 GND ↔ translator GND
```

Detailed hardware record: [`docs/HARDWARE.md`](docs/HARDWARE.md)

## Safety defaults

- Homing is off unless explicitly enabled.
- Physical font size remains meaningful instead of silently filling the page.
- Raster images are bounded and downsampled before tracing to limit geometry growth.
- Manually edited raster geometry is validated before final placement.
- Every final coordinate must be finite and inside configured bounds.
- The first and final pen state is up.
- Air-plot mode cannot lower the pen.
- Heater, extrusion, tool-change, and `E`-axis commands are rejected.
- USB physical sending requires `--confirm DRAW`.
- ESP32 embedded `M112` is rejected inside uploaded files and exposed only through a separate emergency endpoint.
- ESP32 pause and orderly cancellation occur between acknowledged commands.
- Only one ESP32 hardware job can be active.
- The current bridge must remain on a trusted network because request-level authentication is not finished.

The software cannot detect a loose pen, reversed motor, incorrect endstop direction, wiring fault, shifted paper, obstruction, incorrect level shifter, unstable power supply, bad photograph perspective, or unwanted trace artifacts that were not removed during review.

## Project documentation

- [`AGENTS.md`](AGENTS.md) — non-negotiable architecture and development guardrails
- [`docs/RELEASE_0.2.md`](docs/RELEASE_0.2.md) — safe-machine foundation and remaining physical validation
- [`docs/RELEASE_0.3.md`](docs/RELEASE_0.3.md) — native writing engine and current limitations
- [`docs/RELEASE_0.4.md`](docs/RELEASE_0.4.md) — ESP32 transport progress and acceptance criteria
- [`docs/RELEASE_0.5.md`](docs/RELEASE_0.5.md) — Image & Handwriting Studio
- [`docs/HARDWARE.md`](docs/HARDWARE.md) — hardware, firmware, wiring, power, and sources
- [`docs/ESP32_API.md`](docs/ESP32_API.md) — embedded HTTP API

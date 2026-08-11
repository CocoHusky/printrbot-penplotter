# Printrbot Pen Plotter

Printrbot Pen Plotter converts typed text, photographed or scanned handwriting, raster images, and vector artwork into reproducible physical marker drawings. The software generates centerline handwriting, seeded glyph variations, connected cursive-style writing, geometric robot lettering, raster centerlines or contours, optimized plot routes, exact machine-space previews, and guarded Marlin G-code. Jobs can be sent directly over USB or uploaded to an ESP32-C3 Wi-Fi bridge.

The preview and G-code are always generated from the same final absolute polylines, including any explicitly enabled Release 0.6 motion transforms.

Licensed under the [Apache License 2.0](LICENSE).

## Current capabilities

### Writing and geometry

- Native single-line `hand` and `robot` stroke fonts.
- Uppercase, lowercase, digits, and common punctuation.
- Deterministic alternate glyphs using a saved random seed.
- Simple lowercase cursive joins.
- Physical cap height, tracking, word spacing, slant, and wrapping in millimeters.
- Custom JSON stroke-font packs.
- SVG path import.
- Raster image and handwriting tracing from PNG, JPEG, WebP, TIFF, and BMP files.
- Explicit centerline and contour trace modes.
- Deterministic Otsu or manual thresholding, inversion, blur, size limiting, and small-component cleanup.
- Browser drag-and-drop raster workflow with original, cleaned-mask, editable-trace, and final-machine views.
- In-browser path deletion, reversal, midpoint splitting, two-stroke joining, endpoint dragging, and undo.
- Editable SVG, G-code, and reproducible raster-job JSON downloads.
- Explicit machine limits, paper origin, margins, scale, and placement.
- Authored, nearest-endpoint, and two-opt route modes.
- Optional stroke reversal, endpoint joining, RDP simplification, resampling, and smoothing.
- Corner-aware drawing feed requests.
- Before/after motion metrics for distance, travel, pen lifts, points, and idealized duration.
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

### Release 0.6 — Motion Quality & Plot Optimization

Release 0.6 acts on already-created, machine-placed polylines. It does not generate artwork and it does not replace Marlin's real-time motion planner.

Available route modes:

- `authored` — preserve incoming stroke order; this is the default and the normal choice for text/cursive.
- `nearest` — greedily choose the closest remaining stroke endpoint, with optional reversal.
- `two_opt` — start from nearest routing and deterministically improve pen-up travel with two-opt refinement.

Optional shape-quality controls are all disabled by default:

- near-endpoint joining;
- millimeter Ramer-Douglas-Peucker simplification;
- fixed-spacing resampling;
- conservative endpoint-preserving smoothing.

Every normal rendered job now reports before/after draw distance, pen-up travel, stroke/point count, pen lifts, estimated duration, and travel savings. The estimate is planning information only; real runtime still depends on Marlin acceleration, junction behavior, transport pacing, and physical mechanics.

Sharp corners can request a separate slower drawing feed using `--corner-feed` and `--corner-angle`. Marlin still performs acceleration and step timing.

### Safety and calibration

- Non-moving `M115`, `M119`, `M114`, and `M503` preflight.
- Known-size square/cross/octagon calibration pattern.
- Calibration deliberately bypasses Release 0.6 route/smoothing transforms.
- Air-plot mode that never emits a pen-down move.
- Finite-coordinate, machine-bound, paper-bound, Z-bound, point-count, and command-count validation.
- Canonical hardware job envelope: `G21 → G90 → G28 → pen up` before XY plotting, then final pen up and `G28 X Y` at the end.
- Direct USB and host-side Wi-Fi uploads perform complete-job validation before hardware receives the file.
- ESP32 firmware validates the complete stored file again before a job can become runnable.
- USB serial sending one command at a time with Marlin `ok` acknowledgement.
- Heater, extrusion, tool-change, and `E`-axis commands blocked from normal jobs.
- Separate orderly cancellation and immediate emergency stop behavior.
- Dedicated Safety Contract CI runs the full Python suite on Python 3.11/3.13, safety smoke tests, ESP32 native protocol tests, and the ESP32-C3 firmware build.

Full contract: [`docs/JOB_SAFETY.md`](docs/JOB_SAFETY.md)

### ESP32 local bridge

- PlatformIO firmware for the ESP32-C3-DevKitC-02.
- Setup Wi-Fi access point and optional home-network connection.
- GPIO6 RX / GPIO7 TX Marlin UART at 115200 baud.
- G-code upload to ESP32 LittleFS.
- Full-file safety validation before a job becomes runnable.
- One active hardware job at a time.
- Ready, running, paused, cancelling, cancelled, completed, failed, and emergency states.
- Acknowledgement-based progress and UART activity log.
- Browser draft editing, bed preview, whole-drawing placement, final validation, start, pause, resume, orderly cancel, emergency stop, and non-moving queries.
- Python `printrbot-bridge` client for scripted upload and control.
- Native firmware protocol tests and reproducible ESP32 build artifacts in CI.

**Deployment status:** rendering, G-code validation, native bridge protocol tests, and the ESP32-C3 build are automated. Treat the bridge as a **local, trusted-network controller**, not an internet-facing service: HTTP requests are not authenticated and OTA updates are not provided. Before a pen-down job on any newly configured machine, run preflight and an air plot, then verify homing direction, paper placement, and Z lift physically.

## Install the Python application

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m pytest
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

Current cursive uses authored entry/exit anchors and simple connector curves. It does not yet implement contextual forms, ligatures, or collision-aware calligraphy. Keep global Release 0.6 routing on `authored` for normal language output.

## Generate robot lettering

```bash
printrbot-plotter text "ROBOT 06" \
  --preset robot \
  --font-size 16
```

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

## Optimize independent artwork motion

For SVG, traced images, or other independent strokes, two-opt routing can reduce pen-up travel:

```bash
printrbot-plotter svg artwork.svg \
  --motion-route two_opt \
  --air-plot \
  --output out/artwork.gcode \
  --preview out/artwork.svg
```

Clean and optimize a dense traced image:

```bash
printrbot-plotter image sketch.png \
  --trace-mode centerline \
  --motion-route two_opt \
  --rdp-tolerance 0.08 \
  --resample-spacing 1.0 \
  --air-plot
```

Conservative smoothing is explicit:

```bash
printrbot-plotter handwriting note.jpg \
  --smooth-passes 1 \
  --rdp-tolerance 0.05 \
  --air-plot
```

Joining nearby endpoints adds ink across the gap, so it is disabled by default and should only be enabled after reviewing the preview:

```bash
printrbot-plotter svg cleaned.svg \
  --motion-route two_opt \
  --join-tolerance 0.25 \
  --air-plot
```

Corner speed can be tuned separately from the normal drawing feed:

```bash
printrbot-plotter svg artwork.svg \
  --draw-feed 1200 \
  --corner-feed 600 \
  --corner-angle 70 \
  --air-plot
```

The command's metadata reports `motion_before`, `motion_after`, `travel_saved_mm`, and `travel_saved_percent` so routing changes can be evaluated before hardware use.

Release 0.6 details: [`docs/RELEASE_0.6.md`](docs/RELEASE_0.6.md)

## Run the Image & Handwriting Studio

```bash
printrbot-studio
```

Open `http://127.0.0.1:8000/`. The **Write** workspace creates centerline text; the **Art** workspace at `http://127.0.0.1:8000/studio2` processes images into plot-ready paths. Both use the same final placement and G-code safety contract.

The Studio exposes **Home all axes before plot** and enables it by default. Turning it off is useful only for offline inspection or special non-hardware workflows; the hardware validators will refuse normal XY plotting without the guarded envelope.

The retired `/raster` editing prototype is no longer served. Use Studio 2 for image processing so there is one supported image workflow.

## Generate an air-plot calibration

```bash
printrbot-plotter calibrate --home
```

This creates:

```text
out/calibration.svg
out/calibration.gcode
```

The default calibration file is an air plot. Use `--home` for any calibration that will actually be sent to hardware. Do not use `--pen-plot` until motor direction, homing, machine origin, travel, and Z-up/Z-down have been physically validated.

## Run direct USB preflight

```bash
printrbot-plotter preflight \
  --port /dev/cu.usbmodemPrintrbot123451
```

This only queries firmware identity, endstops, position, and stored settings. It does not move the machine.

## Send a reviewed job directly over USB

Generate hardware-bound XY jobs with `--home` so they contain the canonical guarded start/end sequence. For example:

```bash
printrbot-plotter text "Hello" \
  --preset human \
  --air-plot \
  --home \
  --output out/hello.gcode \
  --preview out/hello.svg
```

Then send the reviewed job:

```bash
printrbot-plotter send out/hello.gcode \
  --port /dev/cu.usbmodemPrintrbot123451 \
  --safe-z-up 5 \
  --confirm DRAW
```

The direct USB sender validates the complete job before writing the first byte to Marlin. XY jobs without same-job X/Y/Z homing, a safe first XY state, bounds-safe motion, final pen-up, and final `G28 X Y` are rejected. The sender then waits for Marlin `ok` after every command and attempts `M400 → pen up → M400` after an ordinary cancellation or communication failure.

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

The ESP32 uses USB flashing. There is intentionally no OTA update path in this local-controller build.

## Use the Python ESP32 client

Generate a hardware-bound job with `--home`, then:

```bash
printrbot-bridge status
printrbot-bridge upload out/plot.gcode
printrbot-bridge start
printrbot-bridge pause
printrbot-bridge resume
printrbot-bridge cancel
printrbot-bridge query M119
printrbot-bridge emergency --confirm STOP
```

`printrbot-bridge upload` performs complete-job validation before network upload. The ESP32 repeats complete stored-job validation before the job can enter `ready`.

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
  motion routing / optional path cleanup
  exact post-motion preview
  G-code generation
  complete hardware-job validation
            ↓ HTTP upload
ESP32-C3 bridge
  Wi-Fi and browser UI
  stored job validation
  one-command-at-a-time forwarding
  progress, pause, cancel, emergency
            ↓ translated UART
Printrboard Rev F4
  Marlin parser
  acceleration / junction planning
  endstops
  stepper control
            ↓
physical pen drawing
```

The ESP32 does not generate handwriting, trace images, optimize geometry, or create motion geometry. The Printrboard remains the real-time motion controller.

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

- Rendering and preview can deliberately omit homing, but every normal hardware-bound XY job must contain the guarded same-job homing/start/end envelope. Studio enables the visible homing control by default; CLI users include `--home` for hardware-bound generation.
- Physical font size remains meaningful instead of silently filling the page.
- Raster images are bounded and downsampled before tracing to limit geometry growth.
- Manually edited raster geometry is validated before final placement.
- Authored stroke order is the default; global route optimization is explicit.
- Endpoint joining, RDP cleanup, resampling, and smoothing are disabled by default.
- Calibration bypasses Release 0.6 motion transforms.
- Every final coordinate must be finite and inside configured bounds.
- Preview and G-code use the same exact post-motion geometry.
- The first XY motion occurs only after homing and a safe pen-up move; the final state is pen-up with X/Y re-homed and Z left raised.
- X+Y coordinated diagonal movement is valid; simultaneous XY+Z movement is rejected.
- Air-plot mode cannot lower the pen.
- Heater, extrusion, tool-change, and `E`-axis commands are rejected.
- USB physical sending requires `--confirm DRAW` and complete-job validation.
- Host-side ESP32 upload validates the complete job before network transfer; firmware validates it again before `ready`.
- ESP32 embedded `M112` is rejected inside uploaded files and exposed only through a separate emergency endpoint.
- ESP32 pause and orderly cancellation occur between acknowledged commands.
- Only one ESP32 hardware job can be active.
- The current bridge must remain on a trusted network because request-level authentication is not finished.
- Safety-contract regressions are covered by dedicated CI in addition to the repository's general Python and ESP32 checks.

The software cannot detect a loose pen, reversed motor, incorrect endstop direction, wiring fault, shifted paper, obstruction, incorrect level shifter, unstable power supply, bad photograph perspective, or unwanted trace artifacts that were not removed during review. Motion runtime values are estimates rather than measured hardware timing.

## Project documentation

- [`AGENTS.md`](AGENTS.md) — non-negotiable architecture and development guardrails
- [`docs/JOB_SAFETY.md`](docs/JOB_SAFETY.md) — canonical hardware job envelope and validator contract
- [`docs/RELEASE_0.2.md`](docs/RELEASE_0.2.md) — safe-machine foundation and remaining physical validation
- [`docs/RELEASE_0.3.md`](docs/RELEASE_0.3.md) — native writing engine and current limitations
- [`docs/RELEASE_0.4.md`](docs/RELEASE_0.4.md) — ESP32 transport progress and acceptance criteria
- [`docs/RELEASE_0.5.md`](docs/RELEASE_0.5.md) — Image & Handwriting Studio
- [`docs/RELEASE_0.6.md`](docs/RELEASE_0.6.md) — Motion Quality & Plot Optimization
- [`docs/HARDWARE.md`](docs/HARDWARE.md) — hardware, firmware, wiring, power, and sources
- [`docs/ESP32_API.md`](docs/ESP32_API.md) — embedded HTTP API

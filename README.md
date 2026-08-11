# Printrbot Pen Plotter

Local software for turning typed language into tactile, pen-written communication on repurposed Printrbot hardware. It also converts SVGs and images into reviewed plots.

> **Status:** Public demo release, active development. The core text, image, preview, G-code, and ESP32 bridge workflows are usable; the UI and firmware are still evolving.

> **Network notice:** The ESP32 bridge is intended for demo use on a trusted local network. It does not include user authentication, so do not expose it directly to the internet.

<p align="center">
  <img src="docs/images/plotter-hero.png" alt="Printrbot pen plotter with a drawing on its bed" width="460">
</p>

## Why it exists

This project gives discarded or incomplete plotter hardware a practical second life while helping people communicate across languages. The goal is a note that feels made by a person: a real pen moves across real paper, leaving a physical line and texture instead of only producing a digital message or a flat print.

A Printrboard remains responsible for real-time motion, while a Python application handles text and image processing, previews, layout, and G-code. An ESP32-C3 bridge provides local Wi-Fi access and acknowledged UART transport through the required 3.3 V/5 V level shifter.

The project makes written communication more accessible. A typed message can become a physical pen-written note in English, Chinese, Japanese, and other languages when the matching centerline font pack is installed. The same pipeline can prepare images and line art. It does not physically erase ink from paper; removing existing marks still requires a separate erasing tool.

## The workflow

Each step has a separate purpose so the machine never receives an unexplained or unreviewed job.

### 1. Choose the source

Start with text, an SVG, or an image.

This keeps the input flexible while converting every source into the same internal representation: millimeter-based pen paths.

### 2. Choose how it should look

For text, choose a centerline font such as hand or robot lettering. For images, choose grayscale, black-and-white, line-art, silhouette, or pen-shading processing.

This separates appearance from machine movement. A text font or image style describes the marks; it does not directly control the printer.

### 3. Preview and place it

Review the original, processed image, paths, paper, 10 mm grid, print-area bounds, pen-up travel, and final machine coordinates.

This is where scale, margins, origin, rotation, and placement are checked. The preview and exported G-code use the same final geometry.

### 4. Validate and export

Generate SVG for inspection and guarded Marlin G-code for the machine.

Validation checks coordinates, page limits, geometry size, safe Z motion, homing/start/end behavior, and forbidden heater, extrusion, tool-change, or E-axis commands. A job is not ready to send until it passes.

### 5. Plot locally

Send the reviewed job by direct USB or store it on the ESP32-C3 bridge for acknowledged forwarding to Marlin.

The bridge accepts one job at a time and exposes progress, pause, orderly cancel, and emergency stop. It transports the job; it does not render images or generate handwriting.

## See it in action

<p align="center">
  <img src="docs/images/write-multilingual.png" alt="Multilingual centerline text with spacing controls" width="49%">
  <img src="docs/images/studio-grayscale.png" alt="Studio grayscale stage with source and processed previews" width="49%">
</p>
<p align="center">
  <img src="docs/images/studio-pointillism.png" alt="Studio pointillism preview" width="49%">
  <img src="docs/images/studio-machine-export.png" alt="Studio machine and export preview" width="49%">
</p>

The local controller also supports NFC access: tap a configured tag to open `printrbot.local` on a phone or tablet connected to the same trusted network.

<p align="center">
  <img src="docs/images/nfc-quick-access.png" alt="NFC notification opening printrbot.local in Safari" width="520">
</p>

### Tap to print from a phone

1. Connect the phone to the same trusted Wi-Fi network as the bridge.
2. Tap the NFC tag on the printer.
3. Enter a note, choose an image, or load a reviewed G-code draft.
4. Check the bed preview, placement, pen settings, and estimated job details.
5. Validate and store the final job, then press **Start**.

The NFC tag opens the local page; it does not start motion by itself. The explicit review and **Start** action are intentional safety steps.

## Quick start

### Install the Python application

Python 3.11 or newer is required.

```bash
git clone https://github.com/CocoHusky/printrbot-penplotter.git
cd printrbot-penplotter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m pytest -q
```

### Open the browser tools

```bash
printrbot-studio
```

Open:

- `http://127.0.0.1:8000/` for writing text and preparing jobs.
- `http://127.0.0.1:8000/studio2` for the guided image workflow.

### Create centerline text

```bash
printrbot-plotter text "Hello from Printrbot" \
  --preset human \
  --font-size 18 \
  --air-plot \
  --home \
  --output out/hello.gcode \
  --preview out/hello.svg
```

`out/hello.svg` is the visual review file. `out/hello.gcode` is the machine file. Use `--preset robot` for technical single-line lettering or a matching installed font pack for additional languages.

### Trace an image

```bash
printrbot-penplotter image sketch.png \
  --trace-mode contour \
  --air-plot \
  --output out/sketch.gcode \
  --preview out/sketch.svg
```

Use `--trace-mode centerline` for stroke-like drawings or photographed handwriting. The tracer follows visible marks; it does not perform OCR, translation, or handwriting recognition.

## Hardware and local access

- Printrboard / Marlin: real-time motion, acceleration, endstops, and stepper control.
- Python application: text, image processing, layout, path optimization, preview, G-code, and host validation.
- ESP32-C3 bridge: local Wi-Fi UI/API, LittleFS job storage, complete-job validation, and acknowledged UART forwarding.
- Level shifter: mandatory translation between the Printrboard's 5 V UART and the ESP32's 3.3 V GPIO.
- NFC tag: optional shortcut to the local bridge address.

The bridge is a local transport and demo controller, not an internet-facing service. Authentication is not included; keep it on a trusted local network. OTA firmware updates are outside the current product scope.

Hardware wiring and sources: [`docs/HARDWARE.md`](docs/HARDWARE.md)

## Safety

Always review the SVG and run an air plot before using a pen. Hardware-bound jobs require a guarded start/end envelope with homing, safe pen-up movement, configured bounds, and final pen-up state. The Python sender and ESP32 both validate the complete job.

The software cannot detect a loose pen, reversed motor, incorrect endstop direction, shifted paper, obstruction, wiring fault, unstable power, or an unwanted trace artifact. Physical validation remains the operator's responsibility.

Full contract: [`docs/JOB_SAFETY.md`](docs/JOB_SAFETY.md)

## Releases

The latest numbered release is **0.6.0**. Work after 0.6 is currently unreleased on `main`.

| Release | Purpose |
| --- | --- |
| [0.2](docs/RELEASE_0.2.md) | Safe machine foundation and physical validation |
| [0.3](docs/RELEASE_0.3.md) | Native centerline writing engine |
| [0.4](docs/RELEASE_0.4.md) | ESP32 local bridge |
| [0.5](docs/RELEASE_0.5.md) | Image and handwriting studio |
| [0.6.0](docs/RELEASE_0.6.md) | Motion quality and plot optimization |

## Documentation

- [`docs/HARDWARE.md`](docs/HARDWARE.md) — wiring, power, level shifting, and hardware sources.
- [`docs/JOB_SAFETY.md`](docs/JOB_SAFETY.md) — complete hardware-job safety contract.
- [`docs/ESP32_API.md`](docs/ESP32_API.md) — local bridge API.
- [`docs/ESP32_BRIDGE_HARDWARE.md`](docs/ESP32_BRIDGE_HARDWARE.md) — bridge-specific hardware details.
- [`docs/STROKE_FONT_FORMAT.md`](docs/STROKE_FONT_FORMAT.md) — custom centerline font packs.
- [`docs/NEURAL_HANDWRITING.md`](docs/NEURAL_HANDWRITING.md) — optional experimental trajectory backend.
- [`docs/RELEASE_0.6.md`](docs/RELEASE_0.6.md) — motion optimization details.

## Contributing

Keep changes focused, run the relevant tests, and update the documentation when behavior changes. See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md).

## License

Apache-2.0. See [`LICENSE`](LICENSE).

# AGENTS.md — Project Direction and Guardrails

This file is the standing instruction set for every coding agent, contributor, and future work session in this repository.

## Final vision

Build one dependable system that turns a person's intent into a physical pen drawing:

```text
text / handwriting / sketch / image
                ↓
        vector geometry
                ↓
 style + controlled variation
                ↓
      exact visual preview
                ↓
 safety checks + calibration
                ↓
          Marlin G-code
                ↓
   USB or ESP32 Wi-Fi bridge
                ↓
       Printrbot + real pen
```

The finished product must let a user type text or supply handwriting, sketches, or images; choose clean, human, cursive, font-based, or intentionally robotic styles; preview the exact result; and draw it safely with a marker. Repeated letters should support controlled variation so output can look authored rather than mechanically duplicated.

## Non-negotiable product rules

1. **Stay on the pipeline above.** Do not start unrelated printer-control, AI-chat, home-automation, slicer, or generic 3D-printing work.
2. **One geometry source of truth.** Preview and G-code must be generated from the same final polylines. A preview that differs from physical motion is a defect.
3. **Deterministic variation.** Humanization and randomized character variation must accept a seed and reproduce the same output with the same inputs.
4. **Input adapters remain separate from machine output.** Text, SVG, handwriting, and image tracing should all produce the same internal polyline model before G-code is generated.
5. **Hardware motion is opt-in.** Rendering and previewing must work without connected hardware. Sending motion requires explicit confirmation and a configured transport.
6. **No hidden homing or calibration assumptions.** Homing, pen-up height, pen-down height, page bounds, feed rates, and origin must be explicit configuration.
7. **Never send heaters or extrusion commands.** This machine is a heaterless pen plotter with `EXTRUDERS 0`.
8. **Do not bypass voltage conversion.** The Printrboard UART is 5 V logic and the ESP32-C3 GPIO domain is 3.3 V. Keep the documented level-translation boundary.
9. **Preserve Marlin compatibility.** The AT90USB1286 Printrboard remains the real-time motion controller. The ESP32 is a network/host bridge, not a replacement motion planner.
10. **Document evidence.** Hardware claims, pin mappings, firmware choices, and safety decisions belong in `docs/HARDWARE.md` with source links.

## Current implementation boundary

The current foundation is expected to provide:

- typed text to vector paths;
- installed-font and custom TTF/OTF support;
- deterministic clean, human, cursive-oriented, and robot presets;
- SVG path import;
- page fitting and machine-bound validation;
- SVG preview generated from final plot paths;
- Marlin G-code generation using X/Y motion and Z pen lift;
- guarded serial sending;
- a local browser UI and CLI;
- tests proving deterministic output, bounds, and safe default behavior.

Do not claim raster-image tracing, handwriting recognition, stroke-order optimization, ESP32 production firmware, or autonomous calibration is complete until code and tests exist.

## Required development order

Work in this order unless a blocking hardware defect forces a documented change:

1. **Geometry foundation** — text/SVG → polylines → preview/G-code.
2. **Safe direct plotting** — calibration, dry runs, serial acknowledgements, pause/stop behavior.
3. **ESP32 transport** — Wi-Fi UI/API forwarding to Marlin UART with status and recovery.
4. **Image and handwriting ingestion** — thresholding, tracing, simplification, cleanup, manual correction.
5. **Writing intelligence** — single-line fonts, cursive joining, glyph alternates, seeded variation, word layout.
6. **Motion quality** — stroke ordering, reduced pen lifts, corner handling, feed optimization.
7. **Product UX** — job queue, presets, saved calibration, mobile controls, reproducible job files.

## Code architecture rules

- `inputs.py` converts source material into polylines.
- `geometry.py` transforms, fits, simplifies, and previews polylines.
- `gcode.py` is the only module that converts final geometry into Marlin movement commands.
- `sender.py` handles transport acknowledgement and errors; it must not generate artwork.
- `pipeline.py` composes the modules without duplicating their logic.
- Web and CLI layers call the pipeline; they do not implement a second renderer.
- New transports implement the same job-sending boundary rather than modifying rendering code.

## Safety requirements for every hardware change

Before merging hardware-moving code, verify:

- no command exceeds configured X/Y page bounds;
- the first motion occurs with the pen up;
- the final state leaves the pen up;
- homing is disabled by default unless explicitly requested;
- feed rates are configurable and conservative;
- malformed input cannot create NaN, infinity, or extreme coordinates;
- serial errors and timeouts stop the job instead of continuing blindly;
- physical motion still requires a deliberate confirmation phrase;
- emergency-stop behavior is documented and tested manually before being advertised.

## Documentation rules

Update `README.md` when software usage changes. Update `docs/HARDWARE.md` when wiring, electronics, firmware, power, pin assignments, or validated machine settings change. Keep build/wiring procedures out of the README except for a link to the hardware document.

Every hardware source entry should state:

- the exact fact it supports;
- the source URL;
- why that source is trusted;
- whether the fact is vendor-documented, schematic-derived, measured, or experimentally verified.

## Definition of done for a feature

A feature is complete only when:

1. it is implemented through the shared pipeline;
2. it has a test or a documented manual validation procedure;
3. failure behavior is explicit;
4. README usage is updated when user-facing;
5. hardware documentation is updated when electrical or mechanical behavior changes;
6. the result advances the final text/handwriting/image-to-physical-drawing vision.

## Decision rule

When several implementations are possible, choose the one that most directly improves reproducible physical drawing while minimizing custom firmware, duplicated geometry, unsafe assumptions, and irreversible hardware changes.

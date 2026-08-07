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
7. **Never send heaters, extrusion, or tool-change commands.** This machine is a heaterless pen plotter with `EXTRUDERS 0`.
8. **Do not bypass voltage conversion.** The Printrboard UART is 5 V logic and the ESP32-C3 GPIO domain is 3.3 V. Keep the documented level-translation boundary.
9. **Preserve Marlin compatibility.** The AT90USB1286 Printrboard remains the real-time motion controller. The ESP32 is a network/host bridge, not a replacement motion planner.
10. **Document evidence.** Hardware claims, pin mappings, firmware choices, and safety decisions belong in `docs/HARDWARE.md` with source links.

## Writing-engine rules

1. **Centerlines and outlines are different products.** The native stroke engine draws authored centerlines. The TTF/OTF engine traces outlines. Never describe outline paths as single-line handwriting.
2. **Actual glyph alternates come before random jitter.** Human variation should select between distinct authored glyph paths, then optionally apply small seeded transforms. Jitter alone is not a complete alternate-glyph system.
3. **Every writing choice is reproducible.** Font pack, glyph variant, seed, slant, spacing, joins, wrapping, and layout must be represented in settings or metadata.
4. **Unsupported characters are visible.** Use a declared fallback glyph and report every fallback substitution. Never silently drop text.
5. **Cursive joins are geometry.** Connectors must enter the same polyline pipeline, preview, bounds validation, and G-code generation as authored glyph strokes.
6. **Do not reorder written language globally.** Stroke optimization may reorder independent artwork or strokes within a glyph, but must not scramble character or word order unless a font explicitly defines a continuous alternative.
7. **Custom font packs are untrusted input.** Validate finite coordinates, advances, anchors, variant lists, fallback presence, and path sizes before rendering.
8. **Physical font size remains meaningful.** Cap height and wrapping width are millimeter values before page placement. Do not silently expand text to fill the page.
9. **Keep font data separate from layout.** `stroke_fonts.py` owns glyph definitions and loading; `writing.py` owns selection, wrapping, transforms, and joins; machine placement remains in `geometry.py`.
10. **Do not overclaim cursive quality.** Baseline connectors are not contextual calligraphy, ligatures, collision avoidance, or continuous handwriting unless those features are implemented and tested.

## Current implementation boundary

The current foundation provides:

- native centerline stroke fonts with built-in hand and robot alphabets;
- deterministic glyph alternates and optional baseline joins;
- physical wrapping, tracking, word spacing, and slant;
- conventional TTF/OTF outline compatibility;
- SVG path import;
- exact machine-space placement and validation;
- preview generated from final plot paths;
- Marlin G-code using X/Y motion and Z pen lift;
- guarded serial sending;
- local browser UI and CLI;
- tests proving deterministic output, bounds, safe defaults, font loading, joining, and wrapping.

Do not claim raster-image tracing, handwriting recognition, contextual cursive, ligatures, production ESP32 firmware, autonomous calibration, or complete background hardware job control until code and tests exist.

## Development sequence

Software work may proceed in separate releases, but physical drawing remains gated by Release 0.2 validation:

1. **Geometry foundation** — text/SVG → polylines → preview/G-code.
2. **Safe machine foundation** — physical coordinates, calibration, air plots, serial failure behavior.
3. **Writing intelligence** — centerline fonts, alternates, joins, wrapping, and word layout.
4. **ESP32 transport** — Wi-Fi UI/API forwarding to Marlin UART with status and recovery.
5. **Image and handwriting ingestion** — thresholding, centerline/contour tracing, cleanup, manual correction.
6. **Motion quality** — reduced pen lifts, corner handling, smoothing, and feed optimization.
7. **Product UX** — job queue, saved profiles, mobile controls, editing, and reproducible job files.

Writing-engine code can be developed and previewed while physical Release 0.2 work is unfinished. It must not bypass preflight, air-plot, motor-direction, homing, origin, or pen-height validation before real plotting.

## Code architecture rules

- `stroke_fonts.py` defines centerline font models, built-ins, and validated font-pack loading.
- `writing.py` selects glyph variants, wraps text, creates joins, and emits millimeter polylines.
- `optimize.py` provides deterministic travel metrics and ordering helpers without generating artwork.
- `inputs.py` dispatches source material into polylines and keeps stroke/outline engines explicit.
- `geometry.py` validates, transforms, places, simplifies, and previews polylines.
- `gcode.py` is the only module that converts final geometry into Marlin movement commands.
- `sender.py` handles transport acknowledgement and errors; it must not generate artwork.
- `pipeline.py` composes modules without duplicating their logic.
- Web and CLI layers call the pipeline; they do not implement a second renderer.
- New transports implement the same job-sending boundary rather than modifying rendering code.

## Safety requirements for every hardware change

Before merging hardware-moving code, verify:

- no command exceeds configured X/Y paper or machine bounds;
- the first motion occurs with the pen up;
- the final state leaves the pen up;
- homing is disabled by default unless explicitly requested;
- feed rates are configurable and conservative;
- malformed input cannot create NaN, infinity, or extreme coordinates;
- serial errors and timeouts stop the job instead of continuing blindly;
- physical motion still requires a deliberate confirmation phrase;
- emergency-stop behavior is documented and tested manually before being advertised.

## Documentation rules

Update `README.md` when software usage changes. Update release documents when scope or completion changes. Update `docs/HARDWARE.md` when wiring, electronics, firmware, power, pin assignments, or validated machine settings change. Keep build/wiring procedures out of the README except for links to hardware documentation.

Every hardware source entry should state:

- the exact fact it supports;
- the source URL;
- why that source is trusted;
- whether the fact is vendor-documented, schematic-derived, measured, or experimentally verified.

Every bundled or imported font pack should state its provenance and license before distribution beyond private development.

## Definition of done for a feature

A feature is complete only when:

1. it is implemented through the shared pipeline;
2. it has a test or a documented manual validation procedure;
3. failure behavior is explicit;
4. README usage is updated when user-facing;
5. release tracking is updated;
6. hardware documentation is updated when electrical or mechanical behavior changes;
7. the result advances the final text/handwriting/image-to-physical-drawing vision.

## Decision rule

When several implementations are possible, choose the one that most directly improves reproducible physical drawing while minimizing duplicated geometry, unsafe assumptions, irreversible hardware changes, hidden substitutions, and custom firmware.

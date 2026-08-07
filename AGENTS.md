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
      motion-quality stage
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
10. **Document evidence.** Hardware claims, pin mappings, firmware choices, and safety decisions belong in hardware documentation with source links.

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

## Raster image and handwriting rules

1. **Raster input becomes polylines before machine placement.** Thresholding, cleanup, skeletonization, and contour extraction happen upstream of page layout and G-code.
2. **Centerline and contour tracing are distinct.** Centerline mode is intended for stroke-like input such as handwriting; contour mode follows foreground boundaries. Never describe contour output as one-stroke handwriting.
3. **Do not claim handwriting recognition.** Release 0.5 traces visible marks. It does not infer characters, retype notes, perform OCR, or reconstruct semantic writing unless a separate recognition feature is explicitly implemented and tested.
4. **Preprocessing must be deterministic.** Threshold, inversion, blur, component filtering, resize limits, tracing mode, and simplification values belong in metadata or a reproducible job record.
5. **Raster files are untrusted input.** Enforce source-pixel, processed-pixel, geometry-point, and stroke-count limits before hardware output is possible.
6. **Large images are downsampled before expensive tracing.** Do not allow phone-camera resolution to become unbounded skeleton or contour geometry.
7. **Noise removal must be visible and controllable.** Connected-component filtering may remove only components below an explicit configured size; report what was removed.
8. **Manual correction must preserve the shared pipeline.** Browser edits or editable trace SVGs become the geometry source that is then previewed and converted to G-code. Do not maintain a separate hidden corrected representation.
9. **Do not silently apply remote AI or cloud image processing.** Raster tracing is local and deterministic unless the user explicitly opts into a separate external service in a future feature.
10. **Do not overclaim photographic robustness.** Global thresholding is not perspective correction, adaptive illumination handling, semantic segmentation, or background removal. Those capabilities require their own implementation and tests.

## Motion-quality rules

1. **Motion optimization happens after artwork generation and page placement.** `optimize.py` may transform final plot polylines, but it must not become another text, raster, or SVG renderer.
2. **Authored order is the default.** Text and cursive must retain authored language order unless the user explicitly enables global route optimization.
3. **Route optimization is deterministic.** Nearest and two-opt routing must produce identical results for identical geometry and settings.
4. **Stroke reversal preserves geometry.** Reversing a stroke may change traversal direction only; it must not change the set of points that will be drawn.
5. **Endpoint joining is opt-in.** A non-zero gap becomes ink. Never silently join nearby endpoints, especially in text or handwriting.
6. **Shape-changing cleanup is opt-in.** RDP simplification, resampling, and smoothing default to zero/off because they modify physical geometry.
7. **Calibration bypasses motion transforms.** Known-size calibration patterns must not be rerouted, joined, simplified, resampled, or smoothed by Release 0.6 settings.
8. **The post-motion polylines are the source of truth.** Preview, bounds validation, metadata, and G-code must all use the exact same optimized geometry.
9. **Python does not replace Marlin's real-time planner.** Python may select route/order and request feed values. Marlin remains responsible for acceleration, junction behavior, and step timing.
10. **Corner speed is conservative and explicit.** Corner feed and angle threshold are configured values; corner feed must never result in a faster command than normal drawing feed.
11. **Metrics are estimates.** Pen-up distance, pen-down distance, lift count, and idealized duration are planning metrics, not claims about measured physical runtime.
12. **Optimization must never worsen route cost by design.** A refinement such as two-opt should retain the prior route when no tested improvement exists.

## ESP32 transport rules

1. **The ESP32 transports final jobs; it does not render them.** Font selection, image tracing, geometry, layout, preview, motion optimization, and G-code generation remain in the Python application.
2. **One command must be acknowledged before the next is sent.** Do not add blind streaming, speculative buffering, or movement retries that can desynchronize Marlin state.
3. **One hardware job at a time.** Upload replacement, query traffic, and network reconfiguration must not race with an active job.
4. **Validate the complete stored job before start.** A partial upload or unvalidated file must never become runnable.
5. **Apply safety filtering at both ends.** Python generation and ESP32 upload validation both block heaters, extrusion, tool changes, embedded emergency stop, and `E`-axis motion.
6. **Pause is cooperative.** Pause occurs between Marlin acknowledgements and does not pretend to interrupt an already accepted motion command.
7. **Orderly cancel and emergency stop are different operations.** Normal cancel stops new commands and attempts `M400 → calibrated pen up → M400`. Emergency stop sends `M112` immediately and may require controller reset.
8. **Never auto-resume after reset, reconnect, or power loss.** Recovery requires explicit operator review and confirmation.
9. **Keep UART electrical assumptions explicit.** GPIO6 is ESP32 RX, GPIO7 is ESP32 TX, baud is 115200, grounds are common, and a proper 5 V↔3.3 V translator is mandatory.
10. **Treat Wi-Fi and HTTP input as untrusted.** Enforce size limits, line limits, state checks, credential limits, and API authentication before describing the bridge as production-ready.
11. **The setup access point is a recovery channel.** Station-mode support must not remove the ability to reach and recover the device locally.
12. **Firmware builds must be reproducible.** Pin PlatformIO/platform versions, test protocol code natively, compile the exact board target, and publish binary hashes.
13. **No hidden physical validation claims.** Firmware compilation and browser operation do not prove UART voltage safety, motor direction, homing, pen height, or emergency-stop behavior.
14. **Transport clients implement the existing sender boundary.** New desktop/mobile clients upload and monitor the exact G-code represented by the preview; they do not create a second artwork pipeline.

## Current implementation boundary

The current foundation provides:

- native centerline stroke fonts with built-in hand and robot alphabets;
- deterministic glyph alternates and optional baseline joins;
- physical wrapping, tracking, word spacing, and slant;
- conventional TTF/OTF outline compatibility;
- SVG path import;
- deterministic raster preprocessing and explicit centerline/contour tracing;
- Image & Handwriting Studio with four-stage browser inspection and manual path editing;
- source hashing and raster job sidecars;
- exact machine-space placement and validation;
- authored, nearest, and two-opt motion route modes;
- optional stroke reversal and endpoint joining;
- optional RDP simplification, resampling, and endpoint-preserving smoothing;
- motion metrics for draw/travel distance, pen lifts, point count, and estimated time;
- corner-aware drawing feed requests;
- preview generated from the exact final post-motion paths;
- Marlin G-code using X/Y motion and Z pen lift;
- guarded direct USB serial sending;
- ESP32-C3 firmware with Wi-Fi, LittleFS upload, safety validation, acknowledgement-based forwarding, job states, browser controls, and UART logs;
- a Python ESP32 bridge client;
- local browser UI and CLI;
- tests covering deterministic rendering, bounds, safety, writing, raster tracing/editing, transport, and motion optimization.

Do not claim handwriting recognition, contextual calligraphy, adaptive/local thresholding, perspective correction, authenticated ESP32 sessions, power-loss resume, autonomous calibration, measured runtime prediction, or completed physical hardware validation until code and tests exist.

## Development sequence

Software work may proceed in separate releases, but physical drawing remains gated by Release 0.2 validation:

1. **Geometry foundation** — text/SVG → polylines → preview/G-code.
2. **Safe machine foundation** — physical coordinates, calibration, air plots, serial failure behavior.
3. **Writing foundation** — centerline fonts, alternates, joins, wrapping, and word layout.
4. **ESP32 transport** — Wi-Fi UI/API forwarding to Marlin UART with status and recovery.
5. **Image and handwriting ingestion** — thresholding, centerline/contour tracing, browser cleanup, manual correction.
6. **Motion quality** — route optimization, reduced pen lifts, path cleanup, corner handling, feed optimization, and metrics.
7. **Writing intelligence** — contextual forms, richer alternates, ligatures, and collision-aware joins.
8. **Product UX** — job queue, saved profiles, mobile controls, editing, and reproducible job files.

Writing, raster, motion, and transport code can be developed and previewed while Release 0.2 physical work is unfinished. None may bypass preflight, air-plot, motor-direction, homing, origin, level-shifter, power, or pen-height validation before real plotting.

## Code architecture rules

- `stroke_fonts.py` defines centerline font models, built-ins, and validated font-pack loading.
- `writing.py` selects glyph variants, wraps text, creates joins, and emits millimeter polylines.
- `raster.py` owns deterministic raster preprocessing, skeletonization, contour extraction, trace simplification, and editable raw-trace SVG generation.
- `raster_studio.py` owns browser raster upload and manual pre-machine path correction.
- `optimize.py` owns deterministic Release 0.6 motion transforms, route metrics, and route ordering without generating artwork or machine commands.
- `inputs.py` dispatches text, SVG, and raster source material into polylines and keeps engine/trace modes explicit.
- `geometry.py` validates, transforms, places, simplifies, and previews polylines.
- `gcode.py` is the only Python module that converts final geometry into Marlin movement commands.
- `sender.py` handles direct USB acknowledgement and errors; it must not generate artwork.
- `esp32_client.py` uploads and controls already-generated jobs; it must not generate artwork.
- `pipeline.py` composes modules without duplicating their logic and applies motion optimization only after page placement.
- `firmware/esp32/include/plotter_protocol.h` owns firmware-side command sanitation shared with native tests.
- `firmware/esp32/src/printer_bridge.*` owns UART framing, acknowledgement, timeout, and logs.
- `firmware/esp32/src/job_runner.*` owns stored-job state and one-command-at-a-time execution.
- `firmware/esp32/src/main.cpp` owns Wi-Fi, HTTP routing, Preferences, LittleFS upload, and device lifecycle.
- Web and CLI layers call the pipeline or transport clients; they do not implement a second renderer.

## Safety requirements for every hardware-moving change

Before merging hardware-moving code, verify:

- no command exceeds configured X/Y paper or machine bounds;
- the first motion occurs with the pen up;
- the final state leaves the pen up;
- homing is disabled by default unless explicitly requested;
- feed rates are configurable and conservative;
- malformed input cannot create NaN, infinity, extreme coordinates, oversized files, or unsafe commands;
- serial errors and timeouts stop new job commands instead of continuing blindly;
- physical motion still requires a deliberate start action;
- orderly cancellation and emergency stop remain separate;
- no automatic resume occurs after reset or reconnect;
- physical emergency power removal remains reachable during first validation.

## Documentation rules

Update `README.md` when software usage changes. Update release documents when scope or completion changes. Update `docs/HARDWARE.md` or dedicated hardware documents when wiring, electronics, firmware, power, pin assignments, or validated machine settings change. Keep detailed build/wiring procedures out of the root README except for concise summaries and links.

Every hardware source entry should state:

- the exact fact it supports;
- the source URL;
- why that source is trusted;
- whether the fact is vendor-documented, schematic-derived, measured, or experimentally verified.

Every bundled or imported font pack should state its provenance and license before distribution beyond private development.

## Definition of done for a feature

A feature is complete only when:

1. it is implemented through the shared geometry or transport architecture;
2. it has a test or a documented manual validation procedure;
3. failure behavior is explicit;
4. README usage is updated when user-facing;
5. release tracking is updated;
6. hardware documentation is updated when electrical or mechanical behavior changes;
7. physical behavior is not claimed without physical evidence;
8. the result advances the final text/handwriting/image-to-physical-drawing vision.

## Decision rule

When several implementations are possible, choose the one that most directly improves reproducible physical drawing while minimizing duplicated geometry, unsafe assumptions, irreversible hardware changes, hidden substitutions, unauthenticated control, and automatic recovery behavior that could restart motion without an operator.

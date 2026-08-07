# Release 0.2 — Safe Machine Foundation

Release 0.2 establishes a trustworthy coordinate system and a controlled path from generated geometry to first physical motion. It must be completed before adding advanced handwriting, image tracing, or production ESP32 job control.

## Release goal

A user can define machine limits and paper placement, generate a known-size pattern, inspect the exact machine-space path, run non-moving communication checks, perform a pen-up air plot, and only then enable a real pen-down drawing.

## Implemented in the first Release 0.2 increment

- [x] Separate machine bounds from paper bounds.
- [x] Add explicit paper X/Y origin.
- [x] Convert text font sizes from typographic points into millimeter geometry.
- [x] Preserve physical size by default instead of always filling the page.
- [x] Add `none`, `downscale`, and `fit` placement modes.
- [x] Add horizontal and vertical alignment, scale, and XY offsets.
- [x] Reject NaN, infinity, malformed coordinates, excessive points, and excessive G-code commands.
- [x] Validate paper placement inside the machine envelope.
- [x] Validate all final XY points against paper and machine bounds.
- [x] Validate pen-up, pen-down, and park coordinates against machine bounds.
- [x] Add exact machine-space preview with paper, margins, ink paths, and dashed pen-up travel.
- [x] Add 10 mm square/cross/octagon and disconnected-stroke calibration geometry.
- [x] Add air-plot G-code that never lowers the pen.
- [x] Add non-moving `M115`, `M119`, `M114`, and `M503` preflight checks.
- [x] Add cancellable command-by-command sending with progress callback support.
- [x] Attempt an orderly `M400 → pen up → M400` stop after cancellation or Marlin error.
- [x] Add mocked Marlin tests for preflight, cancellation, and safe-stop behavior.
- [x] Add CLI and browser controls for physical layout and calibration generation.

## Remaining before Release 0.2 is complete

### Hardware validation

- [ ] Install and verify the final motor-capable 12 V supply.
- [ ] Verify X motor direction with a small positive and negative jog.
- [ ] Verify Y motor direction with a small positive and negative jog.
- [ ] Verify Z motor direction with the pen removed or safely clear.
- [ ] Verify X-, Y-, and Z-home direction one axis at a time.
- [ ] Establish the trusted machine origin after homing.
- [ ] Measure the real usable X/Y travel and update machine limits.
- [ ] Calibrate and record Z-up.
- [ ] Calibrate and record Z-down using scrap paper.
- [ ] Complete a 10 mm calibration air plot.
- [ ] Measure the physical square in X and Y.
- [ ] Complete a 10 mm pen-down calibration on scrap paper.
- [ ] Record any steps-per-unit correction and resulting measurements.

### Software job control

- [ ] Add a background job manager with one active hardware job at a time.
- [ ] Add job states: queued, running, paused, completed, cancelled, and failed.
- [ ] Add pause and resume behavior between acknowledged commands.
- [ ] Add browser cancel and emergency-stop controls.
- [ ] Add live command/stroke progress and Marlin response logs.
- [ ] Persist the last completed command and stroke for diagnosis.
- [ ] Add reconnect behavior after USB disconnect or controller reset.
- [ ] Distinguish orderly cancellation from `M112` emergency stop in the UI.

### Calibration and configuration

- [ ] Add a saved machine profile file rather than repeating CLI values.
- [ ] Add a guided pen-height calibration command.
- [ ] Add a guided page-origin calibration command.
- [ ] Add an optional machine-outline dry run before every new page placement.
- [ ] Add a calibration result record containing requested size, measured size, date, firmware hash, and correction.
- [ ] Add conservative validated speed presets for marker drawing.

### Tests and quality

- [ ] Add web API tests.
- [ ] Add SVG import and transform fixtures.
- [ ] Add disconnect, timeout, malformed response, and serial write-failure tests.
- [ ] Add tests proving no heater or extrusion command can be generated or sent by the normal job pipeline.
- [ ] Add golden calibration SVG and G-code fixtures.
- [ ] Add formatting, linting, type checking, and coverage reporting.
- [ ] Run CI on macOS and Linux.

## Required physical test order

Do not skip ahead because a later test appears convenient.

1. Power and polarity inspection.
2. Non-moving serial preflight.
3. Endstop report inspection with each switch manually activated.
4. Individual 1–2 mm axis jogs with pen removed.
5. Individual homing tests.
6. Establish and record machine coordinates.
7. Generate and inspect calibration SVG.
8. Send calibration as an air plot.
9. Measure motion direction and travel.
10. Calibrate Z-up and Z-down.
11. Run the same calibration with a pen on scrap paper.
12. Measure the physical result before drawing generated text.

## Release acceptance criteria

Release 0.2 is complete only when all of the following are true:

- a requested 10.0 mm square is measured within the selected tolerance in both axes;
- the preview uses the exact absolute XY coordinates sent to Marlin;
- air-plot mode cannot emit a pen-down command;
- every generated coordinate is finite and inside configured bounds;
- a communication failure stops new drawing commands and attempts pen-up;
- normal cancellation and emergency stop are separately available and documented;
- machine limits, page origin, and pen heights are stored in a reproducible profile;
- the physical validation results are recorded in `docs/HARDWARE.md`.

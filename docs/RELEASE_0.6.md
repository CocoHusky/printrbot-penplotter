# Release 0.6 — Motion Quality & Plot Optimization

Release 0.6 improves how already-created geometry is physically traversed. It does not create new artwork and does not replace Marlin motion planning. The Python application chooses stroke order, optional path cleanup, corner-aware feed requests, and publishes before/after motion metrics; Marlin remains responsible for real-time acceleration and stepper control.

## Release pipeline

```text
final artwork polylines
        ↓
optional RDP cleanup
        ↓
optional resampling
        ↓
optional endpoint-preserving smoothing
        ↓
route selection
 authored / nearest / two-opt
        ↓
optional near-endpoint joining
        ↓
exact preview + motion metrics
        ↓
corner-aware Marlin G-code
```

## Implemented

### Stroke routing

- [x] Preserve authored order by default.
- [x] Deterministic nearest-endpoint routing.
- [x] Optional stroke reversal to approach the nearest endpoint.
- [x] Deterministic open-path two-opt refinement after nearest-neighbor routing.
- [x] Keep calibration geometry out of route optimization.
- [x] Keep text/cursive authored order unless the user explicitly opts into another route mode.

### Pen-lift reduction

- [x] Measure pen-up travel before and after optimization.
- [x] Optional endpoint joining within a user-specified millimeter tolerance.
- [x] Joining is disabled by default because a non-zero gap becomes a short drawn connector.
- [x] Record pen-lift count in motion metrics.

### Path quality

- [x] True Ramer-Douglas-Peucker simplification in millimeters.
- [x] Fixed-spacing resampling for long line segments.
- [x] Conservative three-point smoothing that preserves the first and last point of each stroke.
- [x] All shape-changing operations are opt-in and deterministic.

### Corner-aware feed

- [x] Add `corner_feed_mm_min` to the pen profile.
- [x] Add configurable corner-angle threshold.
- [x] Detect whether a segment touches a corner at or below that threshold.
- [x] Emit the slower feed for segments entering/leaving a sharp corner.
- [x] Keep travel, normal draw, corner, and Z feed values independent.

### Motion metrics

Every optimized job records:

- [x] stroke count;
- [x] point count;
- [x] total pen-down distance;
- [x] total pen-up travel distance;
- [x] pen-lift count;
- [x] idealized estimated duration;
- [x] travel distance saved in millimeters;
- [x] travel distance saved as a percentage;
- [x] complete motion configuration.

The runtime estimate is intentionally approximate. Marlin acceleration, junction behavior, USB/UART pacing, and physical pen mechanics can make real plots slower.

### CLI controls

All normal render commands now accept:

```text
--motion-route authored|nearest|two_opt
--motion-reverse / --no-motion-reverse
--join-tolerance MM
--rdp-tolerance MM
--resample-spacing MM
--smooth-passes N
--two-opt-passes N
--corner-feed MM_PER_MIN
--corner-angle DEGREES
```

The safe default is no geometry modification beyond the established pipeline:

```text
--motion-route authored
--join-tolerance 0
--rdp-tolerance 0
--resample-spacing 0
--smooth-passes 0
```

## Examples

Optimize independent SVG artwork without changing its drawn shapes:

```bash
printrbot-plotter svg artwork.svg \
  --motion-route two_opt \
  --air-plot \
  --output out/artwork.gcode \
  --preview out/artwork.svg
```

Reduce dense traced-image points while optimizing travel:

```bash
printrbot-plotter image sketch.png \
  --trace-mode centerline \
  --motion-route two_opt \
  --rdp-tolerance 0.08 \
  --resample-spacing 1.0 \
  --air-plot
```

Use conservative smoothing on a noisy trace:

```bash
printrbot-plotter handwriting note.jpg \
  --smooth-passes 1 \
  --rdp-tolerance 0.05 \
  --air-plot
```

Join tiny gaps only after visually checking the preview:

```bash
printrbot-plotter svg cleaned.svg \
  --motion-route two_opt \
  --join-tolerance 0.25 \
  --air-plot
```

For language output, keep `--motion-route authored` unless intentionally testing a font whose strokes are independent. Global route optimization can scramble the intended writing sequence even when the final ink geometry looks similar.

## Safety rules

- Route optimization never generates heaters, extrusion, homing, or direct hardware commands.
- Calibration jobs bypass Release 0.6 motion transforms.
- Authored order remains the default.
- Joining is disabled by default because it adds ink between close endpoints.
- Smoothing, RDP, and resampling are disabled by default because they alter point geometry.
- The exact post-optimization geometry is used by both preview and G-code.
- Corner-feed values are validated and cannot exceed the normal drawing feed.
- Release 0.2 physical machine validation remains mandatory before pen-down testing.
- Release 0.4 electrical validation remains mandatory for ESP32 UART use.

## Release acceptance criteria

Release 0.6 is accepted when:

- nearest and two-opt routing are deterministic and never increase route cost in their tests;
- optional reversal preserves each stroke's geometry;
- endpoint joining only occurs within the configured tolerance;
- RDP, resampling, and smoothing preserve stroke endpoints as designed;
- motion metrics are present in every normal rendered job;
- corner-aware feeds appear in G-code at tested sharp turns;
- calibration output remains unchanged by motion settings;
- existing text, raster, USB, and ESP32 tests continue to pass.

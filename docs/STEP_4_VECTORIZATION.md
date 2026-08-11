# Historical Step 4 — High-quality vectorization and path cleanup

> Historical design note. The supported image workflow is Studio 2; this file
> records the original cleanup design and is not a separate user flow.

Step 4 adds deterministic cleanup between raw raster tracing and machine placement. It improves jagged pixel-derived paths while preserving the project's single-geometry-source rule. It does not add drawing styles, hatching, semantic recognition, route optimization, or machine commands.

## Pipeline boundary

```text
Step 2 preprocessing
  -> Step 3 feature understanding
  -> raw centerline / contour trace
  -> Step 4 vector cleanup (optional, explicit)
  -> shared page placement
  -> existing motion optimization
  -> exact preview
  -> validated G-code
```

`vector_cleanup.py` owns source-coordinate trace cleanup. It never emits G-code and never performs global artwork route ordering.

## Operations

`VectorCleanupConfig` supports:

- consecutive micro-segment removal;
- minimum open-stroke length pruning;
- tiny closed-loop area pruning;
- corner-aware RDP simplification;
- endpoint-preserving moving-average smoothing;
- closed/open-safe Chaikin smoothing;
- approximate duplicate-stroke suppression, including reversed traversal;
- opt-in endpoint joining with both distance and tangent-angle gates;
- bounded input/output stroke and point counts.

Every shape-changing operation is explicit. The default configuration is an exact no-op, consistent with the repository guardrail that smoothing, simplification, joining, and pruning must not silently create or remove ink.

## Named cleanup presets

The module provides deterministic presets intended for later style and Studio layers:

- `raw` — exact no-op;
- `clean` — micro-segment, short-stroke, tiny-loop, mild simplification, and duplicate cleanup;
- `smooth` — conservative smoothing plus short-gap joining for smoother line drawings;
- `flowing` — stronger curve smoothing and gap joining for intentionally continuous artwork.

These are cleanup presets, not artistic styles. Step 5 will build actual outline/sketch style choices using the analysis and cleanup stages.

## Corner preservation

Simplification and smoothing inspect local interior angle. Points at or below `preserve_corner_deg` are treated as intentional corners and are retained rather than averaged away. Closed contours are anchored deterministically before simplification so repeated runs produce identical geometry.

## Duplicate suppression

When enabled, candidate strokes are length-gated and deterministically resampled. Mean point distance is compared in both forward and reversed directions. A duplicate is removed only when the configured source-pixel tolerance is met.

## Gap joining

Joining is disabled by default because a gap converted into a line becomes real ink. When enabled, Step 4 considers endpoint orientations deterministically and requires:

- endpoint separation within `join_distance_px`;
- tangent direction change within `join_angle_deg`;
- both strokes to be open paths.

Metadata records join count and total bridge length.

## Raster adapter integration

`inputs.raster_to_polylines_with_metadata()` and `raster_to_polylines()` now accept an optional keyword-only `cleanup=VectorCleanupConfig(...)` argument. When cleanup is supplied, the cleaned polylines become the geometry returned to the shared placement/preview/G-code pipeline. When omitted, legacy raster behavior remains unchanged.

Example:

```python
from printrbot_penplotter.inputs import raster_to_polylines_with_metadata
from printrbot_penplotter.vector_cleanup import VectorCleanupConfig

polylines, metadata = raster_to_polylines_with_metadata(
    "drawing.png",
    cleanup=VectorCleanupConfig.for_quality("smooth"),
)
```

## Metadata

Every cleanup run records `printrbot-vector-cleanup/v1` plus:

- input/output strokes and points;
- input/output path length;
- removed micro-points;
- removed short strokes;
- removed tiny loops;
- duplicate removals;
- joins and bridge length;
- all cleanup thresholds and smoothing settings.

## CI acceptance

`.github/workflows/vector-cleanup.yml` runs on pull requests and pushes to `main` using Python 3.11 and 3.13. It checks:

- compilation of Steps 2–4 modules;
- focused Step 4 vector-cleanup tests;
- Step 3 image-understanding regressions;
- Step 2 preprocessing, raster, and Studio regressions;
- deterministic trace -> cleanup smoke behavior.

The existing `Test`, `Safety Contract`, `Image Preprocessing`, and `Image Understanding` workflows also run on Step 4 changes. Step 4 must not merge unless Steps 1–3 remain green.

## Explicitly deferred

Step 4 does not implement:

- Clean Outline / Detailed Outline / Continuous Contour art styles;
- pet/portrait interpretation;
- hatching, crosshatching, stippling, engraving, fur, or hair strokes;
- semantic subject recognition;
- automatic style selection;
- physical pen-tip-aware minimum-feature filtering;
- Studio 2.0 advanced controls.

Those remain Steps 5–9 of the roadmap.

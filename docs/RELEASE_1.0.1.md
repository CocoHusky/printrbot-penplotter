# Release 1.0.1 — Centerline Path Cleanup

Release 1.0.1 is a focused quality patch for typed centerline lettering.

## Changes

- Resamples transformed centerline strokes to even path spacing.
- Smooths repeated small deviations on stable straight runs.
- Preserves endpoints, stroke breaks, dots, and sharp bends.
- Keeps the blue dashed pen-up travel preview unchanged.
- Covers the cleanup with tests for jitter reduction and bend preservation.

The cleanup is intentionally conservative: it does not flatten curves or
replace authored glyph geometry with an outline trace.

## Verification

- Full automated test suite passes.
- Live website tested with `r t y k x 4` and a multiline birthday note.
- Local `main` and GitHub `origin/main` remain synchronized.

# Release 1.0.0 — Usable Text-to-Plotter Workflow

Release 1.0.0 is the first complete public workflow for preparing and reviewing
text, images, and machine-safe pen-plotter jobs locally.

## What is included

- Clean Hershey Script single-line centerlines are the default handwriting-style
  lettering in the Write notes page.
- Robot and Hershey centerline fonts draw each mark once; conventional outline
  fonts remain explicitly experimental.
- Text wraps to a physical width and previews the same machine-space paths used
  for G-code.
- The neural Graves trajectory backend remains available behind an explicit
  experimental toggle and never silently replaces the clean default.
- The UI keeps experimental controls collapsed so the main writing workflow is
  visible without unnecessary settings.
- Preview, placement, travel moves, homing, pen safety, G-code export, and the
  ESP32 bridge continue to use the shared geometry and validation pipeline.

## Verification

- Full automated suite: 226 tests passed.
- Live website verification covered handwriting input, multiline text, wrapping,
  preview generation, and the experimental neural control.
- Local `main` and GitHub `origin/main` are kept synchronized for this release.

## Known limits

- The neural model is experimental and may be less legible than authored
  centerline lettering.
- Physical plots still require an air plot, correct pen placement, clear travel,
  and an operator at the machine.
- Installed outline fonts are not guaranteed to produce good centerlines; use
  authored stroke fonts for reliable pen lettering.

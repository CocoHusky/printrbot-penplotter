# Release 1.0.2 — Graves Controls and Mode Isolation

Release 1.0.2 fixes the experimental Graves workflow without presenting it as
a reliable handwriting font.

## Changes

- Graves style, sampling bias, variation seed, and slant are now passed through
  to the worker and reflected in metadata.
- Robot mode forcibly uses the robot centerline font and disables Graves.
- Neural controls are hidden outside handwriting mode.
- The neural control is labeled as sampling bias rather than neatness because
  higher bias does not guarantee recognizable letterforms.
- Added regression coverage for neural parameters and robot-mode isolation.

Live testing confirmed that Graves changes with its parameters but remains
experimental and can produce malformed letterforms. Hershey Script remains the
recommended handwriting mode.

# Release 1.0.4 — Handwriting Controls and Orientation

Release 1.0.4 makes the handwriting workflow clearer and prevents stale or
misoriented output from being mistaken for a parameter failure.

- Selecting handwriting chooses Graves automatically when the neural worker is
  installed; there is no redundant checkbox gate. The controls are labeled as
  a handwriting model rather than an unexplained experimental switch.
- Style, sampling bias, variation seed, and slant remain editable and are
  passed through to generation or post-processing as appropriate.
- Changing any lettering, layout, spacing, page, plot, or handwriting control
  clears the previous preview and disables G-code download until a new render
  is generated.
- The Graves worker now declares its reference renderer's Cartesian Y-up
  coordinates, preventing the client from flipping the generated letters a
  second time.
- Robot mode continues to hide and ignore neural handwriting controls.

Graves is stochastic trajectory generation, not a guaranteed legible font.

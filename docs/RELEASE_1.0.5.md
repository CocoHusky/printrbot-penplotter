# Release 1.0.5 — Direct Handwriting Selection

Selecting **Single-line handwriting** now directly selects the Graves neural
centerline backend when the worker is installed.

- Removed the redundant **Use Graves neural handwriting** checkbox.
- Kept the four meaningful Graves controls visible: model style, sampling
  bias, variation seed, and slant.
- Robot mode remains independent and never invokes the neural handwriting
  backend.
- Updated UI, README, and neural-backend documentation.

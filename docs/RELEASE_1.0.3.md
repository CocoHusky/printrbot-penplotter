# Release 1.0.3 — Handwriting Mode Isolation

Release 1.0.3 removes an ambiguity in the Write notes controls.

- Installed outline-font conversion is hidden and disabled in handwriting mode.
- Handwriting always uses the authored Hershey Script centerline path.
- Robot mode exposes only its intended robot/outline controls and cannot invoke
  Graves through the API.
- Added UI and API regression coverage for the mode boundaries.

Outline conversion remains an experiment for non-handwriting lettering. It is
not required for, or applied to, normal handwriting.

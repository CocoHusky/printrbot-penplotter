# Physical routing performance policy

Studio and photo-derived artwork can contain hundreds or thousands of independent strokes. The generic `two_opt_stroke_order()` implementation is deterministic but intentionally exhaustive and is not suitable for large interactive previews.

Physical plotting therefore uses a bounded routing policy:

- `quick`: nearest-neighbor routing
- `balanced`: nearest-neighbor routing
- `best`: two-opt only for small jobs; large jobs fall back to nearest-neighbor

This changes only stroke order/direction after artwork generation. It does not alter the hardware safety envelope, homing contract, pen-Z behavior, or G-code validation.

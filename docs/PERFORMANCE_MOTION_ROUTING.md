# Physical routing performance policy

Studio and photo-derived artwork can contain hundreds or thousands of independent strokes. The generic `two_opt_stroke_order()` implementation is deterministic but intentionally exhaustive and is not suitable for large interactive previews.

Physical plotting therefore uses a bounded routing policy when `route_mode="two_opt"` is requested:

- `quick`: nearest-neighbor routing
- `balanced`: nearest-neighbor routing
- `best`: two-opt only for small jobs; jobs above `max_two_opt_strokes` fall back to nearest-neighbor

The requested and effective routing modes are recorded in physical-plot metadata.

This changes only stroke order/direction after artwork generation. It does not alter the hardware safety envelope, homing contract, pen-Z behavior, or G-code validation.

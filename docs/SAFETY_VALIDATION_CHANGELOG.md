# Safety validation change note

Reason for this guard: during first real pen plotting, a generated job without homing trusted stale logical coordinates and drove an axis to its mechanical end. Individual X, Y, and Z homing were then physically tested successfully over the ESP32 bridge.

This change therefore makes stored XY hardware jobs self-contained: same-job homing is required, the pen must be raised before XY motion, and the job must finish pen-up with X/Y re-homed. The validator remains permissive for home-only diagnostic jobs.

The change does not alter the confirmed axis home directions: X homes to X-min, Y homes to Y-max, and Z homes to Z-min. End-of-job homing intentionally uses `G28 X Y` only so Z stays raised rather than moving back toward Z-min after drawing.

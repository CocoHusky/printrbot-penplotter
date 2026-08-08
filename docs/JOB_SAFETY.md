# Guarded hardware job envelope

Real-hardware jobs use a self-contained start/end envelope so a stored G-code file does not depend on stale Marlin coordinates from an earlier session.

## Standard plotting sequence

A normal Wi-Fi plotting job that contains XY motion must establish its own coordinate system and leave the machine in a known state.

```gcode
G21                 ; millimeters
G90                 ; absolute coordinates
M400
G28                 ; home X/Y/Z before any plotting motion
M400
G0 Z5 F300          ; raise pen before first XY move

; ... XY travel and drawing ...
; X+Y together is valid and produces diagonal motion.
; Z moves remain separate from XY moves.

M400
G0 Z5 F300          ; final pen up
M400
G28 X Y             ; re-home planar axes only
M400
```

The end sequence intentionally does **not** home Z. On this Printrbot, Z homes toward the Z-min sensor/paper side, so end-of-job Z homing is rejected after plotting motion. The pen is raised first and only X/Y are re-homed.

## Validator behavior

Hardware G-code is validated twice:

1. `printrbot-bridge upload` performs host-side sequence validation before sending the file over the network.
2. ESP32 firmware validates the complete stored file before it can enter the `ready` state.

For any job that performs XY motion, the validators reject:

- movement before `G21` millimeter mode and `G90` absolute positioning;
- X/Y/Z movement without same-job homing;
- first XY movement before the pen has been raised to the configured safe Z;
- X, Y, or Z coordinates outside configured machine limits;
- feed values above configured machine maxima;
- simultaneous XY and Z movement;
- jobs that finish below safe pen-up Z;
- jobs that do not re-home X/Y after the final XY movement;
- Z homing after plotting motion;
- relative-position, coordinate-reset, arc, heater, extrusion, tool-change, embedded emergency-stop, and other unsupported commands;
- status-query commands embedded inside stored motion jobs.

Diagonal planar movement is explicitly allowed. `G1 X30 Y30` is normal coordinated XY motion and is not treated as simultaneous XY/Z motion.

## Diagnostics

Home-only diagnostic jobs remain valid, for example:

```gcode
G28 X
M400
```

This keeps individual axis validation possible without requiring a full plotting envelope.

## Studio behavior

The Image & Handwriting Studio exposes **Home all axes before plot** and enables it by default. When enabled, generated G-code includes the full start home and the safe end sequence above. A Studio job with homing deliberately disabled can still be generated for offline/non-bridge inspection, but `printrbot-bridge upload` and the updated ESP32 validator will refuse XY hardware motion that lacks the guarded envelope.

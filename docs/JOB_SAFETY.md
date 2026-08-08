# Guarded hardware job envelope

Real-hardware jobs use one self-contained start/end contract so a stored G-code file never depends on stale Marlin coordinates from an earlier session.

## Standard plotting sequence

Any normal hardware job that contains XY motion must establish its own coordinate system and leave the machine in a known state.

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

## Generation versus hardware execution

Rendering and previewing remain hardware-independent. A user may deliberately generate a no-home file for offline inspection, geometry debugging, or other non-hardware work. That file is **not** a runnable XY hardware job.

The Image & Handwriting Studio exposes **Home all axes before plot** and enables it by default. CLI users generating a hardware-bound job must include `--home`. The hardware execution boundaries do not rely on the user remembering this: they reject XY jobs that do not contain the complete guarded envelope.

This keeps homing visible and configurable while making stale logical coordinates impossible to accept at a hardware boundary.

## Validator behavior

Hardware G-code is guarded at every execution path:

1. `printrbot-bridge upload` performs host-side complete-job validation before sending a file over the network.
2. Direct USB `MarlinSender.send_gcode()` / `printrbot-plotter send` performs the same complete-job validation before writing the first byte to Marlin.
3. ESP32 firmware validates the complete stored file again before it can enter the `ready` state.

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

## CI contract

`.github/workflows/safety-contract.yml` is the regression gate for this contract. On every pull request and push to `main` it:

- runs the full Python test suite on Python 3.11 and 3.13;
- generates and validates a canonical homed hardware job;
- verifies that an otherwise valid no-home XY job is rejected for hardware execution;
- runs the ESP32 native protocol tests;
- compiles the ESP32-C3 firmware.

The existing general Python and ESP32 workflows remain useful independent checks. A safety-contract change is not considered complete until the dedicated contract workflow and the existing repository checks pass.

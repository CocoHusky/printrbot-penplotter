# Printrboard Marlin firmware

This directory tracks the project-specific Marlin settings and rebuild workflow for the Printrboard Rev F4 / AT90USB1286 used by the pen plotter.

The full Marlin source tree is not vendored here. Build against upstream **Marlin 2.1.2.8** using PlatformIO environment `at90usb1286_dfu`.

## Confirmed project settings

The currently intended configuration is:

```c
#define EXTRUDERS 0

#define SERIAL_PORT 0
#define BAUDRATE 115200
#define SERIAL_PORT_2 1
#define BAUDRATE_2 115200

#define INVERT_X_DIR true
#define INVERT_Y_DIR true
#define INVERT_Z_DIR true

#define X_HOME_DIR -1
#define Y_HOME_DIR 1
#define Z_HOME_DIR -1
```

Home switches on this machine are:

- X: `x_min`
- Y: `y_max`
- Z: `z_min`

Recovered motion settings are documented in `docs/HARDWARE.md`.

## UART requirement

This project uses native USB as Marlin serial port 0 and hardware UART1 as secondary host serial port 1 for the ESP32 bridge. The local working Marlin tree also contains an AT90USB1286 HAL adjustment so the secondary serial port resolves to the Teensy/AVR `Serial1` implementation.

That HAL change must be preserved when recreating the firmware from a clean Marlin 2.1.2.8 tree. Until the exact local diff is committed here, the known-good local tree remains the authoritative build source for that patch.

## Apply the tracked configuration values

From this repository:

```bash
python3 firmware/marlin/apply_project_config.py \
  ~/Desktop/printrboard-marlin-2.1.2.8
```

The script edits `Marlin/Configuration.h` and verifies the values it controls.

## Build

```bash
firmware/marlin/build_printrboard.sh \
  ~/Desktop/printrboard-marlin-2.1.2.8
```

The script builds:

```text
pio run -e at90usb1286_dfu
```

and copies the resulting HEX to the Marlin tree's `build-artifacts/` directory with a descriptive filename and SHA-256.

## Physical validation status

As of 2026-08-07:

- native USB `M115` works;
- ESP32 UART loopback works;
- ESP32 → level shifter → Printrboard UART1 → ESP32 communication works and returns Marlin capability lines;
- Y homing direction was observed correct;
- the previous build drove X and Z in the wrong homing direction;
- X and Z inversion were changed from `false` to `true` and a new build completed successfully;
- the new X/Z direction build has **not yet been flashed and physically revalidated**.

Do not run a full `G28` until X, Y, and Z have each been homed individually and observed moving toward the correct switch.

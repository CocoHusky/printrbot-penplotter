# Hardware, Firmware, Wiring, and Evidence

**Document status:** initial verified build record, 2026-08-06

This document records the physical system, confirmed firmware state, planned ESP32 bridge, wiring decisions, and the source for each important claim. It is intentionally separate from the software-focused README.

## 1. System architecture

```text
Phone / computer browser
          │ Wi-Fi or local network
          ▼
ESP32-C3-DevKitC-02
          │ UART1, 115200 baud
          │ 3.3 V ↔ 5 V level translation
          ▼
Printrboard Rev F4 / AT90USB1286
          │ Marlin motion planning
          ▼
X/Y/Z steppers + endstops + pen holder
```

The Printrboard remains responsible for deterministic stepper motion and safety-relevant machine state. The ESP32 is a web/network host and serial bridge. It does not directly pulse stepper drivers.

## 2. Confirmed hardware inventory

| Component | Confirmed state | Reason used |
|---|---|---|
| Printrboard Rev F4 | Installed and communicating over native USB | Existing motion controller with integrated stepper drivers and broken-out UART1 |
| AT90USB1286 | MCU on the Printrboard | Native USB, 128 KB flash, existing DFU workflow |
| ESP32-C3-DevKitC-02 v1.1 | Available | Wi-Fi web UI, UART bridge, onboard RGB LED for diagnostics |
| Three-axis pen mechanism | Existing X/Y/Z motion | X/Y draw; Z lifts and lowers marker |
| Endstops | X minimum, Y maximum, Z minimum | All three were physically triggered and verified through `M119` |
| UART level translator | Required before UART connection | Printrboard logic is 5 V; ESP32-C3 GPIO logic is 3.3 V |
| 12 V supply | Required for final motor operation | Powers Printrboard logic regulator and motors |

## 3. Confirmed Printrboard firmware state

The active firmware is a heaterless Marlin 2.1.2.8 configuration built for `BOARD_PRINTRBOARD_REVF` with:

```c
#define EXTRUDERS 0
#define SERIAL_PORT 0
#define BAUDRATE 115200
#define SERIAL_PORT_2 1
#define BAUDRATE_2 115200
```

The secondary serial port is intended for the ESP32 bridge. Marlin documents `SERIAL_PORT_2` as an additional host communication port and provides a separate baud-rate setting for it:

- Marlin serial settings: https://marlinfw.org/docs/setting/serial.html
- Marlin configuration reference: https://marlinfw.org/docs/configuration/configuration.html

### Stored motion settings recovered from the original machine

```text
M92  X80 Y80 Z2020
M203 X125 Y125 Z5
M201 X2000 Y2000 Z30
M204 S3000 T3000
M205 S0 T0 B20000 X20 Z0.4 E5
M206 X0 Y0 Z0
```

Configured axis limits are currently `0–152.4 mm` for X, Y, and Z. The software defaults to a 152.4 × 152.4 mm page but applies margins before generating motion.

### Endstop behavior verified on this machine

| Axis | Marlin input | Home direction | Released state | Triggered state |
|---|---|---:|---|---|
| X | `x_min` | negative | open | TRIGGERED |
| Y | `y_max` | positive | open | TRIGGERED |
| Z | `z_min` | negative | open/no metal | TRIGGERED/metal detected |

Do not run a full `G28` until motor directions, physical travel direction, and the pen mount have been checked with small individual jogs.

## 4. Printrboard EXP1 UART and power pins

The Rev F schematic maps these pins on the 2×7 `EXP1` header:

| EXP1 pin | Signal | Use in this project |
|---:|---|---|
| 5 | `PD2 / RX1` | Receives ESP32 UART TX |
| 7 | `PD3 / TX1` | Sends Marlin responses to ESP32 UART RX |
| 13 | `+5V` | ESP32 5 V input and level-shifter high-side supply/reference |
| 14 | `GND` | Common ground |

Top-view numbering when the square PCB pad is pin 1:

```text
1    3    5    7    9    11   13
2    4    6    8    10   12   14
          RX1  TX1             GND

                              pin 13 = +5 V above pin 14
```

### Evidence

- RepRap Printrboard page: https://reprap.org/wiki/Printrboard
  - Supports: Rev F4 identity, AT90USB1286, native USB, onboard SD, dedicated I²C, broken-out UART1, 5 V endstop supply, board power behavior, and DFU information.
  - Trust level: primary community hardware documentation linked to the original design files.
- Original Eagle schematic: https://github.com/lwalkera/Printrboard/blob/master/Printrboard.sch
  - Supports: `EXP1 pin 7 → PD3-TX1`, `EXP1 pin 5 → PD2-RX1`, `EXP1 pin 13 → +5V`, and `EXP1 pin 14 → GND`.
  - Trust level: original schematic source; exact net mapping is schematic-derived.

## 5. ESP32-C3 header pins used

On the ESP32-C3-DevKitC-02 J1 header:

| ESP32 header signal | Official J1 position | Use |
|---|---:|---|
| GPIO6 | J1 pin 8 | UART1 RX from Printrboard TX1 |
| GPIO7 | J1 pin 9 | UART1 TX to Printrboard RX1 |
| GND | J1 pin 10 or another G pin | Common ground |
| 3V3 | J1 pin 2 or 3 | Low-side reference for level translator |
| 5V | J1 pin 13 or 14 | Board power input from regulated 5 V |
| GPIO8 | J1 pin 11 | Onboard addressable RGB LED |

### Evidence

- Espressif ESP32-C3-DevKitC-02 user guide: https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32c3/esp32-c3-devkitc-02/user_guide.html
  - Supports: exact J1 pin table, GPIO6/GPIO7 positions, onboard RGB LED on GPIO8, Micro-USB programming, and the documented power-input methods.
  - Trust level: official board vendor documentation.
- PlatformIO board page: https://docs.platformio.org/en/stable/boards/espressif32/esp32-c3-devkitc-02.html
  - Supports: PlatformIO board identifier `esp32-c3-devkitc-02`, MCU, flash, RAM, and upload protocol support.
  - Trust level: official PlatformIO documentation.

## 6. Final UART wiring

**Power everything off before adding or moving wires.**

```text
POWER
Printrboard EXP1 pin 13 (+5 V) ───────────────► ESP32 5V
Printrboard EXP1 pin 14 (GND) ────────────────► ESP32 GND
ESP32 3V3 ─────────────────────────────────────► level shifter LV/VCCA
Printrboard +5 V ──────────────────────────────► level shifter HV/VCCB
Common GND ────────────────────────────────────► level shifter GND

DATA — crossed by function
Printrboard EXP1 pin 7, TX1 (5 V)
    ─► high-side input ─► low-side output ─► ESP32 GPIO6, RX

ESP32 GPIO7, TX (3.3 V)
    ─► low-side input ─► high-side output ─► Printrboard EXP1 pin 5, RX1
```

The 5 V wire powers the ESP32 development board through its onboard regulator. It does **not** make the ESP32 GPIO pins 5 V tolerant.

### Recommended translator

A two-channel fixed-direction push-pull translator with opposite channel directions is the cleanest UART solution. TI's TXU0202 is designed for this topology, accepts 1.1–5.5 V rails, and is rated far beyond the planned 115200-baud link:

- https://www.ti.com/product/TXU0202

A common BSS138 four-channel bidirectional module may work for short bench wiring at 115200 baud, but it is fundamentally an auto-bidirectional/open-drain-style circuit. Treat it as a bench option to validate with an oscilloscope or repeated serial testing, not the preferred final design.

## 7. Why UART is used instead of SD or I²C

UART is Marlin's supported live host interface. It carries commands, `ok` acknowledgements, errors, status reports, pause/stop commands, and SD-file operations through one full-duplex link. Marlin explicitly supports a secondary serial host port.

The onboard SD card is storage, not a safe two-controller command bus. Allowing both the AT90USB1286 and ESP32 to drive the same SPI card interface would require bus ownership, arbitration, and corruption protection, while still failing to provide a complete live-status channel.

The dedicated I²C header is suitable for peripherals, but Marlin does not expose its normal host G-code stream as a drop-in I²C transport. Using it would require a custom protocol and custom firmware on both sides.

Sources:

- Printrboard features and expansion buses: https://reprap.org/wiki/Printrboard
- Marlin secondary serial host setting: https://marlinfw.org/docs/setting/serial.html
- Marlin G0/G1 motion behavior: https://marlinfw.org/docs/gcode/G000-G001.html

## 8. Power plan

### Bench development

- Program and test the ESP32 from its Micro-USB port with the Printrboard-to-ESP32 5 V wire disconnected.
- Operate the Printrboard from its own regulated 12 V source.
- Connect grounds before UART data.
- Do not connect both USB power and external 5 V to the ESP32 simultaneously; Espressif documents its USB, 5 V header, and 3.3 V header supply methods as mutually exclusive.

### Final installation

Preferred final arrangement:

```text
regulated 12 V supply
        ├──► Printrboard power input
        └──► 12 V to 5 V buck converter, ≥1 A
                    └──► ESP32 5V + translator high-side rail
```

The Printrboard 5 V rail can power the ESP32 for early testing, but a dedicated buck converter gives the Wi-Fi board cleaner current headroom and separates its transient load from the legacy controller regulator.

## 9. Firmware artifacts and backups

Known local artifacts from the restoration session:

```text
Plotter-safe Marlin:
~/Desktop/printrboard-marlin-2.1.2.8/build-artifacts/
  printrbot-revf4-plotter-marlin-2.1.2.8.hex

UART-enabled Marlin:
~/Desktop/printrboard-marlin-2.1.2.8/build-artifacts/
  printrbot-revf4-plotter-wifi-marlin-2.1.2.8.hex

Recovered settings text backup:
~/Desktop/printrboard-backup/original-settings.txt
```

Recorded SHA-256 values:

```text
plotter-safe initial build:
223e15f723b34a0ee2fb34ceafd25f6e954b1ecbb91ba1b0288f4e5970954f7c

UART-enabled build:
362c37f42debd5cdc0aaee239a5c411c9d9529163f9f942aefa04ef5d7843473
```

The text settings backup is not a binary dump of the original firmware.

## 10. Validation checklist before the first drawing

- [ ] Proper 12 V motor-capable supply installed with polarity verified.
- [ ] ESP32 powered through exactly one approved method.
- [ ] Common ground confirmed.
- [ ] Level translator installed and rails measured before data wires are attached.
- [ ] Printrboard TX1 reaches ESP32 GPIO6 through 5 V→3.3 V conversion.
- [ ] ESP32 GPIO7 reaches Printrboard RX1 through 3.3 V→5 V conversion.
- [ ] `M115`, `M119`, `M503`, and `M114` work through the intended transport.
- [ ] Each axis is jogged a few millimeters individually with the pen removed.
- [ ] Home direction is verified one axis at a time.
- [ ] Z-up and Z-down values are calibrated above scrap paper.
- [ ] First generated job is reviewed in SVG and run as a pen-up air plot.
- [ ] Physical emergency power removal is reachable during the first motion tests.

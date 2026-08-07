# ESP32-C3 Bridge Hardware Record

**Status:** design documented; final level-shifter wiring and end-to-end UART validation remain physically incomplete.

This document records the hardware boundary used by Release 0.4. The main system inventory remains in [`HARDWARE.md`](HARDWARE.md).

## Architecture

```text
phone / computer
       │ Wi-Fi
       ▼
ESP32-C3-DevKitC-02
       │ 3.3 V UART
       ▼
proper 3.3 V ↔ 5 V translator
       │ 5 V UART
       ▼
Printrboard Rev F4 / AT90USB1286
       │ Marlin motion planning
       ▼
X/Y/Z steppers and pen
```

The ESP32 is a host bridge. The Printrboard remains the real-time motion controller.

## Confirmed ESP32 board

```text
Board: ESP32-C3-DevKitC-02 v1.1
PlatformIO board ID: esp32-c3-devkitc-02
MCU: ESP32-C3
Flash: 4 MB
UART bridge RX: GPIO6
UART bridge TX: GPIO7
Onboard RGB LED: GPIO8
```

### Source

Espressif user guide:

https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32c3/esp32-c3-devkitc-02/user_guide.html

Supports the board header pin table, GPIO6/GPIO7 locations, onboard RGB LED, USB programming, and documented power methods. This is the official board-vendor source.

PlatformIO board page:

https://docs.platformio.org/en/stable/boards/espressif32/esp32-c3-devkitc-02.html

Supports the exact PlatformIO board identifier and board resources. This is the official build-system documentation.

## Printrboard EXP1 connections

```text
EXP1 pin 5   PD2 / RX1   receives ESP32 UART TX
EXP1 pin 7   PD3 / TX1   sends Marlin UART data
EXP1 pin 13  +5 V        power/reference
EXP1 pin 14  GND         common ground
```

Top view when the square PCB pad is pin 1:

```text
1    3    5    7    9    11   13
2    4    6    8    10   12   14
          RX1  TX1             GND
```

### Source

Original Printrboard Eagle schematic:

https://github.com/lwalkera/Printrboard/blob/master/Printrboard.sch

Supports the exact EXP1-to-MCU net mapping. This is the original schematic source and the mapping is schematic-derived.

RepRap Printrboard documentation:

https://reprap.org/wiki/Printrboard

Supports the board family, AT90USB1286, native USB, expansion interfaces, and firmware/programming context. This is the original community hardware documentation.

## Required translated UART wiring

```text
Printrboard EXP1 pin 7, TX1
    → translator 5 V-side input
    → translator 3.3 V-side output
    → ESP32 GPIO6, RX

ESP32 GPIO7, TX
    → translator 3.3 V-side input
    → translator 5 V-side output
    → Printrboard EXP1 pin 5, RX1

Printrboard EXP1 pin 14 GND
    ↔ translator GND
    ↔ ESP32 GND

Printrboard regulated +5 V
    → translator high-side supply/reference

ESP32 3V3
    → translator low-side supply/reference
```

The signal directions are crossed by function: printer TX goes to ESP32 RX, and ESP32 TX goes to printer RX.

## Why level translation is mandatory

The ESP32-C3 GPIO domain is a 3.3 V domain. Supplying the Printrboard's 5 V UART TX directly to GPIO6 is outside that domain. The ESP32 development board can accept regulated 5 V at its power input because an onboard regulator supplies the module, but that does not make GPIO6 or GPIO7 5 V tolerant.

Use a translator intended for push-pull UART signals. A fixed-direction two-channel device with opposite channel directions is preferred. A common BSS138 auto-bidirectional module may work at 115200 baud on short bench wiring, but it should be treated as a bench option to validate rather than the ideal final interface.

Example preferred topology:

https://www.ti.com/product/TXU0202

This source supports a dual-channel, dual-supply translator designed with opposite directions suitable for UART. It is a semiconductor-vendor source.

## Power methods

### USB development

```text
ESP32 powered from USB
external ESP32 5 V disconnected
Printrboard powered separately
common ground added only when translated UART testing begins
```

### Final installation

Preferred arrangement:

```text
regulated 12 V motor supply
       ├── Printrboard
       └── 12 V → regulated 5 V buck, at least 1 A
                    ├── ESP32 5V pin
                    └── translator high-side rail/reference

ESP32 3V3 pin → translator low-side rail/reference
all grounds common
```

A dedicated buck converter gives the Wi-Fi board current headroom and avoids placing its transmit-current spikes on the legacy Printrboard regulator.

Espressif documents USB, 5 V header, and 3.3 V header power as alternative supply methods. Do not power the development board through USB and the 5 V header simultaneously during normal development.

## Firmware electrical assumptions

Release 0.4 currently compiles these values into `firmware/esp32/include/bridge_config.h`:

```text
UART index: 1
baud: 115200
RX: GPIO6
TX: GPIO7
response timeout: 15 seconds
safe Z-up: 5.000 mm
safe Z feed: 300 mm/min
```

The safe Z-up value is not yet physically calibrated. It must be changed to the measured machine profile before relying on orderly cancellation.

Marlin is configured with a secondary serial host port at 115200 baud. Marlin serial settings documentation:

https://marlinfw.org/docs/setting/serial.html

## Physical validation checklist

- [ ] Power off both boards.
- [ ] Confirm translator model and pin direction from its datasheet.
- [ ] Confirm no direct Printrboard TX-to-ESP32 GPIO connection exists.
- [ ] Measure translator high-side rail near 5 V.
- [ ] Measure translator low-side rail near 3.3 V.
- [ ] Confirm continuity of common ground.
- [ ] Power ESP32 through exactly one method.
- [ ] Connect translated Printrboard TX1 to ESP32 GPIO6 RX.
- [ ] Connect translated ESP32 GPIO7 TX to Printrboard RX1.
- [ ] Boot with motors disabled or safely clear.
- [ ] Verify repeated `M115` responses.
- [ ] Verify repeated `M119`, `M114`, and `M503` responses.
- [ ] Check for corrupted characters or dropped acknowledgements.
- [ ] Run a query-only uploaded file.
- [ ] Run the Release 0.2 air-plot calibration file.
- [ ] Test pause/resume.
- [ ] Test orderly cancellation and observe the Z-up sequence.
- [ ] Test emergency stop under controlled conditions.
- [ ] Record final translator, rail measurements, power source, cable length, and observed UART reliability here.

## Not yet verified

The repository does not yet contain physical evidence for:

- final translator installation;
- measured logic levels under load;
- error-free sustained 115200-baud UART operation;
- Wi-Fi range in the installed machine;
- 5 V rail behavior during simultaneous Wi-Fi and stepper activity;
- physically safe Z-up during cancellation;
- controller reset behavior after browser-triggered `M112`.

Do not mark Release 0.4 complete until those results are recorded.

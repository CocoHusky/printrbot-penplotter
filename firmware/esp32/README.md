# ESP32-C3 Wi-Fi Bridge

This firmware turns the ESP32-C3-DevKitC-02 into a small Wi-Fi host for the Printrbot pen plotter. It accepts already-reviewed G-code, stores it in LittleFS, sends one command at a time to Marlin UART1, waits for `ok`, and reports progress to a browser.

It does **not** render fonts, trace images, or plan drawing geometry. Those jobs remain in the Python application, where preview and G-code share the same final machine-space paths.

## Current local-bridge features

- Setup access point at `192.168.4.1`.
- Optional station-mode connection saved in ESP32 Preferences.
- Captive-portal redirects and `printrbot.local` mDNS.
- GPIO6 RX / GPIO7 TX UART at 115200 baud.
- Multipart G-code upload streamed to LittleFS.
- 512 KiB job limit and 100,000-command limit.
- Full-file validation before motion is enabled.
- Blocking for heaters, extrusion, tool changes, embedded `M112`, and `E`-axis motion.
- One active hardware job at a time.
- The bridge injects a full `G28` and `M400` before every job, even when the uploaded G-code omits homing.
- Command-by-command Marlin acknowledgement.
- Ready, running, paused, cancelling, cancelled, completed, failed, and emergency states.
- Orderly cancellation using `M400`, calibrated pen-up Z, then `M400`.
- Separate immediate `M112` emergency-stop endpoint.
- Non-moving `M115`, `M119`, `M114`, and `M503` query endpoint.
- Live browser status, progress, active command, and UART ring log.
- Onboard RGB state indicator.
- Native protocol tests and ESP32-C3 compilation in CI.

## Build

Install PlatformIO, then run from this directory:

```bash
pio run -e esp32-c3-devkitc-02
```

The board target is the official PlatformIO identifier `esp32-c3-devkitc-02`.

## Flash over USB

Disconnect external 5 V from the ESP32 before connecting its USB cable.

```bash
pio run -e esp32-c3-devkitc-02 -t upload
```

If automatic bootloader entry fails, hold **BOOT**, press and release **RESET**, release **BOOT**, then retry.

Open the USB debug monitor:

```bash
pio device monitor -b 115200
```

## First standalone test

The Printrboard UART does not need to be connected for the first Wi-Fi test.

1. Power the ESP32 from USB only.
2. Connect a phone or computer to `Printrbot-Bridge`.
3. Use password `plotter123`.
4. Open `http://192.168.4.1`.
5. Confirm that the dashboard loads and the bridge reports `no response yet` for Marlin.

## UART wiring

Do not connect the UART until a proper 5 V↔3.3 V translator is installed.

```text
Printrboard EXP1 pin 7, TX1
  → translator high side
  → translator low side
  → ESP32 GPIO6, RX

ESP32 GPIO7, TX
  → translator low side
  → translator high side
  → Printrboard EXP1 pin 5, RX1

Printrboard EXP1 pin 14 GND ↔ ESP32 GND ↔ translator GND
Printrboard 5 V → translator HV/VCCB
ESP32 3V3 → translator LV/VCCA
```

Power the ESP32 through exactly one method at a time. During USB programming, disconnect external 5 V. For final installation, use regulated 5 V into the ESP32 `5V` pin.

## Native protocol tests

```bash
pio test -e native
```

These tests verify that normal X/Y/Z plotter commands are accepted while heater, extrusion, tool-change, embedded emergency-stop, and unauthorized query commands are rejected.

## Browser workflow

1. Generate and inspect SVG/G-code using the Python application.
2. Run an air plot whenever the machine, paper origin, pen, or Z height has changed.
3. Upload the reviewed `.gcode` file.
4. Wait for the `ready` state.
5. Start the job.
6. Use pause/resume between acknowledged commands.
7. Use orderly cancel for a normal stop.
8. Use emergency stop only for an immediate safety event.

## LED states

```text
Blue       validated job ready
Green      job running
Amber      paused or cancelling
Cyan       job completed
Red        failed or emergency stopped
Purple     idle / waiting for Marlin
```

## Deployment boundary

This is a local controller, not an internet-facing appliance. The access point has WPA2 credentials, but individual HTTP API requests are not authenticated. Keep it on a trusted local network and do not expose it through port forwarding, a public tunnel, or an untrusted LAN.

Firmware updates are USB-only. OTA updates, signed firmware, credential rotation, and hardened provisioning are intentionally not claimed by this release.

## Source references

- ESP32-C3-DevKitC-02 board and power documentation: https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32c3/esp32-c3-devkitc-02/user_guide.html
- Arduino-ESP32 Wi-Fi AP/STA API: https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html
- PlatformIO ESP32-C3-DevKitC-02 board target: https://docs.platformio.org/en/stable/boards/espressif32/esp32-c3-devkitc-02.html
- PlatformIO Espressif 32 release used here: https://github.com/platformio/platform-espressif32/releases/tag/v7.0.1
- Marlin serial configuration: https://marlinfw.org/docs/setting/serial.html

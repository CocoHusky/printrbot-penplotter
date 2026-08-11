# ESP32 Local Bridge

> Historical release note. Consult `firmware/esp32/README.md` and
> `docs/ESP32_API.md` for supported bridge behavior.

The ESP32-C3 bridge moves reviewed G-code between the Python application and the Printrboard. It is a transport and job-control layer only: it does not render text, trace images, create paths, or replace Marlin's motion planner.

## Supported workflow

1. Generate and inspect the drawing in the Python application.
2. Load a `.gcode` file or paste it into the bridge's editable draft field.
3. Review the bed preview and move the whole drawing by dragging its red print-area box or entering an exact X/Y placement.
4. Validate and store the final G-code.
5. Start the ready job explicitly.
6. Monitor acknowledgement-based progress; pause, resume, or orderly-cancel only between acknowledged commands.
7. Use `M112` only for an immediate safety event, then reset the Printrboard before continuing.

The bridge injects a full `G28`/`M400` pre-job sequence before every stored job. Uploaded jobs are still validated for safe motion and safe ending behavior.

## Implemented controls

- ESP32-C3-DevKitC-02 firmware with GPIO6 RX / GPIO7 TX at 115200 baud.
- Setup access point, optional station mode, and `printrbot.local` mDNS.
- LittleFS draft and validated-job storage with a 512 KiB/100,000-command limit.
- Full-file safety validation that blocks heater, extrusion, tool-change, filament, embedded emergency-stop, and E-axis commands.
- One active hardware job at a time, with acknowledgement-gated command forwarding.
- Ready, running, paused, cancelling, cancelled, completed, failed, and emergency states.
- Browser placement preview, drawing/travel speed inputs, final validation, job controls, and non-moving status queries.
- Native protocol tests and an ESP32-C3 build in CI.

## Deployment requirements

- Use a proper fixed-direction 3.3 V/5 V UART level translator; ESP32 GPIO pins are not 5 V tolerant.
- Run non-moving queries and an air plot after any change to wiring, machine origin, pen, paper, or Z calibration.
- Verify homing direction, limits, paper placement, and pen-up height on the physical machine before a pen-down job.
- Keep the bridge on a trusted local network.

## Security boundaries

- HTTP Basic authentication protects the dashboard and every API request. The
  first-boot password is generated on-device, stored in Preferences, and
  printed to the USB serial monitor.
- No public-internet deployment support.
- No OTA or signed firmware updates; updates are installed over USB.
- No automatic resume after reset, power loss, or emergency stop.

Those limits are safety boundaries, not hidden capabilities. The full endpoint contract is in [`ESP32_API.md`](ESP32_API.md); hardware wiring and electrical checks are in [`ESP32_BRIDGE_HARDWARE.md`](ESP32_BRIDGE_HARDWARE.md).
